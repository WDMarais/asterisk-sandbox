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

### Config files
Selective symlinks — only files managed in this repo are linked. The rest of
`/etc/asterisk` (modules.conf, logger.conf, etc.) is left as installed by apt.

```bash
./scripts/link-configs.sh
sudo asterisk -rx "core reload"
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

### Provisioning script
`setup.sh` — idempotent, runs on a fresh Ubuntu/Debian VPS:
- Install Asterisk from packages
- Copy config files from repo
- Generate TLS cert (Let's Encrypt via certbot, or self-signed for dev)
- Enable and start asterisk service

### TLS / WebSocket
- WSS requires TLS. Self-signed is fine for local dev.
- On a public VPS: Let's Encrypt via certbot — free, auto-renewing.
- WebRTC from a browser to a remote host needs STUN at minimum.
  TURN only required if behind symmetric NAT — test without it first.
  Coturn is the standard open-source TURN server if needed.
