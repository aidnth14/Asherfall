import math
import random
import pygame
from enemy.bloodseeker import BloodMonster
from enemy.demon import Demon
from enemy.skull import Skull
from enemy.rat import Rat
from enemy.bat import Bat
from enemy.golem import Golem
from enemy.soldier import Soldier
from enemy.orc import Orc
try:
    import iso
except ImportError:
    import client.iso as iso

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
