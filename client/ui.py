import random

import pygame

import config as cfg


class Starfield:
    def __init__(self, w, h, count=110):
        self.w, self.h = w, h
        self.stars = [
            [random.uniform(0, w), random.uniform(0, h), random.uniform(0.15, 1.2)]
            for _ in range(count)
        ]

    def update(self, dt):
        for s in self.stars:
            s[1] += s[2] * 30 * dt
            if s[1] > self.h:
                s[1] = 0
                s[0] = random.uniform(0, self.w)

    def draw(self, surf):
        for x, y, speed in self.stars:
            b = min(255, int(70 + speed * 90))
            pygame.draw.circle(surf, (b, b, b), (int(x), int(y)), 1)


class ShipFlyby:
    """Occasional cargo freighter drifting across the starfield. Drawn
    procedurally (no sprite): a long hull with a lit cockpit and a row of
    glowing cargo-bay windows, so it reads cleanly over the dark background."""

    HULL = (40, 44, 54)
    HULL_EDGE = (90, 96, 112)
    WINDOW = (120, 210, 255)
    ENGINE = (255, 190, 90)

    def __init__(self, w, h, image_path=None):
        self.w, self.h = w, h
        self.iw, self.ih = 190, 46  # freighter bounding box
        self.active = False
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.timer = random.uniform(2.0, 5.0)  # first pass fairly soon

    def _launch(self):
        # start off-screen top-right, exit off-screen bottom-left
        self.x = self.w + random.uniform(20, 160)
        self.y = random.uniform(-self.ih, self.h * 0.35)
        speed = random.uniform(30, 55)
        self.vx = -speed
        self.vy = speed * random.uniform(0.5, 0.9)
        self.active = True

    def update(self, dt):
        if not self.active:
            self.timer -= dt
            if self.timer <= 0:
                self._launch()
            return
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x + self.iw < 0 or self.y > self.h:
            self.active = False
            self.timer = random.uniform(8.0, 18.0)

    def draw(self, surf):
        if not self.active:
            return
        x, y = int(self.x), int(self.y)
        iw, ih = self.iw, self.ih
        # engine glow at the trailing (right) end
        for i, a in enumerate((60, 110, 180)):
            gr = 7 - i * 2
            g = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
            pygame.draw.circle(g, (*self.ENGINE, a), (gr, gr), gr)
            surf.blit(g, (x + iw - 6 - gr, y + ih // 2 - gr))
        # main hull (tapered nose on the left, travel direction)
        hull = [
            (x, y + ih // 2), (x + 34, y + 6), (x + iw - 10, y + 8),
            (x + iw, y + ih // 2), (x + iw - 10, y + ih - 8), (x + 34, y + ih - 6),
        ]
        pygame.draw.polygon(surf, self.HULL, hull)
        pygame.draw.polygon(surf, self.HULL_EDGE, hull, 2)
        # bridge/cockpit block on top
        bridge = pygame.Rect(x + 40, y + 2, 26, 12)
        pygame.draw.rect(surf, self.HULL_EDGE, bridge, border_radius=3)
        pygame.draw.circle(surf, self.WINDOW, (x + 46, y + 8), 2)
        # row of lit cargo-bay windows
        for i in range(6):
            wx = x + 58 + i * 18
            pygame.draw.circle(surf, self.WINDOW, (wx, y + ih // 2), 2)


def _lerp(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def make_vignette(w, h, depth=165):
    """Cached radial darkening for the screen edges. Built small (cheap
    per-pixel) then smoothscaled up so it costs almost nothing to blit."""
    import math
    s = 40
    small = pygame.Surface((s, s), pygame.SRCALPHA)
    for y in range(s):
        for x in range(s):
            d = math.hypot(x - s / 2, y - s / 2) / (s / 2 * 1.42)
            a = int(min(1.0, d * d) * depth)
            small.set_at((x, y), (0, 0, 0, a))
    return pygame.transform.smoothscale(small, (w, h))


class NineSlice:
    """Stretch a bordered sprite to any rect without distorting its corners —
    used to skin buttons and panels with the chopped pixel-art assets."""
    def __init__(self, path, margin):
        self.img = pygame.image.load(path).convert_alpha()
        self.m = margin

    def draw(self, surf, rect):
        img, m = self.img, self.m
        iw, ih = img.get_size()
        x, y, w, h = rect.x, rect.y, max(rect.w, 2 * m + 2), max(rect.h, 2 * m + 2)
        sub = lambda sx, sy, sw, sh: img.subsurface(pygame.Rect(sx, sy, sw, sh))
        sc = pygame.transform.scale
        b = surf.blit
        rmw, rmh = iw - 2 * m, ih - 2 * m       # source middle spans
        cw, ch = w - 2 * m, h - 2 * m           # dest middle spans
        b(sub(0, 0, m, m), (x, y))
        b(sub(iw - m, 0, m, m), (x + w - m, y))
        b(sub(0, ih - m, m, m), (x, y + h - m))
        b(sub(iw - m, ih - m, m, m), (x + w - m, y + h - m))
        b(sc(sub(m, 0, rmw, m), (cw, m)), (x + m, y))
        b(sc(sub(m, ih - m, rmw, m), (cw, m)), (x + m, y + h - m))
        b(sc(sub(0, m, m, rmh), (m, ch)), (x, y + m))
        b(sc(sub(iw - m, m, m, rmh), (m, ch)), (x + w - m, y + m))
        b(sc(sub(m, m, rmw, rmh), (cw, ch)), (x + m, y + m))


BUTTON_SKIN = None   # set by game after assets load (NineSlice) — else vector fallback
PANEL_SKIN = None


def draw_glow_text(surf, text, font, x, y, color, glow_color=None, glow_radius=2, center_x=None):
    glow_color = glow_color or color
    rendered = font.render(text, True, color)
    if center_x is not None:
        x = center_x - rendered.get_width() // 2
    
    # Render glow text with a darker base color instead of using set_alpha() which can cause solid boxes
    dim_color = (glow_color[0] // 4, glow_color[1] // 4, glow_color[2] // 4)
    glow = font.render(text, True, dim_color)
    
    for dx in range(-glow_radius, glow_radius + 1):
        for dy in range(-glow_radius, glow_radius + 1):
            if dx == 0 and dy == 0:
                continue
            surf.blit(glow, (x + dx, y + dy))
    surf.blit(rendered, (x, y))
    return rendered.get_width()


_TEXT_CACHE = {}
def draw_text(surf, text, font, x, y, color=cfg.WHITE, center_x=None):
    if isinstance(color, list):
        color = tuple(color)
    key = (id(font), text, color)
    rendered = _TEXT_CACHE.get(key)
    if rendered is None:
        rendered = font.render(text, True, color)
        if len(_TEXT_CACHE) < 512:
            _TEXT_CACHE[key] = rendered
    if center_x is not None:
        x = center_x - rendered.get_width() // 2
    surf.blit(rendered, (x, y))
    return rendered.get_width()


def wrap_text(text, font, max_width):
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if font.size(trial)[0] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped_text(surf, text, font, y, max_width, color=cfg.WHITE, center_x=None, line_gap=4):
    lines = wrap_text(text, font, max_width)
    line_h = font.get_height() + line_gap
    for i, line in enumerate(lines):
        draw_text(surf, line, font, 0, y + i * line_h, color, center_x=center_x)
    return len(lines) * line_h


def draw_card(surf, rect, radius=cfg.CARD_RADIUS):
    shadow_rect = rect.move(0, 6)
    shadow = pygame.Surface(shadow_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, 110), shadow.get_rect(), border_radius=radius)
    surf.blit(shadow, shadow_rect.topleft)

    if PANEL_SKIN is not None:                 # parchment-panel skin from the pack
        PANEL_SKIN.draw(surf, rect)
        return

    pygame.draw.rect(surf, cfg.CARD_BG, rect, border_radius=radius)
    pygame.draw.rect(surf, cfg.CARD_BORDER, rect, 2, border_radius=radius)

    top_line = pygame.Rect(rect.x + radius, rect.y + 1, rect.w - radius * 2, 2)
    pygame.draw.rect(surf, cfg.GOLD_FAINT, top_line)


def draw_divider(surf, x, y, w, color=cfg.DIVIDER):
    pygame.draw.line(surf, color, (x, y), (x + w, y), 1)


class TextInput:
    def __init__(self, x, y, w, h, label, value=""):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value
        self.active = False

    def handle_click(self, pos):
        self.active = self.rect.collidepoint(pos)
        return self.active

    def handle_key(self, event):
        if not self.active:
            return
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
        elif event.unicode.isprintable():
            self.value += event.unicode

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x + 2, self.rect.y - 20, cfg.GOLD_DIM)

        prefix_color = cfg.GOLD if self.active else cfg.GOLD_DIM
        draw_text(surf, "›", font, self.rect.x + 10, self.rect.y + 6, prefix_color)
        draw_text(surf, self.value, font, self.rect.x + 30, self.rect.y + 6, cfg.GOLD)

        if self.active and int(pygame.time.get_ticks() / 500) % 2 == 0:
            tw = font.size(self.value)[0]
            cx = self.rect.x + 30 + tw + 2
            pygame.draw.line(surf, cfg.GOLD, (cx, self.rect.y + 7), (cx, self.rect.bottom - 7), 2)


class Button:
    def __init__(self, x, y, w, h, label, primary=True, palette=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.primary = primary
        # palette: dict of fill/fill_hover/border/border_hover/text/accent to
        # override the default green. Lets the lobby use a sand skin.
        self.palette = palette or {}

    def draw(self, surf, font):
        import time, math, pygame
        r = self.rect
        hover = r.collidepoint(pygame.mouse.get_pos())
        
        # If palette is provided and not text_only, render as a solid block button
        if self.palette and not self.palette.get("text_only"):
            bg = self.palette.get("fill_hover") if hover and "fill_hover" in self.palette else self.palette.get("fill", cfg.INPUT_BG)
            border = self.palette.get("border_hover") if hover and "border_hover" in self.palette else self.palette.get("border", cfg.GOLD)
            text_color = self.palette.get("text", cfg.WHITE)
            
            pygame.draw.rect(surf, bg, r, border_radius=6)
            pygame.draw.rect(surf, border, r, 2, border_radius=6)
            draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, text_color, center_x=r.centerx)
        else:
            # Default minimalistic text button
            c_hover = self.palette.get("text_hover", cfg.SAND_BRIGHT) if self.palette else cfg.SAND_BRIGHT
            c_norm = self.palette.get("text", cfg.SAND) if self.palette else cfg.SAND
            color = c_hover if hover else c_norm
            txt_w = draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, color, center_x=r.centerx)
    
            if hover:
                now = time.time()
                px = r.centerx + txt_w // 2 + 14 + int(2 * math.sin(now * 6))
                draw_text(surf, "<", font, px, r.centery - font.get_height() // 2, c_hover)
    def clicked(self, pos):
        return self.rect.collidepoint(pos)


def pulse_alpha(now, period=1.6, lo=140, hi=255):
    import math
    t = (now % period) / period
    return int(lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * 2 * math.pi)))


class IconButton:
    """Small circular button. Currently only draws a gear glyph, but takes
    a `kind` in case more icons are needed later."""

    def __init__(self, x, y, size, kind="gear", image_path=None):
        self.rect = pygame.Rect(x, y, size, size)
        self.kind = kind
        self.img = None
        if image_path:
            try:
                img = pygame.image.load(image_path).convert_alpha()
                self.img = pygame.transform.smoothscale(img, (size, size))
            except pygame.error:
                self.img = None

    def clicked(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf):
        import math
        hover = self.rect.collidepoint(pygame.mouse.get_pos())
        color = cfg.GOLD if hover else cfg.MUTED
        cx, cy = self.rect.center
        if self.img is not None:
            img = self.img.copy()
            img.set_alpha(255 if hover else 170)
            surf.blit(img, self.rect.topleft)
            return
        if self.kind == "close":
            r = self.rect.w // 2 - 2
            pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r + 3)
            pygame.draw.circle(surf, cfg.RED if hover else color, (cx, cy), r, 2)
            d = int(r * 0.45)
            line_col = cfg.RED if hover else color
            pygame.draw.line(surf, line_col, (cx - d, cy - d), (cx + d, cy + d), 2)
            pygame.draw.line(surf, line_col, (cx - d, cy + d), (cx + d, cy - d), 2)
            return
        if self.kind == "help":
            r = self.rect.w // 2 - 2
            pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r + 3)
            pygame.draw.circle(surf, color, (cx, cy), r, 2)
            if not hasattr(self, "_help_font") or self._help_font is None:
                self._help_font = pygame.font.SysFont("Courier", int(r * 1.5), bold=True)
            text = self._help_font.render("?", True, color)
            surf.blit(text, (cx - text.get_width() // 2 + 1, cy - text.get_height() // 2 + 1))
            return
        r_outer = self.rect.w // 2 - 2
        r_inner = int(r_outer * 0.55)
        pygame.draw.circle(surf, cfg.CARD_BG, (cx, cy), r_outer + 3)
        pygame.draw.circle(surf, color, (cx, cy), r_outer, 2)
        pygame.draw.circle(surf, color, (cx, cy), r_inner, 2)
        teeth = 8
        for i in range(teeth):
            angle = (2 * math.pi / teeth) * i
            x1 = cx + math.cos(angle) * r_outer
            y1 = cy + math.sin(angle) * r_outer
            x2 = cx + math.cos(angle) * (r_outer + 5)
            y2 = cy + math.sin(angle) * (r_outer + 5)
            pygame.draw.line(surf, color, (x1, y1), (x2, y2), 2)


class Slider:
    def __init__(self, x, y, w, value=0.5, label=""):
        self.rect = pygame.Rect(x, y, w, 6)
        self.value = value
        self.label = label
        self.dragging = False

    def _handle_pos(self):
        return int(self.rect.x + self.value * self.rect.w)

    def hit_handle(self, pos):
        hx = self._handle_pos()
        hy = self.rect.centery
        return (pos[0] - hx) ** 2 + (pos[1] - hy) ** 2 <= 12 ** 2

    def handle_mousedown(self, pos):
        # Check if mouse is near the slider horizontally and vertically
        if self.hit_handle(pos) or (self.rect.x <= pos[0] <= self.rect.right and abs(pos[1] - self.rect.centery) <= 15):
            self.dragging = True
            self._update_from_x(pos[0])
            return True
        return False

    def handle_mouseup(self):
        self.dragging = False

    def handle_mousemotion(self, pos):
        if self.dragging:
            self._update_from_x(pos[0])

    def _update_from_x(self, x):
        self.value = max(0.0, min(1.0, (x - self.rect.x) / self.rect.w))

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 22, cfg.GOLD_DIM)
        pygame.draw.rect(surf, cfg.INPUT_BG, self.rect, border_radius=3)
        fill_w = int(self.rect.w * self.value)
        if fill_w > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_w, self.rect.h)
            pygame.draw.rect(surf, cfg.GOLD_DIM, fill_rect, border_radius=3)
        hx, hy = self._handle_pos(), self.rect.centery
        pygame.draw.circle(surf, cfg.GOLD, (hx, hy), 9)
        pygame.draw.circle(surf, cfg.CARD_BG, (hx, hy), 4)
        pct = int(self.value * 100)
        draw_text(surf, f"{pct}%", font, self.rect.right + 16, self.rect.y - 8, cfg.GOLD)


def draw_focus_ring(surf, rect, color=None, pad=5):
    color = color or cfg.GOLD
    ring = rect.inflate(pad * 2, pad * 2)
    pygame.draw.rect(surf, color, ring, 3, border_radius=12)


class Stepper:
    def __init__(self, x, y, w, h, label, value, lo, hi):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value
        self.lo, self.hi = lo, hi
        btn_w = h
        self.minus_rect = pygame.Rect(x, y, btn_w, h)
        self.plus_rect = pygame.Rect(x + w - btn_w, y, btn_w, h)

    def handle_click(self, pos):
        if self.minus_rect.collidepoint(pos):
            self.value = max(self.lo, self.value - 1)
            return True
        if self.plus_rect.collidepoint(pos):
            self.value = min(self.hi, self.value + 1)
            return True
        return False

    def draw(self, surf, font, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 20, cfg.GOLD_DIM)
        for r, sym in ((self.minus_rect, "-"), (self.plus_rect, "+")):
            hover = r.collidepoint(pygame.mouse.get_pos())
            color = cfg.GOLD if hover else cfg.GOLD_DIM
            txt = font.render(sym, True, color)
            surf.blit(txt, (r.centerx - txt.get_width() // 2, r.centery - txt.get_height() // 2))
        mid = pygame.Rect(self.minus_rect.right, self.rect.y, self.plus_rect.x - self.minus_rect.right, self.rect.h)
        val_txt = font.render(str(self.value), True, cfg.GOLD)
        surf.blit(val_txt, (mid.centerx - val_txt.get_width() // 2, mid.centery - val_txt.get_height() // 2))


class Toggle:
    def __init__(self, x, y, w, h, label, value=True):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value

    def clicked(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surf, small_font):
        draw_text(surf, self.label, small_font, self.rect.x, self.rect.y - 22, cfg.GOLD_DIM)
        bg = cfg.BTN_BG_HOVER if self.value else cfg.INPUT_BG
        pygame.draw.rect(surf, bg, self.rect, border_radius=self.rect.h // 2)
        border = cfg.GOLD if self.value else cfg.INPUT_BORDER
        pygame.draw.rect(surf, border, self.rect, 2, border_radius=self.rect.h // 2)
        knob_x = self.rect.right - self.rect.h // 2 if self.value else self.rect.x + self.rect.h // 2
        pygame.draw.circle(surf, cfg.GOLD if self.value else cfg.MUTED, (knob_x, self.rect.centery), self.rect.h // 2 - 4)
