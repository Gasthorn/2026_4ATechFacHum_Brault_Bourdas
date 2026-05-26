"""Détection automatique des ports : accéléromètre, PPG, EMG."""

import statistics

from .config import *  # noqa: F401,F403  (SAMPLING_HZ, seuils PPG/EMG)


# ─────────────────────────────────────────────
#  Détection automatique des ports
# ─────────────────────────────────────────────
def _accel_candidates(samples, exclude=()):
    """Ports plausibles pour un axe accéléromètre : moyenne dans 180..840 et
    σ faible (immobile = courbe plate). `exclude` retire le port PPG déjà
    identifié — le pouls ne doit jamais être pris pour un axe."""
    cands = []
    for i in range(6):
        if i in exclude:
            continue
        col = [s[i] for s in samples]
        m = statistics.mean(col)
        sd = statistics.pstdev(col) if len(col) > 1 else 0
        if 180 < m < 840 and sd < 20:
            cands.append(i)
    return cands or [i for i in range(6) if i not in exclude]


def _col_std(samples, idx):
    """Écart-type de la colonne `idx` d'une liste d'échantillons (tuples)."""
    if not samples:
        return 0.0
    col = [s[idx] for s in samples]
    return statistics.pstdev(col) if len(col) > 1 else 0.0


def _max_delta_std(rest, active, candidates):
    if not candidates:
        return None
    return max(candidates,
               key=lambda c: _col_std(active, c) - _col_std(rest, c))


def detect_x_axis(rest_samples, lr_samples, exclude=()):
    return _max_delta_std(rest_samples, lr_samples,
                          _accel_candidates(rest_samples, exclude))


def detect_y_axis(rest_samples, ud_samples, exclude=()):
    return _max_delta_std(rest_samples, ud_samples,
                          _accel_candidates(rest_samples, exclude))


def detect_z_axis(rest_samples, exclude=()):
    cands = _accel_candidates(rest_samples, exclude)
    if not cands:
        return None
    means = {c: statistics.mean(s[c] for s in rest_samples) for c in cands}
    return max(cands, key=lambda c: abs(means[c] - 512))


def detect_accel_axes(rest_samples, lr_samples, ud_samples, exclude=()):
    """Détection JOINTE des 3 axes accéléromètre (X / Y / Z).

    Les mouvements de calibration ne sont jamais purs : un balayage G/D
    réel sollicite un peu Y (épaule qui s'incline) et Z (rotation poignet),
    et inversement. La détection séquentielle « max σ par phase » peut donc
    confondre les axes quand l'utilisateur bouge en diagonale.

    Approche : pour chaque port plausible, on calcule la σ EN EXCÈS du
    repos sur les phases LR et UD. L'axe X est le port dont la composante
    LR domine NETTEMENT la composante UD (différence maximale), Y est le
    symétrique parmi les ports restants, Z est le port accéléro restant le
    plus excentré au repos (gravité). C'est le RATIO LR/UD qui décide ;
    un port qui répond un peu aux deux ne usurpe plus l'axe principal.
    """
    cands = _accel_candidates(rest_samples, exclude)
    if not cands:
        return None, None, None

    scores = {}
    for p in cands:
        sr = _col_std(rest_samples, p)
        sl = max(0.0, _col_std(lr_samples, p) - sr) if lr_samples else 0.0
        su = max(0.0, _col_std(ud_samples, p) - sr) if ud_samples else 0.0
        scores[p] = (sl, su)

    # X : maximise (LR − UD). Bouge ÉNORMÉMENT en LR et peu en UD.
    x = max(cands, key=lambda p: scores[p][0] - scores[p][1])
    rem = [p for p in cands if p != x]
    if not rem:
        return x, None, None

    # Y : maximise (UD − LR) parmi le reste.
    y = max(rem, key=lambda p: scores[p][1] - scores[p][0])
    rem2 = [p for p in rem if p != y]
    if not rem2:
        return x, y, None

    # Z : port accéléro restant à la moyenne la plus excentrée (gravité).
    means = {p: statistics.mean(s[p] for s in rest_samples) for p in rem2}
    z = max(rem2, key=lambda p: abs(means[p] - 512))
    return x, y, z


# ─────────────────────────────────────────────
#  Détection PPG / rythme cardiaque
# ─────────────────────────────────────────────
def _smooth(data, window=50):
    half = window // 2
    n = len(data)
    result = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        result.append(sum(data[lo:hi]) / (hi - lo))
    return result


def _estimate_bpm_and_score(col, frequency):
    """Peak-detection BPM from a raw PPG column. Returns (bpm, quality_score)."""
    if len(col) < frequency:
        return 0, 0.0
    smoothed = _smooth(col, window=max(10, frequency // 20))
    mean_v = statistics.mean(smoothed)
    std_v  = statistics.pstdev(smoothed) if len(smoothed) > 1 else 0
    if std_v < 5:
        return 0, 0.0
    threshold = mean_v + 0.35 * std_v
    min_gap = int(frequency * 60 / 180)   # fastest plausible: 180 BPM
    max_gap = int(frequency * 60 / 30)    # slowest plausible:  30 BPM
    peaks = []
    i = 1
    while i < len(smoothed) - 1:
        if (smoothed[i] >= threshold
                and smoothed[i] >= smoothed[i - 1]
                and smoothed[i] >= smoothed[i + 1]):
            if not peaks or (i - peaks[-1]) >= min_gap:
                peaks.append(i)
        i += 1
    if len(peaks) < 3:
        return 0, 0.0
    intervals = [peaks[k + 1] - peaks[k] for k in range(len(peaks) - 1)]
    valid = [iv for iv in intervals if min_gap <= iv <= max_gap]
    if len(valid) < 2:
        return 0, 0.0
    mean_iv = statistics.mean(valid)
    bpm = int(round(60 * frequency / mean_iv))
    cv = statistics.pstdev(valid) / mean_iv if mean_iv > 0 else 1
    score = len(valid) / (1 + cv * 8)
    return bpm, score


def detect_ppg_from_rest(rest_samples, frequency=SAMPLING_HZ):
    """Le capteur cardiaque (oreille) est branché dès le départ. Quand
    l'accéléromètre est tenu immobile, c'est le SEUL signal qui « bouge
    encore » : on cherche donc le port le plus périodique (meilleur score
    de détection de pic) parmi les 6. Retourne (port, bpm) ou (None, 0)."""
    best_port, best_bpm, best_score = None, 0, PPG_MIN_SCORE
    for port in range(6):
        col = [s[port] for s in rest_samples]
        bpm, score = _estimate_bpm_and_score(col, frequency)
        if score > best_score and PPG_MIN_BPM <= bpm <= PPG_MAX_BPM:
            best_score, best_port, best_bpm = score, port, bpm
    return best_port, best_bpm


def detect_ppg_port(hr_samples, exclude_ports, frequency=SAMPLING_HZ):
    """Repli pour la phase cardiaque dédiée : meilleur port PPG parmi les
    ports non-axes. Retourne (port, bpm) ou (None, 0)."""
    candidates = [i for i in range(6) if i not in exclude_ports]
    best_port, best_bpm, best_score = None, 0, PPG_MIN_SCORE
    for port in candidates:
        col = [s[port] for s in hr_samples]
        bpm, score = _estimate_bpm_and_score(col, frequency)
        if score > best_score and PPG_MIN_BPM <= bpm <= PPG_MAX_BPM:
            best_score, best_port, best_bpm = score, port, bpm
    return best_port, best_bpm


# ─────────────────────────────────────────────
#  Détection EMG / contraction musculaire
# ─────────────────────────────────────────────
def _emg_envelope(samples, port, win):
    """Enveloppe d'activité : σ du port `port` par fenêtre de `win`
    échantillons (un demi-cycle contracté/relâché)."""
    col = [s[port] for s in samples]
    return [statistics.pstdev(col[k:k + win]) if win > 1 else 0.0
            for k in range(0, len(col) - win + 1, win)]


def detect_emg_port(rest_samples, flex_samples, exclude_ports,
                     frequency=SAMPLING_HZ, gain=EMG_GAIN):
    """Capteur EMG à FAIBLE amplitude : exiger une grosse σ absolue échoue
    si le signal est faible. À la place l'utilisateur ALTERNE ~1 s
    contracté / ~1 s relâché ; le port EMG est celui dont l'enveloppe
    d'activité (σ par demi-cycle) OSCILLE le plus à ce rythme — mesure
    différentielle, robuste aux niveaux faibles, hors port PPG.

    Capteur souvent MAL DÉTECTÉ car la modulation reste sous le plancher
    absolu `EMG_MIN_MOD`. On AMPLIFIE la modulation (×`gain`) AU MOMENT DE
    LA DÉTECTION : le port faible franchit alors le plancher. Le ratio
    repos reste invariant (numérateur et dénominateur amplifiés).

    Retourne (port, sigma_repos, sigma_pic) BRUTS (le gain ne sert qu'à
    la décision) ; port = None si aucune modulation franche détectée."""
    candidates = [i for i in range(6) if i not in exclude_ports]
    if not candidates or not flex_samples:
        return None, 0.0, 0.0

    win = max(1, int(EMG_CYCLE_SECONDS * frequency / 2))  # demi-cycle

    # Choisir par RATIO flex_mod / rest_mod (gain-invariant) plutôt que par
    # mod absolu : un capteur EDA dérive lentement → mod absolu peut dominer
    # un EMG faible alors que rest_mod ≈ flex_mod (ratio≈1). EMG vrai :
    # rest_mod faible (relâché), flex_mod fort (bursts) → ratio >> 1.
    best_port, best_ratio, best_mod = None, 0.0, 0.0
    rsd = fsd = 0.0
    for port in candidates:
        env = _emg_envelope(flex_samples, port, win)
        if len(env) < 2:
            continue
        mod = statistics.pstdev(env) * gain
        rest_env = _emg_envelope(rest_samples, port, win)
        rest_mod = (statistics.pstdev(rest_env) * gain
                    if len(rest_env) > 1 else 0.0)
        ratio = mod / rest_mod if rest_mod > 1e-6 else (mod * 1e6)
        if ratio > best_ratio and mod >= EMG_MIN_MOD:
            best_ratio, best_mod, best_port = ratio, mod, port
            rsd = _col_std(rest_samples, port)
            fsd = max(env)
    if best_port is None:
        return None, 0.0, 0.0
    if best_ratio < EMG_MIN_RATIO:
        return None, rsd, fsd
    return best_port, rsd, fsd


# ─────────────────────────────────────────────
#  Détection EDA / activité électrodermale (GSR)
# ─────────────────────────────────────────────
def detect_eda_port(eda_samples, exclude_ports):
    """Capteur EDA calibré EN DERNIER : PPG + 3 axes + EMG déjà connus et
    exclus → l'EDA est le port restant qui porte un SIGNAL CONTINU depuis
    le début (présent, non « débranché/plat à zéro »).

    Choisit, parmi les ports non exclus, celui dont la colonne a la plus
    forte variation tout en restant dans une plage ADC plausible (signal
    réel continu). Repli : s'il ne reste qu'un seul candidat, on l'accepte
    même très plat (un EDA tonique peut être quasi constant au repos).
    Retourne le port (index 0-5) ou None."""
    cands = [i for i in range(6) if i not in exclude_ports]
    if not cands or not eda_samples:
        return None
    best_port, best_std = None, EDA_MIN_STD
    for c in cands:
        col = [s[c] for s in eda_samples]
        m = statistics.mean(col)
        sd = statistics.pstdev(col) if len(col) > 1 else 0.0
        if 30 < m < 1000 and sd >= best_std:
            best_std, best_port = sd, c
    if best_port is None and len(cands) == 1:
        c = cands[0]
        if 30 < statistics.mean(s[c] for s in eda_samples) < 1000:
            best_port = c
    return best_port
