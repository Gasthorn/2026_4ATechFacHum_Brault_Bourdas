"""Constantes, configuration PLUX et palette graphique."""

import platform
import sys

# ─────────────────────────────────────────────
#  Configuration de l'API PLUX
# ─────────────────────────────────────────────
osDic = {
    "Darwin": f"MacOS/Intel{''.join(platform.python_version().split('.')[:2])}",
    "Linux": "Linux64",
    "Windows": f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}",
}
if platform.mac_ver()[0] != "":
    import subprocess
    from os import linesep
    p = subprocess.Popen("sw_vers", stdout=subprocess.PIPE)
    result = p.communicate()[0].decode("utf-8").split(str("\t"))[2].split(linesep)[0]
    if result.startswith("12."):
        osDic["Darwin"] = "MacOS/Intel310"

sys.path.append(f"PLUX-API-Python3/{osDic.get(platform.system(), '')}")

try:
    import plux
    PLUX_AVAILABLE = True
except Exception:
    PLUX_AVAILABLE = False

if not PLUX_AVAILABLE:
    plux = None  # nom toujours défini pour les imports


# ─────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────
INITIAL_W, INITIAL_H = 1280, 720
MIN_W,     MIN_H     = 960, 600
FPS                  = 60
DEFAULT_ADDR         = "BTH98:D3:51:FE:87:0E"
SAMPLING_HZ          = 1000
ALL_PORTS            = [1, 2, 3, 4, 5, 6]
REST_SECONDS         = 8.0   # assez long pour isoler le pouls (≥ ~8 battements)
MOVE_SECONDS         = 5.0
HR_SECONDS           = 15.0  # calibration cardiaque dédiée : BPM de repos fiable
PPG_MIN_BPM          = 40
PPG_MAX_BPM          = 180
PPG_MIN_SCORE        = 1.0    # score mini de périodicité pour valider un PPG
# EMG faible amplitude : calibration par ALTERNANCE contracté/relâché.
# On détecte le port dont l'enveloppe d'activité OSCILLE au rythme
# demandé (mesure différentielle, robuste aux signaux faibles).
EMG_CYCLE_SECONDS    = 1.0    # fenêtre demi-cycle pour la détection / sim
EMG_SECONDS          = 30.0   # durée totale calib. EMG (consignes aléatoires)
EMG_MIN_SEG          = 1.0    # durée mini d'une consigne (s) : ≥ 1 s
EMG_MIN_CONTRACT     = 3      # nombre mini de phases CONTRACTÉ
EMG_MIN_RELEASE      = 3      # nombre mini de phases RELÂCHÉ
EMG_MIN_RATIO        = 2.0    # modulation ≥ 2× modulation repos pour valider
EMG_MIN_MOD          = 2.0    # modulation mini absolue (ADC) pour valider
EMG_MIN_SIGMA        = 3.0    # plancher σ live (highlight) — capteur faible
EMG_THRESHOLD_FRAC   = 0.35   # seuil d'activation entre repos et contraction
# Capteur EMG très faible : σ live mesurée sur une FENÊTRE RÉCENTE (pas tout
# le buffer, sinon contraction noyée → toujours « relâché »). L'excursion
# au-dessus du repos est AMPLIFIÉE (gain réglable sur la page zone morte).
EMG_GAIN             = 6.0    # gain d'amplification EMG par défaut
EMG_GAIN_MIN         = 1.0    # gain mini (pas d'amplification)
EMG_GAIN_MAX         = 20.0   # gain maxi (capteur très faible)
# EDA / activité électrodermale (GSR) : calibré EN DERNIER. C'est le port
# au signal CONTINU depuis le début (ni périodique comme le PPG, ni plat
# comme un axe immobile) → isolé par élimination + présence d'un signal.
EDA_SECONDS          = 10.0   # durée mesure du niveau EDA au repos
EDA_MIN_STD          = 0.5    # variation mini (ADC) prouvant un signal réel

# ─────────────────────────────────────────────
#  Palette  —  TETRIS MODERN
#  Matrice indigo profond, tuiles néon biseautées.
# ─────────────────────────────────────────────
BG_DEEP      = (  7,   8,  20)   # fond matrice (presque noir indigo)
BG_PANEL     = ( 15,  16,  34)   # puits / panneau
BG_PANEL_HI  = ( 26,  27,  54)   # surface surélevée / hover
GRID_DIM     = ( 22,  23,  46)   # lignes de matrice faibles
GRID_HI      = ( 42,  44,  84)   # lignes de matrice fortes
PHOSPHOR     = (  0, 238, 255)   # I — cyan, accent primaire
PHOSPHOR_MID = (  0, 230, 130)   # S — vert, succès / terminé
PHOSPHOR_DIM = ( 24,  70,  96)   # bord cyan atténué
AMBER        = (255, 178,  36)   # L — orange, enregistrement / actif
AMBER_DIM    = (104,  70,  16)
TEXT_HI      = (238, 241, 255)
TEXT_MID     = (152, 160, 205)
TEXT_DIM     = ( 99, 106, 154)
TEXT_FAINT   = ( 56,  60,  98)
DANGER       = (255,  58,  96)   # Z — rouge, pouls / erreur
DANGER_DIM   = (110,  22,  42)

# 7 couleurs de tétrominos. 6 premières = mapping des 6 ports BITalino.
TETRO = {
    "I": (  0, 238, 255), "O": (255, 209,  38), "T": (180,  86, 255),
    "S": (  0, 230, 130), "Z": (255,  58,  96), "J": ( 46, 122, 255),
    "L": (255, 148,  28),
}
PORT_COLORS = [TETRO["I"], TETRO["O"], TETRO["T"],
               TETRO["S"], TETRO["Z"], TETRO["J"]]

# Formes de tétrominos (offsets de cellules) — décor de fond.
TETRO_SHAPES = {
    "I": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(0, 0), (1, 0), (2, 0), (1, 1)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "Z": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "J": [(0, 0), (0, 1), (1, 1), (2, 1)],
    "L": [(2, 0), (0, 1), (1, 1), (2, 1)],
}


def _lighten(c, f):
    return tuple(min(255, int(v + (255 - v) * f)) for v in c[:3])


def _darken(c, f):
    return tuple(max(0, int(v * (1 - f))) for v in c[:3])
