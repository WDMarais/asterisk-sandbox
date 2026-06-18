# Dashboard — stack notes

> **Status: exploratory (sandbox).** Decisions captured here so they aren't lost
> while we figure out what we actually want. Deliberately *not* spec'd yet — skipping
> the case-interviewer → contract → harness flow until the scope firms up.

## Intent

A single lightweight page on `pbx.wdmarais.dev`, served by the existing FastAPI app,
showing two things:

- **Live call/agent state** — the browser-side consumer of the existing `/events` SSE
  stream (`snapshot` + `agent_state_changed`).
- **Instance health** — disk, load, memory, service status, so the box can be glanced
  at without SSHing in (a poor-man's stand-in for the deferred CloudWatch disk alarm).

Presentation only — no changes to `ami.py` / `parsing.py`, just new routes. Building it
also exercises the `/events` contract for real.

## Stack

- **Serving**: `GET /` → `HTMLResponse`, one self-contained page (inline CSS + JS).
  Promote to a Jinja template only if it outgrows a single file.
- **Transport split** (the two halves want different transport):
  - call state → SSE via `EventSource('/events')` — event-driven, already exists.
  - health → `GET /stats` JSON, polled every 5–10s from the page — a periodic snapshot,
    no need to force it through SSE.
- **Health gathering** (cheap, mostly in-process — no shell where avoidable):
  - disk: `shutil.disk_usage('/')` (no `df` subprocess)
  - load: `os.getloadavg()`; memory: parse `/proc/meminfo`
  - services: `systemctl is-active asterisk asterisk-fastapi nginx` via `subprocess`
    with an arg list — never `shell=True`; fixed args, no request input, so safe.
  - `du`: expensive (walks the tree) — omit, or cache a per-dir breakdown on a timer.
    `disk_usage` alone answers "is the disk filling".
- **Styling**: hand-rolled CSS, inline. A small token layer via CSS custom properties at
  `:root` (`--bg/--fg/--accent/--ok/--warn/--gap`), system font stack, CSS grid for the
  cards, colored status dots, optional dark mode via `@media (prefers-color-scheme: dark)`.
  - *Rejected Tailwind*: needs a Node/PostCSS build step (a JS toolchain bolted onto a
    zero-build Python repo), and the no-build escape hatch (Play CDN) is non-prod + an
    external runtime dependency — both against the repo's self-contained character.
  - *Rejected classless CSS*: styles bare elements globally (action-at-a-distance), and
    customizing means fighting its globals — less legible than CSS we wrote ourselves.
    At this page size a framework earns very little.
- **Auth**: nginx HTTP basic auth covering `/`, `/events`, `/calls`, `/stats` uniformly —
  no app-side auth code. A shared token is the alternative if we want to skip the prompt.
- **Dependencies**: zero external, no CDN. Self-contained, matching the rest of the repo.

## Still to figure out (pre-spec)

- Exact health metrics, and whether a `du` per-directory breakdown is worth the cost.
- Refresh cadence; current-state-only vs any trend/history (likely current-only for now).
- Call view: agent states only, or per-endpoint call detail too.
- Final auth: basic auth vs shared token.
- When scope settles: run it through case-interviewer → contract → harness like the rest
  of the system, rather than leaving it ad hoc.
