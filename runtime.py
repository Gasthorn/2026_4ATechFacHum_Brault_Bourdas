"""Runtime BITalino pour Tetris : lecture live, modulation vitesse, contrôles.

- ``BioState`` : agrège HR, EDA, EMG, axes accéléro depuis ``device.live_buf``
  (deques alimentés par le thread d'acquisition) et expose des valeurs lissées.
- ``BioSpeedModulator`` : convertit (HR_now − HR_rest) + écart EDA en un
  multiplicateur d'intervalle de chute (×0.3 stress max .. ×2 relax).
- ``KeyboardInputHandler`` / ``BitalinoInputHandler`` : interface commune pour
  le jeu (get_move, get_soft_drop, action_rotate, action_*).
- L'``InputHandler`` BITalino implémente un anti-rebond direction : après
  un mouvement à gauche/droite, l'input opposé est ignoré tant que l'axe
  n'a pas franchi le zéro (sinon la décélération renvoie une pièce dans
  l'autre sens).
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections import deque
from typing import Optional

import pygame


# ─────────────────────────────────────────────
#  État biosignal live
# ─────────────────────────────────────────────
class BioState:
    """Lecture continue des 6 ports BITalino → métriques jeu.

    Tourne dans un thread daemon. Le ``device`` (réel ou simulé) garde
    ``live_buf[port]`` à jour ; on échantillonne périodiquement pour calculer
    BPM (PPG), niveau EDA, σ EMG amplifié, et écarts d'axes accéléro normalisés.
    """

    def __init__(self, device, calib: dict):
        self.device   = device
        self.calib    = calib
        self.ppg_port = calib.get("ppg", {}).get("port")
        self.eda_port = calib.get("eda", {}).get("port")
        self.emg_port = calib.get("emg", {}).get("port")
        self.x_port   = calib.get("ports", {}).get("x")
        self.y_port   = calib.get("ports", {}).get("y")
        self.bpm_rest = calib.get("ppg", {}).get("bpm_rest", 70) or 70
        self.eda_rest = calib.get("eda", {}).get("rest", 500) or 500
        emg = calib.get("emg", {}) or {}
        self.emg_rest   = emg.get("sigma_rest", 0.0) or 0.0
        self.emg_thresh = emg.get("threshold", 1.0) or 1.0
        self.emg_gain   = emg.get("gain", 1.0) or 1.0
        rest = calib.get("rest", {}) or {}
        rng  = calib.get("range", {}) or {}
        self.x_rest = rest.get("x", 512)
        self.y_rest = rest.get("y", 512)
        self.x_min  = rng.get("x_min", 14)
        self.x_max  = rng.get("x_max", 1010)
        self.y_min  = rng.get("y_min", 14)
        self.y_max  = rng.get("y_max", 1010)
        self.dead_zone = calib.get("dead_zone", 0.4)
        inv = calib.get("invert", {}) or {}
        self.invert_x = bool(inv.get("x", False))
        self.invert_y = bool(inv.get("y", False))

        # Live values
        self.bpm     = self.bpm_rest
        self.eda     = self.eda_rest
        self.emg_sigma = self.emg_rest
        self.emg_active_raw = False
        self.x_norm  = 0.0   # -1..+1 (gauche/droite après invert)
        self.y_norm  = 0.0   # -1..+1 (haut/bas après invert)

        self._stop = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True

    # ── boucle de mise à jour ─────────────────────────────────────
    def _loop(self):
        while not self._stop:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(0.05)

    def _read_buf(self, port):
        if port is None:
            return []
        try:
            buf = self.device.live_buf[port]
            return list(buf)
        except Exception:
            return []

    @staticmethod
    def _bpm_from(buf, freq_eff):
        """Estimation BPM rapide depuis la partie récente du live_buf."""
        if len(buf) < 60:
            return None
        n = min(len(buf), 480)
        col = buf[-n:]
        m  = statistics.mean(col)
        sd = statistics.pstdev(col) if len(col) > 1 else 0
        if sd < 3:
            return None
        threshold = m + 0.3 * sd
        min_gap = int(freq_eff * 60 / 180)
        peaks = []
        for i in range(1, len(col) - 1):
            if col[i] >= threshold and col[i] >= col[i - 1] and col[i] >= col[i + 1]:
                if not peaks or i - peaks[-1] >= min_gap:
                    peaks.append(i)
        if len(peaks) < 3:
            return None
        intervals = [peaks[k + 1] - peaks[k] for k in range(len(peaks) - 1)]
        if not intervals:
            return None
        return int(round(60 * freq_eff / statistics.mean(intervals)))

    def _update(self):
        # live_buf est décimé : un échantillon tous les 8 frames @ SAMPLING_HZ
        freq = getattr(self.device, "frequency", 1000)
        freq_eff = max(1, freq // 8)

        if self.ppg_port is not None:
            bpm = self._bpm_from(self._read_buf(self.ppg_port), freq_eff)
            if bpm is not None and 40 <= bpm <= 220:
                with self._lock:
                    self.bpm = self.bpm * 0.7 + bpm * 0.3  # lissage exponentiel

        if self.eda_port is not None:
            buf = self._read_buf(self.eda_port)
            if buf:
                eda_now = statistics.mean(buf[-min(len(buf), 60):])
                with self._lock:
                    self.eda = self.eda * 0.8 + eda_now * 0.2

        if self.emg_port is not None:
            buf = self._read_buf(self.emg_port)
            if len(buf) >= 20:
                # σ sur la fenêtre récente (~1 s) amplifiée au-dessus du repos
                win = buf[-min(len(buf), 130):]
                sigma_raw = statistics.pstdev(win) if len(win) > 1 else 0.0
                sigma_amp = self.emg_rest + self.emg_gain * (sigma_raw - self.emg_rest)
                with self._lock:
                    self.emg_sigma = sigma_amp
                    self.emg_active_raw = sigma_amp >= self.emg_thresh

        if self.x_port is not None:
            buf = self._read_buf(self.x_port)
            if buf:
                x_now = statistics.mean(buf[-min(len(buf), 10):])
                left_span  = max(1, self.x_rest - self.x_min)
                right_span = max(1, self.x_max - self.x_rest)
                if x_now < self.x_rest:
                    nx = -(self.x_rest - x_now) / left_span
                else:
                    nx = (x_now - self.x_rest) / right_span
                if self.invert_x:
                    nx = -nx
                with self._lock:
                    self.x_norm = max(-1.5, min(1.5, nx))

        if self.y_port is not None:
            buf = self._read_buf(self.y_port)
            if buf:
                y_now = statistics.mean(buf[-min(len(buf), 10):])
                down_span = max(1, self.y_rest - self.y_min)
                up_span   = max(1, self.y_max - self.y_rest)
                if y_now < self.y_rest:
                    ny = -(self.y_rest - y_now) / down_span
                else:
                    ny = (y_now - self.y_rest) / up_span
                if self.invert_y:
                    ny = -ny
                with self._lock:
                    self.y_norm = max(-1.5, min(1.5, ny))

    # ── accesseurs synchronisés ──────────────────────────────────
    def snapshot(self):
        with self._lock:
            return dict(bpm=self.bpm, eda=self.eda,
                        emg_sigma=self.emg_sigma,
                        emg_active=self.emg_active_raw,
                        x_norm=self.x_norm, y_norm=self.y_norm)


# ─────────────────────────────────────────────
#  Modulateur de vitesse (HR + EDA → ×0.3..×2)
# ─────────────────────────────────────────────
class BioSpeedModulator:
    """Convertit l'écart BPM/EDA par rapport au repos en un facteur de vitesse.

    Stress (BPM monte, EDA grimpe) → facteur < 1 → chute plus RAPIDE.
    Relax (≈ repos) → facteur ≈ 1.
    Très calme (BPM stable, EDA stable) → facteur > 1 → chute plus lente.

    Plage : 0.3 (×2 vitesse) .. 2.0 (½ vitesse). Mode "fort" du brief.
    """

    BPM_FULL_STRESS_DELTA = 35   # +35 BPM = stress max
    EDA_FULL_DELTA        = 200  # delta ADC EDA significatif

    def __init__(self, bio: Optional[BioState]):
        self.bio = bio
        self._smoothed = 1.0

    def factor(self) -> float:
        if self.bio is None:
            return 1.0
        snap = self.bio.snapshot()
        bpm_delta = snap["bpm"] - self.bio.bpm_rest
        eda_delta = snap["eda"] - self.bio.eda_rest
        # 0 = repos, 1 = stress max, négatif = très calme
        stress_bpm = bpm_delta / self.BPM_FULL_STRESS_DELTA
        stress_eda = eda_delta / self.EDA_FULL_DELTA
        stress = max(stress_bpm, stress_eda)   # le pire signal pilote
        stress = max(-0.8, min(1.0, stress))
        # mapping linéaire : stress  -0.8 → 2.0 ; 0 → 1.0 ; 1 → 0.3
        if stress >= 0:
            target = 1.0 - 0.7 * stress
        else:
            target = 1.0 + (-stress) * 1.25       # 1 + 0.8*1.25 = 2.0
        self._smoothed = self._smoothed * 0.9 + target * 0.1
        return max(0.3, min(2.0, self._smoothed))


# ─────────────────────────────────────────────
#  Input handlers
# ─────────────────────────────────────────────
class KeyboardInputHandler:
    """Contrôles clavier classiques. Identique au handler historique."""

    def __init__(self):
        self._events = []
        self._keys   = {}

    def update(self, events):
        self._events = events
        self._keys   = pygame.key.get_pressed()

    def action_rotate(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_UP
                   for e in self._events)

    def action_hard_drop(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE
                   for e in self._events)

    def action_pause(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_p
                   for e in self._events)

    def action_restart(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_r
                   for e in self._events)

    def get_move(self) -> int:
        if self._keys and self._keys[pygame.K_LEFT]:  return -1
        if self._keys and self._keys[pygame.K_RIGHT]: return 1
        return 0

    def get_soft_drop(self) -> bool:
        return bool(self._keys and self._keys[pygame.K_DOWN])

    def label(self):
        return "Clavier"


class BitalinoInputHandler:
    """Contrôles BITalino : accéléromètre G/D + H/B, EMG → rotation.

    Anti-rebond : quand l'utilisateur incline brusquement à GAUCHE, l'axe
    franchit la zone morte (input -1), puis lors du retour (décélération)
    il déborde à DROITE → un input opposé indésirable. On bloque la
    direction opposée tant que ``x_norm`` n'est pas REVENU sous le seuil
    de neutralité (``NEUTRAL_FRAC`` × seuil). Pareil pour H/B.

    Rotation par contraction EMG : action ponctuelle sur le FRONT MONTANT
    (passage de relâché → actif), pas tant que le muscle reste contracté.

    Hard drop : un grand mouvement vers le BAS (axe Y) sur l'accéléromètre.
    Pause / restart restent au clavier (P / R) — toujours dispo.
    """

    NEUTRAL_FRAC   = 0.4    # il faut redescendre sous 0.4× DZ pour réarmer
    LOCKOUT_MS     = 250    # verrou temps après un mouvement validé

    def __init__(self, bio: BioState):
        self.bio = bio
        self._events = []
        self._keys   = {}
        self._last_move_side = 0     # -1, +1, 0
        self._lockout_until  = 0     # ms : DAS verrou direction IDENTIQUE
        self._neutral_passed = True  # axe est-il REVENU au neutre franc ?
        self._last_emg_active = False
        self._last_hard_drop_t = 0.0

    def update(self, events):
        self._events = events
        self._keys   = pygame.key.get_pressed()

    def _now_ms(self):
        return pygame.time.get_ticks()

    def action_rotate(self) -> bool:
        # Pad clavier reste possible (UP) + front montant EMG.
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_UP
                 for e in self._events)
        snap = self.bio.snapshot()
        active = snap["emg_active"]
        edge = active and not self._last_emg_active
        self._last_emg_active = active
        return kb or edge

    def action_hard_drop(self) -> bool:
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE
                 for e in self._events)
        snap = self.bio.snapshot()
        # Mouvement DOWN très ample sur Y → hard drop. Limité 1×/600 ms.
        if snap["y_norm"] < -1.0:
            t = time.time()
            if t - self._last_hard_drop_t > 0.6:
                self._last_hard_drop_t = t
                return True
        return kb

    def action_pause(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_p
                   for e in self._events)

    def action_restart(self) -> bool:
        return any(e.type == pygame.KEYDOWN and e.key == pygame.K_r
                   for e in self._events)

    def get_move(self) -> int:
        snap = self.bio.snapshot()
        x = snap["x_norm"]
        dz = max(0.05, min(0.95, self.bio.dead_zone))
        if x > dz:
            side = +1
        elif x < -dz:
            side = -1
        else:
            side = 0
        # Réarmement : l'axe doit REVENIR dans une bande neutre étroite
        # avant d'accepter le SENS OPPOSÉ — c'est ce passage qui distingue
        # un nouveau geste d'un rebond / overshoot de décélération.
        if abs(x) < dz * self.NEUTRAL_FRAC:
            self._neutral_passed = True
        if side == 0:
            return 0
        # Sens opposé sans avoir touché le neutre → rebond ignoré.
        if side == -self._last_move_side and not self._neutral_passed:
            return 0
        if side != self._last_move_side:
            self._last_move_side = side
            self._neutral_passed = False
            self._lockout_until = self._now_ms() + self.LOCKOUT_MS
        return side

    def get_soft_drop(self) -> bool:
        snap = self.bio.snapshot()
        # Soft drop = inclinaison BAS modérée (entre 0.4 et 1.0).
        return -1.0 <= snap["y_norm"] < -0.4

    def label(self):
        return "Capteurs"
