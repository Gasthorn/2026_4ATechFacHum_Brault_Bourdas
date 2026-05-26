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

# Détection PPG mutualisée avec le calibrage (source unique : signal
# lisser → seuil mean+0.35σ → pics avec min/max gap → score qualité).
# Évite la dérive entre la σ_rest calibrée et le BPM live.
from calibrage.detection import _estimate_bpm_and_score


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
        # Tampons PLEIN DÉBIT (~1 kHz) issus du polling de device.latest.
        # ``live_buf`` est décimé 1:8 (~125 Hz) — adapté aux plots et au
        # BPM (signal lent) mais NOIE l'EMG (bursts haute fréquence) et
        # introduit du retard sur l'accéléro. Le polling 1 ms restaure les
        # σ EMG calibrées (mesurées à 1 kHz) et donne un x_norm/y_norm
        # réactif (~50 ms de fenêtre).
        self._fr_bufs = [deque(maxlen=1500) for _ in range(6)]
        self._fr_lock = threading.Lock()
        self._last_tick = -1
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._poll  = threading.Thread(target=self._poll_loop, daemon=True)

    def start(self):
        self._thread.start()
        self._poll.start()

    def stop(self):
        self._stop = True

    # ── Polling plein débit de device.latest ─────────────────────
    def _poll_loop(self):
        while not self._stop:
            try:
                with self.device.lock:
                    sample = self.device.latest
                    tick = getattr(self.device, "_tick", None)
                if sample is not None and tick != self._last_tick:
                    self._last_tick = tick
                    with self._fr_lock:
                        for i, v in enumerate(sample):
                            self._fr_bufs[i].append(v)
            except Exception:
                pass
            time.sleep(0.001)

    def _read_fr(self, port, n):
        """Renvoie les ``n`` derniers échantillons plein débit du ``port``."""
        if port is None:
            return []
        with self._fr_lock:
            buf = self._fr_bufs[port]
            if not buf:
                return []
            if n >= len(buf):
                return list(buf)
            return list(buf)[-n:]

    # ── boucle de mise à jour ─────────────────────────────────────
    def _loop(self):
        while not self._stop:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(0.02)   # 50 Hz : accéléro réactif sans saturer le CPU

    def _read_buf(self, port):
        if port is None:
            return []
        try:
            buf = self.device.live_buf[port]
            return list(buf)
        except Exception:
            return []

    # Seuil mini du score de qualité PPG pour mettre à jour ``self.bpm``.
    # Sous ce seuil : signal jugé bruité (électrode débranchée, mouvement)
    # → on garde la dernière valeur stable plutôt que dériver vers du n'importe quoi.
    _BPM_MIN_SCORE = 0.5

    def _update(self):
        # live_buf est décimé : un échantillon tous les 8 frames @ SAMPLING_HZ
        freq = getattr(self.device, "frequency", 1000)

        if self.ppg_port is not None:
            # BPM sur les ~3 dernières secondes PLEIN DÉBIT (3000 @ 1 kHz).
            # Mutualise ``_estimate_bpm_and_score`` du calibrage : smoothing
            # box + filtre min/max gap + score qualité. Sous ``_BPM_MIN_SCORE``
            # → on garde la dernière valeur stable (rejet bruit / décrochage).
            win = self._read_fr(self.ppg_port, 3 * freq)
            if len(win) >= freq:
                bpm, score = _estimate_bpm_and_score(win, freq)
                if (score >= self._BPM_MIN_SCORE
                        and 40 <= bpm <= 220):
                    with self._lock:
                        self.bpm = self.bpm * 0.7 + bpm * 0.3

        if self.eda_port is not None:
            buf = self._read_buf(self.eda_port)
            if buf:
                eda_now = statistics.mean(buf[-min(len(buf), 60):])
                with self._lock:
                    self.eda = self.eda * 0.8 + eda_now * 0.2

        if self.emg_port is not None:
            # σ EMG sur les 1000 derniers échantillons PLEIN DÉBIT (~1 s
            # @ 1 kHz) — même cadence que la calibration ⇒ σ_raw cohérent
            # avec ``emg_rest`` / ``emg_flex``. Avec live_buf décimé 1:8,
            # σ_raw était fortement sous-estimée (le bruit large-bande
            # disparaît à la décimation) ⇒ seuil jamais franchi.
            win = self._read_fr(self.emg_port, 1000)
            if len(win) >= 50:
                sigma_raw = statistics.pstdev(win)
                sigma_amp = self.emg_rest + self.emg_gain * (sigma_raw - self.emg_rest)
                with self._lock:
                    self.emg_sigma = sigma_amp
                    self.emg_active_raw = sigma_amp >= self.emg_thresh

        if self.x_port is not None:
            # x_norm sur les 50 derniers échantillons PLEIN DÉBIT (~50 ms
            # @ 1 kHz) : assez court pour rester réactif, assez long pour
            # filtrer le bruit. Avant : 10 × ~8 ms = 80 ms via live_buf
            # décimé ⇒ retard perçu et faible résolution.
            win = self._read_fr(self.x_port, 50)
            if win:
                x_now = statistics.mean(win)
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
            win = self._read_fr(self.y_port, 50)
            if win:
                y_now = statistics.mean(win)
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
        self._smoothed_stress = 0.0   # 0..1 visible côté UI

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
        # Indicateur visible 0..1 : on remappe les valeurs négatives (très
        # calme) à 0. Lissage exponentiel comme le facteur de vitesse.
        stress_pos = max(0.0, min(1.0, stress))
        self._smoothed_stress = (self._smoothed_stress * 0.9
                                  + stress_pos * 0.1)
        # mapping linéaire : stress  -0.8 → 2.0 ; 0 → 1.0 ; 1 → 0.3
        if stress >= 0:
            target = 1.0 - 0.7 * stress
        else:
            target = 1.0 + (-stress) * 1.25       # 1 + 0.8*1.25 = 2.0
        self._smoothed = self._smoothed * 0.9 + target * 0.1
        return max(0.3, min(2.0, self._smoothed))

    def stress(self) -> float:
        """Niveau de stress lissé (0 = repos / calme, 1 = stress max).
        Combinaison max(stress_bpm, stress_eda) ⇒ le pire signal pilote."""
        return max(0.0, min(1.0, self._smoothed_stress))


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
        return any(e.type == pygame.KEYDOWN
                   and e.key in (pygame.K_p, pygame.K_TAB)
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
        return any(e.type == pygame.KEYDOWN
                   and e.key in (pygame.K_p, pygame.K_TAB)
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
