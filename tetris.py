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
import statistics
import sys
import time
from collections import deque
from datetime import datetime

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
    Button, Theme, draw_block, draw_corner_brackets, draw_gauge, draw_panel,
    draw_radar, draw_text, draw_text_centered, make_grid, make_scanlines,
    make_vignette,
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

# Accélération temporelle inéluctable (en plus du niveau + biosignaux) :
# tous les TIME_RAMP_SEC, l'intervalle de chute est multiplié par
# TIME_RAMP_GAIN. Plancher TIME_FACTOR_MIN borne la vitesse maxi.
TIME_RAMP_SEC    = 20.0   # palier d'accélération (s)
TIME_RAMP_GAIN   = 0.92   # ×0.92 par palier ⇒ +8.7 % vitesse
TIME_FACTOR_MIN  = 0.15   # vitesse maxi ≈ ×6.7 / jeu neutre


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
        # Boutons du menu pause : recommencer / recalibrer / menu principal / quitter.
        self.btn_pause_restart = Button("[  RECOMMENCER  ]", accent=PHOSPHOR)
        self.btn_pause_recal   = Button("[  RECALIBRER  ]", accent=DANGER)
        self.btn_pause_menu    = Button("[  MENU PRINCIPAL  ]", accent=AMBER)
        self.btn_pause_quit    = Button("[  QUITTER  ]", accent=PHOSPHOR_MID)
        self.exit_reason = "done"   # 'done' | 'quit' | 'recalibrate' | 'main_menu'
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
        self._game_start_t = time.time()
        # Enregistrement de session : échantillons toutes les ~200 ms.
        self._history = []
        self._last_sample_t = 0.0
        self._session_summary = None
        self._session_saved_path = None

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
            self._finalize_session()

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
        # Accélération temporelle inéluctable : tous les TIME_RAMP_SEC,
        # l'intervalle est multiplié par TIME_RAMP_GAIN (0.92 ⇒ +8.7%
        # vitesse). Plancher TIME_FACTOR_MIN évite l'asymptote → 0.
        elapsed = time.time() - self._game_start_t
        steps = elapsed / TIME_RAMP_SEC
        time_factor = max(TIME_FACTOR_MIN, TIME_RAMP_GAIN ** steps)
        return max(30, int(base * self.modulator.factor() * time_factor))

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

        # Enregistrement de session (~5 Hz) : stress, BPM, EDA, σ EMG, vitesse.
        t = time.time() - self._game_start_t
        if t - self._last_sample_t >= 0.2:
            self._last_sample_t = t
            if self.bio is not None:
                snap = self.bio.snapshot()
                self._history.append({
                    "t":      round(t, 2),
                    "bpm":    round(snap["bpm"], 1),
                    "eda":    round(snap["eda"], 1),
                    "emg":    round(snap["emg_sigma"], 2),
                    "stress": round(self.modulator.stress(), 3),
                    "factor": round(self.modulator.factor(), 3),
                    "score":  self.score,
                    "lines":  self.lines,
                })

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

        # Panneau droit : widgets capteurs en haut + 6 plots ports en bas
        self._draw_right_panel(self.layout.plots_rect)

        # Overlays décoratifs
        s.blit(self.scanlines, (0, 0))
        s.blit(self.vignette, (0, 0))

        if self.paused:
            self._overlay("PAUSE", "P pour reprendre")
            self._draw_pause_buttons()
        elif self.game_over:
            self._draw_review_overlay()
            self._draw_pause_buttons()

        pygame.display.flip()

    def _draw_right_panel(self, rect):
        """Panneau droit : ligne du haut = widgets capteurs (radar accéléro
        + jauge EMG + libellé vitesse), reste = 6 mini-plots ports.
        En fin de partie (game_over) → grille 2×2 de courbes biosignaux."""
        pygame.draw.rect(self.screen, BG_PANEL, rect, border_radius=6)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, rect, 1, border_radius=6)
        if self.game_over and self._history:
            self._draw_history_panel(rect)
            return
        # Bandeau widgets (jamais plus de 40% de la hauteur)
        widget_h = min(220, max(160, rect.h // 3))
        widget_r = pygame.Rect(rect.left + 6, rect.top + 6,
                               rect.w - 12, widget_h)
        self._draw_sensor_widgets(widget_r)
        # Plots dessous
        plot_r = pygame.Rect(rect.left, widget_r.bottom + 4,
                             rect.w, rect.bottom - (widget_r.bottom + 4))
        draw_plots_panel(self.screen, plot_r, self.device,
                         self.port_labels, self.theme)

    def _draw_history_panel(self, rect):
        """Grille 2×2 de courbes historiques en fin de partie : STRESS,
        BPM, EDA, FACTEUR VITESSE. Stress graph stretche sur 2 cellules
        horizontales (priorité visuelle demandée par l'utilisateur)."""
        draw_text(self.screen, self.theme.f_med_b,
                  "RÉCAPITULATIF — ÉVOLUTION BIOSIGNAUX",
                  (rect.left + 12, rect.top + 6), color=TEXT_HI)
        inner = pygame.Rect(rect.left + 8, rect.top + 34,
                            rect.w - 16, rect.h - 42)
        # 3 lignes : stress (large), puis BPM/EDA, puis FACTEUR.
        n_rows = 3
        gap = 6
        row_h = (inner.h - (n_rows - 1) * gap) // n_rows
        bio = self.bio
        bpm_rest = getattr(bio, "bpm_rest", None)
        eda_rest = getattr(bio, "eda_rest", None)
        rows = [
            # (label, key, color, baseline, y_range, fill_under)
            [("STRESS  0..1",    "stress", DANGER,
              0.5, (0.0, 1.0), True)],
            [("BPM",             "bpm",    PHOSPHOR,
              bpm_rest, None,    False),
             ("EDA",             "eda",    PHOSPHOR_MID,
              eda_rest, None,    False)],
            [("FACTEUR VITESSE", "factor", AMBER,
              1.0, (0.3, 2.0),  False)],
        ]
        for ri, row in enumerate(rows):
            y = inner.top + ri * (row_h + gap)
            cw = (inner.w - (len(row) - 1) * gap) // len(row)
            for ci, (lbl, key, col, base, yr, fill) in enumerate(row):
                gr = pygame.Rect(inner.left + ci * (cw + gap),
                                 y, cw, row_h)
                self._draw_history_plot(gr, key, col, lbl,
                                         baseline=base, y_range=yr,
                                         fill_under=fill)

    def _draw_history_plot(self, rect, key, color, label,
                           baseline=None, y_range=None, fill_under=False):
        """Tracé d'une série (`self._history[key]`) en fonction du temps.
        Optionnel : ``baseline`` (ligne pointillée de référence — ex. BPM
        repos), ``y_range`` (plage forcée), ``fill_under`` (remplissage du
        dessous, utile pour le stress)."""
        pygame.draw.rect(self.screen, BG_DEEP, rect, border_radius=4)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, rect, 1, border_radius=4)
        hdr_h = self.theme.f_tiny.get_height() + 4
        draw_text(self.screen, self.theme.f_tiny, label,
                  (rect.left + 6, rect.top + 2), color=TEXT_MID)
        inner = pygame.Rect(rect.left + 30, rect.top + hdr_h + 2,
                            rect.w - 38, rect.h - hdr_h - 14)
        if inner.w < 10 or inner.h < 10:
            return
        samples = self._history
        if not samples or len(samples) < 2:
            draw_text_centered(self.screen, self.theme.f_tiny,
                               "— pas de données —", inner.center,
                               color=TEXT_FAINT)
            return
        vals = [s[key] for s in samples]
        ts   = [s["t"] for s in samples]
        if y_range is not None:
            vmin, vmax = y_range
        else:
            vmin, vmax = min(vals), max(vals)
            pad = max((vmax - vmin) * 0.1, 1.0)
            vmin -= pad; vmax += pad
            if baseline is not None:
                vmin = min(vmin, baseline)
                vmax = max(vmax, baseline)
        span = max(1e-6, vmax - vmin)
        tmax = max(ts) or 1.0

        def _pt(t, v):
            x = inner.left + int(t / tmax * (inner.w - 1))
            y = inner.bottom - int((v - vmin) / span * (inner.h - 1))
            return (x, max(inner.top, min(inner.bottom, y)))

        # Baseline (ligne horizontale faible)
        if baseline is not None and vmin <= baseline <= vmax:
            by = inner.bottom - int((baseline - vmin) / span * (inner.h - 1))
            for x in range(inner.left, inner.right, 6):
                pygame.draw.line(self.screen, TEXT_FAINT,
                                 (x, by), (x + 3, by), 1)
        # Courbe
        pts = [_pt(s["t"], s[key]) for s in samples]
        if fill_under and len(pts) > 1:
            poly = [(inner.left, inner.bottom)] + pts + [(inner.right, inner.bottom)]
            fill = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
            fill_color = (*color[:3], 60)
            pygame.draw.polygon(
                fill, fill_color,
                [(p[0] - inner.left, p[1] - inner.top) for p in poly])
            self.screen.blit(fill, inner.topleft)
        if len(pts) > 1:
            pygame.draw.lines(self.screen, color, False, pts, 2)
        # Axes : valeurs min/max à gauche, durée en bas.
        draw_text(self.screen, self.theme.f_tiny, f"{vmax:.1f}",
                  (rect.left + 2, inner.top - 1), color=TEXT_FAINT)
        draw_text(self.screen, self.theme.f_tiny, f"{vmin:.1f}",
                  (rect.left + 2, inner.bottom - 10), color=TEXT_FAINT)
        draw_text(self.screen, self.theme.f_tiny, f"{tmax:.0f}s",
                  (inner.right - 24, rect.bottom - 12), color=TEXT_FAINT)

    def _draw_sensor_widgets(self, rect):
        """Radar accéléromètre (G/D + H/B + zone morte) + jauge EMG."""
        pygame.draw.rect(self.screen, BG_DEEP, rect, border_radius=4)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, rect, 1, border_radius=4)
        draw_text(self.screen, self.theme.f_med_b, "CAPTEURS LIVE",
                  (rect.left + 12, rect.top + 6), color=TEXT_HI)
        if self.bio is None:
            draw_text_centered(self.screen, self.theme.f_tiny,
                               "— aucun capteur —", rect.center,
                               color=TEXT_FAINT)
            return
        snap = self.bio.snapshot()
        # Layout : RADAR à gauche (carré), jauges/stats à droite
        radar_side = min(rect.h - 36, rect.w // 2)
        radar_r = pygame.Rect(rect.left + 8,
                              rect.top + 30,
                              radar_side, radar_side)
        draw_radar(self.screen, radar_r, snap["x_norm"], snap["y_norm"],
                   self.bio.dead_zone, self.theme)

        # Côté droit : valeurs + jauge EMG
        info_x = radar_r.right + 12
        info_w = rect.right - info_x - 8
        info_y = rect.top + 34
        lh = self.theme.f_tiny.get_height() + 2

        for txt, col in (
            (f"X  {snap['x_norm']:+.2f}",
             AMBER if abs(snap["x_norm"]) > self.bio.dead_zone else TEXT_MID),
            (f"Y  {snap['y_norm']:+.2f}",
             AMBER if abs(snap["y_norm"]) > self.bio.dead_zone else TEXT_MID),
            (f"PULS {snap['bpm']:.0f} BPM  (repos {self.bio.bpm_rest:.0f})",
             DANGER),
            (f"EDA  {snap['eda']:.0f}      (repos {self.bio.eda_rest:.0f})",
             PHOSPHOR_MID),
        ):
            draw_text(self.screen, self.theme.f_tiny, txt,
                      (info_x, info_y), color=col)
            info_y += lh

        info_y += 4
        draw_text(self.screen, self.theme.f_tiny,
                  f"EMG σ  {snap['emg_sigma']:.2f}  / "
                  f"seuil {self.bio.emg_thresh:.2f}",
                  (info_x, info_y),
                  color=AMBER if snap["emg_active"] else TEXT_MID)
        info_y += lh
        gauge_r = pygame.Rect(info_x, info_y, info_w, 14)
        scale_max = max(self.bio.emg_thresh * 2,
                        snap["emg_sigma"] * 1.1, 1.0)
        draw_gauge(self.screen, gauge_r, snap["emg_sigma"],
                   self.bio.emg_thresh, scale_max, AMBER,
                   snap["emg_active"])
        info_y += 24
        draw_text(self.screen, self.theme.f_tiny,
                  f"VITESSE  ×{1.0/self.modulator.factor():.2f}",
                  (info_x, info_y), color=PHOSPHOR)

        # ── Indicateur de STRESS 0..1 (BPM + EDA combinés)
        info_y += lh + 6
        stress = self.modulator.stress()
        # Couleur : vert calme (0) → ambre (0.5) → rouge stress max (1).
        if stress < 0.5:
            k = stress * 2
            sc = (int(PHOSPHOR_MID[0] + (AMBER[0] - PHOSPHOR_MID[0]) * k),
                  int(PHOSPHOR_MID[1] + (AMBER[1] - PHOSPHOR_MID[1]) * k),
                  int(PHOSPHOR_MID[2] + (AMBER[2] - PHOSPHOR_MID[2]) * k))
        else:
            k = (stress - 0.5) * 2
            sc = (int(AMBER[0] + (DANGER[0] - AMBER[0]) * k),
                  int(AMBER[1] + (DANGER[1] - AMBER[1]) * k),
                  int(AMBER[2] + (DANGER[2] - AMBER[2]) * k))
        draw_text(self.screen, self.theme.f_tiny,
                  f"STRESS   {stress:.2f}",
                  (info_x, info_y), color=sc)
        info_y += lh
        stress_r = pygame.Rect(info_x, info_y, info_w, 14)
        pygame.draw.rect(self.screen, BG_DEEP, stress_r, border_radius=3)
        fill_w = int(info_w * stress)
        if fill_w > 2:
            pygame.draw.rect(self.screen, sc,
                             pygame.Rect(stress_r.left + 1, stress_r.top + 1,
                                         fill_w - 2, stress_r.h - 2),
                             border_radius=3)
        # Repère mi-course 0.5
        mid_x = stress_r.left + stress_r.w // 2
        pygame.draw.line(self.screen, TEXT_MID,
                         (mid_x, stress_r.top - 1),
                         (mid_x, stress_r.bottom + 1), 1)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, stress_r, 1, border_radius=3)

    # ── Fin de partie : agrégation stats + sauvegarde JSON
    def _finalize_session(self):
        if self._session_summary is not None:
            return   # idempotent : déjà fait
        duration = time.time() - self._game_start_t
        stress_series = [h["stress"] for h in self._history]
        bpm_series    = [h["bpm"]    for h in self._history if h["bpm"]]
        eda_series    = [h["eda"]    for h in self._history if h["eda"]]
        factor_series = [h["factor"] for h in self._history]

        def _stat(arr, fn, default=0.0):
            return fn(arr) if arr else default

        # Temps cumulé au-dessus d'un seuil (somme des fenêtres ~200 ms).
        dt = 0.2
        time_above_05 = dt * sum(1 for s in stress_series if s >= 0.5)
        time_above_08 = dt * sum(1 for s in stress_series if s >= 0.8)

        summary = {
            "started_at":  datetime.fromtimestamp(self._game_start_t).isoformat(),
            "ended_at":    datetime.now().isoformat(),
            "duration_sec": round(duration, 2),
            "mode":  self.handler.label(),
            "score": self.score,
            "lines": self.lines,
            "level": self.level,
            "stress": {
                "mean": round(_stat(stress_series, statistics.mean), 3),
                "max":  round(_stat(stress_series, max), 3),
                "min":  round(_stat(stress_series, min), 3),
                "time_above_0.5_sec": round(time_above_05, 1),
                "time_above_0.8_sec": round(time_above_08, 1),
            },
            "bpm": {
                "rest": getattr(self.bio, "bpm_rest", None) if self.bio else None,
                "mean": round(_stat(bpm_series, statistics.mean), 1),
                "max":  round(_stat(bpm_series, max), 1),
                "min":  round(_stat(bpm_series, min), 1),
            },
            "eda": {
                "rest": getattr(self.bio, "eda_rest", None) if self.bio else None,
                "mean": round(_stat(eda_series, statistics.mean), 1),
                "max":  round(_stat(eda_series, max), 1),
                "min":  round(_stat(eda_series, min), 1),
            },
            "speed_factor": {
                "mean": round(_stat(factor_series, statistics.mean), 3),
                "min":  round(_stat(factor_series, min), 3),
            },
            "samples": len(self._history),
        }
        self._session_summary = summary
        # Sauvegarde JSON : sessions/session_YYYYMMDD_HHMMSS.json
        try:
            os.makedirs("sessions", exist_ok=True)
            fname = "session_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
            path = os.path.join("sessions", fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({**summary, "history": self._history}, f,
                          indent=2, ensure_ascii=False)
            self._session_saved_path = path
        except Exception as exc:
            self._session_saved_path = f"ERREUR sauvegarde : {exc}"

    def _draw_review_overlay(self):
        """Carte de fin de partie : score + review du stress + chemin du JSON."""
        r = self.layout.grid_rect
        overlay = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, r.topleft)

        # Titre
        draw_text_centered(self.screen, self.theme.f_huge, "GAME OVER",
                           (r.centerx, r.top + 60), color=DANGER)
        s = self._session_summary or {}
        st = s.get("stress", {})
        y = r.top + 130
        lh = self.theme.f_small.get_height() + 4

        def line(label, value, col=TEXT_HI):
            nonlocal y
            draw_text_centered(self.screen, self.theme.f_small,
                               f"{label}  {value}",
                               (r.centerx, y), color=col)
            y += lh

        line("SCORE",   str(s.get("score", 0)))
        line("LIGNES",  str(s.get("lines", 0)))
        line("DURÉE",   f"{s.get('duration_sec', 0):.0f} s")
        y += 4
        # Review du stress (couleur selon le max)
        smax = st.get("max", 0)
        col = (DANGER if smax >= 0.8 else AMBER if smax >= 0.5 else PHOSPHOR_MID)
        line("STRESS MOYEN", f"{st.get('mean', 0):.2f}", col)
        line("STRESS MAX",   f"{smax:.2f}", col)
        line("TEMPS > 0.5",  f"{st.get('time_above_0.5_sec', 0):.1f} s", col)
        line("TEMPS > 0.8",  f"{st.get('time_above_0.8_sec', 0):.1f} s", col)
        y += 4
        b = s.get("bpm", {})
        line("BPM moy / max", f"{b.get('mean', 0):.0f} / {b.get('max', 0):.0f}",
             PHOSPHOR_MID)
        # Verdict
        y += 6
        if smax >= 0.8:
            verdict = "Stress élevé — respire !"
        elif smax >= 0.5:
            verdict = "Stress modéré"
        else:
            verdict = "Calme maîtrisé"
        draw_text_centered(self.screen, self.theme.f_med_b, verdict,
                           (r.centerx, y), color=col)
        y += self.theme.f_med_b.get_height() + 4
        # Chemin de sauvegarde
        if self._session_saved_path:
            draw_text_centered(self.screen, self.theme.f_tiny,
                               f"sauvé : {self._session_saved_path}",
                               (r.centerx, y), color=TEXT_DIM)

    def _draw_pause_buttons(self):
        r = self.layout.grid_rect
        bw, bh, gap = min(240, r.w - 40), 40, 10
        bx = r.centerx - bw // 2
        by = r.centery + 70
        btns = (self.btn_pause_restart, self.btn_pause_recal,
                self.btn_pause_menu,    self.btn_pause_quit)
        for i, b in enumerate(btns):
            b.rect = pygame.Rect(bx, by + i * (bh + gap), bw, bh)
        ta = time.time() - self.t0
        for b in btns:
            b.draw(self.screen, self.theme.f_med_b, ta)

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

        # Biosignaux : compact (détails sur le panneau droit avec radar).
        if self.bio is not None:
            snap = self.bio.snapshot()
            draw_text(self.screen, self.theme.f_small, "BIOSIGNAUX",
                      (x, y), color=TEXT_DIM)
            y += self.theme.f_small.get_height() + 2
            draw_text(self.screen, self.theme.f_tiny,
                      f"PULS  {snap['bpm']:.0f} BPM",
                      (x, y), color=DANGER)
            y += self.theme.f_tiny.get_height() + 1
            draw_text(self.screen, self.theme.f_tiny,
                      f"VITESSE ×{1.0/self.modulator.factor():.2f}",
                      (x, y), color=PHOSPHOR)
            y += self.theme.f_tiny.get_height() + 4

        # Commandes
        y += 8
        draw_text(self.screen, self.theme.f_small, "COMMANDES",
                  (x, y), color=TEXT_DIM)
        y += self.theme.f_small.get_height() + 2
        if isinstance(self.handler, KeyboardInputHandler):
            ctl = ["← →    déplacer", "↑      rotation", "↓      soft drop",
                   "ESPC   hard drop", "TAB/P  pause", "R      restart"]
        else:
            ctl = ["Incl. G/D  bouger", "EMG        rotation",
                   "Bas        soft drop", "Bas++      hard drop",
                   "TAB / P    pause", "R          restart"]
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
        """Boucle principale. Renvoie 'quit' (fermeture), 'recalibrate'
        (bouton RECALIBRER en pause), ou 'done' (game over puis quit)."""
        self.exit_reason = "quit"
        running = True
        while running:
            dt = self.clock.tick(FPS)
            events = pygame.event.get()
            mouse  = pygame.mouse.get_pos()
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
            # Boutons pause/game-over actifs UNIQUEMENT quand ils s'affichent.
            if self.paused or self.game_over:
                if self.btn_pause_restart.update(mouse, events):
                    self.reset()
                    self.paused = False
                if self.btn_pause_recal.update(mouse, events):
                    self.exit_reason = "recalibrate"
                    running = False
                if self.btn_pause_menu.update(mouse, events):
                    self.exit_reason = "main_menu"
                    running = False
                if self.btn_pause_quit.update(mouse, events):
                    self.exit_reason = "quit"
                    running = False
            self._maybe_resize()
            self.update(dt, events)
            self.draw()
        return self.exit_reason


# ─────────────────────────────────────────────
#  Menus de démarrage
# ─────────────────────────────────────────────
def _has_valid_calibration(path="calibration.json"):
    """Accepte toute calibration chargeable comportant AU MOINS un capteur
    calibré (port non nul). Les capteurs sautés sont simulés au runtime."""
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        ports = j.get("ports", {}) or {}
        any_axis = any(ports.get(k) is not None for k in ("x", "y", "z"))
        any_bio = any((j.get(k, {}) or {}).get("port") is not None
                      for k in ("ppg", "emg", "eda"))
        return any_axis or any_bio
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
    """index port (base 0 de ``device.live_buf``) → libellé X/Y/Z/PPG/EMG/EDA.
    JSON stocke les ports en BASE 1, soustraire 1 pour aligner avec live_buf."""
    out = {}
    ports = calib.get("ports", {})
    for name, key in (("X", "x"), ("Y", "y"), ("Z", "z")):
        p = ports.get(key)
        if isinstance(p, int) and p > 0:
            out[p - 1] = name
    for name, k in (("PPG", "ppg"), ("EMG", "emg"), ("EDA", "eda")):
        sec = calib.get(k, {}) or {}
        p = sec.get("port")
        if isinstance(p, int) and p > 0:
            out[p - 1] = name
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

    # ── Détection OBLIGATOIRE au démarrage. Si la carte BITalino n'est
    # pas trouvée → bascule auto en MODE DÉMO (simulateur). Plus de chemin
    # sans device : runtime + plots ont toujours un signal à lire.
    shared_device, shared_thread, is_real = _startup_detection(
        screen, address, force_demo=force_demo)
    if shared_device is None:
        pygame.quit(); return
    screen = pygame.display.get_surface() or screen

    subtitle = (f"BITalino connectée — {address}" if is_real
                else "MODE DÉMO — carte BITalino introuvable")

    def cleanup():
        if shared_device is not None:
            shared_device.stop_flag = True
            try: shared_device.stop(); shared_device.close()
            except Exception: pass
        pygame.quit()

    try:
        # ── Boucle EXTERNE : permet le retour au MENU PRINCIPAL depuis le
        # menu pause sans fermer la fenêtre ni rouvrir la carte BITalino.
        while True:
            has_cal = _has_valid_calibration()
            pick = _menu(
                screen, "TETRINO", subtitle,
                [("JOUER (calibration sauvée)", "play", has_cal),
                 ("CALIBRER", "calibrate", True),
                 ("QUITTER", "quit", True)])
            if pick in (None, "quit"):
                cleanup(); return
            screen = pygame.display.get_surface() or screen

            if pick == "calibrate":
                cal_app = CalibrationApp(
                    screen, address,
                    preconnected=(shared_device, shared_thread))
                ok = cal_app.run()
                screen = pygame.display.get_surface() or screen
                if not ok:
                    cleanup(); return
                shared_device = cal_app.device
                shared_thread = cal_app.acq_thread
                try:
                    calib = _load_calibration()
                except Exception:
                    cleanup(); return
            else:
                try:
                    calib = _load_calibration()
                except Exception:
                    cleanup(); return

            mode = _menu(
                screen, "MODE DE JEU",
                "Pouls + EDA pilotent la vitesse dans les deux modes",
                [("CLAVIER (flèches + ↑ rotation)", "keyboard", True),
                 ("CAPTEURS (accéléro + EMG)", "sensors", True),
                 ("RETOUR", "main_menu", True)])
            screen = pygame.display.get_surface() or screen
            if mode in (None, "quit"):
                cleanup(); return
            if mode == "main_menu":
                continue   # remonte au menu de départ

            # ── Boucle JEU ↔ RECALIBRER (sortie via main_menu/quit)
            back_to_main = False
            while True:
                bio = BioState(shared_device, calib)
                bio.start()
                modulator = BioSpeedModulator(bio)
                # KeyboardInputHandler reçoit aussi `bio` → EMG déclenche
                # la rotation même en mode CLAVIER (contracter le muscle =
                # tourner la pièce, en plus de la flèche ↑).
                handler = (KeyboardInputHandler(bio) if mode == "keyboard"
                           else BitalinoInputHandler(bio))
                port_labels = _port_labels_from_calib(calib)
                game = TetrisGame(screen, handler, modulator, shared_device,
                                  port_labels, bio)
                reason = game.run()
                bio.stop()
                screen = pygame.display.get_surface() or screen
                if reason == "main_menu":
                    back_to_main = True
                    break
                if reason != "recalibrate":
                    cleanup(); return
                # RECALIBRER : relance CalibrationApp puis revient au jeu.
                cal_app = CalibrationApp(
                    screen, address,
                    preconnected=(shared_device, shared_thread))
                ok = cal_app.run()
                screen = pygame.display.get_surface() or screen
                if not ok:
                    cleanup(); return
                shared_device = cal_app.device
                shared_thread = cal_app.acq_thread
                try:
                    calib = _load_calibration()
                except Exception:
                    cleanup(); return
            if back_to_main:
                continue
    finally:
        cleanup()


def _connect_device(address, force_demo=False):
    """Connexion BITalino (ou simulateur si ``--demo`` / plux absent).

    Renvoie ``(device, is_real)`` : ``is_real=True`` si carte BITalino
    réelle, ``False`` si fallback simulateur."""
    import threading
    from calibrage.config import PLUX_AVAILABLE, ALL_PORTS
    if force_demo or not PLUX_AVAILABLE:
        d = SimulatedDevice()
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d, False
    try:
        from calibrage.device import CalibrationDevice
        d = CalibrationDevice(address)
        d.frequency = SAMPLING_HZ
        d.start(d.frequency, ALL_PORTS, 16)
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d, True
    except Exception as exc:
        print(f"Connexion BITalino impossible ({exc}) — mode démo.")
        d = SimulatedDevice()
        t = threading.Thread(target=d.loop, daemon=True)
        t.start()
        d._thread_handle = t
        return d, False


def _startup_detection(screen, address, force_demo=False):
    """Écran de détection au LANCEMENT : tente la carte BITalino. En cas
    d'échec, affiche [RÉESSAYER] / [MODE DÉMO] et reste sur l'écran tant
    que l'utilisateur n'a pas tranché. Renvoie ``(device, thread, is_real)``
    ou ``(None, None, False)`` si fenêtre fermée."""
    import threading
    theme = Theme(*screen.get_size())
    bg = make_grid(*screen.get_size())
    scan = make_scanlines(*screen.get_size(), alpha=20, spacing=3)
    vig = make_vignette(*screen.get_size())
    clock = pygame.time.Clock()
    btn_retry = Button("[  RÉESSAYER  ]", accent=AMBER)
    btn_demo  = Button("[  MODE DÉMO  ]", accent=PHOSPHOR_MID)

    result = {"device": None, "is_real": False, "done": False,
              "phase": "scan"}   # scan / fail / ok
    scan_t0 = [time.time()]
    force_local = [force_demo]

    def launch():
        result["device"]  = None
        result["is_real"] = False
        result["done"]    = False
        result["phase"]   = "scan"
        scan_t0[0] = time.time()

        def worker():
            d, ok = _connect_device(address, force_demo=force_local[0])
            # Délai mini pour que l'utilisateur voie le scan
            time.sleep(max(0.0, scan_t0[0] + 1.0 - time.time()))
            result["device"]  = d
            result["is_real"] = ok
            result["phase"]   = "ok" if (ok or force_local[0]) else "fail"
            result["done"]    = True

        threading.Thread(target=worker, daemon=True).start()

    launch()
    while True:
        clock.tick(FPS)
        w, h = screen.get_size()
        screen.blit(bg, (0, 0))
        elapsed = time.time() - scan_t0[0]
        dots = "." * (int(elapsed * 3) % 4)

        if result["phase"] == "scan":
            sub, col = f"DÉTECTION DE LA CARTE BITALINO{dots}", PHOSPHOR_MID
        elif result["phase"] == "ok":
            sub = ("BITALINO CONNECTÉE" if result["is_real"]
                   else "MODE DÉMO ACTIVÉ")
            col = PHOSPHOR if result["is_real"] else PHOSPHOR_MID
        else:
            sub = "CARTE INTROUVABLE — RÉESSAYER OU PASSER EN DÉMO"
            col = DANGER

        draw_text_centered(screen, theme.f_huge, "TETRINO",
                           (w // 2, h // 3), color=TEXT_HI)
        draw_text_centered(screen, theme.f_med, sub,
                           (w // 2, h // 2), color=col)
        draw_text_centered(screen, theme.f_tiny,
                           f"adresse cible : {address}",
                           (w // 2, h // 2 + 50), color=TEXT_DIM)

        # Boutons RÉESSAYER / MODE DÉMO en phase d'échec
        events = pygame.event.get()
        mouse = pygame.mouse.get_pos()
        if result["phase"] == "fail":
            btn_retry.rect = pygame.Rect(w // 2 - 320, h // 2 + 100, 280, 56)
            btn_demo.rect  = pygame.Rect(w // 2 +  40, h // 2 + 100, 280, 56)
            if btn_retry.update(mouse, events):
                force_local[0] = False
                launch()
            if btn_demo.update(mouse, events):
                force_local[0] = True
                launch()
            btn_retry.draw(screen, theme.f_med_b, time.time())
            btn_demo.draw(screen, theme.f_med_b, time.time())

        for e in events:
            if e.type == pygame.QUIT:
                return None, None, False
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                return None, None, False
            if e.type == pygame.VIDEORESIZE:
                new_w = max(MIN_W, e.w); new_h = max(MIN_H, e.h)
                screen = pygame.display.set_mode(
                    (new_w, new_h), pygame.RESIZABLE | pygame.DOUBLEBUF)
                theme.update(new_w, new_h)
                bg   = make_grid(new_w, new_h)
                scan = make_scanlines(new_w, new_h, alpha=20, spacing=3)
                vig  = make_vignette(new_w, new_h)

        screen.blit(scan, (0, 0))
        screen.blit(vig, (0, 0))
        pygame.display.flip()

        if result["phase"] == "ok" and elapsed > 0.8:
            d = result["device"]
            return d, getattr(d, "_thread_handle", None), result["is_real"]


if __name__ == "__main__":
    main()