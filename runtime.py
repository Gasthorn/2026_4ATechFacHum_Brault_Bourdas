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
import random
import statistics
import threading
import time
from typing import Optional

import pygame

# Détection PPG mutualisée avec le calibrage (source unique : signal
# lisser → seuil mean+0.35σ → pics avec min/max gap → score qualité).
# Évite la dérive entre la σ_rest calibrée et le BPM live.
from calibrage.config import EMG_CYCLE_SECONDS
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
        # Capteurs sautés à la calibration → simulés ici (signal démo) pour
        # que le jeu reste jouable.
        ppg = calib.get("ppg", {}) or {}
        emg = calib.get("emg", {}) or {}
        eda = calib.get("eda", {}) or {}
        ports = calib.get("ports", {}) or {}
        skipped = calib.get("skipped", {}) or {}

        # JSON stocke les ports en BASE 1 (`int(x_axis + 1)` côté calibrage)
        # alors que `device.live_buf` est indexé en BASE 0 → soustraire 1.
        # Sans ça, runtime lit le MAUVAIS canal et la pièce part gauche/
        # droite aléatoirement.
        def _p(v):
            return (v - 1) if isinstance(v, int) and v > 0 else None
        self.ppg_port = _p(ppg.get("port"))
        self.eda_port = _p(eda.get("port"))
        self.emg_port = _p(emg.get("port"))
        self.x_port   = _p(ports.get("x"))
        self.y_port   = _p(ports.get("y"))
        # Skip explicite (JSON) OU port absent → sim démo pour ce capteur.
        self.sim_ppg   = bool(skipped.get("ppg", self.ppg_port is None))
        self.sim_eda   = bool(skipped.get("eda", self.eda_port is None))
        self.sim_emg   = bool(skipped.get("emg", self.emg_port is None))
        self.sim_accel = bool(skipped.get(
            "accel", self.x_port is None or self.y_port is None))
        # Valeurs de repos : défauts plausibles si capteur sauté (sinon le
        # modulateur lirait 0 et calculerait un delta absurde).
        self.bpm_rest = ppg.get("bpm_rest", 70) or 70
        self.eda_rest = eda.get("rest", 500) or 500
        self.emg_rest   = emg.get("sigma_rest", 0.0) or 0.0
        self.emg_thresh = emg.get("threshold", 1.0) or 1.0
        self.emg_gain   = emg.get("gain", 1.0) or 1.0
        if self.sim_emg:
            # EMG simulé : seuil très haut → jamais "actif" (pas de rotation
            # parasite). Le joueur peut toujours utiliser ↑ au clavier.
            self.emg_rest, self.emg_thresh, self.emg_gain = 1.0, 1e9, 1.0
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

        # Horloge sim + RNG (sim_* basé sur monotonic, reproductible côté
        # caractéristiques mais pas bit-exact).
        self._sim_t0 = time.monotonic()
        self._sim_rng = random.Random(1234)
        # Suivi de la durée de contraction EMG (≥ 0.5 s pour tourner pièce).
        self._emg_hold_since = 0.0
        self._emg_hold_fired = False

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

    def _live_freq(self):
        """Fréquence effective du live_buf (décimé 1:8 vs acquisition)."""
        base = getattr(self.device, "frequency", 1000) or 1000
        return max(1, int(round(base / 8)))

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
        # Toutes les lectures passent par ``device.live_buf`` (décimé 1:8,
        # ~125 Hz @ SAMPLING_HZ=1000) — MÊME source que la dernière page du
        # calibrage (`_live_emg`/`_live_bpm`/`_live_eda`) qui marche déjà bien.
        # σ EMG calibrées (`emg_rest`/`emg_flex` enregistrées sur recorded brut)
        # sont équivalentes en σ population à celles sur live_buf décimé pour
        # signal stationnaire — la décimation préserve σ. Garder le même chemin
        # que le calibrage garantit la cohérence seuil ↔ mesure.
        live_freq = self._live_freq()
        t = time.monotonic() - self._sim_t0

        if self.sim_ppg:
            # BPM démo : oscille doucement autour du repos (~±6 BPM).
            bpm_sim = self.bpm_rest + 6.0 * math.sin(t / 7.0) \
                      + self._sim_rng.uniform(-1.0, 1.0)
            with self._lock:
                self.bpm = self.bpm * 0.85 + bpm_sim * 0.15
        elif self.ppg_port is not None:
            buf = self._read_buf(self.ppg_port)
            if len(buf) >= live_freq:
                bpm, score = _estimate_bpm_and_score(buf, live_freq)
                if (score >= self._BPM_MIN_SCORE
                        and 40 <= bpm <= 220):
                    with self._lock:
                        self.bpm = self.bpm * 0.7 + bpm * 0.3

        if self.sim_eda:
            # EDA démo : dérive tonique très lente (~±30 ADC) + petit bruit.
            eda_sim = self.eda_rest + 30.0 * math.sin(t / 18.0) \
                      + 8.0 * math.sin(t / 4.0) \
                      + self._sim_rng.uniform(-2.0, 2.0)
            with self._lock:
                self.eda = self.eda * 0.85 + eda_sim * 0.15
        elif self.eda_port is not None:
            buf = self._read_buf(self.eda_port)
            if buf:
                eda_now = statistics.mean(buf[-min(len(buf), 60):])
                with self._lock:
                    self.eda = self.eda * 0.8 + eda_now * 0.2

        if self.sim_emg:
            # EMG démo : σ très basse, jamais "actif" → rotation EMG inerte.
            # Le joueur garde la touche ↑ pour tourner (handler clavier OK
            # même en mode CAPTEURS — UP est lu dans `action_rotate`).
            with self._lock:
                self.emg_sigma = 0.0
                self.emg_active_raw = False
        elif self.emg_port is not None:
            # Recopie de ``calibrage.App._live_emg`` : σ sur la dernière
            # ~EMG_CYCLE_SECONDS du live_buf, puis excursion amplifiée
            # (gain) au-dessus du repos. Seuil reste en σ BRUT.
            buf = self._read_buf(self.emg_port)
            win_n = max(8, int(live_freq * EMG_CYCLE_SECONDS))
            recent = buf[-win_n:] if len(buf) > win_n else buf
            if len(recent) > 1:
                sigma_raw = statistics.pstdev(recent)
                sigma_amp = self.emg_rest + self.emg_gain * (sigma_raw - self.emg_rest)
                sigma_amp = max(0.0, sigma_amp)
                with self._lock:
                    self.emg_sigma = sigma_amp
                    self.emg_active_raw = sigma_amp >= self.emg_thresh

        if self.sim_accel:
            # Accéléro démo : pas de mouvement → pièce ne dérive pas seule.
            # Le joueur garde ← → clavier en mode CAPTEURS.
            with self._lock:
                self.x_norm = 0.0
                self.y_norm = 0.0
            return

        # x_norm/y_norm : moyenne des ~8 derniers échantillons live (~64 ms)
        # → réactif sans bruit. Span SYMÉTRIQUE (max des deux côtés du repos)
        # pour qu'un balayage asymétrique ne donne pas de norm démesurée
        # sur le côté étroit (pas de mouvement parasite au repos).
        def _norm(port, rest, vmin, vmax, invert):
            buf = self._read_buf(port)
            if not buf:
                return None
            v = statistics.mean(buf[-min(len(buf), 8):])
            span = max(1, rest - vmin, vmax - rest)
            n = (v - rest) / span
            if invert:
                n = -n
            return max(-1.5, min(1.5, n))

        if self.x_port is not None:
            nx = _norm(self.x_port, self.x_rest, self.x_min, self.x_max,
                       self.invert_x)
            if nx is not None:
                with self._lock:
                    self.x_norm = nx
        if self.y_port is not None:
            ny = _norm(self.y_port, self.y_rest, self.y_min, self.y_max,
                       self.invert_y)
            if ny is not None:
                with self._lock:
                    self.y_norm = ny

    # ── accesseurs synchronisés ──────────────────────────────────
    def snapshot(self):
        with self._lock:
            return dict(bpm=self.bpm, eda=self.eda,
                        emg_sigma=self.emg_sigma,
                        emg_active=self.emg_active_raw,
                        x_norm=self.x_norm, y_norm=self.y_norm)

    # Durée minimale de contraction EMG (en s) pour valider une rotation.
    EMG_HOLD_SEC = 0.5

    def consume_emg_rotation(self) -> bool:
        """Retourne True UNE SEULE FOIS par contraction EMG soutenue
        ≥ ``EMG_HOLD_SEC`` (0.5 s). Tant que le muscle reste contracté après
        le déclenchement → False. Relâcher le muscle réarme."""
        with self._lock:
            active = self.emg_active_raw
        now = time.time()
        if not active:
            self._emg_hold_since = 0.0
            self._emg_hold_fired = False
            return False
        if self._emg_hold_since == 0.0:
            self._emg_hold_since = now
        if (not self._emg_hold_fired
                and now - self._emg_hold_since >= self.EMG_HOLD_SEC):
            self._emg_hold_fired = True
            return True
        return False


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
        # Pire des deux signaux pilote, clampé [-0.8, 1.0].
        stress = max(-0.8, min(1.0, max(stress_bpm, stress_eda)))
        # Indicateur 0..1 (négatifs = très calme remappés à 0), lissé.
        self._smoothed_stress = (self._smoothed_stress * 0.9
                                  + max(0.0, stress) * 0.1)
        # Mapping linéaire : -0.8 → 2.0 ; 0 → 1.0 ; 1 → 0.3.
        target = 1.0 - 0.7 * stress if stress >= 0 else 1.0 - 1.25 * stress
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
    """Contrôles clavier classiques. EMG (si ``bio`` fourni) déclenche AUSSI
    la rotation : le joueur peut tourner la pièce en contractant le muscle
    même dans le mode CLAVIER."""

    def __init__(self, bio: Optional["BioState"] = None):
        self._events = []
        self._keys   = {}
        self.bio = bio

    def update(self, events):
        self._events = events
        self._keys   = pygame.key.get_pressed()

    def action_rotate(self) -> bool:
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_UP
                 for e in self._events)
        # EMG soutenue ≥ 0.5 s ⇒ rotation (clavier mode aussi : on garde ↑).
        emg = self.bio.consume_emg_rotation() if self.bio is not None else False
        return kb or emg

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
    """Contrôles BITalino : accéléromètre G/D = mouvement, axe Y (haut OU
    bas) = soft drop, axe Y très ample (< -1.0) = hard drop, EMG = rotation.

    Anti-rebond X : un coup à gauche revient au repos en OVERSHOOTANT
    légèrement à droite. On exige que l'axe RESTE dans une bande proche de
    zéro pendant ≥ SETTLE_S avant d'accepter le sens opposé. Même latch
    réutilisé sur Y pour qualifier le hard drop.

    Rotation : clavier ↑ + contraction EMG soutenue (≥ EMG_HOLD_SEC). PAS
    de rotation par l'accéléromètre. Pause / restart restent au clavier.
    """

    SETTLE_THRESH   = 0.15  # |norm| < seuil ⇒ axe considéré au repos
    SETTLE_S        = 0.30  # durée mini de repos avant sens opposé
    MOVE_COOLDOWN_S = 0.5   # 2 inputs/sec max sur axe X
    SOFT_DROP_THRESH = 0.4  # |y_norm| > seuil ⇒ soft drop (haut OU bas)

    def __init__(self, bio: BioState):
        self.bio = bio
        self._events = []
        self._keys   = {}
        self._last_hard_drop_t = 0.0
        # État axe X (mouvement gauche/droite)
        self._x_last_side    = 0     # dernier côté EMIS (-1, 0, +1)
        self._x_last_emit_t  = 0.0
        self._x_settle_since = None  # timestamp d'entrée dans bande neutre
        self._x_was_settled  = False # repos confirmé ≥ SETTLE_S depuis dernier emit
        # État axe Y (servait au tilt-up retiré ; gardé pour anti-rebond hard drop)
        self._y_settle_since  = None
        self._y_was_settled   = False

    def update(self, events):
        self._events = events
        self._keys   = pygame.key.get_pressed()

    def _now_ms(self):
        return pygame.time.get_ticks()

    def action_rotate(self) -> bool:
        # Clavier ↑ + contraction EMG soutenue ≥ 0.5 s. PAS d'accéléro.
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_UP
                 for e in self._events)
        return kb or self.bio.consume_emg_rotation()

    def _update_settle(self, axis: str, value: float, now: float):
        """Met à jour le latch "repos confirmé" pour un axe (X ou Y).
        Doit avoir passé ≥ SETTLE_S dans la bande neutre |v| < SETTLE_THRESH
        avant d'être déclaré settled → filtre les overshoots de décélération."""
        since_attr = f"_{axis}_settle_since"
        settled_attr = f"_{axis}_was_settled"
        if abs(value) < self.SETTLE_THRESH:
            since = getattr(self, since_attr)
            if since is None:
                setattr(self, since_attr, now)
            elif now - since >= self.SETTLE_S:
                setattr(self, settled_attr, True)
        else:
            setattr(self, since_attr, None)

    def action_hard_drop(self) -> bool:
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE
                 for e in self._events)
        snap = self.bio.snapshot()
        # Anti-rebond Y rafraîchi ici (plus appelé par tilt-up retiré).
        y = snap["y_norm"]
        t = time.time()
        self._update_settle("y", y, t)
        # Mouvement DOWN très ample sur Y → hard drop. Exige repos préalable
        # + cooldown 600 ms.
        if y < -1.0 and self._y_was_settled and t - self._last_hard_drop_t > 0.6:
            self._last_hard_drop_t = t
            self._y_was_settled = False
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
        side = 1 if x > dz else (-1 if x < -dz else 0)
        now = time.time()
        self._update_settle("x", x, now)
        if side == 0:
            return 0
        # Sens opposé : exige que l'axe AIT été au repos depuis le dernier
        # emit → filtre l'overshoot de décélération.
        if side == -self._x_last_side and not self._x_was_settled:
            return 0
        # Même sens maintenu → cooldown 500 ms (2 inputs/sec max).
        if (side == self._x_last_side
                and now - self._x_last_emit_t < self.MOVE_COOLDOWN_S):
            return 0
        self._x_last_side    = side
        self._x_last_emit_t  = now
        self._x_was_settled  = False
        self._x_settle_since = None
        return side

    def get_soft_drop(self) -> bool:
        snap = self.bio.snapshot()
        # Soft drop si inclinaison Y franche (HAUT ou BAS) au-delà de la
        # zone morte SOFT_DROP_THRESH. Au-delà de -1.0 ⇒ hard drop a la
        # priorité (test fait avant dans la boucle de jeu).
        return abs(snap["y_norm"]) > self.SOFT_DROP_THRESH

    def label(self):
        return "Capteurs"
