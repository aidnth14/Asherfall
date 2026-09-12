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

class Soldier(BaseEnemy):
    """Elite Royal Soldier enemy featuring:
      - Perception 2.0 visual cone (110 deg, 5.8 tiles)
      - Dual-mode combat: Tactical Sword Combat (Slash / Leaping Strike) at close range
      - Ranged Archery: Draws bow and fires high-speed arrow projectiles (Attack03) at distance
      - Frontal Deflective Shield Guard: 35% chance to deflect frontal strikes with reduced damage and metallic parry sparks
      - Military Supply Drops: ammo, iron ore, boots, bread, key
    """

    SPRITE_CACHE = {}
    ARROW_IMG = None
    LOOT_ITEMS = ["ammo", "pistol_ammo", "shotgun_ammo", "iron_ore", "boots", "bread", "meat", "key"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=95, max_poise=80,
            windup_dur=0.38, recover_dur=0.50, alert_dur=0.35,
            sight_radius=5.8, sight_cone_deg=110.0,
            attack_radius=1.25, move_speed=1.80
        )
        self.attack_mode = "MELEE_SLASH"  # "MELEE_SLASH", "MELEE_JUMP", "RANGED_BOW"
        self.last_shot_time = -999.0
        self.bow_cooldown = 2.8
        self.shield_block_chance = 0.35

        self.anim_speeds = {
            "Idle": 6.0,
            "Walk": 9.0,
            "Attack01": 11.0,
            "Attack02": 10.0,
            "Attack03": 10.0,
            "Hit": 10.0,
            "Death": 6.5,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Soldier.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "soldier")

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
                    print(f"Error loading soldier sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
                pygame.draw.circle(surf, (80, 120, 200), (fw // 2, fh // 2), 24)
                frames = [surf]
            return frames

        Soldier.SPRITE_CACHE["Idle"] = load_sheet("Soldier_Idle.png", 6)
        Soldier.SPRITE_CACHE["Walk"] = load_sheet("Soldier_Walk.png", 8)
        Soldier.SPRITE_CACHE["Attack01"] = load_sheet("Soldier_Attack01.png", 6)
        Soldier.SPRITE_CACHE["Attack02"] = load_sheet("Soldier_Attack02.png", 6)
        Soldier.SPRITE_CACHE["Attack03"] = load_sheet("Soldier_Attack03.png", 9)
        Soldier.SPRITE_CACHE["Hit"] = load_sheet("Soldier_Hurt.png", 4)
        Soldier.SPRITE_CACHE["Death"] = load_sheet("Soldier_Death.png", 4)

        if Soldier.ARROW_IMG is None:
            arrow_path = os.path.join(folder, "Arrow01(32x32).png")
            if os.path.exists(arrow_path):
                try:
                    Soldier.ARROW_IMG = pygame.image.load(arrow_path).convert_alpha()
                except Exception as e:
                    print(f"Error loading arrow projectile: {e}")
            if Soldier.ARROW_IMG is None:
                surf = pygame.Surface((24, 8), pygame.SRCALPHA)
                pygame.draw.line(surf, (200, 180, 140), (0, 4), (20, 4), 2)
                pygame.draw.polygon(surf, (160, 160, 170), [(20, 1), (24, 4), (20, 7)])
                Soldier.ARROW_IMG = surf

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        if not self.is_dead and self.state not in (STATE_STAGGERED, STATE_HURT):
            hit_angle = math.atan2(kdy, kdx)
            facing_diff = abs((hit_angle - self.facing_angle + math.pi) % (2 * math.pi) - math.pi)
            if facing_diff > 1.8 and random.random() < self.shield_block_chance:
                amount = max(1, int(amount * 0.32))
                poise_dmg = int(poise_dmg * 0.25)
                
                if hasattr(S, "particles") and hasattr(S, "iso"):
                    wx, wy = S.iso.world_px(self.gx, self.gy)
                    sx, sy = S.iso.to_screen(wx, wy)
                    try:
                        sy -= S.iso.elev(self.gx, self.gy)
                    except Exception:
                        pass
                    for _ in range(8):
                        S.particles.append({
                            "x": sx + random.uniform(-6, 6),
                            "y": sy - 18 + random.uniform(-6, 6),
                            "vx": random.uniform(-70, 70),
                            "vy": random.uniform(-90, -20),
                            "life": random.uniform(0.2, 0.4),
                            "size": random.randint(2, 4),
                            "color": random.choice([(255, 235, 150), (255, 255, 255), (180, 220, 255)])
                        })
                
                if hasattr(S, "damage_popups") and hasattr(S, "iso"):
                    wx, wy = S.iso.world_px(self.gx, self.gy)
                    sx, sy = S.iso.to_screen(wx, wy)
                    try:
                        sy -= S.iso.elev(self.gx, self.gy)
                    except Exception:
                        pass
                    S.damage_popups.append({
                        "x": sx, "y": sy - 36, "text": "Parried!",
                        "color": (190, 230, 255), "life": 0.9, "max_life": 0.9, "vy": -32.0
                    })

        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = Soldier.SPRITE_CACHE.get(self.current_anim, [])
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
            if self.attack_mode == "RANGED_BOW":
                if not self.has_damaged_in_attack and self.frame_index >= 5.5 and target:
                    self.has_damaged_in_attack = True
                    self.last_shot_time = now

                    ang = math.atan2(target[1] - self.gy, target[0] - self.gx)
                    spd = 8.0
                    if hasattr(S, "enemy_manager"):
                        if not hasattr(S.enemy_manager, "projectiles"):
                            S.enemy_manager.projectiles = []
                        S.enemy_manager.projectiles.append({
                            "gx": self.gx + math.cos(ang) * 0.4,
                            "gy": self.gy + math.sin(ang) * 0.4,
                            "vx": math.cos(ang) * spd,
                            "vy": math.sin(ang) * spd,
                            "angle": ang,
                            "life": 2.2,
                            "damage": 16,
                            "shooter": self
                        })
            else:
                if not self.has_damaged_in_attack and self.frame_index >= 2.8 and target:
                    if min_dist <= self.attack_radius * 1.35:
                        self.has_damaged_in_attack = True
                        dmg = 24 if self.attack_mode == "MELEE_JUMP" else 18
                        if hasattr(S, "player_health"):
                            S.player_health = max(0, S.player_health - dmg)
                            if hasattr(S, "enemy_manager"):
                                S.enemy_manager.record_player_damage(now, dmg)
                                if S.player_health <= 20:
                                    S.enemy_manager.record_near_death(now)
                        S.player_hit_timer = 0.7
                        S.shake = max(getattr(S, "shake", 0.0), 0.12)
            return

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
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.75)
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
                        self.attack_mode = "MELEE_JUMP"
                        self.current_anim = "Attack02"
                    else:
                        self.attack_mode = "MELEE_SLASH"
                        self.current_anim = "Attack01"
                    self.frame_index = 0.0
                    return

                if 2.0 <= min_dist <= 6.2 and (now - self.last_shot_time >= self.bow_cooldown):
                    self.state = STATE_WINDUP
                    self.windup_timer = 0.52
                    self.attack_mode = "RANGED_BOW"
                    self.current_anim = "Attack03"
                    self.frame_index = 0.0
                    return

                self.current_anim = "Walk"
                self.navigate_towards(S, target[0], target[1], dt)
            return

        if self.state == STATE_IDLE:
            if can_see:
                self.state = STATE_ALERT
                self.alert_timer = self.alert_dur
                return

            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(2.5, 5.0)
                if random.random() < 0.55:
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

        col = (255, 210, 60, 40) if self.alert else (180, 195, 220, 20)
        bcol = (255, 230, 90, 130) if self.alert else (160, 180, 210, 60)
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

        frames = Soldier.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.89
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(frame.get_width() * 0.50 * scale_factor)
            anchor_y = int(frame.get_height() * 0.60 * scale_factor)

            death_sink = 0.0
            death_alpha = 1.0
            if self.is_dead:
                death_prog = 1.0 - max(0.0, min(1.0, self.death_timer / max(0.01, getattr(self, "death_total_dur", 1.0))))
                death_sink = death_prog * (5.0 * S.iso.scale)
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
