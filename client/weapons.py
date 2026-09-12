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
    "Shotgunshellsmall": Weapon("Shotgunshellsmall", 0.4, 600, 10, "items/bullets/ShotgunShellSmall.png", "items/bullets/ShotgunShellSmall.png", recoil=0.2, fire_mode="SOLO"),
    "Axe": Weapon("Axe", 0.4, 0, 25, "items/tools/axe.png", "items/tools/axe.png", recoil=0.0, fire_mode="TOOL"),
    "Pickaxe": Weapon("Pickaxe", 0.4, 0, 25, "items/tools/pickaxe.png", "items/tools/pickaxe.png", recoil=0.0, fire_mode="TOOL"),
    "Shovel": Weapon("Shovel", 0.4, 0, 18, "items/tools/shovel.png", "items/tools/shovel.png", recoil=0.0, fire_mode="TOOL"),
    "Fishing_rod": Weapon("Fishing_rod", 0.4, 0, 15, "items/tools/fishing_rod.png", "items/tools/fishing_rod.png", recoil=0.0, fire_mode="TOOL"),
    "Hammer": Weapon("Hammer", 0.4, 0, 24, "items/tools/hammer.png", "items/tools/hammer.png", recoil=0.0, fire_mode="TOOL"),
    "Scythe": Weapon("Scythe", 0.4, 0, 20, "items/tools/hoe.png", "items/tools/hoe.png", recoil=0.0, fire_mode="TOOL"),
    "Mallet": Weapon("Mallet", 0.4, 0, 22, "items/tools/mallet.png", "items/tools/mallet.png", recoil=0.0, fire_mode="TOOL"),
    "Mushroom": Weapon("Mushroom", 0.4, 600, 10, "items/food/mushroom.png", "items/food/mushroom.png", recoil=0.5),
    "Apple": Weapon("Apple", 0.4, 600, 10, "items/food/apple.png", "items/food/apple.png", recoil=0.5),
    "Bread": Weapon("Bread", 0.4, 600, 10, "items/food/bread.png", "items/food/bread.png", recoil=0.5),
    "Fish": Weapon("Fish", 0.4, 600, 10, "items/food/fish.png", "items/food/fish.png", recoil=0.5),
    "Meat": Weapon("Meat", 0.4, 600, 10, "items/food/meat.png", "items/food/meat.png", recoil=0.5),
    "Wheat": Weapon("Wheat", 0.4, 600, 10, "items/food/wheat.png", "items/food/wheat.png", recoil=0.5),
    "Brick": Weapon("Brick", 0.4, 600, 10, "items/material/brick.png", "items/material/brick.png", recoil=0.5),
    "Coal": Weapon("Coal", 0.4, 600, 10, "items/ore/coal.png", "items/ore/coal.png", recoil=0.5),
    "Iron_ore": Weapon("Iron_ore", 0.4, 600, 10, "items/ore/iron_ore.png", "items/ore/iron_ore.png", recoil=0.5),
    "Wood": Weapon("Wood", 0.4, 600, 10, "items/material/wood.png", "items/material/wood.png", recoil=0.5),
    "Copper_ore": Weapon("Copper_ore", 0.4, 600, 10, "items/ore/copper_ore.png", "items/ore/copper_ore.png", recoil=0.5),
    "Gold_ore": Weapon("Gold_ore", 0.4, 600, 10, "items/ore/gold_ore.png", "items/ore/gold_ore.png", recoil=0.5),
    "Diamond": Weapon("Diamond", 0.4, 600, 10, "items/ore/diamond.png", "items/ore/diamond.png", recoil=0.5),
    "Key": Weapon("Key", 0.4, 600, 10, "items/material/key.png", "items/material/key.png", recoil=0.5),
    "Book": Weapon("Book", 0.4, 600, 10, "items/material/book.png", "items/material/book.png", recoil=0.5),
    "Map": Weapon("Map", 0.4, 600, 10, "items/material/map.png", "items/material/map.png", recoil=0.5),
    "Letter": Weapon("Letter", 0.4, 600, 10, "items/material/letter.png", "items/material/letter.png", recoil=0.5),
    "Sack": Weapon("Sack", 0.4, 600, 10, "items/material/sack.png", "items/material/sack.png", recoil=0.5),
    "Boots": Weapon("Boots", 0.4, 600, 10, "items/material/boots.png", "items/material/boots.png", recoil=0.5),
    "Stick": Weapon("Stick", 0.4, 600, 10, "items/material/stick.png", "items/material/stick.png", recoil=0.5),
    "Log1": Weapon("Log1", 0.4, 600, 10, "items/material/log1.png", "items/material/log1.png", recoil=0.5),
    "Log2": Weapon("Log2", 0.4, 600, 10, "items/material/log2.png", "items/material/log2.png", recoil=0.5),
    "Log3": Weapon("Log3", 0.4, 600, 10, "items/material/log3.png", "items/material/log3.png", recoil=0.5),
    "Log4": Weapon("Log4", 0.4, 600, 10, "items/material/log4.png", "items/material/log4.png", recoil=0.5),
}

GLOBAL_HOTBAR = [k for k, w in WEAPONS.items() if "weapons" in w.gun_image_path or "tools" in w.gun_image_path]
