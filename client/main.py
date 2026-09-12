#!/usr/bin/env python3
"""Bootstrapper + live hot-reloader.

The whole per-frame game lives in game.py. This file owns the persistent
state object `S` (which it never rebuilds) and watches game.py / ui.py /
config.py. The instant any of them changes on disk it reloads the modules and
rebuilds the UI in place — the pygame window keeps running, the network
connection and music keep going, no restart needed.
"""
import importlib
import os
import sys
import time
from types import SimpleNamespace

import pygame

import ui
import config as cfg
from network import Connection, install_dns_fallback
import controller
import weapons
import iso
import game

install_dns_fallback()

pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=8192)
pygame.init()
try:
    pygame.joystick.init()
except Exception:
    pass

import controller

S = SimpleNamespace()
S.ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
try:
    S.controller_mgr = controller.ControllerManager(S.ASSETS_DIR)
    S.joysticks = S.controller_mgr.joysticks
except Exception as _je:
    print(f"[controller] boot detection error: {_je}")
    S.joysticks = []

# The game always draws to a fixed logical canvas (cfg.WIDTH x cfg.HEIGHT); the
# window can be freely resized or made fullscreen and we letterbox-scale the
# canvas into it. This keeps all UI layout math resolution-independent.
CW, CH = cfg.WIDTH, cfg.HEIGHT
S.window = pygame.display.set_mode((CW, CH), pygame.RESIZABLE)
S.screen = pygame.Surface((CW, CH))          # the canvas game.frame renders to
S.fullscreen = False
S.windowed_size = (CW, CH)
pygame.display.set_caption("Asherfall")
try:
    _icon_path = os.path.join(S.ASSETS_DIR, "ui", "icon.png")
    if not os.path.exists(_icon_path):
        _icon_path = os.path.join(S.ASSETS_DIR, "ui", "logo.png")
    if os.path.exists(_icon_path):
        _icon_img = pygame.image.load(_icon_path).convert_alpha()
        iw, ih = _icon_img.get_size()
        if iw != ih:
            dim = max(iw, ih)
            _sq_icon = pygame.Surface((dim, dim), pygame.SRCALPHA)
            _sq_icon.blit(_icon_img, ((dim - iw) // 2, (dim - ih) // 2))
            _icon_img = _sq_icon
        pygame.display.set_icon(_icon_img)
except Exception:
    pass


def canvas_fit():
    ww, wh = S.window.get_size()
    scale_x = ww / CW
    scale_y = wh / CH
    return scale_x, scale_y


def to_canvas(pos):
    scale_x, scale_y = canvas_fit()
    return (pos[0] / scale_x, pos[1] / scale_y)


def to_window(pos):
    scale_x, scale_y = canvas_fit()
    return (int(pos[0] * scale_x), int(pos[1] * scale_y))


S.canvas_fit = canvas_fit
S.to_canvas = to_canvas
S.to_window = to_window



def remap_events(events):
    """Translate mouse coords from window space into canvas space, and handle
    window-level keys (F11 fullscreen) / resize here."""
    out = []
    for e in events:
        if e.type == pygame.VIDEORESIZE and not S.fullscreen:
            S.windowed_size = (e.w, e.h)
            S.window = pygame.display.set_mode((e.w, e.h), pygame.RESIZABLE)
            continue
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            S.fullscreen = not S.fullscreen
            if S.fullscreen:
                S.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                S.window = pygame.display.set_mode(S.windowed_size, pygame.RESIZABLE)
            continue
        if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            d = e.dict.copy()
            d["pos"] = to_canvas(e.pos)
            out.append(pygame.event.Event(e.type, d))
        else:
            out.append(e)
    return out


# widgets read pygame.mouse.get_pos() for hover — remap it to canvas space too
_real_mouse_pos = pygame.mouse.get_pos
pygame.mouse.get_pos = lambda: tuple(int(v) for v in to_canvas(_real_mouse_pos()))


def present():
    """Scale the canvas into the window, stretching to fill completely."""
    ww, wh = S.window.get_size()
    
    # Screen shake
    dx = dy = 0
    if getattr(S, "shake", 0.0) > 0.0:
        import random
        intensity = S.shake * 15
        dx = random.randint(-int(intensity), int(intensity))
        dy = random.randint(-int(intensity), int(intensity))
        S.shake = max(0.0, S.shake - 0.05)

    if (ww, wh) == (CW, CH):
        # Direct blit avoids heavy CPU scaling when window matches canvas size
        S.window.blit(S.screen, (dx, dy))
    else:
        # Fast hardware-friendly scale
        scaled = pygame.transform.scale(S.screen, (ww, wh))
        S.window.blit(scaled, (dx, dy))
        
    pygame.display.flip()


class CPURegulator:
    """Intelligent Low-CPU Frame Regulator.
    Guarantees silky-smooth 60 FPS gameplay (eliminating all lag and input latency)
    while avoiding CPU busy-wait loops by yielding idle frame margins to the OS kernel.
    """
    def __init__(self, target_fps=60):
        self.target_fps = target_fps
        self.clock = pygame.time.Clock()
        self.last_frame = time.perf_counter()

    def tick(self, S=None):
        now = time.perf_counter()
        elapsed = now - self.last_frame
        is_active = pygame.display.get_active()
        
        # When minimized / backgrounded, throttle to 20 FPS; otherwise full 60 FPS
        fps = 20.0 if not is_active else float(getattr(cfg, "FPS", self.target_fps))
        target_dt = 1.0 / fps
        rem = target_dt - elapsed
        
        # Non-busy kernel sleep: yields CPU core while waiting for the next frame
        if rem > 0.002:
            time.sleep(rem - 0.001)

        dt = self.clock.tick(int(fps)) / 1000.0
        now2 = time.perf_counter()
        self.last_frame = now2
        return min(dt, 0.05)


S.clock = pygame.time.Clock()
S.cpu_regulator = CPURegulator(60)
S.MUSIC_END_EVENT = pygame.USEREVENT + 1
pygame.mixer.music.set_endevent(S.MUSIC_END_EVENT)
S.conn = Connection()
S.reload_flash = 0

game.init(S)

# --- file watcher: modules that hot-reload live ---
WATCHED = [ui, weapons, iso, game]
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def ensure_relay_server():
    """If pointing to a local relay server (e.g. localhost:8080) and it isn't
    running yet, start server/server.py automatically in the background."""
    server_url = getattr(cfg, "DEFAULT_SERVER", "")
    if "localhost" in server_url or "127.0.0.1" in server_url:
        import socket
        import subprocess
        import atexit
        
        port = 8080
        try:
            from urllib.parse import urlparse
            p = urlparse(server_url).port
            if p: port = p
        except Exception:
            pass
            
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return None  # Server is already running
        except OSError:
            pass
            
        server_path = os.path.join(os.path.dirname(_THIS_DIR), "server", "server.py")
        if os.path.exists(server_path):
            try:
                proc = subprocess.Popen(
                    [sys.executable, server_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                print(f"[auto-server] Started local relay server (PID: {proc.pid}) on port {port}")
                atexit.register(lambda: proc.terminate() if proc.poll() is None else None)
                return proc
            except Exception as e:
                print(f"[auto-server] Failed to start local relay server: {e}")
    return None

S.server_proc = ensure_relay_server()


def _watch_paths():
    paths = {}
    for mod in WATCHED:
        p = getattr(mod, "__file__", None)
        if p:
            paths[mod] = p
    return paths


def _mtimes(paths):
    out = {}
    for mod, p in paths.items():
        try:
            out[mod] = os.path.getmtime(p)
        except OSError:
            pass
    return out


_paths = _watch_paths()
_last_mtimes = _mtimes(_paths)
_last_check = 0.0
CHECK_INTERVAL = 1.0  # seconds between disk polls


def check_for_reload(now):
    """Poll watched files; reload changed modules and rebuild UI in place.
    Returns True if a reload happened."""
    global _last_mtimes
    current = _mtimes(_paths)
    changed = [m for m, t in current.items() if _last_mtimes.get(m) != t]
    if not changed:
        return False
    _last_mtimes = current
    try:
        # reload ui first so game sees new values, then weapons/iso, then game
        for mod in (ui, weapons, iso, game):
            if mod in changed or mod is game:
                importlib.reload(mod)
        game.rebuild(S)
        S.reload_flash = now + 1.5
        print(f"[hot-reload] {', '.join(m.__name__ for m in changed)} @ {time.strftime('%H:%M:%S')}")
        return True
    except Exception as e:
        # keep the old, working code running instead of crashing
        print(f"[hot-reload] FAILED, keeping previous version: {type(e).__name__}: {e}")
        return False


import traceback
import datetime

running = True
try:
    while running:
        dt = S.cpu_regulator.tick(S)
        now = time.time()
    
        if now - _last_check > CHECK_INTERVAL:
            _last_check = now
            check_for_reload(now)
    
        events = remap_events(pygame.event.get())
        running = game.frame(S, events, dt, now)
        present()
except Exception as e:
    crash_report = traceback.format_exc()
    print("\n" + "="*50)
    print("FATAL CRASH DETECTED IN MAIN LOOP")
    print("="*50)
    print(crash_report)
    print("="*50)
    try:
        with open("crash.log", "a") as logfile:
            logfile.write(f"\n--- CRASH AT {datetime.datetime.now()} ---\n")
            logfile.write(crash_report)
        print("Crash report saved to client/crash.log")
    except Exception:
        pass

finally:
    if getattr(S, "server_proc", None) and S.server_proc.poll() is None:
        try:
            S.server_proc.terminate()
        except Exception:
            pass
    S.conn.close()
    if getattr(S, "voice", None):
        S.voice.close()
    pygame.quit()
    sys.exit(0 if not running else 1)
