"""Vérification headless du nouveau tetris.py (menus, jeu, runtime).

Charge les stubs pygame/plux du calibrage_selfcheck, puis :
  - importe ``tetris`` + ``runtime`` (sans pygame réel),
  - instancie ``BioState`` + ``BioSpeedModulator`` sur un SimulatedDevice,
  - vérifie l'anti-rebond ``BitalinoInputHandler.get_move``,
  - vérifie le bord montant de la rotation EMG,
  - vérifie le rendu de la grille + plots à plusieurs tailles.

Usage :  python tools/tetris_selfcheck.py
"""

import importlib
import sys
import time
import types

# Charger les stubs pygame/plux du selfcheck calibrage
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
import tools.calibrage_selfcheck  # noqa: F401  (stub pygame/plux)
import pygame                         # stub maintenant


def main():
    rt = importlib.import_module("runtime")
    tetris = importlib.import_module("tetris")
    from calibrage.device import SimulatedDevice
    from calibrage.config import EMG_THRESHOLD_FRAC

    # ── BioState + modulator
    dev = SimulatedDevice()
    calib = {
        "ports": {"x": 0, "y": 1, "z": 2},
        "rest": {"x": 512, "y": 512},
        "range": {"x_min": 200, "x_max": 820, "y_min": 200, "y_max": 820},
        "dead_zone": 0.4,
        "invert": {"x": False, "y": False},
        "ppg": {"port": 3, "bpm_rest": 70},
        "emg": {"port": 4, "sigma_rest": 5.0, "sigma_flex": 60.0,
                "threshold": 25.0, "gain": 1.0, "dead_zone": 0.35},
        "eda": {"port": 5, "rest": 500},
    }
    bio = rt.BioState(dev, calib)
    snap0 = bio.snapshot()
    assert "bpm" in snap0 and "x_norm" in snap0, snap0
    mod = rt.BioSpeedModulator(bio)
    f = mod.factor()
    assert 0.3 <= f <= 2.0, f

    # ── BitalinoInputHandler : anti-rebond accéléromètre
    # On bypasse BioState et on injecte directement x_norm/emg_active.
    handler = rt.BitalinoInputHandler(bio)
    handler.update([])
    # Pousser à GAUCHE (x_norm très négatif) → -1, lockout démarre.
    with bio._lock:
        bio.x_norm = -0.9
    assert handler.get_move() == -1
    # Rebond : x_norm passe brusquement à +0.6 (overshoot après décélération)
    # → on doit RENVOYER 0 tant que dans le lockout.
    with bio._lock:
        bio.x_norm = 0.6
    assert handler.get_move() == 0, "rebond non filtré"
    # Après le lockout, mais axe encore proche de la zone morte → toujours 0.
    handler._lockout_until = 0
    assert handler.get_move() == 0, "rebond marginal non filtré"
    # Retour au neutre franc puis vraie inclinaison droite → +1
    with bio._lock:
        bio.x_norm = 0.05
    handler.get_move()
    with bio._lock:
        bio.x_norm = 0.9
    assert handler.get_move() == +1

    # ── EMG : action_rotate sur le FRONT MONTANT seulement
    handler._last_emg_active = False
    with bio._lock:
        bio.emg_active_raw = True
    assert handler.action_rotate() is True   # front montant
    assert handler.action_rotate() is False  # toujours actif → pas de re-trigger
    with bio._lock:
        bio.emg_active_raw = False
    assert handler.action_rotate() is False
    with bio._lock:
        bio.emg_active_raw = True
    assert handler.action_rotate() is True   # second front montant

    # ── KeyboardInputHandler basique
    kb = rt.KeyboardInputHandler()
    kb.update([])
    assert kb.get_move() == 0

    # ── TetrisGame render à plusieurs tailles
    screen = pygame.display.set_mode((1280, 720))
    game = tetris.TetrisGame(screen, kb, mod, dev,
                             {0: "X", 1: "Y", 2: "Z",
                              3: "PPG", 4: "EMG", 5: "EDA"}, bio)
    for sz in ((960, 600), (1280, 720), (1600, 900), (2560, 1440)):
        game.screen = pygame.display.set_mode(sz)
        game._maybe_resize()
        game.draw()
    # Overlay pause + game over
    game.paused = True
    game.draw()
    game.paused = False
    game.game_over = True
    game.draw()

    # ── Modulateur : stress → facteur < 1, relax → facteur > 1
    bio.bpm = bio.bpm_rest + 50
    bio.eda = bio.eda_rest + 250
    for _ in range(50):
        f = mod.factor()
    assert f < 0.9, f
    bio.bpm = bio.bpm_rest
    bio.eda = bio.eda_rest
    mod._smoothed = 1.0
    for _ in range(50):
        f = mod.factor()
    assert 0.9 <= f <= 1.1, f

    # ── _menu présent + signature
    assert callable(tetris._menu)
    assert callable(tetris.main)

    print("ALL GREEN — tetris + runtime OK (menus, anti-rebond, EMG, render)")


if __name__ == "__main__":
    main()
