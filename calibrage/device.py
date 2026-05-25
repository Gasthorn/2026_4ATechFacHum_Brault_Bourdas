"""Couche périphérique BITalino : carte réelle (PLUX) + simulateur."""

import math
import random
import threading
import time
from collections import deque

from .config import (ALL_PORTS, EMG_CYCLE_SECONDS, PLUX_AVAILABLE,
                     SAMPLING_HZ, plux)


#  Devices
# ─────────────────────────────────────────────
if PLUX_AVAILABLE:
    class CalibrationDevice(plux.SignalsDev):
        def __init__(self, address):
            plux.SignalsDev.__init__(address)
            self.frequency  = SAMPLING_HZ
            self.lock       = threading.Lock()
            self.stop_flag  = False
            self.latest     = (0,) * 6
            self.recording  = False
            self.recorded   = []
            self.live_buf   = [deque([512] * 720, maxlen=720) for _ in ALL_PORTS]
            self._tick      = 0

        def onRawFrame(self, nSeq, data):
            sample = tuple(int(v) for v in data[:6])
            with self.lock:
                self.latest = sample
                if self.recording:
                    self.recorded.append(sample)
                self._tick += 1
                if self._tick % 8 == 0:
                    for i, v in enumerate(sample):
                        self.live_buf[i].append(v)
            return self.stop_flag


class SimulatedDevice:
    def __init__(self):
        self.frequency = SAMPLING_HZ
        self.lock      = threading.Lock()
        self.stop_flag = False
        self.latest    = (512,) * 6
        self.recording = False
        self.recorded  = []
        self.live_buf  = [deque([512] * 720, maxlen=720) for _ in ALL_PORTS]
        self._t        = 0
        self._mode     = "rest"

    def loop(self):
        rng = random.Random(7)
        while not self.stop_flag:
            self._t += 1
            t = self._t / 120.0
            x = 512 + int(2 * math.sin(t * 13) + rng.uniform(-2, 2))
            y = 510 + int(2 * math.cos(t * 11) + rng.uniform(-2, 2))
            z = 780 + int(1.5 * math.sin(t *  7) + rng.uniform(-2, 2))
            if self._mode == "lr":
                x = int(512 + 220 * math.sin(t * 3) + rng.uniform(-3, 3))
            elif self._mode == "ud":
                y = int(510 + 200 * math.sin(t * 2.4) + rng.uniform(-3, 3))
            elif self._mode == "radar":
                x = int(512 + 180 * math.sin(t * 1.7))
                y = int(510 + 140 * math.cos(t * 1.3))
            # PPG simulé sur le port 4 (index 3), ~72 BPM (1.2 Hz).
            # Toujours actif : il "bouge encore" même accéléromètre immobile.
            ppg = int(400 + 80 * math.sin(t * 0.905) + rng.uniform(-6, 6))
            # EMG simulé sur le port 5 (index 4) : plat au repos (~64).
            # En calib. EMG : ALTERNANCE contracté/relâché à FAIBLE amplitude
            # (≈±15 ADC) — la détection se fait par modulation, pas amplitude.
            #
            # IMPORTANT : la cadence doit suivre les ÉCHANTILLONS (self._t,
            # = index d'acquisition), PAS `t` (mis à l'échelle /120).
            # detect_emg_port mesure σ par demi-cycle de
            # EMG_CYCLE_SECONDS × frequency échantillons ; si l'alternance
            # sim ne s'aligne pas sur `frequency`, un demi-cycle ne fait que
            # ~120 échantillons contre une fenêtre de détection de ~500 → la
            # modulation est moyennée sur plusieurs cycles et le port EMG
            # n'est JAMAIS détecté en mode démo.
            emg = 64
            if self._mode == "emg":
                half = max(1, int(EMG_CYCLE_SECONDS * self.frequency))
                contracted = (self._t % (2 * half)) < half
                if contracted:
                    # Bruit large bande : variance invariante à la décimation
                    # 1/8 du live_buf (la jauge live reste cohérente).
                    emg = int(64 + rng.uniform(-15, 15))
                else:
                    emg = int(64 + rng.uniform(-2, 2))
            # EDA simulé sur le port 6 (index 5) : signal CONTINU présent
            # depuis le début (dérive tonique lente + petit bruit). Jamais
            # plat à zéro → détectable par élimination comme l'EDA.
            eda = int(700 + 40 * math.sin(t * 0.05) + 12 * math.sin(t * 0.31)
                      + rng.uniform(-2, 2))
            sample = (x, y, z, ppg, emg, eda)
            with self.lock:
                self.latest = sample
                if self.recording:
                    self.recorded.append(sample)
                if self._t % 8 == 0:
                    for i, v in enumerate(sample):
                        self.live_buf[i].append(v)
            time.sleep(1.0 / self.frequency)

    def start(self, *_a, **_kw):
        pass

    def stop(self):
        self.stop_flag = True

    def close(self):
        pass

    def set_mode(self, mode):
        self._mode = mode
