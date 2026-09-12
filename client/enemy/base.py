import math
import random
import pygame
from enemy.navigation import find_path, slide_move

STATE_IDLE = "IDLE"
STATE_ALERT = "ALERT"
STATE_INVESTIGATE = "INVESTIGATE"
STATE_CHASE = "CHASE"
STATE_WINDUP = "WINDUP"
STATE_ATTACK = "ATTACK"
STATE_RECOVER = "RECOVER"
STATE_STAGGERED = "STAGGERED"
STATE_RETREAT = "RETREAT"
STATE_HURT = "HURT"
STATE_DEATH = "DEATH"

class BaseEnemy:
    """Universal Base Enemy implementing:
      - Perception 2.0: 100-degree visual cone + noise ping reactivity (gunfire 12t, mining 5t, swing 3t, sprint 2t)
      - Expanded State Machine: IDLE -> ALERT (pause beat) -> INVESTIGATE (3-5s search) -> CHASE -> WINDUP (telegraph) -> ATTACK -> RECOVER (punishable) -> STAGGERED (0 poise) / RETREAT -> DEATH
      - Poise & Stagger: independent meter, rapid regen on 1.75s peace, vulnerability on 0 poise
    """

    def __init__(self, gx, gy, assets_dir, max_hp, max_poise, windup_dur, recover_dur, alert_dur=0.4, sight_radius=4.0, sight_cone_deg=100.0, attack_radius=0.85, move_speed=2.0):
        self.gx = float(gx)
        self.gy = float(gy)
        self.z = 0.0
        self.assets_dir = assets_dir

        self.max_hp = max_hp
        self.hp = max_hp

        # Poise & Stagger
        self.max_poise = max_poise
        self.current_poise = max_poise
        self.last_poise_hit_time = -999.0
        self.stagger_timer = 0.0

        # State Machine
        self.state = STATE_IDLE
        self.facing_angle = random.uniform(0, math.pi * 2)
        self.facing_left = False

        # Perception 2.0
        self.sight_radius = sight_radius
        self.sight_cone_deg = sight_cone_deg
        self.alert_dur = alert_dur
        self.alert_timer = 0.0
        self.investigate_pos = None
        self.search_timer = 0.0
        self.last_known_player_pos = None

        # Combat timing
        self.windup_dur = windup_dur
        self.windup_timer = 0.0
        self.recover_dur = recover_dur
        self.recover_timer = 0.0
        self.attack_radius = attack_radius
        self.move_speed = move_speed
        self.last_attack_time = -999.0
        self.has_damaged_in_attack = False

        # Retreat / Flee
        self.retreat_timer = 0.0

        # Animation & Juice
        self.current_anim = "Idle"
        self.frame_index = 0.0
        self.white_flash_timer = 0.0
        self.hurt_timer = 0.0
        self.death_timer = 0.0
        self.is_dead = False
        self.remove_ready = False
        self.knock_vx = 0.0
        self.knock_vy = 0.0

        # Group slot allocation
        self.group_slot_angle = None
        self.orbit_dist = None

        # Buffs / Modifiers
        self.speed_mult = 1.0
        self.damage_mult = 1.0

        # Intelligent Pathfinding & Route Planning
        self.waypoints = []
        self.path_target = None
        self.path_replan_timer = -999.0
        self.can_fly = False
        self.can_swim = False

        # Death & Swimming Animation Attributes
        self.death_total_dur = 1.1
        self.is_in_water = False
        self.water_bob_phase = random.uniform(0, 6.28)

    def can_see_player(self, S, px, py):
        """Perception 2.0 sight calculation."""
        dist = math.hypot(px - self.gx, py - self.gy)
        if dist > self.sight_radius:
            return False

        # Special tremor sensing for Golem (ground vibration 360 within 3.0 tiles)
        if getattr(self, "tremor_sensing", False) and dist <= 3.0:
            return True

        # Angle check against facing heading
        angle_to_p = math.atan2(py - self.gy, px - self.gx)
        diff = abs((angle_to_p - self.facing_angle + math.pi) % (2 * math.pi) - math.pi)
        half_cone = math.radians(self.sight_cone_deg / 2.0)
        return diff <= half_cone

    def check_noise_pings(self, S, now):
        """Check if any loud action pulls the enemy in without line of sight."""
        if self.state in (STATE_IDLE, STATE_INVESTIGATE):
            pings = getattr(S, "noise_pings", [])
            for np in pings:
                d = math.hypot(np["x"] - self.gx, np["y"] - self.gy)
                if d <= np["radius"]:
                    self.investigate_pos = (np["x"], np["y"])
                    self.facing_angle = math.atan2(np["y"] - self.gy, np["x"] - self.gx)
                    self.facing_left = (np["x"] < self.gx)
                    self.state = STATE_ALERT
                    self.alert_timer = self.alert_dur * 0.6
                    self.current_anim = "Idle"
                    break

    def update_poise_and_stagger(self, dt, now):
        """Handle stagger duration and poise regeneration."""
        if self.state == STATE_STAGGERED:
            self.stagger_timer -= dt
            if self.stagger_timer <= 0:
                self.current_poise = self.max_poise
                self.state = STATE_IDLE
                self.current_anim = "Idle"
        else:
            if (now - self.last_poise_hit_time >= 1.75) and (self.current_poise < self.max_poise):
                regen_rate = (self.max_poise / 1.5) * dt
                self.current_poise = min(self.max_poise, self.current_poise + regen_rate)

    def trigger_stagger(self, S):
        """Enter staggered vulnerability state upon poise breaking."""
        self.state = STATE_STAGGERED
        self.stagger_timer = 1.4  # Vulnerability window
        self.current_anim = "Hit" if "Hit" in getattr(self, "SPRITE_CACHE", {}) else "Idle"
        self.frame_index = 0.0

        # Burst of golden stun stars
        if hasattr(S, "particles") and hasattr(S, "iso"):
            try:
                wx, wy = S.iso.world_px(self.gx, self.gy)
                sx, sy = S.iso.to_screen(wx, wy)
                sy -= S.iso.elev(self.gx, self.gy) + 24
                for _ in range(8):
                    ang = random.uniform(0, math.pi * 2)
                    spd = random.uniform(20, 60)
                    S.particles.append({
                        "x": sx, "y": sy,
                        "vx": math.cos(ang) * spd, "vy": math.sin(ang) * spd - 15,
                        "life": random.uniform(0.3, 0.6), "size": 3,
                        "color": (255, 230, 80)
                    })
            except Exception:
                pass

    def apply_damage_and_poise(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        """Standardized damage & poise pipeline."""
        if self.is_dead:
            return

        # Golem resistance: resists light-gun damage (-60%) unless staggered or mid-recover
        if getattr(self, "resists_light_guns", False) and wep_name in ("Gun", "Luger", "M92", "MP5"):
            if self.state not in (STATE_STAGGERED, STATE_RECOVER):
                amount = max(1, int(amount * 0.40))
                # Ricochet spark
                if hasattr(S, "particles") and hasattr(S, "iso"):
                    wx, wy = S.iso.world_px(self.gx, self.gy)
                    sx, sy = S.iso.to_screen(wx, wy)
                    sy -= S.iso.elev(self.gx, self.gy) + 14
                    for _ in range(5):
                        S.particles.append({
                            "x": sx, "y": sy,
                            "vx": random.uniform(-40, 40), "vy": random.uniform(-50, -10),
                            "life": 0.15, "size": 2, "color": (255, 255, 200)
                        })

        # Demon resistance: Infernal Ward absorbs heavy high-caliber single hits (-30%) unless staggered
        if getattr(self, "infernal_ward", False) and wep_name == "M24":
            if self.state not in (STATE_STAGGERED, STATE_RECOVER):
                amount = max(1, int(amount * 0.70))
                # Fiery ward deflection particles
                if hasattr(S, "particles") and hasattr(S, "iso"):
                    wx, wy = S.iso.world_px(self.gx, self.gy)
                    sx, sy = S.iso.to_screen(wx, wy)
                    sy -= S.iso.elev(self.gx, self.gy) + 14
                    for _ in range(5):
                        S.particles.append({
                            "x": sx, "y": sy,
                            "vx": random.uniform(-35, 35), "vy": random.uniform(-45, -15),
                            "life": 0.20, "size": 3, "color": (255, 120, 40)
                        })

        self.hp = max(0, self.hp - amount)
        now = pygame.time.get_ticks() / 1000.0

        # Poise depletion
        self.last_poise_hit_time = now
        self.current_poise = max(0, self.current_poise - poise_dmg)
        if self.current_poise <= 0 and self.state != STATE_STAGGERED:
            self.trigger_stagger(S)
        elif self.state not in (STATE_STAGGERED, STATE_WINDUP, STATE_ATTACK):
            self.white_flash_timer = 0.12
            self.hurt_timer = 0.10
            if self.state != STATE_RETREAT:
                self.state = STATE_HURT
                self.current_anim = "Hit" if "Hit" in getattr(self, "SPRITE_CACHE", {}) else "Idle"

        # Damage popup
        if hasattr(S, "iso"):
            if not hasattr(S, "damage_popups"):
                S.damage_popups = []
            wx, wy = S.iso.world_px(self.gx, self.gy)
            sx, sy = S.iso.to_screen(wx, wy)
            sy -= S.iso.elev(self.gx, self.gy) + 16
            is_crit = amount >= 45
            S.damage_popups.append({
                "x": sx, "y": sy - 10,
                "text": f"-{int(amount)}" if not is_crit else f"CRIT -{int(amount)}!",
                "color": (255, 215, 60) if is_crit else (255, 90, 90),
                "life": 0.85, "max_life": 0.85, "vy": -45, "is_crit": is_crit
            })

        # Death check
        if self.hp <= 0:
            self.hp = 0
            self.is_dead = True
            self.state = STATE_DEATH
            self.current_anim = "Death" if "Death" in getattr(self, "SPRITE_CACHE", {}) else "Idle"
            self.frame_index = 0.0
            self.death_total_dur = 1.15
            self.death_timer = self.death_total_dur
            # Record kill in AI Director
            mgr = getattr(S, "enemy_mgr", None) or getattr(S, "enemy_manager", None)
            if mgr and hasattr(mgr, "record_kill"):
                mgr.record_kill(now)
            self._spawn_loot(S)
            self._spawn_death_particles(S)

    def _spawn_death_particles(self, S):
        """Visceral species-specific death burst."""
        if not hasattr(S, "particles") or not hasattr(S, "iso"):
            return
        wx, wy = S.iso.world_px(self.gx, self.gy)
        sx, sy = S.iso.to_screen(wx, wy)
        sy -= S.iso.elev(self.gx, self.gy) + 10

        cls_name = self.__class__.__name__.lower()
        if "skull" in cls_name:
            colors = [(100, 240, 255), (180, 255, 255), (60, 160, 220)]
        elif "demon" in cls_name:
            colors = [(255, 120, 40), (255, 60, 30), (255, 200, 60), (45, 30, 30)]
        elif "blood" in cls_name:
            colors = [(190, 20, 30), (225, 45, 55), (130, 10, 20)]
        elif "golem" in cls_name:
            colors = [(140, 130, 120), (180, 170, 160), (95, 85, 80)]
        elif "bat" in cls_name:
            colors = [(80, 60, 100), (125, 95, 155), (45, 35, 65)]
        else: # Rat
            colors = [(165, 145, 125), (205, 185, 165), (225, 125, 135)]

        for _ in range(18):
            c = random.choice(colors)
            ang = random.uniform(0, math.pi * 2)
            spd = random.uniform(35, 130)
            S.particles.append({
                "x": sx + random.uniform(-6, 6),
                "y": sy + random.uniform(-6, 6),
                "vx": math.cos(ang) * spd,
                "vy": math.sin(ang) * spd - random.uniform(20, 60),
                "life": random.uniform(0.45, 0.85),
                "color": c
            })

    def navigate_towards(self, S, target_gx, target_gy, dt, speed_override=None):
        """Intelligent route planning: uses raycasts, A* waypoints, and obstacle tangent sliding."""
        now = pygame.time.get_ticks() / 1000.0
        spd = (speed_override if speed_override is not None else self.move_speed) * self.speed_mult

        # Check water status
        if hasattr(S, "iso") and hasattr(S.iso, "is_water"):
            self.is_in_water = S.iso.is_water(self.gx, self.gy) and not self.can_fly
            if self.is_in_water:
                spd *= 0.65  # water wading resistance

        dist_to_goal = math.hypot(target_gx - self.gx, target_gy - self.gy)
        needs_replan = (
            not self.waypoints or
            self.path_target is None or
            math.hypot(self.path_target[0] - target_gx, self.path_target[1] - target_gy) > 1.6 or
            (now - self.path_replan_timer > 0.55)
        )

        if needs_replan and dist_to_goal > 0.35:
            self.path_target = (float(target_gx), float(target_gy))
            self.path_replan_timer = now
            self.waypoints = find_path(
                S, self.gx, self.gy, target_gx, target_gy,
                can_fly=self.can_fly, can_swim=self.can_swim
            )

        # Advance along waypoints
        while self.waypoints:
            wp_x, wp_y = self.waypoints[0]
            if math.hypot(wp_x - self.gx, wp_y - self.gy) < 0.35:
                self.waypoints.pop(0)
            else:
                break

        # Move towards current active waypoint (or direct goal if waypoints exhausted)
        next_x, next_y = self.waypoints[0] if self.waypoints else (target_gx, target_gy)
        dx = next_x - self.gx
        dy = next_y - self.gy
        dist_next = math.hypot(dx, dy)

        if dist_next > 0.05:
            self.facing_angle = math.atan2(dy, dx)
            self.facing_left = (dx < 0)
            self.gx, self.gy = slide_move(
                S, self.gx, self.gy, next_x, next_y, spd, dt,
                can_fly=self.can_fly, can_swim=self.can_swim
            )
            return True
        return False

    def draw_water_ripples(self, S, screen, sx, sy):
        """Render concentric swimming water ripples when submerged."""
        if not self.is_in_water or self.can_fly or self.is_dead:
            return
        t = pygame.time.get_ticks() / 1000.0
        rw = int(14 * S.iso.scale)
        rh = int(7 * S.iso.scale)
        for ring_i in range(2):
            phase = ((t * 1.4 + self.water_bob_phase + ring_i * 0.5) % 1.0)
            cur_w = max(2, int(rw * (0.6 + phase * 0.6)))
            cur_h = max(2, int(rh * (0.6 + phase * 0.6)))
            alpha = int(140 * (1.0 - phase))
            rip_surf = pygame.Surface((cur_w * 2, cur_h * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(rip_surf, (170, 235, 255, alpha), rip_surf.get_rect(), max(1, int(1.5 * S.iso.scale)))
            screen.blit(rip_surf, (int(sx - cur_w), int(sy - cur_h)))

    def _spawn_loot(self, S):
        if not hasattr(S, "dropped_items"):
            S.dropped_items = []
        loot_pool = getattr(self, "LOOT_ITEMS", ["meat", "coal", "iron"])
        loot_type = random.choice(loot_pool)
        S.dropped_items.append({
            "cx": self.gx, "cy": self.gy,
            "type": loot_type,
            "z": 15.0, "vz": random.uniform(140, 220),
            "vx": random.uniform(-1.0, 1.0), "vy": random.uniform(-1.0, 1.0)
        })


    def draw_overlays(self, S, screen, sx, sy, scale_factor=1.0):
        """Render Poise bar, Health bar, Alert indicator, and Stagger stars."""
        # 1. Stagger stars
        if self.state == STATE_STAGGERED:
            t = pygame.time.get_ticks() / 200.0
            for si in range(3):
                sang = t + (si * (2 * math.pi / 3))
                star_x = sx + math.cos(sang) * (12 * S.iso.scale)
                star_y = sy - (32 * S.iso.scale) + math.sin(sang) * (4 * S.iso.scale)
                pygame.draw.circle(screen, (255, 235, 70), (int(star_x), int(star_y)), max(2, int(2.5 * S.iso.scale)))

        # 2. Alert indicator ("!" bubble)
        elif self.state == STATE_ALERT:
            bubble_y = sy - (32 * S.iso.scale)
            pygame.draw.circle(screen, (240, 190, 40), (int(sx), int(bubble_y)), int(6 * S.iso.scale))
            pygame.draw.circle(screen, (20, 20, 20), (int(sx), int(bubble_y)), int(6 * S.iso.scale), 1)
            # exclamation mark
            pygame.draw.line(screen, (20, 20, 20), (int(sx), int(bubble_y - 3 * S.iso.scale)), (int(sx), int(bubble_y + 1 * S.iso.scale)), 2)
            pygame.draw.circle(screen, (20, 20, 20), (int(sx), int(bubble_y + 3 * S.iso.scale)), 1)

        # 3. Windup glint
        elif self.state == STATE_WINDUP:
            bubble_y = sy - (28 * S.iso.scale)
            # Red flash warning
            pygame.draw.circle(screen, (255, 60, 60), (int(sx), int(bubble_y)), int(4 * S.iso.scale))

        # 4. Health & Poise Bars
        if not self.is_dead and (self.hp < self.max_hp or self.current_poise < self.max_poise):
            bar_w = int(18 * S.iso.scale)
            bar_h = 2
            bx = int(sx - bar_w // 2)
            by = int(sy - 21 * S.iso.scale)

            # Health bar (Red/Orange)
            pygame.draw.rect(screen, (30, 30, 30), (bx, by, bar_w, bar_h))
            fill_w = int((self.hp / self.max_hp) * (bar_w - 2))
            if fill_w > 0:
                pygame.draw.rect(screen, (220, 160, 40), (bx + 1, by + 1, fill_w, bar_h - 2))
            pygame.draw.rect(screen, (80, 80, 80), (bx, by, bar_w, bar_h), 1)

            # Poise bar (Cyan / White)
            p_by = by + bar_h + 1
            pygame.draw.rect(screen, (20, 20, 20), (bx, p_by, bar_w, 2))
            p_fill = int((self.current_poise / self.max_poise) * (bar_w - 2))
            if p_fill > 0:
                p_col = (100, 220, 255) if self.state != STATE_STAGGERED else (255, 80, 80)
                pygame.draw.rect(screen, p_col, (bx + 1, p_by + 1, p_fill, 1))
            pygame.draw.rect(screen, (60, 60, 60), (bx, p_by, bar_w, 2), 1)


    def draw_cached_cone(self, S, screen, col, bcol, pts):
        """Zero-allocation perception cone renderer using reusable buffer."""
        if len(pts) <= 2:
            return
        ww, wh = screen.get_size()
        if not hasattr(S, "_cone_scratch") or S._cone_scratch.get_size() != (ww, wh):
            S._cone_scratch = pygame.Surface((ww, wh), pygame.SRCALPHA)
        cone_surf = S._cone_scratch
        cone_surf.fill((0, 0, 0, 0))
        pygame.draw.polygon(cone_surf, col, pts)
        pygame.draw.lines(cone_surf, bcol, True, pts, 2)
        screen.blit(cone_surf, (0, 0))


_SCALED_FRAME_CACHE = {}
def get_scaled_frame(frame, scale_factor, flip_x=False):
    """Zero-allocation sprite transform cache."""
    k = (id(frame), round(scale_factor, 3), flip_x)
    cached = _SCALED_FRAME_CACHE.get(k)
    if cached is not None:
        return cached
    tw = max(1, int(frame.get_width() * scale_factor))
    th = max(1, int(frame.get_height() * scale_factor))
    scaled = pygame.transform.scale(frame, (tw, th))
    if flip_x:
        scaled = pygame.transform.flip(scaled, True, False)
    _SCALED_FRAME_CACHE[k] = scaled
    return scaled


_ENEMY_SHADOW_CACHE = {}
def get_enemy_shadow(sw, sh):
    """Zero-allocation soft contact shadow cache."""
    sw, sh = max(4, int(sw)), max(2, int(sh))
    cached = _ENEMY_SHADOW_CACHE.get((sw, sh))
    if cached is not None:
        return cached
    surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
    # Dual-layer feathered shadow: soft ambient rim + grounded contact core
    pygame.draw.ellipse(surf, (0, 0, 0, 50), (0, 0, sw, sh))
    core_w = max(2, int(sw * 0.72))
    core_h = max(2, int(sh * 0.72))
    cx = (sw - core_w) // 2
    cy = (sh - core_h) // 2
    pygame.draw.ellipse(surf, (0, 0, 0, 90), (cx, cy, core_w, core_h))
    _ENEMY_SHADOW_CACHE[(sw, sh)] = surf
    return surf