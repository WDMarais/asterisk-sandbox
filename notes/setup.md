# Setup Notes

## Approach

Direct Asterisk install — no container, no FreePBX. The environment (WSL locally,
VPS for the persistent reference instance) is the reproducible unit; config files
are committed to the repo and the setup is repeatable from scratch.

FreePBX adds a web UI but layers its own config management on top of pjsip.conf
in ways that obscure what's actually happening. For understanding the standard and
building a clean contract, raw Asterisk config files are clearer.

---

## Local (WSL)

### WSL gotchas
- WSL IP resets on restart — check with `ip addr show eth0`

### Install
```bash
sudo apt update && sudo apt install asterisk -y
```

### Secrets

Credentials live in `.env` (gitignored). Copy the template and fill in values:

```bash
cp .env.example .env
# edit .env — set AMI_SECRET to something non-trivial
```

### Generated configs

Some Asterisk config files (`manager.conf`) contain secrets and are generated
from templates rather than symlinked. Run after first setup or any `.env` change:

```bash
sudo bash scripts/render-configs.sh
sudo systemctl restart asterisk
# Verify:
sudo asterisk -rx "manager show users"   # should list asterisk-sandbox
```

On VPS: same steps — `render-configs.sh` reads `.env` from the repo root,
substitutes values via `envsubst`, and writes directly to `/etc/asterisk/`.

### Config files
Selective symlinks — only files managed in this repo are linked. The rest of
`/etc/asterisk` (modules.conf, logger.conf, etc.) is left as installed by apt.

```bash
sudo bash scripts/link-configs.sh
sudo systemctl restart asterisk
```

To add a new config file to the repo: create it in `asterisk/`, add its name
to the `files` array in `scripts/link-configs.sh`, then re-run the script.

### Useful CLI commands
```bash
sudo asterisk -rvvv                    # connect to running instance
sudo asterisk -rx "core show version"  # one-shot command
sudo asterisk -rx "pjsip show endpoints"
sudo asterisk -rx "pjsip show registrations"
sudo asterisk -rx "core reload"
```

### Softphone (Zoiper5)
- Server: `<WSL IP>`
- Port: 5060
- Username: 6001 / Password: pass6001
- Username: 6002 / Password: pass6002

---

## VPS (persistent reference instance)

See `vps.md` for when and why. Setup steps:

### Config files to commit
All minimal, annotated with what each setting does and why:

- `pjsip.conf` — transport (WebSocket + TLS), endpoints with credentials,
  registration settings
- `extensions.conf` — inbound routing, queue context, DND contexts, outbound
  routing; keep minimal and commented
- `queues.conf` — one test queue, member configuration
- `http.conf` — WebSocket module: `bindport=8089`, TLS, `res_http_websocket`
- `manager.conf` — AMI on 127.0.0.1:5038, one user with sufficient permissions
- `modules.conf` — explicit load list; only what's needed

### Provisioning scripts
Split along lifecycle seams, all idempotent and run as the target user (e.g.
`ubuntu`) with passwordless sudo:

- `provision.sh` — one-time host prep: apt packages, uv, repo clone/pull, `.env`,
  and base asterisk + nginx on HTTP. Run once per box.
- `certs.sh` — Let's Encrypt cert for `$DOMAIN`. Needs DNS for `$DOMAIN` already
  pointing at the box (the natural part-1/part-2 boundary). Idempotent; skips if a
  live cert exists, `--force` to re-issue. Ongoing renewal is certbot's own timer.
- `apply-repo.sh` — everything re-appliable on a `git pull`: link + render configs,
  install the systemd service and logrotate, `uv sync`, enable the TLS nginx site,
  then reload nginx + `core reload` asterisk + restart `asterisk-fastapi`. This is
  the redeploy command.
- `setup.sh` — orchestrates `provision.sh` → `certs.sh` → `apply-repo.sh`. If DNS
  for `$DOMAIN` doesn't resolve to this box yet, it provisions, prints the IP to
  point DNS at, and stops cleanly; re-run once DNS is live.

Building blocks `render-configs.sh` (render templates) and `link-configs.sh` (symlink
asterisk confs + perms) are called by `apply-repo.sh`, not run directly in normal use.

Typical flows:
```bash
# fresh box, new domain
bash scripts/provision.sh
# ...point DNS at the printed IP...
bash scripts/certs.sh && bash scripts/apply-repo.sh

# or one-shot when DNS already resolves (e.g. rebuilding on an existing domain)
bash scripts/setup.sh

# redeploy after a code/config change
git pull --ff-only && bash scripts/apply-repo.sh
```

### TLS / WebSocket
- WSS requires TLS. Self-signed is fine for local dev.
- On a public VPS: Let's Encrypt via certbot — free, auto-renewing.
- WebRTC from a browser to a remote host needs STUN at minimum.
  TURN only required if behind symmetric NAT — test without it first.
  Coturn is the standard open-source TURN server if needed.
