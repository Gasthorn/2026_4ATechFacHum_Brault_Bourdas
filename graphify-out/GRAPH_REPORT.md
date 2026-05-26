# Graph Report - TeTrino  (2026-05-26)

## Corpus Check
- 51 files · ~41,175 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 769 nodes · 1327 edges · 85 communities (61 shown, 24 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 74 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1e07620b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]

## God Nodes (most connected - your core abstractions)
1. `App` - 80 edges
2. `TetrisGame` - 32 edges
3. `draw_block()` - 29 edges
4. `draw_text()` - 27 edges
5. `BioState` - 24 edges
6. `BitalinoInputHandler` - 23 edges
7. `KeyboardInputHandler` - 20 edges
8. `_darken()` - 20 edges
9. `SimulatedDevice` - 20 edges
10. `Grid` - 16 edges

## Surprising Connections (you probably didn't know these)
- `BioState (live biosignal state)` --semantically_similar_to--> `_estimate_bpm_and_score`  [INFERRED] [semantically similar]
  runtime.py → calibrage/detection.py
- `DOCUMENTATION.txt (French API docs)` --references--> `TetrisGame (pygame loop)`  [EXTRACTED]
  DOCUMENTATION.txt → tetris.py
- `CalibrationDevice (PLUX wrapper)` --semantically_similar_to--> `NewDevice (PLUX SignalsDev wrapper)`  [INFERRED] [semantically similar]
  calibrage/device.py → Bitalino.py
- `OneBITalinoAcquisitionExample` --semantically_similar_to--> `NewDevice (PLUX SignalsDev wrapper)`  [INFERRED] [semantically similar]
  OneBITalinoAcquisitionExample.py → Bitalino.py
- `CLAUDE.md project memory` --cites--> `EMG detection by modulation ratio (gain-invariant)`  [EXTRACTED]
  CLAUDE.md → calibrage/detection.py

## Hyperedges (group relationships)
- **Sensor acquisition â†’ state â†’ game pipeline** — calibrage_device_CalibrationDevice, runtime_BioState, runtime_BioSpeedModulator, tetris_TetrisGame [INFERRED 0.90]
- **Sequential port elimination (PPGâ†’Accelâ†’EMGâ†’EDA)** — calibrage_detection_detect_ppg_from_rest, calibrage_detection_detect_accel_axes, calibrage_detection_detect_emg_port, calibrage_detection_detect_eda_port [INFERRED 0.95]
- **Shared CRT visual toolkit (calibrage UI reused by tetris)** — calibrage_ui_Theme, calibrage_ui_draw_block, calibrage_ui_draw_radar, calibrage_ui_draw_gauge, tetris_TetrisGame [INFERRED 0.85]

## Communities (85 total, 24 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.14
Nodes (15): Liste de lignes de journal : la plus récente en cyan., Liste de lignes de journal : la plus récente en cyan., draw_panel(), draw_text(), draw_text_centered(), Puits sombre : liseré, barre d'accent supérieure, coins encochés., draw_plots_panel(), draw_port_plot() (+7 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (19): CalibrationDevice, Couche périphérique BITalino : carte réelle (PLUX) + simulateur., SimulatedDevice, str, base_drop_interval(), _connect_device(), Grid, Piece (+11 more)

### Community 2 - "Community 2"
Cohesion: 0.19
Nodes (16): _accel_candidates(), _col_std(), detect_accel_axes(), detect_ppg_port(), detect_x_axis(), detect_y_axis(), detect_z_axis(), _estimate_bpm_and_score() (+8 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (17): draw_cell(), drop_interval(), Grid, InputHandler, main(), Piece, Tetris - Projet BITalino ======================== Jeu Tetris fonctionnel en Py, Centralise tous les contrôles du jeu.     Pour intégrer BITalino : remplacez / (+9 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (17): draw_cell(), drop_interval(), Grid, InputHandler, main(), Piece, Tetris - Projet BITalino ======================== Jeu Tetris fonctionnel en Py, Centralise tous les contrôles du jeu.     Pour intégrer BITalino : remplacez / (+9 more)

### Community 5 - "Community 5"
Cohesion: 0.16
Nodes (8): int, BioState, _bpm_from(), Runtime BITalino pour Tetris : lecture live, modulation vitesse, contrôles.  - `, Renvoie les ``n`` derniers échantillons plein débit du ``port``., Fréquence effective du live_buf (décimé 1:8 vs acquisition)., Lecture continue des 6 ports BITalino → métriques jeu.      Tourne dans un threa, Lecture continue des 6 ports BITalino → métriques jeu.      Tourne dans un threa

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (6): Font, _PG, Vérification headless du package calibrage/ (pas de pygame/BITalino requis)., Rect, SignalsDev, Surface

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (12): Stoppe/efface tout enregistrement en cours (avant un saut d'état)., Stoppe/efface tout enregistrement en cours (avant un saut d'état)., Recalibre UN capteur, garde les autres (compat interne + selfcheck)., Recalibre UN capteur, garde les autres (compat interne + selfcheck)., Lance le recalibrage pour un ensemble de capteurs (multi-selection).         Con, Lance le recalibrage pour un ensemble de capteurs (multi-selection).         Con, Demarre le prochain capteur dans la file. File vide -> ZONE MORTE., Demarre le prochain capteur dans la file. File vide -> ZONE MORTE. (+4 more)

### Community 8 - "Community 8"
Cohesion: 0.27
Nodes (9): Accelerometer anti-rebound (neutral pass), Full-rate 1ms polling for EMG/accel responsiveness, BioSpeedModulator (HR+EDA â†’ speed), BioState (live biosignal state), BitalinoInputHandler (sensor controls + anti-rebound), KeyboardInputHandler, tetris.main launcher, _menu screen helper (+1 more)

### Community 9 - "Community 9"
Cohesion: 0.29
Nodes (6): address, dead_zone, eda, port, rest, frequency

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (7): Fait défiler AUTO → P1..P6 → AUTO pour un capteur., Fait défiler AUTO → P1..P6 → AUTO pour un capteur., Recalcule le seuil EMG depuis le curseur (zone morte EMG)., Fréquence d'acquisition des échantillons enregistrés (non décimés)., True (+ log/bouton RÉESSAYER) si l'enregistrement est vide., Valeur ADC moyenne d'un axe sur les échantillons de repos.         Axe sauté / p, Valeur ADC moyenne d'un axe sur les échantillons de repos.         Axe sauté / p

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (24): BioSpeedModulator, Button, make_grid(), make_scanlines(), make_vignette(), Halo cyan (fond lumineux) : grand bloom haut + léger bas, dégradé     doux. Plus, Assombrissement de bord TRÈS progressif : bande douce ≈ 46 % de la     plus peti, Polices proportionnelles à la fenêtre.     DISPLAY = sans condensé géométrique ( (+16 more)

### Community 12 - "Community 12"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 13 - "Community 13"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 14 - "Community 14"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 15 - "Community 15"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 16 - "Community 16"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 17 - "Community 17"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 18 - "Community 18"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 19 - "Community 19"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 20 - "Community 20"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 21 - "Community 21"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 22 - "Community 22"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 23 - "Community 23"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 24 - "Community 24"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 25 - "Community 25"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 26 - "Community 26"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 27 - "Community 27"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 28 - "Community 28"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 29 - "Community 29"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 30 - "Community 30"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 31 - "Community 31"
Cohesion: 0.25
Nodes (8): mapping, down, emg_active, invert_x, invert_y, left, right, up

### Community 32 - "Community 32"
Cohesion: 0.40
Nodes (5): range, x_max, x_min, y_max, y_min

### Community 33 - "Community 33"
Cohesion: 0.50
Nodes (4): rest, x, y, z

### Community 47 - "Community 47"
Cohesion: 0.17
Nodes (8): En-tête de panneau commun : tuile badge + titre néon + sous-titres.         Renv, En-tête de panneau commun : tuile badge + titre néon + sous-titres.         Renv, Squelette commun aux écrans capteur (CŒUR / EMG) :         en-tête → indicateur, Squelette commun aux écrans capteur (CŒUR / EMG) :         en-tête → indicateur, Stepper compact ◀ AUTO/Px ▶ pour CORRIGER le port du capteur de         l'étape, Stepper compact ◀ AUTO/Px ▶ pour CORRIGER le port du capteur de         l'étape, draw_scope(), Oscilloscope sur matrice Tetris : signaux en couleurs de pièces,     lueur sur l

### Community 48 - "Community 48"
Cohesion: 0.15
Nodes (5): bool, KeyboardInputHandler, Retourne True UNE SEULE FOIS par contraction EMG soutenue         ≥ ``EMG_HOLD_S, Contrôles clavier classiques. Identique au handler historique., Contrôles clavier classiques. EMG (si ``bio`` fourni) déclenche AUSSI     la rot

### Community 49 - "Community 49"
Cohesion: 0.18
Nodes (6): BitalinoInputHandler, Contrôles BITalino : accéléromètre G/D + H/B, EMG → rotation.      Anti-rebond :, Contrôles BITalino : accéléromètre G/D = mouvement, axe Y (haut OU     bas) = so, Met à jour le latch "repos confirmé" pour un axe (X ou Y).         Doit avoir pa, Met à jour le latch "repos confirmé" pour un axe (X ou Y).         Doit avoir pa, Front montant tilt-up + anti-rebond settle + cooldown 500 ms.         Filtre l'o

### Community 50 - "Community 50"
Cohesion: 0.19
Nodes (6): App, main(), Niveau EDA live = moyenne du buffer du port EDA (signal lent,         continu →, Tétrominos fantômes qui descendent lentement — ambiance matrice., Tétrominos fantômes qui descendent lentement — ambiance matrice., Point d'entrée — délègue au package calibrage/ (voir calibrage/__init__.py).

### Community 51 - "Community 51"
Cohesion: 0.14
Nodes (18): Éditeur des correspondances ports : par ligne, pastille capteur         + libell, Éditeur des correspondances ports : par ligne, pastille capteur         + libell, Overlay modal : cases a cocher pour choisir les capteurs a         recalibrer. B, Overlay modal : cases a cocher pour choisir les capteurs a         recalibrer. B, _darken(), _lighten(), Constantes, configuration PLUX et palette graphique., draw_block() (+10 more)

### Community 52 - "Community 52"
Cohesion: 0.29
Nodes (4): BPM live calculé sur le buffer du port PPG (recalcul ~1 Hz)., Fréquence effective du live_buf (décimé 1/8 vs acquisition)., BPM live calculé sur le buffer du port PPG (recalcul ~1 Hz)., Fréquence effective du live_buf (décimé 1/8 vs acquisition).

### Community 53 - "Community 53"
Cohesion: 0.22
Nodes (6): Port effectif d'un capteur : override manuel sinon AUTO., Pousse le port effectif (override/AUTO) vers l'attribut associé., Ré-impose les overrides manuels APRÈS l'auto-détection : une         détection (, Port effectif d'un capteur : override manuel sinon AUTO., Pousse le port effectif (override/AUTO) vers l'attribut associé., Ré-impose les overrides manuels APRÈS l'auto-détection : une         détection (

### Community 54 - "Community 54"
Cohesion: 0.17
Nodes (10): Architecture, code:bash (# MAIN entry — launcher : détection BITalino → menu Calibrer), Dependencies, Gotchas, graphify, Key Files, Language, Project (+2 more)

### Community 56 - "Community 56"
Cohesion: 0.25
Nodes (5): _emg_gain_to_slider(), Gain EMG → position curseur 0..1 (inverse de _slider_to_emg_gain)., Remet à zéro échantillons, ports et seuils détectés.         Partagé par __init_, Remet à zéro échantillons, ports et seuils détectés.         Partagé par __init_, ``preconnected=(device, acq_thread)`` saute la phase DETECT         (utile quand

### Community 57 - "Community 57"
Cohesion: 0.13
Nodes (10): Écart-type d'un buffer (amplitude EMG instantanée)., Gain d'amplification EMG courant (curseur AMPLI de la page)., σ EMG live sur une FENÊTRE RÉCENTE, EXCURSION amplifiée.          Capteur très f, Écart-type d'un buffer (amplitude EMG instantanée)., Gain d'amplification EMG courant (curseur AMPLI de la page)., σ EMG live sur une FENÊTRE RÉCENTE, EXCURSION amplifiée.          Capteur très f, Recalcule le seuil EMG depuis le curseur (zone morte EMG)., Consigne EMG courante pendant l'enregistrement : (label, reste_s).         Retou (+2 more)

### Community 58 - "Community 58"
Cohesion: 0.29
Nodes (7): emg, dead_zone, gain, port, sigma_flex, sigma_rest, threshold

### Community 59 - "Community 59"
Cohesion: 0.29
Nodes (7): ports_override, eda, emg, ppg, x, y, z

### Community 60 - "Community 60"
Cohesion: 0.33
Nodes (4): En-tête commun des panneaux (PORTS / RECAL) : barre accent + titre         + sou, En-tête commun des panneaux (PORTS / RECAL) : barre accent + titre         + sou, Sélecteur de recalibrage ciblé : 3 tuiles accent (titre + ce qui         est ref, Sélecteur de recalibrage ciblé : 3 tuiles accent (titre + ce qui         est ref

### Community 61 - "Community 61"
Cohesion: 0.33
Nodes (5): 01:04 | gab, 01:15-01:41 | gab, 02:02 | gab, 02:12 | gab, 11:54 | gab

### Community 62 - "Community 62"
Cohesion: 0.40
Nodes (5): skipped, accel, eda, emg, ppg

### Community 63 - "Community 63"
Cohesion: 0.50
Nodes (3): 19:43 | gab, 20:23 | gab, 20:52 | gab

### Community 64 - "Community 64"
Cohesion: 0.50
Nodes (4): ports, x, y, z

### Community 67 - "Community 67"
Cohesion: 0.67
Nodes (3): invert, x, y

### Community 68 - "Community 68"
Cohesion: 0.67
Nodes (3): ppg, bpm_rest, port

### Community 77 - "Community 77"
Cohesion: 0.24
Nodes (11): calibrage.App (state machine), CALIB_STEPS canonical order, detect_eda_port(), detect_ppg_from_rest(), _estimate_bpm_and_score, Le capteur cardiaque (oreille) est branché dès le départ. Quand     l'accéléromè, Capteur EDA calibré EN DERNIER : PPG + 3 axes + EMG déjà connus et     exclus →, calibrage.py entry shim (+3 more)

### Community 78 - "Community 78"
Cohesion: 0.25
Nodes (9): OneBITalinoAcquisitionExample, NewDevice (PLUX SignalsDev wrapper), exampleAcquisition (matplotlib live), PLUX_AVAILABLE flag, CalibrationDevice (PLUX wrapper), SimulatedDevice (demo synth), _connect_device (real or sim), draw_plots_panel (6 port plots) (+1 more)

### Community 79 - "Community 79"
Cohesion: 0.22
Nodes (9): Theme (proportional fonts), DOCUMENTATION.txt (French API docs), Inexorable time-based speed ramp, tetris_selfcheck, GameLayout responsive, Grid (10x20 board), Piece (tetromino), TetrisGame (pygame loop) (+1 more)

### Community 80 - "Community 80"
Cohesion: 0.25
Nodes (6): float, BioSpeedModulator, Convertit l'écart BPM/EDA par rapport au repos en un facteur de vitesse.      St, Convertit l'écart BPM/EDA par rapport au repos en un facteur de vitesse.      St, Niveau de stress lissé (0 = repos / calme, 1 = stress max).         Combinaison, Niveau de stress lissé (0 = repos / calme, 1 = stress max).         Combinaison

### Community 81 - "Community 81"
Cohesion: 0.29
Nodes (5): _fit_text(), _normalize(), _port_label(), Application de calibrage : machine d'état et boucle principale., Calibrage BITalino — Interface CRT responsive (package).  Ordre de calibration :

### Community 82 - "Community 82"
Cohesion: 0.33
Nodes (6): detect_emg_port(), _emg_envelope(), Enveloppe d'activité : σ du port `port` par fenêtre de `win`     échantillons (u, Capteur EMG à FAIBLE amplitude : exiger une grosse σ absolue échoue     si le si, EMG weak-signal amplification rationale, EMG detection by modulation ratio (gain-invariant)

### Community 83 - "Community 83"
Cohesion: 0.50
Nodes (3): GameLayout, Layout responsive : recalcule positions/tailles selon ``screen``.      Conventio, Layout responsive : recalcule positions/tailles selon ``screen``.      Conventio

## Knowledge Gaps
- **87 isolated node(s):** `address`, `frequency`, `x`, `y`, `z` (+82 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `str` connect `Community 1` to `Community 3`, `Community 4`, `Community 6`, `Community 10`, `Community 49`?**
  _High betweenness centrality (0.218) - this node is a cross-community bridge._
- **Why does `App` connect `Community 50` to `Community 0`, `Community 65`, `Community 1`, `Community 7`, `Community 10`, `Community 11`, `Community 47`, `Community 81`, `Community 51`, `Community 52`, `Community 53`, `Community 84`, `Community 83`, `Community 56`, `Community 57`, `Community 60`?**
  _High betweenness centrality (0.198) - this node is a cross-community bridge._
- **Why does `TetrisGame (pygame loop)` connect `Community 79` to `Community 8`, `Community 9`, `Community 51`, `Community 78`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `App` (e.g. with `int` and `Piece`) actually correct?**
  _`App` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TetrisGame` (e.g. with `App` and `SimulatedDevice`) actually correct?**
  _`TetrisGame` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `BioState` (e.g. with `int` and `Piece`) actually correct?**
  _`BioState` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Example acquisition. Runs indefinitely and plots the 6 ports until window is clo`, `Point d'entrée — délègue au package calibrage/ (voir calibrage/__init__.py).`, `address` to the rest of the system?**
  _260 weakly-connected nodes found - possible documentation gaps or missing edges._