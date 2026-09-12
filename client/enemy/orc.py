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

class Orc(BaseEnemy):
    """Heavy Orc Berserker enemy featuring:
      - Perception 2.0 (105 deg, 5.2 tiles)
      - Brutal Melee Combat: Cleave Swing (Attack01) and Heavy Ground Slam (Attack02)
      - Bloodlust Rage: Gains +22% move speed and +25% damage when below 50% HP
      - Drops: meat, wood, brick, iron_ore, gold_ore
    """

    SPRITE_CACHE = {}
    LOOT_ITEMS = ["meat", "wood", "brick", "iron_ore", "gold_ore"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=130, max_poise=110,
            windup_dur=0.48, recover_dur=0.65, alert_dur=0.38,
            sight_radius=5.2, sight_cone_deg=105.0,
            attack_radius=1.35, move_speed=1.50
        )
        self.enraged = False
        self.attack_mode = "CLEAVE"  # "CLEAVE" or "SLAM"

        self.anim_speeds = {
            "Idle": 6.0,
            "Walk": 8.0,
            "Attack01": 10.0,
            "Attack02": 9.0,
            "Hit": 10.0,
            "Death": 6.5,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Orc.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "orc")

        def load_sheet(fname, count, fw=100, fh=100):
            path = os.path.join(folder, fname)
            frames = []
            if os.path.exists(path):
                try:
                    sheet = pygame.image.load(path).convert_alpha()
                    sw, sh = sheet.get_size()
                    for i in range(count):
                        x = i * fw
                        if x + fw <= sw:
                            frame = sheet.subsurface((x, 0, fw, fh))
                            frames.append(frame)
                except Exception as e:
                    print(f"Error loading orc sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
                pygame.draw.circle(surf, (60, 140, 60), (fw // 2, fh // 2), 26)
                frames = [surf]
            return frames

        Orc.SPRITE_CACHE["Idle"] = load_sheet("Orc_Idle.png", 6)
        Orc.SPRITE_CACHE["Walk"] = load_sheet("Orc_Walk.png", 8)
        Orc.SPRITE_CACHE["Attack01"] = load_sheet("Orc_Attack01.png", 6)
        Orc.SPRITE_CACHE["Attack02"] = load_sheet("Orc_Attack02.png", 6)
        Orc.SPRITE_CACHE["Hit"] = load_sheet("Orc_Hurt.png", 4)
        Orc.SPRITE_CACHE["Death"] = load_sheet("Orc_Death.png", 4)

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)
        if not self.is_dead and self.hp <= self.max_hp * 0.5 and not self.enraged:
            self.enraged = True
            self.speed_mult = 1.22
            self.damage_mult = 1.25
            if hasattr(S, "damage_popups") and hasattr(S, "iso"):
                wx, wy = S.iso.world_px(self.gx, self.gy)
                sx, sy = S.iso.to_screen(wx, wy)
                try:
                    sy -= S.iso.elev(self.gx, self.gy)
                except Exception:
                    pass
                S.damage_popups.append({
                    "x": sx, "y": sy - 40, "text": "ENRAGED!",
                    "color": (255, 60, 40), "life": 1.2, "max_life": 1.2, "vy": -35.0
                })

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = Orc.SPRITE_CACHE.get(self.current_anim, [])
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

        players = []
        if getattr(S, "state", "") == "test" and getattr(S, "me", None):
            players.append(S.me)
        elif getattr(S, "local_players", None):
            players = S.local_players
        elif getattr(S, "me", None):
            players.append(S.me)

        target = None
        min_dist = 999.0
        can_see = False
        for p in players:
            d = math.hypot(p[0] - self.gx, p[1] - self.gy)
            if d < min_dist:
                min_dist = d
                target = p

        if target and self.can_see_player(S, target[0], target[1]):
            can_see = True
            self.last_known_player_pos = (target[0], target[1])
            self.alert = True
        else:
            self.alert = False

        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Idle"
            if self.recover_timer <= 0:
                self.state = STATE_CHASE if can_see else STATE_INVESTIGATE
            return

        if self.state == STATE_WINDUP:
            self.windup_timer -= dt
            if target:
                self.facing_left = (target[0] < self.gx)
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
            if self.windup_timer <= 0:
                self.state = STATE_ATTACK
                self.has_damaged_in_attack = False
                self.frame_index = 0.0
            return

        if self.state == STATE_ATTACK:
            frames = Orc.SPRITE_CACHE.get(self.current_anim, [])
            total_frames = len(frames) if frames else 6

            if not self.has_damaged_in_attack and self.frame_index >= 2.8 and target:
                if min_dist <= self.attack_radius * 1.35:
                    self.has_damaged_in_attack = True
                    dmg = int((32 if self.attack_mode == "SLAM" else 24) * self.damage_mult)
                    if hasattr(S, "player_health"):
                        S.player_health = max(0, S.player_health - dmg)
                        if hasattr(S, "enemy_manager"):
                            S.enemy_manager.record_player_damage(now, dmg)
                            if S.player_health <= 20:
                                S.enemy_manager.record_near_death(now)
                    S.player_hit_timer = 0.8
                    S.shake = max(getattr(S, "shake", 0.0), 0.22 if self.attack_mode == "SLAM" else 0.14)
                    try:
                        from game import play_sfx
                        play_sfx(S, "break" if self.attack_mode == "SLAM" else "slash", 0.75)
                    except Exception:
                        pass
            return

        # Enraged burning aura particles
        if self.enraged and not self.is_dead and hasattr(S, "particles") and random.random() < 0.35:
            wx, wy = S.iso.world_px(self.gx, self.gy)
            sx, sy = S.iso.to_screen(wx, wy)
            try:
                sy -= S.iso.elev(self.gx, self.gy)
            except Exception:
                pass
            S.particles.append({
                "x": sx + random.uniform(-10, 10),
                "y": sy - random.uniform(8, 22),
                "vx": random.uniform(-12, 12),
                "vy": -random.uniform(25, 55),
                "life": random.uniform(0.25, 0.45),
                "size": random.randint(2, 3),
                "color": random.choice([(255, 60, 40), (255, 120, 50), (200, 30, 30)])
            })

        if self.state == STATE_ALERT:
            self.alert_timer -= dt
            self.current_anim = "Idle"
            if target:
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)
                self.facing_left = (target[0] < self.gx)
            if self.alert_timer <= 0:
                self.state = STATE_CHASE
            return

        if self.state == STATE_INVESTIGATE:
            if can_see:
                self.state = STATE_ALERT
                self.alert_timer = self.alert_dur
                return
            if self.investigate_pos:
                ix, iy = self.investigate_pos
                if math.hypot(ix - self.gx, iy - self.gy) > 0.4:
                    self.current_anim = "Walk"
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.70)
                else:
                    self.investigate_pos = None
                    self.search_timer = random.uniform(3.0, 5.0)
            else:
                self.search_timer -= dt
                self.current_anim = "Idle"
                if self.search_timer <= 0:
                    self.state = STATE_IDLE
            return

        if self.state == STATE_CHASE:
            if not can_see and min_dist > self.sight_radius * 1.3:
                self.state = STATE_INVESTIGATE
                if self.last_known_player_pos:
                    self.investigate_pos = self.last_known_player_pos
                return

            if target:
                self.facing_left = (target[0] < self.gx)
                self.facing_angle = math.atan2(target[1] - self.gy, target[0] - self.gx)

                if min_dist <= self.attack_radius:
                    self.state = STATE_WINDUP
                    self.windup_timer = self.windup_dur
                    if random.random() < 0.45:
                        self.attack_mode = "SLAM"
                        self.current_anim = "Attack02"
                    else:
                        self.attack_mode = "CLEAVE"
                        self.current_anim = "Attack01"
                    self.frame_index = 0.0
                    return

                self.current_anim = "Walk"
                self.navigate_towards(S, target[0], target[1], dt, speed_override=self.move_speed * self.speed_mult)
            return

        if self.state == STATE_IDLE:
            if can_see:
                self.state = STATE_ALERT
                self.alert_timer = self.alert_dur
                return

            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(2.5, 5.0)
                if random.random() < 0.50:
                    ang = random.uniform(0, math.pi * 2)
                    dist = random.uniform(1.5, 3.5)
                    self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
                else:
                    self.wander_target = None

            if self.wander_target:
                tx, ty = self.wander_target
                if math.hypot(tx - self.gx, ty - self.gy) > 0.4:
                    self.current_anim = "Walk"
                    self.navigate_towards(S, tx, ty, dt, speed_override=self.move_speed * 0.55)
                else:
                    self.wander_target = None
                    self.current_anim = "Idle"
            else:
                self.current_anim = "Idle"

    def draw_sighting_range(self, S, screen):
        if self.is_dead:
            return
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return

        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        try:
            sy -= S.iso.elev(self.gx, self.gy)
        except Exception:
            pass

        half_cone = math.radians(self.sight_cone_deg / 2.0)
        pts = [(sx, sy)]
        steps = 10
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            try:
                csy -= S.iso.elev(c_wx, c_wy)
            except Exception:
                pass
            pts.append((csx, csy))

        col = (230, 80, 40, 45) if self.alert else (140, 160, 110, 20)
        bcol = (255, 100, 50, 140) if self.alert else (150, 170, 120, 60)
        self.draw_cached_cone(S, screen, col, bcol, pts)

    def draw(self, S, screen):
        vis = getattr(S, "vis_cells", None)
        if vis is not None and (int(round(self.gx)), int(round(self.gy))) not in vis:
            return
        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        try:
            sy -= S.iso.elev(self.gx, self.gy)
        except Exception:
            pass

        if sx < -80 or sx > S.window.get_width() + 80 or sy < -80 or sy > S.window.get_height() + 80:
            return

        if self.is_in_water:
            self.draw_water_ripples(S, screen, sx, sy)
            sy += math.sin((pygame.time.get_ticks() / 1000.0) * 5.0 + self.water_bob_phase) * (2.0 * S.iso.scale)
        elif not self.is_dead:
            sw, sh = int(16 * S.iso.scale), int(8 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Orc.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.90
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(frame.get_width() * 0.50 * scale_factor)
            anchor_y = int(frame.get_height() * 0.57 * scale_factor)

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
