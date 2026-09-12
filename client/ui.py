"""
================================================================================
ASHERFALL - UNIFIED CLIENT UI, CONFIGURATION, CONTROLLER & NETWORKING SUBSYSTEM
================================================================================
Consolidates configuration constants, gamepad controller manager, asynchronous
relay connection, voice chat, and all graphical UI widgets into a unified module.
================================================================================
"""
import asyncio
import base64
import collections
import json
import logging
import math
import os
import queue
import random
import socket
import ssl
import sys
import threading
import time
from typing import Dict, List, Tuple, Any, Optional

import pygame
import websockets

try:
    import numpy as np
    import sounddevice as sd
    _HAVE_AUDIO = True
except Exception:
    _HAVE_AUDIO = False

# Self-registration of backwards-compatible module aliases in sys.modules
_ui_mod = sys.modules[__name__]
sys.modules['config'] = _ui_mod
sys.modules['controller'] = _ui_mod
sys.modules['network'] = _ui_mod
sys.modules['voice'] = _ui_mod
cfg = _ui_mod


# ============================================================================
# 1. CONFIGURATION CONSTANTS
# ============================================================================
DEFAULT_SERVER = "ws://localhost:8080"

WIDTH, HEIGHT = 800, 640
FPS = 60

MONO_FONTS = "consolas,menlo,couriernew,dejavusansmono,monospace"

# accent (replaced blue with sand)
GOLD = (240, 214, 158)       # was cyan, now SAND_BRIGHT
GOLD_DIM = (198, 172, 122)   # was dim cyan, now SAND
GOLD_FAINT = (148, 122, 72)  # was faint cyan, now a darker sand
WHITE = (235, 235, 235)
MUTED = (150, 150, 165)
RED = (255, 110, 110)
GREEN = (110, 255, 150)
BG = (5, 5, 10)

# desert-sand lobby text menu
SAND = (198, 172, 122)
SAND_BRIGHT = (240, 214, 158)
SAND_SHADOW = (18, 14, 8)

CARD_BG = (16, 17, 24)
CARD_SHADOW = (0, 0, 0)
CARD_BORDER = (60, 72, 80)
DIVIDER = (48, 58, 66)

INPUT_BG = (24, 25, 34)
INPUT_BORDER = (70, 70, 85)

BTN_BG = (26, 48, 30)
BTN_BG_HOVER = (38, 78, 44)
BTN_BORDER = (80, 90, 80)

CARD_W, CARD_H = 640, 400
CARD_RADIUS = 14

CONNECTION_TIMEOUT = 12.0  # seconds without a pong before we call it dead
PING_INTERVAL = 1.0

MUSIC_TRACKS = [
    "sound/music/neon_market.mp3", "sound/music/orbital_drift.mp3", "sound/music/cargo_run.mp3", "sound/music/boardroom.mp3",
    "sound/music/sanctuary_guardians.mp3", "sound/music/alien_wolves.mp3", "sound/music/melancholic_walk.mp3",
    "sound/music/8bit-Grim Waltz - Creepy Retro Gaming Music For Streaming [No Copyright].mp3.mp3",
    "sound/music/8bit-LonePeakMusic - Highway 1 (16 Bit Retro Gaming Version).mp3.mp3",
    "sound/music/8bit-Mystery  Free mystery music for YouTube videos (no copyright).mp3.mp3",
    "sound/music/8bit-One Cosmos  Royalty Free Sci-Fi Background Music (No Copyright).mp3.mp3",
    "sound/music/8bit-Plinian - Epic Retro Gaming 16 Bit Music [No Copyright].mp3.mp3",
    "sound/music/8bit-Tronicles SciFi - Free Music  [Royalty Free No Copyright].mp3.mp3"
]
MUSIC_VOLUME = 0.22  # dimmed, ambient lobby melody rather than full theme blast
MUSIC_FADE_MS = 1500


# ============================================================================
# 2. GAMEPAD & CONTROLLER SUBSYSTEM
# ============================================================================
"""
================================================================================
ASHERFALL - ADVANCED MULTI-CONTROLLER SUBSYSTEM (XBOX, PLAYSTATION, NINTENDO)
================================================================================
Provides comprehensive, unified controller support across all platforms:
  - Automatic detection of Xbox, PlayStation (PS4/PS5), and Nintendo (Switch Pro/Joy-Con)
  - Seamless button & axis normalization across driver differences (macOS/Windows/Linux)
  - Twin-stick 360-degree aiming and deadzone management
  - Multi-controller Local Co-op support (Players 1-4 assignable to separate gamepads)
  - Dedicated sliced pixel-art button prompt icons for all 3 controller families
  - Live device hot-plugging (JOYDEVICEADDED / JOYDEVICEREMOVED)
================================================================================
"""


TYPE_XBOX = "xbox"
TYPE_PLAYSTATION = "playstation"
TYPE_NINTENDO = "nintendo"
TYPE_GENERIC = "generic"

# Friendly display names
FAMILY_NAMES = {
    TYPE_XBOX: "Xbox Controller",
    TYPE_PLAYSTATION: "PlayStation DualShock / DualSense",
    TYPE_NINTENDO: "Nintendo Switch Controller",
    TYPE_GENERIC: "Gamepad",
}

# Sliced icon coordinates from the 84x72 sprite sheets (12x12 source rects)
ICON_COORDS = {
    TYPE_XBOX: {
        "CONFIRM": (0, 48),    # A (Green)
        "CANCEL": (0, 36),     # B (Red)
        "ATTACK": (0, 12),     # X (Blue)
        "CYCLE": (0, 24),      # Y (Yellow)
        "A": (0, 48), "B": (0, 36), "X": (0, 12), "Y": (0, 24),
        "MENU": (0, 60),       # Menu button
        "BACK": (0, 60),
        "LB": (36, 24), "RB": (48, 24),
        "LT": (60, 24), "RT": (72, 24),
        "PREV": (36, 24), "NEXT": (48, 24),
        "DODGE": (60, 24), "FIRE": (72, 24),
    },
    TYPE_PLAYSTATION: {
        "CONFIRM": (0, 36),    # Cross (Blue)
        "CANCEL": (0, 48),     # Circle (Red)
        "ATTACK": (0, 24),     # Square (Pink)
        "CYCLE": (0, 12),      # Triangle (Cyan)
        "A": (0, 36), "B": (0, 48), "X": (0, 24), "Y": (0, 12), # Alias to Xbox names for compatibility
        "CROSS": (0, 36), "CIRCLE": (0, 48), "SQUARE": (0, 24), "TRIANGLE": (0, 12),
        "MENU": (0, 60),       # Options
        "BACK": (0, 60),
        "LB": (36, 24), "RB": (48, 24),   # L1, R1
        "LT": (60, 24), "RT": (72, 24),   # L2, R2
        "PREV": (36, 24), "NEXT": (48, 24),
        "DODGE": (60, 24), "FIRE": (72, 24),
    },
    TYPE_NINTENDO: {
        "CONFIRM": (0, 48),    # A
        "CANCEL": (0, 36),     # B
        "ATTACK": (0, 24),     # Y
        "CYCLE": (0, 12),      # X
        "A": (0, 48), "B": (0, 36), "X": (0, 12), "Y": (0, 24),
        "MENU": (0, 60),       # Plus (+)
        "BACK": (12, 60),      # Minus (-)
        "LB": (36, 24), "RB": (48, 24),   # L, R
        "LT": (60, 24), "RT": (72, 24),   # ZL, ZR
        "PREV": (36, 24), "NEXT": (48, 24),
        "DODGE": (60, 24), "FIRE": (72, 24),
    },
}


def detect_controller_type(joy) -> str:
    """Identify the controller family (Xbox, PlayStation, Nintendo, or Generic)
    based on joystick device name and SDL hardware descriptors."""
    if not joy:
        return TYPE_XBOX
    try:
        name = joy.get_name().lower()
    except Exception:
        return TYPE_XBOX

    # PlayStation detection (DualShock 4, DualSense, Sony, "Wireless Controller" on macOS)
    ps_keywords = ["ps4", "ps5", "playstation", "dualsense", "dualshock", "sony"]
    if any(k in name for k in ps_keywords):
        return TYPE_PLAYSTATION
    if "wireless controller" in name and not any(k in name for k in ["xbox", "nintendo"]):
        # DualShock / DualSense is reported as generic "Wireless Controller" by Apple macOS IOKit
        return TYPE_PLAYSTATION

    # Nintendo detection (Switch Pro, Joy-Cons, Nintendo, Wii)
    nintendo_keywords = ["nintendo", "switch", "joy-con", "pro controller", "wii", "nes", "snes"]
    if any(k in name for k in nintendo_keywords):
        return TYPE_NINTENDO

    # Xbox detection (Xbox 360, Xbox One, Series X/S, Microsoft XInput)
    xbox_keywords = ["xbox", "x-box", "microsoft", "xinput"]
    if any(k in name for k in xbox_keywords):
        return TYPE_XBOX

    return TYPE_GENERIC


def load_all_controller_icons(assets_dir):
    """Load and slice icon sheets for Xbox, PlayStation, and Nintendo, returned
    in a dictionary mapped by family type."""
    icon_packs = {}
    cdir = os.path.join(assets_dir, "controller")

    sheets = {
        TYPE_XBOX: "xbox.png",
        TYPE_PLAYSTATION: "ps.png",
        TYPE_NINTENDO: "nintendo.png",
    }

    for ctype, filename in sheets.items():
        pack = {}
        sheet_path = os.path.join(cdir, filename)
        if not os.path.exists(sheet_path):
            sheet_path = os.path.join(cdir, "xbox.png")
        try:
            raw_sheet = pygame.image.load(sheet_path)
            sheet = raw_sheet.convert_alpha() if pygame.display.get_surface() else raw_sheet
            coords = ICON_COORDS.get(ctype, ICON_COORDS[TYPE_XBOX])
            for k, (x, y) in coords.items():
                ic = sheet.subsurface(pygame.Rect(x, y, 12, 12)).copy()
                pack[k] = pygame.transform.scale(ic, (26, 26))
        except Exception as e:
            print(f"[controller] error loading icons for {ctype}: {e}")
        icon_packs[ctype] = pack

    # Also map generic to xbox pack
    icon_packs[TYPE_GENERIC] = icon_packs.get(TYPE_XBOX, {})
    return icon_packs


class ControllerManager:
    """Central registry and input processor for all connected gamepads."""

    def __init__(self, assets_dir=None):
        self.joysticks = []
        self.active_type = TYPE_XBOX
        self.icon_packs = {}
        self.last_menu_nav_time = 0.0
        self.last_pause_press = 0.0
        self.last_notepad_press = 0.0
        self.last_cycle_press = 0.0
        if assets_dir:
            self.icon_packs = load_all_controller_icons(assets_dir)
        self.refresh_devices()

    def refresh_devices(self):
        """Re-scan all connected joysticks, init them, and update active controller type."""
        self.joysticks = []
        try:
            if not pygame.joystick.get_init():
                pygame.joystick.init()
            cnt = pygame.joystick.get_count()
            for i in range(cnt):
                j = pygame.joystick.Joystick(i)
                j.init()
                self.joysticks.append(j)
                ctype = detect_controller_type(j)
                print(f"[controller] Registered #{i}: '{j.get_name()}' -> Profile: {FAMILY_NAMES.get(ctype, ctype)}")
            if self.joysticks:
                self.active_type = detect_controller_type(self.joysticks[0])
        except Exception as e:
            print(f"[controller] Device refresh error: {e}")

    def on_device_added(self, device_index):
        """Handle hot-plug event."""
        try:
            j = pygame.joystick.Joystick(device_index)
            j.init()
            if j not in self.joysticks:
                self.joysticks.append(j)
            self.active_type = detect_controller_type(j)
            ctype = self.active_type
            print(f"[controller] Connected: '{j.get_name()}' -> Profile: {FAMILY_NAMES.get(ctype, ctype)}")
            return j
        except Exception as e:
            print(f"[controller] Device add error: {e}")
            return None

    def on_device_removed(self, instance_id=None):
        """Handle device disconnect."""
        self.refresh_devices()

    def get_icons(self, ctype=None):
        """Get the icon dictionary for the given or currently active controller family."""
        ct = ctype or self.active_type
        return self.icon_packs.get(ct, self.icon_packs.get(TYPE_XBOX, {}))

    def read_inputs(self, player_idx=0):
        """Read and normalize inputs from the controller corresponding to player_idx.
        If player_idx has no controller, or all are combined, falls back to controller 0.
        Returns a normalized input dictionary."""
        res = {
            "dx": 0.0, "dy": 0.0,           # Movement axes (normalized with deadzone)
            "rx": 0.0, "ry": 0.0,           # Right stick aiming axes
            "aim_angle": None,              # Right-stick aim angle in radians
            "fire": False,                  # Primary attack/shoot/harvest
            "jump": False,                  # Jump
            "roll": False,                  # Roll / Dodge
            "dash": False,                  # Dash
            "cycle_next": False,            # Hotbar cycle next
            "cycle_prev": False,            # Hotbar cycle prev
            "pause": False,                 # Start / Options / Plus
            "notepad": False,               # Back / Share / Minus / Touchpad
            "confirm": False,               # Menu confirm
            "cancel": False,                # Menu cancel / back
            "menu_up": False,
            "menu_down": False,
            "menu_left": False,
            "menu_right": False,
            "ctype": self.active_type,
        }

        if not self.joysticks:
            return res

        # In Local Co-Op, player 0 gets joystick 0, player 1 gets joystick 1, etc.
        # If fewer joysticks than player index, player has no controller input.
        if player_idx < len(self.joysticks):
            j = self.joysticks[player_idx]
        else:
            j = self.joysticks[0] if player_idx == 0 else None

        if not j or not j.get_init():
            return res

        ctype = detect_controller_type(j)
        res["ctype"] = ctype
        num_axes = j.get_numaxes()
        num_buttons = j.get_numbuttons()
        num_hats = j.get_numhats()

        # 1. Left Stick (Movement) with 0.15 radial deadzone
        if num_axes >= 2:
            lx = j.get_axis(0)
            ly = j.get_axis(1)
            mag = math.hypot(lx, ly)
            if mag > 0.15:
                scale = (mag - 0.15) / 0.85
                res["dx"] = (lx / mag) * scale
                res["dy"] = (ly / mag) * scale

        # 2. Right Stick (Aiming) with 0.18 deadzone
        rx, ry = 0.0, 0.0
        if num_axes >= 4:
            rx = j.get_axis(2)
            ry = j.get_axis(3)
            # Some platforms put right stick on axis 3, 4
            if abs(rx) < 0.1 and abs(ry) < 0.1 and num_axes >= 5:
                alt_rx = j.get_axis(3)
                alt_ry = j.get_axis(4)
                if math.hypot(alt_rx, alt_ry) > 0.18:
                    rx, ry = alt_rx, alt_ry
            mag_r = math.hypot(rx, ry)
            if mag_r > 0.18:
                res["rx"] = rx
                res["ry"] = ry
                res["aim_angle"] = math.atan2(ry, rx)

        # 3. Triggers (Left = Roll/Dodge, Right = Attack/Fire)
        # Supports analog axes (Axis 4 & 5 or 2 & 5) and digital trigger buttons
        if num_axes >= 6:
            # Standard SDL2: Axis 4 is LT/L2/ZL, Axis 5 is RT/R2/ZR
            lt = j.get_axis(4)
            rt = j.get_axis(5)
            if lt > 0.15: res["roll"] = True
            if rt > 0.15: res["fire"] = True
        elif num_axes >= 5:
            rt = j.get_axis(4)
            if rt > 0.15: res["fire"] = True

        # Digital trigger buttons (some OS/Bluetooth drivers report triggers as buttons 6, 7)
        if num_buttons > 6 and j.get_button(6): res["roll"] = True
        if num_buttons > 7 and j.get_button(7): res["fire"] = True

        # 4. Face Buttons Mapping based on Family:
        # Xbox: 0=A (Jump/Confirm), 1=B (Roll/Cancel), 2=X (Attack), 3=Y (Cycle)
        # PlayStation: 0=Cross (Jump/Confirm), 1=Circle (Roll/Cancel), 2=Square (Attack), 3=Triangle (Cycle)
        # Nintendo: 0=B (Jump/Cancel), 1=A (Roll/Confirm), 2=Y (Attack), 3=X (Cycle)
        if num_buttons > 0 and j.get_button(0):
            res["jump"] = True
            if ctype == TYPE_NINTENDO:
                res["confirm"] = True   # B on Nintendo is often confirm or jump
            else:
                res["confirm"] = True   # A / Cross is standard confirm

        if num_buttons > 1 and j.get_button(1):
            res["roll"] = True
            if ctype == TYPE_NINTENDO:
                res["confirm"] = True   # A on Nintendo is traditional Japanese confirm
                res["cancel"] = True
            else:
                res["cancel"] = True    # B / Circle is standard cancel

        if num_buttons > 2 and j.get_button(2):
            res["use_item"] = True      # X (Xbox) / Square (PS) / Y (Nintendo) uses hotbar item!

        if num_buttons > 3 and j.get_button(3):
            res["craft"] = True         # Y (Xbox) / Triangle (PS) / X (Nintendo) toggles Crafting Bench!

        # 5. Bumpers (LB / RB, L1 / R1, L / R)
        if num_buttons > 4 and j.get_button(4):
            res["lb"] = True
            res["cycle_prev"] = True
        if num_buttons > 5 and j.get_button(5):
            res["rb"] = True
            res["cycle_next"] = True

        # 6. Stick Clicks (L3 = Dash, R3)
        if num_buttons > 8 and j.get_button(8):
            res["dash"] = True
        if num_buttons > 9 and j.get_button(9):
            res["dash"] = True
        if num_buttons > 10 and j.get_button(10):
            res["dash"] = True

        # 7. Start / Options / Plus (+) -> Pause & Menu
        # Button 7 (Xbox/PS Start/Options) or Button 9 (Nintendo +) or Button 6
        if num_buttons > 7 and j.get_button(7):
            res["pause"] = True
        elif num_buttons > 9 and j.get_button(9):
            res["pause"] = True
        elif num_buttons > 6 and j.get_button(6) and ctype == TYPE_NINTENDO:
            res["pause"] = True

        # 8. Select / Back / Share / Minus (-) / Touchpad -> Notepad / Map
        if num_buttons > 6 and j.get_button(6) and ctype != TYPE_NINTENDO:
            res["notepad"] = True
        elif num_buttons > 8 and j.get_button(8) and ctype == TYPE_NINTENDO:
            res["notepad"] = True
        elif num_buttons > 11 and j.get_button(11):
            res["notepad"] = True

        # 9. D-Pad (Hat motion and D-pad buttons)
        if num_hats > 0:
            hx, hy = j.get_hat(0)
            if hx < 0:
                res["dx"] -= 1.0
                res["menu_left"] = True
                res["cycle_prev"] = True
            elif hx > 0:
                res["dx"] += 1.0
                res["menu_right"] = True
                res["cycle_next"] = True
            if hy > 0:
                res["dy"] -= 1.0
                res["menu_up"] = True
            elif hy < 0:
                res["dy"] += 1.0
                res["menu_down"] = True

        # Also support D-pad as buttons (buttons 11, 12, 13, 14 on some drivers)
        if num_buttons > 14:
            if j.get_button(11): res["dy"] -= 1.0; res["menu_up"] = True
            if j.get_button(12): res["dy"] += 1.0; res["menu_down"] = True
            if j.get_button(13): res["dx"] -= 1.0; res["menu_left"] = True; res["cycle_prev"] = True
            if j.get_button(14): res["dx"] += 1.0; res["menu_right"] = True; res["cycle_next"] = True

        # Left stick menu navigation pulses (0.22s debounce)
        if abs(res["dx"]) > 0.5:
            if res["dx"] < 0: res["menu_left"] = True
            else: res["menu_right"] = True
        if abs(res["dy"]) > 0.5:
            if res["dy"] < 0: res["menu_up"] = True
            else: res["menu_down"] = True

        return res


# ============================================================================
# 3. NETWORKING CLIENT
# ============================================================================

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"

log = logging.getLogger("network")

class Connection:
    def __init__(self):
        self.state = STATE_DISCONNECTED
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self.addr = None
        self.first_message = None
        self.session_id = None
        self._thread = None
        self._loop = None
        self._shutdown = threading.Event()

    def connect(self, addr, first_message, session_id):
        self.close()
        # Drain queues
        while not self.incoming.empty():
            try: self.incoming.get_nowait()
            except queue.Empty: break
        while not self.outgoing.empty():
            try: self.outgoing.get_nowait()
            except queue.Empty: break
        self.addr = addr
        self.first_message = first_message
        self.session_id = session_id
        self.state = STATE_CONNECTING
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def _run_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            log.exception("Network thread crashed")
        finally:
            self.state = STATE_DISCONNECTED
            self._loop.close()

    async def _run_async(self):
        retry_delay = 0.5
        max_delay = 10.0
        attempts = 0
        max_attempts = 4
        
        while not self._shutdown.is_set():
            attempts += 1
            self._set_state(STATE_CONNECTING if attempts == 1 else STATE_RECONNECTING)
            
            try:
                async with websockets.connect(self.addr, ping_interval=15, ping_timeout=10, open_timeout=5) as ws:
                    self._set_state(STATE_CONNECTED)
                    attempts = 0
                    retry_delay = 0.5
                    
                    # Authenticate
                    auth_msg = dict(self.first_message)
                    auth_msg["session_id"] = self.session_id
                    await ws.send(json.dumps(auth_msg))
                    
                    sender_task = asyncio.create_task(self._sender(ws))
                    receiver_task = asyncio.create_task(self._receiver(ws))
                    
                    done, pending = await asyncio.wait(
                        [sender_task, receiver_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Connection attempt {attempts} failed: {e}")
                if attempts >= max_attempts:
                    self.incoming.put({"type": "connect_error", "error": f"Connection failed ({e})."})
                    break
                
            if self._shutdown.is_set():
                break
                
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

    async def _sender(self, ws):
        while not self._shutdown.is_set():
            try:
                msg = self.outgoing.get_nowait()
                await ws.send(json.dumps(msg))
            except queue.Empty:
                await asyncio.sleep(0.01)
            except Exception as e:
                log.error(f"Send error: {e}")
                break

    async def _receiver(self, ws):
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    self.incoming.put(msg)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            log.error(f"Receive error: {e}")

    def send(self, msg):
        if self.state == STATE_CONNECTED:
            self.outgoing.put(msg)

    def close(self):
        self._shutdown.set()
        self.state = STATE_DISCONNECTED

    def _set_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.incoming.put({"type": "network_state", "state": new_state})

def install_dns_fallback():
    pass


# ============================================================================
# 4. VOICE CHAT CLIENT
# ============================================================================
"""Push-to-talk voice chat over the same relay the game already uses.

Mic audio is captured at 8 kHz mono, crushed to 8-bit, base64'd and sent as
small JSON packets; incoming packets are mixed into a jitter buffer and played
back. Everything degrades gracefully — if PortAudio / a mic isn't available the
module just reports unavailable and the game runs on without voice.

Note: voice needs headroom the public relay's rate limit doesn't give, so it's
meant for the bundled/self-hosted relay (server/ raises the caps). Text chat and
movement stay well within the public relay's budget.
"""

SR = 8000            # sample rate (Hz) — telephone-ish, plenty for chat
CHUNK = 1024         # samples per packet (~128 ms) -> ~8 packets/sec

try:
    import numpy as np
    import sounddevice as sd
    _HAVE_AUDIO = True
except Exception:               # missing dep or no audio backend
    _HAVE_AUDIO = False


def encode(int16_block):
    """int16 mono samples -> base64 str of 8-bit PCM (half the bytes)."""
    small = (int16_block >> 8).astype("int8")
    return base64.b64encode(small.tobytes()).decode("ascii")


def decode(b64):
    """base64 8-bit PCM -> int16 numpy block."""
    raw = base64.b64decode(b64.encode("ascii"))
    return np.frombuffer(raw, dtype="int8").astype("int16") << 8


class Voice:
    def __init__(self):
        self.available = _HAVE_AUDIO
        self.talking = False
        self.error = "" if _HAVE_AUDIO else "install sounddevice + numpy for voice"
        self._outbox = collections.deque(maxlen=32)      # encoded chunks to send
        self._play = collections.deque(maxlen=SR * 2)    # int16 samples to play
        self._lock = threading.Lock()
        self._in_stream = None
        self._out_stream = None

    def _ensure_out_stream(self):
        if self._out_stream is None and _HAVE_AUDIO:
            try:
                self._out_stream = sd.OutputStream(
                    samplerate=SR, channels=1, dtype="int16", blocksize=CHUNK,
                    callback=self._out_cb)
                self._out_stream.start()
            except Exception as e:
                self.available = False
                self.error = f"audio out failed: {e}"

    def _out_cb(self, outdata, frames, time_info, status):
        with self._lock:
            if not self._play:
                outdata.fill(0)
                return
            for i in range(frames):
                outdata[i, 0] = self._play.popleft() if self._play else 0

    def push_incoming(self, b64):
        if not self.available:
            return
        self._ensure_out_stream()
        try:
            block = decode(b64)
        except Exception:
            return
        with self._lock:
            for s in block:                 # mix by append (overlapping talkers sum-ish)
                self._play.append(int(s))

    # --- capture: only while the talk key is held ---
    def _in_cb(self, indata, frames, time_info, status):
        block = (indata[:, 0] * 32767).astype("int16") if indata.dtype.kind == "f" \
            else indata[:, 0].astype("int16")
        self._outbox.append(encode(block))

    def start_talk(self):
        if not self.available or self.talking:
            return
        try:
            self._in_stream = sd.InputStream(
                samplerate=SR, channels=1, dtype="int16", blocksize=CHUNK,
                callback=self._in_cb)
            self._in_stream.start()
            self.talking = True
        except Exception as e:
            self.error = f"mic failed: {e}"

    def stop_talk(self):
        self.talking = False
        st, self._in_stream = self._in_stream, None
        if st:
            try:
                st.stop(); st.close()
            except Exception:
                pass

    def poll_outgoing(self):
        """Return queued encoded chunks to transmit, clearing the outbox."""
        out = []
        while self._outbox:
            out.append(self._outbox.popleft())
        return out

    def close(self):
        self.stop_talk()
        if self._out_stream:
            try:
                self._out_stream.stop(); self._out_stream.close()
            except Exception:
                pass


# ============================================================================
# 5. USER INTERFACE WIDGETS & RENDERING
# ============================================================================


cfg = sys.modules[__name__]


class Starfield:
    def __init__(self, w, h, count=110):
        self.w, self.h = w, h
        self.stars = [
            [random.uniform(0, w), random.uniform(0, h), random.uniform(0.15, 1.2)]
            for _ in range(count)
        ]

    def update(self, dt):
        for s in self.stars:
            s[1] += s[2] * 30 * dt
            if s[1] > self.h:
                s[1] = 0
                s[0] = random.uniform(0, self.w)

    def draw(self, surf):
        for x, y, speed in self.stars:
            b = min(255, int(70 + speed * 90))
            pygame.draw.circle(surf, (b, b, b), (int(x), int(y)), 1)


class ShipFlyby:
    """Occasional cargo freighter drifting across the starfield. Drawn
    procedurally (no sprite): a long hull with a lit cockpit and a row of
    glowing cargo-bay windows, so it reads cleanly over the dark background."""

    HULL = (40, 44, 54)
    HULL_EDGE = (90, 96, 112)
    WINDOW = (120, 210, 255)
    ENGINE = (255, 190, 90)

    def __init__(self, w, h, image_path=None):
        self.w, self.h = w, h
        self.iw, self.ih = 190, 46  # freighter bounding box
        self.active = False
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.timer = random.uniform(2.0, 5.0)  # first pass fairly soon

    def _launch(self):
        # start off-screen top-right, exit off-screen bottom-left
        self.x = self.w + random.uniform(20, 160)
        self.y = random.uniform(-self.ih, self.h * 0.35)
        speed = random.uniform(30, 55)
        self.vx = -speed
        self.vy = speed * random.uniform(0.5, 0.9)
        self.active = True

    def update(self, dt):
        if not self.active:
            self.timer -= dt
            if self.timer <= 0:
                self._launch()
            return
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x + self.iw < 0 or self.y > self.h:
            self.active = False
            self.timer = random.uniform(8.0, 18.0)

    def draw(self, surf):
        if not self.active:
            return
        x, y = int(self.x), int(self.y)
        iw, ih = self.iw, self.ih
        # engine glow at the trailing (right) end
        for i, a in enumerate((60, 110, 180)):
            gr = 7 - i * 2
            g = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
            pygame.draw.circle(g, (*self.ENGINE, a), (gr, gr), gr)
            surf.blit(g, (x + iw - 6 - gr, y + ih // 2 - gr))
        # main hull (tapered nose on the left, travel direction)
        hull = [
            (x, y + ih // 2), (x + 34, y + 6), (x + iw - 10, y + 8),
            (x + iw, y + ih // 2), (x + iw - 10, y + ih - 8), (x + 34, y + ih - 6),
        ]
        pygame.draw.polygon(surf, self.HULL, hull)
        pygame.draw.polygon(surf, self.HULL_EDGE, hull, 2)
        # bridge/cockpit block on top
        bridge = pygame.Rect(x + 40, y + 2, 26, 12)
        pygame.draw.rect(surf, self.HULL_EDGE, bridge, border_radius=3)
        pygame.draw.circle(surf, self.WINDOW, (x + 46, y + 8), 2)
        # row of lit cargo-bay windows
        for i in range(6):
            wx = x + 58 + i * 18
            pygame.draw.circle(surf, self.WINDOW, (wx, y + ih // 2), 2)


def _lerp(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def make_vignette(w, h, depth=165):
    """Cached radial darkening for the screen edges. Built small (cheap
    per-pixel) then smoothscaled up so it costs almost nothing to blit."""
    import math
    s = 40
    small = pygame.Surface((s, s), pygame.SRCALPHA)
    for y in range(s):
        for x in range(s):
            d = math.hypot(x - s / 2, y - s / 2) / (s / 2 * 1.42)
            a = int(min(1.0, d * d) * depth)
            small.set_at((x, y), (0, 0, 0, a))
    return pygame.transform.smoothscale(small, (w, h))


class NineSlice:
    """Stretch a bordered sprite to any rect without distorting its corners —
    used to skin buttons and panels with the chopped pixel-art assets."""
    def __init__(self, path, margin):
        self.img = pygame.image.load(path).convert_alpha()
        self.m = margin

    def draw(self, surf, rect):
        img, m = self.img, self.m
        iw, ih = img.get_size()
        x, y, w, h = rect.x, rect.y, max(rect.w, 2 * m + 2), max(rect.h, 2 * m + 2)
        sub = lambda sx, sy, sw, sh: img.subsurface(pygame.Rect(sx, sy, sw, sh))
        sc = pygame.transform.scale
        b = surf.blit
        rmw, rmh = iw - 2 * m, ih - 2 * m       # source middle spans
        cw, ch = w - 2 * m, h - 2 * m           # dest middle spans
        b(sub(0, 0, m, m), (x, y))
        b(sub(iw - m, 0, m, m), (x + w - m, y))
        b(sub(0, ih - m, m, m), (x, y + h - m))
        b(sub(iw - m, ih - m, m, m), (x + w - m, y + h - m))
        b(sc(sub(m, 0, rmw, m), (cw, m)), (x + m, y))
        b(sc(sub(m, ih - m, rmw, m), (cw, m)), (x + m, y + h - m))
        b(sc(sub(0, m, m, rmh), (m, ch)), (x, y + m))
        b(sc(sub(iw - m, m, m, rmh), (m, ch)), (x + w - m, y + m))
        b(sc(sub(m, m, rmw, rmh), (cw, ch)), (x + m, y + m))


BUTTON_SKIN = None   # set by game after assets load (NineSlice) — else vector fallback
PANEL_SKIN = None


def draw_glow_text(surf, text, font, x, y, color, glow_color=None, glow_radius=2, center_x=None):
    glow_color = glow_color or color
    rendered = font.render(text, True, color)
    if center_x is not None:
        x = center_x - rendered.get_width() // 2
    
    # Render glow text with a darker base color instead of using set_alpha() which can cause solid boxes
    dim_color = (glow_color[0] // 4, glow_color[1] // 4, glow_color[2] // 4)
    glow = font.render(text, True, dim_color)
    
    for dx in range(-glow_radius, glow_radius + 1):
        for dy in range(-glow_radius, glow_radius + 1):
            if dx == 0 and dy == 0:
                continue
            surf.blit(glow, (x + dx, y + dy))
    surf.blit(rendered, (x, y))
    return rendered.get_width()


_TEXT_CACHE = {}
def draw_text(surf, text, font, x, y, color=cfg.WHITE, center_x=None):
    if isinstance(color, list):
        color = tuple(color)
    key = (id(font), text, color)
    rendered = _TEXT_CACHE.get(key)
    if rendered is None:
        rendered = font.render(text, True, color)
        if len(_TEXT_CACHE) < 512:
            _TEXT_CACHE[key] = rendered
    if center_x is not None:
        x = center_x - rendered.get_width() // 2
    surf.blit(rendered, (x, y))
    return rendered.get_width()


def wrap_text(text, font, max_width):
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if font.size(trial)[0] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped_text(surf, text, font, y, max_width, color=cfg.WHITE, center_x=None, line_gap=4):
    lines = wrap_text(text, font, max_width)
    line_h = font.get_height() + line_gap
    for i, line in enumerate(lines):
        draw_text(surf, line, font, 0, y + i * line_h, color, center_x=center_x)
    return len(lines) * line_h


def draw_card(surf, rect, radius=cfg.CARD_RADIUS):
    shadow_rect = rect.move(0, 6)
    shadow = pygame.Surface(shadow_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, 110), shadow.get_rect(), border_radius=radius)
    surf.blit(shadow, shadow_rect.topleft)

    if PANEL_SKIN is not None:                 # parchment-panel skin from the pack
        PANEL_SKIN.draw(surf, rect)
        return

    pygame.draw.rect(surf, cfg.CARD_BG, rect, border_radius=radius)
    pygame.draw.rect(surf, cfg.CARD_BORDER, rect, 2, border_radius=radius)

    top_line = pygame.Rect(rect.x + radius, rect.y + 1, rect.w - radius * 2, 2)
    pygame.draw.rect(surf, cfg.GOLD_FAINT, top_line)


def draw_divider(surf, x, y, w, color=cfg.DIVIDER):
    pygame.draw.line(surf, color, (x, y), (x + w, y), 1)


class TextInput:
    def __init__(self, x, y, w, h, label, value=""):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value
        self.active = False

    def handle_click(self, pos):
        self.active = self.rect.collidepoint(pos)
        return self.active

    def handle_key(self, event):
        if not self.active:
            return
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
        elif event.unicode.isprintable():
            self.value += event.unicode

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x + 2, self.rect.y - 20, cfg.GOLD_DIM)

        prefix_color = cfg.GOLD if self.active else cfg.GOLD_DIM
        draw_text(surf, "›", font, self.rect.x + 10, self.rect.y + 6, prefix_color)
        draw_text(surf, self.value, font, self.rect.x + 30, self.rect.y + 6, cfg.GOLD)

        if self.active and int(pygame.time.get_ticks() / 500) % 2 == 0:
            tw = font.size(self.value)[0]
            cx = self.rect.x + 30 + tw + 2
            pygame.draw.line(surf, cfg.GOLD, (cx, self.rect.y + 7), (cx, self.rect.bottom - 7), 2)


class Button:
    def __init__(self, x, y, w, h, label, primary=True, palette=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.primary = primary
        # palette: dict of fill/fill_hover/border/border_hover/text/accent to
        # override the default green. Lets the lobby use a sand skin.
        self.palette = palette or {}

    def draw(self, surf, font):
        import time, math, pygame
        r = self.rect
        hover = r.collidepoint(pygame.mouse.get_pos())
        
        # If palette is provided and not text_only, render as a solid block button
        if self.palette and not self.palette.get("text_only"):
            bg = self.palette.get("fill_hover") if hover and "fill_hover" in self.palette else self.palette.get("fill", cfg.INPUT_BG)
            border = self.palette.get("border_hover") if hover and "border_hover" in self.palette else self.palette.get("border", cfg.GOLD)
            text_color = self.palette.get("text", cfg.WHITE)
            
            pygame.draw.rect(surf, bg, r, border_radius=6)
            pygame.draw.rect(surf, border, r, 2, border_radius=6)
            draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, text_color, center_x=r.centerx)
        else:
            # Default minimalistic text button
            c_hover = self.palette.get("text_hover", cfg.SAND_BRIGHT) if self.palette else cfg.SAND_BRIGHT
            c_norm = self.palette.get("text", cfg.SAND) if self.palette else cfg.SAND
            color = c_hover if hover else c_norm
            txt_w = draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, color, center_x=r.centerx)
    
            if hover:
                now = time.time()
                px = r.centerx + txt_w // 2 + 14 + int(2 * math.sin(now * 6))
                draw_text(surf, "<", font, px, r.centery - font.get_height() // 2, c_hover)
    def clicked(self, pos):
        return self.rect.collidepoint(pos)


def pulse_alpha(now, period=1.6, lo=140, hi=255):
    import math
    t = (now % period) / period
    return int(lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * 2 * math.pi)))


class IconButton:
    """Small circular button. Currently only draws a gear glyph, but takes
    a `kind` in case more icons are needed later."""

    def __init__(self, x, y, size, kind="gear", image_path=None):
        self.rect = pygame.Rect(x, y, size, size)
        self.kind = kind
        self.img = None
        if image_path:
            try:
                img = pygame.image.load(image_path).convert_alpha()
                self.img = pygame.transform.smoothscale(img, (size, size))
            except pygame.error:
                self.img = None

    def clicked(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf):
        import math
        hover = self.rect.collidepoint(pygame.mouse.get_pos())
        color = cfg.GOLD if hover else cfg.MUTED
        cx, cy = self.rect.center
        if self.img is not None:
            img = self.img.copy()
            img.set_alpha(255 if hover else 170)
            surf.blit(img, self.rect.topleft)
            return
        if self.kind == "close":
            r = self.rect.w // 2 - 2
            pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r + 3)
            pygame.draw.circle(surf, cfg.RED if hover else color, (cx, cy), r, 2)
            d = int(r * 0.45)
            line_col = cfg.RED if hover else color
            pygame.draw.line(surf, line_col, (cx - d, cy - d), (cx + d, cy + d), 2)
            pygame.draw.line(surf, line_col, (cx - d, cy + d), (cx + d, cy - d), 2)
            return
        if self.kind == "help":
            r = self.rect.w // 2 - 2
            pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r + 3)
            pygame.draw.circle(surf, color, (cx, cy), r, 2)
            if not hasattr(self, "_help_font") or self._help_font is None:
                self._help_font = pygame.font.SysFont("Courier", int(r * 1.5), bold=True)
            text = self._help_font.render("?", True, color)
            surf.blit(text, (cx - text.get_width() // 2 + 1, cy - text.get_height() // 2 + 1))
            return
        r_outer = self.rect.w // 2 - 2
        r_inner = int(r_outer * 0.55)
        pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r_outer + 3)
        pygame.draw.circle(surf, color, (cx, cy), r_outer, 2)
        pygame.draw.circle(surf, color, (cx, cy), r_inner, 2)
        teeth = 8
        for i in range(teeth):
            angle = (2 * math.pi / teeth) * i
            x1 = cx + math.cos(angle) * r_outer
            y1 = cy + math.sin(angle) * r_outer
            x2 = cx + math.cos(angle) * (r_outer + 5)
            y2 = cy + math.sin(angle) * (r_outer + 5)
            pygame.draw.line(surf, color, (x1, y1), (x2, y2), 2)


class Slider:
    def __init__(self, x, y, w, value=0.5, label=""):
        self.rect = pygame.Rect(x, y, w, 6)
        self.value = value
        self.label = label
        self.dragging = False

    def _handle_pos(self):
        return int(self.rect.x + self.value * self.rect.w)

    def hit_handle(self, pos):
        hx = self._handle_pos()
        hy = self.rect.centery
        return (pos[0] - hx) ** 2 + (pos[1] - hy) ** 2 <= 12 ** 2

    def handle_mousedown(self, pos):
        # Check if mouse is near the slider horizontally and vertically
        if self.hit_handle(pos) or (self.rect.x <= pos[0] <= self.rect.right and abs(pos[1] - self.rect.centery) <= 15):
            self.dragging = True
            self._update_from_x(pos[0])
            return True
        return False

    def handle_mouseup(self):
        self.dragging = False

    def handle_mousemotion(self, pos):
        if self.dragging:
            self._update_from_x(pos[0])

    def _update_from_x(self, x):
        self.value = max(0.0, min(1.0, (x - self.rect.x) / self.rect.w))

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 22, cfg.GOLD_DIM)
        pygame.draw.rect(surf, cfg.INPUT_BG, self.rect, border_radius=3)
        fill_w = int(self.rect.w * self.value)
        if fill_w > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_w, self.rect.h)
            pygame.draw.rect(surf, cfg.GOLD_DIM, fill_rect, border_radius=3)
        hx, hy = self._handle_pos(), self.rect.centery
        pygame.draw.circle(surf, cfg.GOLD, (hx, hy), 9)
        pygame.draw.circle(surf, cfg.CARD_BG, (hx, hy), 4)
        pct = int(self.value * 100)
        draw_text(surf, f"{pct}%", font, self.rect.right + 16, self.rect.y - 8, cfg.GOLD)


def draw_focus_ring(surf, rect, color=None, pad=5):
    color = color or cfg.GOLD
    ring = rect.inflate(pad * 2, pad * 2)
    pygame.draw.rect(surf, color, ring, 3, border_radius=12)


class Stepper:
    def __init__(self, x, y, w, h, label, value, lo, hi):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value
        self.lo, self.hi = lo, hi
        btn_w = h
        self.minus_rect = pygame.Rect(x, y, btn_w, h)
        self.plus_rect = pygame.Rect(x + w - btn_w, y, btn_w, h)

    def handle_click(self, pos):
        if self.minus_rect.collidepoint(pos):
            self.value = max(self.lo, self.value - 1)
            return True
        if self.plus_rect.collidepoint(pos):
            self.value = min(self.hi, self.value + 1)
            return True
        return False

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 20, cfg.GOLD_DIM)
        for r, sym in ((self.minus_rect, "-"), (self.plus_rect, "+")):
            hover = r.collidepoint(pygame.mouse.get_pos())
            color = cfg.GOLD if hover else cfg.GOLD_DIM
            txt = font.render(sym, True, color)
            surf.blit(txt, (r.centerx - txt.get_width() // 2, r.centery - txt.get_height() // 2))
        mid = pygame.Rect(self.minus_rect.right, self.rect.y, self.plus_rect.x - self.minus_rect.right, self.rect.h)
        val_txt = font.render(str(self.value), True, cfg.GOLD)
        surf.blit(val_txt, (mid.centerx - val_txt.get_width() // 2, mid.centery - val_txt.get_height() // 2))


class Toggle:
    def __init__(self, x, y, w, h, label, value=True):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value

    def clicked(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 22, cfg.GOLD_DIM)
        bg = cfg.BTN_BG_HOVER if self.value else cfg.INPUT_BG
        pygame.draw.rect(surf, bg, self.rect, border_radius=self.rect.h // 2)
        border = cfg.GOLD if self.value else cfg.INPUT_BORDER
        pygame.draw.rect(surf, border, self.rect, 2, border_radius=self.rect.h // 2)
        knob_x = self.rect.right - self.rect.h // 2 if self.value else self.rect.x + self.rect.h // 2
        pygame.draw.circle(surf, cfg.GOLD if self.value else cfg.MUTED, (knob_x, self.rect.centery), self.rect.h // 2 - 4)

