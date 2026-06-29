# ADR 0001: Softphone ↔ broker API auth and CORS

- **Status:** Proposed
- **Date:** 2026-06-29
- **Context this serves:** the browser softphone (separate repo, Phase 2) needs to
  call the broker API (`POST /originate`, `GET /events`, `GET /calls`) from a web
  origin. Today those endpoints are unauthenticated and the API sends no CORS
  headers. Before the outbound-call slice lands we need a deliberate trust model,
  not an incidental one.

---

## Context

A WebRTC softphone touches the PBX over **two independent channels**:

1. **SIP signalling + media** — SIP.js registers an extension over `wss://.../ws`
   and exchanges RTP directly with Asterisk. This is *not* subject to CORS and is
   already proven live (6003 registers). Out of scope for this ADR except where the
   identity model converges (see "Future: one login, two channels").
2. **The broker HTTP API** — click-to-call (`/originate`), the live-events SSE
   stream (`/events`), and the call list (`/calls`). This is what we secure here.

The likely production topology is **not** same-origin. We expect a phone app on
`phone.<domain>` (or a client's own domain) talking to a PBX API on `pbx.<domain>`.
So cross-origin is the steady state, and CORS is a permanent concern rather than a
dev-only nuisance.

### Three gates, kept separate

Conflating these is the usual failure mode. They answer different questions and are
enforced in different places:

| Gate      | Question                                            | Enforced by | Unit of trust              |
|-----------|-----------------------------------------------------|-------------|----------------------------|
| **CORS**  | which *web app* may make a browser issue this call  | the browser | an **origin**              |
| **AuthN** | who is this caller, really                          | the API     | a **token**                |
| **AuthZ** | may this caller originate from ext N / read events  | the API     | a **claim** (tenant + ext) |

Two facts drive the whole design:

- The browser stamps the `Origin` header itself and JS **cannot forge it** (it is a
  forbidden header). So an allowlist of origins is genuinely meaningful *for browser
  traffic* — a page on `evil.com` cannot claim to be `phone.<domain>`.
- But a **non-browser** client (curl, a script) can send any `Origin`, or none.
  CORS therefore protects *browser users*; it is **not** server authentication and
  can never be the thing that guards `/originate`.

Conclusion: CORS and a caller token are complementary and both required.

---

## Decision

### 1. Authenticate the caller with a short-lived, extension-scoped bearer token

A JWT carrying tenant + extension claims:

```jsonc
{ "tenant": "client1", "ext": "6003", "scope": "originate events",
  "exp": <now+15min>, "iss": "auth.<domain>" }
```

- **Signed** with a per-tenant key (HS256 shared secret to start; RS256 later if we
  want the PBX to verify without holding the signing secret).
- **Validated** on every protected request: signature ok → not expired → `ext`
  belongs to this tenant. One FastAPI dependency, applied to `/originate`,
  `/calls`, `/events`.
- **`/originate` additionally enforces `req.agent == token.ext`** — you may only
  originate *from* the extension you are. This single check is what stops a valid
  6003 token from originating as 6001.

### 2. Carry the same token on the SSE stream — switch `/events` off `EventSource`

The browser `EventSource` API **cannot set an `Authorization` header**; it sends
only cookies. Rather than run two auth mechanisms, the softphone consumes `/events`
via `fetch()` + `ReadableStream`, which carries the bearer header like any other
call. (Rejected alternatives: token in query string — leaks into nginx logs and
`Referer`; cookie auth — forces `SameSite=None; Secure` + credentialed CORS in the
cross-origin case. Either is workable but splits the mechanism.)

### 3. CORS as a dynamic allowlist, never `*`

A CORS middleware reflects the request `Origin` back **only if** it appears in the
set of trusted app origins. No wildcard. Single origin from config today; registry-
driven later (see deployment models).

### 4. A registry is the shared source of truth for both gates

One record per tenant:

```yaml
client1:
  app_origins: [https://phone.client1.example.com]   # → CORS allowlist
  extensions:  [6001, 6002, 6003]                     # → authZ
  signing_key: <per-tenant secret>                    # → token verification
```

Both the CORS middleware (`Origin ∈ app_origins`) and the auth dependency
(`ext ∈ extensions`, verify against `signing_key`) read from it. In single-tenant
deployments this degenerates to a few env vars; the **validation code is identical**
whether the registry is one env var or a real table — which is what lets us ship
single-tenant now and add multi-tenant later without touching the gates.

### 5. The browser never holds the long-lived signing secret

Token issuance lives behind a login: the phone app's backend (or a PBX `/auth/login`
endpoint) exchanges operator credentials for a **short-lived, extension-scoped
token**. The per-tenant signing secret stays server-side.

---

## Deployment models this supports

Both are expressible without code changes to the gates — only the registry backing
changes.

**Model A — co-located, same origin** (`client1.example.com/phone` + `/api`):
- CORS: none needed (same origin).
- Auth: still required (curl bypass). Cookie auth is comfortable here.
- Registry: degenerate — one tenant, env vars.
- Trade: simplest; one cert; hard tenant isolation (one box per client). But app and
  PBX scale together and the phone UI can't live on a separate CDN.

**Model B — split hosts + registry** (`pbx1.example.com` trusts `phone1.example.com`):
- CORS: dynamic allowlist from the registry.
- Auth: bearer token (cross-origin → `fetch`-streamed SSE per decision 2).
- Registry: real — the association table is the product's tenancy model.
- Trade: independent scaling, shareable/CDN'd phone UI, many-to-one fan-in. Cost:
  registry + token issuance + dynamic CORS become things we operate.

---

## Consequences

- Single-tenant can ship now: bearer dependency + `agent == ext` check + a one-origin
  CORS allowlist from settings. Multi-tenant slots in by swapping the registry
  backing, not the validation logic.
- The softphone's `/events` consumer must move from `EventSource` to `fetch`
  streaming. Coordinate this with the Phase 2 outbound-call slice.
- Tokens are short-lived, so issuance/refresh must exist before this is usable — a
  login/refresh endpoint is now in scope for the softphone work, not optional.
- `/originate` gains a hard coupling: the token's `ext` must match the requested
  agent. The existing endpoint signature (`{agent, destination}`) is unchanged; only
  a guard is added.
- SIP credentials remain a separately provisioned browser secret for now. The
  convergence below is deliberately deferred.

### Future: one login, two channels

End-state is a single operator login that returns **both** the SIP credentials (to
register over wss) and the API token (to originate / subscribe) — one identity
backing both the media and control planes. Out of scope here; noted so the token
issuance endpoint is designed to grow into it rather than be replaced.

---

## Status / next step

Proposed, not yet implemented. Minimal first implementation, in order:

1. Bearer-token dependency on `/originate`, `/calls`, `/events`, with `agent == ext`.
2. Softphone `/events` consumer → `fetch` + `ReadableStream` carrying the bearer.
3. CORS middleware reading a one-origin allowlist from `settings`, registry-shaped
   so multi-tenant is a later backing swap.
