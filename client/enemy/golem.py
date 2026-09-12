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

class Golem(BaseEnemy):
    """Colossal Titan Golem enemy with Perception 2.0 (100-deg cone + 360-deg ground tremor),
    high poise (220), 0.80s slam windup, 1.20s recovery, and Light Gun Resistance (-60%) trick."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["iron_ore", "gold_ore", "diamond", "brick"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=180, max_poise=220,
            windup_dur=0.80, recover_dur=1.20, alert_dur=0.70,
            sight_radius=4.0, sight_cone_deg=100.0,
            attack_radius=1.2, move_speed=1.05
        )
        self.last_scream_time = -999.0
        self.attack_cooldown = 1.80
        self.anim_speeds = {
            "Idle": 5.0,
            "Walk": 6.0,
            "Attack": 8.0,
            "Hit": 8.0,
            "Death": 6.0,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(2.0, 5.0)
        self.alert = False

        # Golem traits
        self.tremor_sensing = True
        self.resists_light_guns = True

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Golem.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "golem")
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
                    print(f"Error loading golem sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((64, 64), pygame.SRCALPHA)
                pygame.draw.ellipse(surf, (150, 140, 130), (12, 12, 40, 44))
                frames = [surf]
            return frames

        Golem.SPRITE_CACHE["Idle"] = load_sheet("Golem_IdleA.png", 4)
        Golem.SPRITE_CACHE["Walk"] = load_sheet("Golem_Run.png", 4)
        Golem.SPRITE_CACHE["Run"] = Golem.SPRITE_CACHE["Walk"]
        Golem.SPRITE_CACHE["Attack"] = load_sheet("Golem_AttackA.png", 8)
        Golem.SPRITE_CACHE["Hit"] = load_sheet("Golem_HitA.png", 4)
        Golem.SPRITE_CACHE["Death"] = load_sheet("Golem_DeathA.png", 8)

    def _play_scream_sfx(self, S, now):
        if now - Golem.GLOBAL_LAST_SCREAM < 4.0 or now - self.last_scream_time < 9.0 or getattr(S, "music_muted", False):
            return
        try:
            if Golem.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    Golem.SCREAM_SOUND = pygame.mixer.Sound(p)
            if Golem.SCREAM_SOUND:
                Golem.SCREAM_SOUND.set_volume(0.38)
                Golem.SCREAM_SOUND.play()
                Golem.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = Golem.SPRITE_CACHE.get(self.current_anim, [])
        speed = self.anim_speeds.get(self.current_anim, 6.0)
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

        # RECOVER state (1.20s long punishable window!)
        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Idle"
            if self.recover_timer <= 0:
                self.state = STATE_CHASE if can_see else STATE_INVESTIGATE
            return

        # WINDUP state (0.80s colossal ground slam telegraph!)
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

        # ATTACK state: devastating shockwave slam
        if self.state == STATE_ATTACK:
            if not self.has_damaged_in_attack and target and min_dist <= self.attack_radius * 1.5:
                self.has_damaged_in_attack = True
                dmg = int(28 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state (0.7s slow tremor sensing pause)
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
                    self.current_anim = "Walk"
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.65)
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

            if min_dist <= self.attack_radius:
                if now - self.last_attack_time >= self.attack_cooldown:
                    self.last_attack_time = now
                    self.state = STATE_WINDUP
                    self.windup_timer = self.windup_dur
                    self.current_anim = "Attack"
                    self.frame_index = 0.0
                else:
                    self.state = STATE_RECOVER
                    self.recover_timer = 0.30
            else:
                self.state = STATE_CHASE
                self.current_anim = "Walk"
                if self.group_slot_angle is not None:
                    target_x = target[0] + math.cos(self.group_slot_angle) * (self.attack_radius * 0.9)
                    target_y = target[1] + math.sin(self.group_slot_angle) * (self.attack_radius * 0.9)
                else:
                    target_x, target_y = target[0], target[1]

                self.navigate_towards(S, target_x, target_y, dt)
        elif self.state == STATE_CHASE:
            self.state = STATE_INVESTIGATE
            self.investigate_pos = self.last_known_player_pos
            self.search_timer = random.uniform(3.0, 5.0)
        else:
            self.state = STATE_IDLE
            self.current_anim = "Idle"
            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(2.5, 5.0)
                ang = random.uniform(0, math.pi * 2)
                dist = random.uniform(0.5, 1.8)
                self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.1:
                    self.current_anim = "Walk"
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.35)
                else:
                    self.wander_target = None
                    self.current_anim = "Idle"

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 100-degree stone cone + 360-degree ground tremor range."""
        if self.is_dead:
            return
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return

        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        sy -= S.iso.elev(self.gx, self.gy)

        # 1. Tremor circle (3.0 tiles)
        # 1. Tremor circle (3.0 tiles)
        trw = int(3.0 * S.iso.HALF_W * 2)
        trh = int(3.0 * S.iso.HALF_H * 2)
        if not hasattr(self, "_tremor_surf") or self._tremor_surf.get_size() != (trw, trh):
            self._tremor_surf = pygame.Surface((trw, trh), pygame.SRCALPHA)
            pygame.draw.ellipse(self._tremor_surf, (150, 140, 130, 20), (0, 0, trw, trh))
            pygame.draw.ellipse(self._tremor_surf, (170, 160, 145, 60), (0, 0, trw, trh), 1)
        screen.blit(self._tremor_surf, (int(sx - trw // 2), int(sy - trh // 2)))

        # 2. Vision cone
        half_cone = math.radians(self.sight_cone_deg / 2.0)
        pts = [(sx, sy)]
        steps = 10
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            csy -= S.iso.elev(c_wx, c_wy)
            pts.append((csx, csy))

        col = (180, 170, 155, 45) if self.alert else (130, 120, 110, 22)
        bcol = (210, 200, 185, 140) if self.alert else (160, 150, 135, 65)
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

        # Heavy stone titan shadow or water ripples
        if self.is_in_water:
            self.draw_water_ripples(S, screen, sx, sy)
            sy += math.sin((pygame.time.get_ticks() / 1000.0) * 4.0 + self.water_bob_phase) * (2.0 * S.iso.scale)
        elif not self.is_dead:
            sw, sh = int(16 * S.iso.scale), int(8 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Golem.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 1.05
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(32 * scale_factor)
            anchor_y = int(48 * scale_factor)

            # Death animation sink and fade
            death_sink = 0.0
            death_alpha = 1.0
            if self.is_dead:
                death_prog = 1.0 - max(0.0, min(1.0, self.death_timer / max(0.01, getattr(self, "death_total_dur", 1.0))))
                death_sink = death_prog * (6.0 * S.iso.scale)
                if death_prog > 0.45:
                    death_alpha = max(0.0, (1.0 - death_prog) / 0.55)

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