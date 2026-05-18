"""Vérification headless du package calibrage/ (pas de pygame/BITalino requis).

Stube pygame + plux, puis :
  - importe le package (shim calibrage.py → calibrage/),
  - rend chaque écran (_draw) pour tous les STATE_* à 5 tailles (dont MIN 960×600),
  - vérifie l'ordre de la machine d'état (REPOS→CŒUR→EMG→G/D→H/B→ZONE),
  - vérifie la détection (axes excluent PPG+EMG ; détection EMG ; cas plat),
  - vérifie l'écriture de calibration.json (blocs ppg + emg),
  - vérifie la cohérence des numéros de badge et la parité init/restart.

Usage :  python tools/calibrage_selfcheck.py
Sortie  :  "ALL GREEN ..." + exit 0 si tout passe, sinon AssertionError.
"""

import importlib
import json
import math
import re
import sys
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")


# ── Stub pygame ────────────────────────────────────────────────────────
class _PG(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("K_") or n.isupper():
            return 0
        raise AttributeError(n)


pg = _PG("pygame")


class Rect:
    def __init__(self, x=0, y=0, w=0, h=0):
        if isinstance(x, Rect):
            x, y, w, h = x.x, x.y, x.width, x.height
        elif isinstance(x, (tuple, list)):
            x, y, w, h = x
        self.x, self.y, self.width, self.height = int(x), int(y), int(w), int(h)

    def __iter__(self):
        return iter((self.x, self.y, self.width, self.height))

    w = property(lambda s: s.width)
    h = property(lambda s: s.height)
    left = property(lambda s: s.x)
    right = property(lambda s: s.x + s.width)
    top = property(lambda s: s.y)
    bottom = property(lambda s: s.y + s.height)
    centerx = property(lambda s: s.x + s.width // 2)
    centery = property(lambda s: s.y + s.height // 2)
    center = property(lambda s: (s.centerx, s.centery))
    topleft = property(lambda s: (s.x, s.y))
    topright = property(lambda s: (s.right, s.y))
    bottomleft = property(lambda s: (s.x, s.bottom))
    bottomright = property(lambda s: (s.right, s.bottom))
    midtop = property(lambda s: (s.centerx, s.y))
    midbottom = property(lambda s: (s.centerx, s.bottom))
    midleft = property(lambda s: (s.x, s.centery))
    midright = property(lambda s: (s.right, s.centery))
    size = property(lambda s: (s.width, s.height))

    def get_rect(self, **k):
        r = Rect(0, 0, self.width, self.height)
        if "center" in k:
            c = k["center"]
            r.x, r.y = c[0] - r.width // 2, c[1] - r.height // 2
        return r

    def inflate(self, a, b):
        return Rect(self.x - a // 2, self.y - b // 2, self.width + a, self.height + b)

    def move(self, a, b):
        return Rect(self.x + a, self.y + b, self.width, self.height)

    def collidepoint(self, *a):
        return False

    def clamp(self, *a):
        return self

    def copy(self):
        return Rect(self.x, self.y, self.width, self.height)


class Surface:
    def __init__(self, sz=(10, 10), *a, **k):
        self._s = tuple(sz)

    def fill(self, *a, **k):
        pass

    def blit(self, *a, **k):
        pass

    def get_size(self):
        return self._s

    def get_width(self):
        return self._s[0]

    def get_height(self):
        return self._s[1]

    def get_rect(self, **k):
        r = Rect(0, 0, *self._s)
        if "center" in k:
            c = k["center"]
            r.x, r.y = c[0] - r.width // 2, c[1] - r.height // 2
        return r

    def set_alpha(self, *a):
        pass

    def set_colorkey(self, *a):
        pass

    def set_clip(self, *a):
        pass

    def convert(self, *a):
        return self

    def convert_alpha(self, *a):
        return self

    def subsurface(self, *a):
        return self

    def copy(self):
        return Surface(self._s)


class Font:
    def __init__(self, *a, **k):
        pass

    def render(self, *a, **k):
        return Surface((40, 14))

    def get_height(self):
        return 14

    def get_linesize(self):
        return 16

    def size(self, x):
        return (len(str(x)) * 7, 14)


pg.Rect = Rect
pg.Surface = Surface
pg.init = lambda *a, **k: None
pg.quit = lambda: None
pg.font = types.SimpleNamespace(
    init=lambda: None, SysFont=lambda *a, **k: Font(),
    Font=lambda *a, **k: Font(), get_init=lambda: True)
pg.draw = types.SimpleNamespace(
    rect=lambda *a, **k: None, line=lambda *a, **k: None,
    lines=lambda *a, **k: None, circle=lambda *a, **k: None,
    polygon=lambda *a, **k: None, aaline=lambda *a, **k: None,
    aalines=lambda *a, **k: None, arc=lambda *a, **k: None,
    ellipse=lambda *a, **k: None)
pg.display = types.SimpleNamespace(
    set_mode=lambda *a, **k: Surface((1280, 720)),
    set_caption=lambda *a: None, flip=lambda: None,
    update=lambda *a: None, get_surface=lambda: Surface((1280, 720)))
pg.time = types.SimpleNamespace(
    Clock=lambda: types.SimpleNamespace(tick=lambda *a: 16),
    get_ticks=lambda: 0)
pg.event = types.SimpleNamespace(get=lambda: [], pump=lambda: None)
pg.mouse = types.SimpleNamespace(
    get_pos=lambda: (0, 0), get_pressed=lambda: (0, 0, 0))
pg.key = types.SimpleNamespace(get_pressed=lambda: {})
pg.transform = types.SimpleNamespace(
    smoothscale=lambda s, sz: Surface(sz), scale=lambda s, sz: Surface(sz))
pg.gfxdraw = types.SimpleNamespace(
    aacircle=lambda *a: None, filled_circle=lambda *a: None)
sys.modules["pygame"] = pg
sys.modules["pygame.gfxdraw"] = pg.gfxdraw

# ── Stub plux ──────────────────────────────────────────────────────────
_plux = types.ModuleType("plux")


class SignalsDev:
    def __init__(self, *a, **k):
        pass


_plux.SignalsDev = SignalsDev
sys.modules["plux"] = _plux


def main():
    C = importlib.import_module("calibrage.app")
    pkg = importlib.import_module("calibrage")
    assert callable(pkg.main), "le package doit exposer main()"

    # 1) badges dérivés de l'ordre canonique
    assert C._STEP_NO == {
        C.STATE_REST: "01", C.STATE_HR: "02", C.STATE_LR: "03",
        C.STATE_UD: "04", C.STATE_EMG: "05", C.STATE_EDA: "06",
        C.STATE_DEADZONE: "07",
    }, C._STEP_NO

    # 2) rendu de tous les écrans à 5 tailles (960×600 → 2560×1440)
    app = C.App(pg.display.set_mode((1280, 720)), "SIMULATED")
    app.device = C.SimulatedDevice()
    app.rest_samples = [(512, 510, 512, 400, 64, 900) for _ in range(300)]
    app.lr_samples = app.ud_samples = app.rest_samples
    app.x_axis, app.y_axis, app.z_axis = 0, 1, 2
    app.x_min, app.x_max, app.y_min, app.y_max = 300, 720, 310, 700
    app.ppg_port, app.bpm_rest = 3, 72
    app.emg_port, app.emg_rest, app.emg_flex, app.emg_threshold = 4, 4.0, 70.0, 27.0
    app.eda_port, app.eda_rest = 5, 700.0
    app._auto_ports = {"x": 0, "y": 1, "z": 2, "ppg": 3, "emg": 4, "eda": 5}
    for st in (C.STATE_INTRO, C.STATE_REST, C.STATE_HR, C.STATE_EMG,
               C.STATE_EDA, C.STATE_LR, C.STATE_UD, C.STATE_DEADZONE,
               C.STATE_DONE):
        for sz in ((960, 600), (1280, 720), (1100, 720), (1920, 1400), (2560, 1440)):
            app.screen = pg.display.set_mode(sz)
            app.state = st
            app._draw(1.0)
    # 2b) éditeur de ports (toujours visible dans zone morte) : rendu multi-tailles
    app.state = C.STATE_DEADZONE
    for sz in ((960, 600), (1280, 720), (1100, 720), (1920, 1400), (2560, 1440)):
        app.screen = pg.display.set_mode(sz)
        app._draw(1.0)
    # 2c) sélecteur de recalibrage : rendu multi-tailles
    app.recal_select_mode = True
    for sz in ((960, 600), (1280, 720), (1100, 720), (1920, 1400), (2560, 1440)):
        app.screen = pg.display.set_mode(sz)
        app._draw(1.0)
    app.recal_select_mode = False

    # 3) ordre de la machine d'état
    body = open("calibrage/app.py", encoding="utf-8").read()
    i = body.index("def _on_recording_done")
    seg = body[i:body.index("\n    def _ppg_excl")]
    pairs = re.findall(
        r"if self\.state == (STATE_\w+):|self\.state = (STATE_\w+)", seg)
    flow, cur = [], None
    for c, a in pairs:
        if c:
            cur = c
        elif a and cur:
            flow.append((cur, a))
            cur = None
    # EDA→ZONE MORTE et les retours recal ciblé passent par
    # _return_to_deadzone() (hors regex). EMG→EDA est littéral (flux plein) ;
    # le recal EMG ciblé sort via _advance_recal() (hors regex).
    # Ordre = ordre des branches dans _on_recording_done :
    # REST, HR, EMG(→EDA), EDA(helper), LR, UD.
    assert flow == [
        ("STATE_REST", "STATE_HR"), ("STATE_HR", "STATE_LR"),
        ("STATE_EMG", "STATE_EDA"), ("STATE_LR", "STATE_UD"),
        ("STATE_UD", "STATE_EMG")], flow

    # 4) détection : axes excluent PPG+EMG ; EMG par modulation ; plat → None
    D = importlib.import_module("calibrage.detection")
    rest = [(512, 512, 512, 400, 64, 900) for _ in range(600)]
    lr = [(int(512 + 200 * math.sin(i * 0.3)), 512, 512, 400,
           int(64 + 300 * math.sin(i * 0.9)), 900) for i in range(600)]
    assert D.detect_x_axis(rest, lr, (3, 4)) == 0
    # EMG FAIBLE en ALTERNANCE 1 s contracté / 1 s relâché (freq 100 Hz,
    # 8 s) : amplitude ±10 ADC seulement → doit quand même être isolé.
    F = 100
    rest_emg = [(512, 512, 512, 400, 64, 900) for _ in range(8 * F)]
    flex_emg = []
    for i in range(8 * F):
        contracted = (i // F) % 2 == 0          # 1 s on / 1 s off
        e = 64 + (10 * math.sin(i * 1.3) if contracted else 0)
        flex_emg.append((512, 512, 512, 400, int(e), 900))
    assert D.detect_emg_port(rest_emg, flex_emg, (3,), F)[0] == 4
    # Pas d'alternance (signal plat partout) → aucune modulation → None.
    assert D.detect_emg_port(rest_emg, rest_emg, (3,), F)[0] is None
    # Discriminant : port 4 = faible mais MODULÉ ; port 5 = grosse σ
    # CONSTANTE (bruit fort non modulé). Doit choisir 4, pas 5.
    flex_mix = []
    for i in range(8 * F):
        contracted = ((i + F // 2) // F) % 2 == 0      # alternance déphasée
        e4 = 64 + (8 * math.sin(i * 1.3) if contracted else 0)
        e5 = 64 + 90 * math.sin(i * 2.1)               # σ élevée, plate
        flex_mix.append((512, 512, 512, 400, int(e4), int(e5)))
    rest_mix = [(512, 512, 512, 400, 64, 64) for _ in range(8 * F)]
    assert D.detect_emg_port(rest_mix, flex_mix, (3,), F)[0] == 4
    # Amplification À LA DÉTECTION : capteur TRÈS faible. Sans gain la
    # modulation reste sous EMG_MIN_MOD → None ; amplifiée → port trouvé.
    weak = []
    for i in range(8 * F):
        contracted = (i // F) % 2 == 0
        e = 64 + (2 * math.sin(i * 1.3) if contracted else 0)
        weak.append((512, 512, 512, 400, int(e), 900))
    assert D.detect_emg_port(rest_emg, weak, (3,), F, gain=1.0)[0] is None
    assert D.detect_emg_port(rest_emg, weak, (3,), F, gain=200.0)[0] == 4
    # EDA : PPG(3) + axes(0,1,2) + EMG(4) exclus → port restant 5 au signal
    # CONTINU lent (dérive tonique) doit être isolé. Plat partout → None.
    eda_s = [(512, 512, 512, 400, 64,
              int(700 + 30 * math.sin(i * 0.02))) for i in range(6 * F)]
    assert D.detect_eda_port(eda_s, (0, 1, 2, 3, 4)) == 5
    flat = [(512, 512, 512, 400, 64, 0) for _ in range(6 * F)]
    assert D.detect_eda_port(flat, (0, 1, 2, 3, 4)) is None

    # 4b) plan de consignes EMG aléatoire : alternance, ≥1 s, ≥3+3, somme=30
    for _ in range(200):
        app._build_emg_plan()
        plan = app._emg_plan
        labels = [lb for lb, _e in plan]
        ends = [e for _lb, e in plan]
        durs = [ends[0]] + [ends[k] - ends[k - 1] for k in range(1, len(ends))]
        assert labels[0] == "CONTRACTEZ", labels
        assert all(labels[k] != labels[k + 1]
                   for k in range(len(labels) - 1)), labels
        assert all(d >= C.EMG_MIN_SEG - 1e-6 for d in durs), durs
        assert labels.count("CONTRACTEZ") >= C.EMG_MIN_CONTRACT, labels
        assert labels.count("RELÂCHEZ") >= C.EMG_MIN_RELEASE, labels
        assert abs(ends[-1] - C.EMG_SECONDS) < 1e-6, ends[-1]
    app._emg_plan = []

    # 4c) éditeur ports : cycle AUTO→P1..P6→AUTO, override applique l'attr
    app._auto_ports = {"x": 0, "y": 1, "z": 2, "ppg": 3, "emg": 4, "eda": 5}
    app.port_override = {k: None for k in app._port_keys}
    app._apply_port("x")
    assert app._port_value("x") == 0 and app.x_axis == 0, app.x_axis
    app._cycle_port("x", +1)                 # None → P1 (index 0)
    assert app.port_override["x"] == 0 and app.x_axis == 0
    app._cycle_port("x", -1)                 # P1 → AUTO
    assert app.port_override["x"] is None and app.x_axis == 0
    app._cycle_port("x", -1)                 # AUTO → P6 (wrap)
    assert app.port_override["x"] == 5 and app.x_axis == 5
    app._cycle_port("ppg", +1)               # change port cœur
    assert app.port_override["ppg"] == 0 and app.ppg_port == 0
    app.port_override = {k: None for k in app._port_keys}
    for k in app._port_keys:
        app._apply_port(k)

    # 4d) recalibrage ciblé : saut au bon état
    for tgt, st in (("ppg", C.STATE_REST), ("accel", C.STATE_LR),
                    ("emg", C.STATE_EMG), ("eda", C.STATE_EDA)):
        app.recal_select_mode = True
        app._start_single_recal(tgt)
        assert app.state == st and app.recal_target == tgt, (tgt, app.state)
        assert app.recal_select_mode is False   # selecteur ferme
    app._return_to_deadzone()
    assert app.state == C.STATE_DEADZONE and app.recal_target is None
    assert app.recording_until == 0.0
    # 4e) multi-recalibrage : file ppg+emg -> etat REST d'abord
    app._start_recal({"ppg", "emg"})
    assert app.state == C.STATE_REST and app.recal_target == "ppg", app.state
    assert app.recal_queue == ["ppg", "emg"], app.recal_queue
    app._return_to_deadzone()
    # transition recal accéléro : UD terminé → retour ZONE MORTE (pas EMG)
    F2 = 60
    app.rest_samples = [(512, 512, 512, 400, 64, 900) for _ in range(4 * F2)]
    ud = [(512, 512, int(512 + 200 * math.sin(i * 0.4)), 400, 64, 900)
          for i in range(4 * F2)]
    with app.device.lock:
        app.device.recorded = ud           # _stop_recording lira ceci
    app.ppg_port, app.emg_port, app.x_axis = 3, 4, 0
    app.recal_target = "accel"
    app.state = C.STATE_UD
    app._on_recording_done()
    assert app.state == C.STATE_DEADZONE and app.recal_target is None, app.state

    # 5) parité init / restart (réinitialisation partagée)
    app._restart_calibration()
    assert app.emg_port is None and app.bpm_rest == 0 and app.rest_samples == []
    assert app._emg_plan == [], app._emg_plan

    # 6) calibration.json contient ppg + emg
    app.rest_samples = rest
    app.x_axis, app.y_axis, app.z_axis = 0, 1, 2
    app.x_min, app.x_max, app.y_min, app.y_max = 300, 720, 310, 700
    app.ppg_port, app.bpm_rest = 3, 72
    app.emg_port, app.emg_rest, app.emg_flex, app.emg_threshold = 4, 4.0, 70.0, 27.0
    app.slider.value = 0.3
    # Zone morte EMG réglable + inverseurs accéléro (PPG ZM supprimée)
    app.slider_emg.value = 0.50
    app.invert_x, app.invert_y = True, False
    app._save_and_finish()
    j = json.load(open("calibration.json", encoding="utf-8"))
    assert j["ppg"]["port"] == 4 and j["emg"]["port"] == 5, j
    # PPG : plus de zone morte (port + bpm seulement)
    assert set(j["ppg"]) == {"port", "bpm_rest"}, j["ppg"]
    # zone morte EMG : threshold = σ_repos + dz·(σ_flex − σ_repos)
    assert j["emg"]["dead_zone"] == 0.5, j["emg"]
    assert abs(j["emg"]["threshold"] - (4.0 + 0.5 * (70.0 - 4.0))) < 1e-6, j
    assert j["invert"] == {"x": True, "y": False}, j["invert"]
    # EMG amplifié + correspondances ports écrites
    assert j["emg"]["gain"] == C.EMG_GAIN, j["emg"]   # défaut = EMG_GAIN
    # curseur AMPLI EMG : 0→MIN, 1→MAX, cohérent aller-retour
    assert C._slider_to_emg_gain(0.0) == C.EMG_GAIN_MIN
    assert C._slider_to_emg_gain(1.0) == C.EMG_GAIN_MAX
    assert abs(C._slider_to_emg_gain(
        C._emg_gain_to_slider(9.0)) - 9.0) < 1e-6
    app.emg_rest, app.emg_flex = 4.0, 70.0
    app.slider_emg_gain.value = 1.0          # gain max
    app.slider_emg.value = 0.5
    app._save_and_finish()
    j = json.load(open("calibration.json", encoding="utf-8"))
    assert j["emg"]["gain"] == C.EMG_GAIN_MAX, j["emg"]
    # seuil EMG = σ BRUT (gain n'entre PAS dans le seuil)
    assert abs(j["emg"]["threshold"] - (4.0 + 0.5 * (70.0 - 4.0))) < 1e-6, j
    app.slider_emg_gain.value = C._emg_gain_to_slider(C.EMG_GAIN)
    assert set(j["ports_override"]) == {"x", "y", "z", "ppg", "emg",
                                         "eda"}, j
    assert all(v is None for v in j["ports_override"].values()), j
    app._auto_ports = {"x": 0, "y": 1, "z": 2, "ppg": 3, "emg": 4, "eda": 5}
    app.port_override = {k: None for k in app._port_keys}
    app.port_override["emg"] = 5            # override manuel EMG → P6
    app._apply_port("emg")
    app._save_and_finish()
    j = json.load(open("calibration.json", encoding="utf-8"))
    assert j["ports_override"]["emg"] == 6 and j["emg"]["port"] == 6, j
    # toggles inverseurs : _restart remet tout à zéro
    app._restart_calibration()
    assert app.invert_x is False and app.invert_y is False
    assert app.port_edit is True   # port_edit toujours visible
    assert all(v is None for v in app.port_override.values())
    assert app.slider_emg.value == C.EMG_THRESHOLD_FRAC
    assert abs(C._slider_to_emg_gain(app.slider_emg_gain.value)
               - C.EMG_GAIN) < 1e-6

    print("ALL GREEN — calibrage package OK "
          "(ordre CŒUR→ACCÉLÉRO→EMG, rendu, détection, JSON)")


if __name__ == "__main__":
    main()
