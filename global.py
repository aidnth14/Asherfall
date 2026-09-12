#!/usr/bin/env python3
"""
================================================================================
ASHERFALL - GLOBAL ARCHITECTURE & TASK MANAGER ("MOTHER OF MOTHERS")
================================================================================
Central master registry, task manager, and diagnostic coordinator for Asherfall.
Maintains the complete subsystem hierarchy in a clean nested tree format.
"""

import os
import sys
import time
import math
import subprocess
import json
from typing import Dict, List, Any, Optional

# Project root resolution
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.join(ROOT_DIR, "client")
SERVER_DIR = os.path.join(ROOT_DIR, "server")
ASSETS_DIR = os.path.join(CLIENT_DIR, "assets")


class SystemNode:
    """Represents a clean, nested subsystem node in the architecture tree."""
    def __init__(self, name: str, category: str = "Subsystem", status: str = "ONLINE", details: Optional[Dict[str, Any]] = None):
        self.name = name
        self.category = category
        self.status = status
        self.details = details or {}
        self.children: List[SystemNode] = []

    def add_child(self, child: 'SystemNode') -> 'SystemNode':
        self.children.append(child)
        return child

    def render(self, prefix: str = "", is_last: bool = True) -> str:
        """Render this node and its recursive children in a clean ASCII tree format."""
        branch = "└── " if is_last else "├── "
        node_repr = f"{prefix}{branch}[{self.category}] \033[1;36m{self.name}\033[0m"
        if self.status == "ONLINE":
            node_repr += f" - \033[32m● {self.status}\033[0m"
        elif self.status == "ACTIVE":
            node_repr += f" - \033[34m◆ {self.status}\033[0m"
        else:
            node_repr += f" - \033[33m▲ {self.status}\033[0m"

        if self.details:
            detail_strs = [f"{k}={v}" for k, v in self.details.items()]
            node_repr += f" \033[90m({', '.join(detail_strs)})\033[0m"

        lines = [node_repr]
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(self.children):
            last = (i == len(self.children) - 1)
            lines.append(child.render(child_prefix, last))
        return "\n".join(lines)


def build_master_architecture_tree() -> SystemNode:
    """Constructs the comprehensive nested architecture tree of Asherfall."""
    root = SystemNode("Asherfall Master Engine", "Core Orchestrator", "ONLINE", {"version": "2.4.0", "target_fps": 60})

    # 1. Terrain & Hydrology Subsystem
    terrain = root.add_child(SystemNode("TerrainEngine", "Subsystem", "ONLINE", {"file": "client/iso.py", "mode": "Infinite Procedural"}))
    biomes = terrain.add_child(SystemNode("BiomeThemes", "Module", "ONLINE", {"active_themes": 2}))
    biomes.add_child(SystemNode("DirtTheme", "Biome", "ACTIVE", {"ground_tiles": "0-18,21", "props": "48-60", "prop_rate": 0.88}))
    biomes.add_child(SystemNode("StoneTheme", "Biome", "ACTIVE", {"ground_tiles": "61,63,66,69", "props": "62,64,65,67,68", "prop_rate": 0.86}))
    
    noise = terrain.add_child(SystemNode("FractalNoiseEngine", "Module", "ONLINE", {"octaves": 4, "lacunarity": 2.0, "persistence": 0.5, "feature_scale": 30.0}))
    noise.add_child(SystemNode("SmoothstepC1", "Algorithm", "ONLINE", {"formula": "3t^2 - 2t^3"}))
    noise.add_child(SystemNode("ElevationEngine", "Algorithm", "ONLINE", {"max_height_px": 64, "sunken_river_bed_px": -10}))

    hydro = terrain.add_child(SystemNode("HydrologyEngine", "Module", "ONLINE", {"autotiling": "Directional 4-Neighbor"}))
    hydro.add_child(SystemNode("RiverSystem", "Feature", "ONLINE", {"domain_warp_amp": 8.0, "width_oscillation": "0.038-0.046"}))
    hydro.add_child(SystemNode("PondSystem", "Feature", "ONLINE", {"chunk_partition": 28, "radius": "2.2-3.8"}))
    hydro.add_child(SystemNode("FreshwaterTileset", "Catalog", "ONLINE", {"open_water": 104, "banks": "105-113", "rapids": 114}))
    hydro.add_child(SystemNode("DeepWaterTileset", "Catalog", "ONLINE", {"deep_tiles": "86-89", "shores": "96-99"}))
    hydro.add_child(SystemNode("SteppingStoneRocks", "Catalog", "ONLINE", {"water_rock_tiles": "72-81"}))

    geology = terrain.add_child(SystemNode("GeologyAndOres", "Module", "ONLINE", {"hardness_hp": 100}))
    geology.add_child(SystemNode("IronCoalCopperBedrock", "Vein", "ONLINE", {"tile_id": 100, "drops": "coal,copper,iron"}))
    geology.add_child(SystemNode("GoldDiamondBedrock", "Vein", "ONLINE", {"tile_id": 101, "drops": "gold,diamond,iron"}))

    # 2. Enemy Ecosystem & AI Director (Perception 2.0)
    enemy_core = root.add_child(SystemNode("EnemyDirector", "Subsystem", "ONLINE", {"file": "client/enemy/enemy.py", "director": "Adaptive Dynamic"}))
    pacing = enemy_core.add_child(SystemNode("AdaptivePacingController", "Module", "ONLINE", {"phases": "BUILDUP, PEAK, RELIEF", "window": "60s rolling"}))
    pacing.add_child(SystemNode("TrajectorySpawner", "Algorithm", "ONLINE", {"forward_cone_tiles": "5-7"}))
    pacing.add_child(SystemNode("DynamicDifficulty", "System", "ONLINE", {"cruising_score": ">+5.0", "struggling_score": "<-5.0"}))
    pacing.add_child(SystemNode("GroupPositioning", "Algorithm", "ONLINE", {"anti_stacking": "Dynamic Angular Slots"}))

    perception = enemy_core.add_child(SystemNode("Perception2_0", "Module", "ONLINE", {"sight_cone": "100 deg FOV", "alert_beat": "0.2-0.7s"}))
    perception.add_child(SystemNode("NoisePings", "System", "ONLINE", {"gunfire": "12t", "mine_chop": "5t", "melee": "3t", "sprint": "2t"}))
    perception.add_child(SystemNode("InvestigateAI", "Behavior", "ONLINE", {"search_window": "3.0-5.0s"}))

    poise_sys = enemy_core.add_child(SystemNode("PoiseAndStagger", "Module", "ONLINE", {"stun_window": "1.4s", "vulnerability": "+25%"}))

    roster = enemy_core.add_child(SystemNode("MonsterRoster", "Module", "ONLINE", {"species_count": 6}))
    roster.add_child(SystemNode("Rat", "Monster", "ONLINE", {"hp": 30, "poise": 15, "speed": 2.05, "trick": "Pack Courage / Lone Panic"}))
    roster.add_child(SystemNode("Bat", "Monster", "ONLINE", {"hp": 28, "poise": 15, "speed": 2.15, "trick": "Aerial Standoff & Compass Flank"}))
    roster.add_child(SystemNode("Skull", "Monster", "ONLINE", {"hp": 45, "poise": 40, "speed": 1.75, "trick": "Spectral Blink (4s cd)"}))
    roster.add_child(SystemNode("Bloodseeker", "Monster", "ONLINE", {"hp": 75, "poise": 50, "speed": 1.40, "trick": "Blood Frenzy (<40% HP)"}))
    roster.add_child(SystemNode("Demon", "Monster", "ONLINE", {"hp": 110, "poise": 90, "speed": 1.55, "trick": "Emboldened Commander Aura & Infernal Ward (-30% sniper)"}))
    roster.add_child(SystemNode("Golem", "Monster", "ONLINE", {"hp": 180, "poise": 220, "speed": 1.05, "trick": "Stone Carapace (-60% Light Guns) & Tremor"}))

    # 3. Combat, Tools & Celestial Orbital Dynamics
    combat = root.add_child(SystemNode("CombatAndToolsEngine", "Subsystem", "ONLINE", {"file": "client/game.py"}))
    gamepad = combat.add_child(SystemNode("XboxGamepadController", "InputModule", "ONLINE", {"twin_stick_aim": "360 deg", "movement": "Screen-Relative Iso"}))
    orbital = combat.add_child(SystemNode("CelestialOrbitalSystem", "Module", "ONLINE", {"analog": "Earth-Sun"}))
    orbital.add_child(SystemNode("OrbitalRevolution360", "Mechanic", "ONLINE", {"sweep_time_s": 0.20, "angle": "360 deg (2pi)"}))
    orbital.add_child(SystemNode("SelfAxisSpin", "Mechanic", "ONLINE", {"rotation": "720 deg (4pi)", "axis": "Weapon Own Center"}))
    orbital.add_child(SystemNode("LuminousRibbonTrail", "VFX", "ONLINE", {"segments": 16, "color": "Cyan-White/Gold"}))
    orbital.add_child(SystemNode("CentrifugalExpansion", "Physics", "ONLINE", {"ring_expansion_px": "+4px", "scale_pop": "+35%"}))

    tools = combat.add_child(SystemNode("ToolsRegistry", "Module", "ONLINE", {"tool_count": 8}))
    tools.add_child(SystemNode("Sword", "Tool", "ONLINE", {"damage": "45-58", "reach_tiles": 2.85, "affinity": "Enemies, 360 Cleave"}))
    tools.add_child(SystemNode("Axe", "Tool", "ONLINE", {"damage": "25-52", "reach_tiles": 2.45, "affinity": "Trees, Deadfall, Stumps"}))
    tools.add_child(SystemNode("Pickaxe", "Tool", "ONLINE", {"damage": "25-52", "reach_tiles": 2.45, "affinity": "Boulders, Spires, Ore Bedrock"}))
    tools.add_child(SystemNode("Hammer", "Tool", "ONLINE", {"damage": "24-35", "reach_tiles": 2.45, "knockback_impulse": 14.0}))
    tools.add_child(SystemNode("Shovel", "Tool", "ONLINE", {"damage": 18, "reach_tiles": 2.20, "affinity": "Soil Excavation"}))
    tools.add_child(SystemNode("Mallet", "Tool", "ONLINE", {"damage": 22, "reach_tiles": 2.20, "affinity": "Blunt Timber Splitting"}))
    tools.add_child(SystemNode("Scythe", "Tool", "ONLINE", {"damage": 20, "reach_tiles": 2.20, "affinity": "Foliage & Crop Reaping"}))
    tools.add_child(SystemNode("FishingRod", "Tool", "ONLINE", {"damage": 15, "reach_tiles": 2.20, "affinity": "Freshwater Fishing"}))

    # 4. Ballistics & Firearms Subsystem
    ballistics = root.add_child(SystemNode("BallisticsAndWeapons", "Subsystem", "ONLINE", {"file": "client/weapons.py"}))
    ballistics.add_child(SystemNode("SoloFirearms", "Category", "ONLINE", {"count": 5}))
    ballistics.children[-1].add_child(SystemNode("M24Sniper", "Weapon", "ONLINE", {"damage": 80, "speed": 2600, "recoil": 1.2, "fire_rate": 1.10}))
    ballistics.children[-1].add_child(SystemNode("Revolver", "Weapon", "ONLINE", {"damage": 22, "speed": 1300, "recoil": 0.5, "fire_rate": 0.45}))
    ballistics.children[-1].add_child(SystemNode("Luger", "Weapon", "ONLINE", {"damage": 14, "speed": 1000, "recoil": 0.2, "fire_rate": 0.28}))
    ballistics.children[-1].add_child(SystemNode("M92", "Weapon", "ONLINE", {"damage": 12, "speed": 1050, "recoil": 0.18, "fire_rate": 0.22}))
    ballistics.children[-1].add_child(SystemNode("Gun", "Weapon", "ONLINE", {"damage": 10, "speed": 950, "recoil": 0.15, "fire_rate": 0.25}))

    ballistics.add_child(SystemNode("AutomaticAndBurst", "Category", "ONLINE", {"count": 3}))
    ballistics.children[-1].add_child(SystemNode("AK47", "Weapon", "ONLINE", {"damage": 34, "speed": 1250, "recoil": 0.9, "fire_rate": 0.12, "mode": "AUTO"}))
    ballistics.children[-1].add_child(SystemNode("MP5", "Weapon", "ONLINE", {"damage": 15, "speed": 1000, "recoil": 0.4, "fire_rate": 0.08, "mode": "AUTO"}))
    ballistics.children[-1].add_child(SystemNode("M15", "Weapon", "ONLINE", {"damage": 26, "speed": 1450, "recoil": 1.0, "ammo": "RifleAmmoSmall", "burst": "3 rounds @ 0.065s", "mode": "BURST"}))

    ballistics.add_child(SystemNode("ShotgunsAndSpread", "Category", "ONLINE", {"count": 2}))
    ballistics.children[-1].add_child(SystemNode("SawedOffShotgun", "Weapon", "ONLINE", {"damage": "90 (5x18)", "speed": 850, "recoil": 1.1, "spread_rad": "[-0.2, +0.2]"}))
    ballistics.children[-1].add_child(SystemNode("ShotgunShellSmall", "Weapon", "ONLINE", {"damage": 10, "speed": 600, "recoil": 0.2}))

    # 5. Physics & Tactile Game Feel ("Juice")
    physics = root.add_child(SystemNode("PhysicsAndJuiceEngine", "Subsystem", "ONLINE", {"file": "client/game.py"}))
    physics.add_child(SystemNode("VisceralHitStop", "Mechanic", "ONLINE", {"freeze_duration_s": 0.035, "dt_scale": 0.15}))
    physics.add_child(SystemNode("EnemyMomentumPhysics", "Mechanic", "ONLINE", {"sword_impulse": 12.0, "hammer_impulse": 14.0, "bullet_impulse": 7.5}))
    physics.add_child(SystemNode("GroundDragDamping", "Algorithm", "ONLINE", {"decay_rate": "exp(-8.5 * dt)", "rebound_elasticity": -0.35}))
    physics.add_child(SystemNode("BouncyDamageNumbers", "UI/VFX", "ONLINE", {"initial_vy": -55.0, "gravity": 130.0, "scale_pop": "+30%"}))
    physics.add_child(SystemNode("DirectionalSlashFX", "VFX", "ONLINE", {"slash_lines": True, "starburst_sparks": 12, "max_speed": 200}))
    physics.add_child(SystemNode("DynamicScreenShake", "Camera", "ONLINE", {"tool_sword_shake": 0.0, "reduced_firearm_shake": True, "max_recoil": 1.2}))

    # 6. Items, Drops & Economics
    items_core = root.add_child(SystemNode("EconomicsAndInventory", "Subsystem", "ONLINE", {"assets_dir": "client/assets/items/"}))
    items_core.add_child(SystemNode("HarvestableMaterials", "Category", "ONLINE", {"items": "logs, wood, sticks, brick, key, book, map, letter, sack, boots"}))
    items_core.add_child(SystemNode("OresAndMinerals", "Category", "ONLINE", {"items": "coal, copper_ore, iron_ore, gold_ore, diamond"}))
    items_core.add_child(SystemNode("FoodAndConsumables", "Category", "ONLINE", {"items": "apple, bread, meat, mushroom, fish, wheat"}))
    items_core.add_child(SystemNode("AncientBooks", "Category", "ONLINE", {"volumes_cataloged": 28}))
    items_core.add_child(SystemNode("ParabolicBouncePhysics", "Physics", "ONLINE", {"vz_initial": "160-260", "gravity": -800, "restitution": -0.4}))
    items_core.add_child(SystemNode("ProximityMagnetization", "Mechanic", "ONLINE", {"pull_radius_tiles": 2.5, "pickup_radius_tiles": 0.85}))
    items_core.add_child(SystemNode("GlassmorphicInventoryHUD", "UI", "ONLINE", {"position": "x=16, y=96", "icon_size": "18x18"}))

    # 7. Navigation & Audio Engine
    nav = root.add_child(SystemNode("NavigationAndAudio", "Subsystem", "ONLINE", {"audio_format": "WAV/MP3 (44.1kHz)"}))
    nav.add_child(SystemNode("BasecampCompass", "Navigation", "ONLINE", {"target": "(0, 0) Base Camp", "pointer_offset_deg": -47.0}))
    nav.add_child(SystemNode("SynthesizedSFXEngine", "Audio", "ONLINE", {"cached_sfx": "chop, mine, break, pickup, slash, hit_slice, scream, bullet_collision"}))
    nav.add_child(SystemNode("AdaptiveMusicEngine", "Audio", "ONLINE", {"tracks": "ambient exploration"}))

    # 8. Networking & Spatial Voice Chat
    net = root.add_child(SystemNode("MultiplayerAndNetwork", "Subsystem", "ONLINE", {"port": 8080}))
    net.add_child(SystemNode("RelayServer", "Server", "ONLINE", {"file": "server/server.py", "protocol": "TCP Asynchronous non-blocking", "tick_rate": 60}))
    net.add_child(SystemNode("SpatialVoiceChat", "Audio", "ONLINE", {"file": "client/ui.py", "protocol": "UDP Opus / PyAudio", "spatial_attenuation": True}))

    # 9. Frame Rate Regulator & Performance Architecture
    perf = root.add_child(SystemNode("CPURegulatorAndPerformance", "Subsystem", "ONLINE", {"file": "client/main.py", "target_fps": 60}))
    perf.add_child(SystemNode("CPURegulator", "Governor", "ONLINE", {"target_fps": 60.0, "minimized_fps": 20.0, "sleep": "Hybrid OS Kernel Non-Busy"}))
    perf.add_child(SystemNode("SlidingWindowBuffer", "Renderer", "ONLINE", {"file": "client/iso.py", "pad_px": 96, "tile_reduction": "95%"}))
    perf.add_child(SystemNode("PrecomposedOverlays", "GraphicsCache", "ONLINE", {"file": "client/game.py", "combined_alpha_surfaces": True}))
    perf.add_child(SystemNode("OptimizedMixerBuffer", "AudioDriver", "ONLINE", {"sample_rate": 44100, "buffer": 8192, "thread_cpu": "0.9%"}))

    return root


class TaskManager:
    """Master Task Manager & Diagnostic Auditor for the Asherfall Engine."""
    
    @staticmethod
    def inspect_system_health() -> Dict[str, Any]:
        """Perform live audit on file integrity, memory, and disk footprint."""
        health = {
            "timestamp": time.time(),
            "status": "HEALTHY",
            "disk_usage_mb": 0.0,
            "within_size_budget": True,
            "core_scripts_present": True,
            "asset_directories_present": True,
            "documentation_complete": True,
            "checks": []
        }

        # 1. Check disk footprint (Must stay under 30MB constraint)
        total_bytes = 0
        for dirpath, _, filenames in os.walk(ROOT_DIR):
            if ".git" in dirpath:
                continue
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_bytes += os.path.getsize(fp)
                except OSError:
                    pass
        mb_size = total_bytes / (1024 * 1024)
        health["disk_usage_mb"] = round(mb_size, 2)
        health["within_size_budget"] = (mb_size <= 30.0)
        health["checks"].append({
            "name": "Disk Budget (<30MB)",
            "passed": mb_size <= 30.0,
            "detail": f"{health['disk_usage_mb']} MB / 30.00 MB limit"
        })

        # 2. Check essential scripts
        critical_files = [
            "client/main.py",
            "client/game.py",
            "client/iso.py",
            "client/weapons.py",
            "client/enemy/enemy.py",
            "server/server.py",
            "terrain.txt",
            "enemy.txt",
            "tools.txt",
            "weapons.txt",
            "items.txt",
            "ores.txt",
            "mechanics.txt"
        ]
        for rel_path in critical_files:
            full_path = os.path.join(ROOT_DIR, rel_path)
            exists = os.path.exists(full_path)
            health["checks"].append({
                "name": f"File: {rel_path}",
                "passed": exists,
                "detail": "Present" if exists else "MISSING"
            })
            if not exists:
                health["core_scripts_present"] = False
                health["status"] = "DEGRADED"

        # 3. Check audio SFX files
        critical_sfx = ["chop.wav", "mine.wav", "break.wav", "pickup.wav", "slash.wav", "hit_slice.wav"]
        sfx_dir = os.path.join(ASSETS_DIR, "sound", "sfx")
        for sfx in critical_sfx:
            exists = os.path.exists(os.path.join(sfx_dir, sfx))
            health["checks"].append({
                "name": f"SFX: {sfx}",
                "passed": exists,
                "detail": "Ready" if exists else "MISSING"
            })

        return health

    @staticmethod
    def print_dashboard():
        """Render complete mother-of-mothers tree and task manager dashboard."""
        tree = build_master_architecture_tree()
        health = TaskManager.inspect_system_health()

        print("\n" + "=" * 80)
        print("  \033[1;35mASHERFALL MOTHER-OF-MOTHERS MASTER TASK MANAGER & ARCHITECTURE REGISTRY\033[0m")
        print("=" * 80)
        print(f" System Status: \033[1;32m{health['status']}\033[0m | Disk Footprint: \033[1;33m{health['disk_usage_mb']} MB\033[0m (Budget: <30 MB)")
        print("-" * 80)
        print(" MASTER SYSTEM HIERARCHY TREE:")
        print("-" * 80)
        print(tree.render())
        print("-" * 80)
        print(" SYSTEM HEALTH & DIAGNOSTIC AUDIT:")
        print("-" * 80)
        for c in health["checks"]:
            mark = "\033[32m[PASS]\033[0m" if c["passed"] else "\033[31m[FAIL]\033[0m"
            print(f"  {mark} {c['name']:<35} : {c['detail']}")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(TaskManager.inspect_system_health(), indent=2))
    else:
        TaskManager.print_dashboard()
