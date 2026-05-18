"""Application de calibrage : machine d'état et boucle principale."""

import json
import math
import random
import statistics
import threading
import time
from collections import deque

import pygame

from .config import *  # noqa: F401,F403
from .config import _darken
from .detection import *  # noqa: F401,F403
from .detection import _col_std, _estimate_bpm_and_score
from .device import CalibrationDevice, SimulatedDevice  # noqa: F401
from .ui import *  # noqa: F401,F403


# ─────────────────────────────────────────────
#  États
# ─────────────────────────────────────────────
STATE_DETECT   = "detect"
STATE_INTRO    = "intro"
STATE_REST     = "rest"
STATE_LR       = "lr"
STATE_UD       = "ud"
STATE_HR       = "hr"
STATE_EMG      = "emg"
STATE_EDA      = "eda"
STATE_DEADZONE = "dead"
STATE_DONE     = "done"

# Ordre canonique des étapes de calibration : cœur → accéléro → EMG → zone
# morte. SOURCE UNIQUE — numéros de badge, frise latérale et progression en
# dérivent (changer l'ordre ici suffit, plus de numéros codés en dur).
CALIB_STEPS = [
    (STATE_REST,     "REPOS + POULS",    "I"),
    (STATE_HR,       "RYTHME CARDIAQUE", "Z"),
    (STATE_LR,       "GAUCHE / DROITE",  "J"),
    (STATE_UD,       "HAUT / BAS",       "L"),
    (STATE_EMG,      "MUSCLE / EMG",     "S"),
    (STATE_EDA,      "EDA / SUDATION",   "O"),
    (STATE_DEADZONE, "ZONE MORTE",       "T"),
]
_STEP_NO = {st: f"{i + 1:02d}" for i, (st, _lbl, _shp) in enumerate(CALIB_STEPS)}
_STEP_ORDER = ([STATE_INTRO] + [st for st, _l, _s in CALIB_STEPS] + [STATE_DONE])

# Étapes où le bouton PASSER (skip d'un capteur) est proposé. REPOS exclu :
# il fournit la référence accéléro + isolation cœur, il reste obligatoire.
_SKIP_STATES = (STATE_HR, STATE_LR, STATE_UD, STATE_EMG, STATE_EDA)


def _slider_to_emg_gain(v):
    """Position curseur 0..1 → gain EMG (EMG_GAIN_MIN..EMG_GAIN_MAX)."""
    return EMG_GAIN_MIN + max(0.0, min(1.0, v)) * (EMG_GAIN_MAX - EMG_GAIN_MIN)


def _emg_gain_to_slider(g):
    """Gain EMG → position curseur 0..1 (inverse de _slider_to_emg_gain)."""
    span = EMG_GAIN_MAX - EMG_GAIN_MIN
    return 0.0 if span <= 0 else max(0.0, min(1.0, (g - EMG_GAIN_MIN) / span))


# ─────────────────────────────────────────────
#  Application
# ─────────────────────────────────────────────
class App:
    def __init__(self, screen, address):
        self.screen   = screen
        self.address  = address
        w, h = screen.get_size()
        self.layout   = Layout(w, h)
        self.theme    = Theme(w, h)
        self.clock    = pygame.time.Clock()
        self._cached_size = (w, h)
        self._rebuild_overlays()
        self.t0       = time.time()

        self.state    = STATE_DETECT
        self.recording_until = 0.0

        # Détection
        self.detect_status = "idle"   # idle / scanning / ok / fail
        self.detect_error  = ""
        self.detect_started_at = 0.0
        self.device   = None
        self.acq_thread = None
        self._demo    = False

        # Données (échantillons + ports/seuils détectés)
        self._reset_calibration_data()

        # Composants
        self.btn_main        = Button("[  OK  ]", accent=PHOSPHOR, hot_key=pygame.K_RETURN)
        self.btn_retry       = Button("[  RÉESSAYER  ]", accent=AMBER, hot_key=pygame.K_r)
        self.btn_demo        = Button("[  MODE DÉMO  ]", accent=PHOSPHOR_MID, hot_key=pygame.K_d)
        self.btn_recalibrate = Button("[  RECALIBRER  ]", accent=DANGER)
        self.btn_skip        = Button("[  PASSER  ]", accent=DANGER)
        # Trois zones mortes réglables (accéléro / cœur / EMG) + 2 inverseurs.
        self.slider          = Slider(value=0.3, accent=AMBER)
        self.slider_emg      = Slider(value=EMG_THRESHOLD_FRAC, accent=PHOSPHOR_MID)
        self.slider_emg_gain = Slider(value=_emg_gain_to_slider(EMG_GAIN),
                                      accent=PHOSPHOR)
        self.btn_inv_x       = Button("INVERSER G/D", accent=PHOSPHOR_MID)
        self.btn_inv_y       = Button("INVERSER H/B", accent=PHOSPHOR_MID)
        # Recalibrage ciblé : sélecteur cases + boutons valider/annuler
        self.btn_recal_sel_ppg   = Button("COEUR",        accent=DANGER)
        self.btn_recal_sel_accel = Button("ACCELERO",     accent=AMBER)
        self.btn_recal_sel_emg   = Button("EMG",          accent=PHOSPHOR_MID)
        self.btn_recal_sel_eda   = Button("EDA",          accent=TETRO["O"])
        self.btn_recal_confirm   = Button("[  RECALIBRER  ]", accent=DANGER)
        self.btn_recal_cancel    = Button("[  ANNULER  ]",    accent=PHOSPHOR)
        self._port_keys      = ["x", "y", "z", "ppg", "emg", "eda"]
        self.btn_port_dec    = [Button("<", accent=PHOSPHOR_MID)
                                for _ in self._port_keys]
        self.btn_port_inc    = [Button(">", accent=PHOSPHOR_MID)
                                for _ in self._port_keys]

        self.log_lines = deque(maxlen=10)
        self._log("SYSTEM BOOT ............................. OK")
        self._log("AWAITING DEVICE DETECTION...")
        self._start_detection()

    # ── Logs ───────────────────────────────────────────────────────
    def _log(self, msg):
        self.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    # ── Rebuild des surfaces selon la taille ───────────────────────
    def _rebuild_overlays(self):
        w, h = self.screen.get_size()
        self.bg_grid   = make_grid(w, h)
        self.scanlines = make_scanlines(w, h, alpha=22, spacing=3)
        self.vignette  = make_vignette(w, h)
        self._cached_size = (w, h)

    def _maybe_resize(self):
        if self.screen.get_size() != self._cached_size:
            w, h = self.screen.get_size()
            self.layout.compute(w, h)
            self.theme.update(w, h)
            self._rebuild_overlays()

    # ── Détection BITalino ─────────────────────────────────────────
    def _start_detection(self, force_demo=False):
        # Reset éventuelle connexion précédente
        if self.device is not None:
            try:
                self.device.stop_flag = True
                self.device.stop()
                self.device.close()
            except Exception:
                pass
            self.device = None

        self._demo = force_demo
        self.detect_status = "scanning"
        self.detect_error  = ""
        self.detect_started_at = time.time()
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        # Petit délai mini pour que l'utilisateur voie la phase de scan
        target_min = self.detect_started_at + 1.4
        if self._demo:
            self._log("DEMO MODE ENABLED — using simulated sensor data")
            d = SimulatedDevice()
            self.acq_thread = threading.Thread(target=d.loop, daemon=True)
            self.acq_thread.start()
            self.device = d
            time.sleep(max(0, target_min - time.time()))
            self.detect_status = "ok"
            self._log(f"DEVICE READY  → SIMULATED  @ {SAMPLING_HZ} Hz")
            return
        if not PLUX_AVAILABLE:
            time.sleep(max(0, target_min - time.time()))
            self.detect_status = "fail"
            self.detect_error  = "Module 'plux' introuvable (PLUX-API-Python3)"
            self._log("DETECTION FAILED — plux module not found")
            return
        try:
            self._log(f"PROBING {self.address} ...")
            d = CalibrationDevice(self.address)
            d.frequency = SAMPLING_HZ
            d.start(d.frequency, ALL_PORTS, 16)
            self.acq_thread = threading.Thread(target=d.loop, daemon=True)
            self.acq_thread.start()
            self.device = d
            time.sleep(max(0, target_min - time.time()))
            self.detect_status = "ok"
            self._log(f"DEVICE READY  → BITALINO @ {SAMPLING_HZ} Hz")
        except Exception as exc:
            time.sleep(max(0, target_min - time.time()))
            self.detect_status = "fail"
            self.detect_error  = str(exc)
            self._log(f"DETECTION FAILED — {exc}")

    # ── Acquisition control ────────────────────────────────────────
    def _start_recording(self, seconds):
        with self.device.lock:
            self.device.recorded = []
            self.device.recording = True
        self.recording_until = time.time() + seconds

    def _stop_recording(self):
        with self.device.lock:
            self.device.recording = False
            return list(self.device.recorded)

    def _rec_freq(self):
        """Fréquence d'acquisition des échantillons enregistrés (non décimés)."""
        return self.device.frequency if self.device is not None else SAMPLING_HZ

    def _recording_failed(self, samples, retry_label):
        """True (+ log/bouton RÉESSAYER) si l'enregistrement est vide."""
        if samples:
            return False
        self._log("ERR: NO SAMPLES — CHECK BITALINO LINK")
        self.btn_main.label = retry_label
        return True

    # ── Boucle ─────────────────────────────────────────────────────
    def run(self):
        running = True
        while running:
            self.clock.tick(FPS)
            t_now = time.time() - self.t0
            mouse = pygame.mouse.get_pos()
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
                        (new_w, new_h), pygame.RESIZABLE | pygame.DOUBLEBUF
                    )
            self._maybe_resize()
            self._update(t_now, mouse, events)
            self._draw(t_now)
            pygame.display.flip()
        return self.state == STATE_DONE

    # ── Update ─────────────────────────────────────────────────────
    def _update(self, t, mouse, events):
        if self.state == STATE_DETECT:
            if self.detect_status == "ok":
                self.state = STATE_INTRO
                return
            if self.detect_status == "fail":
                if self.btn_retry.update(mouse, events):
                    self._log("RETRYING DETECTION...")
                    self._start_detection(force_demo=False)
                if self.btn_demo.update(mouse, events):
                    self._start_detection(force_demo=True)
            return

        recording = self.recording_until > 0 and time.time() < self.recording_until
        if self.state in (STATE_INTRO, STATE_REST, STATE_LR, STATE_UD,
                          STATE_HR, STATE_EMG):
            self.btn_main.enabled = not recording
            if self.btn_main.update(mouse, events):
                self._on_main_button()
            if self.state in _SKIP_STATES and not recording:
                if self.btn_skip.update(mouse, events):
                    self._skip_step()
                    return
            # Stepper de port inline : corriger le port du capteur de
            # l'étape courante (CŒUR sur REPOS/POULS, axes, EMG).
            pkey = self._step_port_key()
            if pkey is not None:
                pidx = self._port_keys.index(pkey)
                if self.btn_port_dec[pidx].update(mouse, events):
                    self._cycle_port(pkey, -1)
                if self.btn_port_inc[pidx].update(mouse, events):
                    self._cycle_port(pkey, +1)

        if self.state == STATE_DEADZONE:
            if self.recal_select_mode:
                # Selecteur de recalibrage : cases a cocher
                for key, btn in (("ppg",   self.btn_recal_sel_ppg),
                                 ("accel", self.btn_recal_sel_accel),
                                 ("emg",   self.btn_recal_sel_emg),
                                 ("eda",   self.btn_recal_sel_eda)):
                    if btn.update(mouse, events):
                        self.recal_checks[key] = not self.recal_checks[key]
                if self.btn_recal_confirm.update(mouse, events):
                    checked = {k for k, v in self.recal_checks.items() if v}
                    if checked:
                        self._start_recal(checked)
                if self.btn_recal_cancel.update(mouse, events):
                    self.recal_select_mode = False
            else:
                self.slider.update(mouse, events)
                self.slider_emg.update(mouse, events)
                self.slider_emg_gain.update(mouse, events)
                self._apply_emg_threshold()
                if self.btn_inv_x.update(mouse, events):
                    self.invert_x = not self.invert_x
                if self.btn_inv_y.update(mouse, events):
                    self.invert_y = not self.invert_y
                # Editeur de ports toujours actif
                for k, bd, bi in zip(self._port_keys,
                                     self.btn_port_dec, self.btn_port_inc):
                    if bd.update(mouse, events):
                        self._cycle_port(k, -1)
                    if bi.update(mouse, events):
                        self._cycle_port(k, +1)
                self.btn_main.enabled = True
                if self.btn_main.update(mouse, events):
                    self._save_and_finish()
                if self.btn_recalibrate.update(mouse, events):
                    self.recal_select_mode = True
                    self.recal_checks = {"ppg": False, "accel": False,
                                         "emg": False, "eda": False}

        if self.state == STATE_DONE:
            if self.btn_main.update(mouse, events):
                pygame.event.post(pygame.event.Event(pygame.QUIT))

        if self.recording_until > 0 and time.time() >= self.recording_until:
            self.recording_until = 0
            self._on_recording_done()
            # L'auto-détection vient d'écrire les ports : un override manuel
            # choisi dans l'écran d'étape doit reprendre le dessus.
            self._reapply_overrides()

        if isinstance(self.device, SimulatedDevice):
            mode = {
                STATE_INTRO: "rest", STATE_REST: "rest",
                STATE_LR: "lr",      STATE_UD: "ud",
                STATE_HR: "rest",    STATE_EMG: "emg",
                STATE_EDA: "eda",
                STATE_DEADZONE: "radar", STATE_DONE: "radar",
            }.get(self.state, "rest")
            self.device.set_mode(mode)

    def _on_main_button(self):
        if self.state == STATE_INTRO:
            self.state = STATE_REST
            self._log(f"STEP {_STEP_NO[STATE_REST]}/{len(CALIB_STEPS):02d} "
                      f"— REPOS + ISOLATION DU PORT CŒUR")
            return
        # Phases d'enregistrement : (durée, message log, libellé bouton).
        # Source unique — l'ordre logique vit dans _on_recording_done.
        rec_phases = {
            STATE_REST: (REST_SECONDS,
                         f"RECORDING REST BASELINE ({REST_SECONDS:.1f} s)...",
                         "[  ENREGISTREMENT...  ]"),
            STATE_LR:   (MOVE_SECONDS,
                         f"RECORDING LEFT/RIGHT MOTION ({MOVE_SECONDS:.1f} s)...",
                         "[  ENREGISTREMENT...  ]"),
            STATE_UD:   (MOVE_SECONDS,
                         f"RECORDING UP/DOWN MOTION ({MOVE_SECONDS:.1f} s)...",
                         "[  ENREGISTREMENT...  ]"),
            STATE_HR:   (HR_SECONDS,
                         f"RECORDING HEART RATE AT REST ({HR_SECONDS:.1f} s)...",
                         "[  ENREGISTREMENT...  ]"),
            STATE_EMG:  (EMG_SECONDS,
                         f"RECORDING EMG ({EMG_SECONDS:.0f} s) — SUIVEZ "
                         f"LES CONSIGNES À L'ÉCRAN (DURÉES ALÉATOIRES)",
                         "[  SUIVEZ LES CONSIGNES À L'ÉCRAN...  ]"),
            STATE_EDA:  (EDA_SECONDS,
                         f"RECORDING EDA REST LEVEL ({EDA_SECONDS:.1f} s)...",
                         "[  ENREGISTREMENT...  ]"),
        }
        if self.state in rec_phases and self.recording_until == 0:
            secs, msg, label = rec_phases[self.state]
            if self.state == STATE_EMG:
                self._build_emg_plan()   # consignes aléatoires neuves
            self._log(msg)
            self._start_recording(secs)
            self.btn_main.label = label
            return

    def _on_recording_done(self):
        if self.state == STATE_REST:
            self.rest_samples = self._stop_recording()
            if self._recording_failed(self.rest_samples, "[  RÉESSAYER  ]"):
                return
            # Capteur cardiaque calibré EN PREMIER : accéléromètre immobile au
            # repos → seul le pouls (oreille) « bouge encore ». On isole donc
            # le port PPG actif par sa périodicité, dès le départ.
            port, bpm = detect_ppg_from_rest(self.rest_samples,
                                             frequency=self._rec_freq())
            self.ppg_port = port
            self.bpm_rest = bpm
            if port is not None:
                self._log(f"PPG (CŒUR) → PORT {port + 1}   "
                          f"BPM REPOS = {bpm}")
            else:
                self._log("PPG NON DÉTECTÉ — VÉRIFIER LE CAPTEUR D'OREILLE")
            self.state = STATE_HR
            self.btn_main.label = "[  OK, CALIBRER LE POULS DE REPOS  ]"
            return
        if self.state == STATE_HR:
            self.hr_samples = self._stop_recording()
            if self._recording_failed(self.hr_samples,
                                      "[  RÉESSAYER L'ENREGISTREMENT  ]"):
                return
            freq = self._rec_freq()
            if self.ppg_port is not None:
                # Port PPG déjà isolé en phase REPOS : on raffine le BPM repos
                # sur une fenêtre plus longue (mesure dédiée, immobile).
                col = [s[self.ppg_port] for s in self.hr_samples]
                bpm, score = _estimate_bpm_and_score(col, freq)
                ok = (score > PPG_MIN_SCORE
                      and PPG_MIN_BPM <= bpm <= PPG_MAX_BPM)
                if not ok:
                    self._log("ERR: POULS INSTABLE — RESTEZ IMMOBILE, RÉESSAYEZ")
                    self.btn_main.label = "[  RÉESSAYER L'ENREGISTREMENT  ]"
                    return
            else:
                # Repli : REPOS n'a pas isolé le pouls. Axes accéléro pas
                # encore connus (calibrés après) → scan de tous les ports
                # par périodicité.
                port, bpm = detect_ppg_port(self.hr_samples, (),
                                            frequency=freq)
                if port is None or bpm <= 0:
                    self._log("ERR: PPG NON DÉTECTÉ — VÉRIFIER CAPTEUR OREILLE")
                    self.btn_main.label = "[  RÉESSAYER L'ENREGISTREMENT  ]"
                    return
                self.ppg_port = port
            self.bpm_rest = bpm
            self._bpm_live = bpm
            self._log(f"CŒUR CALIBRÉ → PORT {self.ppg_port + 1}   "
                      f"BPM REPOS = {bpm}")
            if self.recal_target == "ppg":   # fin de la tranche PPG
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_LR
            self.btn_main.label = "[  OK, COMMENCER LE BALAYAGE G/D  ]"
            return
        if self.state == STATE_EMG:
            self.emg_samples = self._stop_recording()
            if self._recording_failed(self.emg_samples,
                                      "[  RÉESSAYER L'ENREGISTREMENT  ]"):
                return
            # EMG calibré EN DERNIER : PPG + axes accéléro déjà connus, on
            # les exclut → le port EMG est isolé par élimination (capteur
            # faible : on ne dépend plus de l'amplitude absolue). On confirme
            # par l'enveloppe qui OSCILLE au rythme contracté/relâché.
            port, rsd, fsd = detect_emg_port(
                self.rest_samples, self.emg_samples,
                self._ppg_excl(self.x_axis, self.y_axis, self.z_axis),
                self._rec_freq())
            if port is None:
                self._log("ERR: EMG NON DÉTECTÉ — ALTERNEZ FRANCHEMENT "
                          "CONTRACTÉ/RELÂCHÉ, VÉRIFIER LES ÉLECTRODES")
                self.btn_main.label = "[  RÉESSAYER L'ENREGISTREMENT  ]"
                return
            self.emg_port      = port
            # σ BRUTES : le gain d'amplification est réglable en direct sur
            # la page zone morte (excursion live amplifiée vs seuil brut).
            self.emg_rest      = rsd
            self.emg_flex      = fsd
            # Seuil d'activation : entre l'écart-type de repos et celui de
            # contraction (EMG_THRESHOLD_FRAC du chemin).
            self.emg_threshold = self.emg_rest + EMG_THRESHOLD_FRAC * (
                self.emg_flex - self.emg_rest)
            self._emg_live = self.emg_rest
            self._log(f"MUSCLE CALIBRÉ → PORT {port + 1}   "
                      f"σ REPOS={self.emg_rest:.1f}  "
                      f"CONTRACTION={self.emg_flex:.1f}  "
                      f"SEUIL={self.emg_threshold:.1f}")
            self._auto_ports = {
                "x": self.x_axis, "y": self.y_axis, "z": self.z_axis,
                "ppg": self.ppg_port, "emg": self.emg_port,
                "eda": self._auto_ports.get("eda")}
            if self.recal_target == "emg":   # fin de la tranche EMG (recal)
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_EDA
            self.btn_main.label = "[  OK, CALIBRER L'EDA  ]"
            return
        if self.state == STATE_EDA:
            self.eda_samples = self._stop_recording()
            if self._recording_failed(self.eda_samples,
                                      "[  RÉESSAYER L'ENREGISTREMENT  ]"):
                return
            # EDA calibré EN DERNIER : PPG + 3 axes + EMG connus et exclus →
            # le port restant au SIGNAL CONTINU depuis le début est l'EDA.
            port = detect_eda_port(
                self.eda_samples,
                self._ppg_excl(self.x_axis, self.y_axis, self.z_axis,
                               self.emg_port))
            if port is None:
                self._log("ERR: EDA NON DÉTECTÉ — VÉRIFIER LES ÉLECTRODES")
                self.btn_main.label = "[  RÉESSAYER L'ENREGISTREMENT  ]"
                return
            self.eda_port = port
            self.eda_rest = statistics.mean(s[port] for s in self.eda_samples)
            self._eda_live = self.eda_rest
            self._log(f"EDA CALIBRÉ → PORT {port + 1}   "
                      f"NIVEAU REPOS = {self.eda_rest:.0f}")
            self._auto_ports = {
                "x": self.x_axis, "y": self.y_axis, "z": self.z_axis,
                "ppg": self.ppg_port, "emg": self.emg_port,
                "eda": self.eda_port}
            if self.recal_queue:
                self.recal_queue.pop(0)
            self._advance_recal()
            return
        if self.state == STATE_LR:
            self.lr_samples = self._stop_recording()
            # Exclut PPG (+ EMG si déjà connu, ex. recal accéléro seul).
            self.x_axis = detect_x_axis(self.rest_samples, self.lr_samples,
                                        self._ppg_excl(self.emg_port))
            xs = [s[self.x_axis] for s in self.lr_samples]
            self.x_min, self.x_max = min(xs), max(xs)
            self._log(f"X AXIS DETECTED → PORT {self.x_axis + 1}  "
                      f"[{self.x_min}..{self.x_max}]")
            self.state = STATE_UD
            self.btn_main.label = "[  OK, COMMENCER LE BALAYAGE H/B  ]"
            return
        if self.state == STATE_UD:
            self.ud_samples = self._stop_recording()
            self.y_axis = detect_y_axis(
                self.rest_samples, self.ud_samples,
                self._ppg_excl(self.emg_port, self.x_axis))
            ys = [s[self.y_axis] for s in self.ud_samples]
            self.y_min, self.y_max = min(ys), max(ys)
            self.z_axis = detect_z_axis(
                self.rest_samples,
                self._ppg_excl(self.emg_port, self.x_axis, self.y_axis))
            self._log(f"Y AXIS DETECTED → PORT {self.y_axis + 1}  "
                      f"[{self.y_min}..{self.y_max}]")
            if self.z_axis is not None:
                self._log(f"Z AXIS INFERRED  → PORT {self.z_axis + 1}")
            if self.recal_target == "accel":   # fin de la tranche ACCELERO
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_EMG
            self.btn_main.label = "[  OK, CALIBRER LE MUSCLE (EMG)  ]"
            return

    def _ppg_excl(self, *extra):
        """Ports à exclure des axes : le port PPG + axes déjà trouvés."""
        return tuple(p for p in (self.ppg_port, *extra) if p is not None)

    def _axis_rest_mean(self, axis):
        """Valeur ADC moyenne d'un axe sur les échantillons de repos.
        Axe sauté / pas de repos → centre ADC neutre (512)."""
        if axis is None or not self.rest_samples:
            return 512
        return statistics.mean(s[axis] for s in self.rest_samples)

    @staticmethod
    def _port_label(p):
        """Libellé port lisible : 'P3' ou '—' si capteur non calibré/sauté."""
        return f"P{p + 1}" if p is not None else "—"

    def _reset_calibration_data(self):
        """Remet à zéro échantillons, ports et seuils détectés.
        Partagé par __init__ et _restart_calibration (source unique)."""
        self.rest_samples = []
        self.lr_samples   = []
        self.ud_samples   = []
        self.hr_samples   = []
        self.emg_samples  = []
        self.eda_samples  = []
        self.x_axis = self.y_axis = self.z_axis = None
        self.ppg_port = None
        self.bpm_rest = 0
        self._bpm_live   = 0
        self._bpm_live_t = 0.0
        self.emg_port      = None
        self.emg_rest      = 0.0
        self.emg_flex      = 0.0
        self.emg_threshold = 0.0
        self._emg_live   = 0.0
        self._emg_live_t = 0.0
        self.eda_port    = None
        self.eda_rest    = 0.0
        self._eda_live   = 0.0
        self._eda_live_t = 0.0
        # Plan de consignes EMG : liste de (label, fin_s cumulée), tiré au
        # hasard à chaque enregistrement (durées aléatoires ≥ EMG_MIN_SEG).
        self._emg_plan = []
        self.invert_x  = False   # inverser GAUCHE / DROITE
        self.invert_y  = False   # inverser HAUT / BAS
        # Correspondances ports : AUTO par défaut, override manuel optionnel.
        self._auto_ports   = {"x": None, "y": None, "z": None,
                              "ppg": None, "emg": None, "eda": None}
        self.port_override = {"x": None, "y": None, "z": None,
                              "ppg": None, "emg": None, "eda": None}
        self.port_edit        = True    # toujours visible (compat selfcheck)
        # Recalibrage ciblé : cible courante + file + sélecteur.
        self.recal_target     = None
        self.recal_select_mode = False
        self.recal_checks     = {"ppg": False, "accel": False,
                                 "emg": False, "eda": False}
        self.recal_queue      = []
        self.x_min  = self.x_max  = 0
        self.y_min  = self.y_max  = 0

    def _restart_calibration(self):
        self._reset_calibration_data()
        self.recording_until = 0.0
        self.slider.value = 0.3
        self.slider_emg.value = EMG_THRESHOLD_FRAC
        self.slider_emg_gain.value = _emg_gain_to_slider(EMG_GAIN)
        if self.device is not None:
            with self.device.lock:
                self.device.recorded  = []
                self.device.recording = False
        self.btn_main.label  = "[  OK, JE SUIS PRÊT  ]"
        self.btn_main.accent = PHOSPHOR
        self.state = STATE_REST
        self._log("RECALIBRATION REQUESTED — RESTARTING FROM STEP 01")

    def _clear_recording(self):
        """Stoppe/efface tout enregistrement en cours (avant un saut d'état)."""
        self.recording_until = 0.0
        if self.device is not None:
            with self.device.lock:
                self.device.recorded  = []
                self.device.recording = False

    def _start_single_recal(self, target):
        """Recalibre UN capteur, garde les autres (compat interne + selfcheck)."""
        self.recal_select_mode = False
        self.recal_target = target
        self.recal_queue  = [target]
        self._clear_recording()
        self.btn_main.enabled = True
        self.btn_main.accent  = PHOSPHOR
        if target == "ppg":
            self.state = STATE_REST
            self.btn_main.label = "[  CAPTURER LE REPOS + COEUR  ]"
            self._log("RECAL COEUR — REPOS + RYTHME (autres capteurs gardes)")
        elif target == "accel":
            self.state = STATE_LR
            self.btn_main.label = "[  OK, COMMENCER LE BALAYAGE G/D  ]"
            self._log("RECAL ACCELERO — G/D + H/B (autres capteurs gardes)")
        elif target == "emg":
            self.state = STATE_EMG
            self.btn_main.label = "[  OK, CALIBRER LE MUSCLE (EMG)  ]"
            self._log("RECAL EMG (autres capteurs gardes)")
        elif target == "eda":
            self.state = STATE_EDA
            self.btn_main.label = "[  OK, CALIBRER L'EDA  ]"
            self._log("RECAL EDA (autres capteurs gardes)")

    def _start_recal(self, sensors):
        """Lance le recalibrage pour un ensemble de capteurs (multi-selection).
        Construit une file en ordre canonique PPG -> ACCELERO -> EMG -> EDA."""
        order = ["ppg", "accel", "emg", "eda"]
        self.recal_queue      = [s for s in order if s in sensors]
        self.recal_select_mode = False
        self.recal_target     = None
        self._clear_recording()
        self.btn_main.enabled = True
        self.btn_main.accent  = PHOSPHOR
        self._advance_recal()

    def _advance_recal(self):
        """Demarre le prochain capteur dans la file. File vide -> ZONE MORTE."""
        if not self.recal_queue:
            self._return_to_deadzone()
            return
        target = self.recal_queue[0]   # ne pop pas encore
        self.recal_target = target
        if target == "ppg":
            self.state = STATE_REST
            self.btn_main.label = "[  CAPTURER LE REPOS + COEUR  ]"
            self._log("RECAL COEUR — REPOS + RYTHME (autres capteurs gardes)")
        elif target == "accel":
            self.state = STATE_LR
            self.btn_main.label = "[  OK, COMMENCER LE BALAYAGE G/D  ]"
            self._log("RECAL ACCELERO — G/D + H/B (autres capteurs gardes)")
        elif target == "emg":
            self.state = STATE_EMG
            self.btn_main.label = "[  OK, CALIBRER LE MUSCLE (EMG)  ]"
            self._log("RECAL EMG (autres capteurs gardes)")
        elif target == "eda":
            self.state = STATE_EDA
            self.btn_main.label = "[  OK, CALIBRER L'EDA  ]"
            self._log("RECAL EDA (autres capteurs gardes)")

    def _return_to_deadzone(self):
        """Fin d'étape : revient à ZONE MORTE (flux complet OU recal ciblé)."""
        self.recal_target = None
        self.recal_queue  = []
        self._clear_recording()
        self.state = STATE_DEADZONE
        self.btn_main.enabled = True
        self.btn_main.accent  = AMBER
        self.btn_main.label   = "[  VALIDER  ]"

    def _skip_step(self):
        """Saute le calibrage du capteur de l'étape courante (bouton PASSER).

        Les données du capteur sauté restent à None (code aval tolérant) ;
        on enchaîne sur l'étape suivante du flux — ou la file de recal si on
        est en recalibrage ciblé. Hors `_on_recording_done` → invisible au
        regex de flux du selfcheck (helper, transitions non littérales)."""
        self._clear_recording()
        st = self.state
        if st == STATE_HR:
            self.ppg_port = None
            self.bpm_rest = 0
            self._bpm_live = 0
            self._log("CŒUR IGNORÉ — calibrage du capteur cardiaque sauté")
            if self.recal_target == "ppg":
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_LR
            self.btn_main.label  = "[  OK, COMMENCER LE BALAYAGE G/D  ]"
            self.btn_main.accent = PHOSPHOR
            return
        if st in (STATE_LR, STATE_UD):
            self.x_axis = self.y_axis = self.z_axis = None
            self.x_min = self.x_max = 0
            self.y_min = self.y_max = 0
            self._log("ACCÉLÉRO IGNORÉ — balayages G/D + H/B sautés")
            if self.recal_target == "accel":
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_EMG
            self.btn_main.label  = "[  OK, CALIBRER LE MUSCLE (EMG)  ]"
            self.btn_main.accent = PHOSPHOR
            return
        if st == STATE_EMG:
            self.emg_port = None
            self.emg_rest = self.emg_flex = 0.0
            self.emg_threshold = 0.0
            self._emg_live = 0.0
            self._log("EMG IGNORÉ — calibrage musculaire sauté")
            if self.recal_target == "emg":
                if self.recal_queue:
                    self.recal_queue.pop(0)
                self._advance_recal()
                return
            self.state = STATE_EDA
            self.btn_main.label  = "[  OK, CALIBRER L'EDA  ]"
            self.btn_main.accent = PHOSPHOR
            return
        if st == STATE_EDA:
            self.eda_port = None
            self.eda_rest = 0.0
            self._eda_live = 0.0
            self._log("EDA IGNORÉ — calibrage électrodermal sauté")
            if self.recal_queue:
                self.recal_queue.pop(0)
            self._advance_recal()

    def _save_and_finish(self):
        x_rest = self._axis_rest_mean(self.x_axis)
        y_rest = self._axis_rest_mean(self.y_axis)
        z_rest = (self._axis_rest_mean(self.z_axis)
                  if self.z_axis is not None else 512)
        emg_thr = round(self._apply_emg_threshold(), 2)
        calib = {
            "address":   self.address if not self._demo else "SIMULATED",
            "frequency": SAMPLING_HZ,
            "ports": {
                "x": int(self.x_axis + 1) if self.x_axis is not None else None,
                "y": int(self.y_axis + 1) if self.y_axis is not None else None,
                "z": int(self.z_axis + 1) if self.z_axis is not None else None,
            },
            "ports_override": {
                k: (None if self.port_override[k] is None
                    else int(self.port_override[k] + 1))
                for k in self._port_keys},
            "rest":  {"x": x_rest, "y": y_rest, "z": z_rest},
            "range": {"x_min": int(self.x_min), "x_max": int(self.x_max),
                      "y_min": int(self.y_min), "y_max": int(self.y_max)},
            "dead_zone": round(self.slider.value, 3),
            "invert": {"x": bool(self.invert_x), "y": bool(self.invert_y)},
            "ppg": {
                "port": int(self.ppg_port + 1) if self.ppg_port is not None else None,
                "bpm_rest": int(self.bpm_rest),
            },
            "emg": {
                "port": int(self.emg_port + 1) if self.emg_port is not None else None,
                "sigma_rest": round(self.emg_rest, 2),
                "sigma_flex": round(self.emg_flex, 2),
                "gain": round(self._emg_gain(), 2),
                "dead_zone": round(self.slider_emg.value, 3),
                "threshold":  emg_thr,
            },
            "eda": {
                "port": int(self.eda_port + 1) if self.eda_port is not None else None,
                "rest": round(self.eda_rest, 2),
            },
            "mapping": {
                "left":  "x < x_rest - dead_zone * (x_rest - x_min)",
                "right": "x > x_rest + dead_zone * (x_max - x_rest)",
                "up":    "y > y_rest + dead_zone * (y_max - y_rest)",
                "down":  "y < y_rest - dead_zone * (y_rest - y_min)",
                "invert_x": "si invert.x : échanger left ↔ right",
                "invert_y": "si invert.y : échanger up ↔ down",
                "emg_active": "sigma_rest + gain*(sigma_emg - sigma_rest) >= emg.threshold",
            },
        }
        with open("calibration.json", "w", encoding="utf-8") as f:
            json.dump(calib, f, indent=2, ensure_ascii=False)
        self._log("CALIBRATION WRITTEN → calibration.json")
        self.state = STATE_DONE
        self.btn_main.label = "[  QUITTER  ]"

    # ── Rendu ──────────────────────────────────────────────────────
    def _draw(self, t):
        self.screen.fill(BG_DEEP)
        self.screen.blit(self.bg_grid, (0, 0))
        self._draw_drift(t)

        self._draw_header(t)
        self._draw_title(t)

        if self.state == STATE_DETECT:
            self._draw_detect(t)
        else:
            self._draw_step_track()
            self._draw_log_panel()
            if self.state == STATE_INTRO:
                self._draw_intro(t)
            elif self.state == STATE_REST:
                self._draw_rest(t)
            elif self.state in (STATE_LR, STATE_UD):
                self._draw_axis_step(t, "x" if self.state == STATE_LR else "y")
            elif self.state == STATE_HR:
                self._draw_hr(t)
            elif self.state == STATE_EMG:
                self._draw_emg(t)
            elif self.state == STATE_EDA:
                self._draw_eda(t)
            elif self.state == STATE_DEADZONE:
                self._draw_deadzone(t)
            elif self.state == STATE_DONE:
                self._draw_done(t)

        self.screen.blit(self.scanlines, (0, 0))
        self.screen.blit(self.vignette, (0, 0))

    def _draw_drift(self, t):
        """Tétrominos fantômes qui descendent lentement — ambiance matrice."""
        w, h = self.screen.get_size()
        if getattr(self, "_drift_sz", None) != (w, h):
            rng = random.Random(1991)
            keys = list(TETRO_SHAPES)
            self._drift = []
            for _ in range(max(7, w // 220)):
                k = rng.choice(keys)
                self._drift.append((
                    k, rng.randint(0, w), rng.uniform(7, 22),
                    rng.uniform(0, 1000), rng.randint(20, 40)))
            self._drift_sz = (w, h)
        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        for k, x, spd, ph, cell in self._drift:
            shp = TETRO_SHAPES[k]
            span = (max(c[1] for c in shp) + 2) * cell
            y = int((ph + t * spd) % (h + span)) - span
            rot = int(t * 0.15 + ph) % 2
            for (cx, cy) in shp:
                bx = x + (cy if rot else cx) * cell
                by = y + (cx if rot else cy) * cell
                pygame.draw.rect(layer, (*TETRO[k], 16),
                                 pygame.Rect(bx, by, cell - 3, cell - 3), 2)
        self.screen.blit(layer, (0, 0))

    def _status(self):
        is_rec = self.recording_until > 0
        if self.state == STATE_DETECT:
            c = (AMBER if self.detect_status == "scanning" else
                 PHOSPHOR_MID if self.detect_status == "ok" else DANGER)
            return c, self.detect_status.upper()
        if is_rec:
            return DANGER, "REC"
        return PHOSPHOR_MID, "READY"

    def _draw_header(self, t):
        bar = self.layout.header
        pygame.draw.rect(self.screen, (12, 13, 28), bar)
        pygame.draw.line(self.screen, PHOSPHOR_DIM,
                         (0, bar.bottom), (bar.right, bar.bottom), 2)
        # Logo : mini pièce I
        m = self.layout.margin
        bs = max(7, bar.height // 6)
        for j in range(4):
            draw_block(self.screen,
                       pygame.Rect(bar.left + m + j * (bs + 2),
                                   bar.centery - bs // 2, bs, bs),
                       PHOSPHOR)
        draw_text(self.screen, self.theme.f_small,
                  "BITALINO  ·  CALIBRAGE ACCÉL + POULS + EMG",
                  (bar.left + m + 4 * (bs + 2) + 16,
                   bar.centery - self.theme.f_small.get_height() // 2),
                  color=TEXT_MID)
        # Statut : chip bloc + libellé uniquement
        sc, sl = self._status()
        blink = sc if int(t * 2) % 2 == 0 else _darken(sc, 0.45)
        ts = self.theme.f_small.render(sl, True, TEXT_MID)
        chip = max(10, bar.height // 5)
        cxr = bar.right - m - ts.get_width()
        draw_block(self.screen,
                   pygame.Rect(cxr - chip - 12, bar.centery - chip // 2,
                               chip, chip), blink)
        self.screen.blit(ts, (cxr, bar.centery - ts.get_height() // 2))

    def _draw_title(self, t):
        rect = self.layout.title
        fh = self.theme.f_huge.get_height()
        draw_text(self.screen, self.theme.f_huge, "CALIBRAGE",
                  (rect.left, rect.top + max(4, (rect.height - fh) // 3)),
                  color=TEXT_HI, glow=PHOSPHOR)
        draw_text(self.screen, self.theme.f_small,
                  "ACCÉL 3 AXES → ◄ ► ▲ ▼     CŒUR → BPM     EMG → CONTRACTION",
                  (rect.left + 4, rect.bottom - self.theme.f_small.get_height() - 4),
                  color=TEXT_DIM)
        # Frise de tuiles décorative en haut-droite (sous le titre)
        order = ["I", "O", "T", "S", "Z", "J", "L"]
        bs = max(12, rect.height // 6)
        bx = rect.right - len(order) * (bs + 4)
        by = rect.top + max(4, (rect.height - fh) // 3)
        for i, k in enumerate(order):
            off = int(3 * math.sin(t * 2 + i))
            draw_block(self.screen,
                       pygame.Rect(bx + i * (bs + 4), by + off, bs, bs),
                       TETRO[k])

    def _draw_step_track(self):
        rect = self.layout.side
        steps = [(_STEP_NO[st], lbl, st, shp)
                 for st, lbl, shp in CALIB_STEPS]
        order = _STEP_ORDER
        cur_idx = order.index(self.state) if self.state in order else 0
        slot_h = rect.height // len(steps)
        pad = max(6, slot_h // 10)
        for i, (num, label, st, shp) in enumerate(steps):
            done = order.index(st) < cur_idx
            active = self.state == st
            slot = pygame.Rect(rect.left, rect.top + i * slot_h + pad,
                               rect.width, slot_h - 2 * pad)
            base = (PHOSPHOR if active else
                    PHOSPHOR_MID if done else TEXT_FAINT)
            fill = BG_PANEL_HI if active else BG_PANEL
            pygame.draw.rect(self.screen, fill, slot, border_radius=4)
            pygame.draw.rect(self.screen, base, slot, 2 if active else 1,
                             border_radius=4)
            if active:
                draw_corner_brackets(self.screen, slot, color=PHOSPHOR,
                                     length=12, width=3)
            gs = min(slot.height - 8, slot.width // 5, 56)
            gx = slot.left + 14
            gy = slot.centery - gs // 2
            tcol = TETRO[shp]
            if active:
                draw_block(self.screen, pygame.Rect(gx, gy, gs, gs), tcol)
            elif done:
                draw_block(self.screen, pygame.Rect(gx, gy, gs, gs),
                           _darken(PHOSPHOR_MID, 0.25))
                pygame.draw.lines(self.screen, BG_DEEP, False,
                                  [(gx + gs * 0.22, gy + gs * 0.52),
                                   (gx + gs * 0.42, gy + gs * 0.72),
                                   (gx + gs * 0.80, gy + gs * 0.28)], 3)
            else:
                pygame.draw.rect(self.screen, _darken(tcol, 0.55),
                                 pygame.Rect(gx, gy, gs, gs), 2)
            tx = gx + gs + 16
            tiny_h = self.theme.f_tiny.get_height()
            lbl_font = self.theme.f_med_b if active else self.theme.f_small
            lbl_h = lbl_font.get_height()
            total_h = tiny_h + 3 + lbl_h
            ty = slot.centery - total_h // 2
            draw_text(self.screen, self.theme.f_tiny, f"ÉTAPE {num}",
                      (tx, ty),
                      color=base if not done else PHOSPHOR_MID)
            draw_text(self.screen, lbl_font,
                      label, (tx, ty + tiny_h + 3),
                      color=TEXT_HI if active else base,
                      glow=PHOSPHOR if active else None)

    @staticmethod
    def _fit_text(font, text, max_w):
        """Tronque `text` (ellipse) pour tenir dans `max_w` px — évite que la
        console déborde du cadre (lignes longues : MUSCLE CALIBRÉ …)."""
        if max_w <= 0 or font.size(text)[0] <= max_w:
            return text
        while text and font.size(text + "…")[0] > max_w:
            text = text[:-1]
        return text + "…"

    def _draw_log_lines(self, x, y, shown, max_w=None):
        """Liste de lignes de journal : la plus récente en cyan."""
        lh = self.theme.f_tiny.get_height() + 4
        for idx, line in enumerate(shown):
            newest = idx == len(shown) - 1
            txt = f"› {line}"
            if max_w is not None:
                txt = self._fit_text(self.theme.f_tiny, txt, max_w)
            draw_text(self.screen, self.theme.f_tiny, txt, (x, y),
                      color=PHOSPHOR if newest else TEXT_DIM)
            y += lh

    def _draw_log_panel(self):
        rect = self.layout.log
        draw_panel(self.screen, rect, accent=PHOSPHOR)
        pad = max(8, int(rect.height * 0.07))
        tiny_h = self.theme.f_tiny.get_height()
        draw_text(self.screen, self.theme.f_tiny, "// CONSOLE",
                  (rect.left + 14, rect.top + pad), color=PHOSPHOR_MID)
        lh = tiny_h + 4
        content_y = rect.top + pad + tiny_h + max(4, pad // 2)
        max_lines = max(3, (rect.bottom - pad - content_y) // lh)
        self.screen.set_clip(rect)
        self._draw_log_lines(rect.left + 14, content_y,
                             list(self.log_lines)[-max_lines:],
                             max_w=rect.width - 28)
        self.screen.set_clip(None)

    # ── Écran : Détection ──────────────────────────────────────────
    def _draw_detect(self, t):
        m = self.layout.margin
        rect = pygame.Rect(m, self.layout.title.bottom + 10,
                           self.layout.w - 2 * m,
                           self.layout.h - self.layout.title.bottom - m - 20)
        draw_panel(self.screen, rect, accent=PHOSPHOR)
        console_w = max(360, int(rect.width * 0.34))
        console = pygame.Rect(rect.right - console_w - 24, rect.top + 28,
                              console_w, rect.height - 56)
        pygame.draw.rect(self.screen, (10, 11, 24), console, border_radius=3)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, console, 1, border_radius=3)
        draw_text(self.screen, self.theme.f_tiny, "// JOURNAL",
                  (console.left + 14, console.top + 12), color=PHOSPHOR_MID)
        max_lines = max(6, (console.height - 54) // 20)
        self.screen.set_clip(console)
        self._draw_log_lines(console.left + 14, console.top + 38,
                             list(self.log_lines)[-max_lines:],
                             max_w=console.width - 28)
        self.screen.set_clip(None)

        zone = pygame.Rect(rect.left + 30, rect.top + 30,
                           console.left - rect.left - 56,
                           rect.height - 60)
        if self.detect_status == "scanning":
            self._draw_scan_animation(zone, t)
        elif self.detect_status == "ok":
            for i in range(3):
                draw_block(self.screen,
                           pygame.Rect(zone.centerx - 60 + i * 44,
                                       zone.centery - 60, 38, 38),
                           PHOSPHOR_MID)
            draw_text_centered(self.screen, self.theme.f_huge, "DÉTECTÉ",
                               (zone.centerx, zone.centery + 10),
                               color=PHOSPHOR_MID, glow=PHOSPHOR_MID)
        elif self.detect_status == "fail":
            self._draw_detect_failure(zone, t)

    def _draw_scan_animation(self, zone, t):
        draw_text(self.screen, self.theme.f_xl, "DÉTECTION DU MATÉRIEL",
                  (zone.left, zone.top + 6), color=PHOSPHOR, glow=PHOSPHOR)
        draw_text(self.screen, self.theme.f_small,
                  f"Sondage de la liaison Bluetooth  ·  {self.address}",
                  (zone.left, zone.top + 70), color=TEXT_MID)
        # Ligne de tuiles qui se "remplit" puis se vide (clear de ligne)
        bs = max(22, zone.width // 16)
        cells = zone.width // (bs + 6)
        bar_y = zone.top + 130
        phase = (math.sin(t * 1.6) + 1) / 2
        lit = int(phase * cells)
        order = list(TETRO)
        for i in range(cells):
            bx = zone.left + i * (bs + 6)
            if i <= lit:
                draw_block(self.screen, pygame.Rect(bx, bar_y, bs, bs),
                           TETRO[order[i % len(order)]])
            else:
                pygame.draw.rect(self.screen, GRID_HI,
                                 pygame.Rect(bx, bar_y, bs, bs), 1,
                                 border_radius=3)
        dots = "." * (1 + int(t * 3) % 4)
        draw_text(self.screen, self.theme.f_med, f"SCAN EN COURS{dots}",
                  (zone.left, bar_y + bs + 24), color=AMBER)
        elapsed = time.time() - self.detect_started_at
        draw_text(self.screen, self.theme.f_tiny,
                  f"elapsed={elapsed:5.1f}s   ports={len(ALL_PORTS)}   "
                  f"fs={SAMPLING_HZ}Hz",
                  (zone.left, bar_y + bs + 60), color=TEXT_DIM)

    def _draw_detect_failure(self, zone, t):
        draw_block(self.screen, pygame.Rect(zone.left, zone.top + 6, 34, 34),
                   DANGER)
        draw_text(self.screen, self.theme.f_xl, "AUCUN BITALINO",
                  (zone.left + 48, zone.top + 8), color=DANGER, glow=DANGER_DIM)
        draw_text(self.screen, self.theme.f_small,
                  "La carte n'a pas pu être ouverte sur la liaison Bluetooth.",
                  (zone.left, zone.top + 74), color=TEXT_HI)
        err = self.detect_error or "(raison inconnue)"
        if len(err) > 90:
            err = err[:87] + "..."
        draw_text(self.screen, self.theme.f_small, f"› {err}",
                  (zone.left, zone.top + 112), color=DANGER)
        tips = [
            "• Carte allumée et appairée en Bluetooth.",
            f"• Adresse utilisée : {self.address}",
            "• Rapprochez la carte, fermez les autres apps audio/BT.",
            "• Ou lancez le MODE DÉMO pour tester l'interface seule.",
        ]
        y = zone.top + 158
        for tip in tips:
            draw_text(self.screen, self.theme.f_small, tip,
                      (zone.left, y), color=TEXT_MID)
            y += 30

        btn_w = max(260, zone.width // 3 - 20)
        btn_h = max(64, int(zone.height * 0.13))
        gap = 22
        total_w = btn_w * 2 + gap
        start_x = zone.left + (zone.width - total_w) // 2
        by = zone.bottom - btn_h - 24
        self.btn_retry.rect = pygame.Rect(start_x, by, btn_w, btn_h)
        self.btn_demo.rect  = pygame.Rect(start_x + btn_w + gap, by,
                                          btn_w, btn_h)
        self.btn_retry.draw(self.screen, self.theme.f_med_b, t)
        self.btn_demo.draw(self.screen, self.theme.f_med_b, t)

    # ── Écrans : étapes ────────────────────────────────────────────
    def _panel_header(self, rect, badge, title, accent, shape="T",
                       subtitle=None, sub2=None):
        """En-tête de panneau commun : tuile badge + titre néon + sous-titres.
        Renvoie le Y sous l'en-tête."""
        draw_panel(self.screen, rect, accent=accent)
        bs = self.theme.f_xl.get_height()
        pad = max(14, min(32, int(rect.width * 0.022)))
        bx = rect.left + pad
        by = rect.top + pad
        draw_block(self.screen, pygame.Rect(bx, by, bs, bs), TETRO[shape])
        bt = self.theme.f_big.render(badge, True, _darken(TETRO[shape], 0.78))
        self.screen.blit(bt, bt.get_rect(center=(bx + bs // 2,
                                                 by + bs // 2)))
        tx = bx + bs + max(12, pad // 2)
        draw_text(self.screen, self.theme.f_xl, title, (tx, by - 2),
                  color=TEXT_HI, glow=accent)
        yy = by + bs + max(6, pad // 3)
        if subtitle:
            draw_text(self.screen, self.theme.f_med, subtitle,
                      (rect.left + pad, yy), color=TEXT_HI)
            yy += self.theme.f_med.get_height() + 6
        if sub2:
            draw_text(self.screen, self.theme.f_small, sub2,
                      (rect.left + pad, yy), color=TEXT_DIM)
            yy += self.theme.f_small.get_height() + 4
        self._hdr_bottom = yy
        return yy

    def _draw_intro(self, t):
        rect = self.layout.main
        self.screen.set_clip(rect)
        self._panel_header(rect, "00", "PRÉPARATION", PHOSPHOR, shape="I")
        lines = [
            "▸ Branchez l'accéléromètre 3 axes sur la carte BITalino.",
            "▸ Branchez AUSSI le capteur cardiaque (oreille) maintenant :",
            "  il reste branché pendant tout le calibrage.",
            "▸ Aucun choix de port n'est nécessaire :",
            "  à la phase REPOS l'accéléromètre est immobile, donc le",
            "  seul signal qui bouge encore est le pouls → le port PPG",
            "  est isolé automatiquement, les 3 axes ensuite.",
            "▸ L'étape 04 calibre votre BPM de repos (capteur cardiaque).",
            "",
            "▸ Le calibrage produit le fichier  ›  calibration.json",
            "  (mapping des flèches + votre BPM de repos).",
            "",
            "  [ESC] pour quitter à tout moment.",
        ]
        y = self._hdr_bottom + 16
        for l in lines:
            draw_text(self.screen, self.theme.f_med, l,
                      (rect.left + 30, y), color=TEXT_MID)
            y += 32
        if self.btn_main.label == "[  OK  ]":
            self.btn_main.label = "[  COMMENCER LE CALIBRAGE  ]"
        self._place_main_button(rect)
        self.btn_main.accent = PHOSPHOR
        self.btn_main.draw(self.screen, self.theme.f_med_b, t)
        self.screen.set_clip(None)

    def _draw_rest(self, t):
        rect = self.layout.main
        self.screen.set_clip(rect)
        self._panel_header(
            rect, _STEP_NO[STATE_REST], "REPOS + POULS", PHOSPHOR, shape="I",
            subtitle="Prenez l'accéléromètre en main et tenez-le IMMOBILE.",
            sub2="Lignes plates = accéléro. La courbe qui bouge encore = "
                 "le pouls (oreille) → port PPG isolé tout seul.")
        self._draw_step_port_ctrl(rect, t)
        scope = self._scope_rect(rect)
        with self.device.lock:
            buffers = [list(b) for b in self.device.live_buf]
        labels = [f"P{i+1}" for i in range(6)]
        draw_scope(self.screen, scope, buffers,
                   axis_labels=labels, theme=self.theme)
        self._draw_progress_or_button(t, rect, "[  OK, JE SUIS PRÊT  ]")
        self.screen.set_clip(None)

    def _draw_axis_step(self, t, axis):
        rect = self.layout.main
        self.screen.set_clip(rect)
        if axis == "x":
            badge, shape = _STEP_NO[STATE_LR], "J"
            title = "GAUCHE  ◄ ►  DROITE"
            instr = "Bougez l'accéléromètre de GAUCHE à DROITE plusieurs fois."
            tip   = "Allez jusqu'aux amplitudes que vous utiliserez en jeu."
            highlight_idx = self.x_axis
        else:
            badge, shape = _STEP_NO[STATE_UD], "L"
            title = "HAUT  ▲ ▼  BAS"
            instr = "Bougez l'accéléromètre de HAUT en BAS plusieurs fois."
            tip   = "Évitez de tourner sur l'axe X pendant ce balayage."
            highlight_idx = self.y_axis
        self._panel_header(rect, badge, title, PHOSPHOR, shape=shape,
                           subtitle=instr, sub2=tip)
        self._draw_step_port_ctrl(rect, t)
        if self.x_axis is not None and axis == "y":
            draw_text(self.screen, self.theme.f_small,
                      f"✓ X = PORT {self.x_axis + 1}   "
                      f"[{self.x_min}..{self.x_max}]",
                      (rect.left + 30, self._hdr_bottom + 8),
                      color=PHOSPHOR_MID)
        scope = self._scope_rect(rect)
        with self.device.lock:
            buffers = [list(b) for b in self.device.live_buf]
        labels = [f"P{i+1}" for i in range(6)]
        draw_scope(self.screen, scope, buffers,
                   highlight=highlight_idx,
                   axis_labels=labels, theme=self.theme)
        self._draw_progress_or_button(t, rect, "[  OK, COMMENCER LE BALAYAGE  ]")
        self.screen.set_clip(None)

    def _draw_sensor_step(self, t, *, state, title, accent, shape, subtitle,
                          sub2, badge, label_fn, highlight_fn, prompt):
        """Squelette commun aux écrans capteur (CŒUR / EMG) :
        en-tête → indicateur live → oscilloscope (labels + courbe en avant)
        → bouton de progression. Les parties spécifiques au capteur sont
        passées en paramètres (`badge`, `label_fn`, `highlight_fn`)."""
        rect = self.layout.main
        self.screen.set_clip(rect)
        self._panel_header(rect, _STEP_NO[state], title, accent, shape=shape,
                           subtitle=subtitle, sub2=sub2)
        badge_y = None
        if badge is not None:
            block_color, text, text_color, glow = badge
            hx = rect.left + 30
            hy = self._hdr_bottom + 6
            badge_y = hy
            bs = self.theme.f_big.get_height()
            draw_block(self.screen, pygame.Rect(hx, hy, bs, bs), block_color)
            draw_text(self.screen, self.theme.f_big, text,
                      (hx + bs + 14, hy - 2), color=text_color, glow=glow)
            # Le badge (BPM cœur / consigne EMG) est une ligne SOUS l'en-tête :
            # l'oscilloscope démarre à _hdr_bottom — il faut donc descendre
            # _hdr_bottom sous le badge, sinon le scope le recouvre (visible
            # surtout fenêtre élargie : badge masqué). Source : _scope_rect.
            self._hdr_bottom = hy + bs + max(8, int(rect.height * 0.012))

        # Éditeur de port inline : aligné à droite sur la rangée du badge
        # quand il y en a un (pas de rangée en plus), sinon rangée propre.
        self._draw_step_port_ctrl(rect, t, anchor_y=badge_y)

        axis_excl = self._ppg_excl(self.x_axis, self.y_axis, self.z_axis)
        scope = self._scope_rect(rect)
        with self.device.lock:
            buffers = [list(b) for b in self.device.live_buf]
        labels = [label_fn(i, axis_excl) for i in range(6)]
        highlight = highlight_fn(axis_excl, buffers)
        draw_scope(self.screen, scope, buffers,
                   highlight=highlight, axis_labels=labels, theme=self.theme)
        self._draw_progress_or_button(t, rect, prompt)
        self.screen.set_clip(None)

    def _draw_hr(self, t):
        if self.ppg_port is not None:
            sub = (f"Port pouls isolé au REPOS → P{self.ppg_port + 1}. "
                   f"Calibration du BPM de repos ({HR_SECONDS:.0f} s).")
        else:
            sub = (f"Pouls non isolé : détection ici sur "
                   f"{HR_SECONDS:.0f} s, respirez calmement.")

        bpm_now = self._live_bpm()
        badge = None
        if self.ppg_port is not None and bpm_now > 0:
            phase = (t * bpm_now / 60.0) % 1.0
            beat  = phase < 0.16 or 0.32 < phase < 0.46
            hcol  = DANGER if beat else _darken(DANGER, 0.35)
            badge = (hcol, f"{bpm_now} BPM", DANGER, DANGER_DIM)

        def label_fn(i, axis_excl):
            return f"P{i+1}" + ("  (acc)" if i in axis_excl else
                                ("  ♥" if i == self.ppg_port else ""))

        def highlight_fn(axis_excl, buffers):
            if self.ppg_port is not None:
                return self.ppg_port
            # Met en évidence le meilleur candidat PPG en direct.
            freq = self._live_freq()
            best_port, best = None, PPG_MIN_SCORE
            for cdt in (i for i in range(6) if i not in axis_excl):
                _, sc = _estimate_bpm_and_score(list(buffers[cdt]), freq)
                if sc > best:
                    best, best_port = sc, cdt
            return best_port

        self._draw_sensor_step(
            t, state=STATE_HR, title="RYTHME CARDIAQUE", accent=DANGER,
            shape="Z",
            subtitle="Gardez le capteur d'oreille en place, restez IMMOBILE.",
            sub2=sub, badge=badge, label_fn=label_fn,
            highlight_fn=highlight_fn,
            prompt="[  OK, CALIBRER LE POULS DE REPOS  ]")

    def _live_bpm(self):
        """BPM live calculé sur le buffer du port PPG (recalcul ~1 Hz)."""
        if self.ppg_port is None or self.device is None:
            return self.bpm_rest
        now = time.time()
        if now - self._bpm_live_t < 1.0:
            return self._bpm_live
        self._bpm_live_t = now
        with self.device.lock:
            col = list(self.device.live_buf[self.ppg_port])
        bpm, score = _estimate_bpm_and_score(col, self._live_freq())
        if score > PPG_MIN_SCORE and PPG_MIN_BPM <= bpm <= PPG_MAX_BPM:
            self._bpm_live = bpm
        elif self._bpm_live == 0:
            self._bpm_live = self.bpm_rest
        return self._bpm_live

    def _live_freq(self):
        """Fréquence effective du live_buf (décimé 1/8 vs acquisition)."""
        base = self.device.frequency if self.device.frequency else SAMPLING_HZ
        return max(1, int(round(base / 8)))

    def _emg_sigma(self, buf):
        """Écart-type d'un buffer (amplitude EMG instantanée)."""
        col = list(buf)
        return statistics.pstdev(col) if len(col) > 1 else 0.0

    def _emg_gain(self):
        """Gain d'amplification EMG courant (curseur AMPLI de la page)."""
        return _slider_to_emg_gain(self.slider_emg_gain.value)

    def _live_emg(self):
        """σ EMG live sur une FENÊTRE RÉCENTE, EXCURSION amplifiée.

        Capteur très faible : mesurer σ sur tout le buffer noie la
        contraction dans le repos → indicateur bloqué sur « relâché ».
        On ne garde que la dernière ~EMG_CYCLE_SECONDS, puis on amplifie
        l'écart AU-DESSUS du repos (gain réglable) — le seuil reste en σ
        brut, donc plus le gain est fort, plus la contraction passe."""
        if self.emg_port is None or self.device is None:
            return self._emg_live
        now = time.time()
        if now - self._emg_live_t < 0.2:
            return self._emg_live
        self._emg_live_t = now
        with self.device.lock:
            buf = list(self.device.live_buf[self.emg_port])
        win = max(8, int(self._live_freq() * EMG_CYCLE_SECONDS))
        recent = buf[-win:] if len(buf) > win else buf
        raw = self._emg_sigma(recent)
        amp = self.emg_rest + self._emg_gain() * (raw - self.emg_rest)
        self._emg_live = max(0.0, amp)
        return self._emg_live

    def _live_eda(self):
        """Niveau EDA live = moyenne du buffer du port EDA (signal lent,
        continu → on suit le niveau tonique, recalcul ~3 Hz)."""
        if self.eda_port is None or self.device is None:
            return self.eda_rest
        now = time.time()
        if now - self._eda_live_t < 0.3:
            return self._eda_live
        self._eda_live_t = now
        with self.device.lock:
            col = list(self.device.live_buf[self.eda_port])
        self._eda_live = statistics.mean(col) if col else self.eda_rest
        return self._eda_live

    # ── Éditeur de correspondances ports (override optionnel) ──────
    def _port_value(self, key):
        """Port effectif d'un capteur : override manuel sinon AUTO."""
        ov = self.port_override.get(key)
        return self._auto_ports.get(key) if ov is None else ov

    def _apply_port(self, key):
        """Pousse le port effectif (override/AUTO) vers l'attribut associé."""
        val = self._port_value(key)
        if key == "x":
            self.x_axis = val
        elif key == "y":
            self.y_axis = val
        elif key == "z":
            self.z_axis = val
        elif key == "ppg":
            self.ppg_port = val
        elif key == "emg":
            self.emg_port = val
        elif key == "eda":
            self.eda_port = val

    def _cycle_port(self, key, delta):
        """Fait défiler AUTO → P1..P6 → AUTO pour un capteur."""
        seq = [None, 0, 1, 2, 3, 4, 5]
        cur = self.port_override.get(key)
        i = seq.index(cur) if cur in seq else 0
        self.port_override[key] = seq[(i + delta) % len(seq)]
        self._apply_port(key)
        self._log(f"PORT {key.upper()} → "
                  f"{'AUTO' if self.port_override[key] is None else 'P' + str(self.port_override[key] + 1)}")

    def _reapply_overrides(self):
        """Ré-impose les overrides manuels APRÈS l'auto-détection : une
        détection (`_on_recording_done`) écrit l'attribut en direct ; sans
        ça l'override choisi dans l'écran d'étape serait écrasé."""
        for k in self._port_keys:
            if self.port_override[k] is not None:
                self._apply_port(k)

    # Port (capteur) modifiable manuellement DANS l'écran de chaque étape.
    _STEP_PORT_KEY = {STATE_REST: "ppg", STATE_HR: "ppg",
                      STATE_LR: "x", STATE_UD: "y", STATE_EMG: "emg",
                      STATE_EDA: "eda"}

    def _step_port_key(self):
        return self._STEP_PORT_KEY.get(self.state)

    def _draw_step_port_ctrl(self, rect, t, anchor_y=None):
        """Stepper compact ◀ AUTO/Px ▶ pour CORRIGER le port du capteur de
        l'étape courante sans attendre la zone morte. Pastille = couleur de
        la courbe scope correspondante. `anchor_y` : si fourni (rangée du
        badge), s'aligne à droite dessus sans pousser l'en-tête ; sinon
        rangée propre sous l'en-tête (descend _hdr_bottom)."""
        key = self._step_port_key()
        if key is None:
            return
        th  = self.theme
        idx = self._port_keys.index(key)
        names = {"x": "AXE X", "y": "AXE Y", "z": "AXE Z",
                 "ppg": "CŒUR", "emg": "EMG", "eda": "EDA"}
        sx  = max(12, int(rect.width * 0.02))
        sh  = th.f_small.get_height()
        btn = max(24, sh + 10)
        chip = max(8, sh - 2)
        eff  = self._port_value(key)
        curve_col = (PORT_COLORS[eff % len(PORT_COLORS)]
                     if eff is not None else None)
        ov   = self.port_override[key]
        val  = "AUTO" if ov is None else f"P{ov + 1}"
        sub  = f"→ P{eff + 1}" if eff is not None else "→ —"
        lbl  = f"PORT {names[key]}"
        val_w = max(52, th.f_small.size("AUTO")[0] + 8,
                    th.f_tiny.size(sub)[0] + 8)
        lbl_w = th.f_small.size(lbl)[0]
        block_w = (chip + 6 + lbl_w + max(10, sx) + btn
                   + 6 + val_w + 6 + btn)
        if anchor_y is not None:
            cy = anchor_y + th.f_big.get_height() // 2
            x0 = rect.right - sx - block_w
        else:
            y0 = self._hdr_bottom + max(6, int(rect.height * 0.012))
            cy = y0 + btn // 2
            x0 = rect.left + sx
        cxp = x0
        chip_r = pygame.Rect(cxp, cy - chip // 2, chip, chip)
        if curve_col is not None:
            draw_block(self.screen, chip_r, curve_col)
        else:
            pygame.draw.rect(self.screen, _darken(PHOSPHOR_MID, 0.5),
                             chip_r, 2, border_radius=2)
        lx = cxp + chip + 6
        draw_text(self.screen, th.f_small, lbl,
                  (lx, cy - sh // 2), color=TEXT_HI)
        bd = self.btn_port_dec[idx]
        bi = self.btn_port_inc[idx]
        bd.rect = pygame.Rect(lx + lbl_w + max(10, sx),
                              cy - btn // 2, btn, btn)
        vx = bd.rect.right + 6
        mc = AMBER if ov is not None else PHOSPHOR_MID
        draw_text_centered(self.screen, th.f_small, val,
                           (vx + val_w // 2,
                            cy - th.f_tiny.get_height() // 2),
                           color=mc, glow=mc)
        draw_text_centered(self.screen, th.f_tiny, sub,
                           (vx + val_w // 2,
                            cy + th.f_small.get_height() // 2),
                           color=curve_col if curve_col is not None
                           else TEXT_DIM)
        bi.rect = pygame.Rect(vx + val_w + 6, cy - btn // 2, btn, btn)
        bd.draw(self.screen, th.f_small, t)
        bi.draw(self.screen, th.f_small, t)
        if anchor_y is None:
            self._hdr_bottom = (cy + btn // 2
                                + max(6, int(rect.height * 0.014)))

    def _apply_emg_threshold(self):
        """Recalcule le seuil EMG depuis le curseur (zone morte EMG)."""
        self.emg_threshold = self.emg_rest + self.slider_emg.value * (
            self.emg_flex - self.emg_rest)
        return self.emg_threshold

    def _build_emg_plan(self):
        """Tire un plan de consignes aléatoire pour la calibration EMG.

        Alternance CONTRACTÉ / RELÂCHÉ, départ CONTRACTÉ. Chaque consigne
        dure ≥ EMG_MIN_SEG s ; au moins EMG_MIN_CONTRACT contractions et
        EMG_MIN_RELEASE relâchements ; somme exacte = EMG_SECONDS.
        Stocke self._emg_plan = [(label, fin_s_cumulée), ...]."""
        n_pairs = max(EMG_MIN_CONTRACT, EMG_MIN_RELEASE)
        # Paires supplémentaires possibles tant que n_seg * EMG_MIN_SEG tient
        # dans EMG_SECONDS (chaque paire = 2 consignes).
        max_pairs = int(EMG_SECONDS // (2 * EMG_MIN_SEG))
        n_pairs = random.randint(n_pairs, max(n_pairs, min(max_pairs, 7)))
        n_seg = 2 * n_pairs
        # Durée = plancher EMG_MIN_SEG + part aléatoire du temps restant.
        slack = EMG_SECONDS - n_seg * EMG_MIN_SEG
        weights = [random.random() for _ in range(n_seg)]
        wsum = sum(weights) or 1.0
        durs = [EMG_MIN_SEG + slack * w / wsum for w in weights]
        # Rattrape l'arrondi flottant sur la dernière consigne.
        durs[-1] += EMG_SECONDS - sum(durs)
        plan, acc = [], 0.0
        for i, d in enumerate(durs):
            acc += d
            plan.append(("CONTRACTEZ" if i % 2 == 0 else "RELÂCHEZ", acc))
        self._emg_plan = plan

    def _emg_consigne(self):
        """Consigne EMG courante pendant l'enregistrement : (label, reste_s).
        Retourne None hors enregistrement / plan absent."""
        rec = self.recording_until > 0 and time.time() < self.recording_until
        if not rec or not self._emg_plan:
            return None
        elapsed = EMG_SECONDS - (self.recording_until - time.time())
        for label, end in self._emg_plan:
            if elapsed < end:
                return label, end - elapsed
        label, end = self._emg_plan[-1]
        return label, max(0.0, end - elapsed)

    def _draw_emg(self, t):
        consigne = self._emg_consigne()
        sigma_now = self._live_emg()
        badge = None
        # Pendant un ENREGISTREMENT (1er calibrage OU recal EMG), la consigne
        # CONTRACTEZ/RELÂCHEZ prime sur l'indicateur d'état live : en recal le
        # port est déjà connu, sans cette priorité la consigne disparaissait.
        if consigne is not None:
            cname, crem = consigne
            sub = (f"Consigne aléatoire : {cname} encore "
                   f"{crem:.0f} s — suivez le rythme affiché.")
            if cname == "CONTRACTEZ":
                badge = (DANGER, f"{cname}  {crem:.0f}s", DANGER, DANGER_DIM)
            else:
                badge = (_darken(PHOSPHOR_MID, 0.35),
                         f"{cname}  {crem:.0f}s", PHOSPHOR_MID, PHOSPHOR_DIM)
        elif self.emg_port is not None:
            sub = (f"Muscle calibré → P{self.emg_port + 1}. "
                   f"σ repos={self.emg_rest:.0f}  seuil={self.emg_threshold:.0f}.")
            active = sigma_now >= self.emg_threshold
            scol   = PHOSPHOR_MID if active else _darken(PHOSPHOR_MID, 0.35)
            label  = f"{'CONTRACTÉ' if active else 'RELÂCHÉ'}  σ={sigma_now:.0f}"
            badge  = (scol, label, PHOSPHOR_MID, PHOSPHOR_DIM)
        else:
            sub = (f"{EMG_SECONDS:.0f} s : le port dont l'activité OSCILLE au "
                   f"rythme contracté/relâché sera le capteur EMG.")

        def label_fn(i, axis_excl):
            return f"P{i+1}" + ("  (acc)" if i in axis_excl else
                                ("  ♥" if i == self.ppg_port else
                                 ("  ⚡" if i == self.emg_port else "")))

        def highlight_fn(axis_excl, buffers):
            if self.emg_port is not None:
                return self.emg_port
            # Met en évidence le port le plus « nerveux » en direct.
            excl = set(axis_excl)
            best_port, best = None, EMG_MIN_SIGMA
            for cdt in (i for i in range(6) if i not in excl):
                sd = self._emg_sigma(buffers[cdt])
                if sd > best:
                    best, best_port = sd, cdt
            return best_port

        self._draw_sensor_step(
            t, state=STATE_EMG, title="MUSCLE / EMG", accent=PHOSPHOR_MID,
            shape="S",
            subtitle="Suivez la consigne affichée — durées ALÉATOIRES (≥ 1 s).",
            sub2=sub, badge=badge, label_fn=label_fn,
            highlight_fn=highlight_fn,
            prompt="[  OK, CALIBRER LE MUSCLE (EMG)  ]")

    def _draw_eda(self, t):
        eda_col = TETRO["O"]
        if self.eda_port is not None:
            sub = (f"EDA isolé → P{self.eda_port + 1}. "
                   f"Niveau de repos = {self.eda_rest:.0f}.")
        else:
            sub = (f"{EDA_SECONDS:.0f} s immobile : le port au signal "
                   f"CONTINU depuis le début sera l'EDA (par élimination).")
        lvl = self._live_eda()
        badge = None
        if self.eda_port is not None:
            badge = (eda_col, f"EDA {lvl:.0f}", eda_col,
                     _darken(eda_col, 0.5))

        def label_fn(i, axis_excl):
            return f"P{i+1}" + ("  (acc)" if i in axis_excl else
                                ("  ♥" if i == self.ppg_port else
                                 ("  ⚡" if i == self.emg_port else
                                  ("  ~" if i == self.eda_port else ""))))

        def highlight_fn(axis_excl, buffers):
            if self.eda_port is not None:
                return self.eda_port
            # Candidat EDA : port hors capteurs connus avec le plus de
            # signal continu (σ non nulle = pas un port débranché/plat).
            excl = set(axis_excl)
            if self.emg_port is not None:
                excl.add(self.emg_port)
            best_port, best = None, EDA_MIN_STD
            for cdt in (i for i in range(6) if i not in excl):
                sd = self._emg_sigma(buffers[cdt])
                if sd > best:
                    best, best_port = sd, cdt
            return best_port

        self._draw_sensor_step(
            t, state=STATE_EDA, title="EDA / SUDATION", accent=eda_col,
            shape="O",
            subtitle="Restez calme et immobile — mesure du niveau au repos.",
            sub2=sub, badge=badge, label_fn=label_fn,
            highlight_fn=highlight_fn,
            prompt="[  OK, CALIBRER L'EDA  ]")

    def _draw_deadzone(self, t):
        rect = self.layout.main
        self.screen.set_clip(rect)
        draw_panel(self.screen, rect, accent=AMBER)
        th  = self.theme
        sx  = max(10, int(rect.width * 0.018))
        sy  = max(8,  int(rect.height * 0.022))
        pad = rect.left + sx

        # En-tete
        y  = rect.top + sy
        bs = th.f_xl.get_height()
        draw_block(self.screen, pygame.Rect(pad, y, bs, bs), TETRO["T"])
        _bt = th.f_big.render(_STEP_NO[STATE_DEADZONE], True,
                              _darken(TETRO["T"], 0.78))
        self.screen.blit(_bt, _bt.get_rect(center=(pad + bs // 2,
                                                   y + bs // 2)))
        draw_text(self.screen, th.f_xl, "ZONE MORTE",
                  (pad + bs + sx, y - 2), color=TEXT_HI, glow=AMBER)

        y += th.f_xl.get_height() + max(6, sy // 2)
        draw_text(self.screen, th.f_med,
                  "Zone morte accelero + EMG (seuil & amplification) en "
                  "direct ; inversez G/D et H/B au besoin.",
                  (pad, y), color=TEXT_HI)
        bpm_now = self._live_bpm()
        if self.ppg_port is not None and bpm_now > 0:
            phase = (t * bpm_now / 60.0) % 1.0
            beat  = phase < 0.16 or 0.32 < phase < 0.46
            hc    = DANGER if beat else _darken(DANGER, 0.4)
            bpm_s = f"BPM {bpm_now}"
            bw    = th.f_med_b.size(bpm_s)[0]
            draw_text(self.screen, th.f_med_b, bpm_s,
                      (rect.right - sx - bw, y - 2), color=hc,
                      glow=DANGER_DIM if beat else None)

        y += th.f_med.get_height() + max(10, sy)
        body_top = y
        body_h   = rect.bottom - body_top - sy

        # Colonne gauche : radar (haut) + editeur de ports (bas)
        left_w     = min(max(150, rect.width // 2 - 2 * sx), int(rect.width * 0.44), 480)
        radar_size = max(100, min(int(body_h * 0.44), left_w, 360))
        radar      = pygame.Rect(rect.left + sx, body_top, radar_size, radar_size)
        pygame.draw.rect(self.screen, (10, 11, 24), radar, border_radius=4)
        pygame.draw.rect(self.screen, PHOSPHOR_DIM, radar, 1, border_radius=4)

        with self.device.lock:
            sample = self.device.latest
        if self.x_axis is not None and self.y_axis is not None:
            xn = _normalize(sample[self.x_axis],
                            self._axis_rest_mean(self.x_axis),
                            self.x_min, self.x_max)
            yn = _normalize(sample[self.y_axis],
                            self._axis_rest_mean(self.y_axis),
                            self.y_min, self.y_max)
        else:
            xn, yn = 0.0, 0.0
        if self.invert_x:
            xn = -xn
        if self.invert_y:
            yn = -yn
        draw_radar(self.screen, radar, xn, yn, self.slider.value, self.theme)

        # Editeur de ports compact sous le radar
        port_top  = radar.bottom + max(4, sy // 2)
        port_rect = pygame.Rect(rect.left + sx, port_top,
                                left_w, rect.bottom - port_top - sy)
        if port_rect.height > 30:
            self._draw_port_editor(port_rect, t)

        # Colonne droite : curseurs + inverseurs + boutons
        right_x = rect.left + sx + left_w + 2 * sx
        right_w = rect.right - right_x - sx
        right_y = body_top
        small_h = th.f_small.get_height()
        med_h   = th.f_med.get_height()

        # Boutons [RECALIBRER | VALIDER] en bas
        btn_h    = max(38, min(54, int(body_h * 0.11)))
        btn_top  = rect.bottom - btn_h - sy
        btn_gap  = max(6, sx // 2)
        btn_each = (right_w - btn_gap) // 2
        self.btn_recalibrate.rect = pygame.Rect(right_x, btn_top,
                                                btn_each, btn_h)
        self.btn_recalibrate.draw(self.screen, th.f_small, t)
        self.btn_main.rect = pygame.Rect(right_x + btn_each + btn_gap, btn_top,
                                         right_w - btn_each - btn_gap, btn_h)
        self.btn_main.accent = AMBER
        self.btn_main.draw(self.screen, th.f_med_b, t)

        # Inverseurs accéléro
        tg_h   = max(30, min(48, int(btn_h * 0.80)))
        tg_top = btn_top - max(8, sy // 2) - tg_h
        for btn, on, bx, bw in (
                (self.btn_inv_x, self.invert_x, right_x, btn_each),
                (self.btn_inv_y, self.invert_y,
                 right_x + btn_each + btn_gap,
                 right_w - btn_each - btn_gap)):
            btn.rect = pygame.Rect(bx, tg_top, bw, tg_h)
            btn.accent = AMBER if on else _darken(PHOSPHOR_MID, 0.35)
            btn.draw(self.screen, th.f_small, t)

        # Trois blocs curseur
        sig_emg = self._live_emg()
        gain    = self._emg_gain()
        dz_acc  = self.slider.value
        in_dead = math.hypot(xn, yn) <= dz_acc
        if in_dead:
            acc_state, acc_col = "CENTRE", _darken(AMBER, 0.4)
        else:
            ax = "<- " if xn < -dz_acc else ("-> " if xn > dz_acc else "")
            ay = "^" if yn > dz_acc else ("v" if yn < -dz_acc else "")
            acc_state, acc_col = (ax + ay).strip() or "---", AMBER
        emg_active = self.emg_port is not None and sig_emg >= self.emg_threshold

        emg_scale = max(1.0, self.emg_flex * self._emg_gain() * 1.1,
                        sig_emg * 1.15, self.emg_threshold * 1.6)
        blocks = [
            ("ACCEL  ZONE MORTE", AMBER, self.slider,
             acc_state, acc_col, None, None),
            (f"EMG  P{self.emg_port + 1}" if self.emg_port is not None
             else "EMG  N/A", PHOSPHOR_MID, self.slider_emg,
             (f"CONTRACTE s={sig_emg:.0f}" if emg_active
              else f"RELACHE s={sig_emg:.0f}"),
             PHOSPHOR_MID if emg_active else _darken(PHOSPHOR_MID, 0.4),
             (sig_emg, self.emg_threshold, emg_scale, emg_active,
              PHOSPHOR_MID), None),
            ("EMG  AMPLIFICATION", PHOSPHOR, self.slider_emg_gain,
             ("SIGNAL FORT" if gain >= 12 else
              ("AMPLIFIE" if gain > 2 else "BRUT")),
             PHOSPHOR if gain > 2 else _darken(PHOSPHOR, 0.4),
             None, f"x{gain:.1f}"),
        ]
        line_h   = med_h
        rail_h   = max(12, int(small_h * 1.0))
        gauge_h  = max(8,  int(small_h * 0.7))
        intra    = max(2,  sy // 4)
        blk_gap  = max(3,  sy // 4)
        smargin  = max(10, sx)
        heights = [line_h + intra + rail_h + blk_gap if g is None
                   else line_h + intra + gauge_h + intra + rail_h + blk_gap
                   for *_, g, _v in blocks]
        region_b   = tg_top - max(8, sy // 2)
        blocks_top = max(right_y + max(4, sy // 3),
                         region_b - sum(heights))

        by = blocks_top
        for (lbl, acc, sld, st_txt, st_col, gauge, vstr), bh in zip(
                blocks, heights):
            draw_text(self.screen, th.f_med_b, lbl, (right_x, by),
                      color=TEXT_HI)
            st_w = th.f_small.size(st_txt)[0]
            vals = vstr if vstr is not None else f"{sld.value:.2f}"
            vw   = th.f_med_b.size(vals)[0]
            draw_text(self.screen, th.f_med_b, vals,
                      (right_x + right_w - vw, by), color=acc, glow=acc)
            draw_text(self.screen, th.f_small, st_txt,
                      (right_x + right_w - vw - sx - st_w, by +
                       max(0, (med_h - small_h) // 2)), color=st_col)
            ry = by + line_h + intra
            if gauge is not None:
                gv, gth, gsc, gac, gcol = gauge
                draw_gauge(self.screen,
                           pygame.Rect(right_x + smargin, ry,
                                       right_w - 2 * smargin, gauge_h),
                           gv, gth, gsc, gcol, gac)
                ry += gauge_h + intra
            sld.rect = pygame.Rect(right_x + smargin, ry + rail_h // 2,
                                   right_w - 2 * smargin, 6)
            sld.draw_compact(self.screen)
            by += bh

        # Overlay selecteur de recalibrage
        if self.recal_select_mode:
            self._draw_recal_selector(rect, t)
        self.screen.set_clip(None)

    def _panel_title(self, rect, label, sub, pad):
        """En-tête commun des panneaux (PORTS / RECAL) : barre accent + titre
        + sous-titre. Retourne le Y du contenu sous l'en-tête."""
        th = self.theme
        x0 = rect.left + pad
        ty = rect.top + pad
        bar_h = th.f_small.get_height()
        pygame.draw.rect(self.screen, PHOSPHOR,
                         pygame.Rect(x0, ty + 2, max(4, pad // 4), bar_h))
        draw_text(self.screen, th.f_small, label,
                  (x0 + pad, ty), color=PHOSPHOR, glow=PHOSPHOR_DIM)
        draw_text(self.screen, th.f_tiny, sub,
                  (x0, ty + bar_h + max(4, pad // 4)), color=TEXT_DIM)
        return ty + bar_h + th.f_tiny.get_height() + 2 * max(4, pad // 4) + pad

    def _draw_port_editor(self, rect, t):
        """Éditeur des correspondances ports : par ligne, pastille capteur
        + libellé, puis stepper [◀] [valeur] [▶]. AUTO = auto-détecté."""
        th = self.theme
        pad = max(10, int(rect.width * 0.05))
        x0  = rect.left + pad
        w   = rect.width - 2 * pad
        top = self._panel_title(rect, "CORRESPONDANCE PORTS",
                                "pastille = couleur de la courbe scope",
                                pad)
        rows = {"x": ("AXE X · G/D", AMBER), "y": ("AXE Y · H/B", AMBER),
                "z": ("AXE Z", AMBER), "ppg": ("CŒUR", DANGER),
                "emg": ("EMG", PHOSPHOR_MID), "eda": ("EDA", TETRO["O"])}
        n   = len(self._port_keys)
        gap = max(4, (rect.bottom - pad - top) // (n * 8))
        rh  = min(56, (rect.bottom - pad - top - gap * (n - 1)) // n)
        btn = max(26, min(rh - 6, int(rh * 0.9)))
        chip = max(8, th.f_small.get_height() - 2)
        for i, k in enumerate(self._port_keys):
            lbl, col = rows[k]
            ry = top + i * (rh + gap)
            cy = ry + rh // 2
            pygame.draw.rect(self.screen, BG_PANEL,
                             pygame.Rect(x0, ry, w, rh), border_radius=4)
            pygame.draw.rect(self.screen, _darken(col, 0.4),
                             pygame.Rect(x0, ry, w, rh), 1, border_radius=4)
            # Pastille = couleur EXACTE de la courbe oscilloscope du port
            # effectif (PORT_COLORS) → on relie sans ambiguïté capteur ↔
            # courbe. Port non assigné/sauté : carré creux atténué.
            eff = self._port_value(k)
            curve_col = (PORT_COLORS[eff % len(PORT_COLORS)]
                         if eff is not None else None)
            chip_r = pygame.Rect(x0 + pad // 2, cy - chip // 2, chip, chip)
            if curve_col is not None:
                draw_block(self.screen, chip_r, curve_col)
            else:
                pygame.draw.rect(self.screen, _darken(col, 0.5), chip_r, 2,
                                 border_radius=2)
            draw_text(self.screen, th.f_small, lbl,
                      (x0 + pad // 2 + chip + max(6, pad // 3),
                       cy - th.f_small.get_height() // 2), color=TEXT_HI)
            bd = self.btn_port_dec[i]
            bi = self.btn_port_inc[i]
            bd.rect = pygame.Rect(x0 + int(w * 0.46), cy - btn // 2, btn, btn)
            bi.rect = pygame.Rect(x0 + w - btn - pad // 3,
                                  cy - btn // 2, btn, btn)
            bd.draw(self.screen, th.f_small, t)
            bi.draw(self.screen, th.f_small, t)
            ov  = self.port_override[k]
            eff = self._port_value(k)
            main = "AUTO" if ov is None else f"P{ov + 1}"
            mc   = PHOSPHOR_MID if ov is None else AMBER
            mid  = (bd.rect.right + bi.rect.left) // 2
            draw_text_centered(self.screen, th.f_small, main,
                               (mid, cy - th.f_tiny.get_height() // 2),
                               color=mc, glow=mc)
            sub = f"→ P{eff + 1}" if eff is not None else "→ —"
            draw_text_centered(self.screen, th.f_tiny, sub,
                               (mid, cy + th.f_small.get_height() // 2),
                               color=curve_col if curve_col is not None
                               else TEXT_DIM)

    def _draw_recal_menu(self, rect, t):
        """Sélecteur de recalibrage ciblé : 3 tuiles accent (titre + ce qui
        est refait). Un capteur recalibré, les autres conservés."""
        th = self.theme
        pad = max(10, int(rect.width * 0.05))
        x0  = rect.left + pad
        w   = rect.width - 2 * pad
        top = self._panel_title(rect, "RECALIBRER UN CAPTEUR",
                                "Les autres capteurs sont conservés", pad)
        tiles = [
            (self.btn_recal_ppg,   DANGER,      "REPOS + RYTHME CARDIAQUE"),
            (self.btn_recal_accel, AMBER,       "BALAYAGE G/D + H/B"),
            (self.btn_recal_emg,   PHOSPHOR_MID, "CONTRACTÉ / RELÂCHÉ"),
        ]
        gap = max(8, (rect.bottom - pad - top) // 14)
        bh  = (rect.bottom - pad - top - gap * (len(tiles) - 1)) // len(tiles)
        for i, (b, col, desc) in enumerate(tiles):
            by = top + i * (bh + gap)
            b.rect = pygame.Rect(x0, by, w, bh)
            b.accent = col
            b.draw(self.screen, th.f_med_b, t)
            draw_text(self.screen, th.f_tiny, desc,
                      (x0 + pad, by + bh - th.f_tiny.get_height()
                       - max(4, pad // 4)),
                      color=_darken(col, 0.78))

    def _draw_recal_selector(self, rect, t):
        """Overlay modal : cases a cocher pour choisir les capteurs a
        recalibrer. Budget vertical déterministe (titre / liste N lignes /
        pied) → tient à 4 capteurs même à 960×600 (hauteurs jamais < 0)."""
        th  = self.theme
        ow  = max(320, min(rect.width - 40, int(rect.width * 0.66)))
        oh  = max(300, min(rect.height - 40, int(rect.height * 0.82)))
        ox  = rect.centerx - ow // 2
        oy  = rect.centery - oh // 2
        ovl = pygame.Surface((ow, oh), pygame.SRCALPHA)
        ovl.fill((8, 9, 22, 220))
        self.screen.blit(ovl, (ox, oy))
        pygame.draw.rect(self.screen, AMBER,
                         pygame.Rect(ox, oy, ow, oh), 2, border_radius=6)

        pad  = max(14, int(ow * 0.05))
        gap  = max(6, int(oh * 0.018))
        foot_h = max(40, min(64, int(oh * 0.14)))
        title_h = th.f_xl.get_height()
        sub_h   = th.f_tiny.get_height()

        draw_text(self.screen, th.f_xl, "RECALIBRER",
                  (ox + pad, oy + pad), color=AMBER, glow=_darken(AMBER, 0.4))
        draw_text(self.screen, th.f_tiny, "Cochez les capteurs a recalibrer :",
                  (ox + pad, oy + pad + title_h + gap), color=TEXT_DIM)

        checks = [
            ("ppg",   self.btn_recal_sel_ppg,   DANGER,       "REPOS + RYTHME CARDIAQUE"),
            ("accel", self.btn_recal_sel_accel, AMBER,        "BALAYAGE G/D + H/B"),
            ("emg",   self.btn_recal_sel_emg,   PHOSPHOR_MID, "CONTRACTE / RELACHE"),
            ("eda",   self.btn_recal_sel_eda,   TETRO["O"],   "NIVEAU EDA AU REPOS"),
        ]
        n = len(checks)
        list_top    = oy + pad + title_h + gap + sub_h + gap
        list_bottom = oy + oh - pad - foot_h - gap
        row_gap = max(4, gap // 2)
        bh = max(28, (list_bottom - list_top - row_gap * (n - 1)) // n)
        box = max(16, bh // 2)
        cy = list_top
        for key, btn, col, desc in checks:
            checked = self.recal_checks[key]
            sq = pygame.Rect(ox + pad, cy + (bh - box) // 2, box, box)
            if checked:
                draw_block(self.screen, sq, col)
            else:
                pygame.draw.rect(self.screen, _darken(col, 0.35), sq, 2,
                                 border_radius=2)
            btn_x = ox + pad + box + 10
            btn_w = ow - 2 * pad - box - 10
            btn.rect   = pygame.Rect(btn_x, cy, btn_w, bh)
            btn.accent = col if checked else _darken(col, 0.40)
            btn.draw(self.screen, th.f_med_b, t)
            draw_text(self.screen, th.f_tiny, desc,
                      (btn_x + pad // 2, cy + bh - th.f_tiny.get_height() - 3),
                      color=_darken(col, 0.78))
            cy += bh + row_gap

        any_checked = any(self.recal_checks.values())
        fy = oy + oh - pad - foot_h
        conf_w = ow // 2 - pad - 4
        canc_w = ow - 2 * pad - conf_w - 8
        self.btn_recal_confirm.rect = pygame.Rect(ox + pad, fy, conf_w, foot_h)
        self.btn_recal_cancel.rect  = pygame.Rect(ox + pad + conf_w + 8, fy,
                                                  canc_w, foot_h)
        self.btn_recal_confirm.accent = DANGER if any_checked else _darken(DANGER, 0.35)
        self.btn_recal_cancel.accent  = PHOSPHOR
        self.btn_recal_confirm.draw(self.screen, th.f_med_b, t)
        self.btn_recal_cancel.draw(self.screen, th.f_small, t)

    def _draw_done(self, t):
        rect = self.layout.main
        self.screen.set_clip(rect)
        draw_panel(self.screen, rect, accent=PHOSPHOR_MID)
        # Bandeau de tuiles "ligne complétée"
        order = ["I", "J", "L", "O", "S", "T", "Z"]
        bs = max(20, rect.width // 26)
        total = len(order) * (bs + 6) - 6
        bxs = rect.centerx - total // 2
        for i, k in enumerate(order):
            off = int(5 * math.sin(t * 3 + i * 0.6))
            draw_block(self.screen,
                       pygame.Rect(bxs + i * (bs + 6), rect.top + 40 + off,
                                   bs, bs), TETRO[k])
        draw_text_centered(self.screen, self.theme.f_huge, "CALIBRAGE OK",
                           (rect.centerx, rect.top + 40 + bs + 64),
                           color=PHOSPHOR_MID, glow=PHOSPHOR_MID)
        draw_text_centered(self.screen, self.theme.f_small,
                           "› calibration.json écrit dans le dossier courant",
                           (rect.centerx, rect.top + 40 + bs + 118),
                           color=TEXT_MID)
        x_rest = self._axis_rest_mean(self.x_axis)
        y_rest = self._axis_rest_mean(self.y_axis)
        cards = [
            ("PORTS", f"X·{self._port_label(self.x_axis)}  "
             f"Y·{self._port_label(self.y_axis)}  "
             f"Z·{self._port_label(self.z_axis)}",
             PHOSPHOR),
            ("REPOS", f"X={x_rest:.0f}  Y={y_rest:.0f}", TETRO["J"]),
            ("ZONES MORTES",
             f"ACC {self.slider.value:.2f}  EMG {self.slider_emg.value:.2f}"
             f"  AMPLI ×{self._emg_gain():.1f}", AMBER),
            ("INVERSION",
             f"G/D {'OUI' if self.invert_x else 'NON'}  "
             f"H/B {'OUI' if self.invert_y else 'NON'}", TETRO["L"]),
            ("POULS", (f"P{self.ppg_port+1}  ·  {self.bpm_rest} BPM"
                       if self.ppg_port is not None else "N/A"), DANGER),
            ("EMG", (f"P{self.emg_port+1}  ·  seuil "
                     f"{self._apply_emg_threshold():.0f}"
                     if self.emg_port is not None else "N/A"), PHOSPHOR_MID),
            ("EDA", (f"P{self.eda_port+1}  ·  niveau "
                     f"{self.eda_rest:.0f}"
                     if self.eda_port is not None else "N/A"), TETRO["O"]),
        ]
        gx = rect.left + 60
        gw = rect.width - 120
        cw = (gw - 24) // 2
        # En-tête proportionnel : libère de la place aux petites fenêtres
        # (constant en grand). Bouton aussi proportionnel.
        gy = rect.top + 40 + bs + min(150, max(96, int(rect.height * 0.22)))
        btn_h  = max(56, min(70, int(rect.height * 0.12)))
        btn_gap = max(12, int(rect.height * 0.035))
        btn_top = rect.bottom - btn_h - btn_gap
        # Grille responsive : tient TOUJOURS entre l'en-tête et le bouton
        # (7 cartes → 4 rangées ; sinon débordait sur le bouton à 960×600).
        n_rows = (len(cards) + 1) // 2
        gap_c  = max(8, int(rect.height * 0.02))
        avail  = btn_top - gy - gap_c
        ch     = max(34, min(int(rect.height * 0.085),
                             (avail - gap_c * (n_rows - 1)) // n_rows))
        for i, (lab, val, col) in enumerate(cards):
            cx = gx + (i % 2) * (cw + 24)
            cy = gy + (i // 2) * (ch + gap_c)
            card = pygame.Rect(cx, cy, cw, ch)
            pygame.draw.rect(self.screen, BG_PANEL, card, border_radius=4)
            pygame.draw.rect(self.screen, _darken(col, 0.4), card, 1,
                             border_radius=4)
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(card.x, card.y + 4, 4,
                                         card.h - 8))
            draw_text(self.screen, self.theme.f_tiny, lab,
                      (card.x + 18, card.y + 10), color=col)
            draw_text(self.screen, self.theme.f_med_b, val,
                      (card.x + 18, card.y + 10 +
                       self.theme.f_tiny.get_height() + 4), color=TEXT_HI)
        btn_w = max(280, rect.width // 3)
        bx = rect.left + (rect.width - btn_w) // 2
        self.btn_main.rect = pygame.Rect(bx, btn_top, btn_w, btn_h)
        self.btn_main.accent = PHOSPHOR_MID
        self.btn_main.draw(self.screen, self.theme.f_med_b, t)
        self.screen.set_clip(None)

    # ── Helpers de placement ───────────────────────────────────────
    def _scope_rect(self, panel):
        # Sous l'en-tête réel (hauteur des polices variable) + 1 ligne info.
        hdr = getattr(self, "_hdr_bottom", panel.top + int(panel.height * 0.30))
        # États avec bouton PASSER : 2 rangées (PASSER au-dessus du bouton
        # principal) → réserver plus de bas pour ne pas chevaucher le scope.
        zone_frac = 0.36 if self.state in _SKIP_STATES else 0.24
        btn_zone = max(100, int(panel.height * zone_frac))
        gap_top = max(12, int(panel.height * 0.04))
        top = hdr + gap_top
        bottom = panel.bottom - btn_zone
        return pygame.Rect(
            panel.left + 20, top,
            panel.width - 40, max(80, bottom - top)
        )

    def _place_main_button(self, panel):
        btn_h = max(56, min(88, int(panel.height * 0.18)))
        btn_w = max(300, min(panel.width - 40, int(panel.width * 0.58)))
        bx = panel.left + (panel.width - btn_w) // 2
        gap = max(16, int(panel.height * 0.04))
        self.btn_main.rect = pygame.Rect(bx, panel.bottom - btn_h - gap, btn_w, btn_h)

    def _draw_progress_or_button(self, t, rect, prompt_label):
        rec = self.recording_until > 0 and time.time() < self.recording_until
        if rec:
            remaining = self.recording_until - time.time()
            total = {STATE_REST: REST_SECONDS,
                     STATE_HR:   HR_SECONDS,
                     STATE_EMG:  EMG_SECONDS,
                     STATE_EDA:  EDA_SECONDS}.get(self.state, MOVE_SECONDS)
            frac = max(0.0, min(1.0, 1.0 - max(0, remaining) / total))
            # Pile de tuiles qui se remplit (clear de ligne en cours)
            cols = 20
            seg = (rect.width - 120) // cols
            bar_w = seg * cols
            bx0 = rect.left + (rect.width - bar_w) // 2
            by_gap = max(50, int(rect.height * 0.14))
            by = rect.bottom - by_gap
            lit = int(frac * cols + 0.001)
            order = list(TETRO)
            for i in range(cols):
                cell = pygame.Rect(bx0 + i * seg, by, seg - 4, 30)
                if i < lit:
                    draw_block(self.screen, cell,
                               TETRO[order[i % len(order)]])
                else:
                    pygame.draw.rect(self.screen, GRID_HI, cell, 1,
                                     border_radius=3)
            pulse = AMBER if int(t * 4) % 2 == 0 else _darken(AMBER, 0.4)
            cs = self.theme.f_xl.get_height()
            txt = f"{remaining:0.1f}s"
            ts = self.theme.f_xl.render(txt, True, AMBER)
            tx = rect.centerx - (cs + 14 + ts.get_width()) // 2
            ty = by - cs - max(14, int(rect.height * 0.04))
            draw_block(self.screen, pygame.Rect(tx, ty, cs, cs), pulse)
            rl = self.theme.f_tiny.render("REC", True, _darken(AMBER, 0.78))
            self.screen.blit(rl, rl.get_rect(center=(tx + cs // 2,
                                                     ty + cs // 2)))
            for off in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                g = self.theme.f_xl.render(txt, True, AMBER)
                g.set_alpha(80)
                self.screen.blit(g, (tx + cs + 14 + off[0], ty + off[1]))
            self.screen.blit(ts, (tx + cs + 14, ty))
        else:
            self.btn_main.label = prompt_label
            self.btn_main.accent = PHOSPHOR
            self._place_main_button(rect)
            self.btn_main.draw(self.screen, self.theme.f_med_b, t)
            if self.state in _SKIP_STATES:
                # PASSER : bouton séparé, EMPILÉ au-dessus du principal (le
                # libellé du principal est long → pas de partage de rangée
                # qui le rétrécirait illisible à 960×600). Centré, plus bas.
                mb = self.btn_main.rect
                skip_h = max(34, int(mb.height * 0.58))
                skip_w = max(220, min(rect.width - 40,
                                      int(rect.width * 0.42)))
                skip_gap = max(10, int(rect.height * 0.018))
                sx = rect.left + (rect.width - skip_w) // 2
                self.btn_skip.rect = pygame.Rect(
                    sx, mb.y - skip_gap - skip_h, skip_w, skip_h)
                self.btn_skip.enabled = True
                self.btn_skip.accent = DANGER
                self.btn_skip.draw(self.screen, self.theme.f_small, t)


def _normalize(v, rest, vmin, vmax):
    if v >= rest:
        return (v - rest) / max(1, (vmax - rest))
    return (v - rest) / max(1, (rest - vmin))


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main(argv):
    address = DEFAULT_ADDR
    for a in argv:
        if not a.startswith("-"):
            address = a

    pygame.init()
    pygame.display.set_caption("BITalino — Calibrage Accéléromètre")
    flags = pygame.RESIZABLE | pygame.DOUBLEBUF
    screen = pygame.display.set_mode((INITIAL_W, INITIAL_H), flags)

    app = App(screen, address)
    try:
        app.run()
    finally:
        if app.device is not None:
            try:
                app.device.stop_flag = True
                if app.acq_thread is not None:
                    app.acq_thread.join(timeout=2)
                app.device.stop()
                app.device.close()
            except Exception:
                pass
        pygame.quit()
