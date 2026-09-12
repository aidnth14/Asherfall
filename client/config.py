DEFAULT_SERVER = "ws://localhost:8080"

WIDTH, HEIGHT = 800, 640
FPS = 60

MONO_FONTS = "consolas,menlo,couriernew,dejavusansmono,monospace"

# accent (replaced blue with sand)
GOLD = (240, 214, 158)       # was cyan, now SAND_BRIGHT
GOLD_DIM = (198, 172, 122)   # was dim cyan, now SAND
GOLD_FAINT = (148, 122, 72)  # was faint cyan, now a darker sand
WHITE = (235, 235, 235)
MUTED = (150, 150, 165)
RED = (255, 110, 110)
GREEN = (110, 255, 150)
BG = (5, 5, 10)

# desert-sand lobby text menu
SAND = (198, 172, 122)
SAND_BRIGHT = (240, 214, 158)
SAND_SHADOW = (18, 14, 8)

CARD_BG = (16, 17, 24)
CARD_SHADOW = (0, 0, 0)
CARD_BORDER = (60, 72, 80)
DIVIDER = (48, 58, 66)

INPUT_BG = (24, 25, 34)
INPUT_BORDER = (70, 70, 85)

BTN_BG = (26, 48, 30)
BTN_BG_HOVER = (38, 78, 44)
BTN_BORDER = (80, 90, 80)

CARD_W, CARD_H = 640, 400
CARD_RADIUS = 14

CONNECTION_TIMEOUT = 12.0  # seconds without a pong before we call it dead
PING_INTERVAL = 1.0

MUSIC_TRACKS = [
    "sound/music/neon_market.mp3", "sound/music/orbital_drift.mp3", "sound/music/cargo_run.mp3", "sound/music/boardroom.mp3",
    "sound/music/sanctuary_guardians.mp3", "sound/music/alien_wolves.mp3", "sound/music/melancholic_walk.mp3",
    "sound/music/8bit-Grim Waltz - Creepy Retro Gaming Music For Streaming [No Copyright].mp3.mp3",
    "sound/music/8bit-LonePeakMusic - Highway 1 (16 Bit Retro Gaming Version).mp3.mp3",
    "sound/music/8bit-Mystery  Free mystery music for YouTube videos (no copyright).mp3.mp3",
    "sound/music/8bit-One Cosmos  Royalty Free Sci-Fi Background Music (No Copyright).mp3.mp3",
    "sound/music/8bit-Plinian - Epic Retro Gaming 16 Bit Music [No Copyright].mp3.mp3",
    "sound/music/8bit-Tronicles SciFi - Free Music  [Royalty Free No Copyright].mp3.mp3"
]
MUSIC_VOLUME = 0.22  # dimmed, ambient lobby melody rather than full theme blast
MUSIC_FADE_MS = 1500
