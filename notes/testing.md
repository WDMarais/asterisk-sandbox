# PBX integration testing

## Approaches

### SIPp — conformance and load testing

Industry-standard SIP scenario runner. Write a scenario XML file (call, answer,
hangup sequence) and SIPp drives the PBX deterministically without a human on
either end. Useful for:

- Verifying the contract holds against a fresh container
- Regression testing: if a config change breaks a known-good flow, SIPp catches it
- Load testing: can simulate N concurrent calls to find capacity limits

Runs from the command line, no install beyond a single binary. Scenarios are
committed alongside the container config.

### Mock AMI server

A small asyncio server that listens on port 5038 and responds to known AMI actions
with canned responses. Lets you test the server-side parsing library without the
container running at all — analogous to the MariaDB container approach for CDR
testing.

Design: map of action name → response generator. Should be minimal — just enough
to exercise the parsing library's happy path and known edge cases. Not a full AMI
emulator.

### Wireshark + SIP dissector

Capturing actual wire traffic is the fastest way to distinguish standard from
deployment-specific. Workflow:

1. Run a call flow against the local container
2. Capture on the loopback interface
3. Filter `sip` in Wireshark
4. Any header or field not in RFC 3261 or the PJSIP docs is a custom convention

If a custom header appears when talking to a vanilla Asterisk container, it's
Asterisk-specific. If it only appears against a specific deployment, it's
deployment-specific. That distinction is the audit.

### Integration test harness

See `contract.md` — end-to-end assertions against the local container. SIPp
handles call flow; the harness asserts the server-side state transitions.
