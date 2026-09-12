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

class Rat(BaseEnemy):
    """Scurrying Rat enemy with Perception 2.0 (100-deg cone, noise reactivity),
    expanded state machine, poise/stagger, and Pack Tactics vs Lone Flee trick."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["meat", "coal", "iron"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=30, max_poise=15,
            windup_dur=0.15, recover_dur=0.30, alert_dur=0.40,
            sight_radius=3.2, sight_cone_deg=100.0,
            attack_radius=0.80, move_speed=2.05
        )
        self.last_scream_time = -999.0
        self.attack_cooldown = 0.90
        self.anim_speeds = {
            "Idle": 6.0,
            "Run": 11.0,
            "Attack": 12.0,
            "Hit": 10.0,
            "Death": 8.0,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False
        self.can_swim = True  # Swarm scavengers swim across water
        self._load_all_sprites()

    def _load_all_sprites(self):
        if Rat.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "rat")
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
                    print(f"Error loading rat sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((64, 64), pygame.SRCALPHA)
                pygame.draw.ellipse(surf, (140, 110, 80), (24, 36, 16, 12))
                frames = [surf]
            return frames

        Rat.SPRITE_CACHE["Idle"] = load_sheet("Rat_Idle.png", 4)
        Rat.SPRITE_CACHE["Run"] = load_sheet("Rat_Run.png", 6)
        Rat.SPRITE_CACHE["Attack"] = load_sheet("Rat_Attack.png", 8)
        Rat.SPRITE_CACHE["Hit"] = load_sheet("Rat_Hit.png", 4)
        Rat.SPRITE_CACHE["Death"] = load_sheet("Rat_Death.png", 5)

    def _play_scream_sfx(self, S, now):
        if now - Rat.GLOBAL_LAST_SCREAM < 3.5 or now - self.last_scream_time < 8.0 or getattr(S, "music_muted", False):
            return
        try:
            if Rat.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    Rat.SCREAM_SOUND = pygame.mixer.Sound(p)
            if Rat.SCREAM_SOUND:
                Rat.SCREAM_SOUND.set_volume(0.28)
                Rat.SCREAM_SOUND.play()
                Rat.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)
        # 50% flee chance if alone and injured
        if not self.is_dead and self.state not in (STATE_STAGGERED, STATE_DEATH):
            has_pack = any(
                other is not self and not other.is_dead and isinstance(other, Rat) and
                math.hypot(other.gx - self.gx, other.gy - self.gy) <= 4.0
                for other in getattr(getattr(S, "enemy_manager", None), "enemies", [])
            )
            if not has_pack and random.random() < 0.50:
                self.state = STATE_RETREAT
                self.retreat_timer = 2.5
                self.current_anim = "Run"

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        # Poise recovery & stagger countdown
        self.update_poise_and_stagger(dt, now)

        frames = Rat.SPRITE_CACHE.get(self.current_anim, [])
        speed = self.anim_speeds.get(self.current_anim, 8.0)
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

        # Find closest player
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

        # Check pack presence (ally within 4 tiles -> +20% speed)
        has_pack = any(
            other is not self and not other.is_dead and isinstance(other, Rat) and
            math.hypot(other.gx - self.gx, other.gy - self.gy) <= 4.0
            for other in getattr(getattr(S, "enemy_manager", None), "enemies", [])
        )
        self.speed_mult = 1.20 if has_pack else 1.0

        # Perception 2.0: Vision cone check
        can_see = target and self.can_see_player(S, target[0], target[1])
        self.alert = bool(can_see)

        # Check noise pings if not chasing
        if not can_see:
            self.check_noise_pings(S, now)

        # RETREAT behavior
        if self.state == STATE_RETREAT:
            self.retreat_timer -= dt
            if self.retreat_timer <= 0 or not target:
                self.state = STATE_IDLE
                self.current_anim = "Idle"
            else:
                self.current_anim = "Run"
                # Run away from target
                rx = self.gx - target[0]
                ry = self.gy - target[1]
                rlen = math.hypot(rx, ry)
                if rlen > 0.01:
                    vx = (rx / rlen) * self.move_speed * 1.15 * dt
                    vy = (ry / rlen) * self.move_speed * 1.15 * dt
                    if not S.iso.solid(self.gx + vx, self.gy + vy):
                        self.gx += vx; self.gy += vy
                    self.facing_left = (vx < 0)
                    self.facing_angle = math.atan2(vy, vx)
            return

        # RECOVER state: punishable window after attack
        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Idle"
            if self.recover_timer <= 0:
                self.state = STATE_CHASE if can_see else STATE_INVESTIGATE
            return

        # WINDUP state: attack telegraph before damage lands
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

        # ATTACK state: delivering bite damage
        if self.state == STATE_ATTACK:
            if not self.has_damaged_in_attack and target and min_dist <= self.attack_radius * 1.4:
                self.has_damaged_in_attack = True
                dmg = int(8 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state: 0.4s pause beat upon first spotting player
        if self.state == STATE_ALERT:
            self.alert_timer -= dt
            self.current_anim = "Idle"
            if target:
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
                self.facing_left = (target[0] < self.gx)
            if self.alert_timer <= 0:
                # If alone and player armed -> 50% flee chance
                armed = getattr(S, "my_weapon", "") in ("Sword", "Axe", "Hammer", "AK47", "SawedOffShotgun", "M24")
                if not has_pack and armed and random.random() < 0.50:
                    self.state = STATE_RETREAT
                    self.retreat_timer = 2.5
                else:
                    self.state = STATE_CHASE
                    self._play_scream_sfx(S, now)
            return

        # INVESTIGATE state: pathing to last known player position, searching 3-5s
        if self.state == STATE_INVESTIGATE:
            if can_see:
                self.state = STATE_ALERT
                self.alert_timer = self.alert_dur
                return
            if self.investigate_pos:
                ix, iy = self.investigate_pos
                if math.hypot(ix - self.gx, iy - self.gy) > 0.4:
                    self.current_anim = "Run"
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.75)
                else:
                    self.investigate_pos = None
                    self.search_timer = random.uniform(3.0, 5.0)
                    self.current_anim = "Idle"
            else:
                self.search_timer -= dt
                self.current_anim = "Idle"
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
                    self.recover_timer = 0.15
            else:
                self.state = STATE_CHASE
                self.current_anim = "Run"
                # Group positioning: approach along assigned slot angle if provided
                if self.group_slot_angle is not None:
                    target_x = target[0] + math.cos(self.group_slot_angle) * (self.attack_radius * 0.9)
                    target_y = target[1] + math.sin(self.group_slot_angle) * (self.attack_radius * 0.9)
                else:
                    target_x, target_y = target[0], target[1]

                self.navigate_towards(S, target_x, target_y, dt)
        elif self.state == STATE_CHASE:
            # Lost sight: transition to INVESTIGATE instead of resetting to IDLE!
            self.state = STATE_INVESTIGATE
            self.investigate_pos = self.last_known_player_pos
            self.search_timer = random.uniform(3.0, 5.0)
            self.current_anim = "Idle"
        else:
            # IDLE / Wander
            self.state = STATE_IDLE
            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(1.5, 4.0)
                if random.random() < 0.65:
                    ang = random.uniform(0, math.pi * 2)
                    dist = random.uniform(0.6, 2.0)
                    self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
                else:
                    self.wander_target = None

            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.1:
                    self.current_anim = "Run"
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.45)
                else:
                    self.wander_target = None
                    self.current_anim = "Idle"
            else:
                self.current_anim = "Idle"

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 100-degree vision cone projected onto isometric ground."""
        if self.is_dead:
            return
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return

        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        sy -= S.iso.elev(self.gx, self.gy)

        # Draw vision cone arc
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

        col = (250, 180, 40, 50) if self.alert else (160, 110, 25, 25)
        bcol = (255, 200, 50, 140) if self.alert else (180, 130, 35, 70)
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

        # Water ripples or ground shadow
        if self.is_in_water:
            self.draw_water_ripples(S, screen, sx, sy)
            sy += math.sin((pygame.time.get_ticks() / 1000.0) * 5.0 + self.water_bob_phase) * (2.0 * S.iso.scale)
        elif not self.is_dead:
            sw, sh = int(14 * S.iso.scale), int(7 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Rat.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.91
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

        # Universal overlays (Poise bar, Health bar, Alert indicator, Stagger stars)
        if not self.is_dead:
            self.draw_overlays(S, screen, sx, sy, S.iso.scale)