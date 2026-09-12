# Security notes

Honest scope: this hardens the relay server against the abuse a small
hobby co-op relay actually faces (room-code guessing, connection floods,
oversized/rapid messages, resource exhaustion). It is not a claim that the
server is "unhackable" — no server is. Large-scale volumetric (L3/L4) DDoS
mitigation is handled by Fly.io's anycast edge network, not application
code; nothing below changes that.

## Encryption in transit

- Client connects via `wss://` (WebSocket over TLS). Fly.io terminates TLS
  at its edge; the edge-to-machine hop runs over Fly's private, encrypted
  6PN network.
- Nothing is ever sent in plaintext from client to server.

## Application-layer hardening (`server/server.py`)

| Protection | Limit | Purpose |
|---|---|---|
| Global connection cap | 200 concurrent | prevents memory/fd exhaustion |
| Per-IP connection cap | 6 concurrent | one abusive client can't hog capacity |
| Per-IP new-connection rate | 20/min | throttles connection-flood attempts |
| Per-connection message rate | 10/sec | throttles message-flood attempts |
| Max message size | 2 KB | protocol only ever sends small JSON; rejects oversized frames |
| Room code length | 6 alphanumeric chars (~2.2B combinations) | makes brute-forcing a room infeasible at any practical rate |
| Failed-join lockout | 8 failed joins / 60s → 120s IP lockout | stops room-code brute-forcing |
| Stale room expiry | unjoined rooms auto-delete after 10 min | prevents slow memory leak from abandoned "host" spam |
| Keepalive ping/timeout | 15s / 10s | drops dead/zombie connections, frees rooms promptly |

All of the above is enforced server-side; a malicious client can't opt out
of it.

## What this does NOT cover

- Volumetric network-layer DDoS (handled by Fly's edge, out of app scope).
- Anyone who *has* the correct room code can join — the code itself is the
  shared secret between the two friends. Don't post it publicly.
- No user accounts/authentication — this is a throwaway relay for casual
  co-op sessions, not a persistent service handling sensitive data.
