# Changelog

## Gameplay Polish & Physics
- Fixed bullet trajectory math to perfectly translate screen-space aim into the isometric grid coordinate system.
- Added dynamic drop physics (bouncing, scattering) when mining rocks and chopping trees, which correctly hides behind the fog-of-war.
- Implemented a health pool for resource tiles (trees/rocks take 5-7 hits to break).
- Integrated weapon-specific recoil physics, granting dynamic screenshake and player knockback upon firing.
- Added scatter-shot spread logic for the SawedOffShotgun.
- Increased weapon scaling by 10% and normalized bullet sizes for better visual clarity.
- Restored the Shift+Scroll Hotbar to specifically cycle through all combat weapons and utilities.
- Implemented particle bursts (splinters and shards) when striking resource tiles.

## Weapons & Tools Integration
- Restored the comprehensive weapons system including combat logic (firing, bullets).
- Re-added tools (Axe, Pickaxe, Shovel, etc.) and mining/gathering functionality which drops resources like coal, ore, and wood into the game world.
- Re-added the UI compass and notepad icons, fully restoring their functionality.
- Fixed a handful of legacy multiplayer combat crashes from earlier testing (unbound local variable `p_arr`, string type bug in `iso_move` dash cooldown, and `math` variable shadowing).
- Resolved absolute path errors for loading asset textures by using dynamic paths relative to the Asherfall asset directory.

## Server hardening
- Per-IP and global connection caps, connection-rate throttling, per-message
  rate limiting, 2KB message size cap.
- Room codes lengthened 4→6 chars; failed-join lockout to stop brute-forcing.
- Stale unjoined rooms now auto-expire instead of leaking memory.
- See `SECURITY.md` for the full breakdown.

## Settings panel + gamepad support
- Gear icon next to HOST opens a settings modal: music volume slider, mute
  toggle.
- Gamepad navigation: D-pad/stick to move focus, A to confirm, B to back
  out — falls back to mouse/keyboard automatically, hot-pluggable.

## Music playlist
- Added a 4-track looping playlist (Neon Market, Orbital Drift, Cargo Run,
  Boardroom), crossfading between tracks via `MUSIC_END_EVENT`.
- The first four tracks are original, synthesized from scratch in pure
  Python (`assets/_gen_music.py`) — chord-progression pads, plucks, and
  bells at a correct 44100Hz.
- Added three 8-bit chiptune tracks (Sanctuary Guardians, Alien Wolves,
  Melancholic Walk), kept as their original unmodified WAV files.

## UI redesign
- Replaced the flat, loosely-positioned layout with a proper card-panel
  shell: header + centered bordered card with drop shadow, consistent
  spacing, glowing gold title text, pulsing room-code display.
- Added friendly, human-readable connection errors (`network.py`
  `humanize_connect_error`) instead of raw Python exceptions.
- Made `Connection.connect()` and `.close()` fully non-blocking (moved off
  the main thread) — previously a slow/hanging connect or close could
  freeze the whole UI during a state transition.

## Initial build
- Room-code relay server (WebSocket) deployed on Fly.io.
- pygame client with Host/Join flow and live ping/pong RTT display.
- Public-DNS (8.8.8.8) fallback resolver for stale local DNS caches.
