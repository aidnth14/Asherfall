import math
import os
import random
import pygame
from enemy.base import (
    BaseEnemy, get_scaled_frame, get_enemy_shadow,
    STATE_IDLE, STATE_ALERT, STATE_INVESTIGATE, STATE_CHASE,
    STATE_WINDUP, STATE_ATTACK, STATE_RECOVER, STATE_STAGGERED,
    STATE_RETREAT, STATE_HURT, STATE_DEATH
)

class Skull(BaseEnemy):
    """Spectral Stalker Skull enemy with Perception 2.0 (160-deg cone),
    and Spectral Blink trick (teleports 2-3 tiles away on 4s cooldown when player closes in)."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["coal", "iron", "diamond"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=45, max_poise=40,
            windup_dur=0.30, recover_dur=0.50, alert_dur=0.20,
            sight_radius=4.5, sight_cone_deg=160.0,
            attack_radius=0.95, move_speed=1.75
        )
        self.last_scream_time = -999.0
        self.attack_cooldown = 1.10
        self.anim_speeds = {
            "Idle": 7.0,
            "Attack": 12.0,
            "Hit": 10.0,
            "Death": 8.0,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False

        # Skull Trick: Spectral Blink & Flight
        self.can_fly = True
        self.last_blink_time = -999.0
        self.blink_cooldown = 4.0

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Skull.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "skull")
        def load_sheet(fname, count, cols_per_row=4):
            path = os.path.join(folder, fname)
            frames = []
            if os.path.exists(path):
                try:
                    sheet = pygame.image.load(path).convert_alpha()
                    for i in range(count):
                        r = i // cols_per_row
                        c = i % cols_per_row
                        frame = sheet.subsurface((c * 64, r * 64, 64, 64))
                        frames.append(frame)
                except Exception as e:
                    print(f"Error loading skull sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((64, 64), pygame.SRCALPHA)
                pygame.draw.circle(surf, (100, 220, 255), (32, 32), 12)
                frames = [surf]
            return frames

        Skull.SPRITE_CACHE["Idle"] = load_sheet("Bones_SingleSkull_Idle.png", 4)
        Skull.SPRITE_CACHE["Fly"] = load_sheet("Bones_SingleSkull_Fly.png", 8)
        Skull.SPRITE_CACHE["Attack"] = load_sheet("Bones_SingleSkull_Fly.png", 8)
        Skull.SPRITE_CACHE["Hit"] = load_sheet("Bones_SingleSkull_Hit.png", 4)
        Skull.SPRITE_CACHE["Death"] = load_sheet("Bones_SingleSkull_Death.png", 8)

    def _play_scream_sfx(self, S, now):
        if now - Skull.GLOBAL_LAST_SCREAM < 3.5 or now - self.last_scream_time < 8.0 or getattr(S, "music_muted", False):
            return
        try:
            if Skull.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    Skull.SCREAM_SOUND = pygame.mixer.Sound(p)
            if Skull.SCREAM_SOUND:
                Skull.SCREAM_SOUND.set_volume(0.30)
                Skull.SCREAM_SOUND.play()
                Skull.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def _trigger_spectral_blink(self, S, target, now):
        """Skull trick: blinks 2-3 tiles away when player closes in."""
        self.last_blink_time = now
        # Emit mist at origin
        if hasattr(S, "particles") and hasattr(S, "iso"):
            wx, wy = S.iso.world_px(self.gx, self.gy)
            sx, sy = S.iso.to_screen(wx, wy)
            sy -= S.iso.elev(self.gx, self.gy)
            for _ in range(12):
                S.particles.append({
                    "x": sx + random.uniform(-8, 8), "y": sy + random.uniform(-10, 4),
                    "vx": random.uniform(-40, 40), "vy": random.uniform(-50, 10),
                    "life": random.uniform(0.3, 0.5), "size": random.randint(2, 4),
                    "color": (90, 220, 255)
                })

        # Teleport 2.5 tiles away
        flee_ang = math.atan2(self.gy - target[1], self.gx - target[0]) + random.uniform(-0.5, 0.5)
        dist = random.uniform(2.2, 2.8)
        dest_x = self.gx + math.cos(flee_ang) * dist
        dest_y = self.gy + math.sin(flee_ang) * dist
        fx, fy = S.iso.find_free(dest_x, dest_y, radius=2)
        if not S.iso.solid(fx, fy):
            self.gx, self.gy = fx, fy

        # Flash white upon arrival
        self.white_flash_timer = 0.15

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = Skull.SPRITE_CACHE.get(self.current_anim, [])
        speed = self.anim_speeds.get(self.current_anim, 7.0)
        if frames:
            self.frame_index += speed * dt
            if self.frame_index >= len(frames):
                if self.state == STATE_DEATH:
                    self.frame_index = len(frames) - 1
                elif self.state in (STATE_ATTACK, STATE_HURT):
                    self.frame_index = 0.0
                    self.state = STATE_RECOVER
                    self.recover_timer = self.recover_dur
                    self.current_anim = "Idle"
                else:
                    self.frame_index %= len(frames)

        if self.is_dead:
            self.death_timer -= dt
            if self.death_timer <= 0:
                self.remove_ready = True
            return

        if self.state == STATE_STAGGERED:
            return

        if self.state == STATE_HURT:
            self.hurt_timer -= dt
            if self.hurt_timer <= 0:
                self.state = STATE_CHASE if self.last_known_player_pos else STATE_IDLE
                self.current_anim = "Idle"
            return

        players = []
        if getattr(S, "state", "") == "test" and getattr(S, "me", None):
            players.append(S.me)
        elif getattr(S, "local_players", None):
            players.extend(S.local_players)
        elif getattr(S, "me", None):
            players.append(S.me)

        target = None
        min_dist = 99999.0
        for p in players:
            d = math.hypot(p[0] - self.gx, p[1] - self.gy)
            if d < min_dist:
                min_dist = d
                target = p

        can_see = target and self.can_see_player(S, target[0], target[1])
        self.alert = bool(can_see)

        if not can_see:
            self.check_noise_pings(S, now)

        # Skull Trick: Blink away when player gets within 1.9 tiles!
        if target and min_dist <= 1.9 and (now - self.last_blink_time >= self.blink_cooldown):
            self._trigger_spectral_blink(S, target, now)
            return

        # RECOVER state
        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Idle"
            if self.recover_timer <= 0:
                self.state = STATE_CHASE if can_see else STATE_INVESTIGATE
            return

        # WINDUP state
        if self.state == STATE_WINDUP:
            self.windup_timer -= dt
            self.current_anim = "Attack"
            if target:
                self.facing_left = (target[0] < self.gx)
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
            if self.windup_timer <= 0:
                self.state = STATE_ATTACK
                self.has_damaged_in_attack = False
                self.frame_index = 0.0
            return

        # ATTACK state
        if self.state == STATE_ATTACK:
            if not self.has_damaged_in_attack and target and min_dist <= self.attack_radius * 1.4:
                self.has_damaged_in_attack = True
                dmg = int(14 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state (0.2s quick beat)
        if self.state == STATE_ALERT:
            self.alert_timer -= dt
            self.current_anim = "Idle"
            if target:
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
                self.facing_left = (target[0] < self.gx)
            if self.alert_timer <= 0:
                self.state = STATE_CHASE
                self._play_scream_sfx(S, now)
            return

        # INVESTIGATE state
        if self.state == STATE_INVESTIGATE:
            if can_see:
                self.state = STATE_ALERT
                self.alert_timer = self.alert_dur
                return
            if self.investigate_pos:
                ix, iy = self.investigate_pos
                if math.hypot(ix - self.gx, iy - self.gy) > 0.4:
                    self.current_anim = "Idle"
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.75)
                else:
                    self.investigate_pos = None
                    self.search_timer = random.uniform(3.0, 5.0)
            else:
                self.search_timer -= dt
                if self.search_timer <= 0:
                    self.state = STATE_IDLE
            return

        # CHASE state
        if can_see and target:
            self.last_known_player_pos = (target[0], target[1])
            self.facing_left = (target[0] < self.gx)
            self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
            self.current_anim = "Idle"

            if min_dist <= self.attack_radius:
                if now - self.last_attack_time >= self.attack_cooldown:
                    self.last_attack_time = now
                    self.state = STATE_WINDUP
                    self.windup_timer = self.windup_dur
                    self.current_anim = "Attack"
                    self.frame_index = 0.0
                else:
                    self.state = STATE_RECOVER
                    self.recover_timer = 0.20
            else:
                self.state = STATE_CHASE
                self.navigate_towards(S, target[0], target[1], dt)
        elif self.state == STATE_CHASE:
            self.state = STATE_INVESTIGATE
            self.investigate_pos = self.last_known_player_pos
            self.search_timer = random.uniform(3.0, 5.0)
        else:
            self.state = STATE_IDLE
            self.current_anim = "Idle"
            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(2.0, 4.0)
                ang = random.uniform(0, math.pi * 2)
                dist = random.uniform(0.6, 2.0)
                self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.1:
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.40)
                else:
                    self.wander_target = None

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 160-degree spectral vision cone."""
        if self.is_dead:
            return
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return

        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        sy -= S.iso.elev(self.gx, self.gy)

        half_cone = math.radians(self.sight_cone_deg / 2.0)
        pts = [(sx, sy)]
        steps = 12
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            csy -= S.iso.elev(c_wx, c_wy)
            pts.append((csx, csy))

        col = (60, 200, 240, 45) if self.alert else (40, 150, 190, 22)
        bcol = (90, 230, 255, 140) if self.alert else (60, 180, 220, 65)
        self.draw_cached_cone(S, screen, col, bcol, pts)

    def draw(self, S, screen):
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return
        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        sy -= S.iso.elev(self.gx, self.gy)

        if sx < -80 or sx > S.window.get_width() + 80 or sy < -80 or sy > S.window.get_height() + 80:
            return

        # Spectral shadow or water ripples below
        if hasattr(S, "iso") and hasattr(S.iso, "is_water") and S.iso.is_water(self.gx, self.gy):
            self.draw_water_ripples(S, screen, sx, sy)
        elif not self.is_dead:
            sw, sh = int(14 * S.iso.scale), int(7 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Skull.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 1.05
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(32 * scale_factor)
            anchor_y = int(37 * scale_factor) + int(6 * S.iso.scale)

            # Death animation sink and fade
            death_sink = 0.0
            death_alpha = 1.0
            if self.is_dead:
                death_prog = 1.0 - max(0.0, min(1.0, self.death_timer / max(0.01, getattr(self, "death_total_dur", 1.0))))
                death_sink = death_prog * (5.0 * S.iso.scale)
                if death_prog > 0.40:
                    death_alpha = max(0.0, (1.0 - death_prog) / 0.60)

            draw_pos = (int(sx - anchor_x), int(sy - anchor_y + death_sink))

            if getattr(self, "white_flash_timer", 0.0) > 0:
                flash = scaled_frame.copy()
                flash.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)
                screen.blit(flash, draw_pos)
            elif death_alpha < 0.99:
                faded = scaled_frame.copy()
                faded.fill((255, 255, 255, int(255 * death_alpha)), special_flags=pygame.BLEND_RGBA_MULT)
                screen.blit(faded, draw_pos)
            else:
                screen.blit(scaled_frame, draw_pos)

        if not self.is_dead:
            self.draw_overlays(S, screen, sx, sy, S.iso.scale)