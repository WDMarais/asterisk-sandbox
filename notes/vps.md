# VPS considerations

## When to do it

Set up the VPS after local config is validated — know the contract is stable before
putting it on a public endpoint. Local testing with a softphone against 127.0.0.1
is faster to iterate on than remote.

## Purpose

A persistent reference instance that:
- Desmond can hit with his standard test table on his own schedule
- Eliminates the "schedule a session" bottleneck for sign-off
- Serves as the stable URL for browser-side SIP UA testing

## Practical notes

- Let's Encrypt via certbot for TLS — free, auto-renewing, works on any VPS with
  a domain pointed at it
- STUN is required for WebRTC from a browser to a remote host. Test without TURN
  first — TURN is only needed behind symmetric NAT.
- Coturn is the standard open-source TURN server if TURN becomes necessary
- A small VPS (1 vCPU, 1GB RAM) is sufficient for a handful of concurrent test
  calls — Asterisk is not resource-hungry at this scale
- Point a subdomain at it; easier to manage TLS and easier to give Desmond a
  stable URL than a raw IP
