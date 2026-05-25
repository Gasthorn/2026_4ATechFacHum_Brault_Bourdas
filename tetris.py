"""TeTrino — Tetris BITalino.

Lanceur unifié :
  1. Menu de départ : "JOUER (calibration sauvée)" / "CALIBRER" / "QUITTER".
     Si aucun ``calibration.json`` valide → bouton JOUER désactivé.
  2. Si CALIBRER : lance le flux ``calibrage/`` dans la même fenêtre, puis
     bascule sur l'étape suivante (sans relancer pygame).
  3. Menu d'entrée : "CLAVIER" vs "CAPTEURS". Dans les deux cas, le pouls
     et l'EDA pilotent la vitesse de chute (×0.3..×2). En mode CAPTEURS,
     l'accéléromètre fait G/D et la contraction EMG fait tourner la pièce.
  4. Tetris : grille au centre, stats à gauche, 6 mini-plots (un par port
     BITalino) à droite — utilise les mêmes briques visuelles que le
     calibrage (Theme/Button/draw_block) pour un design cohérent.

Anti-rebond accéléromètre, modulation HR+EDA, et lecture des capteurs
vivent dans ``runtime.py``.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import deque

import pygame

# Réutilise le thème et les composants du calibrage (mêmes briques
# visuelles → cohérence du design).
from calibrage.app import App as CalibrationApp
from calibrage.config import (
    BG_DEEP, BG_PANEL, BG_PANEL_HI, DANGER, DEFAULT_ADDR, FPS, GRID_DIM,
    GRID_HI, INITIAL_W, INITIAL_H, MIN_H, MIN_W, PHOSPHOR, PHOSPHOR_DIM,
    PHOSPHOR_MID, PORT_COLORS, SAMPLING_HZ, TETRO, TEXT_DIM, TEXT_FAINT,
    TEXT_HI, TEXT_MID, AMBER,
)
from calibrage.device import SimulatedDevice
from calibrage.ui import (
    Button, Theme, draw_block, draw_corner_brackets, draw_panel,
    draw_text, draw_text_centered, make_grid, make_scanlines, make_vignette,
)
from runtime import (
    BioState, BioSpeedModulator, BitalinoInputHandler, KeyboardInputHandler,
)


# ─────────────────────────────────────────────
#  Plateau
# ─────────────────────────────────────────────
COLS    = 10
ROWS    = 20

PIECES = {
    "I": {"shape": [[1, 1, 1, 1]],                "color": TETRO["I"]},
    "O": {"shape": [[1, 1], [1, 1]],              "color": TETRO["O"]},
    "T": {"shape": [[0, 1, 0], [1, 1, 1]],        "color": TETRO["T"]},
    "S": {"shape": [[0, 1, 1], [1, 1, 0]],        "color": TETRO["S"]},
    "Z": {"shape": [[1, 1, 0], [0, 1, 1]],        "color": TETRO["Z"]},
    "J": {"shape": [[1, 0, 0], [1, 1, 1]],        "color": TETRO["J"]},
    "L": {"shape": [[0, 0, 1], [1, 1, 1]],        "color": TETRO["L"]},
}

LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}

BASE_DROP_MIN_MS = 100
BASE_DROP_MAX_MS = 800


def base_drop_interval(level: int) -> int:
    """Vitesse de chute "neutre" (avant modulation biosignal) selon le niveau."""
    return max(BASE_DROP_MIN_MS, BASE_DROP_MAX_MS - (level - 1) * 70)


# ─────────────────────────────────────────────
#  Pièce / Grille
# ─────────────────────────────────────────────
def rotate_matrix(matrix):
    return [list(row) for row in zip(*matrix[::-1])]


class Piece:
    def __init__(self, name=None):
        self.name  = name or random.choice(list(PIECES.keys()))
        self.color = PIECES[self.name]["color"]
        self.shape = [row[:] for row in PIECES[self.name]["shape"]]
        self.x = COLS // 2 - len(self.shape[0]) // 2
        self.y = 0

    def rotated(self):
        return rotate_matrix(self.shape)

    def cells(self, shape=None, dx=0, dy=0):
        s = shape or self.shape
        return [(self.x + c + dx, self.y + r + dy)
                for r, row in enumerate(s)
                for c, v in enumerate(row) if v]


class Grid:
    def __init__(self):
        self.cells = [[None] * COLS for _ in range(ROWS)]

    def is_valid(self, cells):
        for x, y in cells:
            if x < 0 or x >= COLS or y >= ROWS:
                return False
            if y >= 0 and self.cells[y][x] is not None:
                return False
        return True

    def lock(self, piece):
        for x, y in piece.cells():
            if 0 <= y < ROWS and 0 <= x < COLS:
                self.cells[y][x] = piece.color

    def clear_lines(self):
        full = [i for i, row in enumerate(self.cells)
                if all(c is not None for c in row)]
        for i in full:
            del self.cells[i]
            self.cells.insert(0, [None] * COLS)
        return len(full)

    def is_game_over(self):
        return any(self.cells[0][c] is not None for c in range(COLS))


# ─────────────────────────────────────────────
#  Layout : grille au centre, stats gauche, plots droite
# ─────────────────────────────────────────────
class GameLayout:
    """Layout responsive : recalcule positions/tailles selon ``screen``.

    Convention : grille TOUJOURS visible (10 colonnes × 20 rangées). La
    taille de cellule ``cell`` s'adapte à la hauteur de la fenêtre. Les
    panneaux stats (gauche) et plots (droite) prennent ce qui reste de
    chaque côté."""

    def __init__(self, w, h):
        self.compute(w, h)

    def compute(self, w, h):
        self.w, self.h = w, h
        margin = max(12, h // 50)
        self.cell = max(18, min((h - 2 * margin) // ROWS,
                                (w - 2 * 220 - 4 * margin) // COLS))
        grid_w = COLS * self.cell
        grid_h = ROWS * self.cell
        self.grid_rect = pygame.Rect((w - grid_w) // 2,
                                     (h - grid_h) // 2,
                                     grid_w, grid_h)
        # Stats à gauche : du bord à la grille (avec marge)
        stats_left = margin
        stats_right = self.grid_rect.left - margin
        self.stats_rect = pygame.Rect(stats_left, margin,
                                      max(140, stats_right - stats_left),
                                      h - 2 * margin)
        plots_left = self.grid_rect.right + margin
        self.plots_rect = pygame.Rect(plots_left, margin,
                                      max(140, w - plots_left - margin),
                                      h - 2 * margin)


# ─────────────────────────────────────────────
#  Rendu plateau
# ─────────────────────────────────────────────
def draw_grid_panel(surf, rect, grid, current, ghost_dy, cell):
    pygame.draw.rect(surf, BG_PANEL, rect)
    # Quadrillage
    for r in range(ROWS + 1):
        y = rect.top + r * cell
        pygame.draw.line(surf, GRID_DIM, (rect.left, y), (rect.right, y))
    for c in range(COLS + 1):
        x = rect.left + c * cell
        pygame.draw.line(surf, GRID_DIM, (x, rect.top), (x, rect.bottom))

    # Cellules verrouillées
    for r in range(ROWS):
        for c in range(COLS):
            color = grid.cells[r][c]
            if color:
                px = rect.left + c * cell
                py = rect.top + r * cell
                draw_block(surf, pygame.Rect(px, py, cell - 1, cell - 1), color)

    # Ghost
    if ghost_dy > 0:
        for x, y in current.cells(dy=ghost_dy):
            if 0 <= y < ROWS:
                px = rect.left + x * cell
                py = rect.top + y * cell
                draw_block(surf,
                           pygame.Rect(px, py, cell - 1, cell - 1),
                           current.color, alpha=70)
    # Pièce courante
    for x, y in current.cells():
        if 0 <= y < ROWS:
            px = rect.left + x * cell
            py = rect.top + y * cell
            draw_block(surf, pygame.Rect(px, py, cell - 1, cell - 1),
                       current.color)
    draw_corner_brackets(surf, rect, color=PHOSPHOR_DIM, length=18, width=3)


# ─────────────────────────────────────────────
#  Plots ports BITalino
# ─────────────────────────────────────────────
def draw_port_plot(surf, rect, samples, color, label, theme):
    draw_panel(surf, rect, fill=BG_DEEP, border=PHOSPHOR_DIM, accent=color)
    inner = rect.inflate(-12, -12)
    pygame.draw.rect(surf, BG_PANEL, inner)
    if not samples or len(samples) < 2:
        draw_text_centered(surf, theme.f_tiny, "— pas de signal —",
                           inner.center, color=TEXT_FAINT)
    else:
        vmin = min(samples)
        vmax = max(samples)
        if vmax - vmin < 1:
            vmin -= 1
            vmax += 1
        span = vmax - vmin
        n = len(samples)
        step = max(1, n // max(1, inner.w))
        pts = []
        for i in range(0, n, step):
            x = inner.left + int(i * inner.w / (n - 1))
            y = inner.bottom - int((samples[i] - vmin) / span * (inner.h - 2))
            pts.append((x, y))
        if len(pts) > 1:
            pygame.draw.lines(surf, color, False, pts, 1)
    draw_text(surf, theme.f_tiny, label, (rect.left + 8, rect.top + 4),
              color=TEXT_MID)


def draw_plots_panel(surf, rect, device, port_labels, theme):
    pygame.draw.rect(surf, BG_PANEL, rect, border_radius=6)
    pygame.draw.rect(surf, PHOSPHOR_DIM, rect, 1, border_radius=6)
    header = pygame.Rect(rect.left, rect.top, rect.w, 30)
    draw_text(surf, theme.f_med_b, "PORTS BITALINO",
              (rect.left + 12, rect.top + 6), color=TEXT_HI)
    plot_area = pygame.Rect(rect.left + 8, rect.top + 36,
                            rect.w - 16, rect.h - 44)
    n = 6
    row_h = plot_area.h // n
    for i in range(n):
        pr = pygame.Rect(plot_area.left,
                         plot_area.top + i * row_h,
                         plot_area.w, row_h - 2)
        buf = []
        try:
            buf = list(device.live_buf[i])
        except Exception:
            buf = []
        draw_port_plot(surf, pr, buf, PORT_COLORS[i],
                       f"P{i+1}  {port_labels.get(i, '')}", theme)


# ─────────────────────────────────────────────
#  Tetris game (boucle pygame interne)
# ─────────────────────────────────────────────
class TetrisGame:
    def __init__(self, screen, handler, modulator: BioSpeedModulator,
                 device, port_labels: dict, bio: "BioState | None"):
        self.screen   = screen
        self.handler  = handler
        self.modulator = modulator
        self.device  = device
        self.port_labels = port_labels
        self.bio = bio
        w, h = screen.get_size()
        self.layout = GameLayout(w, h)
        self.theme  = Theme(w, h)
        self._cached_size = (w, h)
        self._rebuild_overlays()
        self.clock = pygame.time.Clock()
        self.t0 = time.time()
        self.reset()

    def _rebuild_overlays(self):
        w, h = self.screen.get_size()
        self.bg_grid   = make_grid(w, h)
        self.scanlines = make_scanlines(w, h, alpha=20, spacing=3)
        self.vignette  = make_vignette(w, h)

    def _maybe_resize(self):
        if self.screen.get_size() != self._cached_size:
            w, h = self.screen.get_size()
            self.layout.compute(w, h)
            self.theme.update(w, h)
            self._rebuild_overlays()
            self._cached_size = (w, h)

    def reset(self):
        self.grid = Grid()
        self.current = Piece()
        self.next_piece = Piece()
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self._drop_timer = 0
        self._move_timer = 0
        self._move_delay = 150
        self._move_repeat = 50
        self._last_move_dir = 0
        self._move_held_ms = 0

    # ── Logique ───────────────────────────────────────────────
    def _ghost_y(self):
        dy = 0
        while self.grid.is_valid(self.current.cells(dy=dy + 1)):
            dy += 1
        return dy

    def _lock_piece(self):
        self.grid.lock(self.current)
        cleared = self.grid.clear_lines()
        if cleared:
            self.score += LINE_SCORES.get(cleared, 0) * self.level
            self.lines += cleared
            self.level  = self.lines // 10 + 1
        self.current = self.next_piece
        self.next_piece = Piece()
        if self.grid.is_game_over():
            self.game_over = True

    def _try_move(self, dx=0, dy=0, shape=None):
        cells = self.current.cells(shape=shape, dx=dx, dy=dy)
        if self.grid.is_valid(cells):
            if shape:
                self.current.shape = shape
            self.current.x += dx
            self.current.y += dy
            return True
        return False

    def _drop_interval(self):
        base = base_drop_interval(self.level)
        return max(40, int(base * self.modulator.factor()))

    def update(self, dt_ms, events):
        self.handler.update(events)
        if self.handler.action_restart():
            self.reset(); return
        if self.handler.action_pause():
            self.paused = not self.paused
        if self.paused or self.game_over:
            return

        if self.handler.action_rotate():
            self._try_move(shape=self.current.rotated())

        if self.handler.action_hard_drop():
            dy = self._ghost_y()
            self.current.y += dy
            self._lock_piece()
            return

        move = self.handler.get_move()
        if move != 0:
            if move != self._last_move_dir:
                self._last_move_dir = move
                self._move_held_ms  = 0
                self._try_move(dx=move)
            else:
                self._move_held_ms += dt_ms
                delay = (self._move_delay if self._move_held_ms < self._move_delay
                         else self._move_repeat)
                self._move_timer += dt_ms
                if self._move_timer >= delay:
                    self._move_timer = 0
                    self._try_move(dx=move)
        else:
            self._last_move_dir = 0
            self._move_held_ms  = 0
            self._move_timer    = 0

        interval = (max(40, self._drop_interval() // 6)
                    if self.handler.get_soft_drop()
                    else self._drop_interval())
        self._drop_timer += dt_ms
        if self._drop_timer >= interval:
            self._drop_timer = 0
            if not self._try_move(dy=1):
                self._lock_piece()

    # ── Rendu ─────────────────────────────────────────────────
    def draw(self):
        s = self.screen
        s.fill(BG_DEEP)
        s.blit(self.bg_grid, (0, 0))

        # Grille + pièces
        draw_grid_panel(s, self.layout.grid_rect, self.grid,
                        self.current, self._ghost_y(), self.layout.cell)

        # Stats à gauche
        self._draw_stats(self.layout.stats_rect)

        # Plots à droite
        draw_plots_panel(s, self.layout.plots_rect, self.device,
                         self.port_labels, self.theme)

        # Overlays décoratifs
        s.blit(self.scanlines, (0, 0))
        s.blit(self.vignette, (0, 0))

        if self.paused:
            self._overlay("PAUSE", "P pour reprendre")
        elif self.game_over:
            self._overlay("GAME OVER",
                          f"Score : {self.score}    R pour rejouer")

        pygame.display.flip()

    def _draw_stats(self, rect):
        pygame.draw.rect(self.screen, BG_PANEL, rect, border_radius=8)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, rect, 1, border_radius=8)
        x = rect.left + 14
        y = rect.top + 12
        draw_text(self.screen, self.theme.f_xl, "TETRIS",
                  (x, y), color=TEXT_HI)
        y += self.theme.f_xl.get_height() + 4
        draw_text(self.screen, self.theme.f_tiny,
                  f"Mode: {self.handler.label()}",
                  (x, y), color=PHOSPHOR_MID)
        y += self.theme.f_tiny.get_height() + 12

        # Suivant
        draw_text(self.screen, self.theme.f_small, "SUIVANT",
                  (x, y), color=TEXT_DIM)
        y += self.theme.f_small.get_height() + 4
        prev_r = pygame.Rect(x, y, rect.w - 28, 80)
        pygame.draw.rect(self.screen, BG_DEEP, prev_r, border_radius=4)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, prev_r, 1, border_radius=4)
        self._draw_preview(prev_r)
        y = prev_r.bottom + 14

        # Stats
        for label, value, col in [
            ("SCORE",  self.score, PHOSPHOR),
            ("LIGNES", self.lines, PHOSPHOR_MID),
            ("NIVEAU", self.level, AMBER)]:
            draw_text(self.screen, self.theme.f_small, label,
                      (x, y), color=TEXT_DIM)
            y += self.theme.f_small.get_height() + 2
            draw_text(self.screen, self.theme.f_big, str(value),
                      (x, y), color=col)
            y += self.theme.f_big.get_height() + 8

        # Biosignaux
        y += 4
        draw_text(self.screen, self.theme.f_small, "BIOSIGNAUX",
                  (x, y), color=TEXT_DIM)
        y += self.theme.f_small.get_height() + 4
        if self.bio is not None:
            snap = self.bio.snapshot()
            lines = [
                (f"PULS  {snap['bpm']:.0f} BPM  "
                 f"(repos {self.bio.bpm_rest:.0f})", DANGER),
                (f"EDA   {snap['eda']:.0f}      "
                 f"(repos {self.bio.eda_rest:.0f})", PHOSPHOR_MID),
                (f"EMG   σ={snap['emg_sigma']:.1f}  "
                 f"{'CONTRACTE' if snap['emg_active'] else 'relâché'}",
                 AMBER if snap['emg_active'] else TEXT_MID),
                (f"VIT   ×{1.0/self.modulator.factor():.2f}", PHOSPHOR),
            ]
            for txt, col in lines:
                draw_text(self.screen, self.theme.f_tiny, txt,
                          (x, y), color=col)
                y += self.theme.f_tiny.get_height() + 2
        else:
            draw_text(self.screen, self.theme.f_tiny,
                      "Aucun capteur connecté", (x, y), color=TEXT_FAINT)
            y += self.theme.f_tiny.get_height() + 2

        # Commandes
        y += 8
        draw_text(self.screen, self.theme.f_small, "COMMANDES",
                  (x, y), color=TEXT_DIM)
        y += self.theme.f_small.get_height() + 2
        if isinstance(self.handler, KeyboardInputHandler):
            ctl = ["← →   déplacer", "↑     rotation", "↓     soft drop",
                   "ESPC  hard drop", "P     pause", "R     restart"]
        else:
            ctl = ["Incl. G/D  bouger", "EMG       rotation",
                   "Bas       soft drop", "Bas++     hard drop",
                   "P / R     pause/restart"]
        for c in ctl:
            draw_text(self.screen, self.theme.f_tiny, c,
                      (x, y), color=TEXT_MID)
            y += self.theme.f_tiny.get_height() + 1

    def _draw_preview(self, rect):
        shape = self.next_piece.shape
        color = self.next_piece.color
        cell = min(18, rect.h // max(2, len(shape) + 1))
        sw = len(shape[0]) * cell
        sh = len(shape) * cell
        ox = rect.left + (rect.w - sw) // 2
        oy = rect.top + (rect.h - sh) // 2
        for r, row in enumerate(shape):
            for c, v in enumerate(row):
                if v:
                    draw_block(self.screen,
                               pygame.Rect(ox + c * cell, oy + r * cell,
                                           cell - 1, cell - 1), color)

    def _overlay(self, title, subtitle):
        r = self.layout.grid_rect
        overlay = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, r.topleft)
        draw_text_centered(self.screen, self.theme.f_huge, title,
                           r.center, color=TEXT_HI)
        draw_text_centered(self.screen, self.theme.f_small, subtitle,
                           (r.centerx, r.centery + 60), color=TEXT_MID)

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS)
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    running = False
                elif e.type == pygame.VIDEORESIZE:
                    new_w = max(MIN_W, e.w)
                    new_h = max(MIN_H, e.h)
                    self.screen = pygame.display.set_mode(
                        (new_w, new_h), pygame.RESIZABLE | pygame.DOUBLEBUF)
            self._maybe_resize()
            self.update(dt, events)
            self.draw()


# ─────────────────────────────────────────────
#  Menus de démarrage
# ─────────────────────────────────────────────
def _has_valid_calibration(path="calibration.json"):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        return (j.get("ppg", {}).get("port") is not None
                and j.get("ports", {}).get("x") is not None)
    except Exception:
        return False


def _load_calibration(path="calibration.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _menu(screen, title, subtitle, options):
    """Affiche un menu plein écran avec ``options`` = [(label, key, enabled)].

    Retourne la clé de l'option sélectionnée (clic ou touche) ou ``None``
    si fenêtre fermée."""
    theme = Theme(*screen.get_size())
    bg_grid   = make_grid(*screen.get_size())
    scanlines = make_scanlines(*screen.get_size(), alpha=20, spacing=3)
    vignette  = make_vignette(*screen.get_size())
    clock = pygame.time.Clock()
    accents = [PHOSPHOR, PHOSPHOR_MID, AMBER, DANGER]
    buttons = []
    for i, (label, key, enabled) in enumerate(options):
        b = Button(f"  {label}  ", accent=accents[i % len(accents)])
        b.enabled = enabled
        buttons.append((b, key))

    t0 = time.time()
    while True:
        clock.tick(FPS)
        w, h = screen.get_size()
        screen.blit(bg_grid, (0, 0))
        # Titre
        draw_text_centered(screen, theme.f_huge, title,
                           (w // 2, h // 4), color=TEXT_HI)
        draw_text_centered(screen, theme.f_med, subtitle,
                           (w // 2, h // 4 + 70), color=TEXT_MID)
        # Boutons en colonne
        btn_h = 64
        gap = 18
        total = len(buttons) * btn_h + (len(buttons) - 1) * gap
        start_y = h // 2 - total // 2 + 60
        for i, (b, _key) in enumerate(buttons):
            b.rect = pygame.Rect(w // 2 - 200,
                                 start_y + i * (btn_h + gap), 400, btn_h)

        mouse = pygame.mouse.get_pos()
        events = pygame.event.get()
        for e in events:
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                return None
            if e.type == pygame.VIDEORESIZE:
                new_w = max(MIN_W, e.w); new_h = max(MIN_H, e.h)
                screen = pygame.display.set_mode(
                    (new_w, new_h), pygame.RESIZABLE | pygame.DOUBLEBUF)
                theme.update(new_w, new_h)
                bg_grid   = make_grid(new_w, new_h)
                scanlines = make_scanlines(new_w, new_h, alpha=20, spacing=3)
                vignette  = make_vignette(new_w, new_h)
        chosen = None
        for b, key in buttons:
            if b.update(mouse, events):
                chosen = key
        for b, _ in buttons:
            b.draw(screen, theme.f_med_b, time.time() - t0)
        screen.blit(scanlines, (0, 0))
        screen.blit(vignette, (0, 0))
        pygame.display.flip()
        if chosen is not None:
            return chosen


# ─────────────────────────────────────────────
#  Lanceur
# ─────────────────────────────────────────────
def _port_labels_from_calib(calib):
    """index port → libellé court (X/Y/Z/PPG/EMG/EDA)."""
    out = {}
    ports = calib.get("ports", {})
    for name, key in (("X", "x"), ("Y", "y"), ("Z", "z")):
        p = ports.get(key)
        if p is not None:
            out[p] = name
    for name, k in (("PPG", "ppg"), ("EMG", "emg"), ("EDA", "eda")):
        sec = calib.get(k, {}) or {}
        p = sec.get("port")
        if p is not None:
            out[p] = name
    return out


def main(argv=None):
    argv = argv or sys.argv[1:]
    address = DEFAULT_ADDR
    force_demo = "--demo" in argv
    for a in argv:
        if not a.startswith("-"):
            address = a

    pygame.init()
    pygame.display.set_caption("TeTrino — Tetris BITalino")
    flags = pygame.RESIZABLE | pygame.DOUBLEBUF
    screen = pygame.display.set_mode((INITIAL_W, INITIAL_H), flags)

    # ── Menu de départ : jouer direct (si calib OK) ou calibrer
    has_cal = _has_valid_calibration()
    pick = _menu(
        screen, "TETRINO",
        "Tetris piloté par capteurs BITalino",
        [("JOUER (calibration sauvée)", "play", has_cal),
         ("CALIBRER", "calibrate", True),
         ("QUITTER", "quit", True)])
    if pick in (None, "quit"):
        pygame.quit(); return
    # Le menu peut avoir redimensionné : récupère la display courante.
    screen = pygame.display.get_surface() or screen

    shared_device = None
    shared_thread = None

    if pick == "calibrate":
        cal_app = CalibrationApp(screen, address)
        ok = cal_app.run()
        screen = pygame.display.get_surface() or screen
        if not ok:
            pygame.quit(); return
        shared_device = cal_app.device
        shared_thread = cal_app.acq_thread
        # Recharge la calibration fraîchement écrite
        try:
            calib = _load_calibration()
        except Exception:
            pygame.quit(); return
    else:
        calib = _load_calibration()

    # ── Menu d'entrée
    mode = _menu(
        screen, "MODE DE JEU",
        "Pouls + EDA pilotent la vitesse dans les deux modes",
        [("CLAVIER (flèches + ↑ rotation)", "keyboard", True),
         ("CAPTEURS (accéléro + EMG)", "sensors", True),
         ("QUITTER", "quit", True)])
    screen = pygame.display.get_surface() or screen
    if mode in (None, "quit"):
        if shared_device is not None:
            shared_device.stop_flag = True
            try: shared_device.stop(); shared_device.close()
            except Exception: pass
        pygame.quit(); return

    # ── Connexion device si pas déjà partagée (chemin "JOUER DIRECT")
    if shared_device is None:
        shared_device = _connect_device(address, force_demo=force_demo)
        if shared_device is None:
            pygame.quit(); return
        shared_thread = getattr(shared_device, "_thread_handle", None)

    # ── État biosignal + modulateur de vitesse
    bio = BioState(shared_device, calib)
    bio.start()
    modulator = BioSpeedModulator(bio)

    # ── Handler entrée
    if mode == "keyboard":
        handler = KeyboardInputHandler()
    else:
        handler = BitalinoInputHandler(bio)

    port_labels = _port_labels_from_calib(calib)
    game = TetrisGame(screen, handler, modulator, shared_device,
                      port_labels, bio)
    try:
        game.run()
    finally:
        bio.stop()
        if shared_device is not None:
            shared_device.stop_flag = True
            try: shared_device.stop(); shared_device.close()
            except Exception: pass
        pygame.quit()


def _connect_device(address, force_demo=False):
    """Connexion BITalino (ou simulateur si ``--demo`` / plux absent)."""
    import threading
    from calibrage.config import PLUX_AVAILABLE, ALL_PORTS
    if force_demo or not PLUX_AVAILABLE:
        d = SimulatedDevice()
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d
    try:
        from calibrage.device import CalibrationDevice
        d = CalibrationDevice(address)
        d.frequency = SAMPLING_HZ
        d.start(d.frequency, ALL_PORTS, 16)
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d
    except Exception as exc:
        print(f"Connexion BITalino impossible ({exc}) — mode démo.")
        d = SimulatedDevice()
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d


if __name__ == "__main__":
    main()
