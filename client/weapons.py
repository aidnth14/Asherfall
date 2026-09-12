import os
import pygame

class Weapon:
    def __init__(self, name, fire_rate, bullet_speed, damage, gun_image_path, bullet_image_path, recoil=0.0, fire_mode="SOLO", burst_count=1, burst_interval=0.065):
        self.name = name
        self.fire_rate = fire_rate
        self.bullet_speed = bullet_speed
        self.damage = damage
        self.gun_image_path = gun_image_path
        self.bullet_image_path = bullet_image_path
        self.recoil = recoil
        self.fire_mode = fire_mode          # "SOLO", "BURST", "AUTO", "SPREAD", "MELEE", "TOOL"
        self.burst_count = burst_count
        self.burst_interval = burst_interval
        self.image = None
        self.bullet_image = None
        
    def load(self, assets_dir):
        if not self.image:
            try:
                self.image = pygame.image.load(os.path.join(assets_dir, self.gun_image_path)).convert_alpha()
            except:
                self.image = pygame.Surface((32, 32))
        if not self.bullet_image:
            try:
                self.bullet_image = pygame.image.load(os.path.join(assets_dir, self.bullet_image_path)).convert_alpha()
            except:
                self.bullet_image = pygame.Surface((8, 8))

WEAPONS = {
    # Solo Bullet Precision & Pistols
    "M24": Weapon("M24", 1.1, 2600, 80, "items/weapons/M24.png", "items/bullets/RifleAmmoBig.png", recoil=1.2, fire_mode="SOLO"),
    "Revolver": Weapon("Revolver", 0.45, 1300, 22, "items/weapons/Revolver.png", "items/bullets/PistolAmmoBig.png", recoil=0.5, fire_mode="SOLO"),
    "Luger": Weapon("Luger", 0.28, 1000, 14, "items/weapons/Luger.png", "items/bullets/PistolAmmoBig.png", recoil=0.2, fire_mode="SOLO"),
    "M92": Weapon("M92", 0.22, 1050, 12, "items/weapons/M92.png", "items/bullets/PistolAmmoBig.png", recoil=0.18, fire_mode="SOLO"),
    "Gun": Weapon("Gun", 0.25, 950, 10, "items/weapons/Luger.png", "items/bullets/PistolAmmoSmall.png", recoil=0.15, fire_mode="SOLO"),

    # Burst & Automatic Rifles
    "M15": Weapon("M15", 0.42, 1450, 26, "items/weapons/M15.png", "items/bullets/RifleAmmoSmall.png", recoil=1.0, fire_mode="BURST", burst_count=3, burst_interval=0.065),
    "AK47": Weapon("AK47", 0.12, 1250, 34, "items/weapons/AK47.png", "items/bullets/RifleAmmoBig.png", recoil=0.9, fire_mode="AUTO"),
    "MP5": Weapon("MP5", 0.08, 1000, 15, "items/weapons/MP5.png", "items/bullets/PistolAmmoBig.png", recoil=0.4, fire_mode="AUTO"),
    "SawedOffShotgun": Weapon("SawedOffShotgun", 0.75, 850, 90, "items/weapons/SawedOffShotgun.png", "items/bullets/ShotgunShellBig.png", recoil=1.1, fire_mode="SPREAD"),

    # Melee Weapons & Tools
    "Sword": Weapon("Sword", 0.35, 0, 45, "items/weapons/sword.png", "items/weapons/sword.png", recoil=0.0, fire_mode="MELEE"),
    "Axe": Weapon("Axe", 0.4, 0, 25, "items/tools/axe.png", "items/tools/axe.png", recoil=0.0, fire_mode="TOOL"),
    "Pickaxe": Weapon("Pickaxe", 0.4, 0, 25, "items/tools/pickaxe.png", "items/tools/pickaxe.png", recoil=0.0, fire_mode="TOOL"),
    "Shovel": Weapon("Shovel", 0.4, 0, 18, "items/tools/shovel.png", "items/tools/shovel.png", recoil=0.0, fire_mode="TOOL"),
    "Fishing_rod": Weapon("Fishing_rod", 0.4, 0, 15, "items/tools/fishing_rod.png", "items/tools/fishing_rod.png", recoil=0.0, fire_mode="TOOL"),
    "Hammer": Weapon("Hammer", 0.4, 0, 24, "items/tools/hammer.png", "items/tools/hammer.png", recoil=0.0, fire_mode="TOOL"),
    "Scythe": Weapon("Scythe", 0.4, 0, 20, "items/tools/hoe.png", "items/tools/hoe.png", recoil=0.0, fire_mode="TOOL"),
    "Mallet": Weapon("Mallet", 0.4, 0, 22, "items/tools/mallet.png", "items/tools/mallet.png", recoil=0.0, fire_mode="TOOL"),
}

GLOBAL_HOTBAR = [k for k, w in WEAPONS.items() if "weapons" in w.gun_image_path or "tools" in w.gun_image_path]

