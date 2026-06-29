# PBX API contract experiment

## Problem

Most PBX integrations accumulate inline knowledge: the consumer ends up encoding
assumptions about dialplan context names, channel string formats, CDR schema column
names, and internal device state representations directly in application code. When
the PBX changes — or when a different PBX is introduced — there is no single place
to update. The breakage is silent and diffuse.

The anti-pattern has a name: **Primitive Obsession**. Bare strings carrying domain
meaning (channel identity, call origin, device state) scattered across callsites
instead of owned by named abstractions. The secondary consequence is **Shotgun
Surgery** — a single PBX configuration change requires hunting down and patching
many unrelated files.

The goal of this experiment is to invert that: build the integration from the
documented Asterisk/PJSIP standard up, define the contract the consumer relies on
explicitly, and keep all PBX-format knowledge in one place. If the contract holds,
the application above it doesn't care what's on the other side.

## Scope

This document covers the *consumer* side only. No assumptions about any specific
PBX deployment. All design decisions trace to public Asterisk/PJSIP documentation
or RFC, not to observed behaviour.

---

## Integration surfaces

A clean AMI integration has three surfaces:

1. **AMI socket** — outbound commands (actions), inbound events
2. **HTTP webhooks** — PBX POSTs state change events to the consumer
3. **JS SIP UA** — browser-side softphone (SIP over WebSocket)

A fourth surface — direct DB access for CDR/CSAT — is an anti-pattern and
explicitly out of scope here. If call records are needed, the PBX should expose
them via an API endpoint or push them via webhook.

---

## AMI contract

### What the standard guarantees

From Asterisk AMI docs:

- **Channel format**: structured, technology-prefixed strings with documented parsing rules — consult `doc/AMI.txt` and PJSIP module docs
- **Device state values**: a finite documented enum in `include/asterisk/devicestate.h` — stable across versions; derive the enum from there, not from observed strings
- **AMI action names**: stable public API; version-specific deprecations are documented in the Asterisk changelog
- **Event field names**: Title-Case, consistent within a given event type

### What is NOT guaranteed

- Dialplan context names — entirely internal to the deployment; must not be hardcoded in the consumer
- CDR field values populated by dialplan (userfield, linkedid conventions) — deployment-specific
- Any string that encodes deployment topology rather than Asterisk standard behaviour

### AMI actions to cover

| Action | Purpose | Key response fields |
|---|---|---|
| `PJSIPShowEndpoint` | Device state + registration for one endpoint | `DeviceState`, `Status` |
| `DeviceStateList` | Bulk device state snapshot | `Device`, `State` per event |
| `QueueStatus` | Queue membership + member state | `QueueMember` events |
| `QueueAdd` / `QueueRemove` | Manage queue membership | Success/Error response |
| `Originate` | Initiate a call | `OriginateResponse` event |
| `Setvar` | Set channel/global variable | (async, no response) |

### Typed domain events

Raw AMI events should map to typed domain events before reaching application code:

```
RawAMIEvent
  → parse_channel(event.Channel) → ChannelID(technology, endpoint, unique_id)
  → parse_device_state(event.State) → DeviceState(enum)
  → classify_call_origin(event) → CallOrigin(queue | internal | external | unknown)
```

`classify_call_origin` must operate only on information AMI guarantees — not on
dialplan context names. If origin can't be determined from standard fields, the
result is `unknown`, not a silent misclassification.

---

## Server-side parsing library

Single module. All channel/device string knowledge lives here; zero imports from
application code. Public interface:

Abstractions to own here — look up the documented types and derive names from first principles:

- Channel identity: technology, endpoint name, unique ID — parsed from the documented channel string format
- Device state: typed enum derived from `devicestate.h`, not compared as raw strings anywhere outside this module
- Registration state: derivable from device state per the docs — the consumer shouldn't need a separate field
- Call origin: what can be determined from *standard* AMI fields alone, without dialplan context names; if it can't be determined, the result is `unknown`, not a silent guess
- Event type: typed enum covering the AMI events the integration handles

**Design rule**: no function here takes a context name, userfield value, or deployment-specific string as input. Those are deployment concerns; this module knows only what the Asterisk docs say.

**Test approach**: failing tests as the spec. Write assertions against documented behaviour first — derive the concrete values from the Asterisk docs, not from an existing implementation. The tests *are* the contract documentation.

---

## JS SIP UA

Browser-side softphone over SIP/WebSocket (RFC 7118). Use a current version of
JsSIP or SIP.js — older vendored versions carry Asterisk-specific workaround flags
(`hackIpInContact`, `hackWssInTransport`) that may not exist in current releases
and whose necessity should be verified against the standard before carrying forward.

The JS side has its own equivalent of the parsing problem. Custom SIP headers
(`X-Queue`, `X-Uniqueid`, `X-Linkedid`, and others) are commonly used to pass
call metadata through the PBX to the browser. If these are deployment-specific
inventions rather than standard headers, the browser-side code that parses them
has the same coupling smell as the server-side AMI conditionals — format knowledge
scattered across callsites. A clean design owns all header parsing in one place
and exposes typed values, same principle as the server-side library.

Key states to cover:
- Registration: registered / unregistered / registering / failed
- Call: idle / ringing-out / ringing-in / connected / held / transferring
- Presence: DND / offline / available
- The JS state machine and the server-side AMI integration should converge on
  the same vocabulary — if the server says `UNAVAILABLE`, the JS side should
  have a named state that maps to it

Asterisk WebSocket endpoint: `wss://<host>:8089/ws` (port 8089, SIP subprotocol).
The container config needs `res_http_websocket` loaded, `bindport=8089`, and TLS
enabled in `http.conf`.

---

## Container setup

`pbx_dev.sh up/down/reset/status` — podman (docker-compatible).

Minimal Asterisk config for the experiment:
- `pjsip.conf`: N test endpoints with credentials
- `extensions.conf`: inbound routing, queue context, DND contexts
- `queues.conf`: one test queue
- AMI enabled on 127.0.0.1:5038 with a test user
- WebSocket enabled for JS UA (port 8088/wss)

The config should be committed alongside the harness so the container state is
fully reproducible from scratch.

---

## Integration test harness

End-to-end assertions against the local container:

1. Start container → register two softphone extensions
2. Assert `DeviceState.NOT_INUSE` for both via `PJSIPShowEndpoint`
3. Originate a call from ext A to ext B → assert `DeviceState.RINGING` on B
4. Answer → assert `DeviceState.INUSE` on both
5. Hangup → assert `DeviceState.NOT_INUSE` on both
6. Set DND on A → assert correct device state reflects it
7. Set offline on A → assert `DeviceState.UNAVAILABLE`

These are assertions on the *contract*, not on the implementation. If they hold
against the local container and also hold against a real deployment, the
integration is portable.

---

## Reference: what a clean integration looks like

Twilio SMS is the counter-example worth keeping in mind. It uses a versioned REST
SDK, webhook payloads with documented field names, no DB access, no internal schema
knowledge. The consumer only needs credentials and a callback URL. Any change on
Twilio's side that would break the integration is a documented API version change —
not a silent dialplan or schema rename. The goal of this experiment is to build
toward that model for the AMI/SIP surface.

---

## What this experiment produces

1. A container config that runs standard Asterisk/PJSIP locally
2. A server-side parsing library with a documented, tested contract
3. A JS UA client with equivalent typed state
4. An end-to-end harness that asserts the contract
5. A list of questions for any PBX operator: "our integration relies on X, Y, Z
   from the standard — do you diverge from any of these?"

---

## Related decisions (ADRs)

- [ADR 0001](adr-0001-softphone-api-auth-and-cors.md) — how the browser softphone
  authenticates to the broker API (`/originate`, `/events`, `/calls`) and the CORS
  trust model. Separates the three gates (CORS / authN / authZ), proposes
  short-lived extension-scoped bearer tokens, and shows how single-tenant grows into
  a multi-tenant origin registry.
