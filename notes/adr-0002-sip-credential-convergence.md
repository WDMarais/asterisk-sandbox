# ADR 0002: SIP-credential convergence — one login, two planes

- **Status:** Proposed
- **Date:** 2026-06-29
- **Follows:** [ADR 0001](adr-0001-softphone-api-auth-and-cors.md), which deferred
  this under "Future: one login, two channels."

---

## Context

A WebRTC softphone authenticates over **two independent planes** with two very
different credentials:

| Plane                | Credential today                          | Lifetime    | Issued how                     |
|----------------------|-------------------------------------------|-------------|--------------------------------|
| **Media/signalling** | static SIP password (`SIP_PASS_03`)       | permanent   | baked per-extension at provisioning |
| **Control (API)**    | bearer token (ADR 0001)                   | ~15 min     | minted at login                |

The mismatch is the problem. The SIP secret is a **long-lived secret living in
browser-land**: to register ext 6003 over `wss`, SIP.js needs the password, so today
it ends up in the app's config/bundle. If it leaks, an attacker can register as that
extension and place calls. Internal-only today (6001–6003 + echo) caps the blast
radius — but the moment a PSTN trunk exists this is **toll fraud**, i.e. real money.
fail2ban guards the network layer (brute-force, scanners); it does nothing about an
*exfiltrated valid credential*. That's an application-secret-lifetime problem, and
it's what this ADR addresses.

The goal: **one operator login issues every per-session secret for both planes**, so
a single identity backs media + control, and expiry/logout revokes both together.

### Why this isn't just "use a JWT for SIP too"

PJSIP has no JWT/token registration path. SIP registration authenticates with digest
auth against a `type=auth` section (`auth_type=userpass`). So "short-lived SIP
credential" can't mean "hand Asterisk a JWT" — it means **minting/rotating a real SIP
secret and making Asterisk accept it**. Asterisk reads auth from either:

- the generated flat `pjsip.conf` (what `gen_pjsip.py` produces) — static, needs a
  reload to change; or
- a **realtime backend (ARA / sorcery)** — a DB (e.g. `ps_auths` rows) the auth
  service can write to live, no reload.

Rotation therefore forces an infra decision. That fork is the core of this ADR.

---

## Decision

### 1. The login endpoint becomes the single issuer of all per-session secrets

`POST /auth/login` (operator credentials) returns everything a session needs, for
both planes:

```jsonc
{
  "api_token": "<JWT ~15min, scope=originate events, ext=6003>",   // ADR 0001
  "sip":  { "uri": "...", "ws_server": "wss://.../ws",
            "username": "6003", "password": "<...>", "ttl": <...> },
  "ice":  { "stun": ["..."],
            "turn": [{ "urls": "...", "username": "<ts:uid>",
                       "credential": "<hmac>", "ttl": <...> }] }
}
```

Insight that unifies the design: **all three are per-session secrets**, and a TURN
relay credential is *also* best issued ephemerally (the standard TURN REST scheme —
`username = expiry:userid`, `credential = HMAC(secret, username)`). So the login
endpoint is the one issuer across *both* planes — API token (control), SIP creds
(media auth), ICE/TURN creds (media transport). One identity, three secrets, one
place that mints them. (The TURN half ties to the still-unwritten STUN/TURN audio-
path ADR; cross-reference when that lands.)

### 2. Identity invariant: the extension you register as == the extension your token can act as

ADR 0001 already enforces `req.agent == token.ext` on `/originate`. This ADR adds the
other half: the **SIP `username` and the token `ext` are the same extension, issued
by the same login**. A compromised or expired login invalidates both planes for that
identity — there is no way to hold media authority without matching control authority.

### 3. SIP-credential lifetime: phase it, don't boil the ocean

Two tiers, deliberately sequenced (minimal-first):

**Phase 1 — Just-in-time delivery of existing per-extension creds. (Low infra.)**
- Keep `gen_pjsip.py` and static `auth_type=userpass` in `pjsip.conf`.
- **Stop baking `SIP_PASS_*` into the browser bundle.** The softphone fetches its SIP
  password from the authenticated `/auth/login` and holds it **in memory for the
  session only**.
- Net effect: the secret is no longer a front-end artifact — it's delivered over an
  authenticated channel, just-in-time, and gone on tab close. Big exposure reduction
  for ~no new infrastructure.
- Honest limitation: the credential is still static in Asterisk, so Phase 1 **cannot
  truly revoke it mid-session** — logout drops the registration but the password
  remains valid until manually rotated.

**Phase 2 — Ephemeral SIP creds via PJSIP Realtime (ARA). (Real infra.)**
- Migrate endpoint/auth/aor from the flat file to a writable backend (`ps_auths`
  etc. in a DB).
- `/auth/login` mints a fresh short-lived SIP secret (or ephemeral username) per
  session; logout/expiry **revokes the row** → instant, real revocation.
- Cost: introduces a database + ARA into a stack that is currently flat-file +
  AMI-only. `gen_pjsip.py`'s role shrinks to seeding/transport config.
- Justified when a **PSTN trunk** (toll-fraud exposure) or **real multi-tenant**
  lands — not before.

### 4. Lifetime hierarchy (nested, not equal)

```
session            (long; ends at logout)
  └─ SIP credential (Phase 1: whole session · Phase 2: short, re-minted)
       └─ api_token (~15 min; refreshed within the session)
```

The API token refreshes frequently and independently. The SIP registration re-
registers on its own SIP expiry using the session's SIP credential — it does **not**
rotate on every API-token refresh (that coupling would churn registrations
needlessly). Phase 2's SIP-cred rotation, if added, is its own slower cadence.

---

## Consequences

- Requires the `/auth/login` + refresh endpoint already foreshadowed in ADR 0001 —
  this ADR makes it the issuer for *both* planes, not just the API token.
- **Operator authentication itself is a dependency, not solved here.** Something must
  verify the human (a user store / IdP) before any secret is minted. Out of scope;
  named so it isn't forgotten.
- Phase 1 is shippable alongside the Phase-2 softphone work and the ADR-0001 token
  work: it's a delivery change (env-baked → login-delivered), not an Asterisk change.
- Phase 1 keeps a real gap — no mid-session SIP revocation. Acceptable while
  internal-only; **revisit before any external trunk.**
- Phase 2 is a genuine architectural shift (DB + ARA). Treat it as its own project
  with its own ADR for the realtime schema; this ADR only commits to the *direction*,
  not the table design.
- TURN issuance overlaps the media/NAT work; the login response shape above should be
  agreed jointly with the STUN/TURN audio-path decision so it's designed once.

---

## Status / next step

Proposed. Recommended sequencing:

1. **Now / with ADR-0001 work:** Phase 1 — `/auth/login` returns `api_token` + SIP
   creds; softphone stops bundling `SIP_PASS_*` and holds creds in session memory.
2. **With the audio-path ADR:** fold TURN ephemeral creds into the same login
   response.
3. **Before any PSTN trunk or multi-tenant launch:** Phase 2 — realtime ARA backend,
   ephemeral SIP creds, real revocation. New ADR for the schema.
