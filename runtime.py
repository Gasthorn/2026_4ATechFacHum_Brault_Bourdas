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
        # que le jeu reste jouable. Indices port (cal JSON) sont en BASE 1 :
        # convertir en BASE 0 pour `device.live_buf`. None = capteur absent.
        ppg = calib.get("ppg", {}) or {}
        emg = calib.get("emg", {}) or {}
        eda = calib.get("eda", {}) or {}
        ports = calib.get("ports", {}) or {}
        skipped = calib.get("skipped", {}) or {}

        # JSON stocke les ports en BASE 1 (`int(x_axis + 1)` côté calibrage)
        # alors que `device.live_buf` est indexé en BASE 0 → soustraire 1.
        # Sans ça, runtime lit le MAUVAIS canal et la pièce part gauche/
        # droite aléatoirement alors que le radar de calibrage (qui lit
        # `sample[self.x_axis]` en base 0) fonctionne parfaitement.
        def _p(v):
            return (v - 1) if isinstance(v, int) and v > 0 else None
        self.ppg_port = _p(ppg.get("port"))
        self.eda_port = _p(eda.get("port"))
        self.emg_port = _p(emg.get("port"))
        self.x_port   = _p(ports.get("x"))
        self.y_port   = _p(ports.get("y"))
        # Skip explicite (JSON) OU port absent → sim démo pour ce capteur.
        self.sim_ppg   = bool(skipped.get("ppg",   self.ppg_port is None))
        self.sim_eda   = bool(skipped.get("eda",   self.eda_port is None))
        self.sim_emg   = bool(skipped.get("emg",   self.emg_port is None))
        self.sim_accel = bool(skipped.get("accel",
                                          self.x_port is None
                                          or self.y_port is None))
        # Valeurs de repos : défauts plausibles quand le capteur a été sauté
        # (sinon le modulateur lirait 0 et calculerait un delta absurde).
        self.bpm_rest = ppg.get("bpm_rest", 70) or 70
        if self.sim_ppg and not self.bpm_rest:
            self.bpm_rest = 70
        self.eda_rest = eda.get("rest", 500) or 500
        if self.sim_eda and not self.eda_rest:
            self.eda_rest = 500
        self.emg_rest   = emg.get("sigma_rest", 0.0) or 0.0
        self.emg_thresh = emg.get("threshold", 1.0) or 1.0
        self.emg_gain   = emg.get("gain", 1.0) or 1.0
        if self.sim_emg:
            # EMG simulé : seuil très haut → jamais "actif" (pas de rotation
            # parasite). Le joueur peut toujours utiliser ↑ au clavier.
            self.emg_rest = 1.0
            self.emg_thresh = 1e9
            self.emg_gain = 1.0
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
            # Accéléro démo : pas de mouvement → pièce ne dérive pas toute
            # seule. Le joueur garde ← → clavier en mode CAPTEURS (les
            # handlers BitalinoInputHandler lisent x_norm ; à 0 ⇒ aucun
            # input parasite).
            with self._lock:
                self.x_norm = 0.0
                self.y_norm = 0.0
        if self.x_port is not None and not self.sim_accel:
            # x_norm : moyenne des ~8 derniers échantillons live (~64 ms)
            # → réactif sans bruit. Même approche que le radar de calibrage.
            # Span SYMÉTRIQUE (max gauche/droite) : un balayage asymétrique
            # à la calibration ne donne plus de norm démesurée sur le côté
            # étroit → pas de mouvement parasite au repos.
            buf = self._read_buf(self.x_port)
            if buf:
                x_now = statistics.mean(buf[-min(len(buf), 8):])
                span = max(1, self.x_rest - self.x_min,
                            self.x_max - self.x_rest)
                nx = (x_now - self.x_rest) / span
                if self.invert_x:
                    nx = -nx
                with self._lock:
                    self.x_norm = max(-1.5, min(1.5, nx))

        if self.y_port is not None and not self.sim_accel:
            buf = self._read_buf(self.y_port)
            if buf:
                y_now = statistics.mean(buf[-min(len(buf), 8):])
                span = max(1, self.y_rest - self.y_min,
                            self.y_max - self.y_rest)
                ny = (y_now - self.y_rest) / span
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

    # Anti-rebond physique : un coup d'accéléro à gauche revient au repos en
    # OVERSHOOTANT légèrement à droite. Pour rejeter cet overshoot on exige
    # que l'axe RESTE dans une bande proche de zéro pendant ≥ SETTLE_S avant
    # d'accepter le sens opposé. Un vrai geste a forcément ce temps de pause.
    SETTLE_THRESH   = 0.15  # |norm| < seuil ⇒ axe considéré au repos
    SETTLE_S        = 0.30  # durée mini de repos avant sens opposé
    # Limite stricte de fréquence des mouvements accéléro : 2 inputs / sec.
    MOVE_COOLDOWN_S = 0.5
    # Tilt UP : ≥ +TILT_UP_THRESH pendant edge → rotation. Anti-rebond + cooldown.
    TILT_UP_THRESH  = 0.4
    TILT_UP_COOLDOWN_S = 0.5

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
        # État axe Y (rotation tilt-up — soft drop reste continu)
        self._y_was_up        = False
        self._y_last_rot_t    = 0.0
        self._y_settle_since  = None
        self._y_was_settled   = False

    def update(self, events):
        self._events = events
        self._keys   = pygame.key.get_pressed()

    def _now_ms(self):
        return pygame.time.get_ticks()

    def action_rotate(self) -> bool:
        # Sources de rotation cumulatives : clavier ↑, EMG (≥ 0.5 s), tilt
        # vers le haut (y_norm > +TILT_UP_THRESH après settle).
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_UP
                 for e in self._events)
        emg = self.bio.consume_emg_rotation()
        return kb or emg or self._tilt_up_rotation()

    def _tilt_up_rotation(self) -> bool:
        """Front montant tilt-up + anti-rebond settle + cooldown 500 ms.
        Filtre l'overshoot vertical (un coup vers le BAS revient au repos en
        débordant en haut → sans settle, déclencherait une rotation parasite)."""
        snap = self.bio.snapshot()
        y = snap["y_norm"]
        now = time.time()
        # Latch "repos confirmé" sur Y (cf. axe X).
        if abs(y) < self.SETTLE_THRESH:
            if self._y_settle_since is None:
                self._y_settle_since = now
            elif now - self._y_settle_since >= self.SETTLE_S:
                self._y_was_settled = True
        else:
            self._y_settle_since = None
        up = y > self.TILT_UP_THRESH
        fire = False
        if up and not self._y_was_up:
            # Front montant. Exige un repos confirmé AVANT (filtre overshoot
            # depuis un flick BAS) + cooldown 500 ms après la précédente
            # rotation.
            cooled = now - self._y_last_rot_t >= self.TILT_UP_COOLDOWN_S
            if self._y_was_settled and cooled:
                fire = True
                self._y_last_rot_t = now
                self._y_was_settled = False
        self._y_was_up = up
        return fire

    def action_hard_drop(self) -> bool:
        kb = any(e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE
                 for e in self._events)
        snap = self.bio.snapshot()
        # Mouvement DOWN très ample sur Y → hard drop. Exige aussi un repos
        # préalable (anti-rebond : un flick HAUT peut overshooter sous -1.0
        # au retour). Cooldown 600 ms.
        if snap["y_norm"] < -1.0:
            t = time.time()
            if self._y_was_settled and t - self._last_hard_drop_t > 0.6:
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
        if x > dz:
            side = +1
        elif x < -dz:
            side = -1
        else:
            side = 0
        now = time.time()
        # Latch "repos confirmé" : doit passer ≥ SETTLE_S dans la bande
        # neutre, puis l'axe peut s'écarter → on retient qu'il a été au
        # repos. Empêche un overshoot rapide (axe qui traverse 0 sans
        # vraiment s'arrêter) de compter comme un retour au neutre valide.
        if abs(x) < self.SETTLE_THRESH:
            if self._x_settle_since is None:
                self._x_settle_since = now
            elif now - self._x_settle_since >= self.SETTLE_S:
                self._x_was_settled = True
        else:
            self._x_settle_since = None
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
        # Soft drop = inclinaison BAS modérée (entre 0.4 et 1.0). Continu
        # tant que l'axe Y reste sous le seuil (mécanique Tetris standard).
        return -1.0 <= snap["y_norm"] < -0.4

    def label(self):
        return "Capteurs"
