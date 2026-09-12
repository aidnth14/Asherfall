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

import os
import math
import pygame

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
