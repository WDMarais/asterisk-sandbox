# Setup Notes

## WSL gotchas
- WSL IP resets on restart — check with `ip addr show eth0`
- Current IP when this was written: 172.28.128.67

## Asterisk install
```bash
sudo apt update && sudo apt install asterisk -y
```

## Config files
Selective symlinks — only files managed in this repo are linked. The rest of
/etc/asterisk (modules.conf, logger.conf, etc.) is left as installed by apt.

```bash
./scripts/link-configs.sh
sudo asterisk -rx "core reload"
```

To add a new config file to the repo: create it in `asterisk/`, add its name
to the `files` array in `scripts/link-configs.sh`, then re-run the script.

## Useful CLI commands
```bash
sudo asterisk -rvvv                    # connect to running instance
sudo asterisk -rx "core show version"  # one-shot command
sudo asterisk -rx "pjsip show endpoints"
sudo asterisk -rx "pjsip show registrations"
sudo asterisk -rx "core reload"
```

## Softphone (Zoiper5)
- Server: <WSL IP>
- Port: 5060
- Username: 6001 / Password: pass6001
- Username: 6002 / Password: pass6002
