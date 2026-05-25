"""Thème, primitives de rendu CRT et composants d'interface."""

import math
import random

import pygame

from .config import *  # noqa: F401,F403  (palette + constantes)
from .config import _darken, _lighten


# ─────────────────────────────────────────────
#  Polices
# ─────────────────────────────────────────────
class Theme:
    """Polices proportionnelles à la fenêtre.
    DISPLAY = sans condensé géométrique (titres, façon HUD Tetris moderne).
    MONO    = chasse fixe (données, logs, valeurs)."""
    DISPLAY = "bahnschrift,segoeuisemibold,franklingothicmedium,impact,arialblack"
    MONO    = "cascadiamono,consolas,couriernew,monospace"

    def __init__(self, w, h):
        self.update(w, h)

    def update(self, w, h):
        # Ratios calibrés sur 950px de hauteur/largeur (min des deux)
        s = max(0.70, min(1.6, min(w, h) / 950))
        D = lambda px: pygame.font.SysFont(self.DISPLAY, int(px * s), bold=True)
        M = lambda px, b=False: pygame.font.SysFont(self.MONO, int(px * s),
                                                    bold=b)
        self.f_huge   = D(78)
        self.f_xl     = D(46)
        self.f_big    = D(34)
        self.f_med    = M(21)
        self.f_med_b  = D(22)
        self.f_small  = M(17)
        self.f_tiny   = M(13)
        self.f_micro  = M(11)


# ─────────────────────────────────────────────
#  Tuile tétromino — motif central du design
# ─────────────────────────────────────────────
def draw_block(surf, rect, color, alpha=255, gloss=True, inset=0):
    """Tuile Tetris moderne : face mate, biseau clair haut/gauche,
    biseau sombre bas/droite, reflet en haut. Brique de toute l'UI."""
    r = pygame.Rect(rect)
    if inset:
        r = r.inflate(-2 * inset, -2 * inset)
    if r.w <= 2 or r.h <= 2:
        return
    b = max(2, min(r.w, r.h) // 9)
    light = _lighten(color, 0.50)
    dark  = _darken(color, 0.45)
    face  = _darken(color, 0.10)

    if alpha >= 255:
        pygame.draw.rect(surf, face, r)
        pygame.draw.polygon(surf, light, [
            r.topleft, r.topright, (r.right - b, r.top + b),
            (r.left + b, r.top + b)])
        pygame.draw.polygon(surf, light, [
            r.topleft, (r.left + b, r.top + b),
            (r.left + b, r.bottom - b), r.bottomleft])
        pygame.draw.polygon(surf, dark, [
            r.bottomleft, (r.left + b, r.bottom - b),
            (r.right - b, r.bottom - b), r.bottomright])
        pygame.draw.polygon(surf, dark, [
            r.topright, (r.right - b, r.top + b),
            (r.right - b, r.bottom - b), r.bottomright])
        if gloss:
            gl = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            pygame.draw.rect(gl, (255, 255, 255, 28),
                             pygame.Rect(b, b, r.w - 2 * b,
                                         max(1, (r.h - 2 * b) // 3)))
            surf.blit(gl, r.topleft)
        pygame.draw.rect(surf, _darken(color, 0.62), r, 1)
    else:
        tmp = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        lr = pygame.Rect(0, 0, r.w, r.h)
        pygame.draw.rect(tmp, (*face, alpha), lr)
        pygame.draw.rect(tmp, (*light, alpha), lr, b)
        pygame.draw.rect(tmp, (*_darken(color, 0.62), alpha), lr, 1)
        surf.blit(tmp, r.topleft)


def draw_tetromino(surf, x, y, cell, shape, color, alpha=255, gap=2):
    for (cx, cy) in TETRO_SHAPES[shape]:
        draw_block(surf,
                   pygame.Rect(x + cx * cell, y + cy * cell,
                               cell - gap, cell - gap),
                   color, alpha=alpha)


# ─────────────────────────────────────────────
#  Pré-rendus (rebuild si la taille change)
# ─────────────────────────────────────────────
def make_grid(w, h, step=40):
    """Fond opaque : dégradé indigo vertical + matrice + tétrominos
    fantômes géants en filigrane."""
    s = pygame.Surface((w, h)).convert()
    top, bot = (10, 11, 26), (5, 5, 15)
    for yy in range(h):
        f = yy / max(1, h - 1)
        s.fill((int(top[0] + (bot[0] - top[0]) * f),
                int(top[1] + (bot[1] - top[1]) * f),
                int(top[2] + (bot[2] - top[2]) * f)),
               pygame.Rect(0, yy, w, 1))
    rng = random.Random(42)
    ghosts = pygame.Surface((w, h), pygame.SRCALPHA)
    for _ in range(max(4, w // 360)):
        shp = rng.choice(list(TETRO_SHAPES))
        cell = rng.randint(46, 96)
        gx = rng.randint(-cell, w)
        gy = rng.randint(-cell, h)
        for (cx, cy) in TETRO_SHAPES[shp]:
            pygame.draw.rect(ghosts, (*TETRO[shp], 14),
                             pygame.Rect(gx + cx * cell, gy + cy * cell,
                                         cell - 4, cell - 4), 2)
    s.blit(ghosts, (0, 0))
    grid = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(0, w, step):
        c = GRID_HI if (x // step) % 4 == 0 else GRID_DIM
        pygame.draw.line(grid, (*c, 90), (x, 0), (x, h))
    for y in range(0, h, step):
        c = GRID_HI if (y // step) % 4 == 0 else GRID_DIM
        pygame.draw.line(grid, (*c, 90), (0, y), (w, y))
    s.blit(grid, (0, 0))
    return s


def make_scanlines(w, h, alpha=22, spacing=3):
    """Halo cyan (fond lumineux) : grand bloom haut + léger bas, dégradé
    doux. Plus large qu'avant pour que le centre reste clair."""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    glow_h = max(1, int(h * 0.55))
    for yy in range(glow_h):
        a = int(30 * (1 - yy / glow_h) ** 1.5)
        if a > 0:
            pygame.draw.line(s, (*PHOSPHOR, a), (0, yy), (w, yy))
    base_h = max(1, int(h * 0.22))
    for k in range(base_h):
        a = int(12 * (1 - k / base_h) ** 1.6)
        if a > 0:
            yy = h - 1 - k
            pygame.draw.line(s, (*PHOSPHOR, a), (0, yy), (w, yy))
    return s


def make_vignette(w, h):
    """Assombrissement de bord TRÈS progressif : bande douce ≈ 46 % de la
    plus petite dimension (au lieu d'un liseré ≤ 70 px qui « tombait d'un
    coup »). Bord franc, fond central pleinement clair."""
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    band = max(60, int(min(w, h) * 0.46))
    max_a = 85
    for i in range(band):
        f = i / band                         # 0 = bord, 1 = limite intérieure
        a = int(max_a * (1.0 - f) ** 2.4)    # fort au bord, s'éteint en fondu
        if a <= 0:
            continue
        pygame.draw.rect(overlay, (0, 0, 6, a),
                         pygame.Rect(i, i, w - 2 * i, h - 2 * i), 1)
    return overlay


# ─────────────────────────────────────────────
#  Helpers de dessin
# ─────────────────────────────────────────────
def draw_text(surf, font, text, pos, color=TEXT_HI, glow=None):
    if glow is not None:
        g = font.render(text, True, glow)
        g.set_alpha(90)
        for off in [(-2, 0), (2, 0), (0, -2), (0, 2), (-3, 0), (3, 0)]:
            surf.blit(g, (pos[0] + off[0], pos[1] + off[1]))
    t = font.render(text, True, color)
    surf.blit(t, pos)
    return t.get_rect(topleft=pos)


def draw_text_centered(surf, font, text, center, color=TEXT_HI, glow=None):
    t = font.render(text, True, color)
    rect = t.get_rect(center=center)
    if glow is not None:
        g = font.render(text, True, glow)
        g.set_alpha(80)
        for off in [(-2, 0), (2, 0), (0, -2), (0, 2), (-3, 0), (3, 0)]:
            surf.blit(g, (rect.x + off[0], rect.y + off[1]))
    surf.blit(t, rect)
    return rect


def draw_corner_brackets(surf, rect, color=PHOSPHOR_DIM, length=18, width=3):
    """Coins en équerre façon pièce de Tetris (encoche carrée)."""
    x, y, w, h = rect
    L = length
    for (cx, cy, dx, dy) in (
        (x, y, 1, 1), (x + w, y, -1, 1),
        (x, y + h, 1, -1), (x + w, y + h, -1, -1),
    ):
        pygame.draw.line(surf, color, (cx, cy), (cx + dx * L, cy), width)
        pygame.draw.line(surf, color, (cx, cy), (cx, cy + dy * L), width)


def draw_panel(surf, rect, fill=BG_PANEL, border=PHOSPHOR_DIM, accent=None):
    """Puits sombre : liseré, barre d'accent supérieure, coins encochés."""
    r = pygame.Rect(rect)
    pygame.draw.rect(surf, fill, r, border_radius=3)
    pygame.draw.rect(surf, border, r, 1, border_radius=3)
    if accent is not None:
        bar = pygame.Surface((r.w - 4, 3), pygame.SRCALPHA)
        bar.fill((*accent, 150))
        surf.blit(bar, (r.x + 2, r.y + 2))
    draw_corner_brackets(surf, r, color=border, length=16, width=3)


def draw_scope(surf, rect, buffers, highlight=None, axis_labels=None, theme=None):
    """Oscilloscope sur matrice Tetris : signaux en couleurs de pièces,
    lueur sur la courbe mise en avant."""
    pygame.draw.rect(surf, (10, 11, 24), rect, border_radius=3)
    cell = max(18, rect.width // 28)
    for x in range(rect.left, rect.right, cell):
        pygame.draw.line(surf, GRID_DIM, (x, rect.top), (x, rect.bottom))
    for y in range(rect.top, rect.bottom, cell):
        pygame.draw.line(surf, GRID_DIM, (rect.left, y), (rect.right, y))
    cy = rect.centery
    pygame.draw.line(surf, GRID_HI, (rect.left, cy), (rect.right, cy), 1)
    pygame.draw.rect(surf, PHOSPHOR_DIM, rect, 1, border_radius=3)
    draw_corner_brackets(surf, rect, color=PHOSPHOR_DIM, length=14, width=3)

    n = max(1, len(buffers[0]))
    step = rect.width / n
    for i, buf in enumerate(buffers):
        color = PORT_COLORS[i % len(PORT_COLORS)]
        is_hi = (highlight is None) or (i == highlight)
        if not is_hi:
            color = _darken(color, 0.74)
        pts = []
        for k, v in enumerate(buf):
            x = rect.left + int(k * step)
            y = int(cy - (v - 512) * (rect.height / 2) / 512)
            y = max(rect.top + 1, min(rect.bottom - 1, y))
            pts.append((x, y))
        if len(pts) > 1:
            try:
                if is_hi and highlight is not None:
                    glow = pygame.Surface(rect.size, pygame.SRCALPHA)
                    gp = [(px - rect.left, py - rect.top) for px, py in pts]
                    pygame.draw.lines(glow, (*color, 60), False, gp, 7)
                    surf.blit(glow, rect.topleft)
                pygame.draw.aalines(surf, color, False, pts)
                if is_hi:
                    pygame.draw.lines(surf, color, False, pts, 2)
            except ValueError:
                pass

    if theme is not None and axis_labels:
        chip = max(12, cell // 2)
        x = rect.right - 96
        y = rect.top + 10
        for i, lab in enumerate(axis_labels):
            color = PORT_COLORS[i % len(PORT_COLORS)]
            is_hi = (highlight is None) or (i == highlight)
            c = color if is_hi else _darken(color, 0.62)
            draw_block(surf, pygame.Rect(x, y, chip, chip), c)
            t = theme.f_tiny.render(lab, True, c if is_hi else TEXT_DIM)
            surf.blit(t, (x + chip + 6, y + (chip - t.get_height()) // 2))
            y += chip + 5


def draw_gauge(surf, rect, value, threshold, scale_max, accent, active):
    """Jauge horizontale d'amplitude (cœur / EMG) :
      • bande sombre 0..seuil = ZONE MORTE (capteur inactif),
      • repère vertical néon = seuil réglable,
      • remplissage briques 0..valeur (vif si actif, terne sinon).
    `scale_max` borne l'échelle ; value/threshold en unités σ."""
    sm = max(1e-6, float(scale_max))
    x0, y0, w, h = rect.left, rect.top, rect.width, rect.height
    pygame.draw.rect(surf, (8, 9, 20), rect, border_radius=3)
    # Zone morte (0..seuil) ombrée
    dz_w = int(w * min(1.0, max(0.0, threshold / sm)))
    if dz_w > 0:
        shade = pygame.Surface((dz_w, h), pygame.SRCALPHA)
        shade.fill((*TEXT_FAINT, 60))
        surf.blit(shade, (x0, y0))
    # Remplissage valeur en briques
    val_w = int(w * min(1.0, max(0.0, value / sm)))
    col = accent if active else _darken(accent, 0.45)
    seg = max(6, w // 26)
    bx = x0
    while bx < x0 + val_w - 1:
        draw_block(surf, pygame.Rect(bx + 1, y0 + 2,
                                     min(seg - 2, x0 + val_w - bx),
                                     h - 4), col)
        bx += seg
    # Repère seuil
    tx = x0 + int(w * min(1.0, max(0.0, threshold / sm)))
    pygame.draw.line(surf, AMBER, (tx, y0 - 2), (tx, y0 + h + 2), 2)
    pygame.draw.rect(surf, PHOSPHOR_DIM, rect, 1, border_radius=3)


def draw_radar(surf, rect, x_norm, y_norm, dead_zone, theme):
    """Matrice carrée centrée : zone morte = carré néon (bloc),
    pièce-curseur biseautée, flèches actives en surbrillance."""
    cx, cy = rect.center
    r = max(10, min(rect.w, rect.h) // 2 - 30)
    field = pygame.Rect(cx - r, cy - r, 2 * r, 2 * r)
    pygame.draw.rect(surf, (10, 11, 24), field, border_radius=2)
    divs = 8
    for k in range(divs + 1):
        gx = field.left + k * (2 * r) // divs
        gy = field.top + k * (2 * r) // divs
        pygame.draw.line(surf, GRID_DIM, (gx, field.top), (gx, field.bottom))
        pygame.draw.line(surf, GRID_DIM, (field.left, gy), (field.right, gy))
    pygame.draw.line(surf, GRID_HI, (cx - r, cy), (cx + r, cy), 1)
    pygame.draw.line(surf, GRID_HI, (cx, cy - r), (cx, cy + r), 1)
    pygame.draw.rect(surf, PHOSPHOR_DIM, field, 1, border_radius=2)
    draw_corner_brackets(surf, field, color=PHOSPHOR_DIM, length=14, width=3)

    dz = max(4, int(r * dead_zone))
    dz_surf = pygame.Surface((2 * dz, 2 * dz), pygame.SRCALPHA)
    pygame.draw.rect(dz_surf, (*AMBER, 34), dz_surf.get_rect(), border_radius=4)
    pygame.draw.rect(dz_surf, (*AMBER, 210), dz_surf.get_rect(), 2,
                     border_radius=4)
    surf.blit(dz_surf, (cx - dz, cy - dz))

    in_dead = math.hypot(x_norm, y_norm) <= dead_zone
    hot = lambda active: PHOSPHOR if active else TEXT_FAINT
    draw_text_centered(surf, theme.f_big, "◄", (cx - r - 30, cy),
                       hot((not in_dead) and x_norm < -dead_zone))
    draw_text_centered(surf, theme.f_big, "►", (cx + r + 30, cy),
                       hot((not in_dead) and x_norm > dead_zone))
    draw_text_centered(surf, theme.f_big, "▲", (cx, cy - r - 30),
                       hot((not in_dead) and y_norm > dead_zone))
    draw_text_centered(surf, theme.f_big, "▼", (cx, cy + r + 30),
                       hot((not in_dead) and y_norm < -dead_zone))

    px = cx + int(max(-1, min(1, x_norm)) * r)
    py = cy - int(max(-1, min(1, y_norm)) * r)
    pc = AMBER if in_dead else PHOSPHOR
    halo = pygame.Surface((52, 52), pygame.SRCALPHA)
    pygame.draw.circle(halo, (*pc, 55), (26, 26), 24)
    surf.blit(halo, (px - 26, py - 26))
    bs = max(12, r // 9)
    draw_block(surf, pygame.Rect(px - bs // 2, py - bs // 2, bs, bs), pc)


# ─────────────────────────────────────────────
#  Composants
# ─────────────────────────────────────────────
class Button:
    def __init__(self, label, accent=PHOSPHOR, hot_key=None):
        self.label = label
        self.accent = accent
        self.hot_key = hot_key
        self.rect = pygame.Rect(0, 0, 100, 40)
        self.hover = False
        self.pressed = False
        self.enabled = True
        self._pulse = 0.0

    def update(self, mouse_pos, events):
        self.hover = self.enabled and self.rect.collidepoint(mouse_pos)
        clicked = False
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.hover:
                self.pressed = True
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                if self.pressed and self.hover and self.enabled:
                    clicked = True
                    self._pulse = 1.0
                self.pressed = False
            if e.type == pygame.KEYDOWN and self.enabled:
                if self.hot_key is not None and e.key == self.hot_key:
                    clicked = True
                    self._pulse = 1.0
        self._pulse = max(0.0, self._pulse - 0.04)
        return clicked

    def draw(self, surf, font, t_anim):
        breathe = 0.5 + 0.5 * math.sin(t_anim * 2.4)
        a = self.accent
        r = pygame.Rect(self.rect)
        if not self.enabled:
            # Tuile éteinte : plate, terne.
            pygame.draw.rect(surf, BG_PANEL, r, border_radius=3)
            pygame.draw.rect(surf, TEXT_FAINT, r, 1, border_radius=3)
            t = font.render(self.label, True, TEXT_FAINT)
            surf.blit(t, t.get_rect(center=r.center))
            return
        # Halo extérieur (hover / impulsion clic)
        if self.hover or self._pulse > 0:
            inten = breathe if self.hover else self._pulse
            glow = pygame.Surface((r.w + 24, r.h + 24), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*a, int(70 * inten)),
                             glow.get_rect(), border_radius=8)
            surf.blit(glow, (r.x - 12, r.y - 12))
        # Effet d'enfoncement au clic
        if self.pressed:
            r = r.move(0, 2)
            tile = _darken(a, 0.18)
        elif self.hover:
            tile = _lighten(a, 0.12)
        else:
            tile = a
        draw_block(surf, r, tile)
        txt_c = _darken(a, 0.78)
        t = font.render(self.label, True, txt_c)
        surf.blit(t, t.get_rect(center=r.center))


class Slider:
    def __init__(self, value=0.3, vmin=0.0, vmax=1.0, accent=AMBER):
        self.value = value
        self.vmin = vmin
        self.vmax = vmax
        self.accent = accent
        self.rect = pygame.Rect(0, 0, 100, 6)
        self.drag = False

    def update(self, mouse_pos, events):
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self.rect.inflate(0, 30).collidepoint(mouse_pos):
                    self.drag = True
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.drag = False
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_LEFT:
                    self.value = max(self.vmin, self.value - 0.01)
                elif e.key == pygame.K_RIGHT:
                    self.value = min(self.vmax, self.value + 0.01)
        if self.drag and self.rect.width > 0:
            x = max(self.rect.left, min(self.rect.right, mouse_pos[0]))
            self.value = self.vmin + (self.vmax - self.vmin) * \
                         (x - self.rect.left) / self.rect.width

    def draw_compact(self, surf):
        """Rail mince sans texte : rainure + remplissage briques + poignée
        + 3 graduations (0 / .5 / 1). Le libellé et la valeur sont dessinés
        par l'appelant (ligne au-dessus). Empreinte ≈ 24 px."""
        cy = self.rect.centery
        ratio = (self.value - self.vmin) / (self.vmax - self.vmin)
        groove = pygame.Rect(self.rect.left, cy - 6, self.rect.width, 12)
        pygame.draw.rect(surf, (8, 9, 20), groove, border_radius=4)
        pygame.draw.rect(surf, PHOSPHOR_DIM, groove, 1, border_radius=4)
        seg = max(8, self.rect.width // 24)
        filled_w = int(self.rect.width * ratio)
        bx = self.rect.left
        while bx < self.rect.left + filled_w - 2:
            draw_block(surf,
                       pygame.Rect(bx + 1, cy - 5,
                                   min(seg - 2, self.rect.left + filled_w - bx),
                                   10),
                       self.accent)
            bx += seg
        for i in (0, 5, 10):
            tx = self.rect.left + int(self.rect.width * i / 10)
            pygame.draw.line(surf, TEXT_DIM, (tx, cy - 7), (tx, cy + 7), 1)
        hx = self.rect.left + filled_w
        draw_block(surf, pygame.Rect(hx - 9, cy - 12, 18, 24),
                   _lighten(self.accent, 0.10))

    def draw(self, surf, font_value, font_label):
        cy = self.rect.centery
        ratio = (self.value - self.vmin) / (self.vmax - self.vmin)
        # Rail creux
        groove = pygame.Rect(self.rect.left, cy - 7, self.rect.width, 14)
        pygame.draw.rect(surf, (8, 9, 20), groove, border_radius=4)
        pygame.draw.rect(surf, PHOSPHOR_DIM, groove, 1, border_radius=4)
        # Remplissage en briques (clear de ligne Tetris)
        seg = max(10, self.rect.width // 24)
        filled_w = int(self.rect.width * ratio)
        bx = self.rect.left
        while bx < self.rect.left + filled_w - 2:
            draw_block(surf,
                       pygame.Rect(bx + 1, cy - 6,
                                   min(seg - 2, self.rect.left + filled_w - bx),
                                   12),
                       self.accent)
            bx += seg
        # Graduations 0..1
        for i in range(11):
            tx = self.rect.left + int(self.rect.width * i / 10)
            h = 11 if i % 5 == 0 else 5
            pygame.draw.line(surf, TEXT_DIM, (tx, cy - h), (tx, cy + h), 1)
            if i % 5 == 0:
                lab = f"{i / 10:.1f}"
                tl = font_label.render(lab, True, TEXT_DIM)
                surf.blit(tl, (tx - tl.get_width() // 2, cy + 16))
        # Poignée = tuile
        hx = self.rect.left + filled_w
        draw_block(surf, pygame.Rect(hx - 12, cy - 20, 24, 40),
                   _lighten(self.accent, 0.10))
        # Valeur (néon)
        val_str = f"{self.value:.2f}"
        t = font_value.render(val_str, True, self.accent)
        gx = hx - t.get_width() // 2
        gy = cy - 24 - t.get_height()
        g = font_value.render(val_str, True, self.accent)
        g.set_alpha(90)
        for off in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            surf.blit(g, (gx + off[0], gy + off[1]))
        surf.blit(t, (gx, gy))


# ─────────────────────────────────────────────
#  Layout responsive
# ─────────────────────────────────────────────
class Layout:
    def __init__(self, w, h):
        self.compute(w, h)

    def compute(self, w, h):
        self.w = w
        self.h = h
        portrait = h > w * 1.1
        m = max(14, int(min(w, h) * 0.018))
        self.margin   = m
        self.header_h = max(44, int(h * 0.052))

        if portrait:
            # Portrait : panneau principal pleine largeur, frise + log en bas.
            self.title_h = max(80, int(h * 0.095))
            self.side_w  = 0
            self.log_h   = max(80, int(h * 0.10))
            side_h       = max(80, int(h * 0.18))
            self.header  = pygame.Rect(0, 0, w, self.header_h)
            title_top    = self.header_h + max(8, int(h * 0.01))
            self.title   = pygame.Rect(m, title_top, w - 2 * m, self.title_h)
            self.main    = pygame.Rect(m, self.title.bottom + 6,
                                       w - 2 * m,
                                       h - self.title.bottom - 6 - side_h - m - 8)
            half_w       = (w - 3 * m) // 2
            self.side    = pygame.Rect(m, self.main.bottom + 4,
                                       half_w, side_h - self.log_h - 4)
            self.log     = pygame.Rect(m + half_w + m,
                                       self.main.bottom + 4,
                                       half_w, side_h - 4)
        else:
            # Paysage : disposition côte-à-côte.
            self.title_h = max(90, min(160, int(h * 0.14)))
            raw_side     = max(260, int(w * 0.22))
            self.side_w  = min(raw_side, max(200, w - 400 - 3 * m))
            self.log_h   = max(120, min(220, int(h * 0.18)))
            self.header  = pygame.Rect(0, 0, w, self.header_h)
            title_top    = self.header_h + max(16, int(h * 0.022))
            self.title   = pygame.Rect(m, title_top, w - 2 * m, self.title_h)
            self.side    = pygame.Rect(m, self.title.bottom + 10,
                                       self.side_w,
                                       h - self.title.bottom - self.log_h - m - 22)
            self.log     = pygame.Rect(m, h - self.log_h - m,
                                       self.side_w, self.log_h)
            main_x       = self.side.right + m
            self.main    = pygame.Rect(main_x, self.title.bottom + 10,
                                       w - main_x - m,
                                       h - self.title.bottom - m - 20)
