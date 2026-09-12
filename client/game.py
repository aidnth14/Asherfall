"""All per-frame logic lives here so main.py can hot-reload it live.

Persistent state (network conn, music, positions, typed text, counters) is
stored on the shared `S` namespace which main.py owns and never rebuilds, so
reloading this module never drops the connection or resets a session.
"""
import math
import os
import queue
import time
import random
import math

import pygame
from weapons import Weapon, WEAPONS, GLOBAL_HOTBAR
from enemy.enemy import EnemyManager

import ui
import config as cfg
import iso
import controller
import voice as voicelib
from ui import (
    Starfield, TextInput, Button, IconButton, Slider, Toggle, Stepper,
    draw_glow_text, draw_text, draw_wrapped_text, draw_card, draw_divider, pulse_alpha,
    draw_focus_ring,
)

STATE_MENU, STATE_SETUP, STATE_WAIT, STATE_TEST, STATE_LOCAL, STATE_WAKE = \
    "menu", "setup", "wait", "test", "local", "wake"

JOYSTICK_A, JOYSTICK_B = 0, 1  # standard Xbox/PlayStation/Nintendo layout button indices
SPEED_CELLS = 5.5  # avatar walk speed in grid cells / sec (zoom-independent)
PLAYER_R = 12
LOCAL_MAX = 4  # same-screen coop supports up to 4 keyboard controllers
POS_SEND_HZ = 6  # online position updates/sec (stays under the relay rate cap)
CAM_SMOOTH = 6.0  # camera easing — lower = smoother/laggier follow
REVEAL_RADIUS = 6  # cells visible around each player (circular fog of war)

# jump / gravity — z is height in screen px; airborne avatars clear props
GRAVITY = 1500.0
JUMP_V = 470.0
JUMP_CLEAR = 8.0  # z above which you're airborne and can pass over rocks

# auto-assigned avatar colours (online): stable per-name so everyone agrees
PALETTE = [
    (90, 200, 220), (110, 255, 150), (110, 180, 255), (255, 150, 220),
    (255, 190, 90), (180, 140, 255), (255, 120, 120), (120, 255, 205),
]


def color_for(name):
    h = sum(ord(c) for c in name) if name else 0
    return PALETTE[h % len(PALETTE)]


def emit_noise(S, gx, gy, radius):
    """Perception 2.0: Emit loud acoustic noise ping that alerts nearby monsters."""
    if not hasattr(S, "noise_pings"):
        S.noise_pings = []
    S.noise_pings.append({"x": float(gx), "y": float(gy), "radius": float(radius), "time": time.time()})


PEER_TIMEOUT = 4.0     # drop a remote avatar after this many seconds of silence
CHAT_FADE = 9.0        # seconds a message stays before fading when chat is closed
VOICE_KEY = pygame.K_v  # hold to talk (online)

# per-player local control schemes: (label, up, down, left, right, color, jump)
# up/down/left/right map to isometric NE/SW/NW/SE, not screen axes.
SCHEMES = [
    ("WASD", pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d, (90, 200, 220), pygame.K_SPACE, pygame.K_q),
    ("ARROWS", pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, (110, 255, 150), pygame.K_RSHIFT, pygame.K_RCTRL),
    ("IJKL", pygame.K_i, pygame.K_k, pygame.K_j, pygame.K_l, (110, 180, 255), pygame.K_o, pygame.K_u),
    ("TFGH", pygame.K_t, pygame.K_g, pygame.K_f, pygame.K_h, (255, 150, 220), pygame.K_y, pygame.K_r),
]

# --- layout (recomputed from cfg on every reload, so cfg edits apply live) ---
CENTER_X = cfg.WIDTH // 2
CARD_X = (cfg.WIDTH - cfg.CARD_W) // 2
CARD_Y = 150
CARD = pygame.Rect(CARD_X, CARD_Y, cfg.CARD_W, cfg.CARD_H)
PAD = 40
LOCAL_PLAY = pygame.Rect(CARD_X + PAD, CARD_Y + 130, cfg.CARD_W - PAD * 2, cfg.CARD_H - 160)

COL_GAP = 24
COL_W = (cfg.CARD_W - PAD * 2 - COL_GAP) // 2
LEFT_X = CARD_X + PAD
RIGHT_X = LEFT_X + COL_W + COL_GAP
COL_HEADER_Y = CARD_Y + 108

BTN_H = 52
btn_y = CARD_Y + 280
GEAR_SIZE, GEAR_GAP = 40, 12

SETTINGS_W, SETTINGS_H = 680, 560
SETTINGS_RECT = pygame.Rect(CENTER_X - SETTINGS_W // 2, cfg.HEIGHT // 2 - SETTINGS_H // 2,
                            SETTINGS_W, SETTINGS_H)


# --- music (all state on S) ---
def track_display_name(index):
    if not cfg.MUSIC_TRACKS:
        return "No tracks loaded"
    stem = os.path.splitext(cfg.MUSIC_TRACKS[index % len(cfg.MUSIC_TRACKS)])[0]
    return stem.replace("_", " ").title()


def play_track_at(S, index):
    if not cfg.MUSIC_TRACKS:
        return
    S.music_track_index = index % len(cfg.MUSIC_TRACKS)
    path = os.path.join(S.ASSETS_DIR, cfg.MUSIC_TRACKS[S.music_track_index])
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(0.0 if S.music_muted else S.music_volume)
        pygame.mixer.music.play()
        S.music_paused = False
    except pygame.error as e:
        print(f"[audio] couldn't load {path}: {e}")


def play_next_track(S):
    play_track_at(S, S.music_track_index + 1)


def play_prev_track(S):
    play_track_at(S, S.music_track_index - 1)


def toggle_play_pause(S):
    if not cfg.MUSIC_TRACKS:
        return
    if S.music_paused:
        pygame.mixer.music.unpause()
    else:
        pygame.mixer.music.pause()
    S.music_paused = not S.music_paused


def apply_volume(S):
    S.music_volume = S.volume_slider.value
    S.music_muted = S.music_toggle.value  # toggle reads "MUTE": True = muted
    pygame.mixer.music.set_volume(0.0 if S.music_muted else S.music_volume)


def play_bullet_collision_sfx(S):
    """Play bullet collision sound effect when bullet hits an obstacle or enemy."""
    if not hasattr(S, "bullet_hit_sfx"):
        S.bullet_hit_sfx = None
        sfx_path = os.path.join(S.ASSETS_DIR, "sound", "sfx", "bullet_collision.mp3")
        if not os.path.exists(sfx_path):
            sfx_path = os.path.join(S.ASSETS_DIR, "sound", "sfx", "bulletcolusion.mp3")
        try:
            if os.path.exists(sfx_path):
                S.bullet_hit_sfx = pygame.mixer.Sound(sfx_path)
        except Exception as e:
            print(f"[audio] couldn't load bullet collision sound: {e}")

    if getattr(S, "bullet_hit_sfx", None) and not getattr(S, "music_muted", False):
        try:
            vol = getattr(S, "music_volume", 0.5)
            S.bullet_hit_sfx.set_volume(min(1.0, max(0.15, vol * 1.3)))
            S.bullet_hit_sfx.play()
        except Exception:
            pass


def play_sfx(S, sfx_name, volume=0.5):
    """Play a cached sound effect by name (e.g. 'chop', 'mine', 'pickup', 'break')."""
    if getattr(S, "music_muted", False):
        return
    if not hasattr(S, "_sfx_cache"):
        S._sfx_cache = {}
    snd = S._sfx_cache.get(sfx_name)
    if snd is None:
        for ext in (".wav", ".mp3"):
            path = os.path.join(S.ASSETS_DIR, "sound", "sfx", f"{sfx_name}{ext}")
            if os.path.exists(path):
                try:
                    snd = pygame.mixer.Sound(path)
                    S._sfx_cache[sfx_name] = snd
                    break
                except Exception:
                    pass
    if snd:
        try:
            base_vol = getattr(S, "music_volume", 0.5)
            snd.set_volume(min(1.0, max(0.1, base_vol * volume * 1.6)))
            snd.play()
        except Exception:
            pass


# --- Destructible Objects Catalog Mapping ---
DESTRUCTIBLE_CAT_MAP = {
    120: "barrel", 121: "barrel", 122: "barrel",
    123: "crate", 124: "crate", 125: "crate",
    126: "pot", 127: "pot", 128: "pot",
    129: "sign", 130: "sign", 131: "sign",
    132: "signpost", 133: "signpost", 134: "signpost",
    135: "chest", 136: "chest", 137: "chest",
}
DESTRUCTIBLE_PIECES_MAP = {
    120: 140, 121: 140, 122: 140,
    123: 141, 124: 141, 125: 141,
    126: 142, 127: 142, 128: 142,
    129: 143, 130: 143, 131: 143,
    132: 144, 133: 144, 134: 144,
    135: 145, 136: 145, 137: 145,
}

def break_destructible(S, cx, cy, cell, cat_name, sx, sy, now):
    """Break a destructible object: plays sound, particles, animated break effect,
    leaves broken pieces on the ground, and either drops items or gets left as pieces only."""
    play_sfx(S, "break", 0.75)
    if hasattr(S, "hitstop_timer"):
        S.hitstop_timer = 0.035

    # Particles based on material
    if cat_name in ("barrel", "crate", "sign", "signpost"):
        p_colors = [(180, 140, 90), (139, 69, 19), (100, 60, 25), (210, 175, 120)]
    elif cat_name == "pot":
        p_colors = [(215, 185, 150), (185, 150, 110), (145, 110, 80), (240, 215, 180)]
    else:  # chest
        p_colors = [(255, 215, 60), (180, 140, 90), (220, 180, 100), (255, 240, 150)]

    if not hasattr(S, "particles"):
        S.particles = []
    for _ in range(18):
        S.particles.append({
            "x": sx + random.uniform(-14, 14),
            "y": sy - random.uniform(10, 35),
            "vx": random.uniform(-95, 95),
            "vy": random.uniform(-120, -30),
            "life": random.uniform(0.45, 0.75),
            "size": random.randint(3, 5),
            "color": random.choice(p_colors)
        })

    # Trigger break animation overlay
    if not hasattr(S, "break_effects"):
        S.break_effects = []
    S.break_effects.append({
        "cx": cx, "cy": cy,
        "category": cat_name,
        "timer": 0.0,
        "duration": 0.24,
    })

    # Update world tile cache to leave broken pieces on ground
    broken_tile = DESTRUCTIBLE_PIECES_MAP.get(cell[1], 140)
    S.iso.world.cache[(cx, cy)] = (cell[0], broken_tile, cell[2])
    S.iso.world.version += 1

    # Resource drops OR left as pieces only
    if not hasattr(S, "dropped_items"):
        S.dropped_items = []

    drop_roll = random.random()
    should_drop = False
    possible_drops = []

    if cat_name == "barrel":
        # 65% chance to drop food/wood/ammo, 35% left as pieces only
        should_drop = drop_roll < 0.65
        possible_drops = ["apple", "bread", "meat", "wood", "pistol_ammo"]
    elif cat_name == "crate":
        # 65% chance to drop materials/ores/ammo, 35% left as pieces only
        should_drop = drop_roll < 0.65
        possible_drops = ["wood", "brick", "coal", "iron", "ammo"]
    elif cat_name == "pot":
        # 65% chance to drop ores/diamond/key, 35% left as pieces only
        should_drop = drop_roll < 0.65
        possible_drops = ["gold", "diamond", "copper", "key"]
    elif cat_name == "chest":
        # Chests always burst with valuable loot!
        should_drop = True
        possible_drops = ["gold", "diamond", "ammo", "boots", "book", "shotgun_ammo", "key"]
    elif cat_name in ("sign", "signpost"):
        # Signs are mostly left as pieces only, small chance of stick
        should_drop = drop_roll < 0.15
        possible_drops = ["stick"]

    if should_drop and possible_drops:
        count = random.randint(2, 4) if cat_name == "chest" else random.randint(1, 3)
        for _ in range(count):
            dtype = random.choice(possible_drops)
            S.dropped_items.append({
                "cx": cx + random.uniform(-0.35, 0.35),
                "cy": cy + random.uniform(-0.35, 0.35),
                "type": dtype,
                "z": 20.0,
                "vz": random.uniform(160, 260),
                "vx": random.uniform(-1.8, 1.8),
                "vy": random.uniform(-1.8, 1.8)
            })
    else:
        # Left as pieces only!
        if not hasattr(S, "damage_popups"):
            S.damage_popups = []
        S.damage_popups.append({
            "x": sx + random.uniform(-4, 4),
            "y": sy - 38,
            "vy": -40.0,
            "life": 1.0,
            "max_life": 1.0,
            "text": "Pieces Only",
            "color": (200, 205, 215)
        })


def execute_mining_or_chopping(S, now, target_p, mx=None, my=None):
    """Perform responsive, impactful mining and woodchopping with tool affinity,
    audio-visual feedback, particles, prop shaking, floating damage, and resource drops."""
    if mx is None or my is None:
        mx, my = pygame.mouse.get_pos()

    my_weapon = getattr(S, 'my_weapon', 'AK47')
    wep = WEAPONS.get(my_weapon)
    px, py = target_p[0], target_p[1]
    aim = getattr(S, 'aim_angle', 0.0)

    # 1. Identify target candidates: cursor tile + nearby reach arc
    reach = 3.6 if my_weapon == "Sword" else 2.8
    candidates = []

    # Direct cursor hit (tested first)
    cursor_tile = tile_at_screen(S, mx, my)
    if cursor_tile:
        dist_c = math.hypot(px - (cursor_tile[0] + 0.5), py - (cursor_tile[1] + 0.5))
        if dist_c <= reach + 1.0:
            candidates.append((cursor_tile, 0.0))

    # Search all nearby world cells within reach and aim cone
    psx, psy = S.iso.to_screen(*S.iso.world_px(px, py))
    psy -= S.iso.elev(px, py) + 14
    rad = int(math.ceil(reach)) + 1
    ipx, ipy = int(round(px)), int(round(py))
    is_spin = getattr(S, "tool_spin_active", False)

    for dgx in range(-rad, rad + 1):
        for dgy in range(-rad, rad + 1):
            cx, cy = ipx + dgx, ipy + dgy
            if cursor_tile and (cx, cy) == cursor_tile:
                continue
            dist_tile = math.hypot(px - (cx + 0.5), py - (cy + 0.5))
            if dist_tile <= reach:
                tsx, tsy = S.iso.to_screen(*S.iso.world_px(cx + 0.5, cy + 0.5))
                tsy -= S.iso.elev(cx, cy)
                ang_to_tile = math.atan2(tsy - psy, tsx - psx)
                ang_diff = abs((ang_to_tile - aim + math.pi) % (2 * math.pi) - math.pi)
                if is_spin or dist_tile <= 1.4 or ang_diff < 1.4:
                    score = ang_diff + (dist_tile * 0.4)
                    candidates.append(((cx, cy), score))

    candidates.sort(key=lambda item: item[1])

    target_cell = None
    target_info = None
    for (cx, cy), _ in candidates:
        try:
            cell = S.iso.world.get(cx, cy)
            is_tree = cell[1] in range(48, 61) if cell[1] is not None else False
            is_rock_prop = (cell[1] in [62, 64, 65, 67, 68] or cell[1] in range(72, 82)) if cell[1] is not None else False
            is_rock_ground = cell[0] in [100, 101]
            is_rock = is_rock_prop or is_rock_ground
            is_destructible = cell[1] in getattr(iso, "DESTRUCTIBLE_PROPS", []) if cell[1] is not None else False
            if is_tree or is_rock or is_destructible:
                target_cell = (cx, cy)
                target_info = (cell, is_tree, is_rock, is_rock_ground, is_destructible)
                break
        except Exception:
            pass

    if not target_cell:
        return False

    cx, cy = target_cell
    cell, is_tree, is_rock, is_rock_ground, is_destructible = target_info

    # Screen coordinates for impact and requirement indicators
    sx, sy = S.iso.to_screen(*S.iso.world_px(cx, cy))
    sy -= S.iso.elev(cx, cy)

    # 2. Tool damage and effectiveness (Strict requirement: Axe for logs, Pickaxe for stone)
    base_dmg = getattr(wep, "damage", 25) if wep else 25
    dmg = base_dmg
    cat_name = DESTRUCTIBLE_CAT_MAP.get(cell[1], "barrel") if is_destructible else None

    if is_destructible:
        if cat_name in ("barrel", "crate", "sign", "signpost"):
            if my_weapon in ("Sword", "Axe"):
                dmg = max(45, int(base_dmg * 1.5))
            elif my_weapon in ("Mallet", "Hammer"):
                dmg = max(35, base_dmg)
            else:
                dmg = max(20, base_dmg)
        elif cat_name == "pot":
            dmg = max(35, base_dmg)
        elif cat_name == "chest":
            if my_weapon in ("Sword", "Pickaxe", "Hammer"):
                dmg = max(40, int(base_dmg * 1.3))
            else:
                dmg = max(25, base_dmg)
    elif is_tree:
        if my_weapon != "Axe":
            play_sfx(S, "mine", 0.4)
            return False
        dmg = max(35, int(base_dmg * 1.4))
    elif is_rock:
        if my_weapon != "Pickaxe":
            play_bullet_collision_sfx(S)
            return False
        dmg = max(35, int(base_dmg * 1.5))

    # 3. Deduct health
    if not hasattr(S, "prop_health"):
        S.prop_health = {}
    default_hp = 100
    if is_destructible:
        if cat_name == "pot":
            default_hp = 20
        elif cat_name == "chest":
            default_hp = 50
        elif cat_name in ("sign", "signpost"):
            default_hp = 25
        else:
            default_hp = 35

    current_health = S.prop_health.get((cx, cy), default_hp) - dmg
    S.prop_health[(cx, cy)] = current_health

    # 4. Sound & Prop Shake (screen shake removed for tools)
    if is_tree or (is_destructible and cat_name in ("barrel", "crate", "sign", "signpost")):
        play_sfx(S, "chop", 0.6)
    else:
        play_sfx(S, "mine", 0.6)
    emit_noise(S, cx, cy, 5.0)

    if not hasattr(S, "prop_shake"):
        S.prop_shake = {}
    S.prop_shake[(cx, cy)] = now + 0.22

    # 5. Impact particles
    if not hasattr(S, "particles"):
        S.particles = []
    sx, sy = S.iso.to_screen(*S.iso.world_px(cx, cy))
    sy -= S.iso.elev(cx, cy)
    if is_destructible:
        if cat_name in ("barrel", "crate", "sign", "signpost"):
            p_colors = [(180, 140, 90), (139, 69, 19), (100, 60, 25), (210, 175, 120)]
        elif cat_name == "pot":
            p_colors = [(215, 185, 150), (185, 150, 110), (145, 110, 80), (240, 215, 180)]
        else:
            p_colors = [(255, 215, 60), (180, 140, 90), (220, 180, 100), (255, 240, 150)]
    elif is_tree:
        p_colors = [(139, 69, 19), (180, 140, 90), (210, 175, 120), (100, 60, 25)]
    else:
        p_colors = [(140, 140, 140), (185, 185, 185), (220, 220, 220), (255, 215, 80)]
    for _ in range(7):
        S.particles.append({
            "x": sx + random.uniform(-10, 10),
            "y": sy - random.uniform(15, 42),
            "vx": random.uniform(-60, 60),
            "vy": random.uniform(-90, -25),
            "life": random.uniform(0.3, 0.5),
            "size": random.randint(2, 4),
            "color": random.choice(p_colors)
        })

    # 6. Floating damage indicator
    if not hasattr(S, "damage_popups"):
        S.damage_popups = []
    if is_destructible and cat_name == "chest":
        popup_col = (255, 225, 70)
    elif is_tree or (is_destructible and cat_name in ("barrel", "crate", "sign", "signpost")):
        popup_col = (255, 215, 90)
    else:
        popup_col = (120, 220, 255)

    S.damage_popups.append({
        "x": sx + random.uniform(-4, 4),
        "y": sy - 38,
        "vy": -50.0,
        "life": 0.8,
        "max_life": 0.8,
        "text": f"-{dmg}",
        "color": popup_col
    })

    # 7. Depletion & Resource drops
    if current_health <= 0:
        if is_destructible:
            break_destructible(S, cx, cy, cell, cat_name, sx, sy, now)
        else:
            play_sfx(S, "break", 0.7)
            for _ in range(16):
                S.particles.append({
                    "x": sx + random.uniform(-14, 14),
                    "y": sy - random.uniform(10, 45),
                    "vx": random.uniform(-95, 95),
                    "vy": random.uniform(-120, -35),
                    "life": random.uniform(0.45, 0.75),
                    "size": random.randint(3, 5),
                    "color": random.choice(p_colors)
                })

            if cell[1] is not None:
                S.iso.world.cache[(cx, cy)] = (cell[0], None, cell[2])
            if is_rock_ground:
                S.iso.world.cache[(cx, cy)] = (0, cell[1], cell[2])
            S.iso.world.version += 1

            if not hasattr(S, "dropped_items"):
                S.dropped_items = []
            if is_tree:
                drop_count = random.randint(2, 4)
                for _ in range(drop_count):
                    dtype = random.choice(["log", "stick", "wood"])
                    S.dropped_items.append({
                        "cx": cx + random.uniform(-0.35, 0.35),
                        "cy": cy + random.uniform(-0.35, 0.35),
                        "type": dtype,
                        "z": 20.0,
                        "vz": random.uniform(160, 260),
                        "vx": random.uniform(-1.8, 1.8),
                        "vy": random.uniform(-1.8, 1.8)
                    })
            elif is_rock:
                drop_count = random.randint(2, 4)
                if cell[0] == 101:
                    ores = ["gold", "diamond", "iron"]
                elif cell[0] == 100:
                    ores = ["iron", "coal", "copper"]
                else:
                    ores = ["coal", "copper", "iron"]
                for _ in range(drop_count):
                    dtype = random.choice(ores)
                    S.dropped_items.append({
                        "cx": cx + random.uniform(-0.35, 0.35),
                        "cy": cy + random.uniform(-0.35, 0.35),
                        "type": dtype,
                        "z": 20.0,
                        "vz": random.uniform(160, 260),
                        "vx": random.uniform(-1.8, 1.8),
                        "vy": random.uniform(-1.8, 1.8)
                    })

    return True


def _load_icon(path, size):
    try:
        return pygame.transform.smoothscale(pygame.image.load(path).convert_alpha(), (size, size))
    except pygame.error:
        return None


# --- fonts + widgets (rebuilt on reload; values carried over) ---
def _brand_font(S, size):
    """Bold display font for titles / the wordmark."""
    return pygame.font.SysFont(cfg.MONO_FONTS, size, bold=True)


def _build_fonts(S):
    S.small_font = pygame.font.SysFont(cfg.MONO_FONTS, 14)
    S.font = pygame.font.SysFont(cfg.MONO_FONTS, 19)
    S.body_font = pygame.font.SysFont(cfg.MONO_FONTS, 22)
    S.big_font = pygame.font.SysFont(cfg.MONO_FONTS, 26, bold=True)
    # headline/branding uses the bold display font; code/RTT stays mono for digits
    S.title_font = _brand_font(S, 34)
    S.brand_font = _brand_font(S, 52)  # the big "ASHERFALL" wordmark
    S.code_font = pygame.font.SysFont(cfg.MONO_FONTS, 52, bold=True)
    try:
        lp = os.path.join(S.ASSETS_DIR, "ui", "logo.png")
        if os.path.exists(lp):
            raw_l = pygame.image.load(lp).convert_alpha()
            lw = 460
            lh = int(raw_l.get_height() * (lw / raw_l.get_width()))
            S.brand_logo = pygame.transform.smoothscale(raw_l, (lw, lh))
            hlw = 260
            hlh = int(raw_l.get_height() * (hlw / raw_l.get_width()))
            S.header_logo = pygame.transform.smoothscale(raw_l, (hlw, hlh))
    except Exception:
        S.brand_logo = None
        S.header_logo = None


def update_menu_layout(S):
    if not hasattr(S, "menu_page"):
        S.menu_page = "root"
    if S.menu_page == "root":
        S.MENU_FOCUS = [S.play_btn, S.settings_btn, S.quit_btn]
    elif S.menu_page == "play":
        S.MENU_FOCUS = [S.menu_local_btn, S.host_local_coop_btn, S.menu_online_btn, S.menu_back_btn]
    elif S.menu_page == "online":
        S.MENU_FOCUS = [S.menu_join_btn, S.menu_host_btn, S.menu_back_btn]
    else:
        S.menu_page = "root"
        S.MENU_FOCUS = [S.play_btn, S.settings_btn, S.quit_btn]
        
    S.focus_index = 0
    MW, bh, gap = 260, 34, 6
    MX = 44
    y0 = cfg.HEIGHT - len(S.MENU_FOCUS) * (bh + gap) - 40
    for i, btn in enumerate(S.MENU_FOCUS):
        btn.rect = pygame.Rect(MX, y0 + i * (bh + gap), MW, bh)


def _build_ui(S):
    # server address lives on the JOIN / HOST setup panels
    S.addr_input = TextInput(LEFT_X, CARD_Y + 56, cfg.CARD_W - PAD * 2, 36,
                             "SERVER ADDRESS", cfg.DEFAULT_SERVER)
    S.code_input = TextInput(LEFT_X, CARD_Y + 132, cfg.CARD_W - PAD * 2, 40, "ROOM CODE")

    # lobby settings + username live on the SETUP screen (single / local / join / host)
    S.lobby_name_input = TextInput(LEFT_X, CARD_Y + 116, cfg.CARD_W - PAD * 2, 36,
                                   "LOBBY NAME (OPTIONAL)")
    S.max_players_stepper = Stepper(LEFT_X, CARD_Y + 176, 200, 34, "PLAYERS", 2, 2, 4)
    S.name_inputs = [
        TextInput(LEFT_X,  CARD_Y + 240, COL_W, 34, "P1 NAME"),
        TextInput(RIGHT_X, CARD_Y + 240, COL_W, 34, "P2 NAME"),
        TextInput(LEFT_X,  CARD_Y + 296, COL_W, 34, "P3 NAME"),
        TextInput(RIGHT_X, CARD_Y + 296, COL_W, 34, "P4 NAME"),
    ]
    S.setup_confirm_btn = Button(CENTER_X - 130, CARD_Y + 340, 260, 46, "CONFIRM")

    def _mb(label):
        return Button(0, 0, 260, 34, label)
    
    S.play_btn = _mb("PLAY")
    S.settings_btn = _mb("SETTINGS")
    S.quit_btn = _mb("QUIT")
    S.menu_local_btn = _mb("SOLO")
    S.menu_online_btn = _mb("ONLINE CO-OP")
    S.menu_join_btn = _mb("JOIN")
    S.menu_host_btn = _mb("HOST")
    S.host_local_coop_btn = _mb("LOCAL CO-OP")
    S.host_online_coop_btn = _mb("ONLINE CO-OP")
    S.menu_back_btn = _mb("BACK")

    # in-world pause menu
    PR = pygame.Rect(CENTER_X - 170, cfg.HEIGHT // 2 - 175, 340, 350)
    S.pause_rect = PR
    py0, pbh, pgap = PR.y + 88, 44, 12
    def _pb(i, label):
        return Button(CENTER_X - 120, py0 + i * (pbh + pgap), 240, pbh, label)
    S.pause_resume_btn = _pb(0, "RESUME")
    S.pause_help_btn = _pb(1, "HOW TO PLAY")
    S.pause_settings_btn = _pb(2, "SETTINGS")
    S.pause_quit_btn = _pb(3, "QUIT TO MENU")

    S.close_btn = IconButton(cfg.WIDTH - 42, 14, 30, kind="close")  # quits the app
    S.panel_x = IconButton(CARD.right - 42, CARD_Y + 12, 28, kind="close")  # closes current panel
    S.help_icon_btn = IconButton(cfg.WIDTH - 42, cfg.HEIGHT - 42, 30, kind="help")

    S.music_icon = _load_icon(os.path.join(S.ASSETS_DIR, "music.png"), 26)
    S.sound_icon = _load_icon(os.path.join(S.ASSETS_DIR, "sound.png"), 26)

    # Column 1
    col1_x = SETTINGS_RECT.x + 40
    y = SETTINGS_RECT.y + 110
    S.volume_slider = Slider(col1_x, y, 200, value=cfg.MUSIC_VOLUME, label="MUSIC")
    S.cam_smooth_slider = Slider(col1_x, y + 80, 200, value=0.5, label="CAMERA SMOOTHING")
    
    # Column 2
    col2_x = SETTINGS_RECT.x + 320
    S.render_dist_stepper = Stepper(col2_x, y, 200, 30, "RENDER DISTANCE", 6, 2, 16)
    S.fps_toggle = Toggle(col2_x, y + 80, 56, 28, "SHOW FPS", value=False)

    S.music_toggle = Toggle(col1_x, y + 160, 56, 28, "MUTE", value=False)
    S.keybinds_btn = Button(col2_x, y + 295, 200, 36, "KEYBINDS")

    transport_y = SETTINGS_RECT.y + 460
    tw, th, tgap, mid_w = 100, 40, 16, 140
    total = tw * 2 + mid_w + tgap * 2
    tx = SETTINGS_RECT.centerx - total // 2
    S.prev_btn = Button(tx, transport_y, tw, th, "PREV")
    S.play_pause_btn = Button(S.prev_btn.rect.right + tgap, transport_y, mid_w, th, "PAUSE")
    S.next_btn = Button(S.play_pause_btn.rect.right + tgap, transport_y, tw, th, "NEXT")
    S.settings_close_btn = Button(SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 52, 160, 40, "CLOSE")
    S.settings_x = IconButton(SETTINGS_RECT.right - 40, SETTINGS_RECT.y + 12, 26, kind="close")


    update_menu_layout(S)


def init(S):
    """First-time setup. Creates everything, including persistent state."""
    _build_fonts(S)
    _build_ui(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)
    # a slowly drifting procedural world used as the menu backdrop
    S.menu_iso = iso.Iso(seed=90210, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    S.vignette = ui.make_vignette(cfg.WIDTH, cfg.HEIGHT)
    S.paused = False

    # Multi-Controller Registry (PlayStation, Nintendo, Xbox)
    if not hasattr(S, "controller_mgr"):
        S.controller_mgr = controller.ControllerManager(S.ASSETS_DIR)
    else:
        S.controller_mgr.refresh_devices()
    S.joysticks = S.controller_mgr.joysticks
    S.pad = S.controller_mgr.get_icons()

    S.state = STATE_MENU
    S.room_code = ""
    S.lobby_name = ""
    S.max_players = 2
    S.player_count = 1
    S.status_msg = ""
    S.last_rtt = None
    S.ping_count = 0
    S.pong_count = 0
    S.last_ping_time = 0.0
    S.last_pong_time = 0.0
    S.setup_mode = "single"    # "single", "join" or "host"
    S.local_players = []       # list of [wx, wy] world-pixel positions on the map
    S.local_names = []         # per-player usernames, parallel to local_players
    S.username = ""            # this client's name (host / join)

    # the endless isometric dirt world every mode is played on
    S.iso = iso.Iso(seed=1337, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    S.me = [0.0, 0.0, 0.0, 0.0]   # this client's avatar (online), grid cell fx,fy,z,vz
    S.peers = {}                  # id -> {"p":[fx,fy,z], "name":str, "color":rgb, "seen":t}
    S.client_id = ""              # unique per session (name#rand)
    S.last_pos_sent = 0.0

    # chat (Minecraft-style) + push-to-talk voice
    S.chat_open = False
    S.chat_input = ""
    S.chat_log = []
    S.lobby_players = {}
    S.is_host = False
    S.lobby_ready = False
    S.lobby_start_btn = None
    S.lobby_ready_btn = None
    S.lobby_kick_btns = {}
    S.lobby_restrict_btns = {}
    S.lobby_player_list = []
               # list of {"t":ts, "name":str, "color":rgb, "text":str}
    S.voice = voicelib.Voice()
    S.show_keys = False           # keybinds panel
    load_game_icons(S)
    load_cursors(S)

    S.focus_index = 0  # PLAY focused by default
    S.using_controller = False
    S.show_settings = False
    S.spawn_cell = None      # original spawn, marked with a pixel-art X
    S.pressed_tile = None    # tile clicked (drawn white)
    S.pressed_until = 0.0    # timestamp the white tile expires (debug: 5s)

    S.music_track_index = -1
    S.music_volume = cfg.MUSIC_VOLUME
    S.music_muted = False
    S.music_paused = False
    play_next_track(S)
    for w in WEAPONS.values():
        if w.image is None:
            w.load(S.ASSETS_DIR)
    S.enemy_mgr = EnemyManager(S.ASSETS_DIR)
    S.enemy_manager = S.enemy_mgr
    S.player_health = 100
    S.prev_player_health = 100
    S.player_hit_timer = 0.0
    S.play_bullet_sfx = lambda: play_bullet_collision_sfx(S)
    init_inventory(S)


def rebuild(S):
    """Called after a hot reload. Rebuilds fonts/widgets/visuals from the new
    code, but preserves the live session: connection, music, game state, and
    the values the user has typed/adjusted."""
    for w in WEAPONS.values():
        if w.image is None:
            w.load(S.ASSETS_DIR)
    if not hasattr(S, "enemy_mgr") or S.enemy_mgr is None:
        S.enemy_mgr = EnemyManager(S.ASSETS_DIR)
    S.enemy_manager = S.enemy_mgr
    if not hasattr(S, "player_health"):
        S.player_health = 100
    if not hasattr(S, "prev_player_health"):
        S.prev_player_health = S.player_health
    if not hasattr(S, "player_hit_timer"):
        S.player_hit_timer = 0.0
    S.play_bullet_sfx = lambda: play_bullet_collision_sfx(S)
    init_inventory(S)
    vals = {
        "addr": S.addr_input.value, "code": S.code_input.value,
        "names": [n.value for n in S.name_inputs],
        "lobby": S.lobby_name_input.value, "maxp": S.max_players_stepper.value,
        "vol": S.volume_slider.value, 
        "mute": S.music_toggle.value,
    }
    _build_fonts(S)
    _build_ui(S)
    load_game_icons(S)
    load_cursors(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)
    # backdrop world + vignette persist across reloads; create if this session
    # predates them (first hot-reload after the feature was added)
    if not hasattr(S, "menu_iso"):
        S.menu_iso = iso.Iso(seed=90210, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    else:
        S.menu_iso.tiles = iso.load_tiles(S.menu_iso.scale)
    if hasattr(S, "iso") and S.iso:
        S.iso.tiles = iso.load_tiles(S.iso.scale)
    S.vignette = ui.make_vignette(cfg.WIDTH, cfg.HEIGHT)
    S.addr_input.value = vals["addr"]
    S.code_input.value = vals["code"]
    for inp, v in zip(S.name_inputs, vals["names"]):
        inp.value = v
    S.lobby_name_input.value = vals["lobby"]
    S.max_players_stepper.value = vals["maxp"]
    S.volume_slider.value = vals["vol"]
    S.music_toggle.value = vals["mute"]


# --- actions ---
def update_menu_bg(S, dt):
    """Slowly pan the backdrop world so the menu feels alive."""
    if not hasattr(S, "_menu_pan_acc"):
        S._menu_pan_acc = 0.0
    S._menu_pan_acc += dt
    if S._menu_pan_acc >= 0.065:
        S.menu_iso.cam_x += 15 * S._menu_pan_acc
        S.menu_iso.cam_y += 7.5 * S._menu_pan_acc
        S._menu_pan_acc = 0.0


def activate_focused(S):
    widget = S.MENU_FOCUS[S.focus_index]
    if widget is getattr(S, "settings_btn", None):
        return "settings"
    elif widget is getattr(S, "help_icon_btn", None):
        return "help"
    elif widget is getattr(S, "quit_btn", None):
        return "quit"
    
    if widget is getattr(S, "play_btn", None):
        S.menu_page = "play"
        update_menu_layout(S)
    elif widget is getattr(S, "menu_local_btn", None):
        go_setup(S, "single")
    elif widget is getattr(S, "menu_online_btn", None):
        S.menu_page = "online"
        update_menu_layout(S)
    elif widget is getattr(S, "menu_join_btn", None):
        go_setup(S, "join")
    elif widget is getattr(S, "menu_host_btn", None):
        start_wake_server(S)
    elif widget is getattr(S, "host_local_coop_btn", None):
        go_setup(S, "local")
    elif widget is getattr(S, "menu_back_btn", None):
        if S.menu_page == "online":
            S.menu_page = "play"
        elif S.menu_page == "play":
            S.menu_page = "root"
        update_menu_layout(S)
        
    return None


def ensure_local_server_running(S, port=8080):
    """Ensure relay server is running on localhost/127.0.0.1 when hosting."""
    import socket, subprocess, sys, os, time
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True  # already running
    except OSError:
        pass

    curr = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(curr, "server", "server.py"),
        os.path.join(os.path.dirname(curr), "server", "server.py"),
    ]
    for s_path in candidates:
        if os.path.exists(s_path):
            try:
                proc = subprocess.Popen(
                    [sys.executable, s_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                S.server_proc = proc
                print(f"[auto-server] Started local relay server (PID {proc.pid}) on port {port}")
                time.sleep(0.4)
                return True
            except Exception as e:
                print(f"[auto-server] Failed to start server: {e}")
                break
    return False


def start_wake_server(S):
    S.state = STATE_WAKE
    S.wake_start_time = time.time()
    
    def _ping_server():
        import urllib.request, urllib.error
        http_url = cfg.DEFAULT_SERVER.replace("wss://", "https://").replace("ws://", "http://")
        if "localhost" in http_url or "127.0.0.1" in http_url:
            ensure_local_server_running(S)
        try:
            urllib.request.urlopen(http_url, timeout=10)
            S.server_woken = True
        except urllib.error.HTTPError as e:
            if e.code == 426:
                S.server_woken = True
            else:
                S.server_wake_failed = True
        except Exception as e:
            if "localhost" in http_url or "127.0.0.1" in http_url:
                import socket
                try:
                    with socket.create_connection(("127.0.0.1", 8080), timeout=0.4):
                        S.server_woken = True
                        return
                except Exception:
                    pass
            S.server_wake_failed = True
        
    S.server_woken = False
    S.server_wake_failed = False
    import threading
    threading.Thread(target=_ping_server, daemon=True).start()


def go_back(S):
    """Per-panel close (X): back out to the main menu."""
    if S.state == STATE_SETUP:
        S.state = STATE_MENU
    else:
        reset_to_menu(S, "")


def setup_name_count(S):
    return max(2, min(S.max_players_stepper.value, LOCAL_MAX))


def go_setup(S, mode):
    S.setup_mode = mode
    S.max_players_stepper.hi = LOCAL_MAX
    S.max_players_stepper.value = min(S.max_players_stepper.value, S.max_players_stepper.hi)
    S.status_msg = ""
    S.state = STATE_SETUP


def reset_to_menu(S, message):
    S.conn.close()
    S.state = STATE_MENU
    S.menu_page = "root"
    update_menu_layout(S)
    S.status_msg = message
    S.last_rtt = None
    S.ping_count = S.pong_count = 0


def do_host(S):
    addr = S.addr_input.value.strip()
    if not addr:
        S.status_msg = "Enter a server address first."
        return
    if "://" not in addr:
        addr = "ws://" + addr
    elif addr.startswith("http://"):
        addr = "ws://" + addr[7:]
    elif addr.startswith("https://"):
        addr = "wss://" + addr[8:]

    if "localhost" in addr or "127.0.0.1" in addr:
        ensure_local_server_running(S)

    S.is_host = True
    S.room_code = ""
    S.username = S.name_inputs[0].value.strip() or "Host"
    S.lobby_ready_btn = None
    enter_world(S)
    S.conn.connect(addr, {
        "type": "host",
        "lobby_name": S.lobby_name_input.value.strip(),
        "max_players": S.max_players_stepper.value,
        "username": S.username,
    }, S.client_id)
    S.status_msg = "Connecting..."
    S.state = STATE_WAIT


def do_join(S):
    addr = S.addr_input.value.strip()
    code = S.code_input.value.strip().upper()
    if not addr:
        S.status_msg = "Enter a server address first."
        return
    if not code:
        S.status_msg = "Enter a room code first."
        return
    if "://" not in addr:
        addr = "ws://" + addr
    elif addr.startswith("http://"):
        addr = "ws://" + addr[7:]
    elif addr.startswith("https://"):
        addr = "wss://" + addr[8:]

    S.is_host = False
    S.room_code = ""
    S.username = S.name_inputs[0].value.strip() or "Player"
    enter_world(S)
    S.conn.connect(addr, {"type": "join", "code": code, "username": S.username}, S.client_id)
    S.status_msg = "Joining..."
    S.state = STATE_WAIT


def do_single(S):
    S.lobby_name = "Single Player"
    fx, fy = S.iso.find_free(0.0, 0.0)
    S.local_players = [[fx, fy, 0.0, 0.0]]
    S.local_names = [S.name_inputs[0].value.strip() or "P1"]
    S.spawn_cell = (fx, fy)
    snap_camera(S, fx, fy)
    S.status_msg = ""
    init_inventory(S)
    S.state = STATE_LOCAL
    if hasattr(S, "enemy_mgr") and S.enemy_mgr:
        S.enemy_mgr.enemies = []
        if hasattr(S.enemy_mgr, "spawn_initial_encounters"):
            S.enemy_mgr.spawn_initial_encounters(S, fx, fy, count=4)


def do_local(S):
    n = max(2, min(S.max_players_stepper.value, LOCAL_MAX))
    S.lobby_name = S.lobby_name_input.value.strip() or "Local Co-op"
    S.local_players = []
    S.local_names = []
    # fan the party out around the origin, each on a free (non-solid) cell
    for i in range(n):
        ang = (i / n) * 6.28318
        fx, fy = S.iso.find_free(math.cos(ang) * 3, math.sin(ang) * 3)
        S.local_players.append([fx, fy, 0.0, 0.0, 0.0, 0.0, 0.0])
        S.local_names.append(S.name_inputs[i].value.strip() or f"P{i+1}")
    S.spawn_cell = tuple(centroid(S.local_players))
    snap_camera(S, *centroid(S.local_players))
    S.status_msg = ""
    init_inventory(S)
    S.state = STATE_LOCAL
    if hasattr(S, "enemy_mgr") and S.enemy_mgr:
        S.enemy_mgr.enemies = []
        cx, cy = centroid(S.local_players)
        if hasattr(S.enemy_mgr, "spawn_initial_encounters"):
            S.enemy_mgr.spawn_initial_encounters(S, cx, cy, count=4 + n)


# --- world play helpers (shared by single / local / online) ---
def iso_move(S, p, up, down, left, right, dash, roll, dt, pad_dx=0.0, pad_dy=0.0):
    """Walk the isometric grid axes with collision, analog stick support, and dashing."""
    if len(p) < 8:
        p.extend([0.0, 0.0, 0.0, 0.0, 0.0])  # ensure dash and roll states exist
        
    dgx = dgy = 0.0
    if up:    dgy -= 1
    if down:  dgy += 1
    if left:  dgx -= 1
    if right: dgx += 1

    # Analog stick screen-relative translation into isometric grid
    if abs(pad_dx) > 0.15 or abs(pad_dy) > 0.15:
        hw = getattr(S.iso, "HALF_W", 32)
        hh = getattr(S.iso, "HALF_H", 16)
        mag = min(1.0, math.hypot(pad_dx, pad_dy))
        ux = pad_dx / max(0.001, math.hypot(pad_dx, pad_dy))
        uy = pad_dy / max(0.001, math.hypot(pad_dx, pad_dy))
        dgx_stick = (ux / hw + uy / hh)
        dgy_stick = (uy / hh - ux / hw)
        L_stick = math.hypot(dgx_stick, dgy_stick)
        if L_stick > 0:
            dgx += (dgx_stick / L_stick) * mag
            dgy += (dgy_stick / L_stick) * mag
    
    if (dash or roll) and p[4] <= 0 and (dgx or dgy):
        p[4] = 0.8  # cooldown
        emit_noise(S, p[0], p[1], 2.0)  # Perception 2.0: 2-tile sprint noise
        L = math.hypot(dgx, dgy)
        if dash:
            p[5] = (dgx / L) * 45.0
            p[6] = (dgy / L) * 45.0
            S.shake = 0.25
            p[7] = 0.0
        else:
            p[5] = (dgx / L) * 20.0
            p[6] = (dgy / L) * 20.0
            S.shake = 0.05
            p[7] = 1.0
        
    if isinstance(p[4], str): p[4] = 0.0
    if p[4] > 0: p[4] -= dt
    
    # friction on dash velocity
    p[5] *= (0.001 ** dt)
    p[6] *= (0.001 ** dt)
    
    if dgx or dgy:
        L = math.hypot(dgx, dgy)
        step = SPEED_CELLS * dt
        # Swimming in water reduces movement speed to 65% when not jumping/airborne
        if p[2] <= JUMP_CLEAR and hasattr(S, "iso") and S.iso.is_water(p[0], p[1]):
            step *= 0.65
        dgx = dgx / L * step
        dgy = dgy / L * step
        
    total_dx = dgx + p[5] * dt
    total_dy = dgy + p[6] * dt
    
    if not (total_dx or total_dy):
        return
        
    iso = S.iso
    airborne = p[2] > JUMP_CLEAR
    nx, ny = p[0] + total_dx, p[1] + total_dy
    
    if airborne or not iso.solid(nx, ny):
        p[0] = nx
        p[1] = ny
    else:
        if not iso.solid(nx, p[1]):
            p[0] = nx
            p[5] = 0  # kill x velocity if walled
        elif not iso.solid(p[0], ny):
            p[1] = ny
            p[6] = 0  # kill y velocity if walled

    # Player walking dust particles
    if not airborne and (dgx != 0 or dgy != 0 or abs(p[5]) > 1.0 or abs(p[6]) > 1.0):
        if not hasattr(S, "particles"):
            S.particles = []
        p_timer = getattr(S, "_player_step_timer", 0.0) - dt
        if p_timer <= 0:
            p_timer = 0.11
            wx, wy = S.iso.world_px(p[0], p[1])
            sx, sy = S.iso.to_screen(wx, wy)
            sy -= S.iso.elev(p[0], p[1])
            import random
            cell = S.iso.world.get(round(p[0]), round(p[1])) if hasattr(S, "iso") and S.iso else None
            is_water = cell is not None and cell[0] in getattr(iso, "ALL_WATER_TILES", [])
            for _ in range(random.randint(1, 2)):
                S.particles.append({
                    "x": sx + random.uniform(-4, 4),
                    "y": sy + random.uniform(-2, 2),
                    "vx": -total_dx * random.uniform(25, 45) + random.uniform(-6, 6),
                    "vy": -random.uniform(14, 28) if is_water else -random.uniform(8, 20),
                    "life": random.uniform(0.2, 0.35) if is_water else random.uniform(0.2, 0.32),
                    "size": random.randint(2, 4) if is_water else random.randint(2, 3),
                    "color": random.choice([(180, 230, 255), (140, 205, 255), (255, 255, 255), (100, 180, 240)]) if is_water else random.choice([(185, 175, 155), (150, 140, 125), (205, 195, 175), (135, 125, 110)])
                })
        S._player_step_timer = p_timer
            
    # Juicy Knockback: If dashing fast, push other local players
    if abs(p[5]) > 10 or abs(p[6]) > 10:
        if hasattr(S, 'local_players'):
            for other in S.local_players:
                if other is not p:
                    dist = math.hypot(other[0] - p[0], other[1] - p[1])
                    if dist < 0.8 and abs(other[2] - p[2]) < 10:  # hit radius
                        other[5] += p[5] * 0.8  # transfer momentum
                        other[6] += p[6] * 0.8
                        p[5] *= 0.2  # slow self down on impact
                        p[6] *= 0.2
                        S.shake = max(S.shake, 0.8)  # bigger shake on hit!


def apply_jump(p, dt):
    """p is [wx, wy, z, vz]; integrate the hop and land on the ground plane."""
    p[3] -= GRAVITY * dt
    p[2] += p[3] * dt
    if p[2] <= 0.0:
        p[2] = 0.0
        p[3] = 0.0


def try_jump(p):
    if p[2] <= 0.0:            # only when grounded
        p[3] = JUMP_V


def centroid(points):
    n = len(points) or 1
    return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n


_CIRCLE_OFFSETS = {}
def get_circle_offsets(R):
    offsets = _CIRCLE_OFFSETS.get(R)
    if offsets is None:
        offsets = []
        R2 = R * R
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                if dx * dx + dy * dy <= R2:
                    offsets.append((dx, dy))
        _CIRCLE_OFFSETS[R] = offsets
    return offsets

_VIS_CACHE_KEY = None
_VIS_CACHE_SET = set()

def visible_cells(S):
    """Union of circular reveal areas around every on-screen player."""
    global _VIS_CACHE_KEY, _VIS_CACHE_SET
    if S.state == STATE_TEST:
        pts = [S.me] + [pr["p"] for pr in S.peers.values()]
    else:
        pts = S.local_players
    R = S.render_dist_stepper.value
    key = tuple((round(p[0]), round(p[1])) for p in pts) + (R,)
    if key == _VIS_CACHE_KEY:
        return _VIS_CACHE_SET

    offsets = get_circle_offsets(R)
    cells = set()
    for p in pts:
        cx, cy = round(p[0]), round(p[1])
        for dx, dy in offsets:
            cells.add((cx + dx, cy + dy))
    _VIS_CACHE_KEY = key
    _VIS_CACHE_SET = cells
    return cells


def tile_at_screen(S, mx, my):
    """Canvas mouse position -> the grid cell whose (elevated) top-face diamond
    is under the cursor. Tests nearby cells and picks the front-most one so the
    entire visible top face is clickable, not just a quadrant."""
    iso = S.iso
    HW, HH = iso.HALF_W, iso.HALF_H
    base = iso.cell_at(mx + iso.cam_x, my + iso.cam_y)   # flat guess to bound the search
    best = None
    for dgy in range(-3, 4):
        for dgx in range(-3, 4):
            gx, gy = base[0] + dgx, base[1] + dgy
            cx, cy = _tile_anchor(S, gx, gy)            # top-face centre
            if abs(mx - cx) / HW + abs(my - cy) / HH <= 1.0:   # inside the diamond
                key = (gx + gy, iso.world.get(gx, gy)[2])       # front-most, then taller
                if best is None or key > best[0]:
                    best = (key, (gx, gy))
    return best[1] if best else base


def _tile_anchor(S, fx, fy):
    """Screen position of a grid cell's ground center, following elevation."""
    sx, sy = S.iso.to_screen(*S.iso.world_px(fx, fy))
    return int(sx), int(sy - S.iso.elev(fx, fy))


def draw_spawn_marker(S):
    """Draw the tilex1 marker tile on the original spawn cell, seated like a
    normal world tile (position + elevation lift)."""
    cell = getattr(S, "spawn_cell", None)
    img = getattr(S, "spawn_img", None)
    if not cell or not img:
        return
    iso = S.iso
    gx, gy = round(cell[0]), round(cell[1])
    _, _, level = iso.world.get(gx, gy)
    HW, HH = iso.HALF_W, iso.HALF_H
    sx = (gx - gy) * HW - iso.cam_x
    sy = (gx + gy) * HH - iso.cam_y
    oy = sy - level * iso.LIFT
    if sx < -iso.TILE_PX or sx > cfg.WIDTH + iso.TILE_PX or oy < -iso.TILE_PX or oy > cfg.HEIGHT + iso.TILE_PX:
        return
    tile = pygame.transform.scale(img, (iso.TILE_PX, iso.TILE_PX))
    S.screen.blit(tile, (int(sx - HW), int(oy - HH)))


def draw_tile_press(S):
    """While a tile is held (mouse down), recolor only its top face white — the
    cube sides stay untouched (they're hidden when surrounded anyway)."""
    cell = getattr(S, "pressed_tile", None)
    if not cell or time.time() > getattr(S, "pressed_until", 0):
        return
    gx, gy = cell
    iso = S.iso
    base, prop, level = iso.world.get(gx, gy)
    HW, HH, TPX = iso.HALF_W, iso.HALF_H, iso.TILE_PX
    sx = (gx - gy) * HW - iso.cam_x
    sy = (gx + gy) * HH - iso.cam_y
    oy = sy - level * iso.LIFT
    w = iso.tiles[base].copy()
    w.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)      # opaque -> white
    mask = pygame.Surface((TPX, TPX), pygame.SRCALPHA)                  # top-face diamond only
    pygame.draw.polygon(mask, (255, 255, 255, 255),                     # centred at local 2*HH
                        [(HW, HH), (2 * HW, 2 * HH), (HW, 3 * HH), (0, 2 * HH)])
    w.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)          # keep white only on top face
    S.screen.blit(w, (sx - HW, oy - HH))
    if prop is not None:
        prop_lift = int(7 * iso.scale)
        S.screen.blit(iso.tiles[prop], (sx - HW, oy - HH - prop_lift))


def draw_avatar(S, p, color, name, me=False, aim_angle=0.0, weapon_name="AK47", pressing=False, is_hit=False):
    """A rover on the terrain at grid cell [fx, fy, z, vz]; z lifts it mid-jump."""
    screen = S.screen
    hit = bool(is_hit or (me and getattr(S, "player_hit_timer", 0.0) > 0))
    fx, fy, z = p[0], p[1], p[2]
    PR = max(6, int(PLAYER_R * S.iso.scale / 2))   # scale the body with zoom
    wx, wy = S.iso.world_px(fx, fy)
    sx, sy = S.iso.to_screen(wx, wy)
    sy -= S.iso.elev(fx, fy)                       # follow the tile elevation
    if sx < -60 or sx > cfg.WIDTH + 60 or sy < -60 or sy > cfg.HEIGHT + 120:
        return
    import math
    is_dead = me and getattr(S, "player_is_dead", False)
    if is_dead:
        death_timer = getattr(S, "player_death_timer", 2.0)
        prog = max(0.0, min(1.0, (2.0 - death_timer) / 2.0))

        # Collapsing spin
        collapse_scale = max(0.05, 1.0 - prog * 0.95)
        cur_pr = max(2, int(PR * collapse_scale))

        # Draw fading collapsed body
        body_alpha = int(255 * max(0.0, 1.0 - prog * 1.1))
        if body_alpha > 0:
            surf_dim = cur_pr * 2 + 4
            dead_surf = pygame.Surface((surf_dim, surf_dim), pygame.SRCALPHA)
            pygame.draw.circle(dead_surf, (220, 60, 60, body_alpha), (surf_dim // 2, surf_dim // 2), cur_pr)
            pygame.draw.circle(dead_surf, (255, 255, 255, body_alpha), (surf_dim // 2, surf_dim // 2), cur_pr, 2)
            screen.blit(dead_surf, (int(sx) - surf_dim // 2, int(sy - PR - z) - surf_dim // 2))

        # Rising ethereal soul orb
        orb_y = int(sy - PR - z) - int(prog * 65.0 * S.iso.scale)
        orb_alpha = int(230 * max(0.0, 1.0 - prog * 0.4))
        orb_r = max(4, int(7 * S.iso.scale))
        orb_surf = pygame.Surface((orb_r * 4, orb_r * 4), pygame.SRCALPHA)
        # Glow
        pygame.draw.circle(orb_surf, (140, 220, 255, orb_alpha // 3), (orb_r * 2, orb_r * 2), orb_r * 2)
        # Core
        pygame.draw.circle(orb_surf, (230, 250, 255, orb_alpha), (orb_r * 2, orb_r * 2), orb_r)
        screen.blit(orb_surf, (int(sx) - orb_r * 2, orb_y - orb_r * 2))

        # Floating wisps around soul orb
        now_t = pygame.time.get_ticks() / 1000.0
        for w_i in range(3):
            w_ang = now_t * 4.0 + w_i * (math.pi * 2 / 3)
            wx_p = sx + math.cos(w_ang) * (orb_r * 1.5)
            wy_p = orb_y + math.sin(w_ang) * (orb_r * 0.8)
            pygame.draw.circle(screen, (180, 240, 255, max(0, orb_alpha - 50)), (int(wx_p), int(wy_p)), max(1, int(2 * S.iso.scale)))

        # Respawn banner
        secs_left = max(1, math.ceil(death_timer))
        draw_text(screen, f"RESPAWNING IN {secs_left}s...", S.small_font, 0, int(sy - PR - z) - PR - 30, (255, 200, 80), center_x=int(sx))
        return

    # Swimming / Waterline effects or ground shadow
    in_water = (z <= JUMP_CLEAR and hasattr(S, "iso") and S.iso.is_water(fx, fy))
    if in_water:
        t = pygame.time.get_ticks() / 1000.0
        rw = int((PR + 6) * 1.3)
        rh = int((PR // 2 + 3) * 1.3)
        for ring_i in range(2):
            phase = ((t * 1.3 + ring_i * 0.5) % 1.0)
            cur_w = max(2, int(rw * (0.5 + phase * 0.6)))
            cur_h = max(2, int(rh * (0.5 + phase * 0.6)))
            rip_alpha = int(145 * (1.0 - phase))
            rip_surf = pygame.Surface((cur_w * 2, cur_h * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(rip_surf, (160, 230, 255, rip_alpha), rip_surf.get_rect(), max(1, int(1.5 * S.iso.scale)))
            screen.blit(rip_surf, (int(sx - cur_w), int(sy - cur_h)))
        # Waterline wave bobbing
        sy += math.sin(t * 5.2 + fx * 2.0) * (2.2 * S.iso.scale)
    else:
        # ground shadow stays on the tile; it shrinks as you rise
        shr = max(0.4, 1.0 - z / 160.0)
        sw, sh = int((PR * 2 + 4) * shr), int((PR + 2) * shr)
        shadow = pygame.Surface((sw, sh), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 90), shadow.get_rect())
        screen.blit(shadow, (int(sx) - sw // 2, int(sy) - sh // 2))

    ix, iy = int(sx), int(sy - PR - z)             # body lifted by jump height
    if in_water:
        iy += int(3 * S.iso.scale)                  # submerged slightly into water

    hit = is_hit or (me and getattr(S, "player_hit_timer", 0.0) > 0)
    roll_angle = 0
    if len(p) >= 8 and p[4] > 0.4 and p[7] > 0.5:
        roll_phase = (0.8 - p[4]) / 0.4
        roll_angle = roll_phase * math.pi * 2

    is_tool = weapon_name in ["Sword", "Axe", "Pickaxe", "Shovel", "Fishing_rod", "Hammer", "Scythe", "Mallet"]
    is_sword = (weapon_name == "Sword")
    wep = WEAPONS.get(weapon_name)

    # 1. Orbital Ring System: Player is Sun, Sword & Tools orbit as Earth on the ring
    tool_is_behind = False
    if is_tool:
        is_spinning = (me and getattr(S, "tool_spin_active", False))
        orbit_rx = int(32 * S.iso.scale) if is_spinning else int(28 * S.iso.scale)
        orbit_ry = int(20 * S.iso.scale) if is_spinning else int(18 * S.iso.scale)

        # Orbit angle follows mouse aim angle, with swing arc if pressing or FULL 360 rotation if spinning
        tool_ang = aim_angle
        tool_angle_offset = 0.0
        self_spin_angle = 0.0

        if is_spinning:
            import time
            now_t = time.time()
            spin_start = getattr(S, "tool_spin_start", now_t)
            spin_dur = getattr(S, "tool_spin_dur", 0.20)
            prog = min(1.0, max(0.0, (now_t - spin_start) / max(0.01, spin_dur)))
            base_ang = getattr(S, "tool_spin_base_ang", aim_angle)
            
            # 1. Earth orbits around the Sun: completes a FULL 360 degree rotation on the circle
            tool_ang = base_ang + (prog * 2.0 * math.pi)
            
            # 2. Earth spins on its own axis/line: spins rapidly around its own center
            self_spin_angle = prog * 4.0 * math.pi  # 2 full self-rotations (720 deg) during the revolution
        elif pressing:
            import time
            t = time.time() * 18
            swing = math.sin(t)
            tool_ang = aim_angle + swing * 0.45
            tool_angle_offset = swing * 0.65

        # Position is mathematically locked on the ring perimeter (cannot go out of it)
        orbit_tool_x = ix + math.cos(tool_ang) * orbit_rx
        orbit_tool_y = iy + math.sin(tool_ang) * orbit_ry
        tool_is_behind = math.sin(tool_ang) < 0

        # Draw the glowing orbital ring around the player (the Sun)
        def render_orbit_tool():
            if not (wep and wep.image):
                return
            tool_img = wep.image
            scale_mul = 1.35 if (is_sword and is_spinning) else 1.15
            tw = int(tool_img.get_width() * S.iso.scale * scale_mul)
            th = int(tool_img.get_height() * S.iso.scale * scale_mul)
            tool_scaled = pygame.transform.scale(tool_img, (max(1, tw), max(1, th)))

            flip_y = math.cos(tool_ang) < 0 and not is_spinning
            if flip_y:
                tool_scaled = pygame.transform.flip(tool_scaled, False, True)

            rot_angle = math.degrees(-(tool_ang + tool_angle_offset))
            if is_spinning:
                rot_angle += math.degrees(self_spin_angle)
            if roll_angle > 0:
                rot_angle -= math.degrees(roll_angle)
            rot_tool = pygame.transform.rotate(tool_scaled, rot_angle)
            if hit:
                rot_tool = rot_tool.copy()
                rot_tool.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)

            tr = rot_tool.get_rect(center=(int(orbit_tool_x), int(orbit_tool_y)))
            screen.blit(rot_tool, tr.topleft)

        # If orbiting behind player, render before avatar body
        if tool_is_behind:
            render_orbit_tool()

    body_color = (255, 255, 255) if hit else color
    border_color = (255, 255, 255) if hit else ((245, 250, 255) if me else (12, 14, 18))
    pygame.draw.circle(screen, body_color, (ix, iy), PR)
    pygame.draw.circle(screen, border_color, (ix, iy), PR, 2)

    if in_water:
        wake_w = int(PR * 2.2)
        wake_h = int(PR * 1.1)
        wake_surf = pygame.Surface((wake_w + 4, wake_h + 4), pygame.SRCALPHA)
        wake_rect = pygame.Rect(2, 2, wake_w, wake_h)
        pygame.draw.ellipse(wake_surf, (220, 245, 255, 175), wake_rect, max(1, int(1.5 * S.iso.scale)))
        screen.blit(wake_surf, (ix - wake_w // 2 - 2, iy + PR // 3 - wake_h // 2))
    
    eye_x, eye_y = ix - PR // 4, iy - PR // 4
    if roll_angle > 0:
        dx, dy = -PR // 4, -PR // 4
        rx = dx * math.cos(roll_angle) - dy * math.sin(roll_angle)
        ry = dx * math.sin(roll_angle) + dy * math.cos(roll_angle)
        eye_x, eye_y = ix + rx, iy + ry
        
    pygame.draw.circle(screen, (255, 255, 255), (int(eye_x), int(eye_y)), max(2, PR // 4))
    if name:
        draw_text(screen, name, S.small_font, 0, iy - PR - 18, color, center_x=ix)

    # 2. Render tool in front of avatar (if southern half) OR render handheld firearms
    if is_tool:
        if not tool_is_behind:
            render_orbit_tool()
    else:
        # Handheld firearms (AK47, M24, Revolver, etc.)
        if wep and wep.image:
            gun_img = wep.image
            gw, gh = int(gun_img.get_width() * S.iso.scale * 1.0725), int(gun_img.get_height() * S.iso.scale * 1.0725)
            gun_img = pygame.transform.scale(gun_img, (gw, gh))
            
            anim_offset_x = 0
            anim_offset_y = 0
            anim_angle_offset = 0
            
            if pressing:
                import time
                t = time.time() * 15
                kick = max(0, math.sin(t * 2)) * getattr(wep, "recoil", 1.0) * 4
                anim_offset_x = -math.cos(aim_angle) * kick
                anim_offset_y = -math.sin(aim_angle) * kick
                    
            flip_y = math.cos(aim_angle) < 0
            if flip_y:
                gun_img = pygame.transform.flip(gun_img, False, True)
                
            rot_angle = math.degrees(-(aim_angle + anim_angle_offset))
            if roll_angle > 0:
                rot_angle -= math.degrees(roll_angle)
            rot_img = pygame.transform.rotate(gun_img, rot_angle)
            if hit:
                rot_img = rot_img.copy()
                rot_img.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)
            gr = rot_img.get_rect(center=(ix + anim_offset_x, iy + anim_offset_y))
            screen.blit(rot_img, gr.topleft)



def follow_camera(S, fx, fy, dt):
    """Ease the camera toward centering grid cell (fx, fy)."""
    wx, wy = S.iso.world_px(fx, fy)
    tx = wx - cfg.WIDTH // 2
    ty = wy - cfg.HEIGHT // 2
    k = min(1.0, (1.0 + S.cam_smooth_slider.value * 11.0) * dt)
    S.iso.cam_x += (tx - S.iso.cam_x) * k
    S.iso.cam_y += (ty - S.iso.cam_y) * k


def snap_camera(S, fx, fy):
    """Instantly center on a grid cell (used after a zoom change)."""
    S.iso.center_on(*S.iso.world_px(fx, fy))


def zoom(S, delta):
    """Zoom in/out around whoever the camera is following."""
    focus = S.me if S.state == STATE_TEST else (
        centroid(S.local_players) if S.local_players else (0, 0))
    if S.iso.set_scale(S.iso.scale + delta):
        snap_camera(S, focus[0], focus[1])


def enter_world(S):
    """Drop this client's avatar onto the map (online modes)."""
    import random
    S.me = list(S.iso.find_free(0.0, 0.0)) + [0.0, 0.0, 0.0, 0.0, 0.0]   # fx, fy, z, vz, dash_time, dash_x, dash_y
    S.spawn_cell = (S.me[0], S.me[1])
    S.peers = {}
    S.client_id = f"{S.username}#{random.randint(1000, 9999)}"
    snap_camera(S, S.me[0], S.me[1])
    init_inventory(S)


def send_chat(S, text):
    """Post a chat line: always echo locally; broadcast when online."""
    text = text.strip()
    if not text:
        return
    name = S.username or (S.local_names[0] if S.local_names else "You")
    color = color_for(name)
    S.chat_log.append({"t": time.time(), "name": name, "color": color, "text": text})
    if S.state == STATE_TEST:
        try:
            S.conn.send({"type": "chat", "id": S.client_id, "name": name,
                         "color": list(color), "text": text[:180]})
        except Exception:
            pass


def prune_peers(S, now):
    for pid in [k for k, v in S.peers.items() if now - v["seen"] > PEER_TIMEOUT]:
        del S.peers[pid]


def draw_world_hud(S, lines, hint):
    screen = S.screen
    pad = 10
    surf = [S.small_font.render(ln, True, cfg.WHITE) for ln in lines]
    w = max((s.get_width() for s in surf), default=0) + pad * 2
    h = pad * 2 + len(surf) * 20
    panel = pygame.Surface((w, h), pygame.SRCALPHA)
    panel.fill((6, 10, 14, 180))
    pygame.draw.rect(panel, cfg.CARD_BORDER, panel.get_rect(), 1, border_radius=8)
    screen.blit(panel, (12, 12))
    for i, s in enumerate(surf):
        screen.blit(s, (12 + pad, 12 + pad + i * 20))
    if hint:
        draw_text(screen, hint, S.small_font, 0, cfg.HEIGHT - 90, cfg.GOLD_FAINT,
                  center_x=cfg.WIDTH // 2)

def draw_hearts(S):
    screen = S.screen
    heart_img = getattr(S, "heart_img", None)
    HS = 28
    hp = getattr(S, "player_health", 100)
    full_hearts = int(math.ceil(hp / 33.4))
    for i in range(3):
        hx, hy = 16 + i * (HS + 4), 16
        if i < full_hearts:
            if heart_img:
                screen.blit(heart_img, (hx, hy))
            else:
                pygame.draw.circle(screen, cfg.RED, (hx + 7, hy + 7), 7)
                pygame.draw.circle(screen, cfg.RED, (hx + 17, hy + 7), 7)
                pygame.draw.polygon(screen, cfg.RED, [(hx, hy + 10), (hx + 24, hy + 10), (hx + 12, hy + 22)])
        else:
            if heart_img:
                dim_s = heart_img.copy()
                dim_s.fill((60, 60, 60, 160), special_flags=pygame.BLEND_RGBA_MULT)
                screen.blit(dim_s, (hx, hy))
            else:
                pygame.draw.circle(screen, (70, 70, 70), (hx + 7, hy + 7), 7)
                pygame.draw.circle(screen, (70, 70, 70), (hx + 17, hy + 7), 7)
                pygame.draw.polygon(screen, (70, 70, 70), [(hx, hy + 10), (hx + 24, hy + 10), (hx + 12, hy + 22)])


def draw_weapon_hud(S):
    """Render weapon badge with fire mode, damage counter, and icon in top HUD."""
    return


def draw_melee_reach_ring(S, screen):
    pass


def draw_inventory_hud(S):
    """Displays player's gathered inventory items and provides 1-click access to the full backpack."""
    if not hasattr(S, "inventory"):
        return
    inv = S.inventory
    ALL_ITEM_METAS = {
        # Ores & Mining
        "coal": ("Coal", (160, 165, 175)),
        "copper": ("Copper", (225, 150, 95)),
        "iron": ("Iron", (210, 215, 225)),
        "gold": ("Gold", (255, 220, 60)),
        "diamond": ("Diamond", (110, 230, 255)),
        # Raw Timber & Materials
        "log": ("Log", (185, 140, 90)),
        "wood": ("Wood", (210, 175, 120)),
        "stick": ("Stick", (200, 160, 110)),
        "brick": ("Brick", (200, 90, 70)),
        "key": ("Key", (240, 200, 80)),
        "book": ("Book", (170, 120, 220)),
        "map": ("Map", (220, 190, 140)),
        "letter": ("Letter", (230, 225, 200)),
        "boots": ("Boots", (140, 100, 60)),
        "sack": ("Sack", (160, 130, 90)),
        # Food & Consumables
        "apple": ("Apple", (230, 70, 70)),
        "bread": ("Bread", (210, 160, 90)),
        "meat": ("Meat", (200, 60, 60)),
        "fish": ("Fish", (100, 180, 240)),
        "mushroom": ("Mushroom", (190, 80, 80)),
        "wheat": ("Wheat", (220, 200, 90)),
        # Ammunition
        "ammo": ("Rifle Ammo", (220, 180, 80)),
        "pistol_ammo": ("Pistol Ammo", (200, 190, 130)),
        "shotgun_ammo": ("Shotgun Shell", (210, 80, 60)),
    }
    active = []
    for k, count in inv.items():
        if count > 0:
            label, col = ALL_ITEM_METAS.get(k, (k.capitalize(), (220, 220, 220)))
            active.append((k, label, col, count))

    if not active:
        S.inv_hud_rect = None
        return

    # Cap visible HUD items to 8 to preserve screen space; the rest are in full backpack
    displayed_items = active[:8]
    hidden_count = len(active) - len(displayed_items)

    screen = S.screen
    card_x = 16
    card_y = 96
    item_w = 64
    badge_w = 96
    card_w = len(displayed_items) * item_w + badge_w + 14
    card_h = 28

    mx, my = pygame.mouse.get_pos()
    S.inv_hud_rect = pygame.Rect(card_x, card_y, card_w, card_h)
    is_hover = S.inv_hud_rect.collidepoint((mx, my))

    plate = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
    bg_color = (20, 26, 38, 235) if is_hover else (14, 18, 26, 215)
    border_color = (80, 120, 170, 250) if is_hover else (50, 65, 85, 230)
    pygame.draw.rect(plate, bg_color, (0, 0, card_w, card_h), border_radius=6)
    pygame.draw.rect(plate, border_color, (0, 0, card_w, card_h), width=1, border_radius=6)
    screen.blit(plate, (card_x, card_y))

    if not hasattr(S, "inv_font"):
        S.inv_font = pygame.font.SysFont(cfg.MONO_FONTS, 11, bold=True)

    cur_x = card_x + 8
    for itype, label, col, count in displayed_items:
        img = S.drop_images.get(itype) if hasattr(S, "drop_images") else None
        if img:
            icon_s = pygame.transform.scale(img, (18, 18))
            screen.blit(icon_s, (cur_x, card_y + 5))
        txt = S.inv_font.render(f"x{count}", True, col)
        screen.blit(txt, (cur_x + 22, card_y + 8))
        cur_x += item_w

    # Backpack shortcut button on the right
    badge_x = card_x + card_w - badge_w - 6
    badge_rect = pygame.Rect(badge_x, card_y + 4, badge_w, 20)
    badge_hover = badge_rect.collidepoint((mx, my))
    badge_bg = (45, 75, 120) if badge_hover else (28, 40, 60)
    badge_border = (120, 180, 255) if badge_hover else (60, 90, 130)
    pygame.draw.rect(screen, badge_bg, badge_rect, border_radius=4)
    pygame.draw.rect(screen, badge_border, badge_rect, width=1, border_radius=4)

    bp_label = f"[E] Backpack" if hidden_count == 0 else f"[E] +{hidden_count} More"
    bp_txt = S.inv_font.render(bp_label, True, (220, 240, 255) if badge_hover else (160, 190, 230))
    screen.blit(bp_txt, (badge_rect.centerx - bp_txt.get_width() // 2, badge_rect.centery - bp_txt.get_height() // 2))

CRAFTING_RECIPES = [
    {
        "id": "wood_planks",
        "name": "Wood Planks (x4)",
        "result_type": "wood",
        "result_count": 4,
        "cost": {"log": 1},
        "desc": "Processed timber for building and tools.",
    },
    {
        "id": "sticks",
        "name": "Sticks (x4)",
        "result_type": "stick",
        "result_count": 4,
        "cost": {"wood": 1},
        "desc": "Sturdy wooden shafts.",
    },
    {
        "id": "health_salve",
        "name": "Healing Salve",
        "result_type": "apple",
        "result_count": 1,
        "cost": {"apple": 1, "stick": 1},
        "desc": "Restores +35 HP when consumed.",
    },
    {
        "id": "cooked_rations",
        "name": "Cooked Rations",
        "result_type": "meat",
        "result_count": 1,
        "cost": {"meat": 1, "wood": 1},
        "desc": "Hearty meal. Restores +50 HP.",
    },
    {
        "id": "torch",
        "name": "Campfire Torch",
        "result_type": "coal",
        "result_count": 1,
        "cost": {"wood": 2, "coal": 1},
        "desc": "Radiant beacon of light and warmth.",
    },
    {
        "id": "barricade",
        "name": "Stone Brick (x2)",
        "result_type": "brick",
        "result_count": 2,
        "cost": {"iron": 1, "coal": 1},
        "desc": "Hardened masonry block for fortifications.",
    },
    {
        "id": "rifle_ammo",
        "name": "Rifle Ammo (x20)",
        "result_type": "ammo",
        "result_count": 20,
        "cost": {"iron": 1, "coal": 1},
        "desc": "Standard rifle cartridges.",
    },
    {
        "id": "pistol_ammo",
        "name": "Pistol Ammo (x24)",
        "result_type": "pistol_ammo",
        "result_count": 24,
        "cost": {"copper": 1, "coal": 1},
        "desc": "Sidearm defense rounds.",
    },
    {
        "id": "shotgun_ammo",
        "name": "Shotgun Shells (x12)",
        "result_type": "shotgun_ammo",
        "result_count": 12,
        "cost": {"iron": 1, "wood": 1},
        "desc": "Heavy buckshot cartridges.",
    },
]


def ensure_drop_images(S):
    if hasattr(S, "drop_images") and S.drop_images:
        return
    import os
    S.drop_images = {}
    paths = {
        # Raw materials & Ores
        "log": "items/material/log1.png",
        "log1": "items/material/log1.png",
        "log2": "items/material/log2.png",
        "log3": "items/material/log3.png",
        "log4": "items/material/log4.png",
        "wood": "items/material/wood.png",
        "stick": "items/material/stick.png",
        "coal": "items/ore/coal.png",
        "copper": "items/ore/copper_ore.png",
        "copper_ore": "items/ore/copper_ore.png",
        "diamond": "items/ore/diamond.png",
        "gold": "items/ore/gold_ore.png",
        "gold_ore": "items/ore/gold_ore.png",
        "iron": "items/ore/iron_ore.png",
        "iron_ore": "items/ore/iron_ore.png",
        "brick": "items/material/brick.png",
        "boots": "items/material/boots.png",
        "key": "items/material/key.png",
        "map": "items/material/map.png",
        "book": "items/material/book.png",
        "letter": "items/material/letter.png",
        "sack": "items/material/sack.png",
        # Food & Consumables
        "meat": "items/food/meat.png",
        "apple": "items/food/apple.png",
        "bread": "items/food/bread.png",
        "fish": "items/food/fish.png",
        "mushroom": "items/food/mushroom.png",
        "wheat": "items/food/wheat.png",
        # Ammunition
        "ammo": "items/bullets/RifleAmmoSmall.png",
        "pistol_ammo": "items/bullets/PistolAmmoSmall.png",
        "shotgun_ammo": "items/bullets/ShotgunShellSmall.png",
        # Weapons
        "sword": "items/weapons/sword.png",
        "Sword": "items/weapons/sword.png",
        "ak47": "items/weapons/AK47.png",
        "AK47": "items/weapons/AK47.png",
        "m24": "items/weapons/M24.png",
        "M24": "items/weapons/M24.png",
        "revolver": "items/weapons/Revolver.png",
        "Revolver": "items/weapons/Revolver.png",
        "luger": "items/weapons/Luger.png",
        "Luger": "items/weapons/Luger.png",
        "m92": "items/weapons/M92.png",
        "M92": "items/weapons/M92.png",
        "gun": "items/weapons/Luger.png",
        "Gun": "items/weapons/Luger.png",
        "mp5": "items/weapons/MP5.png",
        "MP5": "items/weapons/MP5.png",
        "m15": "items/weapons/M15.png",
        "M15": "items/weapons/M15.png",
        "sawedoffshotgun": "items/weapons/SawedOffShotgun.png",
        "SawedOffShotgun": "items/weapons/SawedOffShotgun.png",
        # Tools
        "axe": "items/tools/axe.png",
        "Axe": "items/tools/axe.png",
        "pickaxe": "items/tools/pickaxe.png",
        "Pickaxe": "items/tools/pickaxe.png",
        "hammer": "items/tools/hammer.png",
        "Hammer": "items/tools/hammer.png",
        "shovel": "items/tools/shovel.png",
        "Shovel": "items/tools/shovel.png",
        "mallet": "items/tools/mallet.png",
        "Mallet": "items/tools/mallet.png",
        "scythe": "items/tools/hoe.png",
        "Scythe": "items/tools/hoe.png",
        "fishing_rod": "items/tools/fishing_rod.png",
        "Fishing_rod": "items/tools/fishing_rod.png",
    }
    for k, v in paths.items():
        try:
            img = pygame.image.load(os.path.join(S.ASSETS_DIR, v)).convert_alpha()
            S.drop_images[k] = pygame.transform.scale(img, (32, 32))
        except Exception:
            surf = pygame.Surface((32, 32), pygame.SRCALPHA)
            pygame.draw.circle(surf, (200, 200, 200), (16, 16), 12)
            S.drop_images[k] = surf


def sync_inventory_totals(S):
    """Keep aggregate S.inventory dictionary in sync with individual hotbar and backpack slots."""
    totals = {}
    for slot in getattr(S, "hotbar", []):
        t = slot.get("type")
        c = slot.get("count", 0)
        if t and c > 0:
            totals[t] = totals.get(t, 0) + c
    for slot in getattr(S, "main_inventory", []):
        t = slot.get("type")
        c = slot.get("count", 0)
        if t and c > 0:
            totals[t] = totals.get(t, 0) + c
    if getattr(S, "cursor_item", None):
        t = S.cursor_item.get("type")
        c = S.cursor_item.get("count", 0)
        if t and c > 0:
            totals[t] = totals.get(t, 0) + c
    S.inventory = totals


def add_to_inventory(S, itype, count=1):
    if not hasattr(S, "inventory"):
        S.inventory = {}
    if not hasattr(S, "hotbar") or not S.hotbar:
        S.hotbar = [{"type": None, "count": 0} for _ in range(5)]
    if not hasattr(S, "main_inventory") or not S.main_inventory:
        S.main_inventory = [{"type": None, "count": 0} for _ in range(16)]

    rem = count
    # 1. Stack if already in hotbar
    for slot in S.hotbar:
        if slot.get("type") == itype:
            slot["count"] += rem
            sync_inventory_totals(S)
            return

    # 2. Stack if already in main backpack inventory
    for slot in S.main_inventory:
        if slot.get("type") == itype:
            slot["count"] += rem
            sync_inventory_totals(S)
            return

    # 3. Place in first empty slot in hotbar
    for slot in S.hotbar:
        if not slot.get("type") or slot.get("count", 0) <= 0:
            slot["type"] = itype
            slot["count"] = rem
            sync_inventory_totals(S)
            return

    # 4. Place in first empty slot in main backpack inventory
    for slot in S.main_inventory:
        if not slot.get("type") or slot.get("count", 0) <= 0:
            slot["type"] = itype
            slot["count"] = rem
            sync_inventory_totals(S)
            return

    sync_inventory_totals(S)


def remove_from_inventory(S, itype, count=1):
    rem = count
    if hasattr(S, "hotbar"):
        for slot in S.hotbar:
            if slot.get("type") == itype:
                take = min(slot.get("count", 0), rem)
                slot["count"] -= take
                rem -= take
                if slot["count"] <= 0:
                    slot["type"] = None
                    slot["count"] = 0
                if rem <= 0:
                    sync_inventory_totals(S)
                    return

    if hasattr(S, "main_inventory") and rem > 0:
        for slot in S.main_inventory:
            if slot.get("type") == itype:
                take = min(slot.get("count", 0), rem)
                slot["count"] -= take
                rem -= take
                if slot["count"] <= 0:
                    slot["type"] = None
                    slot["count"] = 0
                if rem <= 0:
                    sync_inventory_totals(S)
                    return

    sync_inventory_totals(S)


def can_craft_recipe(S, recipe):
    inv = getattr(S, "inventory", {})
    for item, qty in recipe.get("cost", {}).items():
        if inv.get(item, 0) < qty:
            return False
    return True


def craft_recipe(S, recipe_idx):
    if recipe_idx < 0 or recipe_idx >= len(CRAFTING_RECIPES):
        return False
    recipe = CRAFTING_RECIPES[recipe_idx]
    if not can_craft_recipe(S, recipe):
        play_sfx(S, "break", 0.4)
        return False

    # Deduct materials
    for item, qty in recipe.get("cost", {}).items():
        remove_from_inventory(S, item, qty)

    # Yield item
    res_type = recipe.get("result_type", "wood")
    res_count = recipe.get("result_count", 1)
    add_to_inventory(S, res_type, res_count)

    play_sfx(S, "pickup", 0.8)
    if not hasattr(S, "damage_popups"):
        S.damage_popups = []
    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
    if hasattr(S, "iso") and S.iso:
        psx, psy = S.iso.to_screen(*S.iso.world_px(target_p[0], target_p[1]))
        psy -= S.iso.elev(target_p[0], target_p[1])
    else:
        psx, psy = cfg.WIDTH // 2, cfg.HEIGHT // 2
    S.damage_popups.append({
        "x": psx + random.uniform(-6, 6),
        "y": psy - 42,
        "text": f"+Crafted {recipe['name']}",
        "color": (255, 220, 80),
        "life": 1.4,
        "max_life": 1.4,
        "vy": -38.0
    })
    return True


def use_inventory_item(S, slot):
    """Uses, consumes, or equips an item from either backpack or hotbar."""
    if not slot or not slot.get("type") or slot.get("count", 0) <= 0:
        return False
    itype = slot["type"]
    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
    if hasattr(S, "iso") and S.iso:
        psx, psy = S.iso.to_screen(*S.iso.world_px(target_p[0], target_p[1]))
        psy -= S.iso.elev(target_p[0], target_p[1])
    else:
        psx, psy = cfg.WIDTH // 2, cfg.HEIGHT // 2

    if not hasattr(S, "damage_popups"):
        S.damage_popups = []

    # 1. Equippable Weapon or Tool
    norm = itype.lower()
    for wep_name in WEAPONS.keys():
        if wep_name.lower() == norm:
            S.my_weapon = wep_name
            play_sfx(S, "wood", 0.6)
            S.damage_popups.append({"x": psx, "y": psy - 40, "text": f"+Equipped {wep_name}", "color": (255, 220, 100), "life": 1.2, "max_life": 1.2, "vy": -40.0})
            return True

    # 2. Food & Organic Consumables
    food_heals = {
        "apple": 25,
        "bread": 35,
        "meat": 45,
        "fish": 30,
        "mushroom": 20,
    }
    if itype in food_heals:
        heal = food_heals[itype]
        S.player_health = min(100, getattr(S, "player_health", 100) + heal)
        slot["count"] -= 1
        if slot["count"] <= 0:
            slot["type"] = None
            slot["count"] = 0
        play_sfx(S, "pickup", 0.75)
        S.damage_popups.append({"x": psx, "y": psy - 40, "text": f"+{heal} HP", "color": (120, 255, 150), "life": 1.2, "max_life": 1.2, "vy": -40.0})
        sync_inventory_totals(S)
        return True

    # 3. Ammunition
    if itype in ("ammo", "pistol_ammo", "shotgun_ammo"):
        play_sfx(S, "mine", 0.5)
        S.damage_popups.append({"x": psx, "y": psy - 40, "text": "+Loaded Ammo", "color": (255, 220, 100), "life": 1.2, "max_life": 1.2, "vy": -40.0})
        return True

    # 4. Fortifications & Cover
    if itype in ("brick", "wood"):
        aim = getattr(S, "aim_angle", 0.0)
        bx = int(round(target_p[0] + math.cos(aim) * 1.5))
        by = int(round(target_p[1] + math.sin(aim) * 1.5))
        if hasattr(S, "iso") and not S.iso.solid(bx, by) and (bx, by) != (int(target_p[0]), int(target_p[1])):
            tile_prop = 62 if itype == "brick" else 58
            cell = S.iso.world.get(bx, by)
            S.iso.world.cache[(bx, by)] = (cell[0], tile_prop, cell[2])
            S.iso.world.version += 1
            slot["count"] -= 1
            if slot["count"] <= 0:
                slot["type"] = None
                slot["count"] = 0
            play_sfx(S, "chop" if itype == "wood" else "mine", 0.7)
            S.damage_popups.append({"x": psx, "y": psy - 40, "text": "Fortified Cover", "color": (200, 230, 255), "life": 1.2, "max_life": 1.2, "vy": -40.0})
            sync_inventory_totals(S)
            return True

    # 5. Lore Notepad / Book / Map / Letter
    if itype in ("book", "map", "letter"):
        S.notepad_open = not getattr(S, "notepad_open", False)
        play_sfx(S, "pickup", 0.6)
        return True

    # 6. Keys
    if itype == "key":
        play_sfx(S, "pickup", 0.6)
        S.damage_popups.append({"x": psx, "y": psy - 40, "text": "Skeleton Key: Unlocks Chests", "color": (255, 215, 80), "life": 1.2, "max_life": 1.2, "vy": -40.0})
        return True

    return False


def use_hotbar_item(S, slot_idx=None):
    if slot_idx is None:
        slot_idx = getattr(S, "selected_slot", 0)
    if not hasattr(S, "hotbar") or slot_idx < 0 or slot_idx >= len(S.hotbar):
        return
    use_inventory_item(S, S.hotbar[slot_idx])


def select_hotbar_slot(S, slot_idx):
    """Sets active hotbar slot and automatically equips any weapon/tool stored in that slot."""
    if not hasattr(S, "hotbar") or not S.hotbar:
        return
    if slot_idx < 0 or slot_idx >= len(S.hotbar):
        return
    S.selected_slot = slot_idx
    slot = S.hotbar[slot_idx]
    itype = slot.get("type")
    if itype and slot.get("count", 0) > 0:
        norm = itype.lower()
        for wep_name in WEAPONS.keys():
            if wep_name.lower() == norm:
                S.my_weapon = wep_name
                play_sfx(S, "wood", 0.45)
                return
    S.my_weapon = None


def init_inventory(S, force=False):
    """Initializes player hotbar (5 slots) and backpack (16 slots) with starter loadout if empty."""
    if not hasattr(S, "hotbar") or not S.hotbar or force:
        S.hotbar = [{"type": None, "count": 0} for _ in range(5)]
    if not hasattr(S, "main_inventory") or not S.main_inventory or force:
        S.main_inventory = [{"type": None, "count": 0} for _ in range(16)]
    if not hasattr(S, "inventory_open"):
        S.inventory_open = False
    if not hasattr(S, "cursor_item"):
        S.cursor_item = None
    if not hasattr(S, "selected_slot"):
        S.selected_slot = 0
    if not hasattr(S, "crafting_open"):
        S.crafting_open = False
    if not hasattr(S, "craft_scroll"):
        S.craft_scroll = 0
    if not hasattr(S, "craft_selected_idx"):
        S.craft_selected_idx = 0
    if not hasattr(S, "hovered_inv_slot"):
        S.hovered_inv_slot = None

    is_empty = all((not s.get("type") or s.get("count", 0) <= 0) for s in S.hotbar) and \
               all((not s.get("type") or s.get("count", 0) <= 0) for s in S.main_inventory)
    if is_empty or force:
        starter_hotbar = [
            {"type": "sword", "count": 1},
            {"type": "pickaxe", "count": 1},
            {"type": "axe", "count": 1},
            {"type": "apple", "count": 5},
            {"type": "wood", "count": 20},
        ]
        starter_backpack = [
            {"type": "ak47", "count": 1},
            {"type": "ammo", "count": 60},
            {"type": "bread", "count": 4},
            {"type": "meat", "count": 2},
            {"type": "brick", "count": 10},
            {"type": "key", "count": 1},
            {"type": "book", "count": 1},
        ]
        for i, it in enumerate(starter_hotbar):
            if i < len(S.hotbar):
                S.hotbar[i] = it.copy()
        for i, it in enumerate(starter_backpack):
            if i < len(S.main_inventory):
                S.main_inventory[i] = it.copy()
        select_hotbar_slot(S, S.selected_slot)
    sync_inventory_totals(S)


def drop_slot_item_to_world(S, loc_type, slot_idx, drop_all=False):
    """Drops 1 item (or entire stack if drop_all) from hotbar or backpack slot into world."""
    target_list = getattr(S, "main_inventory", []) if loc_type == "bp" else getattr(S, "hotbar", [])
    if not target_list or slot_idx < 0 or slot_idx >= len(target_list):
        return False
    slot = target_list[slot_idx]
    itype = slot.get("type")
    count = slot.get("count", 0)
    if not itype or count <= 0:
        return False

    qty = count if drop_all else 1
    slot["count"] -= qty
    if slot["count"] <= 0:
        slot["type"] = None
        slot["count"] = 0

    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
    if not hasattr(S, "dropped_items"):
        S.dropped_items = []

    for _ in range(qty):
        ang = random.uniform(0, 6.28)
        spd = random.uniform(0.6, 1.6)
        S.dropped_items.append({
            "cx": target_p[0] + math.cos(ang) * 0.45,
            "cy": target_p[1] + math.sin(ang) * 0.45,
            "z": 15.0,
            "vx": math.cos(ang) * spd,
            "vy": math.sin(ang) * spd,
            "vz": random.uniform(80, 160),
            "type": itype
        })
    play_sfx(S, "break", 0.5)
    sync_inventory_totals(S)
    return True


def interact_or_open_chest(S):
    """Primary interaction function for opening chests and world interactions.
    Triggered by pressing E or F (or controller action button).
    1. Detects chests (tiles 135-137) within player reach (~2.4 tiles).
    2. Opens chest: plays celebratory sound, bursts gold/diamond/ammo/supplies, spawns golden sparkles,
       replaces tile with opened chest (145), and shows '+ Chest Opened!' popup.
    3. If near a breakable container/crate/pot within range, breaks/loots it.
    4. If no world interactable is in range, falls back to using the active hotbar item (e.g. food/potions/blocks).
    """
    if getattr(S, "paused", False) or getattr(S, "crafting_open", False):
        return False

    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else None)
    if not target_p or not hasattr(S, "iso") or not S.iso:
        return False

    px, py = target_p[0], target_p[1]
    ipx, ipy = int(round(px)), int(round(py))

    chest_candidates = []
    other_candidates = []

    for dgx in range(-3, 4):
        for dgy in range(-3, 4):
            cx, cy = ipx + dgx, ipy + dgy
            dist = math.hypot(px - (cx + 0.5), py - (cy + 0.5))
            if dist <= 2.5:
                try:
                    cell = S.iso.world.get(cx, cy)
                    if cell and cell[1] is not None:
                        if cell[1] in getattr(iso, "DESTRUCTIBLE_CHESTS", [135, 136, 137]):
                            chest_candidates.append(((cx, cy), cell, dist))
                        elif cell[1] in getattr(iso, "DESTRUCTIBLE_PROPS", []):
                            other_candidates.append(((cx, cy), cell, dist))
                except Exception:
                    pass

    # 1. Open nearby chest
    if chest_candidates:
        chest_candidates.sort(key=lambda item: item[2])
        (cx, cy), cell, dist = chest_candidates[0]

        play_sfx(S, "pickup", 0.95)
        play_sfx(S, "break", 0.6)

        # Update world tile cache to open/broken chest pieces (145)
        broken_tile = DESTRUCTIBLE_PIECES_MAP.get(cell[1], 145)
        S.iso.world.cache[(cx, cy)] = (cell[0], broken_tile, cell[2])
        S.iso.world.version += 1

        sx, sy = S.iso.to_screen(*S.iso.world_px(cx + 0.5, cy + 0.5))
        try:
            sy -= S.iso.elev(cx, cy)
        except Exception:
            pass

        # Golden sparkle particles
        if not hasattr(S, "particles"):
            S.particles = []
        p_colors = [(255, 215, 60), (255, 245, 160), (220, 180, 100), (255, 255, 220), (255, 190, 40)]
        for _ in range(24):
            S.particles.append({
                "x": sx + random.uniform(-14, 14),
                "y": sy - random.uniform(10, 32),
                "vx": random.uniform(-80, 80),
                "vy": random.uniform(-130, -30),
                "life": random.uniform(0.5, 0.85),
                "size": random.randint(3, 6),
                "color": random.choice(p_colors)
            })

        # Break animation effect
        if not hasattr(S, "break_effects"):
            S.break_effects = []
        S.break_effects.append({
            "cx": cx, "cy": cy,
            "category": "chest",
            "timer": 0.0,
            "duration": 0.28,
        })

        # Burst high-tier loot drops
        if not hasattr(S, "dropped_items"):
            S.dropped_items = []
        possible_drops = ["gold", "diamond", "ammo", "boots", "book", "shotgun_ammo", "pistol_ammo", "key", "apple", "bread", "meat"]
        count = random.randint(3, 5)
        for _ in range(count):
            dtype = random.choice(possible_drops)
            S.dropped_items.append({
                "cx": cx + random.uniform(-0.35, 0.35),
                "cy": cy + random.uniform(-0.35, 0.35),
                "type": dtype,
                "z": 20.0,
                "vz": random.uniform(180, 280),
                "vx": random.uniform(-2.0, 2.0),
                "vy": random.uniform(-2.0, 2.0)
            })

        # Floating text popup
        if not hasattr(S, "damage_popups"):
            S.damage_popups = []
        S.damage_popups.append({
            "x": sx,
            "y": sy - 42,
            "text": "+ Chest Opened!",
            "color": (255, 220, 50),
            "life": 1.4,
            "max_life": 1.4,
            "vy": -38.0
        })
        return True

    # 2. Break / open nearby container (pot / crate / barrel)
    if other_candidates:
        other_candidates.sort(key=lambda item: item[2])
        (cx, cy), cell, dist = other_candidates[0]
        if dist <= 1.8:
            cat_name = DESTRUCTIBLE_CAT_MAP.get(cell[1], "crate")
            sx, sy = S.iso.to_screen(*S.iso.world_px(cx + 0.5, cy + 0.5))
            sy -= S.iso.elev(cx, cy)
            break_destructible(S, cx, cy, cell, cat_name, sx, sy, time.time())
            return True

    # 3. Fallback: Use selected item from bottom hotbar (food / consumables / blocks)
    use_hotbar_item(S, getattr(S, "selected_slot", 0))
    return True


def draw_chest_interaction_prompt(S, now):
    """Draws a sleek floating prompt [E] Open Chest when near a chest."""
    if S.state not in (STATE_TEST, STATE_LOCAL) or getattr(S, "paused", False) or getattr(S, "crafting_open", False):
        return
    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else None)
    if not target_p or not hasattr(S, "iso") or not S.iso:
        return
    px, py = target_p[0], target_p[1]
    ipx, ipy = int(round(px)), int(round(py))

    nearest_chest = None
    min_dist = 2.4
    for dgx in range(-3, 4):
        for dgy in range(-3, 4):
            cx, cy = ipx + dgx, ipy + dgy
            dist = math.hypot(px - (cx + 0.5), py - (cy + 0.5))
            if dist <= min_dist:
                try:
                    cell = S.iso.world.get(cx, cy)
                    if cell and cell[1] in getattr(iso, "DESTRUCTIBLE_CHESTS", [135, 136, 137]):
                        nearest_chest = (cx, cy)
                        min_dist = dist
                except Exception:
                    pass

    if not nearest_chest:
        return

    cx, cy = nearest_chest
    sx, sy = S.iso.to_screen(*S.iso.world_px(cx + 0.5, cy + 0.5))
    try:
        sy -= S.iso.elev(cx, cy)
    except Exception:
        pass
    sy -= 44
    bob = int(math.sin(now * 4.5) * 3)
    sy += bob

    key_label = "[X]" if getattr(S, "using_controller", False) else "[F]"
    font = getattr(S, "small_font", None) or S.font
    txt_surf = font.render(f"{key_label} Open Chest", True, (255, 238, 150))
    tw, th = txt_surf.get_size()
    pw, ph = tw + 16, th + 8

    badge = pygame.Surface((pw, ph), pygame.SRCALPHA)
    badge.fill((16, 18, 24, 220))
    pygame.draw.rect(badge, (255, 205, 70), badge.get_rect(), 1, border_radius=4)
    badge.blit(txt_surf, (8, 4))

    S.screen.blit(badge, (int(sx - pw // 2), int(sy - ph // 2)))


def ensure_backpack_image(S):
    """Loads and caches the clean pixel-art adventurer backpack asset scaled to screen."""
    if hasattr(S, "backpack_img") and S.backpack_img:
        return S.backpack_img
    import os
    bp_path = os.path.join(S.ASSETS_DIR, "ui", "backpack_inventory.png")
    if os.path.exists(bp_path):
        try:
            raw = pygame.image.load(bp_path).convert_alpha()
            s = 480.0 / raw.get_height()
            tw = int(raw.get_width() * s)
            th = int(raw.get_height() * s)
            S.backpack_img = pygame.transform.smoothscale(raw, (tw, th))
            return S.backpack_img
        except Exception as e:
            print("Failed to load backpack image:", e)
    return None


def get_backpack_slot_rects():
    """Returns the list of 16 pygame.Rect objects aligned with the 4x4 slots on the backpack asset."""
    s = 480.0 / 846.0
    w_bp = int(1000 * s)
    x_bp = (cfg.WIDTH - w_bp) // 2
    y_bp = 36
    rects = []
    slot_w = int(108 * s)
    slot_h = int(108 * s)
    for r in range(4):
        for c in range(4):
            sx = int(x_bp + (247 + c * 141) * s)
            sy = int(y_bp + (222 + r * 141) * s)
            rects.append(pygame.Rect(sx, sy, slot_w, slot_h))
    return rects


def ensure_hotbar_dock_image(S):
    """Loads and caches the 5-cell pixel-art wooden hotbar dock asset."""
    if hasattr(S, "hotbar_dock_img") and S.hotbar_dock_img:
        return S.hotbar_dock_img
    import os
    dock_path = os.path.join(S.ASSETS_DIR, "ui", "hotbar_dock.png")
    if os.path.exists(dock_path):
        try:
            raw = pygame.image.load(dock_path).convert_alpha()
            hb_w = 294
            hb_h = 64
            S.hotbar_dock_img = pygame.transform.smoothscale(raw, (hb_w, hb_h))
            return S.hotbar_dock_img
        except Exception as e:
            print("Failed to load hotbar dock image:", e)
    return None


def get_hotbar_slot_rects():
    """Returns the list of 5 pygame.Rect objects aligned with the 5 cells of the wooden hotbar dock."""
    hb_w = 294
    hb_h = 64
    hb_x = (cfg.WIDTH - hb_w) // 2
    hb_y = cfg.HEIGHT - hb_h - 8
    scale_x = hb_w / 1466.0
    scale_y = hb_h / 319.0
    rects = []
    for i in range(5):
        cx0 = 50 + i * 278
        cy0 = 42
        cw = 254
        ch = 234
        rx = int(hb_x + cx0 * scale_x)
        ry = int(hb_y + cy0 * scale_y)
        rw = int(cw * scale_x)
        rh = int(ch * scale_y)
        rects.append(pygame.Rect(rx, ry, rw, rh))
    return rects


def toggle_inventory(S):
    """Toggles the full Minecraft-style backpack inventory overlay."""
    S.inventory_open = not getattr(S, "inventory_open", False)
    if S.inventory_open:
        play_sfx(S, "pickup", 0.8)
        if getattr(S, "crafting_open", False):
            S.crafting_open = False
        if getattr(S, "notepad_open", False):
            S.notepad_open = False
    else:
        # Safe return: put any held cursor item back into inventory so it is never lost
        if getattr(S, "cursor_item", None):
            c_type = S.cursor_item.get("type")
            c_cnt = S.cursor_item.get("count", 0)
            if c_type and c_cnt > 0:
                add_to_inventory(S, c_type, c_cnt)
            S.cursor_item = None
        play_sfx(S, "wood", 0.6)


def drop_held_item_to_world(S):
    """Drops the item held on cursor into the world near player (Minecraft drop mechanic)."""
    if not getattr(S, "cursor_item", None):
        return
    c_type = S.cursor_item.get("type")
    c_count = S.cursor_item.get("count", 0)
    if not c_type or c_count <= 0:
        S.cursor_item = None
        return

    target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
    if not hasattr(S, "dropped_items"):
        S.dropped_items = []

    for _ in range(c_count):
        ang = random.uniform(0, 6.28)
        spd = random.uniform(0.6, 1.6)
        S.dropped_items.append({
            "cx": target_p[0] + math.cos(ang) * 0.45,
            "cy": target_p[1] + math.sin(ang) * 0.45,
            "z": 15.0,
            "vx": math.cos(ang) * spd,
            "vy": math.sin(ang) * spd,
            "vz": random.uniform(80, 160),
            "type": c_type
        })
    play_sfx(S, "break", 0.5)
    S.cursor_item = None
    sync_inventory_totals(S)


def handle_inventory_click(S, pos, button, shift_held=False):
    """Minecraft-like inventory slot click handling:
    - Left-Click: Pick up / Place / Swap stacks
    - Right-Click: Pick up half stack / Place 1 item
    - Shift+Left-Click: Quick transfer between backpack & hotbar
    - Click outside while holding: Drop item to world
    """
    if not hasattr(S, "main_inventory") or not S.main_inventory:
        S.main_inventory = [{"type": None, "count": 0} for _ in range(16)]
    if not hasattr(S, "hotbar") or not S.hotbar:
        S.hotbar = [{"type": None, "count": 0} for _ in range(5)]

    # Check backpack close button [X]
    if hasattr(S, "inv_close_btn_rect") and S.inv_close_btn_rect and S.inv_close_btn_rect.collidepoint(pos):
        toggle_inventory(S)
        return True

    bp_rects = get_backpack_slot_rects()
    hb_rects = get_hotbar_slot_rects()

    clicked_loc = None  # ("bp", idx) or ("hb", idx)
    for idx, r in enumerate(bp_rects):
        if r.collidepoint(pos):
            clicked_loc = ("bp", idx)
            break
    if not clicked_loc:
        for idx, r in enumerate(hb_rects):
            if r.collidepoint(pos):
                clicked_loc = ("hb", idx)
                break

    # If clicked outside slots while holding an item
    if not clicked_loc:
        s = 480.0 / 846.0
        w_bp = int(1000 * s)
        x_bp = (cfg.WIDTH - w_bp) // 2
        y_bp = 36
        bp_body_rect = pygame.Rect(x_bp, y_bp, w_bp, 480)
        hb_body_rect = pygame.Rect((cfg.WIDTH - 294) // 2 - 14, cfg.HEIGHT - 72, 322, 72)

        if S.cursor_item and not bp_body_rect.collidepoint(pos) and not hb_body_rect.collidepoint(pos):
            drop_held_item_to_world(S)
            return True
        elif not bp_body_rect.collidepoint(pos) and not hb_body_rect.collidepoint(pos):
            toggle_inventory(S)
            return True
        return False

    loc_type, slot_idx = clicked_loc
    target_slot = S.main_inventory[slot_idx] if loc_type == "bp" else S.hotbar[slot_idx]

    # --- SHIFT + RIGHT CLICK: Direct Use / Consume / Equip ---
    if shift_held and button == 3:
        if target_slot.get("type") and target_slot.get("count", 0) > 0:
            if use_inventory_item(S, target_slot):
                return True

    # --- SHIFT + LEFT CLICK: Quick Transfer between Backpack and Hotbar ---
    if shift_held and button == 1:
        itype = target_slot.get("type")
        icount = target_slot.get("count", 0)
        if itype and icount > 0:
            target_list = S.hotbar if loc_type == "bp" else S.main_inventory
            rem = icount
            # 1. Stack into target container
            for dest_slot in target_list:
                if dest_slot.get("type") == itype:
                    dest_slot["count"] += rem
                    rem = 0
                    break
            # 2. Place into first empty slot in target container
            if rem > 0:
                for dest_slot in target_list:
                    if not dest_slot.get("type") or dest_slot.get("count", 0) <= 0:
                        dest_slot["type"] = itype
                        dest_slot["count"] = rem
                        rem = 0
                        break
            if rem < icount:
                if rem <= 0:
                    target_slot["type"] = None
                    target_slot["count"] = 0
                else:
                    target_slot["count"] = rem
                play_sfx(S, "pickup", 0.7)
                sync_inventory_totals(S)
            return True

    # --- LEFT CLICK (Button 1): Pick up / Place / Swap ---
    if button == 1:
        if S.cursor_item is None:
            # Pick up stack
            if target_slot.get("type") and target_slot.get("count", 0) > 0:
                S.cursor_item = dict(target_slot)
                target_slot["type"] = None
                target_slot["count"] = 0
                play_sfx(S, "pickup", 0.8)
        else:
            # Holding item
            c_type = S.cursor_item["type"]
            c_count = S.cursor_item["count"]
            s_type = target_slot.get("type")
            s_count = target_slot.get("count", 0)

            if not s_type or s_count <= 0:
                target_slot["type"] = c_type
                target_slot["count"] = c_count
                S.cursor_item = None
                play_sfx(S, "pickup", 0.7)
            elif s_type == c_type:
                target_slot["count"] += c_count
                S.cursor_item = None
                play_sfx(S, "pickup", 0.75)
            else:
                S.cursor_item = {"type": s_type, "count": s_count}
                target_slot["type"] = c_type
                target_slot["count"] = c_count
                play_sfx(S, "pickup", 0.8)

        sync_inventory_totals(S)
        return True

    # --- RIGHT CLICK (Button 3): Split / Place 1 ---
    elif button == 3:
        if S.cursor_item is None:
            s_type = target_slot.get("type")
            s_count = target_slot.get("count", 0)
            if s_type and s_count > 0:
                take = (s_count + 1) // 2
                remain = s_count - take
                S.cursor_item = {"type": s_type, "count": take}
                if remain > 0:
                    target_slot["count"] = remain
                else:
                    target_slot["type"] = None
                    target_slot["count"] = 0
                play_sfx(S, "pickup", 0.7)
        else:
            c_type = S.cursor_item["type"]
            s_type = target_slot.get("type")
            s_count = target_slot.get("count", 0)

            if not s_type or s_count <= 0:
                target_slot["type"] = c_type
                target_slot["count"] = 1
                S.cursor_item["count"] -= 1
                if S.cursor_item["count"] <= 0:
                    S.cursor_item = None
                play_sfx(S, "pickup", 0.6)
            elif s_type == c_type:
                target_slot["count"] += 1
                S.cursor_item["count"] -= 1
                if S.cursor_item["count"] <= 0:
                    S.cursor_item = None
                play_sfx(S, "pickup", 0.6)
            else:
                old_c = dict(S.cursor_item)
                S.cursor_item = {"type": s_type, "count": s_count}
                target_slot["type"] = old_c["type"]
                target_slot["count"] = old_c["count"]
                play_sfx(S, "pickup", 0.8)

        sync_inventory_totals(S)
        return True

    return False


def handle_inventory_numkey(S, num_idx):
    """Minecraft feature: Press 1-5 while hovering over a slot to swap directly with hotbar slot 1-5."""
    if not getattr(S, "inventory_open", False):
        return False
    if num_idx < 0 or num_idx >= 5:
        return False
    mx, my = pygame.mouse.get_pos()
    bp_rects = get_backpack_slot_rects()
    hb_rects = get_hotbar_slot_rects()

    for idx, r in enumerate(bp_rects):
        if r.collidepoint((mx, my)):
            S.main_inventory[idx], S.hotbar[num_idx] = S.hotbar[num_idx], S.main_inventory[idx]
            play_sfx(S, "pickup", 0.75)
            sync_inventory_totals(S)
            return True

    for idx, r in enumerate(hb_rects):
        if r.collidepoint((mx, my)):
            if idx != num_idx:
                S.hotbar[idx], S.hotbar[num_idx] = S.hotbar[num_idx], S.hotbar[idx]
                play_sfx(S, "pickup", 0.75)
                sync_inventory_totals(S)
            return True

    return False


def draw_full_inventory(S, now):
    """Renders the full adventurer backpack inventory overlay with Minecraft reorganization mechanics."""
    if not getattr(S, "inventory_open", False):
        return

    screen = S.screen
    # 1. Dark backdrop dimming
    screen.blit(get_screen_overlay(165), (0, 0))

    # 2. Ensure images
    ensure_drop_images(S)
    bp_img = ensure_backpack_image(S)
    if not bp_img:
        return

    w_bp = bp_img.get_width()
    h_bp = bp_img.get_height()
    x_bp = (cfg.WIDTH - w_bp) // 2
    y_bp = 36

    # Draw backpack image
    screen.blit(bp_img, (x_bp, y_bp))

    title_font = getattr(S, "font", None) or pygame.font.SysFont(cfg.MONO_FONTS, 14, bold=True)
    small_font = getattr(S, "small_font", None) or pygame.font.SysFont(cfg.MONO_FONTS, 11)
    inv_font = getattr(S, "inv_font", None) or pygame.font.SysFont(cfg.MONO_FONTS, 11, bold=True)

    # Close button [X] at top right of backpack
    close_r = pygame.Rect(x_bp + w_bp - 56, y_bp + 26, 28, 28)
    S.inv_close_btn_rect = close_r
    mx, my = pygame.mouse.get_pos()
    close_hover = close_r.collidepoint((mx, my))
    pygame.draw.rect(screen, (190, 45, 45) if close_hover else (130, 30, 30), close_r, border_radius=6)
    pygame.draw.rect(screen, (255, 180, 180) if close_hover else (180, 90, 90), close_r, width=1, border_radius=6)
    x_lbl = small_font.render("X", True, (255, 255, 255))
    screen.blit(x_lbl, (close_r.centerx - x_lbl.get_width() // 2, close_r.centery - x_lbl.get_height() // 2))

    # 3. Backpack Slots (16 slots)
    bp_rects = get_backpack_slot_rects()
    hovered_item_info = None
    S.hovered_inv_slot = None

    if not hasattr(S, "main_inventory") or not S.main_inventory:
        S.main_inventory = [{"type": None, "count": 0} for _ in range(16)]

    for idx, r in enumerate(bp_rects):
        slot = S.main_inventory[idx]
        is_hover = r.collidepoint((mx, my))

        if is_hover:
            h_surf = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            h_surf.fill((255, 220, 100, 45))
            screen.blit(h_surf, r.topleft)
            pygame.draw.rect(screen, (255, 225, 110, 220), r, width=2, border_radius=8)

        itype = slot.get("type")
        count = slot.get("count", 0)
        if is_hover:
            S.hovered_inv_slot = ("bp", idx, itype, count)
        if itype and count > 0:
            img = S.drop_images.get(itype)
            if img:
                target_size = 40
                scaled_img = pygame.transform.smoothscale(img, (target_size, target_size)) if img.get_width() != target_size else img
                screen.blit(scaled_img, (r.centerx - target_size // 2, r.centery - target_size // 2 - 2))

            cnt_txt = str(count)
            sh_surf = inv_font.render(cnt_txt, True, (0, 0, 0))
            fg_surf = inv_font.render(cnt_txt, True, (255, 255, 255))
            screen.blit(sh_surf, (r.right - fg_surf.get_width() - 5, r.bottom - fg_surf.get_height() - 3))
            screen.blit(fg_surf, (r.right - fg_surf.get_width() - 6, r.bottom - fg_surf.get_height() - 4))

            if is_hover:
                hovered_item_info = (itype, count, r)

    # 4. Check bottom 5-cell Hotbar slots highlight & tooltip
    hb_rects = get_hotbar_slot_rects()
    for idx, r in enumerate(hb_rects):
        if r.collidepoint((mx, my)):
            pygame.draw.rect(screen, (255, 225, 110, 220), r, width=2, border_radius=8)
            slot = S.hotbar[idx]
            S.hovered_inv_slot = ("hb", idx, slot.get("type"), slot.get("count", 0))
            if slot.get("type") and slot.get("count", 0) > 0:
                hovered_item_info = (slot.get("type"), slot.get("count", 0), r)

    # 6. Item Tooltip on hover
    if hovered_item_info and not getattr(S, "cursor_item", None):
        itype, count, slot_r = hovered_item_info
        name_str = itype.replace("_", " ").title()
        action_hint = ""
        norm = itype.lower()
        if any(w.lower() == norm for w in WEAPONS.keys()):
            action_hint = "  [F] Equip"
        elif itype in ("apple", "bread", "meat", "fish", "mushroom"):
            action_hint = "  [F] Eat (+HP)"
        elif itype in ("brick", "wood"):
            action_hint = "  [F] Fortify"
        elif itype in ("book", "map", "letter"):
            action_hint = "  [F] Read"
        elif itype == "key":
            action_hint = "  [F] Key"
        tip_text = f"{name_str} (x{count}){(' • ' + action_hint) if action_hint else ''}"
        tip_surf = small_font.render(tip_text, True, (255, 255, 240))
        tw, th = tip_surf.get_size()
        tx = max(10, min(cfg.WIDTH - tw - 16, mx + 16))
        ty = max(10, min(cfg.HEIGHT - th - 16, my - 24))
        tip_bg = pygame.Rect(tx, ty, tw + 12, th + 8)
        t_plate = pygame.Surface((tip_bg.width, tip_bg.height), pygame.SRCALPHA)
        pygame.draw.rect(t_plate, (16, 20, 28, 235), (0, 0, tip_bg.width, tip_bg.height), border_radius=6)
        pygame.draw.rect(t_plate, (255, 215, 60, 200), (0, 0, tip_bg.width, tip_bg.height), width=1, border_radius=6)
        screen.blit(t_plate, tip_bg.topleft)
        screen.blit(tip_surf, (tx + 6, ty + 4))

    # 7. Floating Cursor Item (carried with mouse cursor)
    if getattr(S, "cursor_item", None):
        c_item = S.cursor_item
        c_type = c_item.get("type")
        c_cnt = c_item.get("count", 0)
        if c_type and c_cnt > 0:
            img = S.drop_images.get(c_type)
            if img:
                target_size = 36
                scaled_img = pygame.transform.smoothscale(img, (target_size, target_size)) if img.get_width() != target_size else img
                screen.blit(scaled_img, (mx - target_size // 2, my - target_size // 2))
            c_str = str(c_cnt)
            sh_s = inv_font.render(c_str, True, (0, 0, 0))
            fg_s = inv_font.render(c_str, True, (255, 255, 120))
            screen.blit(sh_s, (mx + 8, my + 4))
            screen.blit(fg_s, (mx + 7, my + 3))


def draw_bottom_inventory(S):
    """Renders the 5-cell pixel-art hotbar dock at bottom center."""
    screen = S.screen
    ensure_drop_images(S)

    if not hasattr(S, "hotbar"):
        S.hotbar = [{"type": None, "count": 0} for _ in range(5)]
    if not hasattr(S, "selected_slot"):
        S.selected_slot = 0

    dock_img = ensure_hotbar_dock_image(S)
    hb_w = 294
    hb_h = 64
    hb_x = (cfg.WIDTH - hb_w) // 2
    hb_y = cfg.HEIGHT - hb_h - 8

    # Blit the wooden hotbar dock asset
    if dock_img:
        screen.blit(dock_img, (hb_x, hb_y))

    if not hasattr(S, "inv_font"):
        S.inv_font = pygame.font.SysFont(cfg.MONO_FONTS, 11, bold=True)
    if not hasattr(S, "slot_num_font"):
        S.slot_num_font = pygame.font.SysFont(cfg.MONO_FONTS, 10, bold=True)

    slot_rects = get_hotbar_slot_rects()
    mx, my = pygame.mouse.get_pos()

    for i in range(5):
        slot = S.hotbar[i]
        cell_rect = slot_rects[i]
        is_sel = (i == S.selected_slot)
        is_hover = cell_rect.collidepoint((mx, my))

        # Active slot selection or hover highlight
        if is_sel:
            pygame.draw.rect(screen, (255, 215, 60), cell_rect.inflate(2, 2), width=2, border_radius=4)
            hl = pygame.Surface((cell_rect.width, cell_rect.height), pygame.SRCALPHA)
            hl.fill((255, 215, 60, 45))
            screen.blit(hl, cell_rect.topleft)
        elif is_hover:
            pygame.draw.rect(screen, (255, 235, 140, 180), cell_rect, width=1, border_radius=4)

        # Slot number keybind badge (1-5)
        num_col = (255, 220, 80) if is_sel else (180, 190, 205)
        num_surf = S.slot_num_font.render(str(i + 1), True, num_col)
        screen.blit(num_surf, (cell_rect.x + 4, cell_rect.y + 2))

        # Item icon & quantity
        itype = slot.get("type")
        count = slot.get("count", 0)
        if itype and count > 0:
            img = S.drop_images.get(itype)
            if img:
                target_size = 32
                scaled_img = pygame.transform.smoothscale(img, (target_size, target_size)) if img.get_width() != target_size else img
                screen.blit(scaled_img, (cell_rect.centerx - target_size // 2, cell_rect.centery - target_size // 2))
            cnt_txt = str(count)
            sh_surf = S.inv_font.render(cnt_txt, True, (0, 0, 0))
            fg_surf = S.inv_font.render(cnt_txt, True, (255, 255, 255))
            screen.blit(sh_surf, (cell_rect.right - fg_surf.get_width() - 2, cell_rect.bottom - fg_surf.get_height() - 1))
            screen.blit(fg_surf, (cell_rect.right - fg_surf.get_width() - 3, cell_rect.bottom - fg_surf.get_height() - 2))

    S.inv_open_btn = None
    S.craft_open_btn = None


def draw_crafting_menu(S, now):
    """Draws the Crafting Bench modal with recipe requirements and craft buttons."""
    if not getattr(S, "crafting_open", False):
        return

    screen = S.screen
    screen.blit(get_screen_overlay(155), (0, 0))

    cw, ch = 520, 390
    cx = (cfg.WIDTH - cw) // 2
    cy = (cfg.HEIGHT - ch) // 2
    card_rect = pygame.Rect(cx, cy, cw, ch)

    # Card background & gold border
    pygame.draw.rect(screen, (18, 24, 34), card_rect, border_radius=10)
    pygame.draw.rect(screen, (210, 180, 90), card_rect, width=2, border_radius=10)
    inner = pygame.Rect(cx + 6, cy + 6, cw - 12, ch - 12)
    pygame.draw.rect(screen, (14, 18, 26), inner, border_radius=8)

    # Header
    draw_text(screen, "SURVIVAL CRAFTING BENCH", S.big_font, 0, cy + 16, (255, 220, 80), center_x=cfg.WIDTH // 2)
    draw_text(screen, "Gather resources to forge survival equipment & ammo  (Close: C / ESC)", S.small_font, 0, cy + 44, (160, 175, 195), center_x=cfg.WIDTH // 2)
    draw_divider(screen, cx + 24, cy + 64, cw - 48)

    # Close button [X]
    S.craft_x_btn = Button(card_rect.right - 34, cy + 12, 24, 24, "X", palette={"fill": (80, 30, 30), "border": (200, 60, 60)})
    S.craft_x_btn.draw(screen, S.small_font)

    ensure_drop_images(S)
    if not hasattr(S, "craft_buttons"):
        S.craft_buttons = []
    S.craft_buttons = []

    if not hasattr(S, "craft_scroll"):
        S.craft_scroll = 0
    if not hasattr(S, "craft_selected_idx"):
        S.craft_selected_idx = 0

    visible_recipes = 5
    max_scroll = max(0, len(CRAFTING_RECIPES) - visible_recipes)
    S.craft_scroll = max(0, min(max_scroll, S.craft_scroll))

    start_idx = S.craft_scroll
    end_idx = min(len(CRAFTING_RECIPES), start_idx + visible_recipes)

    row_y = cy + 74
    row_h = 56

    for r_idx in range(start_idx, end_idx):
        recipe = CRAFTING_RECIPES[r_idx]
        can_craft = can_craft_recipe(S, recipe)
        is_focused = (r_idx == getattr(S, "craft_selected_idx", 0))

        row_rect = pygame.Rect(cx + 20, row_y, cw - 40, row_h - 4)
        row_bg = (28, 38, 52) if is_focused else (20, 26, 36)
        row_border = (255, 215, 60) if is_focused else (45, 58, 78)
        pygame.draw.rect(screen, row_bg, row_rect, border_radius=6)
        pygame.draw.rect(screen, row_border, row_rect, width=1, border_radius=6)

        # Output icon
        img = S.drop_images.get(recipe.get("result_type", "wood"))
        if img:
            screen.blit(img, (cx + 26, row_y + (row_h - 4 - 32) // 2))

        # Recipe name & yield
        draw_text(screen, recipe["name"], S.font, cx + 66, row_y + 6, cfg.WHITE)

        # Ingredient costs
        cost_parts = []
        inv = getattr(S, "inventory", {})
        for c_item, c_qty in recipe.get("cost", {}).items():
            have = inv.get(c_item, 0)
            cost_parts.append(f"{c_item.capitalize()}: {have}/{c_qty}")
        cost_txt = "Cost: " + ", ".join(cost_parts)
        cost_col = (130, 230, 150) if can_craft else (220, 120, 120)
        draw_text(screen, cost_txt, S.small_font, cx + 66, row_y + 28, cost_col)

        # CRAFT button
        btn_bg = cfg.GREEN if can_craft else (65, 75, 90)
        c_btn = Button(row_rect.right - 84, row_y + 10, 74, 32, "CRAFT", palette={"fill": btn_bg, "border": btn_bg})
        c_btn.draw(screen, S.small_font)
        S.craft_buttons.append((r_idx, c_btn))

        row_y += row_h

    # Navigation tip
    draw_text(screen, "Scroll / D-Pad: Select Recipe  •  Enter / A: Craft  •  ESC: Close", S.small_font, 0, card_rect.bottom - 24, (140, 155, 175), center_x=cfg.WIDTH // 2)


def draw_damage_popups(S, screen, dt):
    """Update and render animated floating damage counters above characters."""
    if not hasattr(S, "damage_popups") or not S.damage_popups:
        return
    if not hasattr(S, "dmg_font"):
        S.dmg_font = pygame.font.SysFont(cfg.MONO_FONTS, 15, bold=True)

    surviving = []
    for dp in S.damage_popups:
        dp["life"] -= dt
        dp["x"] += dp.get("vx", 0.0) * dt
        dp["y"] += dp.get("vy", -55.0) * dt
        dp["vy"] = dp.get("vy", -55.0) + 130.0 * dt
        if dp["life"] <= 0:
            continue
        max_l = dp.get("max_life", 0.85)
        alpha_ratio = max(0.0, min(1.0, dp["life"] / max_l))
        col = dp.get("color", (255, 90, 90))
        txt = dp.get("text", "")
        base_surf = S.dmg_font.render(txt, True, col)
        outline_surf = S.dmg_font.render(txt, True, (20, 20, 20))
        tw, th = base_surf.get_size()
        surf = pygame.Surface((tw + 4, th + 4), pygame.SRCALPHA)
        for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            surf.blit(outline_surf, (ox + 2, oy + 2))
        surf.blit(base_surf, (2, 2))

        # Juicy dynamic scale pop on fresh hits
        age = max_l - dp["life"]
        if age < 0.12:
            scale_mul = 1.0 + (0.12 - age) * 2.5
            nw = max(1, int((tw + 4) * scale_mul))
            nh = max(1, int((th + 4) * scale_mul))
            surf = pygame.transform.scale(surf, (nw, nh))
            tw, th = nw, nh

        if alpha_ratio < 0.35:
            surf.set_alpha(int(255 * (alpha_ratio / 0.35)))
        screen.blit(surf, (int(dp["x"] - tw // 2), int(dp["y"] - th // 2)))
        surviving.append(dp)
    S.damage_popups = surviving


def draw_hud_compass_and_notebook(S, now):
    """Draws the expedition compass (pointing to Base Camp at 0, 0) and clickable notebook journal icon."""
    if S.state not in (STATE_TEST, STATE_LOCAL):
        return

    screen = S.screen

    # 1. Notebook Journal Icon (bottom-left)
    if not hasattr(S, "notepad_icon") or S.notepad_icon is None:
        try:
            raw_icon = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "notebook.png")).convert_alpha()
            bbox = raw_icon.get_bounding_rect()
            cropped = raw_icon.subsurface(bbox)
            S.notepad_icon = pygame.transform.smoothscale(cropped, (42, 42))
        except Exception:
            S.notepad_icon = pygame.Surface((42, 42), pygame.SRCALPHA)
            pygame.draw.rect(S.notepad_icon, (190, 160, 110), (4, 4, 34, 34), border_radius=6)

    nb_w, nb_h = 48, 48
    nb_x = 20
    nb_y = cfg.HEIGHT - nb_h - 18
    S.notepad_rect = pygame.Rect(nb_x, nb_y, nb_w, nb_h)

    mpos = pygame.mouse.get_pos()
    is_hover = S.notepad_rect.collidepoint(mpos)

    # Frame
    nb_surf = pygame.Surface((nb_w, nb_h), pygame.SRCALPHA)
    bg_col = (28, 38, 54, 220) if is_hover else (18, 24, 35, 200)
    border_col = (255, 215, 60) if is_hover else (55, 70, 95, 200)
    pygame.draw.rect(nb_surf, bg_col, (0, 0, nb_w, nb_h), border_radius=8)
    pygame.draw.rect(nb_surf, border_col, (0, 0, nb_w, nb_h), width=2 if is_hover else 1, border_radius=8)
    screen.blit(nb_surf, (nb_x, nb_y))

    # Icon inside frame
    iw = S.notepad_icon.get_width()
    ih = S.notepad_icon.get_height()
    screen.blit(S.notepad_icon, (nb_x + (nb_w - iw) // 2, nb_y + (nb_h - ih) // 2))

    # 2. Expedition Compass (bottom-right)
    if not hasattr(S, "compass_base") or S.compass_base is None:
        try:
            cb = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "compass", "base.png")).convert_alpha()
            cn = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "compass", "needle.png")).convert_alpha()
            cc = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "compass", "cover.png")).convert_alpha()
            SCALE = 1.25
            cw, ch = int(cb.get_width() * SCALE), int(cb.get_height() * SCALE)
            S.compass_base = pygame.transform.scale(cb, (cw, ch))
            S.compass_needle = pygame.transform.scale(cn, (int(cn.get_width() * SCALE), int(cn.get_height() * SCALE)))
            S.compass_cover = pygame.transform.scale(cc, (int(cc.get_width() * SCALE), int(cc.get_height() * SCALE)))
            S.compass_scale = SCALE
        except Exception:
            S.compass_base = pygame.Surface((100, 120), pygame.SRCALPHA)
            S.compass_needle = pygame.Surface((60, 60), pygame.SRCALPHA)
            S.compass_cover = pygame.Surface((60, 60), pygame.SRCALPHA)
            S.compass_scale = 1.0

    cw, ch = S.compass_base.get_size()
    # Compass positioned in bottom-right corner above help icon
    compass_x = cfg.WIDTH - cw - 14
    compass_y = cfg.HEIGHT - ch - 48
    screen.blit(S.compass_base, (compass_x, compass_y))

    scale = getattr(S, "compass_scale", 1.25)
    dial_center = (compass_x + int(40 * scale), compass_y + int(52 * scale))

    # Stationary dial letters (N, S, E, W)
    nr = S.compass_needle.get_rect(center=dial_center)
    screen.blit(S.compass_needle, nr.topleft)

    # Dynamic needle pointing to (0, 0) Base Camp
    target_p = S.local_players[0] if (getattr(S, "state", None) in (STATE_LOCAL, "local") and getattr(S, "local_players", None) and len(S.local_players) > 0) else getattr(S, "me", (0, 0, 0))
    target_wx, target_wy = S.iso.world_px(0, 0)
    player_wx, player_wy = S.iso.world_px(target_p[0], target_p[1])
    dx = target_wx - player_wx
    dy = target_wy - player_wy
    if math.hypot(dx, dy) > 0.1:
        target_deg = math.degrees(math.atan2(dy, dx))
        angle = (-target_deg - 47.0) % 360.0
    else:
        angle = 0.0
    rotated_pointer = pygame.transform.rotate(S.compass_cover, angle)
    pr = rotated_pointer.get_rect(center=dial_center)
    screen.blit(rotated_pointer, pr.topleft)


def load_game_icons(S):
    """Load controller button icons matching detected gamepad family (Xbox, PlayStation, Nintendo)
    and load the background-free UI glyphs."""
    if not hasattr(S, "controller_mgr"):
        S.controller_mgr = controller.ControllerManager(S.ASSETS_DIR)
    S.pad = S.controller_mgr.get_icons()
    # pixel-art heart (crisp nearest-neighbor scale, aspect preserved)
    S.heart_img = None
    try:
        hi = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "heart.png")).convert_alpha()
        w, h = hi.get_size()
        S.heart_img = pygame.transform.scale(hi, (28, max(1, round(28 * h / w))))
    except Exception as e:
        print(f"[icons] heart: {e}")
    # spawn-point marker tile (a full cube tile drawn on the spawn cell)
    S.spawn_img = None
    try:
        S.spawn_img = pygame.image.load(
            os.path.join(S.ASSETS_DIR, "tiles", "tilex1.png")).convert_alpha()
    except Exception as e:
        print(f"[icons] tilex1: {e}")
    S.uicons = {}
    uidir = os.path.join(S.ASSETS_DIR, "ui")
    try:
        for fn in os.listdir(uidir):
            if fn.endswith(".png"):
                ic = pygame.image.load(os.path.join(uidir, fn)).convert_alpha()
                S.uicons[fn[:-4]] = pygame.transform.scale(ic, (22, 22))
    except Exception as e:
        print(f"[icons] ui glyphs: {e}")


CURSOR_SCALE = 1.75  # 16px source -> 28px on the canvas
CURSOR_HOTSPOTS = {   # in source (16px) coords, before scaling
    "arrow": (1, 1), "point": (5, 1), "grab": (8, 8),
    "open": (8, 8), "hand": (8, 8), "busy": (8, 8),
}


def load_cursors(S):
    """Load the Kenney pixel cursors and hide the OS cursor so we can draw our
    own on the canvas (scales correctly with the letterbox)."""
    S.cursors = {}
    cdir = os.path.join(S.ASSETS_DIR, "cursors")
    try:
        for name in ("arrow", "point", "open", "grab", "hand", "busy"):
            img = pygame.image.load(os.path.join(cdir, name + ".png")).convert_alpha()
            w, h = img.get_size()
            S.cursors[name] = pygame.transform.scale(
                img, (round(w * CURSOR_SCALE), round(h * CURSOR_SCALE)))
    except Exception as e:
        print(f"[cursors] {e}")
    # full selectable pack — press F2 to cycle your pointer through all of them
    S.cursor_pack = []
    pdir = os.path.join(cdir, "pack")
    try:
        for fn in sorted(os.listdir(pdir)):
            if fn.endswith(".png"):
                img = pygame.image.load(os.path.join(pdir, fn)).convert_alpha()
                w, h = img.get_size()
                S.cursor_pack.append(pygame.transform.scale(
                    img, (round(w * CURSOR_SCALE), round(h * CURSOR_SCALE))))
    except Exception as e:
        print(f"[cursors] pack: {e}")
    if not hasattr(S, "cursor_index"):
        S.cursor_index = 0   # 0 = contextual set; >0 picks pack[index-1] as pointer
    pygame.mouse.set_visible(not S.cursors)  # keep OS cursor only if load failed


def cursor_kind(S):
    """Pick which cursor to show for the current context."""
    if S.state in (STATE_WAKE, STATE_WAIT):
        return "busy"
    mp = pygame.mouse.get_pos()
    hot = lambda rects: any(r.collidepoint(mp) for r in rects)
    if S.show_settings:
        if S.volume_slider.dragging or S.cam_smooth_slider.dragging:
            return "grab"
        return "point" if hot([S.volume_slider.rect,
                                S.music_toggle.rect, S.prev_btn.rect, S.play_pause_btn.rect,
                                S.next_btn.rect, S.settings_close_btn.rect,
                                S.settings_x.rect]) else "arrow"
    if S.show_keys:
        return "point"
    if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
        return "point" if hot([S.pause_resume_btn.rect, S.pause_help_btn.rect,
                               S.pause_settings_btn.rect, S.pause_quit_btn.rect]) else "arrow"
    if hot([S.help_icon_btn.rect, S.close_btn.rect]):
        return "point"
    if S.state == STATE_MENU:
        return "point" if hot([b.rect for b in S.MENU_FOCUS]) else "arrow"
    if S.state == STATE_SETUP:
        rects = [S.setup_confirm_btn.rect, S.panel_x.rect] + [i.rect for i in S.name_inputs]
        if S.setup_mode in ("join", "host"):
            rects.append(S.addr_input.rect)
        if S.setup_mode == "join":
            rects.append(S.code_input.rect)
        if S.setup_mode in ("host", "local"):
            rects += [S.lobby_name_input.rect, S.max_players_stepper.rect]
        return "point" if hot(rects) else "arrow"
    return "arrow"


def draw_cursor(S, now):
    if not getattr(S, "cursors", None):
        return
    kind = cursor_kind(S)
    mx, my = pygame.mouse.get_pos()
    # a chosen pack cursor overrides the plain pointer states (arrow/point)
    idx = getattr(S, "cursor_index", 0)
    if idx and kind in ("arrow", "point") and getattr(S, "cursor_pack", None):
        img = S.cursor_pack[(idx - 1) % len(S.cursor_pack)]
        hx, hy = CURSOR_HOTSPOTS.get(kind, (1, 1))
        S.screen.blit(img, (int(mx - hx * CURSOR_SCALE), int(my - hy * CURSOR_SCALE)))
        return
    img = S.cursors.get(kind) or S.cursors.get("arrow")
    if not img:
        return
    if kind == "busy":  # spin the loading ring, centered on the pointer
        rot = pygame.transform.rotate(img, (-now * 300) % 360)
        S.screen.blit(rot, (int(mx - rot.get_width() / 2), int(my - rot.get_height() / 2)))
        return
    hx, hy = CURSOR_HOTSPOTS.get(kind, (1, 1))
    S.screen.blit(img, (int(mx - hx * CURSOR_SCALE), int(my - hy * CURSOR_SCALE)))


def draw_mic(S, screen, cx, cy, h, color, active=True):
    """Microphone glyph, centered on (cx, cy)."""
    if active and S.uicons.get("mic"):
        ic = S.uicons["mic"]
        screen.blit(ic, (cx - ic.get_width() // 2, cy - ic.get_height() // 2))
        return
    if not active and S.uicons.get("mute_red"):
        ic = S.uicons["mute_red"]
        screen.blit(ic, (cx - ic.get_width() // 2, cy - ic.get_height() // 2))
        return
    bw = max(6, int(h * 0.44))
    bh = int(h * 0.68)
    body = pygame.Rect(0, 0, bw, bh)
    body.center = (cx, cy - int(h * 0.14))
    pygame.draw.rect(screen, color, body, border_radius=bw // 2)
    pygame.draw.rect(screen, (12, 14, 18), body, 2, border_radius=bw // 2)
    # stand + base
    base_y = cy + int(h * 0.46)
    pygame.draw.line(screen, color, (cx, body.bottom - 1), (cx, base_y), 3)
    pygame.draw.line(screen, color, (cx - bw, base_y), (cx + bw, base_y), 3)
    if active:                                   # symmetric sound waves either side
        for r in (bw + 5, bw + 11):
            box = (cx - r, body.centery - r, r * 2, r * 2)
            pygame.draw.arc(screen, color, box, -0.7, 0.7, 2)            # right
            pygame.draw.arc(screen, color, box, math.pi - 0.7, math.pi + 0.7, 2)  # left


def draw_chat(S, now):
    """Minecraft-style chat: recent lines bottom-left, fading when closed; an
    input box appears while typing."""
    screen = S.screen
    x = 12
    input_h = 26
    bottom = cfg.HEIGHT - 44 - (input_h + 6 if S.chat_open else 0)
    line_h = 18
    shown = [m for m in S.chat_log[-9:]
             if S.chat_open or (now - m["t"]) < CHAT_FADE]
    for k, m in enumerate(reversed(shown)):
        age = now - m["t"]
        if S.chat_open:
            alpha = 255
        else:
            alpha = 255 if age < CHAT_FADE - 1.5 else int(255 * max(0.0, (CHAT_FADE - age) / 1.5))
        y = bottom - k * line_h
        name = f"{m['name']}: "
        nsurf = S.small_font.render(name, True, m["color"])
        tsurf = S.small_font.render(m["text"], True, cfg.WHITE)
        w = nsurf.get_width() + tsurf.get_width() + 12
        strip = pygame.Surface((w, line_h), pygame.SRCALPHA)
        strip.fill((6, 10, 14, int(alpha * 0.55)))
        nsurf.set_alpha(alpha); tsurf.set_alpha(alpha)
        strip.blit(nsurf, (6, 1)); strip.blit(tsurf, (6 + nsurf.get_width(), 1))
        screen.blit(strip, (x, y - line_h))
    if S.chat_open:
        box = pygame.Rect(x, cfg.HEIGHT - 44 - input_h, cfg.WIDTH - 24, input_h)
        panel = pygame.Surface(box.size, pygame.SRCALPHA)
        panel.fill((6, 10, 14, 210))
        pygame.draw.rect(panel, cfg.GOLD, panel.get_rect(), 1)
        screen.blit(panel, box.topleft)
        caret = "_" if int(now * 2) % 2 == 0 else " "
        draw_text(screen, "> " + S.chat_input + caret, S.font, box.x + 8, box.y + 4, cfg.WHITE)


# action, key label, ui-glyph name (or "mic"/None), controller button (or None)
KEYBINDS = [
    ("Move (isometric)", "WASD / L-Stick", None, None),
    ("Aim (360°)", "Mouse / R-Stick", None, None),
    ("Attack / Shoot / Mine", "Left Click", None, "RT"),
    ("Open Chest / Interact", "F", None, "X"),
    ("Backpack Inventory", "E", None, "D-Pad Up"),
    ("Inventory (Hotbar)", "1 - 5", None, "D-Pad"),
    ("Arsenal (Weapons/Tools)", "Shift + Scroll", None, "RB"),
    ("Zoom In / Out", "Mouse Scroll", None, "R3"),
    ("Jump", "Space", "up", "A"),
    ("Roll / Dodge", "Right Click", None, "LT"),
    ("Dash", "L-Shift / Q", None, "LB"),
    ("Crafting Menu", "C", None, "Y"),
    ("Open Chat", "T / Enter", None, None),
    ("Push-to-talk", "hold V", "mic", None),
    ("Switch Tilemap", "Tab", "redo", None),
    ("Pause / Resume", "Esc", "back", "MENU"),
    ("Keybinds", "F1", "menu", "BACK"),
    ("Fullscreen", "F11", None, None),
    ("Quit", "window X", "close", None),
]


HELP_INTRO = ("Explore an endless, procedurally-generated isometric world. Walk the "
              "terrain, hop over rocks, and reshape the map on the fly — solo, in "
              "same-screen co-op, or online with a friend via a room code.")


def keybinds_rect():
    w, h = 540, 168 + len(KEYBINDS) * 28
    return pygame.Rect(cfg.WIDTH // 2 - w // 2, cfg.HEIGHT // 2 - h // 2, w, h)


_OVERLAY_CACHE = {}
def get_screen_overlay(alpha=150):
    surf = _OVERLAY_CACHE.get(alpha)
    if surf is None:
        surf = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
        surf.fill((0, 0, 0, alpha))
        _OVERLAY_CACHE[alpha] = surf
    return surf


def draw_keybinds(S, now):
    screen = S.screen
    screen.blit(get_screen_overlay(160), (0, 0))
    rect = keybinds_rect()
    icon = S.uicons.get("menu")
    tx = rect.x + 28
    if icon:
        screen.blit(icon, (rect.x + 22, rect.y + 20)); tx = rect.x + 52
    draw_text(screen, "HOW TO PLAY", S.big_font, tx, rect.y + 20, cfg.GOLD)
    # intro / goal blurb
    ih = draw_wrapped_text(screen, HELP_INTRO, S.small_font, rect.y + 58,
                           rect.w - 56, cfg.MUTED, line_gap=3)

    # Active controller indicator badge
    ctype = getattr(S.controller_mgr, "active_type", controller.TYPE_XBOX) if hasattr(S, "controller_mgr") else "xbox"
    c_name = controller.FAMILY_NAMES.get(ctype, "Gamepad").upper()
    draw_text(screen, f"CONTROLLER DETECTED: {c_name}", S.small_font, rect.x + 28, rect.y + 62 + ih, cfg.GOLD)
    div_y = rect.y + 82 + ih
    draw_divider(screen, rect.x + 24, div_y, rect.w - 48)
    y = div_y + 12
    for action, keylabel, glyph, pad in KEYBINDS:
        draw_text(screen, action, S.font, rect.x + 28, y, cfg.WHITE)
        # right-aligned: [pad icon] [glyph] key-chip
        rx = rect.right - 28
        chip = S.small_font.render(keylabel, True, cfg.GOLD)
        cw = chip.get_width() + 16
        chip_rect = pygame.Rect(rx - cw, y - 1, cw, 22)
        pygame.draw.rect(screen, cfg.INPUT_BG, chip_rect, border_radius=6)
        pygame.draw.rect(screen, cfg.INPUT_BORDER, chip_rect, 1, border_radius=6)
        screen.blit(chip, (chip_rect.x + 8, chip_rect.y + 3))
        rx = chip_rect.x - 8
        if pad and S.pad.get(pad):
            rx -= 26; screen.blit(S.pad[pad], (rx, y - 3))
        if glyph == "mic":
            rx -= 24; draw_mic(S, screen, rx + 8, y + 9, 16, cfg.GOLD, active=False)
        elif glyph and S.uicons.get(glyph):
            rx -= 24; screen.blit(S.uicons[glyph], (rx, y - 1))
        y += 28
    draw_text(screen, "F1 / Esc / Back to close", S.small_font, 0, rect.bottom - 24,
              cfg.GOLD_FAINT, center_x=rect.centerx)


def canvas_to_window(S, pos):
    if hasattr(S, "to_window") and callable(S.to_window):
        return S.to_window(pos)
    ww, wh = (cfg.WIDTH, cfg.HEIGHT)
    if hasattr(S, "window") and S.window:
        try:
            ww, wh = S.window.get_size()
        except Exception:
            pass
    return (int(pos[0] * (ww / cfg.WIDTH)), int(pos[1] * (wh / cfg.HEIGHT)))


def get_setup_focusables(S):
    mode = getattr(S, "setup_mode", "single")
    if mode == "single":
        return [S.name_inputs[0], S.setup_confirm_btn]
    elif mode == "local":
        n = setup_name_count(S)
        items = [S.lobby_name_input, S.max_players_stepper]
        for i in range(n):
            items.append(S.name_inputs[i])
        items.append(S.setup_confirm_btn)
        return items
    elif mode == "host":
        return [S.addr_input, S.lobby_name_input, S.max_players_stepper, S.name_inputs[0], S.setup_confirm_btn]
    elif mode == "join":
        return [S.addr_input, S.code_input, S.name_inputs[0], S.setup_confirm_btn]
    return [S.setup_confirm_btn]


def get_settings_focusables(S):
    return [
        S.volume_slider,
        S.cam_smooth_slider,
        S.music_toggle,
        S.fps_toggle,
        S.render_dist_stepper,
        S.prev_btn,
        S.play_pause_btn,
        S.next_btn,
        S.keybinds_btn,
        S.settings_close_btn,
    ]


def get_pause_focusables(S):
    return [
        S.pause_resume_btn,
        S.pause_help_btn,
        S.pause_settings_btn,
        S.pause_quit_btn,
    ]


def get_wait_focusables(S):
    items = []
    if not getattr(S, "is_host", False) and getattr(S, "lobby_ready_btn", None):
        items.append(S.lobby_ready_btn)
    if getattr(S, "is_host", False):
        if getattr(S, "lobby_start_btn", None):
            items.append(S.lobby_start_btn)
        for btn in getattr(S, "lobby_kick_btns", {}).values():
            items.append(btn)
        for btn in getattr(S, "lobby_restrict_btns", {}).values():
            items.append(btn)
    return items


def snap_cursor_to_widget(S, widget):
    if hasattr(widget, "rect"):
        cx, cy = widget.rect.center
        S.virtual_mouse_pos = [float(cx), float(cy)]
        wx, wy = canvas_to_window(S, S.virtual_mouse_pos)
        S._setting_mouse_pos = True
        try:
            pygame.mouse.set_pos((wx, wy))
        except Exception:
            pass
        S._setting_mouse_pos = False


def draw_pause(S, now):
    """In-world pause overlay: dims the game and offers resume / help /
    settings / quit."""
    screen = S.screen
    screen.blit(get_screen_overlay(150), (0, 0))
    rect = S.pause_rect
    draw_glow_text(screen, "PAUSED", S.big_font, 0, rect.y + 26, cfg.GOLD, cfg.GOLD,
                   center_x=rect.centerx)
    sub = S.lobby_name or ("ROOM " + S.room_code if S.room_code else "")
    if sub:
        draw_text(screen, sub[:34], S.small_font, 0, rect.y + 58, cfg.GOLD_DIM,
                  center_x=rect.centerx)
    draw_divider(screen, rect.x + 28, rect.y + 78, rect.w - 56)
    pause_btns = (S.pause_resume_btn, S.pause_help_btn, S.pause_settings_btn, S.pause_quit_btn)
    cur_focus = getattr(S, "pause_focus_idx", 0) % len(pause_btns)
    for i, btn in enumerate(pause_btns):
        btn.draw(screen, S.font)
        if getattr(S, "using_controller", False) and i == cur_focus:
            draw_focus_ring(screen, btn.rect, color=cfg.GOLD, pad=4)
    draw_text(screen, "Esc to resume", S.small_font, 0, rect.bottom - 26,
              cfg.GOLD_FAINT, center_x=rect.centerx)


def draw_header(S, subtitle):
    screen = S.screen
    if getattr(S, "header_logo", None):
        hx = CENTER_X - S.header_logo.get_width() // 2
        screen.blit(S.header_logo, (hx, 20))
        draw_text(screen, subtitle, S.small_font, 0, 106, cfg.GOLD_DIM, center_x=CENTER_X)
        draw_divider(screen, CENTER_X - 180, 128, 360)
    else:
        draw_glow_text(screen, "ASHERFALL", S.brand_font, 0, 36, cfg.GOLD, cfg.GOLD, center_x=CENTER_X)
        draw_text(screen, subtitle, S.small_font, 0, 92, cfg.GOLD_DIM, center_x=CENTER_X)
        draw_divider(screen, CENTER_X - 180, 118, 360)


def draw_footer(S):
    screen = S.screen
    if getattr(S, "using_controller", False):
        ctype = getattr(S.controller_mgr, "active_type", controller.TYPE_XBOX) if hasattr(S, "controller_mgr") else controller.TYPE_XBOX
        if ctype == controller.TYPE_PLAYSTATION:
            prompt = "Gamepad: Stick moves cursor · ✕ Confirm / Click · ◯ Back / Cancel"
        elif ctype == controller.TYPE_NINTENDO:
            prompt = "Gamepad: Stick moves cursor · A / B Confirm · B / A Back"
        else:
            prompt = "Gamepad: Stick moves cursor · A Confirm / Click · B Back / Cancel"
        draw_text(screen, prompt, S.small_font,
                  0, cfg.HEIGHT - 32, cfg.GOLD_FAINT, center_x=CENTER_X)






def frame(S, events, dt, now):
    """One iteration: handle events, update, draw. Returns False to quit."""
    running = True

    # Hit-stop micro-pause for visceral impact feedback
    if getattr(S, "hitstop_timer", 0.0) > 0:
        S.hitstop_timer -= dt
        dt *= 0.15

    # Controller Virtual Mouse & Stick Cursor Tracking
    if not hasattr(S, "virtual_mouse_pos"):
        S.virtual_mouse_pos = [float(p) for p in pygame.mouse.get_pos()]

    p0_ctrl = S.controller_mgr.read_inputs(player_idx=0) if hasattr(S, "controller_mgr") else {}

    # Check for real hardware mouse movement vs virtual controller mouse
    for ev in events:
        if ev.type == pygame.MOUSEMOTION and not getattr(S, "_setting_mouse_pos", False) and not getattr(S, "_ctrl_clicking", False):
            S.virtual_mouse_pos = [float(ev.pos[0]), float(ev.pos[1])]
            S.using_controller = False
            break
        elif ev.type == pygame.MOUSEBUTTONDOWN and not getattr(S, "_ctrl_clicking", False):
            S.using_controller = False

    in_menu_mode = (
        S.state in (STATE_MENU, STATE_SETUP, STATE_WAIT) or
        getattr(S, "show_settings", False) or
        getattr(S, "paused", False) or
        getattr(S, "notepad_open", False) or
        getattr(S, "show_keys", False)
    )

    # Stick deflection for mouse movement:
    # Right stick always moves cursor. In menu mode, left stick also moves cursor.
    stick_x, stick_y = 0.0, 0.0
    rx = p0_ctrl.get("rx", 0.0)
    ry = p0_ctrl.get("ry", 0.0)
    dx = p0_ctrl.get("dx", 0.0)
    dy = p0_ctrl.get("dy", 0.0)

    if math.hypot(rx, ry) > 0.12:
        stick_x, stick_y = rx, ry
    elif in_menu_mode and math.hypot(dx, dy) > 0.12:
        stick_x, stick_y = dx, dy

    stick_mag = math.hypot(stick_x, stick_y)
    if stick_mag > 0.12:
        S.using_controller = True
        speed = 950.0 * (stick_mag ** 1.35)
        S.virtual_mouse_pos[0] = max(0.0, min(float(cfg.WIDTH), S.virtual_mouse_pos[0] + (stick_x / stick_mag) * speed * dt))
        S.virtual_mouse_pos[1] = max(0.0, min(float(cfg.HEIGHT), S.virtual_mouse_pos[1] + (stick_y / stick_mag) * speed * dt))
        wx, wy = canvas_to_window(S, S.virtual_mouse_pos)
        S._setting_mouse_pos = True
        try:
            pygame.mouse.set_pos((wx, wy))
        except Exception:
            pass
        S._setting_mouse_pos = False

    # Virtual mouse click generation in menus & overlays
    if in_menu_mode and hasattr(S, "controller_mgr") and S.controller_mgr.joysticks:
        want_click = p0_ctrl.get("fire", False) or p0_ctrl.get("confirm", False)
        was_click = getattr(S, "_ctrl_clicking", False)
        cur_cpos = (int(S.virtual_mouse_pos[0]), int(S.virtual_mouse_pos[1]))

        if want_click and not was_click:
            S._ctrl_clicking = True
            events.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": cur_cpos, "button": 1}))
        elif not want_click and was_click:
            S._ctrl_clicking = False
            events.append(pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": cur_cpos, "button": 1}))
        elif was_click and stick_mag > 0.12:
            events.append(pygame.event.Event(pygame.MOUSEMOTION, {"pos": cur_cpos, "rel": (int(stick_x * 5), int(stick_y * 5)), "buttons": (1, 0, 0)}))

    for event in events:
        if event.type == pygame.QUIT:
            running = False

        # --- keybinds panel: F1 toggles; swallow all input while it's open ---
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            S.show_keys = not S.show_keys
            continue
        # F2 cycles the pointer through the whole cursor pack (0 = default set)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F2:
            n = len(getattr(S, "cursor_pack", [])) + 1
            S.cursor_index = (getattr(S, "cursor_index", 0) + 1) % n
            continue
        if S.show_keys:
            if event.type == pygame.MOUSEBUTTONDOWN or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                S.show_keys = False
            continue

        # (Removed close_btn click handler)

        if event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings and S.help_icon_btn.clicked(event.pos):
            S.show_keys = True
            continue

        # per-panel close (X) at the card corner backs out one level
        if (event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings
                and S.state in (STATE_SETUP, STATE_WAIT) and S.panel_x.clicked(event.pos)):
            go_back(S)
            continue

        if event.type == S.MUSIC_END_EVENT:
            play_next_track(S)

        if event.type == pygame.JOYDEVICEADDED:
            if not hasattr(S, "controller_mgr"):
                S.controller_mgr = controller.ControllerManager(S.ASSETS_DIR)
            joy = S.controller_mgr.on_device_added(event.device_index)
            S.joysticks = S.controller_mgr.joysticks
            S.pad = S.controller_mgr.get_icons()

        if event.type == pygame.JOYDEVICEREMOVED:
            if hasattr(S, "controller_mgr"):
                S.controller_mgr.on_device_removed(getattr(event, "instance_id", None))
                S.joysticks = S.controller_mgr.joysticks
                S.pad = S.controller_mgr.get_icons()

        if event.type in (pygame.JOYHATMOTION, pygame.JOYBUTTONDOWN):
            S.using_controller = True

        if event.type == pygame.JOYHATMOTION:
            hx, hy = event.value
            if S.show_keys:
                pass
            elif S.show_settings:
                items = get_settings_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.settings_focus_idx = (getattr(S, "settings_focus_idx", 0) + delta) % len(items)
                    snap_cursor_to_widget(S, items[S.settings_focus_idx])
                elif hx != 0:
                    cur = items[getattr(S, "settings_focus_idx", 0) % len(items)]
                    if cur is S.volume_slider:
                        cur.value = max(0.0, min(1.0, cur.value + (0.05 if hx == 1 else -0.05)))
                        apply_volume(S)
                    elif cur is S.cam_smooth_slider:
                        cur.value = max(0.0, min(1.0, cur.value + (0.05 if hx == 1 else -0.05)))
                    elif cur is S.render_dist_stepper:
                        if hx == -1: cur.value = max(cur.lo, cur.value - 1)
                        else: cur.value = min(cur.hi, cur.value + 1)
                    elif cur in (S.prev_btn, S.play_pause_btn, S.next_btn):
                        m_btns = [S.prev_btn, S.play_pause_btn, S.next_btn]
                        m_idx = (m_btns.index(cur) + (1 if hx == 1 else -1)) % 3
                        S.settings_focus_idx = 5 + m_idx
                        snap_cursor_to_widget(S, m_btns[m_idx])
            elif getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
                items = get_pause_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.pause_focus_idx = (getattr(S, "pause_focus_idx", 0) + delta) % len(items)
                    snap_cursor_to_widget(S, items[S.pause_focus_idx])
            elif S.state == STATE_SETUP:
                items = get_setup_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.setup_focus_idx = (getattr(S, "setup_focus_idx", 0) + delta) % len(items)
                    cur = items[S.setup_focus_idx]
                    for inp in S.name_inputs + [S.addr_input, S.code_input, S.lobby_name_input]:
                        inp.active = False
                    if hasattr(cur, "active"):
                        cur.active = True
                    snap_cursor_to_widget(S, cur)
                elif hx != 0:
                    cur = items[getattr(S, "setup_focus_idx", 0) % len(items)]
                    if cur is S.max_players_stepper:
                        if hx == -1: cur.value = max(cur.lo, cur.value - 1)
                        else: cur.value = min(cur.hi, cur.value + 1)
            elif S.state == STATE_WAIT:
                items = get_wait_focusables(S)
                if items and (hy != 0 or hx != 0):
                    S.wait_focus_idx = (getattr(S, "wait_focus_idx", 0) + 1) % len(items)
                    snap_cursor_to_widget(S, items[S.wait_focus_idx])
            if getattr(S, "crafting_open", False) and S.state in (STATE_LOCAL, STATE_TEST):
                if hy == 1:
                    S.craft_selected_idx = max(0, getattr(S, "craft_selected_idx", 0) - 1)
                    if S.craft_selected_idx < getattr(S, "craft_scroll", 0):
                        S.craft_scroll = S.craft_selected_idx
                elif hy == -1:
                    S.craft_selected_idx = min(len(CRAFTING_RECIPES) - 1, getattr(S, "craft_selected_idx", 0) + 1)
                    if S.craft_selected_idx >= getattr(S, "craft_scroll", 0) + 5:
                        S.craft_scroll = S.craft_selected_idx - 4
            elif S.show_keys:
                pass
            elif S.show_settings:
                items = get_settings_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.settings_focus_idx = (getattr(S, "settings_focus_idx", 0) + delta) % len(items)
                    snap_cursor_to_widget(S, items[S.settings_focus_idx])
                elif hx != 0:
                    cur = items[getattr(S, "settings_focus_idx", 0) % len(items)]
                    if cur is S.volume_slider:
                        cur.value = max(0.0, min(1.0, cur.value + (0.05 if hx == 1 else -0.05)))
                        apply_volume(S)
                    elif cur is S.cam_smooth_slider:
                        cur.value = max(0.0, min(1.0, cur.value + (0.05 if hx == 1 else -0.05)))
                    elif cur is S.render_dist_stepper:
                        if hx == -1: cur.value = max(cur.lo, cur.value - 1)
                        else: cur.value = min(cur.hi, cur.value + 1)
                    elif cur in (S.prev_btn, S.play_pause_btn, S.next_btn):
                        m_btns = [S.prev_btn, S.play_pause_btn, S.next_btn]
                        m_idx = (m_btns.index(cur) + (1 if hx == 1 else -1)) % 3
                        S.settings_focus_idx = 5 + m_idx
                        snap_cursor_to_widget(S, m_btns[m_idx])
            elif getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
                items = get_pause_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.pause_focus_idx = (getattr(S, "pause_focus_idx", 0) + delta) % len(items)
                    snap_cursor_to_widget(S, items[S.pause_focus_idx])
            elif S.state == STATE_SETUP:
                items = get_setup_focusables(S)
                if hy != 0:
                    delta = -1 if hy == 1 else 1
                    S.setup_focus_idx = (getattr(S, "setup_focus_idx", 0) + delta) % len(items)
                    cur = items[S.setup_focus_idx]
                    for inp in S.name_inputs + [S.addr_input, S.code_input, S.lobby_name_input]:
                        inp.active = False
                    if hasattr(cur, "active"):
                        cur.active = True
                    snap_cursor_to_widget(S, cur)
                elif hx != 0:
                    cur = items[getattr(S, "setup_focus_idx", 0) % len(items)]
                    if cur is S.max_players_stepper:
                        if hx == -1: cur.value = max(cur.lo, cur.value - 1)
                        else: cur.value = min(cur.hi, cur.value + 1)
            elif S.state == STATE_WAIT:
                items = get_wait_focusables(S)
                if items and (hy != 0 or hx != 0):
                    S.wait_focus_idx = (getattr(S, "wait_focus_idx", 0) + 1) % len(items)
                    snap_cursor_to_widget(S, items[S.wait_focus_idx])
            elif S.state == STATE_MENU:
                if hy == -1:
                    S.focus_index = (S.focus_index + 1) % len(S.MENU_FOCUS)
                    snap_cursor_to_widget(S, S.MENU_FOCUS[S.focus_index])
                elif hy == 1:
                    S.focus_index = (S.focus_index - 1) % len(S.MENU_FOCUS)
                    snap_cursor_to_widget(S, S.MENU_FOCUS[S.focus_index])

        if event.type == pygame.JOYBUTTONDOWN:
            ctype = getattr(S.controller_mgr, "active_type", controller.TYPE_XBOX) if hasattr(S, "controller_mgr") else controller.TYPE_XBOX
            is_confirm = (event.button in (0, 1) if ctype == controller.TYPE_NINTENDO else event.button == 0)
            is_cancel = (event.button in (0, 1) if ctype == controller.TYPE_NINTENDO else event.button == 1)
            is_start = event.button in (6, 7, 9)
            is_select = event.button in (4, 6, 8, 11)

            if is_start:
                if S.state in (STATE_LOCAL, STATE_TEST):
                    S.paused = not getattr(S, "paused", False)
                    if S.paused:
                        S.pause_focus_idx = 0
                        snap_cursor_to_widget(S, S.pause_resume_btn)
                elif S.state == STATE_MENU:
                    S.show_settings = not getattr(S, "show_settings", False)
                    if S.show_settings:
                        S.settings_focus_idx = 0
                        snap_cursor_to_widget(S, S.volume_slider)
            elif is_select and S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False):
                S.notepad_open = not getattr(S, "notepad_open", False)

            # In-game hotbar and crafting controls for controller:
            if S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False):
                if event.button == 4:  # LB: cycle hotbar left
                    S.selected_slot = (getattr(S, "selected_slot", 0) - 1) % 5
                elif event.button == 5:  # RB: cycle hotbar right
                    S.selected_slot = (getattr(S, "selected_slot", 0) + 1) % 5
                elif event.button == 2:  # X Button (Square on PS): Interact / Open Chest / Use Item
                    if not getattr(S, "crafting_open", False):
                        interact_or_open_chest(S)
                elif event.button == 3:  # Y Button (Triangle on PS)
                    S.crafting_open = not getattr(S, "crafting_open", False)

            if getattr(S, "crafting_open", False) and S.state in (STATE_LOCAL, STATE_TEST):
                if is_confirm:
                    craft_recipe(S, getattr(S, "craft_selected_idx", 0))
                    continue
                elif is_cancel:
                    S.crafting_open = False
                    continue

            if is_confirm:
                if getattr(S, "show_keys", False):
                    S.show_keys = False
                elif S.show_settings:
                    items = get_settings_focusables(S)
                    cur = items[getattr(S, "settings_focus_idx", 0) % len(items)]
                    if cur is S.music_toggle:
                        cur.value = not cur.value
                        apply_volume(S)
                    elif cur is S.fps_toggle:
                        cur.value = not cur.value
                    elif cur is S.prev_btn:
                        play_prev_track(S)
                    elif cur is S.play_pause_btn:
                        toggle_play_pause(S)
                    elif cur is S.next_btn:
                        play_next_track(S)
                    elif cur is S.keybinds_btn:
                        S.show_keys = True
                    elif cur is S.settings_close_btn or cur is S.settings_x:
                        S.show_settings = False
                elif getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
                    items = get_pause_focusables(S)
                    cur = items[getattr(S, "pause_focus_idx", 0) % len(items)]
                    if cur is S.pause_resume_btn:
                        S.paused = False
                    elif cur is S.pause_help_btn:
                        S.show_keys = True
                    elif cur is S.pause_settings_btn:
                        S.show_settings = True
                        S.settings_focus_idx = 0
                    elif cur is S.pause_quit_btn:
                        S.paused = False
                        go_back(S)
                elif S.state == STATE_SETUP:
                    items = get_setup_focusables(S)
                    cur = items[getattr(S, "setup_focus_idx", 0) % len(items)]
                    if cur is S.setup_confirm_btn:
                        {"single": do_single, "join": do_join,
                         "host": do_host, "local": do_local}[S.setup_mode](S)
                    elif hasattr(cur, "active"):
                        for inp in S.name_inputs + [S.addr_input, S.code_input, S.lobby_name_input]:
                            inp.active = False
                        cur.active = True
                elif S.state == STATE_WAIT:
                    items = get_wait_focusables(S)
                    if items:
                        cur = items[getattr(S, "wait_focus_idx", 0) % len(items)]
                        if cur is S.lobby_ready_btn:
                            my_info = S.lobby_players.get(S.client_id, {})
                            if not my_info.get("restricted", False):
                                is_ready = my_info.get("ready", False)
                                if S.is_host:
                                    S.lobby_players[S.client_id]["ready"] = not is_ready
                                    S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                                else:
                                    S.conn.send({"type": "lobby_action", "id": S.client_id, "action": "ready", "value": not is_ready})
                        elif cur is getattr(S, "lobby_start_btn", None) and S.is_host:
                            can_start = len(S.lobby_players) > 0 and all(p.get("ready") or p.get("is_host") or p.get("restricted") for p in S.lobby_players.values())
                            if can_start:
                                S.conn.send({"type": "lobby_start"})
                                S.state = STATE_TEST
                        elif S.is_host:
                            for pid, btn in getattr(S, "lobby_kick_btns", {}).items():
                                if cur is btn and pid in S.lobby_players:
                                    del S.lobby_players[pid]
                                    S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                                    break
                            for pid, btn in getattr(S, "lobby_restrict_btns", {}).items():
                                if cur is btn and pid in S.lobby_players:
                                    S.lobby_players[pid]["restricted"] = not S.lobby_players[pid].get("restricted", False)
                                    if S.lobby_players[pid]["restricted"]:
                                        S.lobby_players[pid]["ready"] = False
                                    S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                                    break
                elif S.state == STATE_MENU:
                    res = activate_focused(S)
                    if res == "settings":
                        S.show_settings = True
                        S.settings_focus_idx = 0
                    elif res == "help":
                        S.show_keys = True
                    elif res == "quit":
                        running = False
            elif is_cancel:
                if getattr(S, "show_keys", False):
                    S.show_keys = False
                elif S.show_settings:
                    S.show_settings = False
                elif getattr(S, "crafting_open", False):
                    S.crafting_open = False
                elif getattr(S, "notepad_open", False):
                    S.notepad_open = False
                elif getattr(S, "paused", False):
                    S.paused = False
                elif S.state in (STATE_SETUP, STATE_WAIT):
                    go_back(S)
                elif S.state == STATE_MENU and getattr(S, "menu_page", "root") != "root":
                    if S.menu_page == "host":
                        S.menu_page = "online"
                    elif S.menu_page == "online":
                        S.menu_page = "play"
                    elif S.menu_page == "play":
                        S.menu_page = "root"
                    update_menu_layout(S)

        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            if not getattr(S, "_setting_mouse_pos", False) and not getattr(S, "_ctrl_clicking", False):
                S.using_controller = False

        if S.show_settings:
            if event.type == pygame.MOUSEBUTTONDOWN:
                grabbed = (S.volume_slider.handle_mousedown(event.pos) or S.cam_smooth_slider.handle_mousedown(event.pos))
                if grabbed:
                    apply_volume(S)
                elif S.settings_x.clicked(event.pos) or S.settings_close_btn.clicked(event.pos) \
                        or not SETTINGS_RECT.collidepoint(event.pos):
                    S.show_settings = False
                elif S.music_toggle.clicked(event.pos):
                    S.music_toggle.value = not S.music_toggle.value
                    apply_volume(S)
                elif S.fps_toggle.clicked(event.pos):
                    S.fps_toggle.value = not S.fps_toggle.value
                elif S.keybinds_btn.clicked(event.pos):
                    S.show_keys = True
                elif S.render_dist_stepper.handle_click(event.pos):
                    pass
                elif S.prev_btn.clicked(event.pos):
                    play_prev_track(S)
                elif S.play_pause_btn.clicked(event.pos):
                    toggle_play_pause(S)
                elif S.next_btn.clicked(event.pos):
                    play_next_track(S)
            elif event.type == pygame.MOUSEBUTTONUP:
                S.volume_slider.handle_mouseup()
                S.cam_smooth_slider.handle_mouseup()
            elif event.type == pygame.MOUSEMOTION:
                S.volume_slider.handle_mousemotion(event.pos)
                S.cam_smooth_slider.handle_mousemotion(event.pos)
                if S.volume_slider.dragging or S.cam_smooth_slider.dragging:
                    apply_volume(S)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                S.show_settings = False
            continue

        # --- in-world pause menu (Esc toggles; overlays take Esc first) ---
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                and S.state in (STATE_LOCAL, STATE_TEST)
                and not S.show_settings and not S.show_keys):
            if getattr(S, "notepad_open", False):
                S.notepad_open = False
                continue
            S.paused = not getattr(S, "paused", False)
            continue
        if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
            if event.type == pygame.MOUSEBUTTONDOWN:
                if S.pause_resume_btn.clicked(event.pos):
                    S.paused = False
                elif S.pause_help_btn.clicked(event.pos):
                    S.show_keys = True
                elif S.pause_settings_btn.clicked(event.pos):
                    S.show_settings = True
                elif S.pause_quit_btn.clicked(event.pos):
                    S.paused = False
                    go_back(S)
            continue  # freeze all other in-world input while paused

        # --- MAIN menu: keyboard nav (Up/Down + Enter) drives the cursor ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False):
                # 0. Backpack Inventory clicks
                if getattr(S, "inventory_open", False):
                    shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                    handle_inventory_click(S, event.pos, 1, shift_held)
                    continue

                # 0.5 Backpack BAG [E] open button or Inventory HUD card click
                if (hasattr(S, "inv_open_btn") and S.inv_open_btn and S.inv_open_btn.clicked(event.pos)) or \
                   (hasattr(S, "inv_hud_rect") and S.inv_hud_rect and S.inv_hud_rect.collidepoint(event.pos)):
                    toggle_inventory(S)
                    continue

                # 1. Crafting menu clicks
                if getattr(S, "crafting_open", False):
                    cw, ch = 520, 390
                    cx = (cfg.WIDTH - cw) // 2
                    cy = (cfg.HEIGHT - ch) // 2
                    card_rect = pygame.Rect(cx, cy, cw, ch)
                    if hasattr(S, "craft_x_btn") and S.craft_x_btn and S.craft_x_btn.clicked(event.pos):
                        S.crafting_open = False
                        continue
                    craft_clicked = False
                    for r_idx, btn in getattr(S, "craft_buttons", []):
                        if btn.clicked(event.pos):
                            craft_recipe(S, r_idx)
                            craft_clicked = True
                            break
                    if not craft_clicked and not card_rect.collidepoint(event.pos):
                        S.crafting_open = False
                    continue

                # 2. Crafting open button
                if hasattr(S, "craft_open_btn") and S.craft_open_btn and S.craft_open_btn.clicked(event.pos):
                    S.crafting_open = not getattr(S, "crafting_open", False)
                    continue

                # 3. 5-Cell Hotbar clicks
                hb_rects = get_hotbar_slot_rects()
                hotbar_clicked = False
                for i in range(5):
                    if hb_rects[i].collidepoint(event.pos):
                        select_hotbar_slot(S, i)
                        hotbar_clicked = True
                        break
                if hotbar_clicked:
                    continue

                notepad_rect = getattr(S, "notepad_rect", pygame.Rect(16, cfg.HEIGHT - 70, 56, 56))
                if notepad_rect.collidepoint(event.pos):
                    S.notepad_open = not getattr(S, "notepad_open", False)
                elif getattr(S, "notepad_open", False):
                    close_rect = getattr(S, "notepad_close_rect", None)
                    if close_rect and close_rect.collidepoint(event.pos):
                        S.notepad_open = False
                    else:
                        book_w, book_h = 560, 420
                        bx = (cfg.WIDTH - book_w) // 2
                        by = (cfg.HEIGHT - book_h) // 2
                        if not pygame.Rect(bx, by, book_w, book_h).collidepoint(event.pos):
                            S.notepad_open = False
            if S.state == STATE_WAIT:
                pos = event.pos
                if S.lobby_ready_btn and S.lobby_ready_btn.rect.collidepoint(pos):
                    # Toggle ready if not restricted
                    my_info = S.lobby_players.get(S.client_id, {})
                    if not my_info.get("restricted", False):
                        is_ready = my_info.get("ready", False)
                        if S.is_host:
                            S.lobby_players[S.client_id]["ready"] = not is_ready
                            S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                        else:
                            S.conn.send({"type": "lobby_action", "id": S.client_id, "action": "ready", "value": not is_ready})
                if S.is_host and S.lobby_start_btn and S.lobby_start_btn.rect.collidepoint(pos):
                    # Check if all ready
                    can_start = len(S.lobby_players) > 0 and all(p.get("ready") or p.get("is_host") or p.get("restricted") for p in S.lobby_players.values())
                    if can_start:
                        S.conn.send({"type": "lobby_start"})
                        S.state = STATE_TEST
                if S.is_host:
                    for pid, btn in S.lobby_kick_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                del S.lobby_players[pid]
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                    for pid, btn in S.lobby_restrict_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                S.lobby_players[pid]["restricted"] = not S.lobby_players[pid].get("restricted", False)
                                if S.lobby_players[pid]["restricted"]:
                                    S.lobby_players[pid]["ready"] = False
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
        if event.type == pygame.KEYDOWN and S.state == STATE_MENU:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                S.focus_index = (S.focus_index + 1) % len(S.MENU_FOCUS)
            elif event.key in (pygame.K_UP, pygame.K_w):
                S.focus_index = (S.focus_index - 1) % len(S.MENU_FOCUS)
            elif event.key == pygame.K_RETURN:
                res = activate_focused(S)
                if res == "settings":
                    S.show_settings = True
                elif res == "help":
                    S.show_keys = True
                elif res == "quit":
                    running = False
            elif event.key == pygame.K_ESCAPE and getattr(S, "menu_page", "root") != "root":
                if S.menu_page == "online":
                    S.menu_page = "play"
                elif S.menu_page == "play":
                    S.menu_page = "root"
                update_menu_layout(S)

        # --- MAIN menu: one flat screen ---
        if event.type == pygame.MOUSEBUTTONDOWN and S.state == STATE_MENU:
            for i, btn in enumerate(S.MENU_FOCUS):
                if btn.clicked(event.pos):
                    S.focus_index = i
                    res = activate_focused(S)
                    if res == "settings":
                        S.show_settings = True
                    elif res == "help":
                        S.show_keys = True
                    elif res == "quit":
                        running = False
                    break

        # --- SETUP panel: per-mode fields, then confirm ---
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN) and S.state == STATE_SETUP:
            mode = S.setup_mode
            online = mode in ("join", "host")
            shown = range(setup_name_count(S)) if mode == "local" else range(1)
            if event.type == pygame.MOUSEBUTTONDOWN:
                items = get_setup_focusables(S)
                for idx, itm in enumerate(items):
                    if hasattr(itm, "rect") and itm.rect.collidepoint(event.pos):
                        S.setup_focus_idx = idx
                        break
                if online:
                    S.addr_input.handle_click(event.pos)
                if mode == "join":
                    S.code_input.handle_click(event.pos)
                elif mode in ("host", "local"):
                    S.lobby_name_input.handle_click(event.pos)
                    S.max_players_stepper.handle_click(event.pos)
                for i in shown:
                    S.name_inputs[i].handle_click(event.pos)
                if S.setup_confirm_btn.clicked(event.pos):
                    {"single": do_single, "join": do_join,
                     "host": do_host, "local": do_local}[mode](S)
            else:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    items = get_setup_focusables(S)
                    cur = items[getattr(S, "setup_focus_idx", 0) % len(items)]
                    if cur is S.setup_confirm_btn:
                        {"single": do_single, "join": do_join,
                         "host": do_host, "local": do_local}[mode](S)
                    else:
                        S.setup_focus_idx = (getattr(S, "setup_focus_idx", 0) + 1) % len(items)
                        for inp in S.name_inputs + [S.addr_input, S.code_input, S.lobby_name_input]:
                            inp.active = False
                        if hasattr(items[S.setup_focus_idx], "active"):
                            items[S.setup_focus_idx].active = True
                elif event.key == pygame.K_TAB:
                    items = get_setup_focusables(S)
                    delta = -1 if (pygame.key.get_mods() & pygame.KMOD_SHIFT) else 1
                    S.setup_focus_idx = (getattr(S, "setup_focus_idx", 0) + delta) % len(items)
                    for inp in S.name_inputs + [S.addr_input, S.code_input, S.lobby_name_input]:
                        inp.active = False
                    if hasattr(items[S.setup_focus_idx], "active"):
                        items[S.setup_focus_idx].active = True
                    snap_cursor_to_widget(S, items[S.setup_focus_idx])
                elif event.key == pygame.K_ESCAPE:
                    go_back(S)

                if online:
                    S.addr_input.handle_key(event)
                if mode == "join":
                    S.code_input.handle_key(event)
                elif mode in ("host", "local"):
                    S.lobby_name_input.handle_key(event)
                for i in shown:
                    S.name_inputs[i].handle_key(event)

        # --- chat (Minecraft-style): T / Enter opens, keys are swallowed while open ---
        chat_ok = S.state == STATE_TEST or (S.state == STATE_LOCAL and len(S.local_players) == 1)
        if S.chat_open and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                send_chat(S, S.chat_input); S.chat_input = ""; S.chat_open = False
            elif event.key == pygame.K_ESCAPE:
                S.chat_open = False; S.chat_input = ""
            elif event.key == pygame.K_BACKSPACE:
                S.chat_input = S.chat_input[:-1]
            elif event.unicode and event.unicode.isprintable() and len(S.chat_input) < 180:
                S.chat_input += event.unicode
            continue
        if (event.type == pygame.KEYDOWN and chat_ok and not S.chat_open
                and event.key in (pygame.K_RETURN, pygame.K_t)):
            S.chat_open = True; S.chat_input = ""
            continue

        # --- push-to-talk voice (hold V, online) ---
        if S.state == STATE_TEST and not S.chat_open:
            if event.type == pygame.KEYDOWN and event.key == VOICE_KEY:
                S.voice.start_talk()
            elif event.type == pygame.KEYUP and event.key == VOICE_KEY:
                S.voice.stop_talk()

        # --- in-world controls: jump, switch tilemap (Tab), regen (R), zoom, inventory, crafting ---
        if event.type == pygame.KEYDOWN and S.state in (STATE_LOCAL, STATE_TEST) and not S.chat_open:
            if getattr(S, "crafting_open", False):
                if event.key in (pygame.K_ESCAPE, pygame.K_c):
                    S.crafting_open = False
                    continue
                elif event.key in (pygame.K_UP, pygame.K_w):
                    S.craft_selected_idx = max(0, getattr(S, "craft_selected_idx", 0) - 1)
                    if S.craft_selected_idx < getattr(S, "craft_scroll", 0):
                        S.craft_scroll = S.craft_selected_idx
                    continue
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    S.craft_selected_idx = min(len(CRAFTING_RECIPES) - 1, getattr(S, "craft_selected_idx", 0) + 1)
                    if S.craft_selected_idx >= getattr(S, "craft_scroll", 0) + 5:
                        S.craft_scroll = S.craft_selected_idx - 4
                    continue
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    craft_recipe(S, getattr(S, "craft_selected_idx", 0))
                    continue

            if getattr(S, "inventory_open", False):
                if event.key in (pygame.K_ESCAPE, pygame.K_e):
                    toggle_inventory(S)
                    continue
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    handle_inventory_numkey(S, event.key - pygame.K_1)
                    continue
                elif event.key in (pygame.K_KP1, pygame.K_KP2, pygame.K_KP3, pygame.K_KP4, pygame.K_KP5):
                    handle_inventory_numkey(S, event.key - pygame.K_KP1)
                    continue
                elif event.key in (pygame.K_f, pygame.K_SPACE):
                    if getattr(S, "hovered_inv_slot", None):
                        loc_type, s_idx, s_type, s_cnt = S.hovered_inv_slot
                        target_list = S.main_inventory if loc_type == "bp" else S.hotbar
                        if 0 <= s_idx < len(target_list):
                            use_inventory_item(S, target_list[s_idx])
                    continue
                elif event.key == pygame.K_q:
                    shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                    if getattr(S, "cursor_item", None):
                        if shift_held:
                            drop_held_item_to_world(S)
                        else:
                            c_type = S.cursor_item.get("type")
                            if c_type:
                                target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
                                if not hasattr(S, "dropped_items"):
                                    S.dropped_items = []
                                ang = random.uniform(0, 6.28)
                                spd = random.uniform(0.6, 1.6)
                                S.dropped_items.append({
                                    "cx": target_p[0] + math.cos(ang) * 0.45,
                                    "cy": target_p[1] + math.sin(ang) * 0.45,
                                    "z": 15.0,
                                    "vx": math.cos(ang) * spd,
                                    "vy": math.sin(ang) * spd,
                                    "vz": random.uniform(80, 160),
                                    "type": c_type
                                })
                                play_sfx(S, "break", 0.5)
                                S.cursor_item["count"] -= 1
                                if S.cursor_item["count"] <= 0:
                                    S.cursor_item = None
                                sync_inventory_totals(S)
                    elif getattr(S, "hovered_inv_slot", None):
                        loc_type, s_idx, s_type, s_cnt = S.hovered_inv_slot
                        drop_slot_item_to_world(S, loc_type, s_idx, drop_all=shift_held)
                    continue

            if event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                select_hotbar_slot(S, event.key - pygame.K_1)
            elif event.key in (pygame.K_KP1, pygame.K_KP2, pygame.K_KP3, pygame.K_KP4, pygame.K_KP5):
                select_hotbar_slot(S, event.key - pygame.K_KP1)
            elif event.key == pygame.K_c:
                S.crafting_open = not getattr(S, "crafting_open", False)
            elif event.key == pygame.K_e:
                if not getattr(S, "crafting_open", False) and not getattr(S, "paused", False):
                    toggle_inventory(S)
            elif event.key == pygame.K_f:
                if not getattr(S, "crafting_open", False) and not getattr(S, "paused", False) and not getattr(S, "inventory_open", False):
                    interact_or_open_chest(S)
            elif event.key == pygame.K_TAB:
                S.iso.cycle_theme()
            elif event.key == pygame.K_r:
                S.iso.reseed(random.randint(1, 2_000_000_000))
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                zoom(S, +1)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                zoom(S, -1)
            elif S.state == STATE_TEST and event.key in (pygame.K_SPACE, pygame.K_RSHIFT):
                try_jump(S.me)
            elif S.state == STATE_LOCAL:
                for i in range(len(S.local_players)):
                    if event.key == SCHEMES[i][6]:
                        try_jump(S.local_players[i])

        if event.type == pygame.MOUSEWHEEL and S.state in (STATE_LOCAL, STATE_TEST) \
                and not S.show_settings:
            if getattr(S, "crafting_open", False):
                S.craft_scroll = max(0, min(max(0, len(CRAFTING_RECIPES) - 5), getattr(S, "craft_scroll", 0) - event.y))
            elif pygame.key.get_mods() & pygame.KMOD_SHIFT:
                # Shift + scroll cycles arsenal (weapons and tools)
                my_weapon = getattr(S, "my_weapon", "AK47")
                if my_weapon in GLOBAL_HOTBAR:
                    idx = GLOBAL_HOTBAR.index(my_weapon)
                    idx = (idx - 1) if event.y > 0 else (idx + 1)
                    S.my_weapon = GLOBAL_HOTBAR[idx % len(GLOBAL_HOTBAR)]
            else:
                # Normal scroll is dedicated to camera zoom in / out
                zoom(S, 1 if event.y > 0 else -1)

        # --- right click to use item or mine/chop ---
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 3
                and S.state in (STATE_LOCAL, STATE_TEST)
                and not S.show_settings and not S.show_keys
                and not getattr(S, "paused", False)
                and not getattr(S, "crafting_open", False)
                and not S.help_icon_btn.rect.collidepoint(event.pos)
                and not S.close_btn.rect.collidepoint(event.pos)):
            if getattr(S, "inventory_open", False):
                shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                handle_inventory_click(S, event.pos, 3, shift_held)
                continue

            # Check if right clicking hotbar slot to use
            hb_rects = get_hotbar_slot_rects()
            clicked_hotbar = False
            for i in range(5):
                if hb_rects[i].collidepoint(event.pos):
                    use_hotbar_item(S, i)
                    clicked_hotbar = True
                    break
            if not clicked_hotbar:
                # If active slot has food or consumable, right click uses it
                sel_slot = getattr(S, "hotbar", [{}])[getattr(S, "selected_slot", 0)] if hasattr(S, "hotbar") else {}
                if sel_slot.get("type") in ("apple", "bread", "meat", "brick", "wood"):
                    use_hotbar_item(S, getattr(S, "selected_slot", 0))
                else:
                    S.pressed_tile = tile_at_screen(S, *event.pos)
                    S.pressed_until = now + 5.0
                    S.pressing = True
                    target_p = S.me if S.state == STATE_TEST else S.local_players[0]
                    execute_mining_or_chopping(S, now, target_p, *event.pos)

        if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                and S.state in (STATE_SETUP, STATE_WAIT)):
            go_back(S)
        if event.type == pygame.JOYBUTTONDOWN and event.button == JOYSTICK_B \
                and S.state in (STATE_SETUP, STATE_WAIT):
            go_back(S)

    if S.state == STATE_WAKE:
        if S.server_woken:
            go_setup(S, "host")
        elif getattr(S, "server_wake_failed", False):
            reset_to_menu(S, "Could not reach server.")

    # --- keep the playlist cycling ---
    # the MUSIC_END_EVENT above handles it on most builds, but some SDL setups
    # never post it, so also advance when the track has simply stopped playing.
    # (get_busy() is False while paused too, hence the music_paused guard)
    if cfg.MUSIC_TRACKS and not S.music_paused and not pygame.mixer.music.get_busy():
        play_next_track(S)

    # --- incoming network messages ---
    try:
        while True:
            msg = S.conn.incoming.get_nowait()
            t = msg.get("type")
            if t == "hosted":
                if getattr(S, "is_host", False) and S.room_code == msg["code"]:
                    # Reconnected
                    if S.state == STATE_WAIT:
                        S.conn.send({"type": "lobby_state", "players": getattr(S, "lobby_players", {})})
                    else:
                        S.conn.send({"type": "lobby_start"})
                else:
                    S.is_host = True
                    S.room_code = msg["code"]
                    S.lobby_name = msg.get("lobby_name", "")
                    S.max_players = msg.get("max_players", 2)
                    S.player_count = msg.get("player_count", 1)
                    S.status_msg = "Room created — waiting for your friend..."
                    S.last_pong_time = now
                    S.lobby_ready_btn = None
                    S.lobby_players = {
                        S.client_id: {
                            "name": S.username,
                            "profile": "Pilot",
                            "skin": "Default",
                            "color": tuple(color_for(S.username)),
                            "ready": True,
                            "restricted": False,
                            "is_host": True,
                            "disconnected": False,
                            "last_seen": now
                        }
                    }
                    S.state = STATE_WAIT
            elif t == "joined":
                if S.room_code == msg.get("code") and not getattr(S, "is_host", True):
                    # Reconnected
                    pass
                else:
                    S.is_host = False
                    S.room_code = msg["code"]
                    S.lobby_name = msg.get("lobby_name", "")
                    S.max_players = msg.get("max_players", 2)
                    S.player_count = msg.get("player_count", 2)
                    S.last_pong_time = now
                    S.status_msg = "Joined — waiting for host..."
                    try:
                        S.conn.send({
                            "type": "lobby_hello", 
                            "id": S.client_id,
                            "name": S.username,
                            "profile": "Pilot",
                            "skin": "Default",
                            "color": list(color_for(S.username))
                        })
                    except Exception:
                        pass
            elif t == "peer_joined":
                S.player_count = msg.get("player_count", S.player_count + 1)
                S.status_msg = "Peer connected!"
                S.last_pong_time = now
            elif t == "peer_left":
                S.player_count = msg.get("player_count", max(1, S.player_count - 1))
                S.status_msg = f"A player disconnected ({S.player_count}/{S.max_players} remaining)."
            elif t == "pos":
                pid = msg.get("id", msg.get("name", "peer"))
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                
                # --- ANTI-CHEAT (HOST AUTHORITATIVE PHYSICS) ---
                if getattr(S, "is_host", False) and pid != S.client_id:
                    old_pr = getattr(S, "peers", {}).get(pid)
                    if old_pr:
                        dt = now - old_pr["seen"]
                        if dt > 0:
                            dx = msg["x"] - old_pr["p"][0]
                            dy = msg["y"] - old_pr["p"][1]
                            dist = (dx**2 + dy**2)**0.5
                            speed = dist / dt
                            # Allow up to 600 pixels/sec (SPEED is ~180, plus lag tolerance)
                            # Check if restricted
                            is_restricted = getattr(S, "lobby_players", {}).get(pid, {}).get("restricted", False)
                            if speed > 600 or is_restricted:
                                # Rubberband them back to old position!
                                S.conn.send({"type": "force_pos", "target": pid, "x": old_pr["p"][0], "y": old_pr["p"][1], "z": old_pr["p"][2]})
                                continue  # Ignore this illegal update

                S.peers[pid] = {"p": [msg["x"], msg["y"], msg.get("z", 0.0)],
                                "name": nm, "color": col, "seen": now,
                                "wep": msg.get("wep", "AK47"),
                                "aim": msg.get("aim", 0.0)}
            elif t == "lobby_hello" and S.is_host:
                pid = msg["id"]
                existing = getattr(S, "lobby_players", {}).get(pid, {})
                S.lobby_players[pid] = {
                    "name": msg["name"],
                    "profile": msg.get("profile", "Pilot"),
                    "skin": msg.get("skin", "Default"),
                    "color": tuple(msg.get("color", [255,255,255])),
                    "ready": existing.get("ready", False),
                    "restricted": existing.get("restricted", False),
                    "is_host": False,
                    "disconnected": False,
                    "last_seen": now
                }
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_action":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in S.lobby_players and not S.lobby_players[pid]["restricted"]:
                        if msg.get("action") == "ready":
                            S.lobby_players[pid]["ready"] = bool(msg.get("value"))
                        S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_state":
                S.lobby_players = msg.get("players", {})
                if S.client_id not in S.lobby_players:
                    reset_to_menu(S, "You were kicked by the host.")
            elif t == "lobby_start":
                S.state = STATE_TEST
            elif t == "promote_to_host":
                S.is_host = True
                my_info = getattr(S, "lobby_players", {}).get(S.client_id)
                if my_info:
                    my_info["is_host"] = True
                S.conn.send({"type": "lobby_state", "players": getattr(S, "lobby_players", {})})
            elif t == "force_pos":
                if msg.get("target") == S.client_id:
                    S.me[0] = msg["x"]
                    S.me[1] = msg["y"]
                    S.me[2] = msg.get("z", 0.0)
            elif t == "lobby_ping":
                S.conn.send({"type": "lobby_pong", "id": S.client_id})
            elif t == "lobby_pong":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in getattr(S, "lobby_players", {}):
                        S.lobby_players[pid]["last_seen"] = now
            elif t == "chat":
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                S.chat_log.append({"t": now, "name": nm, "color": col,
                                   "text": str(msg.get("text", ""))[:180]})
            elif t == "voice":
                S.voice.push_incoming(msg.get("d", ""))
            elif t == "ping":
                S.conn.send({"type": "pong", "t": msg["t"]})
                S.pong_count += 1

            elif t == "pong":
                S.last_rtt = (now - msg["t"]) * 1000
                S.last_pong_time = now

            elif t == "error":
                reset_to_menu(S, f"Error: {msg['msg']}")
            elif t == "network_state":
                ns = msg["state"]
                if ns == "reconnecting":
                    S.status_msg = "Reconnecting..."
                elif ns == "disconnected":
                    reset_to_menu(S, "Disconnected from server.")
            elif t == "connect_error":
                reset_to_menu(S, msg["error"])
            elif t == "disconnected":
                if S.state != STATE_MENU:
                    err = msg.get("error", "closed")
                    reset_to_menu(S, f"Disconnected from server ({err}).")
    except queue.Empty:
        pass

    if S.state == STATE_WAIT and S.is_host:
        if now - getattr(S, "last_lobby_ping", 0) > 2.0:
            S.conn.send({"type": "lobby_ping"})
            S.last_lobby_ping = now
            changed = False
            for pid, p in S.lobby_players.items():
                if not p.get("is_host") and now - p.get("last_seen", now) > 6.0:
                    if not p.get("disconnected"):
                        p["disconnected"] = True
                        p["ready"] = False
                        changed = True
            if changed:
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})

    # Gamepad Controller Polling (PlayStation, Nintendo, Xbox)
    if not hasattr(S, "controller_mgr"):
        S.controller_mgr = controller.ControllerManager(S.ASSETS_DIR)

    ctrl_0 = S.controller_mgr.read_inputs(player_idx=0)
    pad_dx, pad_dy = ctrl_0["dx"], ctrl_0["dy"]
    pad_rx, pad_ry = ctrl_0["rx"], ctrl_0["ry"]
    pad_fire = ctrl_0["fire"]
    pad_jump = ctrl_0["jump"]
    pad_roll = ctrl_0["roll"]
    pad_dash = ctrl_0["dash"]
    pad_cycle_next = ctrl_0["cycle_next"]
    pad_cycle_prev = ctrl_0["cycle_prev"]

    # Start / Options / Plus pause toggle during gameplay
    if ctrl_0["pause"]:
        if now - getattr(S, "_last_pad_pause_t", 0.0) > 0.35:
            S._last_pad_pause_t = now
            if S.state in (STATE_LOCAL, STATE_TEST):
                S.paused = not getattr(S, "paused", False)

    # Select / Share / Minus / Touchpad notepad toggle
    if ctrl_0["notepad"]:
        if now - getattr(S, "_last_pad_notepad_t", 0.0) > 0.35:
            S._last_pad_notepad_t = now
            if S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False):
                S.notepad_open = not getattr(S, "notepad_open", False)

    # Gamepad hotbar cycling (LB / RB)
    if (pad_cycle_next or pad_cycle_prev) and not getattr(S, "last_pad_cycle", False):
        S.last_pad_cycle = True
        if pad_cycle_next:
            S.selected_slot = (getattr(S, "selected_slot", 0) + 1) % 5
        else:
            S.selected_slot = (getattr(S, "selected_slot", 0) - 1) % 5
    elif not pad_cycle_next and not pad_cycle_prev:
        S.last_pad_cycle = False

    # Gamepad Use Item (X Button / Square) and Crafting (Y Button / Triangle)
    if ctrl_0.get("use_item") and not getattr(S, "last_pad_use_item", False):
        S.last_pad_use_item = True
        if S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False) and not getattr(S, "crafting_open", False):
            interact_or_open_chest(S)
    elif not ctrl_0.get("use_item"):
        S.last_pad_use_item = False

    if ctrl_0.get("craft") and not getattr(S, "last_pad_craft", False):
        S.last_pad_craft = True
        if S.state in (STATE_LOCAL, STATE_TEST) and not getattr(S, "paused", False):
            S.crafting_open = not getattr(S, "crafting_open", False)
    elif not ctrl_0.get("craft"):
        S.last_pad_craft = False

    if S.state == STATE_TEST:
        prune_peers(S, now)
        keys = pygame.key.get_pressed()
        my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
        if not S.chat_open and not getattr(S, "paused", False) and not my_info.get("restricted"):
            up = keys[pygame.K_w] or keys[pygame.K_UP]
            down = keys[pygame.K_s] or keys[pygame.K_DOWN]
            left = keys[pygame.K_a] or keys[pygame.K_LEFT]
            right = keys[pygame.K_d] or keys[pygame.K_RIGHT]
            dash = keys[pygame.K_q] or pad_dash
            roll = pygame.mouse.get_pressed()[2] or pad_roll
            iso_move(S, S.me, up, down, left, right, dash, roll, dt, pad_dx, pad_dy)
            if pad_jump:
                try_jump(S.me)
        apply_jump(S.me, dt)
        follow_camera(S, S.me[0], S.me[1], dt)

        # relay any captured voice chunks to the room
        for chunk in S.voice.poll_outgoing():
            try:
                S.conn.send({"type": "voice", "d": chunk})
            except Exception:
                pass
        my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
        if not my_info.get("restricted") and now - S.last_pos_sent > 1.0 / POS_SEND_HZ:
            try:
                S.conn.send({"type": "pos", "id": S.client_id, "name": S.username,
                             "color": list(color_for(S.username)),
                             "x": round(S.me[0], 2), "y": round(S.me[1], 2),
                             "z": round(S.me[2], 1),
                             "wep": getattr(S, "my_weapon", "AK47"),
                             "aim": round(getattr(S, "aim_angle", 0.0), 3)})
                S.last_pos_sent = now
            except Exception:
                reset_to_menu(S, "Send failed — connection lost.")
        if now - S.last_ping_time > cfg.PING_INTERVAL:
            try:
                S.conn.send({"type": "ping", "t": now})
                S.ping_count += 1
                S.last_ping_time = now
            except Exception:
                reset_to_menu(S, "Ping failed.")
        if S.last_pong_time and now - S.last_pong_time > cfg.CONNECTION_TIMEOUT:
            reset_to_menu(S, f"Connection timed out (no response for {cfg.CONNECTION_TIMEOUT:.0f}s).")

    if S.state == STATE_LOCAL:
        keys = pygame.key.get_pressed()
        for i in range(len(S.local_players)):
            p = S.local_players[i]
            scheme, up, down, left, right, color, jump, dash_key = SCHEMES[i]
            p_ctrl = S.controller_mgr.read_inputs(player_idx=i) if hasattr(S, "controller_mgr") else {
                "dx": pad_dx if i == 0 else 0.0,
                "dy": pad_dy if i == 0 else 0.0,
                "jump": pad_jump if i == 0 else False,
                "dash": pad_dash if i == 0 else False,
                "roll": pad_roll if i == 0 else False
            }
            if getattr(S, "paused", False) or S.chat_open or (i == 0 and getattr(S, "player_is_dead", False)):
                iso_move(S, p, False, False, False, False, False, False, dt)
            else:
                dash = keys[dash_key] or p_ctrl["dash"]
                roll = p_ctrl["roll"] or (i == 0 and (pygame.mouse.get_pressed()[2] or pad_roll))
                iso_move(S, p, keys[up], keys[down], keys[left], keys[right], dash, roll, dt, p_ctrl["dx"], p_ctrl["dy"])
                if p_ctrl["jump"]:
                    try_jump(p)
            apply_jump(p, dt)
        follow_camera(S, *centroid(S.local_players), dt)
        if S.local_players:
            S.me = S.local_players[0]

    if S.state in (STATE_TEST, STATE_LOCAL):
        # Twin-stick 360-degree aiming or mouse aiming
        target_p = S.me if S.state == STATE_TEST else S.local_players[0]
        pw_x, pw_y = S.iso.world_px(target_p[0], target_p[1])
        mx, my = pygame.mouse.get_pos()
        sx, sy = S.iso.to_screen(pw_x, pw_y)
        sy -= S.iso.elev(target_p[0], target_p[1]) + 12 + target_p[2]

        if math.hypot(pad_rx, pad_ry) > 0.18:
            S.aim_angle = math.atan2(pad_ry, pad_rx)
        elif math.hypot(pad_dx, pad_dy) > 0.22 and not pygame.mouse.get_rel() != (0, 0):
            S.aim_angle = math.atan2(pad_dy, pad_dx)
        else:
            S.aim_angle = math.atan2(my - sy, mx - sx)
        
        # Fire logic (Left click or Controller RT to trigger weapons / tools)
        fire_triggered = (pygame.mouse.get_pressed()[0] or pad_fire)
        if fire_triggered:
            m_pos = pygame.mouse.get_pos()
            hb_w = 294
            hb_h = 64
            hb_x = (cfg.WIDTH - hb_w) // 2
            hb_y = cfg.HEIGHT - hb_h - 8
            hb_area = pygame.Rect(hb_x - 110, hb_y - 12, hb_w + 220, hb_h + 20)
            if pygame.mouse.get_pressed()[0] and hb_area.collidepoint(m_pos):
                fire_triggered = False

        if fire_triggered and not getattr(S, "chat_open", False) and not getattr(S, "show_settings", False) and not getattr(S, "notepad_open", False) and not getattr(S, "crafting_open", False) and not getattr(S, "inventory_open", False) and not getattr(S, "player_is_dead", False):
            my_weapon = getattr(S, "my_weapon", None)
            wep = WEAPONS.get(my_weapon) if my_weapon else None
            last_fire = getattr(S, "last_fire_time", 0.0)
            fire_rate = getattr(wep, "fire_rate", 0.25) if wep else 0.25
            can_fire = (now - last_fire) >= fire_rate
            if wep and can_fire:
                S.pressing = True
                S.last_fire_time = now
                aim = S.aim_angle
                is_tool = my_weapon in ["Sword", "Axe", "Pickaxe", "Shovel", "Fishing_rod", "Hammer", "Scythe", "Mallet"]
                if is_tool:
                    mx, my = pygame.mouse.get_pos()
                    emit_noise(S, target_p[0], target_p[1], 3.0)  # Perception 2.0: 3-tile melee noise
                    S.tool_spin_active = True
                    S.tool_spin_start = now
                    S.tool_spin_dur = 0.20
                    S.tool_spin_base_ang = aim
                    S.tool_spin_hits = set()
                    play_sfx(S, "slash", 0.65)
                    execute_mining_or_chopping(S, now, target_p, mx, my)
                elif hasattr(wep, "bullet_speed") and wep.bullet_speed > 0:
                    emit_noise(S, target_p[0], target_p[1], 12.0)  # Perception 2.0: 12-tile gunfire noise
                    hw = S.iso.HALF_W
                    hh = S.iso.HALF_H
                    
                    pr = max(6, int(12 * S.iso.scale / 2))
                    gun_z = S.iso.elev(target_p[0], target_p[1]) + target_p[2] + pr
                    
                    barrel_px = 16 * S.iso.scale * 1.07
                    sox = math.cos(aim) * barrel_px
                    soy = math.sin(aim) * barrel_px
                    owx = ((sox / hw) + (soy / hh)) / 2.0
                    owy = ((soy / hh) - (sox / hw)) / 2.0
                    
                    bx = target_p[0] + owx
                    by = target_p[1] + owy
                    
                    S.shake = getattr(wep, "recoil", 0) * 0.2
                    
                    kb_px = getattr(wep, "recoil", 0) * 2.0
                    kox = math.cos(aim) * kb_px
                    koy = math.sin(aim) * kb_px
                    target_p[0] -= ((kox / hw) + (koy / hh)) / 2.0
                    target_p[1] -= ((koy / hh) - (kox / hw)) / 2.0
                    
                    if not hasattr(S, "bullets"): S.bullets = []
                    
                    def fire_proj(spd, spr):
                        svx = math.cos(aim + spr) * spd
                        svy = math.sin(aim + spr) * spd
                        vwx = ((svx / hw) + (svy / hh)) / 2.0
                        vwy = ((svy / hh) - (svx / hw)) / 2.0
                        return vwx, vwy, aim + spr
                    
                    fire_mode = getattr(wep, "fire_mode", "SOLO")
                    if fire_mode == "SPREAD" or my_weapon == "SawedOffShotgun":
                        pellet_dmg = max(5, getattr(wep, "damage", 90) // 5)
                        for spread in [-0.2, -0.1, 0, 0.1, 0.2]:
                            spd = wep.bullet_speed * random.uniform(0.7, 1.1)
                            vwx, vwy, sa = fire_proj(spd, spread)
                            S.bullets.append({"wx": bx, "wy": by, "z": gun_z, "vx": vwx, "vy": vwy, "sa": sa, "life": 0.8, "img": wep.bullet_image, "damage": pellet_dmg, "poise_dmg": 12, "wep_name": my_weapon})
                    elif fire_mode == "BURST":
                        vwx, vwy, sa = fire_proj(wep.bullet_speed, 0)
                        S.bullets.append({"wx": bx, "wy": by, "z": gun_z, "vx": vwx, "vy": vwy, "sa": sa, "life": 2.0, "img": wep.bullet_image, "damage": getattr(wep, "damage", 26), "poise_dmg": 8, "wep_name": my_weapon})
                        if not hasattr(S, "burst_queue"):
                            S.burst_queue = []
                        b_count = getattr(wep, "burst_count", 3)
                        b_interval = getattr(wep, "burst_interval", 0.065)
                        for b_idx in range(1, b_count):
                            S.burst_queue.append({
                                "fire_at": now + (b_idx * b_interval),
                                "wep": wep,
                                "aim": aim,
                                "damage": getattr(wep, "damage", 26)
                            })
                    else:
                        vwx, vwy, sa = fire_proj(wep.bullet_speed, 0)
                        p_dmg = 45 if my_weapon == "M24" else (2 if my_weapon == "MP5" else (3 if my_weapon in ("Gun", "M92", "Luger") else (6 if my_weapon == "Revolver" else 8)))
                        S.bullets.append({"wx": bx, "wy": by, "z": gun_z, "vx": vwx, "vy": vwy, "sa": sa, "life": 2.0, "img": wep.bullet_image, "damage": getattr(wep, "damage", 25), "poise_dmg": p_dmg, "wep_name": my_weapon})
            elif not wep and can_fire and pygame.mouse.get_pressed()[0]:
                sel_idx = getattr(S, "selected_slot", 0)
                sel_slot = S.hotbar[sel_idx] if (hasattr(S, "hotbar") and 0 <= sel_idx < len(S.hotbar)) else None
                if sel_slot and sel_slot.get("type") in ("apple", "bread", "meat", "fish", "mushroom"):
                    use_hotbar_item(S, sel_idx)
                    S.last_fire_time = now

        # Celestial spin lifecycle update
        if getattr(S, "tool_spin_active", False):
            spin_elapsed = now - getattr(S, "tool_spin_start", 0.0)
            spin_dur = getattr(S, "tool_spin_dur", 0.20)
            if spin_elapsed >= spin_dur:
                my_wep_name = getattr(S, "my_weapon", "AK47")
                is_t = my_wep_name in ["Sword", "Axe", "Pickaxe", "Shovel", "Fishing_rod", "Hammer", "Scythe", "Mallet"]
                if pygame.mouse.get_pressed()[0] and is_t:
                    # Seamlessly chain into the next swift 360-degree spin!
                    S.tool_spin_start = now
                    S.tool_spin_base_ang = S.aim_angle
                    S.tool_spin_hits = set()
                    play_sfx(S, "slash", 0.55)
                    # Screen shake removed for tools and sword
                    execute_mining_or_chopping(S, now, target_p)
                else:
                    S.tool_spin_active = False

        if getattr(S, "pressing", False):
            last_fire = getattr(S, "last_fire_time", 0.0)
            if not pygame.mouse.get_pressed()[0] or (now - last_fire > 0.25):
                if not getattr(S, "tool_spin_active", False):
                    S.pressing = False

        # Process scheduled burst fire bullets
        if hasattr(S, "burst_queue") and S.burst_queue:
            remaining_burst = []
            hw = S.iso.HALF_W
            hh = S.iso.HALF_H
            for bq in S.burst_queue:
                if now >= bq["fire_at"]:
                    b_wep = bq["wep"]
                    b_aim = getattr(S, "aim_angle", bq["aim"])
                    pr = max(6, int(12 * S.iso.scale / 2))
                    gun_z = S.iso.elev(target_p[0], target_p[1]) + target_p[2] + pr
                    barrel_px = 16 * S.iso.scale * 1.07
                    sox = math.cos(b_aim) * barrel_px
                    soy = math.sin(b_aim) * barrel_px
                    owx = ((sox / hw) + (soy / hh)) / 2.0
                    owy = ((soy / hh) - (sox / hw)) / 2.0
                    bx = target_p[0] + owx
                    by = target_p[1] + owy
                    svx = math.cos(b_aim) * b_wep.bullet_speed
                    svy = math.sin(b_aim) * b_wep.bullet_speed
                    vwx = ((svx / hw) + (svy / hh)) / 2.0
                    vwy = ((svy / hh) - (svx / hw)) / 2.0
                    if not hasattr(S, "bullets"): S.bullets = []
                    S.bullets.append({
                        "wx": bx, "wy": by, "z": gun_z, "vx": vwx, "vy": vwy,
                        "sa": b_aim, "life": 2.0, "img": b_wep.bullet_image, "damage": bq["damage"]
                    })
                    S.shake = max(getattr(S, "shake", 0.0), getattr(b_wep, "recoil", 1.0) * 0.15)
                else:
                    remaining_burst.append(bq)
            S.burst_queue = remaining_burst
            
        # Update bullets
        if hasattr(S, "bullets"):
            alive = []
            if not hasattr(S, "particles"): S.particles = []
            if not hasattr(S, "dropped_items"): S.dropped_items = []
            if not hasattr(S, "prop_health"): S.prop_health = {}
            for b in S.bullets:
                b["wx"] += (b["vx"] / 2.0) * dt
                b["wy"] += (b["vy"] / 2.0) * dt
                b["life"] -= dt
                if b["life"] <= 0:
                    continue

                cx = int(round(b["wx"]))
                cy = int(round(b["wy"]))
                cell = S.iso.world.get(cx, cy)

                is_tree = cell[1] in range(48, 61) if cell[1] is not None else False
                is_rock_prop = (cell[1] in [62, 64, 65, 67, 68] or cell[1] in range(72, 82)) if cell[1] is not None else False
                is_rock_ground = cell[0] in [100, 101]
                is_rock = is_rock_prop or is_rock_ground
                is_destructible = cell[1] in getattr(iso, "DESTRUCTIBLE_PROPS", []) if cell[1] is not None else False
                is_solid = S.iso.solid(cx, cy) or is_rock or is_tree or is_destructible

                if is_solid:
                    # Bullet hit log, rock, or obstacle: play collision sound & destroy bullet!
                    play_bullet_collision_sfx(S)
                    sx, sy = S.iso.to_screen(*S.iso.world_px(b["wx"], b["wy"]))
                    sy -= S.iso.elev(cx, cy)
                    cat_name = DESTRUCTIBLE_CAT_MAP.get(cell[1], "barrel") if is_destructible else None
                    if is_destructible:
                        p_col = (180, 140, 90) if cat_name in ("barrel", "crate", "sign", "signpost") else ((215, 185, 150) if cat_name == "pot" else (255, 215, 60))
                    else:
                        p_col = (120, 120, 120) if is_rock else ((139, 69, 19) if is_tree else (200, 180, 140))
                    for _ in range(5):
                        S.particles.append({
                            "x": sx + random.uniform(-6, 6),
                            "y": sy - random.uniform(4, 18),
                            "vx": random.uniform(-50, 50),
                            "vy": random.uniform(-70, -10),
                            "life": 0.35,
                            "color": p_col
                        })

                    # Bullets only damage destructibles (pots, crates, barrels, chests, signs)
                    # Logs strictly require an Axe, and stones strictly require a Pickaxe
                    if is_destructible:
                        dmg = b.get("damage", 25)
                        default_hp = 35
                        if cat_name == "pot": default_hp = 20
                        elif cat_name == "chest": default_hp = 50
                        elif cat_name in ("sign", "signpost"): default_hp = 25

                        health = S.prop_health.get((cx, cy), default_hp) - dmg
                        S.prop_health[(cx, cy)] = health

                        if health <= 0:
                            break_destructible(S, cx, cy, cell, cat_name, sx, sy, now)
                    # Bullet consumed and destroyed
                    continue

                alive.append(b)
            S.bullets = alive

        # Player hit flash timer and damage detection
        cur_hp = getattr(S, "player_health", 100)
        prev_hp = getattr(S, "prev_player_health", cur_hp)
        if cur_hp < prev_hp:
            S.player_hit_timer = 0.8
            dmg_taken = prev_hp - cur_hp
            target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else None)
            if target_p:
                wx, wy = S.iso.world_px(target_p[0], target_p[1])
                psx, psy = S.iso.to_screen(wx, wy)
                psy -= S.iso.elev(target_p[0], target_p[1]) + 24
                if not hasattr(S, "damage_popups"):
                    S.damage_popups = []
                S.damage_popups.append({
                    "x": psx, "y": psy, "text": f"-{int(dmg_taken)}",
                    "color": (255, 60, 60), "life": 0.85, "max_life": 0.85, "vy": -45, "is_crit": False
                })
        S.prev_player_health = cur_hp

        # Player Death & Respawn Sequence
        target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else None)
        if cur_hp <= 0 and not getattr(S, "player_is_dead", False):
            S.player_is_dead = True
            S.player_death_timer = 2.0
            if target_p:
                wx, wy = S.iso.world_px(target_p[0], target_p[1])
                psx, psy = S.iso.to_screen(wx, wy)
                psy -= S.iso.elev(target_p[0], target_p[1]) + 30
                if not hasattr(S, "damage_popups"):
                    S.damage_popups = []
                S.damage_popups.append({
                    "x": psx, "y": psy, "text": "FALLEN!",
                    "color": (255, 40, 40), "life": 1.6, "max_life": 1.6, "vy": -30, "is_crit": True
                })

        if getattr(S, "player_is_dead", False):
            S.player_death_timer = max(0.0, getattr(S, "player_death_timer", 2.0) - dt)
            if S.player_death_timer <= 0:
                respawn_x, respawn_y = getattr(S, "spawn_cell", (0, 0)) or (0, 0)
                respawn_x, respawn_y = S.iso.find_free(respawn_x, respawn_y)
                if target_p:
                    target_p[0] = respawn_x
                    target_p[1] = respawn_y
                    target_p[2] = 0.0
                    target_p[3] = 0.0
                    if len(target_p) >= 7:
                        target_p[5] = 0.0
                        target_p[6] = 0.0
                    snap_camera(S, target_p[0], target_p[1])
                    wx, wy = S.iso.world_px(target_p[0], target_p[1])
                    psx, psy = S.iso.to_screen(wx, wy)
                    psy -= S.iso.elev(target_p[0], target_p[1]) + 30
                    if not hasattr(S, "damage_popups"):
                        S.damage_popups = []
                    S.damage_popups.append({
                        "x": psx, "y": psy, "text": "REVIVED!",
                        "color": (80, 255, 140), "life": 1.4, "max_life": 1.4, "vy": -35, "is_crit": True
                    })
                S.player_health = 100
                S.prev_player_health = 100
                S.player_is_dead = False

        if getattr(S, "player_hit_timer", 0.0) > 0:
            S.player_hit_timer = max(0.0, S.player_hit_timer - dt)

        # Update enemies
        if hasattr(S, "enemy_mgr") and S.state in (STATE_TEST, STATE_LOCAL):
            S.enemy_mgr.update(S, dt, now)

    # --- draw ---
    screen = S.screen

    if S.state in (STATE_TEST, STATE_LOCAL):
        pass  # S.iso.draw manages backdrop rendering and surface caching directly
    else:
        # menu-family: a slowly drifting procedural world as the backdrop
        update_menu_bg(S, dt)
        S.menu_iso.draw(screen)
        if not hasattr(S, "_menu_dim_vignette"):
            dim_vig = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
            dim_vig.fill((6, 8, 14, 155))
            dim_vig.blit(S.vignette, (0, 0))
            S._menu_dim_vignette = dim_vig
        screen.blit(S._menu_dim_vignette, (0, 0))
        if S.state != STATE_MENU:
            pass # Removed card background to look like main lobby UI

    if S.state == STATE_WAKE:
        draw_header(S, "")
        elapsed = time.time() - S.wake_start_time
        
        # Juicy orbital loading animation
        cx, cy = CENTER_X, CARD_Y + 120
        num_orbs = 6
        for i in range(num_orbs):
            ang = now * 4.0 + (i * 6.28318 / num_orbs)
            rad = 40 + math.sin(now * 6.0 + i) * 15
            ox = cx + math.cos(ang) * rad
            oy = cy + math.sin(ang) * rad * 0.4  # flatten to isometric perspective!
            
            # depth sorting hack: draw back half darker
            is_back = math.sin(ang) < 0
            color = cfg.GOLD_DIM if is_back else cfg.GOLD
            size = max(2, int(5 + math.cos(ang) * 2))
            
            pygame.draw.circle(screen, color, (int(ox), int(oy)), size)
            if not is_back:
                pygame.draw.circle(screen, cfg.WHITE, (int(ox), int(oy)), size // 2)

        # Pulsing loading text
        msg = f"WAKING SERVER [{elapsed:.1f}s]"
        alpha = int(180 + 75 * math.sin(now * 5))
        text_surf = S.big_font.render(msg, True, cfg.GOLD_FAINT)
        text_surf.set_alpha(alpha)
        screen.blit(text_surf, (cx - text_surf.get_width() // 2, cy + 60))

    elif S.state == STATE_MENU:
        # Render prominent Asherfall crossed-swords logo over the world
        if getattr(S, "brand_logo", None):
            if not hasattr(S, "_brand_logo_shadow"):
                shadow_surf = S.brand_logo.copy()
                shadow_surf.fill((0, 0, 0, 130), special_flags=pygame.BLEND_RGBA_MULT)
                S._brand_logo_shadow = shadow_surf
            bob_y = int(3.5 * math.sin(now * 2.0))
            lx = CENTER_X - S.brand_logo.get_width() // 2
            ly = 65 + bob_y
            screen.blit(S._brand_logo_shadow, (lx + 3, ly + 5))
            screen.blit(S.brand_logo, (lx, ly))

        # hovering a menu item selects it (keeps mouse + keyboard in sync)
        mouse = pygame.mouse.get_pos()
        for i, btn in enumerate(S.MENU_FOCUS):
            if btn.rect.collidepoint(mouse):
                S.focus_index = i
                break
        for i, btn in enumerate(S.MENU_FOCUS):
            selected = (i == S.focus_index)
            color = cfg.SAND_BRIGHT if selected else cfg.SAND
            r = btn.rect
            # drop shadow for legibility over the world
            draw_text(screen, btn.label, S.body_font, r.x + 1, r.centery - 12 + 1,
                      cfg.SAND_SHADOW)
            w = draw_text(screen, btn.label, S.body_font, r.x, r.centery - 12, color)
            if selected:  # cursor pointing at the current selection
                px = r.x + w + 14 + int(2 * math.sin(now * 6))  # gentle nudge
                draw_text(screen, "<", S.body_font, px, r.centery - 12, cfg.SAND_BRIGHT)
        if S.status_msg:
            draw_wrapped_text(screen, S.status_msg, S.font, 126,
                              cfg.WIDTH - 120, cfg.RED, center_x=CENTER_X)

    elif S.state == STATE_SETUP and S.setup_mode == "single":
        draw_header(S, "Single Player")
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        draw_text(screen, "Solo play — move around the play area with WASD.",
                  S.small_font, LEFT_X, CARD_Y + 288, cfg.GOLD_FAINT)
        S.setup_confirm_btn.label = "START"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP and S.setup_mode == "join":
        draw_header(S, "Join a Game")
        S.addr_input.draw(screen, S.font, S.small_font)
        S.code_input.draw(screen, S.font, S.small_font)
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        draw_text(screen, "Enter the 6-character code your friend shared.",
                  S.small_font, LEFT_X, CARD_Y + 288, cfg.GOLD_FAINT)
        S.setup_confirm_btn.label = "JOIN GAME"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP and S.setup_mode == "local":
        draw_header(S, "Local Co-op")
        S.lobby_name_input.draw(screen, S.font, S.small_font)
        S.max_players_stepper.draw(screen, S.font, S.small_font)
        n = setup_name_count(S)
        draw_text(screen, "USERNAMES", S.small_font, LEFT_X, CARD_Y + 220, cfg.GOLD_DIM)
        for i in range(n):
            S.name_inputs[i].label = ""
            col = SCHEMES[i][5]
            r = S.name_inputs[i].rect
            pygame.draw.circle(screen, col, (r.x - 10, r.centery), 5)
            draw_text(screen, f"P{i+1}", S.small_font, r.x, r.y - 18, col)
            S.name_inputs[i].draw(screen, S.font, S.small_font)
        S.setup_confirm_btn.label = "START"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP:  # host
        draw_header(S, "Host a Game")
        S.addr_input.draw(screen, S.font, S.small_font)
        S.lobby_name_input.draw(screen, S.font, S.small_font)
        S.max_players_stepper.draw(screen, S.font, S.small_font)
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        S.setup_confirm_btn.label = "HOST GAME"
        S.setup_confirm_btn.draw(screen, S.font)

        if getattr(S, "using_controller", False):
            setup_items = get_setup_focusables(S)
            if setup_items:
                cur_focus = setup_items[getattr(S, "setup_focus_idx", 0) % len(setup_items)]
                if hasattr(cur_focus, "rect"):
                    draw_focus_ring(screen, cur_focus.rect, color=cfg.GOLD, pad=4)

    elif S.state == STATE_WAIT:
        draw_header(S, S.lobby_name if S.lobby_name else "Standing By")
        if S.room_code:
            draw_text(screen, f"{len(S.lobby_players)}/{S.max_players} PLAYERS — SHARE THIS CODE",
                      S.small_font, 0, CARD_Y + 40, cfg.GOLD_DIM, center_x=CENTER_X)
            box_w, box_h = 220, 60
            box = pygame.Rect(CENTER_X - box_w // 2, CARD_Y + 60, box_w, box_h)
            alpha = pulse_alpha(now)
            pygame.draw.rect(screen, cfg.INPUT_BG, box, border_radius=8)
            pygame.draw.rect(screen, cfg.GOLD, box, 2, border_radius=8)
            code_surf = S.big_font.render(S.room_code, True, cfg.WHITE)
            code_surf.set_alpha(alpha)
            screen.blit(code_surf, (box.centerx - code_surf.get_width() // 2,
                                    box.centery - code_surf.get_height() // 2))
            
            # Draw lobby players
            py = CARD_Y + 140
            
            # Recreate buttons dicts for click handling
            S.lobby_kick_btns = {}
            S.lobby_restrict_btns = {}
            
            all_ready = len(S.lobby_players) > 0
            
            # Use fixed order for players
            for pid, p in S.lobby_players.items():
                is_me = (pid == S.client_id)
                prof, skin, col, nm = p.get("profile", "Pilot"), p.get("skin", "Default"), tuple(p.get("color", [255,255,255])), p.get("name", "Unknown")
                status = "HOST" if p.get("is_host") else ("DISCONNECTED" if p.get("disconnected") else ("RESTRICTED" if p.get("restricted") else ("READY" if p.get("ready") else "NOT READY")))
                
                if not p.get("ready") and not p.get("is_host") and not p.get("restricted"):
                    all_ready = False
                
                # Format: [Profile] / [Skin] / [Colour] — [Name] — [Status]
                color_hex = f"#{col[0]:02X}{col[1]:02X}{col[2]:02X}"
                txt = f"[{prof}] / [{skin}] / [{color_hex}] — {nm}"
                
                if is_me: txt = ">> " + txt
                
                status_color = cfg.GREEN if status == "READY" else (cfg.RED if status in ("RESTRICTED", "KICKED") else cfg.WHITE)
                
                # Draw text and status
                draw_text(screen, txt, S.small_font, CENTER_X - 280, py, col)
                draw_text(screen, status, S.small_font, CENTER_X + 80, py, status_color)
                
                # If host, draw host controls for OTHER players
                if S.is_host and not p.get("is_host"):
                    # KICK button
                    kx, ky = CENTER_X + 180, py - 6
                    kick_btn = Button(kx, ky, 50, 24, "KICK", palette={"fill": cfg.RED, "border": cfg.RED})
                    S.lobby_kick_btns[pid] = kick_btn
                    kick_btn.draw(screen, S.small_font)
                    # RESTRICT button
                    rx, ry = kx + 60, ky
                    rlabel = "UNRESTRICT" if p.get("restricted") else "RESTRICT"
                    rbg = cfg.GREEN if p.get("restricted") else (200, 100, 20)
                    r_btn = Button(rx, ry, 100, 24, rlabel, palette={"fill": rbg, "border": rbg})
                    S.lobby_restrict_btns[pid] = r_btn
                    r_btn.draw(screen, S.small_font)
                    
                py += 35
                
            # Draw my ready button
            my_info = S.lobby_players.get(S.client_id, {})
            if my_info and not my_info.get("is_host") and not my_info.get("restricted"):
                ready_label = "NOT READY" if my_info.get("ready") else "READY"
                ready_bg = (100, 100, 100) if my_info.get("ready") else cfg.GREEN
                S.lobby_ready_btn = Button(CENTER_X - 60, cfg.HEIGHT - 120, 120, 40, ready_label, palette={"fill": ready_bg, "border": ready_bg})
                S.lobby_ready_btn.draw(screen, S.small_font)
            else:
                S.lobby_ready_btn = None
                
            # Draw host START GAME button
            if S.is_host:
                start_bg = cfg.GREEN if all_ready else (100, 100, 100)
                S.lobby_start_btn = Button(CENTER_X - 80, cfg.HEIGHT - 120, 160, 40, "START GAME", palette={"fill": start_bg, "border": start_bg})
                S.lobby_start_btn.draw(screen, S.small_font)
            else:
                S.lobby_start_btn = None
                
        else:
            draw_text(screen, "Reaching relay server...", S.small_font,
                      0, CARD_Y + 130, cfg.GOLD_DIM, center_x=CENTER_X)

        if getattr(S, "using_controller", False):
            wait_items = get_wait_focusables(S)
            if wait_items:
                cur_w = wait_items[getattr(S, "wait_focus_idx", 0) % len(wait_items)]
                if hasattr(cur_w, "rect"):
                    draw_focus_ring(screen, cur_w.rect, color=cfg.GOLD, pad=4)

    elif S.state == STATE_TEST:
        # shared endless world: every player walking the same map
        vis = visible_cells(S)
        S.vis_cells = vis
        S.iso.draw(screen, vis)
        draw_tile_press(S)
        crowd = [(pr["p"], pr["color"], pr["name"], False, pr.get("wep", "AK47"), pr.get("aim", 0.0), pr.get("pressing", False)) for pr in S.peers.values()]
        crowd.append((S.me, color_for(S.username), S.username or "You", True, getattr(S, 'my_weapon', 'AK47'), getattr(S, 'aim_angle', 0.0), getattr(S, 'pressing', False)))
        for p, col, nm, me, wep, aim, pressing in sorted(crowd, key=lambda a: a[0][0] + a[0][1]):  # iso depth
            draw_avatar(S, p, col, nm, me=me, aim_angle=aim, weapon_name=wep, pressing=pressing)
        if hasattr(S, "enemy_mgr"):
            S.enemy_mgr.draw(S, screen)

        # mic sign floating over your head
        mx, my = S.iso.to_screen(*S.iso.world_px(S.me[0], S.me[1]))
        my -= S.iso.elev(S.me[0], S.me[1]) + 42 + S.me[2]
        draw_mic(S, screen, int(mx), int(my), 22, (120, 255, 150), active=S.voice.talking)
        # peers who are talking are hard to know per-id; show a room mic flag
        rtt_text = f"{S.last_rtt:.0f} ms" if S.last_rtt is not None else "…"
        talk = "   MIC ON" if S.voice.talking else ""
        draw_hearts(S)
        draw_weapon_hud(S)
        draw_bottom_inventory(S)
        if S.voice.talking:
            draw_mic(S, screen, cfg.WIDTH - 30, 30, 20, (120, 255, 150))
        draw_chat(S, now)

    elif S.state == STATE_LOCAL:
        # same endless world, same screen, up to 4 rovers
        vis = visible_cells(S)
        S.vis_cells = vis
        S.iso.draw(screen, vis)
        draw_tile_press(S)
        order = sorted(range(len(S.local_players)),
                       key=lambda i: S.local_players[i][0] + S.local_players[i][1])
        for i in order:
            p = S.local_players[i]
            name = S.local_names[i] if i < len(S.local_names) else f"P{i+1}"
            draw_avatar(S, p, SCHEMES[i][5], name, me=(i == 0), aim_angle=getattr(S, 'aim_angle', 0.0) if i==0 else 0.0, weapon_name=getattr(S, 'my_weapon', 'AK47') if i==0 else 'AK47', pressing=getattr(S, 'pressing', False) if i==0 else False)
        if hasattr(S, "enemy_mgr"):
            S.enemy_mgr.draw(S, screen)
        title = S.lobby_name if S.lobby_name else "LOCAL CO-OP"
        schemes = "  ".join(f"P{i+1} {SCHEMES[i][0]}" for i in range(len(S.local_players)))
        cx, cy = centroid(S.local_players)
        chat_hint = " · T chat" if len(S.local_players) == 1 else ""
        draw_hearts(S)
        draw_weapon_hud(S)
        draw_bottom_inventory(S)
        draw_chat(S, now)


    if S.state in (STATE_TEST, STATE_LOCAL):
        # Draw bullets
        if hasattr(S, "bullets"):
            for b in S.bullets:
                px, py = S.iso.world_px(b["wx"], b["wy"])
                sx, sy = S.iso.to_screen(px, py)
                sy -= b.get("z", 0)
                if b["img"]:
                    # Use stored screen angle so it points perfectly toward the mouse
                    angle = math.degrees(-b.get("sa", 0))
                    bw, bh = int(b["img"].get_width() * S.iso.scale * 0.91), int(b["img"].get_height() * S.iso.scale * 0.91)
                    scaled_img = pygame.transform.scale(b["img"], (max(1, bw), max(1, bh)))
                    rot_img = pygame.transform.rotate(scaled_img, angle)
                    r = rot_img.get_rect(center=(int(sx), int(sy)))
                    screen.blit(rot_img, r.topleft)
                else:
                    pygame.draw.circle(screen, (255, 255, 0), (int(sx), int(sy)), 3)
                    
        # Draw particles
        if hasattr(S, "particles"):
            surviving = []
            for p in S.particles:
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                if not p.get("is_slash", False):
                    p["vy"] += 300 * dt  # Gravity
                p["life"] -= dt
                if p["life"] > 0:
                    if p.get("is_slash", False):
                        ang = p.get("angle", 0.0)
                        length = p.get("size", 22)
                        dx = math.cos(ang) * length * 0.5
                        dy = math.sin(ang) * length * 0.5
                        p1 = (int(p["x"] - dx), int(p["y"] - dy))
                        p2 = (int(p["x"] + dx), int(p["y"] + dy))
                        pygame.draw.line(screen, (255, 255, 255), p1, p2, 3)
                        pygame.draw.line(screen, p.get("color", (140, 230, 255)), p1, p2, 1)
                    else:
                        sz = p.get("size", 5)
                        pygame.draw.rect(screen, p["color"], (int(p["x"]), int(p["y"]), sz, sz))
                    surviving.append(p)
            S.particles = surviving

        # Draw and update destructible break animations
        if hasattr(S, "break_effects") and S.break_effects:
            if not hasattr(S, "break_effect_images"):
                S.break_effect_images = {}
                d_dir = os.path.join(S.ASSETS_DIR, "destructibles")
                for cat in ("barrel", "crate", "pot", "sign", "signpost", "chest"):
                    cat_path = os.path.join(d_dir, cat)
                    if os.path.exists(cat_path):
                        frames = []
                        for f in sorted(os.listdir(cat_path)):
                            if f.startswith("break_") and f.endswith(".png"):
                                try:
                                    f_img = pygame.image.load(os.path.join(cat_path, f)).convert_alpha()
                                    frames.append(f_img)
                                except Exception:
                                    pass
                        if frames:
                            S.break_effect_images[cat] = frames

            surviving_effects = []
            for eff in S.break_effects:
                eff["timer"] += dt
                progress = eff["timer"] / max(0.01, eff.get("duration", 0.24))
                frames = S.break_effect_images.get(eff.get("category", ""), [])
                if frames and progress < 1.0:
                    f_idx = min(len(frames) - 1, int(progress * len(frames)))
                    img = frames[f_idx]
                    sc = getattr(S.iso, "scale", 2)
                    iw, ih = int(img.get_width() * (sc / 2.0)), int(img.get_height() * (sc / 2.0))
                    scaled_img = pygame.transform.scale(img, (max(1, iw), max(1, ih)))

                    sx, sy = S.iso.to_screen(*S.iso.world_px(eff["cx"], eff["cy"]))
                    sy -= S.iso.elev(eff["cx"], eff["cy"]) + int(7 * sc)
                    screen.blit(scaled_img, (int(sx - iw // 2), int(sy - ih + 10 * sc)))
                    surviving_effects.append(eff)
            S.break_effects = surviving_effects

        # Draw dropped items
        if hasattr(S, "dropped_items"):
            ensure_drop_images(S)
            vis = visible_cells(S)
            target_p = S.me if S.state == STATE_TEST else (S.local_players[0] if getattr(S, "local_players", None) else (0, 0, 0))
            px, py = target_p[0], target_p[1]
            remaining_dropped = []
            for item in S.dropped_items:
                item["cx"] += item.get("vx", 0) * dt
                item["cy"] += item.get("vy", 0) * dt
                item["z"] = item.get("z", 0.0) + item.get("vz", 0.0) * dt
                item["vz"] = item.get("vz", 0.0) - 800 * dt
                if item["z"] < 0:
                    item["z"] = 0
                    item["vz"] *= -0.4
                    if item["vz"] < 40: item["vz"] = 0
                    item["vx"] = item.get("vx", 0) * 0.5
                    item["vy"] = item.get("vy", 0) * 0.5

                # Magnetization and proximity pickup by player
                dist_to_p = math.hypot(px - item["cx"], py - item["cy"])
                if dist_to_p < 2.5:
                    pull_spd = (2.5 - dist_to_p) * 5.0
                    item["cx"] += ((px - item["cx"]) / max(0.01, dist_to_p)) * pull_spd * dt
                    item["cy"] += ((py - item["cy"]) / max(0.01, dist_to_p)) * pull_spd * dt

                if dist_to_p < 0.85:
                    itype = item.get("type", "log")
                    add_to_inventory(S, itype, 1)
                    play_sfx(S, "pickup", 0.55)
                    if not hasattr(S, "damage_popups"):
                        S.damage_popups = []
                    item_name = itype.capitalize()
                    psx, psy = S.iso.to_screen(*S.iso.world_px(px, py))
                    psy -= S.iso.elev(px, py)
                    S.damage_popups.append({
                        "x": psx + random.uniform(-10, 10),
                        "y": psy - 35,
                        "text": f"+1 {item_name}",
                        "color": (120, 255, 150),
                        "life": 1.2,
                        "vy": -35.0
                    })
                    continue

                remaining_dropped.append(item)

                # Culling
                if (int(round(item["cx"])), int(round(item["cy"]))) not in vis:
                    continue

                ix, iy = item["cx"], item["cy"]
                sx, base_sy = S.iso.to_screen(*S.iso.world_px(ix, iy))
                base_sy -= S.iso.elev(ix, iy)
                sy = base_sy - item.get("z", 0)
                
                img = S.drop_images.get(item["type"])
                if img:
                    # Draw ground shadow
                    shadow = pygame.Surface((16, 8), pygame.SRCALPHA)
                    pygame.draw.ellipse(shadow, (0, 0, 0, 100), shadow.get_rect())
                    screen.blit(shadow, (int(sx - 8), int(base_sy - 4)))
                    # Draw item
                    screen.blit(img, (int(sx - img.get_width()//2), int(sy - img.get_height()//2 - 10)))

            S.dropped_items = remaining_dropped

        # Draw floating damage numbers
        draw_damage_popups(S, screen, dt)

        # Draw floating prompt when near a chest
        draw_chest_interaction_prompt(S, now)

        # Draw Compass & Notebook Journal HUD
        draw_hud_compass_and_notebook(S, now)

    if S.state not in (STATE_TEST, STATE_LOCAL, STATE_MENU):
        draw_footer(S)

    if S.state == STATE_MENU:
        S.help_icon_btn.draw(screen)
    # the close-X only belongs on the setup/wait panels, not floating in-world
    if S.state in (STATE_SETUP, STATE_WAIT) and not S.show_settings:
        S.panel_x.draw(screen)

    if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST) \
            and not S.show_settings and not S.show_keys:
        draw_pause(S, now)

    if S.show_settings:
        screen.blit(get_screen_overlay(140), (0, 0))
        # removed draw_card(screen, SETTINGS_RECT)
        draw_text(screen, "SETTINGS", S.big_font, 0, SETTINGS_RECT.y + 24, cfg.GOLD, center_x=CENTER_X)
        draw_divider(screen, SETTINGS_RECT.x + 30, SETTINGS_RECT.y + 66, SETTINGS_RECT.w - 60)

        for slider in (S.volume_slider, S.cam_smooth_slider):
            slider.draw(screen, S.font, S.small_font)
        
        # We manually aligned the sliders, let's just place the icons dynamically or near music/sound
        if S.music_icon is not None:
            screen.blit(S.music_icon, (SETTINGS_RECT.x + 8, S.volume_slider.rect.centery - 13))
        
        S.music_toggle.draw(screen, S.small_font)
        
        S.render_dist_stepper.draw(screen, S.font, S.small_font)
        S.fps_toggle.draw(screen, S.small_font)
        S.keybinds_btn.draw(screen, S.font)

        draw_text(screen, "NOW PLAYING", S.small_font, SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 130, cfg.GOLD_DIM)
        draw_text(screen, track_display_name(S.music_track_index), S.font,
                  SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 110, cfg.WHITE)

        S.play_pause_btn.label = "PLAY" if S.music_paused else "PAUSE"
        S.prev_btn.draw(screen, S.small_font)
        S.play_pause_btn.draw(screen, S.font)
        S.next_btn.draw(screen, S.small_font)
        S.settings_close_btn.draw(screen, S.font)
        S.settings_x.draw(screen)

        if getattr(S, "using_controller", False):
            set_items = get_settings_focusables(S)
            if set_items:
                cur_s = set_items[getattr(S, "settings_focus_idx", 0) % len(set_items)]
                if hasattr(cur_s, "rect"):
                    draw_focus_ring(screen, cur_s.rect, color=cfg.GOLD, pad=4)

    if S.show_keys:
        draw_keybinds(S, now)

    if getattr(S, "notepad_open", False) and S.state in (STATE_LOCAL, STATE_TEST):
        screen.blit(get_screen_overlay(150), (0, 0))

        # Parchment book card
        book_w, book_h = 560, 420
        book_x = (cfg.WIDTH - book_w) // 2
        book_y = (cfg.HEIGHT - book_h) // 2
        book_rect = pygame.Rect(book_x, book_y, book_w, book_h)
        
        # Background and border
        pygame.draw.rect(screen, (34, 28, 22), book_rect, border_radius=10)
        pygame.draw.rect(screen, (190, 160, 110), book_rect, width=2, border_radius=10)
        inner_rect = pygame.Rect(book_x + 6, book_y + 6, book_w - 12, book_h - 12)
        pygame.draw.rect(screen, (24, 20, 16), inner_rect, border_radius=8)
        
        # Title
        draw_text(screen, "SURVIVOR'S FIELD JOURNAL", S.big_font, 0, book_y + 18, (235, 195, 115), center_x=cfg.WIDTH // 2)
        draw_divider(screen, book_x + 30, book_y + 55, book_w - 60)
        
        # Notes / entries
        lines = [
            ("COMBAT & TOOLS", (255, 215, 0)),
            (" • Left-Click: Fire equipped weapon or strike with tool.", (220, 220, 220)),
            (" • Right-Click: Target & mine stone, rocks, or chop wood.", (220, 220, 220)),
            (" • Shift + Scroll: Cycle through hotbar arsenal.", (220, 220, 220)),
            ("", (0,0,0)),
            ("HOSTILE THREATS: BLOODSEEKER", (255, 90, 90)),
            (" • Aggressive predators patrol the wild with 3-tile sight ranges.", (220, 220, 220)),
            (" • Ground circles highlight their detection field (red = alert).", (220, 220, 220)),
            (" • Defeat them to recover dropped resources & vital materials.", (220, 220, 220)),
            ("", (0,0,0)),
            ("EXPEDITION COMPASS", (100, 200, 255)),
            (" • The red-tipped needle points continuously back to (0, 0) Base Camp.", (220, 220, 220)),
            (" • Press ESC or click the Notebook icon again to close this journal.", (180, 180, 180)),
        ]
        curr_y = book_y + 70
        for text, col in lines:
            if text:
                draw_text(screen, text, S.small_font, book_x + 36, curr_y, col)
            curr_y += 24
        
        # Close button in top right of book
        close_btn_rect = pygame.Rect(book_x + book_w - 38, book_y + 14, 24, 24)
        pygame.draw.rect(screen, (160, 40, 40), close_btn_rect, border_radius=4)
        draw_text(screen, "X", S.small_font, book_x + book_w - 31, book_y + 18, (255, 255, 255))
        S.notepad_close_rect = close_btn_rect

    if getattr(S, "crafting_open", False) and S.state in (STATE_LOCAL, STATE_TEST):
        draw_crafting_menu(S, now)

    if getattr(S, "inventory_open", False) and S.state in (STATE_LOCAL, STATE_TEST):
        draw_full_inventory(S, now)

    if getattr(S, "reload_flash", 0) > now:
        draw_text(screen, "↻ hot-reloaded", S.small_font, 16, cfg.HEIGHT - 32, cfg.GREEN)

    draw_cursor(S, now)  # custom pixel cursor, always on top

    if getattr(S, "fps_toggle", None) and getattr(S.fps_toggle, "value", False):
        draw_text(screen, f"FPS: {int(1.0/max(0.001, dt))}", S.font, 10, 10, cfg.GREEN)

    return running
print('hot-reload triggered 25')
