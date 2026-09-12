"""
================================================================================
ASHERFALL - UNIFIED ENEMY ECOSYSTEM & AI DIRECTOR (PERCEPTION 2.0)
================================================================================
Consolidates navigation, universal base enemy, all 8 monster classes, and the
adaptive dynamic EnemyManager director into a high-performance unified module.
================================================================================
"""
import math
import random
import os
import sys
import time
import heapq
import collections
from typing import List, Tuple, Dict, Any, Optional
import pygame
import iso

# Register backward-compatible submodule aliases in sys.modules
_mod = sys.modules[__name__]
sys.modules["enemy"] = _mod
sys.modules["enemy.enemy"] = _mod
for _sub in (
    "base", "navigation", "soldier", "orc",
    "skull", "demon", "rat", "bat", "golem",
    "bloodseeker", "enemy"
):
    setattr(_mod, _sub, _mod)
    sys.modules[f"enemy.{_sub}"] = _mod


# ============================================================================
# 1. NAVIGATION & PATHFINDING
# ============================================================================
"""Intelligent A* Pathfinding, Route Planning, and Obstacle Avoidance for Asherfall Enemies.

Provides:
  - Line-of-sight raycasting to bypass searches when direct path is clear (<0.001ms)
  - Fast bounded A* grid search around solid obstacles, props, cliffs, and deep water
  - String-pulling path smoothing (replaces zigzag steps with direct diagonal routes)
  - Tangential obstacle sliding for continuous fluid movement along wall/rock edges
  - Flanking & tactical route divergence based on assigned group slot angles
"""
import math
import heapq
from typing import List, Tuple

# Directions: 4 cardinals (cost 1.0) and 4 diagonals (cost 1.414)
_DIRS = [
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (-1, -1, 1.414)
]


def is_tile_blocked(S, gx: int, gy: int, can_fly: bool = False, can_swim: bool = False) -> bool:
    """Determine if a grid tile blocks movement for the given entity capability."""
    if can_fly:
        # Flying predators (Bat, Skull) glide over terrain props and water freely
        return False

    # Check solid obstacle layer (rocks, trees, boulders, props)
    if hasattr(S, "iso"):
        if S.iso.solid(gx, gy):
            return True
        if not can_swim and hasattr(S.iso, "is_water"):
            # Deep water blocks or severely restricts heavy non-swimming land units
            if S.iso.is_water(gx, gy):
                return True

    return False


def is_line_clear(S, x0: float, y0: float, x1: float, y1: float, can_fly: bool = False, can_swim: bool = False) -> bool:
    """Raycast line-of-sight check between two world points."""
    if can_fly:
        return True

    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy)
    if dist < 0.2:
        return True

    steps = max(2, int(dist * 2.5))
    for i in range(1, steps):
        t = i / float(steps)
        rx = int(round(x0 + dx * t))
        ry = int(round(y0 + dy * t))
        if is_tile_blocked(S, rx, ry, can_fly=can_fly, can_swim=can_swim):
            return False

    return True


def smooth_path(S, path: List[Tuple[float, float]], can_fly: bool = False, can_swim: bool = False) -> List[Tuple[float, float]]:
    """String-pulling post-processor: replaces jagged grid staircases with smooth diagonal waypoints."""
    if not path or len(path) <= 2:
        return path

    smoothed = [path[0]]
    curr = 0
    total = len(path)
    while curr < total - 1:
        furthest = curr + 1
        for check in range(total - 1, curr, -1):
            if is_line_clear(S, path[curr][0], path[curr][1], path[check][0], path[check][1], can_fly, can_swim):
                furthest = check
                break
        smoothed.append(path[furthest])
        curr = furthest

    return smoothed


def find_path(
    S,
    start_gx: float, start_gy: float,
    goal_gx: float, goal_gy: float,
    can_fly: bool = False,
    can_swim: bool = False,
    max_radius: int = 14
) -> List[Tuple[float, float]]:
    """Intelligent A* Route Planner with direct-line fast path, obstacle avoidance, and path smoothing."""
    # 1. Fast Path: Direct unobstructed line of sight (instant 0.001ms return)
    if is_line_clear(S, start_gx, start_gy, goal_gx, goal_gy, can_fly=can_fly, can_swim=can_swim):
        return [(float(goal_gx), float(goal_gy))]

    # 2. Localized A* Grid Search
    sx, sy = int(round(start_gx)), int(round(start_gy))
    gx, gy = int(round(goal_gx)), int(round(goal_gy))

    # Bounding window around combat encounter
    min_x = min(sx, gx) - 4
    max_x = max(sx, gx) + 4
    min_y = min(sy, gy) - 4
    max_y = max(sy, gy) + 4

    start_node = (sx, sy)
    goal_node = (gx, gy)

    open_set: List[Tuple[float, Tuple[int, int]]] = []
    heapq.heappush(open_set, (0.0, start_node))
    came_from = {}
    g_score = {start_node: 0.0}

    def heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    closest_node = start_node
    closest_dist = heuristic(start_node, goal_node)

    iterations = 0
    max_iterations = 180  # Guarantees ultra-low CPU execution under 0.05ms

    while open_set and iterations < max_iterations:
        iterations += 1
        _, current = heapq.heappop(open_set)

        d_goal = heuristic(current, goal_node)
        if d_goal < closest_dist:
            closest_dist = d_goal
            closest_node = current

        if current == goal_node or d_goal <= 1.0:
            closest_node = current
            break

        cx, cy = current
        for dx, dy, cost in _DIRS:
            nx, ny = cx + dx, cy + dy

            # Bounding box clamp
            if nx < min_x or nx > max_x or ny < min_y or ny > max_y:
                continue

            # Diagonal obstacle clearance (prevent cutting through corners of rock blocks)
            if dx != 0 and dy != 0:
                if is_tile_blocked(S, cx + dx, cy, can_fly, can_swim) or is_tile_blocked(S, cx, cy + dy, can_fly, can_swim):
                    continue

            if is_tile_blocked(S, nx, ny, can_fly, can_swim):
                continue

            tentative_g = g_score[current] + cost
            if tentative_g < g_score.get((nx, ny), float("inf")):
                came_from[(nx, ny)] = current
                g_score[(nx, ny)] = tentative_g
                f = tentative_g + heuristic((nx, ny), goal_node)
                heapq.heappush(open_set, (f, (nx, ny)))

    # Reconstruct raw path
    curr = closest_node
    raw_path = [curr]
    while curr in came_from:
        curr = came_from[curr]
        raw_path.append(curr)
    raw_path.reverse()

    # Convert to float tuples and append exact goal coordinates
    float_path = [(float(x), float(y)) for x, y in raw_path]
    if float_path and math.hypot(float_path[-1][0] - goal_gx, float_path[-1][1] - goal_gy) > 0.4:
        float_path.append((float(goal_gx), float(goal_gy)))

    # 3. String-pulling smoothing to eliminate grid artifacts
    return smooth_path(S, float_path, can_fly=can_fly, can_swim=can_swim)


def slide_move(
    S,
    gx: float, gy: float,
    target_gx: float, target_gy: float,
    speed: float, dt: float,
    can_fly: bool = False, can_swim: bool = False
) -> Tuple[float, float]:
    """Applies velocity with tangent obstacle sliding (prevents stopping dead against rock/tree walls)."""
    dx = target_gx - gx
    dy = target_gy - gy
    dist = math.hypot(dx, dy)
    if dist < 0.01:
        return gx, gy

    step = min(dist, speed * dt)
    vx = (dx / dist) * step
    vy = (dy / dist) * step

    if can_fly:
        return gx + vx, gy + vy

    # Test full move
    new_gx = gx + vx
    new_gy = gy + vy
    if not is_tile_blocked(S, int(round(new_gx)), int(round(new_gy)), can_fly, can_swim):
        return new_gx, new_gy

    # Try sliding along X axis
    if not is_tile_blocked(S, int(round(new_gx)), int(round(gy)), can_fly, can_swim):
        return new_gx, gy

    # Try sliding along Y axis
    if not is_tile_blocked(S, int(round(gx)), int(round(new_gy)), can_fly, can_swim):
        return gx, new_gy

    # Tangent perpendicular deflection
    tangent_dx = -dy / dist * step * 0.7
    tangent_dy = dx / dist * step * 0.7
    if not is_tile_blocked(S, int(round(gx + tangent_dx)), int(round(gy + tangent_dy)), can_fly, can_swim):
        return gx + tangent_dx, gy + tangent_dy
    if not is_tile_blocked(S, int(round(gx - tangent_dx)), int(round(gy - tangent_dy)), can_fly, can_swim):
        return gx - tangent_dx, gy - tangent_dy

    return gx, gy


# ============================================================================
# 2. BASE ENEMY & RENDERING UTILITIES
# ============================================================================
import math
import random
import pygame

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

# ============================================================================
# 3. MONSTER CLASSES
# ============================================================================

# --- BAT ---
import math
import os
import random
import pygame

class Bat(BaseEnemy):
    """Flying Bat enemy with Perception 2.0 (220-deg sonar radar),
    aerial standoff orbiting, and Compass Repositioning trick before re-diving."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["meat", "feather", "coal"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=28, max_poise=15,
            windup_dur=0.25, recover_dur=0.30, alert_dur=0.20,
            sight_radius=5.5, sight_cone_deg=220.0,
            attack_radius=0.90, move_speed=2.15
        )
        self.last_scream_time = -999.0
        self.attack_cooldown = 0.95
        self.anim_speeds = {
            "Fly": 9.0,
            "Attack": 12.0,
            "Hit": 10.0,
            "Death": 9.0,
        }
        self.current_anim = "Fly"
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False

        # Bat Trick: Repositioning compass angle & Aerial Flight
        self.can_fly = True
        self.reposition_angle = None
        self.reposition_timer = 0.0
        self.standoff_dist = 3.5

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Bat.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "bat")
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
                    print(f"Error loading bat sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((64, 64), pygame.SRCALPHA)
                pygame.draw.circle(surf, (120, 80, 160), (32, 32), 10)
                frames = [surf]
            return frames

        Bat.SPRITE_CACHE["Idle"] = load_sheet("Bat_Fly.png", 4)
        Bat.SPRITE_CACHE["Fly"] = Bat.SPRITE_CACHE["Idle"]
        Bat.SPRITE_CACHE["Attack"] = load_sheet("Bat_Attack.png", 8)
        Bat.SPRITE_CACHE["Hit"] = load_sheet("Bat_Hit.png", 4)
        Bat.SPRITE_CACHE["Death"] = load_sheet("Bat_Death.png", 8)

    def _play_scream_sfx(self, S, now):
        if now - Bat.GLOBAL_LAST_SCREAM < 3.5 or now - self.last_scream_time < 8.0 or getattr(S, "music_muted", False):
            return
        try:
            if Bat.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    Bat.SCREAM_SOUND = pygame.mixer.Sound(p)
            if Bat.SCREAM_SOUND:
                Bat.SCREAM_SOUND.set_volume(0.25)
                Bat.SCREAM_SOUND.play()
                Bat.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = Bat.SPRITE_CACHE.get(self.current_anim, [])
        speed = self.anim_speeds.get(self.current_anim, 9.0)
        if frames:
            self.frame_index += speed * dt
            if self.frame_index >= len(frames):
                if self.state == STATE_DEATH:
                    self.frame_index = len(frames) - 1
                elif self.state in (STATE_ATTACK, STATE_HURT):
                    self.frame_index = 0.0
                    self.state = STATE_RECOVER
                    self.recover_timer = self.recover_dur
                    self.current_anim = "Fly"
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
                self.current_anim = "Fly"
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

        # RECOVER state: punishable window
        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Fly"
            if self.recover_timer <= 0:
                # Bat trick: pick new compass angle to reposition!
                if target:
                    cur_ang = math.atan2(self.gy - target[1], self.gx - target[0])
                    # Rotate 90 to 180 degrees away to attack from completely different angle
                    self.reposition_angle = (cur_ang + random.uniform(math.radians(90), math.radians(180))) % (2 * math.pi)
                    self.reposition_timer = random.uniform(1.2, 2.0)
                self.state = STATE_CHASE
            return

        # WINDUP state: dive swoop telegraph
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

        # ATTACK state: swooping bite
        if self.state == STATE_ATTACK:
            if not self.has_damaged_in_attack and target and min_dist <= self.attack_radius * 1.5:
                self.has_damaged_in_attack = True
                dmg = int(10 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state: fast 0.2s pause beat
        if self.state == STATE_ALERT:
            self.alert_timer -= dt
            self.current_anim = "Fly"
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
                dx = ix - self.gx
                dy = iy - self.gy
                d = math.hypot(dx, dy)
                if d > 0.4:
                    self.current_anim = "Fly"
                    spd = self.move_speed * 0.8 * dt
                    self.gx += (dx / d) * spd
                    self.gy += (dy / d) * spd
                    self.facing_left = (dx < 0)
                    self.facing_angle = math.atan2(dy, dx)
                else:
                    self.investigate_pos = None
                    self.search_timer = random.uniform(3.0, 4.0)
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
            self.current_anim = "Fly"

            # Repositioning phase: circle around player holding range
            if self.reposition_timer > 0 and self.reposition_angle is not None:
                self.reposition_timer -= dt
                rx = target[0] + math.cos(self.reposition_angle) * self.standoff_dist
                ry = target[1] + math.sin(self.reposition_angle) * self.standoff_dist
                dx = rx - self.gx
                dy = ry - self.gy
                d = math.hypot(dx, dy)
                if d > 0.1:
                    spd = self.move_speed * self.speed_mult * dt
                    self.gx += (dx / d) * spd
                    self.gy += (dy / d) * spd
                    self.facing_left = (dx < 0)
                else:
                    self.reposition_timer = 0.0
                return

            # When ready to strike: swoop in from the newly claimed angle!
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
                # Move directly in to strike
                self.navigate_towards(S, target[0], target[1], dt)
        elif self.state == STATE_CHASE:
            self.state = STATE_INVESTIGATE
            self.investigate_pos = self.last_known_player_pos
            self.search_timer = random.uniform(3.0, 5.0)
        else:
            # Idle aerial hover
            self.state = STATE_IDLE
            self.current_anim = "Fly"
            self.wander_timer -= dt
            if self.wander_timer <= 0:
                self.wander_timer = random.uniform(1.5, 3.5)
                ang = random.uniform(0, math.pi * 2)
                dist = random.uniform(0.8, 2.2)
                self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.1:
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.45)
                else:
                    self.wander_target = None

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 220-degree aerial sonar cone."""
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
        steps = 14
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            csy -= S.iso.elev(c_wx, c_wy)
            pts.append((csx, csy))

        col = (180, 80, 220, 45) if self.alert else (120, 60, 160, 22)
        bcol = (210, 100, 255, 140) if self.alert else (150, 75, 200, 65)
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

        # Hovering shadow or water ripples below
        if hasattr(S, "iso") and hasattr(S.iso, "is_water") and S.iso.is_water(self.gx, self.gy):
            self.draw_water_ripples(S, screen, sx, sy)
        elif not self.is_dead:
            sw, sh = int(16 * S.iso.scale), int(8 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Bat.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.99
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(32 * scale_factor)
            anchor_y = int(32 * scale_factor) + int(10 * S.iso.scale)

            # Death animation sink and fade
            death_sink = 0.0
            death_alpha = 1.0
            if self.is_dead:
                death_prog = 1.0 - max(0.0, min(1.0, self.death_timer / max(0.01, getattr(self, "death_total_dur", 1.0))))
                death_sink = death_prog * (6.0 * S.iso.scale)
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

# --- BLOODSEEKER ---
import math
import os
import random
import pygame

class BloodMonster(BaseEnemy):
    """BloodMonster enemy with Perception 2.0 (100-deg cone),
    and Blood Frenzy trick (+25% spd / -20% atk cd vs target <40% HP or chased 6s+)."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["meat", "blood_vial", "iron_ore"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=75, max_poise=50,
            windup_dur=0.35, recover_dur=0.50, alert_dur=0.40,
            sight_radius=4.2, sight_cone_deg=100.0,
            attack_radius=1.0, move_speed=1.40
        )
        self.last_scream_time = -999.0
        self.base_cooldown = 1.20
        self.attack_cooldown = 1.20
        self.anim_speeds = {
            "Idle": 6.0,
            "Run": 10.0,
            "Attack": 11.0,
            "Hit": 10.0,
            "Death": 8.0,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False

        # Blood Frenzy trick
        self.chase_duration = 0.0
        self.is_frenzy = False

        self._load_all_sprites()

    def _load_all_sprites(self):
        if BloodMonster.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "blood_monster")
        def load_sheet(fname, count, fw=100, fh=100, cols_per_row=8):
            path = os.path.join(folder, fname)
            frames = []
            if os.path.exists(path):
                try:
                    sheet = pygame.image.load(path).convert_alpha()
                    sw, sh = sheet.get_size()
                    for i in range(count):
                        r = i // cols_per_row
                        c = i % cols_per_row
                        x = c * fw
                        y = r * fh
                        if x + fw <= sw and y + fh <= sh:
                            frame = sheet.subsurface((x, y, fw, fh))
                            frames.append(frame)
                except Exception as e:
                    print(f"Error loading bloodmonster sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
                pygame.draw.ellipse(surf, (180, 40, 40), (fw//4, fh//4, fw//2, fh//2))
                frames = [surf]
            return frames

        BloodMonster.SPRITE_CACHE["Idle"] = load_sheet("Blood Monster_A_Idle.png", 6, 100, 100, 6)
        BloodMonster.SPRITE_CACHE["Run"] = load_sheet("Blood Monster_A_Walk.png", 8, 100, 100, 8)
        BloodMonster.SPRITE_CACHE["Attack"] = load_sheet("Blood Monster_A_Attack01.png", 8, 100, 100, 8)
        BloodMonster.SPRITE_CACHE["Hit"] = load_sheet("Blood Monster_A_Hurt.png", 4, 100, 100, 4)
        BloodMonster.SPRITE_CACHE["Death"] = load_sheet("Blood Monster_A_Death.png", 4, 100, 100, 4)

    def _play_scream_sfx(self, S, now):
        if now - BloodMonster.GLOBAL_LAST_SCREAM < 3.5 or now - self.last_scream_time < 8.0 or getattr(S, "music_muted", False):
            return
        try:
            if BloodMonster.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    BloodMonster.SCREAM_SOUND = pygame.mixer.Sound(p)
            if BloodMonster.SCREAM_SOUND:
                BloodMonster.SCREAM_SOUND.set_volume(0.32)
                BloodMonster.SCREAM_SOUND.play()
                BloodMonster.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        frames = BloodMonster.SPRITE_CACHE.get(self.current_anim, [])
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

        # Blood Frenzy check: player HP < 40% OR chased for 6s+
        player_hp = getattr(S, "player_health", 100)
        if self.state == STATE_CHASE:
            self.chase_duration += dt
        else:
            self.chase_duration = max(0.0, self.chase_duration - dt * 0.5)

        self.is_frenzy = (player_hp < 40 or self.chase_duration >= 6.0)
        if self.is_frenzy:
            self.speed_mult = 1.25
            self.attack_cooldown = self.base_cooldown * 0.80
            # Frenzy blood particles
            if hasattr(S, "particles") and hasattr(S, "iso") and random.random() < 0.20:
                wx, wy = S.iso.world_px(self.gx, self.gy)
                sx, sy = S.iso.to_screen(wx, wy)
                sy -= S.iso.elev(self.gx, self.gy)
                S.particles.append({
                    "x": sx + random.uniform(-6, 6), "y": sy + random.uniform(-16, 2),
                    "vx": random.uniform(-20, 20), "vy": random.uniform(-30, -10),
                    "life": 0.25, "size": 2, "color": (220, 30, 30)
                })
        else:
            self.speed_mult = 1.0
            self.attack_cooldown = self.base_cooldown

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
                dmg = int(16 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state
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
                    self.current_anim = "Run"
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
                self.current_anim = "Run"
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
                self.wander_timer = random.uniform(1.5, 4.0)
                ang = random.uniform(0, math.pi * 2)
                dist = random.uniform(0.6, 2.0)
                self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.2:
                    self.current_anim = "Run"
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.45)
                else:
                    self.wander_target = None
                    self.current_anim = "Idle"

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 100-degree vision cone."""
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
        steps = 10
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            csy -= S.iso.elev(c_wx, c_wy)
            pts.append((csx, csy))

        col = (220, 40, 40, 45) if self.alert else (160, 30, 30, 22)
        bcol = (255, 60, 60, 140) if self.alert else (190, 40, 40, 65)
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
            sw, sh = int(18 * S.iso.scale), int(9 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = BloodMonster.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.85
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(frame.get_width() * 0.5 * scale_factor)
            anchor_y = int(frame.get_height() * 0.57 * scale_factor)

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

# --- DEMON ---
import math
import os
import random
import pygame

class Demon(BaseEnemy):
    """Elite Vanguard Demon enemy with Perception 2.0 (100-deg cone),
    and Emboldened Leader Aura trick (+15% dmg, +10% spd to nearby Rats/Bats within 6 tiles)."""

    SPRITE_CACHE = {}
    SCREAM_SOUND = None
    GLOBAL_LAST_SCREAM = -999.0
    LOOT_ITEMS = ["gold_ore", "diamond", "meat"]

    def __init__(self, gx, gy, assets_dir):
        super().__init__(
            gx=gx, gy=gy, assets_dir=assets_dir,
            max_hp=110, max_poise=90,
            windup_dur=0.60, recover_dur=0.80, alert_dur=0.40,
            sight_radius=4.8, sight_cone_deg=100.0,
            attack_radius=1.1, move_speed=1.55
        )
        self.last_scream_time = -999.0
        self.attack_cooldown = 1.35
        self.anim_speeds = {
            "Idle": 6.0,
            "Walk": 8.0,
            "Attack": 10.0,
            "Hit": 10.0,
            "Death": 7.0,
        }
        self.wander_target = None
        self.wander_timer = random.uniform(1.5, 4.0)
        self.alert = False
        self.infernal_ward = True

        self._load_all_sprites()

    def _load_all_sprites(self):
        if Demon.SPRITE_CACHE:
            return
        folder = os.path.join(self.assets_dir, "characters", "demon")
        def load_sheet(fname, count, fw=100, fh=100, cols_per_row=8):
            path = os.path.join(folder, fname)
            frames = []
            if os.path.exists(path):
                try:
                    sheet = pygame.image.load(path).convert_alpha()
                    sw, sh = sheet.get_size()
                    for i in range(count):
                        r = i // cols_per_row
                        c = i % cols_per_row
                        x = c * fw
                        y = r * fh
                        if x + fw <= sw and y + fh <= sh:
                            frame = sheet.subsurface((x, y, fw, fh))
                            frames.append(frame)
                except Exception as e:
                    print(f"Error loading demon sheet {fname}: {e}")
            if not frames:
                surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
                pygame.draw.ellipse(surf, (220, 80, 20), (fw//4, fh//4, fw//2, fh//2))
                frames = [surf]
            return frames

        Demon.SPRITE_CACHE["Idle"] = load_sheet("Demon_A_Idle.png", 6, 100, 100, 6)
        Demon.SPRITE_CACHE["Walk"] = load_sheet("Demon_A_Walk.png", 8, 100, 100, 8)
        Demon.SPRITE_CACHE["Attack"] = load_sheet("Demon_A_Attack01.png", 7, 100, 100, 7)
        Demon.SPRITE_CACHE["Hit"] = load_sheet("Demon_A_Hurt.png", 4, 100, 100, 4)
        Demon.SPRITE_CACHE["Death"] = load_sheet("Demon_A_Death.png", 4, 100, 100, 4)

    def _play_scream_sfx(self, S, now):
        if now - Demon.GLOBAL_LAST_SCREAM < 3.5 or now - self.last_scream_time < 8.0 or getattr(S, "music_muted", False):
            return
        try:
            if Demon.SCREAM_SOUND is None:
                p = os.path.join(self.assets_dir, "audio", "sfx", "scream.mp3")
                if os.path.exists(p):
                    Demon.SCREAM_SOUND = pygame.mixer.Sound(p)
            if Demon.SCREAM_SOUND:
                Demon.SCREAM_SOUND.set_volume(0.35)
                Demon.SCREAM_SOUND.play()
                Demon.GLOBAL_LAST_SCREAM = now
                self.last_scream_time = now
        except Exception:
            pass

    def take_damage(self, S, amount, kdx=0.0, kdy=0.0, poise_dmg=15, wep_name=""):
        self.apply_damage_and_poise(S, amount, kdx, kdy, poise_dmg, wep_name)

    def _apply_emboldened_aura(self, S):
        """Demon Trick: Emboldens nearby Rats and Bats with +15% dmg, +10% spd within 6 tiles."""
        if hasattr(S, "enemy_manager"):
            for e in S.enemy_manager.enemies:
                if not e.is_dead and e.__class__.__name__ in ("Rat", "Bat"):
                    if math.hypot(e.gx - self.gx, e.gy - self.gy) <= 6.0:
                        e.damage_mult = max(e.damage_mult, 1.15)
                        e.speed_mult = max(e.speed_mult, 1.10)

    def update(self, S, dt, now):
        if getattr(self, "white_flash_timer", 0.0) > 0:
            self.white_flash_timer = max(0.0, self.white_flash_timer - dt)

        self.update_poise_and_stagger(dt, now)

        # Apply Emboldened Aura if active and aware
        if not self.is_dead and self.state in (STATE_ALERT, STATE_CHASE, STATE_WINDUP, STATE_ATTACK):
            self._apply_emboldened_aura(S)
            # Aura particles
            if hasattr(S, "particles") and hasattr(S, "iso") and random.random() < 0.25:
                wx, wy = S.iso.world_px(self.gx, self.gy)
                sx, sy = S.iso.to_screen(wx, wy)
                sy -= S.iso.elev(self.gx, self.gy)
                ang = random.uniform(0, math.pi * 2)
                rad = random.uniform(8, 22)
                S.particles.append({
                    "x": sx + math.cos(ang) * rad, "y": sy + math.sin(ang) * (rad * 0.5),
                    "vx": 0, "vy": -random.uniform(15, 35),
                    "life": 0.35, "size": 2, "color": (255, 100, 20)
                })

        frames = Demon.SPRITE_CACHE.get(self.current_anim, [])
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

        # RECOVER state
        if self.state == STATE_RECOVER:
            self.recover_timer -= dt
            self.current_anim = "Idle"
            if self.recover_timer <= 0:
                self.state = STATE_CHASE if can_see else STATE_INVESTIGATE
            return

        # WINDUP state (0.60s heavy windup telegraph)
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
                dmg = int(22 * self.damage_mult)
                if hasattr(S, "player_health"):
                    S.player_health = max(0, S.player_health - dmg)
                    if hasattr(S, "enemy_manager"):
                        S.enemy_manager.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            S.enemy_manager.record_near_death(now)
                S.player_hit_timer = 0.8
            return

        # ALERT state (0.4s pause beat)
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
                    self.navigate_towards(S, ix, iy, dt, speed_override=self.move_speed * 0.70)
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
                    self.recover_timer = 0.25
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
                self.wander_timer = random.uniform(2.0, 4.5)
                ang = random.uniform(0, math.pi * 2)
                dist = random.uniform(0.6, 2.0)
                self.wander_target = (self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            if self.wander_target:
                if math.hypot(self.wander_target[0] - self.gx, self.wander_target[1] - self.gy) > 0.2:
                    self.current_anim = "Walk"
                    self.navigate_towards(S, self.wander_target[0], self.wander_target[1], dt, speed_override=self.move_speed * 0.40)
                else:
                    self.wander_target = None
                    self.current_anim = "Idle"

    def draw_sighting_range(self, S, screen):
        """Perception 2.0: Draw 100-degree demonic vision cone."""
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
        steps = 10
        for i in range(steps + 1):
            ang = (self.facing_angle - half_cone) + (i / steps) * (half_cone * 2.0)
            c_wx = self.gx + math.cos(ang) * self.sight_radius
            c_wy = self.gy + math.sin(ang) * self.sight_radius
            c_px, c_py = S.iso.world_px(c_wx, c_wy)
            csx, csy = S.iso.to_screen(c_px, c_py)
            csy -= S.iso.elev(c_wx, c_wy)
            pts.append((csx, csy))

        col = (255, 120, 20, 45) if self.alert else (190, 70, 15, 22)
        bcol = (255, 150, 40, 140) if self.alert else (210, 90, 25, 65)
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
            sw, sh = int(20 * S.iso.scale), int(10 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Demon.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 0.91
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(frame.get_width() * 0.5 * scale_factor)
            anchor_y = int(frame.get_height() * 0.59 * scale_factor)

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

# --- GOLEM ---
import math
import os
import random
import pygame

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
            sw, sh = int(26 * S.iso.scale), int(13 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Golem.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 1.47
            scaled_frame = get_scaled_frame(frame, scale_factor, self.facing_left)
            anchor_x = int(32 * scale_factor)
            anchor_y = int(46 * scale_factor)

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

# --- ORC ---
import math
import os
import random
import pygame

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
            sw, sh = int(22 * S.iso.scale), int(11 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Orc.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 1.26
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


# --- RAT ---
import math
import os
import random
import pygame

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

# --- SKULL ---
import math
import os
import random
import pygame

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

# --- SOLDIER ---
import math
import os
import random
import pygame

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
            sw, sh = int(20 * S.iso.scale), int(10 * S.iso.scale)
            screen.blit(get_enemy_shadow(sw, sh), (int(sx - sw // 2), int(sy - sh // 2)))

        frames = Soldier.SPRITE_CACHE.get(self.current_anim, [])
        if frames:
            idx = int(self.frame_index) % len(frames)
            frame = frames[idx]
            scale_factor = S.iso.scale * 1.16
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


# ============================================================================
# 4. ENEMY MANAGER & ADAPTIVE PACING DIRECTOR
# ============================================================================
# AI Director Pacing Phases
PHASE_BUILDUP = "BUILDUP"   # Suspense building as player explores
PHASE_PEAK = "PEAK"         # Combat active with engaged threats
PHASE_RELIEF = "RELIEF"     # Respite after clearing combat

def _get_target_player(S):
    """Accurately resolves the active controllable player across local co-op, solo, and network modes."""
    if not S:
        return None
    st = getattr(S, "state", None)
    if st in ("local", 4) and getattr(S, "local_players", None) and len(S.local_players) > 0:
        return S.local_players[0]
    if getattr(S, "local_players", None) and len(S.local_players) > 0 and st not in ("test", 3):
        return S.local_players[0]
    return getattr(S, "me", None)


class EnemyManager:
    """Master AI Director and coordinator for all enemies.
    Features:
      - Player movement direction tracking & forward cone projection (at least 5-6 tiles ahead)
      - Combat intensity & tension-relief pacing (AI Director)
      - Terrain and elevation affinity (bats on cliffs, rats near props, demons on open ground)
      - Dynamic encounter archetypes (solo, rat pack, flier duo, elite vanguard)
      - Emergence particle telegraphing
      - Strict fog-of-war culling and alpha-masked sighting circles
      - Anti-clustering and distant fog despawning
    """

    def __init__(self, assets_dir):
        self.assets_dir = assets_dir
        self.enemies = []
        self.projectiles = []

        # AI Director & Adaptive Pacing (Rolling 60s Performance Score)
        self.director_phase = PHASE_BUILDUP
        self.phase_timer = 0.0
        self.spawn_timer = 0.0
        self.base_spawn_interval = 4.2
        self.spawn_interval = 4.2
        self.max_enemies = 6
        self.relief_duration = 5.0
        self.performance_events = []  # [(timestamp, score_delta)]

        # Movement Tracking
        self.last_player_positions = {}   # {pid: (x, y)}
        self.player_headings = {}         # {pid: float_angle}
        self.smoothed_headings = {}       # {pid: float_angle}

    def record_kill(self, now):
        """Rolling performance: Player kill grants +2.0."""
        self.performance_events.append((now, 2.0))

    def record_player_damage(self, now, dmg):
        """Rolling performance: Taking damage deducts -0.05 per HP."""
        self.performance_events.append((now, -0.05 * dmg))

    def record_near_death(self, now):
        """Rolling performance: Near-death under 20% HP deducts -4.0."""
        self.performance_events.append((now, -4.0))

    # --- Spawning Constructors ---
    def spawn_blood_monster(self, gx, gy):
        monster = BloodMonster(gx, gy, self.assets_dir)
        self.enemies.append(monster)
        return monster

    def spawn_demon(self, gx, gy):
        demon = Demon(gx, gy, self.assets_dir)
        self.enemies.append(demon)
        return demon

    def spawn_skull(self, gx, gy):
        skull = Skull(gx, gy, self.assets_dir)
        self.enemies.append(skull)
        return skull

    def spawn_rat(self, gx, gy):
        rat = Rat(gx, gy, self.assets_dir)
        self.enemies.append(rat)
        return rat

    def spawn_bat(self, gx, gy):
        bat = Bat(gx, gy, self.assets_dir)
        self.enemies.append(bat)
        return bat

    def spawn_golem(self, gx, gy):
        golem = Golem(gx, gy, self.assets_dir)
        self.enemies.append(golem)
        return golem

    def spawn_soldier(self, gx, gy):
        soldier = Soldier(gx, gy, self.assets_dir)
        self.enemies.append(soldier)
        return soldier

    def spawn_orc(self, gx, gy):
        orc = Orc(gx, gy, self.assets_dir)
        self.enemies.append(orc)
        return orc

    def _spawn_by_type(self, mtype, gx, gy, S=None):
        """Instantiate monster by string identifier with emergence VFX."""
        enemy = None
        if mtype == "soldier":
            enemy = self.spawn_soldier(gx, gy)
        elif mtype == "orc":
            enemy = self.spawn_orc(gx, gy)
        elif mtype == "skull":
            enemy = self.spawn_skull(gx, gy)
        elif mtype == "demon":
            enemy = self.spawn_demon(gx, gy)
        elif mtype == "rat":
            enemy = self.spawn_rat(gx, gy)
        elif mtype == "bat":
            enemy = self.spawn_bat(gx, gy)
        elif mtype == "golem":
            enemy = self.spawn_golem(gx, gy)
        else:
            enemy = self.spawn_blood_monster(gx, gy)

        # Subtle emergence ground particles
        if S and hasattr(S, "particles") and hasattr(S, "iso") and enemy:
            try:
                wx, wy = S.iso.world_px(gx, gy)
                sx, sy = S.iso.to_screen(wx, wy)
                sy -= S.iso.elev(gx, gy)
                color = (180, 200, 230) if mtype == "soldier" else ((70, 130, 70) if mtype == "orc" else ((160, 140, 110) if mtype == "golem" else ((70, 60, 50) if mtype in ("rat", "blood") else (130, 80, 160))))
                for _ in range(5):
                    S.particles.append({
                        "x": sx + random.uniform(-6, 6),
                        "y": sy + random.uniform(-6, 4),
                        "vx": random.uniform(-30, 30),
                        "vy": random.uniform(-40, -10),
                        "life": random.uniform(0.2, 0.4),
                        "color": color
                    })
            except Exception:
                pass

        # Fresh spawns begin in STATE_IDLE to honor Perception 2.0 (sight cones, alert beats, and noise pings)
        if enemy:
            enemy.state = "IDLE"
            enemy.investigate_pos = None

        return enemy

    # --- Terrain-Aware Enemy Selection ---
    def _pick_terrain_affinity_type(self, S, gx, gy):
        """Select an enemy type suited to the local terrain and elevation."""
        level = 0
        has_prop = False
        if hasattr(S, "iso") and hasattr(S.iso, "world"):
            try:
                _, prop, level = S.iso.world.get(round(gx), round(gy))
                has_prop = (prop is not None)
            except Exception:
                pass

        # Types: ["soldier", "orc", "blood", "demon", "skull", "rat", "bat", "golem"]
        types = ["soldier", "orc", "blood", "demon", "skull", "rat", "bat", "golem"]
        if level >= 2:  # High cliffs / peaks: favored by airborne bats, skulls, archer soldiers
            weights = [20, 10, 10, 10, 25, 5, 15, 10]
        elif has_prop:  # Rocky / wooded terrain: favored by orcs, soldiers, golems, rats
            weights = [22, 22, 12, 10, 8, 16, 8, 14]
        else:           # Open flat terrain: favored by patrol soldiers, orcs, demons, bloodseekers
            weights = [25, 20, 15, 18, 8, 10, 4, 10]

        return random.choices(types, weights=weights, k=1)[0]

    # --- Intelligent Directional Spawner ---
    def try_directional_spawn(self, S, px, py, heading):
        """AI Director spawning algorithm:
        1. Validates combat intensity and director pacing.
        2. Samples forward candidate sectors 5.2 to 6.8 tiles ahead in movement direction.
        3. Validates line of sight, non-solid ground, and anti-clustering.
        4. Selects tactical encounter archetype (solo, rat pack, flier duo, elite squad).
        """
        # Combat Intensity Check:
        player_hp = getattr(S, "player_health", 100)
        active_threats = sum(1 for e in self.enemies if not e.is_dead and e.state in ("CHASE", "ATTACK"))
        if player_hp < 30 and active_threats >= 2:
            return None
        if active_threats >= 3:
            return None

        # Randomizer Step 1: Decision on spawn roll
        spawn_chance = 0.70 if len(self.enemies) == 0 else (0.35 if self.director_phase == PHASE_RELIEF else 0.55)
        if random.random() > spawn_chance:
            return None

        # Randomizer Step 2: Select candidate tile 4.5 - 6.2 tiles ahead in movement direction
        candidate_tiles = []
        for _ in range(16):
            dist = random.uniform(4.5, 6.2)
            cone_offset = random.uniform(-math.radians(50), math.radians(50))
            cand_ang = heading + cone_offset
            cand_x = px + math.cos(cand_ang) * dist
            cand_y = py + math.sin(cand_ang) * dist

            fx, fy = S.iso.find_free(cand_x, cand_y, radius=2)
            d_from_p = math.hypot(fx - px, fy - py)

            if d_from_p >= 4.0 and not S.iso.solid(fx, fy):
                too_close = False
                for existing in self.enemies:
                    if not existing.is_dead and math.hypot(existing.gx - fx, existing.gy - fy) < 1.6:
                        too_close = True
                        break
                if not too_close:
                    candidate_tiles.append((fx, fy))

        # Fallback: if directional cone had no valid tiles, sample around player
        if not candidate_tiles:
            for _ in range(12):
                rand_ang = random.uniform(0, math.pi * 2)
                cand_x = px + math.cos(rand_ang) * random.uniform(4.2, 5.5)
                cand_y = py + math.sin(rand_ang) * random.uniform(4.2, 5.5)
                fx, fy = S.iso.find_free(cand_x, cand_y, radius=2)
                if math.hypot(fx - px, fy - py) >= 3.8 and not S.iso.solid(fx, fy):
                    candidate_tiles.append((fx, fy))

        if not candidate_tiles:
            return None

        # Randomizer selects primary tile from valid candidates
        chosen_x, chosen_y = random.choice(candidate_tiles)

        # Randomizer Step 3: Choose Encounter Archetype
        # Archetypes: 'solo' (50%), 'rat_pack' (20%), 'flier_duo' (15%), 'elite_squad' (15%)
        # Pack archetypes only spawn if enemy cap has enough space
        free_slots = self.max_enemies - len(self.enemies)
        archetypes = ["solo"]
        if free_slots >= 2:
            archetypes.extend(["rat_pack", "flier_duo", "elite_squad"])

        chosen_archetype = random.choice(archetypes)

        if chosen_archetype == "rat_pack" and free_slots >= 2:
            # Scurrying pair of rats
            e1 = self._spawn_by_type("rat", chosen_x, chosen_y, S)
            ox, oy = S.iso.find_free(chosen_x + random.choice([-2.0, 2.0]), chosen_y + random.choice([-2.0, 2.0]), radius=2)
            if math.hypot(ox - px, oy - py) >= 5.0 and not S.iso.solid(ox, oy) and math.hypot(ox - chosen_x, oy - chosen_y) >= 1.8:
                self._spawn_by_type("rat", ox, oy, S)
            return e1

        elif chosen_archetype == "flier_duo" and free_slots >= 2:
            # Pair of aerial predators (Bats / Skulls)
            f1_type = random.choice(["bat", "skull"])
            f2_type = "bat" if f1_type == "skull" else random.choice(["bat", "skull"])
            e1 = self._spawn_by_type(f1_type, chosen_x, chosen_y, S)
            ox, oy = S.iso.find_free(chosen_x + random.choice([-2.0, 2.0]), chosen_y + random.choice([-2.0, 2.0]), radius=2)
            if math.hypot(ox - px, oy - py) >= 5.0 and not S.iso.solid(ox, oy) and math.hypot(ox - chosen_x, oy - chosen_y) >= 1.8:
                self._spawn_by_type(f2_type, ox, oy, S)
            return e1

        elif chosen_archetype == "elite_squad" and free_slots >= 2:
            # Heavy bruiser + scout vanguard
            bruiser = random.choice(["demon", "blood", "golem"])
            scout = random.choice(["skull", "rat"])
            e1 = self._spawn_by_type(bruiser, chosen_x, chosen_y, S)
            ox, oy = S.iso.find_free(chosen_x + random.choice([-2.2, 2.2]), chosen_y + random.choice([-2.2, 2.2]), radius=2)
            if math.hypot(ox - px, oy - py) >= 5.0 and not S.iso.solid(ox, oy) and math.hypot(ox - chosen_x, oy - chosen_y) >= 1.8:
                self._spawn_by_type(scout, ox, oy, S)
            return e1

        else:
            # Solo encounter tailored to terrain
            mtype = self._pick_terrain_affinity_type(S, chosen_x, chosen_y)
            return self._spawn_by_type(mtype, chosen_x, chosen_y, S)

    def spawn_initial_encounters(self, S, cx, cy, count=4):
        """Populates the initial world around the player with engaging monster encounters."""
        types = ["soldier", "orc", "blood", "rat", "demon", "skull", "golem", "bat"]
        for _ in range(count):
            ang = random.uniform(0, math.pi * 2)
            dist = random.uniform(5.5, 9.5)
            gx = cx + math.cos(ang) * dist
            gy = cy + math.sin(ang) * dist
            if hasattr(S, "iso") and hasattr(S.iso, "find_free"):
                fx, fy = S.iso.find_free(gx, gy, radius=2)
                if not S.iso.solid(fx, fy):
                    mtype = random.choice(types)
                    self._spawn_by_type(mtype, fx, fy, S)

    def spawn_wave(self, S, count=2):
        """Spawn enemies using directional player heading if available, or forward sector."""
        target_p = _get_target_player(S)
        if not target_p:
            return

        base_heading = self.smoothed_headings.get("p0", self.player_headings.get("p0", getattr(S, "aim_angle", 0.0)))
        for _ in range(count):
            self.try_directional_spawn(S, target_p[0], target_p[1], base_heading)

    def update(self, S, dt, now):
        # 1. Update AI Director Pacing & Adaptive Performance Score (Rolling 60s)
        self.phase_timer += dt
        self.performance_events = [(t, s) for t, s in self.performance_events if now - t <= 60.0]
        perf_score = sum(s for _, s in self.performance_events)

        if perf_score > 5.0:  # Cruising
            self.spawn_interval = self.base_spawn_interval * 0.80  # 20% faster
            self.max_enemies = 8   # Controlled challenge
            self.relief_duration = 4.0
        elif perf_score < -5.0:  # Struggling
            self.spawn_interval = self.base_spawn_interval * 1.35  # 35% slower
            self.max_enemies = 4   # Low pressure
            self.relief_duration = 9.0
        else:  # Balanced
            self.spawn_interval = self.base_spawn_interval
            self.max_enemies = 6
            self.relief_duration = 5.0

        active_threats = sum(1 for e in self.enemies if not e.is_dead and e.state in ("CHASE", "ATTACK", "WINDUP", "ALERT"))

        if active_threats > 0:
            self.director_phase = PHASE_PEAK
        elif self.director_phase == PHASE_PEAK and active_threats == 0:
            # Combat just ended -> brief relief phase
            self.director_phase = PHASE_RELIEF
            self.phase_timer = 0.0
        elif self.director_phase == PHASE_RELIEF and self.phase_timer > self.relief_duration:
            # Relief period ended -> back to buildup
            self.director_phase = PHASE_BUILDUP
            self.phase_timer = 0.0

        # Clean up noise pings older than 0.6s
        if hasattr(S, "noise_pings"):
            S.noise_pings = [np for np in S.noise_pings if now - np.get("time", 0.0) < 0.6]

        # Group positioning: claim separate angles around player
        target_p = _get_target_player(S)
        if target_p:
            targeting_enemies = [e for e in self.enemies if not e.is_dead and e.state in ("ALERT", "CHASE", "WINDUP", "ATTACK")]
            if len(targeting_enemies) >= 2:
                step_ang = (2.0 * math.pi) / len(targeting_enemies)
                for i, e in enumerate(targeting_enemies):
                    e.group_slot_angle = (i * step_ang) + (now * 0.20)
            else:
                for e in self.enemies:
                    e.group_slot_angle = None

        # 2. Track player positions and movement directions
        players = []
        if getattr(S, "state", "") in ("local", 4) and getattr(S, "local_players", None):
            for i, p in enumerate(S.local_players):
                players.append((f"p{i}", p[0], p[1]))
        elif getattr(S, "me", None):
            players.append(("p0", S.me[0], S.me[1]))

        moving_players = []
        for pid, px, py in players:
            last = self.last_player_positions.get(pid)
            if last is not None and dt > 0:
                dx = px - last[0]
                dy = py - last[1]
                dist_moved = math.hypot(dx, dy)
                speed = dist_moved / dt
                if speed > 0.8 and dist_moved > 0.01:
                    raw_heading = math.atan2(dy, dx)
                    self.player_headings[pid] = raw_heading

                    # Smooth heading to filter momentary jitter
                    prev_smooth = self.smoothed_headings.get(pid, raw_heading)
                    angle_diff = (raw_heading - prev_smooth + math.pi) % (2 * math.pi) - math.pi
                    smooth_h = prev_smooth + angle_diff * min(1.0, 8.0 * dt)
                    self.smoothed_headings[pid] = smooth_h

                    moving_players.append((px, py, smooth_h))
            self.last_player_positions[pid] = (px, py)

        # 3. Continuous spawning: runs whether player is sprinting, walking, or stationary
        if getattr(S, "state", "") in ("test", "local", 2, 3, 4):
            self.spawn_timer += dt
            interval = 2.5 if len(self.enemies) == 0 else (self.spawn_interval if self.director_phase != PHASE_RELIEF else (self.spawn_interval * 1.4))
            if self.spawn_timer >= interval:
                self.spawn_timer = 0.0
                if len(self.enemies) < self.max_enemies and players:
                    if moving_players:
                        mpx, mpy, mheading = random.choice(moving_players)
                    else:
                        target = random.choice(players)
                        mpx, mpy = target[1], target[2]
                        mheading = getattr(S, "aim_angle", random.uniform(0, math.pi * 2))
                    self.try_directional_spawn(S, mpx, mpy, mheading)

        # 4. Clean up distant fog wanderers (> 13.0 tiles) & direct idle enemies to stalk player
        if players:
            for e in self.enemies:
                if not e.is_dead:
                    min_dist_to_player = min(math.hypot(e.gx - px, e.gy - py) for _, px, py in players)
                    if min_dist_to_player > 13.0:
                        e.remove_ready = True

        # 5. Update each active enemy
        if not hasattr(S, "particles"):
            S.particles = []
        vis = getattr(S, "vis_cells", None)

        for e in self.enemies:
            old_gx, old_gy = e.gx, e.gy
            e.update(S, dt, now)

            # Physics-driven knockback velocity and momentum deceleration
            kvx = getattr(e, "knock_vx", 0.0)
            kvy = getattr(e, "knock_vy", 0.0)
            if abs(kvx) > 0.02 or abs(kvy) > 0.02:
                ngx = e.gx + kvx * dt
                ngy = e.gy + kvy * dt
                try:
                    cell = S.iso.world.get(int(round(ngx)), int(round(ngy)))
                    is_solid = S.iso.solid(int(round(ngx)), int(round(ngy))) if cell else False
                except Exception:
                    is_solid = False
                if not is_solid:
                    e.gx = ngx
                    e.gy = ngy
                else:
                    e.knock_vx = -kvx * 0.35
                    e.knock_vy = -kvy * 0.35
                drag = math.exp(-8.5 * dt)
                e.knock_vx *= drag
                e.knock_vy *= drag

            # Walking / movement particles for all monsters
            moved = math.hypot(e.gx - old_gx, e.gy - old_gy)
            if moved > 0.002 and not e.is_dead:
                if vis is not None and (int(round(e.gx)), int(round(e.gy))) not in vis:
                    continue
                e.walk_timer = getattr(e, "walk_timer", 0.0) - dt
                if e.walk_timer <= 0:
                    e.walk_timer = 0.12
                    wx, wy = S.iso.world_px(e.gx, e.gy)
                    sx, sy = S.iso.to_screen(wx, wy)
                    sy -= S.iso.elev(e.gx, e.gy)

                    ename = e.__class__.__name__
                    if ename == "Rat":
                        p_cols = [(125, 110, 95), (105, 95, 80), (150, 135, 120)]
                        vy_base = -random.uniform(6, 18)
                        sz = random.randint(2, 3)
                    elif ename == "Bat":
                        p_cols = [(115, 70, 140), (145, 85, 170), (75, 45, 95)]
                        vy_base = -random.uniform(4, 15)
                        sz = random.randint(2, 3)
                    elif ename == "BloodMonster":
                        p_cols = [(165, 35, 35), (115, 25, 25), (75, 20, 20), (195, 45, 45)]
                        vy_base = -random.uniform(10, 26)
                        sz = random.randint(2, 4)
                    elif ename == "Demon":
                        p_cols = [(255, 125, 30), (255, 75, 20), (65, 50, 50), (235, 180, 45)]
                        vy_base = -random.uniform(18, 40)
                        sz = random.randint(2, 4)
                    elif ename == "Skull":
                        p_cols = [(90, 220, 255), (50, 180, 240), (180, 245, 255)]
                        vy_base = -random.uniform(5, 16)
                        sz = random.randint(2, 3)
                    elif ename == "Golem":
                        p_cols = [(155, 145, 135), (120, 115, 110), (185, 175, 165)]
                        vy_base = -random.uniform(12, 30)
                        sz = random.randint(3, 5)
                    elif ename == "Orc":
                        p_cols = [(90, 80, 60), (70, 95, 55), (110, 90, 70)]
                        vy_base = -random.uniform(14, 28)
                        sz = random.randint(3, 4)
                    elif ename == "Soldier":
                        p_cols = [(160, 150, 140), (130, 120, 110), (190, 185, 175)]
                        vy_base = -random.uniform(8, 20)
                        sz = random.randint(2, 3)
                    else:
                        p_cols = [(160, 150, 135), (130, 120, 110)]
                        vy_base = -random.uniform(8, 22)
                        sz = random.randint(2, 3)

                    # Check if enemy is wading through water
                    cell = S.iso.world.get(round(e.gx), round(e.gy)) if hasattr(S, "iso") and S.iso else None
                    if cell and hasattr(iso, "ALL_WATER_TILES") and cell[0] in iso.ALL_WATER_TILES:
                        p_cols = [(180, 230, 255), (140, 205, 255), (255, 255, 255), (100, 180, 240)]
                        vy_base = -random.uniform(12, 26)

                    for _ in range(random.randint(1, 2)):
                        S.particles.append({
                            "x": sx + random.uniform(-4, 4),
                            "y": sy + random.uniform(-2, 1),
                            "vx": -(e.gx - old_gx) * 70 + random.uniform(-8, 8),
                            "vy": vy_base,
                            "life": random.uniform(0.2, 0.35),
                            "size": sz,
                            "color": random.choice(p_cols)
                        })

        # 6. Check bullet collisions with enemies
        if hasattr(S, "bullets") and S.bullets:
            surviving_bullets = []
            for b in S.bullets:
                bullet_consumed = False
                bx = b.get("wx", 0.0)
                by = b.get("wy", 0.0)
                cx, cy = S.iso.cell_at(bx, by) if abs(bx) > 50 else (bx, by)

                for e in self.enemies:
                    if e.is_dead:
                        continue
                    dist = math.hypot(e.gx - cx, e.gy - cy)
                    if dist < 1.15:
                        # Direct hit!
                        damage = b.get("damage", 25)
                        vx = b.get("vx", 0.0)
                        vy = b.get("vy", 0.0)
                        vlen = math.hypot(vx, vy)
                        kdx = (vx / vlen) if vlen > 0.1 else 0.0
                        kdy = (vy / vlen) if vlen > 0.1 else 0.0

                        if hasattr(S, "play_bullet_sfx"):
                            S.play_bullet_sfx()
                        e.knock_vx = kdx * 7.5
                        wep_name = b.get("wep_name", "")
                        poise_dmg = b.get("poise_dmg", 8)
                        e.take_damage(S, damage, kdx, kdy, poise_dmg=poise_dmg, wep_name=wep_name)
                        # Reduced screenshake scaled minimally with projectile impact
                        hit_shake = min(0.20, max(0.02, damage * 0.0018))
                        S.shake = max(getattr(S, "shake", 0.0), hit_shake)
                        bullet_consumed = True
                        break

                if not bullet_consumed:
                    surviving_bullets.append(b)
            S.bullets = surviving_bullets

        # 7. Check player melee attack hitting enemies
        is_spinning = getattr(S, "tool_spin_active", False)
        is_pressing = getattr(S, "pressing", False)
        if is_pressing or is_spinning:
            my_weapon = getattr(S, "my_weapon", "AK47")
            is_melee = my_weapon in ["Sword", "Axe", "Pickaxe", "Shovel", "Fishing_rod", "Hammer", "Scythe", "Mallet"]
            if is_melee:
                from weapons import WEAPONS
                wep = WEAPONS.get(my_weapon)
                wep_dmg = getattr(wep, "damage", 35) if wep else 35
                # Significantly enlarged hitbox for Sword and tools
                if my_weapon == "Sword":
                    wep_reach = 2.85  # Huge reach requested by user
                    base_dmg = int(wep_dmg * 1.3)
                elif my_weapon in ("Axe", "Hammer"):
                    wep_reach = 2.45
                    base_dmg = int(wep_dmg * 1.15)
                else:
                    wep_reach = 2.2
                    base_dmg = wep_dmg

                target_p = _get_target_player(S)
                if target_p:
                    aim = getattr(S, "aim_angle", 0.0)
                    px, py = target_p[0], target_p[1]
                    psx, psy = S.iso.to_screen(*S.iso.world_px(px, py))
                    psy -= S.iso.elev(px, py) + 14

                    for e in self.enemies:
                        if e.is_dead:
                            continue
                        dist = math.hypot(e.gx - px, e.gy - py)
                        if dist <= wep_reach:
                            can_hit = False
                            if is_spinning:
                                # During 360 degree spin around the player:
                                # Hits all enemies within the orbital reach circle!
                                if not hasattr(S, "tool_spin_hits"):
                                    S.tool_spin_hits = set()
                                if id(e) not in S.tool_spin_hits:
                                    can_hit = True
                                    S.tool_spin_hits.add(id(e))
                            else:
                                ex_px, ey_px = S.iso.world_px(e.gx, e.gy)
                                esx, esy = S.iso.to_screen(ex_px, ey_px)
                                esy -= S.iso.elev(e.gx, e.gy) + 14
                                screen_ang_to_e = math.atan2(esy - psy, esx - psx)
                                diff = abs((screen_ang_to_e - aim + math.pi) % (2 * math.pi) - math.pi)
                                if (diff < 1.95 or dist <= 1.45) and getattr(e, "hurt_timer", 0) <= 0.05:
                                    can_hit = True

                            if can_hit and getattr(e, "hurt_timer", 0) <= 0.08:
                                # Outward radial launch impulse vector
                                kx = (e.gx - px) / max(0.01, dist)
                                ky = (e.gy - py) / max(0.01, dist)
                                
                                impulse = 12.0 if my_weapon == "Sword" else (14.0 if my_weapon == "Hammer" else 10.0)
                                e.knock_vx = kx * impulse
                                e.knock_vy = ky * impulse
                                poise_dmg = 40 if my_weapon == "Hammer" else (25 if my_weapon == "Sword" else (20 if my_weapon in ("Axe", "Pickaxe") else 15))
                                e.take_damage(S, base_dmg, kx, ky, poise_dmg=poise_dmg, wep_name=my_weapon)
                                
                                # Visual and tactile juice!
                                ex_px, ey_px = S.iso.world_px(e.gx, e.gy)
                                esx, esy = S.iso.to_screen(ex_px, ey_px)
                                esy -= S.iso.elev(e.gx, e.gy) + 14

                                # Directional slash line particle
                                S.particles.append({
                                    "x": esx, "y": esy, "vx": 0, "vy": -10,
                                    "life": 0.16, "size": 24, "is_slash": True,
                                    "angle": aim + math.pi / 4,
                                    "color": (255, 255, 255)
                                })
                                
                                # Starburst impact sparks
                                for _ in range(12):
                                    sp_ang = random.uniform(0, math.pi * 2)
                                    sp_spd = random.uniform(80, 200)
                                    S.particles.append({
                                        "x": esx + random.uniform(-4, 4),
                                        "y": esy + random.uniform(-4, 4),
                                        "vx": math.cos(sp_ang) * sp_spd,
                                        "vy": math.sin(sp_ang) * sp_spd - 30,
                                        "life": random.uniform(0.18, 0.35),
                                        "size": random.randint(2, 4),
                                        "color": random.choice([(255, 255, 255), (140, 230, 255), (90, 180, 255), (255, 220, 100)])
                                    })
                                
                                # Audio feedback
                                try:
                                    from game import play_sfx
                                    play_sfx(S, "hit_slice", 0.7)
                                except Exception:
                                    pass

                                # Hitstop micro-pause (screenshake removed for tools+sword)
                                S.hitstop_timer = 0.035

        # 7.5 Update enemy projectiles (e.g. Soldier archery arrows)
        surviving_proj = []
        for proj in getattr(self, "projectiles", []):
            proj["life"] -= dt
            if proj["life"] <= 0:
                continue
            proj["gx"] += proj["vx"] * dt
            proj["gy"] += proj["vy"] * dt

            # World tile obstacle collision
            igx, igy = int(round(proj["gx"])), int(round(proj["gy"]))
            if hasattr(S, "iso") and S.iso.solid(igx, igy):
                if hasattr(S, "particles"):
                    wx, wy = S.iso.world_px(proj["gx"], proj["gy"])
                    sx, sy = S.iso.to_screen(wx, wy)
                    try:
                        sy -= S.iso.elev(proj["gx"], proj["gy"])
                    except Exception:
                        pass
                    for _ in range(6):
                        S.particles.append({
                            "x": sx + random.uniform(-4, 4),
                            "y": sy + random.uniform(-4, 4),
                            "vx": random.uniform(-40, 40),
                            "vy": random.uniform(-50, -10),
                            "life": 0.22,
                            "size": 2,
                            "color": random.choice([(140, 110, 70), (180, 180, 190), (90, 70, 50)])
                        })
                continue

            # Player collision
            hit_player = False
            for _, px, py in players:
                p_dist = math.hypot(px - proj["gx"], py - proj["gy"])
                if p_dist < 0.65:
                    hit_player = True
                    dmg = proj.get("damage", 16)
                    if hasattr(S, "player_health"):
                        S.player_health = max(0, S.player_health - dmg)
                        self.record_player_damage(now, dmg)
                        if S.player_health <= 20:
                            self.record_near_death(now)
                    S.player_hit_timer = 0.7
                    S.shake = max(getattr(S, "shake", 0.0), 0.12)

                    if hasattr(S, "damage_popups") and hasattr(S, "iso"):
                        wx, wy = S.iso.world_px(px, py)
                        sx, sy = S.iso.to_screen(wx, wy)
                        try:
                            sy -= S.iso.elev(px, py)
                        except Exception:
                            pass
                        S.damage_popups.append({
                            "x": sx, "y": sy - 30, "text": f"-{dmg}",
                            "color": (255, 60, 60), "life": 1.0, "max_life": 1.0, "vy": -35.0
                        })
                    break

            if not hit_player:
                surviving_proj.append(proj)
        self.projectiles = surviving_proj

        # 8. Filter out despawned/decayed enemies
        self.enemies = [e for e in self.enemies if not e.remove_ready]

    @staticmethod
    def is_in_view(e, vis):
        if vis is None:
            return True
        return (int(round(e.gx)), int(round(e.gy))) in vis

    def draw_sighting_ranges(self, S, screen):
        """Hidden hitboxes/sighting cones."""
        pass

    def draw(self, S, screen):
        """Draw enemies sorted with isometric depth, strictly culled if outside view range."""
        vis = getattr(S, "vis_cells", None)
        for e in sorted(self.enemies, key=lambda en: en.gx + en.gy):
            if vis is not None and not self.is_in_view(e, vis):
                continue
            e.draw(S, screen)

        # Draw enemy arrows / projectiles
        for proj in getattr(self, "projectiles", []):
            wx, wy = S.iso.world_px(proj["gx"], proj["gy"])
            sx, sy = S.iso.to_screen(wx, wy)
            try:
                sy -= S.iso.elev(proj["gx"], proj["gy"])
            except Exception:
                pass
            arrow_img = getattr(Soldier, "ARROW_IMG", None)
            if arrow_img:
                ang_deg = math.degrees(-proj["angle"])
                rot_img = pygame.transform.rotate(arrow_img, ang_deg)
                screen.blit(rot_img, (int(sx - rot_img.get_width() // 2), int(sy - rot_img.get_height() // 2)))


__all__ = [
    "EnemyManager", "BloodMonster", "Demon", "Skull", "Rat", "Bat",
    "Golem", "Soldier", "Orc", "BaseEnemy", "find_path", "slide_move",
    "get_scaled_frame", "get_enemy_shadow", "PHASE_BUILDUP", "PHASE_PEAK", "PHASE_RELIEF"
]
