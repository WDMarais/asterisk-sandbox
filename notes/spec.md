# asterisk-sandbox: behavioural spec

Generated via case-interviewer session, 2026-06-14.
Seed: `notes/contract.md`. Two subsystems: server-side parsing library, JS SIP UA state machine.

---

## 1. Server-side parsing library

Single module. Zero imports from application code. All PBX string knowledge lives here.
Pure functions — no logging, no side effects. Returns typed results; caller logs unknowns.

### 1.1 Channel string parsing — `parse_channel(raw: str)`

Parses a raw AMI `Channel` field value into a typed struct.

**Happy path**

```
parse_channel("PJSIP/6001-0000000a")
  → { technology: PJSIP, endpoint: "6001", unique_id: "0000000a" }

parse_channel("SIP/6001-0000000a")
  → { technology: SIP, endpoint: "6001", unique_id: "0000000a" }
  # same format as PJSIP; SIP concession costs nothing, legacy endpoints may exist

parse_channel("Local/6001@from-internal-0000000a;1")
  → { technology: LOCAL, endpoint: "6001@from-internal", unique_id: "0000000a", leg: 1 }
  # routing artifact — consumer discards and logs, does not update agent state

parse_channel("Local/6001@from-internal-0000000a;2")
  → { technology: LOCAL, endpoint: "6001@from-internal", unique_id: "0000000a", leg: 2 }
```

**Error cases**

```
parse_channel("PJSIP/6001")
  → { technology: PJSIP, error: MALFORMED_PARAMS, raw: "PJSIP/6001" }
  # recognised technology, missing unique_id suffix — structural violation

parse_channel("DAHDI/1-0000000a")
  → { technology: UNKNOWN_TECH, raw: "DAHDI/1-0000000a" }
  # unknown technology prefix but valid channel string structure

parse_channel("notavalidstring")
  → { technology: INSCRUTABLE, raw: "notavalidstring" }
  # no resemblance to channel string format — no slash, no recognisable structure

parse_channel("")
  → { technology: INSCRUTABLE, raw: "" }
```

**Consumer responsibilities for non-PJSIP results**

| Result type | Consumer action |
|---|---|
| `LOCAL` | Discard; log as "routing artifact" with raw string |
| `MALFORMED_PARAMS` | Log with raw string; do not update agent state |
| `UNKNOWN_TECH` | Log with raw string; do not update agent state |
| `INSCRUTABLE` | Log with raw string; do not update agent state |

Logged entries should be aggregable (count by type, by raw prefix) for observability.

### 1.2 Device state parsing — `parse_device_state(raw: str)`

Parses a raw AMI device state string into a typed enum. Values derived from `devicestate.h`.

**Happy path — documented enum values**

```
parse_device_state("NOT_INUSE")   → DeviceState.NOT_INUSE
parse_device_state("INUSE")       → DeviceState.INUSE
parse_device_state("RINGING")     → DeviceState.RINGING
parse_device_state("RINGINUSE")   → DeviceState.RINGINUSE   # preserve; don't collapse to INUSE
parse_device_state("ONHOLD")      → DeviceState.ONHOLD      # first-class state; hold metrics tracked above this layer
parse_device_state("UNAVAILABLE") → DeviceState.UNAVAILABLE
parse_device_state("BUSY")        → DeviceState.BUSY        # endpoint-level busy; rare in PJSIP
parse_device_state("INVALID")     → DeviceState.INVALID
```

**Error cases**

```
parse_device_state("CUSTOM_THING") → { state: UNKNOWN, raw: "CUSTOM_THING" }
parse_device_state("")             → { state: UNKNOWN, raw: "" }
# consumer logs both; raw string preserved for aggregation
```

**Registration state derivation**

Registration state is derived from device state — no separate field needed:

```
DeviceState.UNAVAILABLE → RegistrationState.UNREGISTERED
any other DeviceState   → RegistrationState.REGISTERED
```

### 1.3 Agent combined state and FSM

Presence (Online/DND/Offline) and call state (Idle/Ringing/In-call/On-hold) are tracked
as a single flat enum of valid combinations. Illegal combinations are unrepresentable.

**Valid combined states**

```
AVAILABLE      — idle, queue not paused (NOT_INUSE + unpaused)
RINGING_IN     — incoming call ringing
RINGING_OUT    — outgoing call ringing
IN_CALL        — connected (INUSE)
ON_HOLD        — call on hold (ONHOLD)
DND            — at desk, queue paused, no active call
DND_IN_CALL    — agent set DND during a call; auto-transitions to DND when call ends
DND_ON_HOLD    — DND set while call is on hold
OFFLINE        — not registered (UNAVAILABLE)
```

**FSM transitions — explicit allowed set**

```
AVAILABLE    → RINGING_IN    # incoming call
AVAILABLE    → RINGING_OUT   # agent initiates call
AVAILABLE    → DND           # agent sets DND
AVAILABLE    → OFFLINE       # agent closes browser (SIP reg expires)
RINGING_IN   → IN_CALL       # answered
RINGING_IN   → AVAILABLE     # missed / rejected
RINGING_OUT  → IN_CALL       # remote answered
RINGING_OUT  → AVAILABLE     # no answer / cancelled
IN_CALL      → ON_HOLD       # agent puts caller on hold
IN_CALL      → AVAILABLE     # call ended
IN_CALL      → DND_IN_CALL   # agent sets DND mid-call
ON_HOLD      → IN_CALL       # agent resumes
ON_HOLD      → AVAILABLE     # call ended while on hold
ON_HOLD      → DND_ON_HOLD   # agent sets DND while on hold
DND          → AVAILABLE     # agent clears DND
DND          → OFFLINE       # agent closes browser
DND_IN_CALL  → DND           # call ends; auto-transitions (no re-prompt)
DND_ON_HOLD  → DND_IN_CALL   # agent resumes held call
DND_ON_HOLD  → DND           # call ended while on hold
OFFLINE      → AVAILABLE     # agent opens browser, SIP registers
```

**Explicitly blocked transitions**

```
IN_CALL  → OFFLINE   # REJECTED — button hidden in UI; API returns error
ON_HOLD  → OFFLINE   # REJECTED — same rule
```

**DND_IN_CALL → DND auto-transition rationale**: agent made explicit intent during the call;
DND is low-cost to undo (one click); re-prompting adds friction to a valid workflow.
If post-call DND abandonment becomes a measured problem, add re-prompt at that point.

### 1.4 Call origin classification — `classify_call_origin(events, is_server_originated, known_endpoints)`

Classifies a call's origin from its accumulated AMI event sequence.
Pure function — no deployment string knowledge hardcoded; `known_endpoints` is injected config.

```
classify_call_origin(events=[OriginateResponse(...)], is_server_originated=True, ...)
  → CallOrigin.OUTBOUND
  # is_server_originated flag is authoritative; takes priority over all other signals

classify_call_origin(events=[], is_server_originated=True, ...)
  → CallOrigin.UNKNOWN
  # flag set but no confirming event yet — defer; failed originates must not be classified

classify_call_origin(events=[QueueCallerJoin(Queue="support"), ...], is_server_originated=False, ...)
  → CallOrigin.QUEUE
  # Queue field present on any event in sequence

classify_call_origin(events=[...], is_server_originated=False, known_endpoints={"6001","6002"})
  where CallerIDNum ∈ known_endpoints AND destination ∈ known_endpoints
  → CallOrigin.INTERNAL

classify_call_origin(events=[...], is_server_originated=False, known_endpoints={"6001","6002"})
  where CallerIDNum or destination ∉ known_endpoints, no queue events
  → CallOrigin.UNKNOWN
  # not a silent guess; explicit unknown preferred over wrong classification
```

### 1.5 AMI event field-level error cases

Connection drops and action timeouts are owned by the AMI client layer, not the library.
Authentication is verified before events reach the library. The library owns field-level parsing only.

```
parse_channel(None or missing field)
  → { technology: INSCRUTABLE, raw: "" }     # same rule as empty string

parse_device_state(None or missing field)
  → { state: UNKNOWN, raw: "" }              # same rule

Hangup event, Channel missing, Uniqueid present
  → parse proceeds using Uniqueid for correlation
  # Uniqueid is the primary call correlator; Channel is redundant here

Hangup event, Channel missing AND Uniqueid missing
  → { error: MALFORMED, event_type: "Hangup", raw: <full event dict> }
  # identity unresolvable; full event preserved for logging

AgentCalled event, Queue field missing, Uniqueid present
  → parse proceeds; classify_call_origin receives no Queue signal
  → CallOrigin.UNKNOWN for this event

UnknownEventType received (event type not in handled enum)
  → { error: UNHANDLED_EVENT_TYPE, raw: <full event dict> }
  # distinct from MALFORMED: expected and ignorable, but logged separately
  # MALFORMED = structurally broken; UNHANDLED = out of scope
```

**Inference rule**: if an event is missing a "required" field but the call can be
unambiguously identified from remaining fields (Uniqueid sufficient), proceed and
surface the missing field as a warning. Only return MALFORMED when identity is
unresolvable.

---

## 2. JS SIP UA state machine

Browser-side softphone over SIP/WebSocket (JsSIP or SIP.js current version).
All SIP header parsing in one module — typed output, no raw header access outside it.
State machine drives the combined agent state enum defined in §1.3.

### 2.1 Registration transitions

```
Page load, auto-register=true (default)
  OFFLINE → REGISTERING → AVAILABLE

Page load, auto-register=false
  OFFLINE  (stays until agent clicks "Go Online")

Agent clicks "Go Online"
  OFFLINE → REGISTERING → AVAILABLE

Registration fails (SIP 403 / timeout / DNS failure)
  REGISTERING → REGISTRATION_FAILED
  # auto-retry with backoff; agent can manually retry at any point

Registration fails N times (default N=2, configurable)
  → health indicator surfaces alongside REGISTRATION_FAILED
  # health check reports FastAPI server + Asterisk/AMI status separately
  # e.g. "Server: OK, Asterisk: unreachable"

Health check itself fails
  → "Server unreachable" — network/infra issue, not a SIP registration issue

Agent manually retries during REGISTRATION_FAILED
  → REGISTERING immediately, regardless of backoff timer position
```

### 2.2 SIP header parsing — `parse_sip_headers(invite)`

One module owns all SIP header extraction. Typed output. Nothing else touches raw headers.
Headers `X-Queue` and `X-Asterisk-Uniqueid` are injected by Asterisk via dialplan on queue routing.

```
parse_sip_headers(invite) → {
  caller_id: "0821234567",     # From header — RFC 3261 standard
  queue_name: "support",       # X-Queue — dialplan-injected
  unique_id: "0000000a",       # X-Asterisk-Uniqueid — dialplan-injected; correlates with AMI
  linked_id: "0000000b"        # X-Asterisk-Linkedid — informational only in phase 1; no logic
}

parse_sip_headers(invite) where X-Queue missing
  → { ..., queue_name: None, warnings: ["X-Queue missing"] }
  # not fatal; CallerID still shown to agent

parse_sip_headers(invite) where From header missing
  → { ..., caller_id: None, warnings: ["From header missing"] }
  # malformed INVITE — must not crash; surface as warning
```

### 2.3 Outbound call flow

Agent initiates a call from the browser UI.

```
Agent clicks "Call" on a number
  AVAILABLE → RINGING_OUT
  # server sends Originate AMI action; tags unique_id as is_server_originated=True

Remote answers
  RINGING_OUT → IN_CALL

Remote doesn't answer / agent cancels
  RINGING_OUT → AVAILABLE

Originate fails (busy, unreachable)
  RINGING_OUT → AVAILABLE
  # toast: "Call failed — [reason]"
```

### 2.4 Inbound call flow

Answer is browser-only — no hardware trigger or external action in phase 1.
Incoming call notification displays: CallerID + queue name.

```
SIP INVITE arrives (JsSIP newRTCSession, direction=incoming)
  AVAILABLE → RINGING_IN
  # UI shows: CallerID, queue_name from parse_sip_headers

Agent clicks "Answer"
  RINGING_IN → IN_CALL

Agent clicks "Reject" / call times out
  RINGING_IN → AVAILABLE

SIP INVITE arrives while agent is RINGING_IN (second call)
  → rejected automatically; agent state unchanged
  # system prevents RINGINUSE; queue should not route to a ringing agent

SIP INVITE arrives while agent is IN_CALL
  → rejected automatically; agent state unchanged
```

### 2.5 Hold and DND mid-call

```
Agent clicks "Hold" during IN_CALL
  IN_CALL → ON_HOLD
  # hold timer starts; color escalates: neutral → amber (configurable, e.g. 2min)
  #   → red (configurable, e.g. 5min); visible to agent as urgency signal

Agent resumes from hold
  ON_HOLD → IN_CALL
  # hold timer clears

Agent sets DND during IN_CALL
  IN_CALL → DND_IN_CALL
  # secondary indicator: "DND after call" — persistent, not a badge state change
  # agent remains visually IN_CALL; indicator is additive

DND_IN_CALL → DND (call ends, auto-transition)
  → dismissable notification fires: "You are now in DND"
  # requires explicit dismiss; does not auto-fade
  # agent must acknowledge before notification clears

Agent sets DND during ON_HOLD
  ON_HOLD → DND_ON_HOLD
  # same DND indicator applies; hold timer continues
```

### 2.6 Connection loss and recovery

```
WebSocket drops, agent was IN_CALL or ON_HOLD
  → CONNECTION_LOST state, surfaces immediately to agent
  # banner: "Connection lost — reconnecting" (warning severity)
  # auto-reconnect with backoff; on reconnect attempts re-INVITE to re-attach call

WebSocket drops, agent was AVAILABLE (race window)
  → server detects CONNECTION_LOST, immediately issues QueuePause for agent
  → any INVITE that arrived in race window: SIP layer returns 503
  → server detects failed routing, re-queues caller with priority flag
  # caller does not lose queue position due to infrastructure failure
  # priority queue is deployment config concern; contract carries the priority flag

WebSocket reconnects successfully
  → resumes FSM state prior to CONNECTION_LOST
  # toast: "Reconnected"

Reconnect fails N times (default=2, configurable)
  → banner escalates to critical; health indicator surfaces
  # health check: FastAPI server + Asterisk/AMI status reported separately

STUN failure (ICE can't establish audio path)
  IN_CALL → CALL_DEGRADED
  # agent sees: "Call has issues" (non-technical)
  # technical layer logs: STUN_FAILURE with timestamp — metricked, not shown to agent
  # severity=warning (call may still partially work)
```

### 2.7 UI notification layers

Three layers — same pattern as owm dashboard:

| Layer | Type | Examples |
|---|---|---|
| Status badge | Persistent state | AVAILABLE (running) / OFFLINE (stopped) / IN_CALL (running) / DND (stopped) / CALL_DEGRADED (degraded) |
| Banner | Persistent alert, requires resolution | "Connection lost — reconnecting" (warning) / "Registration failed" (critical) |
| Toast | Transient, auto-fades | "Registered", "Reconnecting (attempt 2)…", "Call ended" |
| Dismissable notification | Requires explicit dismiss | "You are now in DND" (DND_IN_CALL → DND transition) |

Health indicator (on banner, after threshold failures): expandable by default collapsed.
Agent sees summary; supervisor/admin expands for Asterisk/server detail.

Non-technical agent messages: "Call has issues", "Connection lost". Technical detail
(STUN_FAILURE, WS_DISCONNECT, ICE_FAILED) is logged and metricked, never shown to agents.

---

## 3. Explicitly deferred (phase 2)

- **Call transfers** — TRANSFERRING FSM state, blind vs attended transfer flows, AMI
  `Redirect` action, linked_id correlation across transfer legs
- **WhatsApp trunk** — separate integration surface (Business API or gateway);
  changes routing model; not started until phase 1 voice is stable
- **Wrap-up state** — post-call agent state before returning to AVAILABLE; wrap-up
  timer, disposition codes; DND_IN_CALL ping on wrap-up entry
- **Supervisor dashboard** — agent grid view, real-time status, hold duration alerts,
  queue depth; same status badge vocabulary as agent UI
- **Hold duration metrics aggregation** — linked_id correlation, per-agent hold
  statistics, Odoo CRM push
- **Priority queue implementation detail** — Asterisk config for caller re-queue
  after failed routing; contract carries priority flag, deployment config decides mechanism

---

## 4. Technology recommendation

### Server-side parsing library

Inputs are well-structured strings with a finite documented grammar. Error taxonomy
is small and enumerable. No ambiguity requiring backtracking or lookahead.
**String splitting with typed result enums is sufficient** — no parser combinators needed.

The value is in the type system: `DeviceState`, `ChannelTechnology`, `CallOrigin`,
and the combined agent state must be unrepresentable as raw strings anywhere outside
the library. Python `enum.Enum` + Pydantic models covers this; Pydantic is already
present (FastAPI stack), zero new dependencies.

### JS SIP UA

JsSIP or SIP.js current version (settled in contract.md). SIP header parsing module
follows the same design: one place, typed output. **TypeScript with a discriminated
union return type** handles all error variants cleanly:

```ts
type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; warnings: string[]; raw: string }
```

### Combined agent state FSM

Flat enum + explicit transition table — small enough to own directly. No state
machine library needed; ownership of the transition table is the point.

Implement as:
- Server: Python `enum` + transition dict; illegal transitions raise at the boundary
- JS: TypeScript discriminated union + event handler; illegal transitions are
  unrepresentable in the type

### Vocabulary convergence

Server `DeviceState` enum values and JS combined state enum share names where they
overlap. Mapping lives in one module per side. No runtime cross-dependency —
the shared vocabulary is a naming convention, not a shared package.

### Summary

| Layer | Language | Key tool |
|---|---|---|
| Server parsing library | Python | `enum.Enum` + Pydantic |
| FastAPI server | Python | FastAPI (existing) |
| JS UA + header parser | TypeScript | Discriminated unions |
| FSM (both sides) | Python / TypeScript | Explicit transition table |

No new frameworks. No latency/throughput constraints surfaced that push toward a
different runtime — a small call centre (handful of concurrent agents) is well
within what a single FastAPI process handles comfortably.
