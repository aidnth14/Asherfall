# Asherfall

A pygame client + WebSocket relay server for testing peer-to-peer co-op
connectivity between players over the internet, set in the world of Asherfall.

## Structure

```
client/            pygame app (host/join UI, live RTT test, settings, gamepad)
  main.py          entrypoint / game loop
  network.py       websocket connection handling + public-DNS fallback
  ui.py            widgets: starfield, freighter flyby, buttons, sliders, cards
  config.py        colors, layout, timeouts, music tracks
  assets/          synthesized lobby soundtrack (.mp3) + icons

server/            relay server (deployed on Render.com)
  server.py        room-code relay with rate limiting / abuse protection
  Dockerfile
  render.yaml
```

## Running the client

```
cd client
pip install -r requirements.txt
python3 main.py
```

One player clicks **HOST**, gets a 6-character room code, shares it with
their friend. The friend enters the code and clicks **JOIN**. Once
connected, both sides see a live round-trip-latency readout confirming the
relay path is fully operational.

## Running the server locally

```
cd server
pip install -r requirements.txt
python3 server.py
```

Listens on `ws://0.0.0.0:8080`.

## Deploying the server

```
The server is deployed via Render Blueprint (`render.yaml`). Every push to the `master` branch auto-deploys.

Live instance: `wss://asherfall-relay.onrender.com`

## Features

- **Host/Join relay** — no direct P2P/NAT traversal needed; both clients
  connect out to the relay, which pairs them by room code.
- **Live connectivity test** — continuous ping/pong once paired, showing
  real round-trip latency so you know the link is actually working.
- **Settings panel** — gear icon next to HOST; adjust music volume or
  mute, live.
- **Gamepad support** — D-pad/left-stick to move focus, A to confirm, B to
  back out of settings. Falls back to mouse/keyboard automatically.
- **Original soundtrack** — four synthesized ambient/chiptune tracks
  (Neon Market, Orbital Drift, Cargo Run, Boardroom), generated from
  scratch by `assets/_gen_music.py`; loops forever, fades between tracks.
- **Resilient networking** — connect/close never block the UI thread;
  friendly error messages instead of raw exceptions; automatic fallback to
  public DNS (8.8.8.8) if the local resolver is stale; dead-peer detection
  via ping timeout.
- **Server hardening** — see `SECURITY.md`.

See `keybinds.txt` for the full input reference and `CHANGELOG.md` for
what's been built and why.
