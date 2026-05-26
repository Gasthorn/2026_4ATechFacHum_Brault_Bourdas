# Graph Report - .  (2026-05-26)

## Corpus Check
- Corpus is ~38,139 words - fits in a single context window. You may not need a graph.

## Summary
- 641 nodes · 1178 edges · 47 communities (35 shown, 12 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 67 edges (avg confidence: 0.56)
- Token cost: 78,000 input · 7,429 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Calibration App  State Machine|Calibration App / State Machine]]
- [[_COMMUNITY_BITalino Device Layer|BITalino Device Layer]]
- [[_COMMUNITY_Calibration Recording Flow|Calibration Recording Flow]]
- [[_COMMUNITY_Tetris Engine (GridPiece)|Tetris Engine (Grid/Piece)]]
- [[_COMMUNITY_Tetris Engine (variant)|Tetris Engine (variant)]]
- [[_COMMUNITY_Runtime BioState + Modulator|Runtime BioState + Modulator]]
- [[_COMMUNITY_Pygame Test Stubs|Pygame Test Stubs]]
- [[_COMMUNITY_Calibration Helpers|Calibration Helpers]]
- [[_COMMUNITY_Project Documentation|Project Documentation]]
- [[_COMMUNITY_calibration.json Schema|calibration.json Schema]]
- [[_COMMUNITY_Tetris Game Layout|Tetris Game Layout]]
- [[_COMMUNITY_Live Acquisition + Sim Devices|Live Acquisition + Sim Devices]]
- [[_COMMUNITY_MultiThread Acquisition Example|MultiThread Acquisition Example]]
- [[_COMMUNITY_MultiThread Example (clone)|MultiThread Example (clone)]]
- [[_COMMUNITY_MultiThread Example (clone)|MultiThread Example (clone)]]
- [[_COMMUNITY_OneDevice Acquisition Example|OneDevice Acquisition Example]]
- [[_COMMUNITY_OneDevice Acquisition (clone)|OneDevice Acquisition (clone)]]
- [[_COMMUNITY_OneDevice Acquisition (clone)|OneDevice Acquisition (clone)]]
- [[_COMMUNITY_OneBITalino Acquisition Example|OneBITalino Acquisition Example]]
- [[_COMMUNITY_OneBITalino Acquisition (clone)|OneBITalino Acquisition (clone)]]
- [[_COMMUNITY_Download Acquisition Example|Download Acquisition Example]]
- [[_COMMUNITY_Special Channels Example|Special Channels Example]]
- [[_COMMUNITY_Schedule Acquisition Example|Schedule Acquisition Example]]
- [[_COMMUNITY_Download Acquisition (clone)|Download Acquisition (clone)]]
- [[_COMMUNITY_Special Channels (clone)|Special Channels (clone)]]
- [[_COMMUNITY_Schedule Acquisition (clone)|Schedule Acquisition (clone)]]
- [[_COMMUNITY_Download Acquisition (clone 2)|Download Acquisition (clone 2)]]
- [[_COMMUNITY_Special Channels (clone 2)|Special Channels (clone 2)]]
- [[_COMMUNITY_Schedule Acquisition (clone 2)|Schedule Acquisition (clone 2)]]
- [[_COMMUNITY_Bitalino.py Example|Bitalino.py Example]]
- [[_COMMUNITY_OneBITalino Example (clone 2)|OneBITalino Example (clone 2)]]
- [[_COMMUNITY_Game Input Mapping (LRUD)|Game Input Mapping (L/R/U/D)]]
- [[_COMMUNITY_Accel Range Bounds|Accel Range Bounds]]
- [[_COMMUNITY_Accel Rest Baseline|Accel Rest Baseline]]
- [[_COMMUNITY_Calibration UI Layout|Calibration UI Layout]]
- [[_COMMUNITY_Settings Permissions|Settings Permissions]]
- [[_COMMUNITY_Settings Permissions (clone)|Settings Permissions (clone)]]
- [[_COMMUNITY_Settings Permissions (clone 2)|Settings Permissions (clone 2)]]
- [[_COMMUNITY_Session State|Session State]]
- [[_COMMUNITY_VSCode Python Env|VSCode Python Env]]
- [[_COMMUNITY_VSCode Python Env (clone)|VSCode Python Env (clone)]]
- [[_COMMUNITY_VSCode Python Env (clone 2)|VSCode Python Env (clone 2)]]
- [[_COMMUNITY_BPM Estimation Rationale|BPM Estimation Rationale]]
- [[_COMMUNITY_Port Label Rationale|Port Label Rationale]]
- [[_COMMUNITY_Text Truncation Helper|Text Truncation Helper]]
- [[_COMMUNITY_CRT Palette Rationale|CRT Palette Rationale]]

## God Nodes (most connected - your core abstractions)
1. `App` - 80 edges
2. `draw_block()` - 29 edges
3. `TetrisGame` - 28 edges
4. `draw_text()` - 25 edges
5. `BioState` - 21 edges
6. `BitalinoInputHandler` - 20 edges
7. `_darken()` - 20 edges
8. `SimulatedDevice` - 20 edges
9. `KeyboardInputHandler` - 19 edges
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
- `int` --uses--> `BioState`  [INFERRED]
  tetris.py → runtime.py

## Hyperedges (group relationships)
- **Sensor acquisition â†’ state â†’ game pipeline** — calibrage_device_CalibrationDevice, runtime_BioState, runtime_BioSpeedModulator, tetris_TetrisGame [INFERRED 0.90]
- **Sequential port elimination (PPGâ†’Accelâ†’EMGâ†’EDA)** — calibrage_detection_detect_ppg_from_rest, calibrage_detection_detect_accel_axes, calibrage_detection_detect_emg_port, calibrage_detection_detect_eda_port [INFERRED 0.95]
- **Shared CRT visual toolkit (calibrage UI reused by tetris)** — calibrage_ui_Theme, calibrage_ui_draw_block, calibrage_ui_draw_radar, calibrage_ui_draw_gauge, tetris_TetrisGame [INFERRED 0.85]

## Communities (47 total, 12 thin omitted)

### Community 0 - "Calibration App / State Machine"
Cohesion: 0.05
Nodes (44): App, Liste de lignes de journal : la plus récente en cyan., En-tête de panneau commun : tuile badge + titre néon + sous-titres.         Renv, Squelette commun aux écrans capteur (CŒUR / EMG) :         en-tête → indicateur, BPM live calculé sur le buffer du port PPG (recalcul ~1 Hz)., Fréquence effective du live_buf (décimé 1/8 vs acquisition)., Écart-type d'un buffer (amplitude EMG instantanée)., Gain d'amplification EMG courant (curseur AMPLI de la page). (+36 more)

### Community 1 - "BITalino Device Layer"
Cohesion: 0.05
Nodes (44): BioSpeedModulator, ``preconnected=(device, acq_thread)`` saute la phase DETECT         (utile quand, CalibrationDevice, Couche périphérique BITalino : carte réelle (PLUX) + simulateur., SimulatedDevice, Button, make_grid(), make_scanlines() (+36 more)

### Community 2 - "Calibration Recording Flow"
Cohesion: 0.07
Nodes (41): calibrage.App (state machine), CALIB_STEPS canonical order, _fit_text(), main(), _normalize(), _port_label(), Application de calibrage : machine d'état et boucle principale., Fréquence d'acquisition des échantillons enregistrés (non décimés). (+33 more)

### Community 3 - "Tetris Engine (Grid/Piece)"
Cohesion: 0.08
Nodes (17): draw_cell(), drop_interval(), Grid, InputHandler, main(), Piece, Tetris - Projet BITalino ======================== Jeu Tetris fonctionnel en Py, Centralise tous les contrôles du jeu.     Pour intégrer BITalino : remplacez / (+9 more)

### Community 4 - "Tetris Engine (variant)"
Cohesion: 0.08
Nodes (17): draw_cell(), drop_interval(), Grid, InputHandler, main(), Piece, Tetris - Projet BITalino ======================== Jeu Tetris fonctionnel en Py, Centralise tous les contrôles du jeu.     Pour intégrer BITalino : remplacez / (+9 more)

### Community 5 - "Runtime BioState + Modulator"
Cohesion: 0.07
Nodes (13): float, bool, int, BioState, BitalinoInputHandler, _bpm_from(), KeyboardInputHandler, Runtime BITalino pour Tetris : lecture live, modulation vitesse, contrôles.  - ` (+5 more)

### Community 6 - "Pygame Test Stubs"
Cohesion: 0.06
Nodes (6): Font, _PG, Vérification headless du package calibrage/ (pas de pygame/BITalino requis)., Rect, SignalsDev, Surface

### Community 7 - "Calibration Helpers"
Cohesion: 0.09
Nodes (13): _emg_gain_to_slider(), Fait défiler AUTO → P1..P6 → AUTO pour un capteur., Recalcule le seuil EMG depuis le curseur (zone morte EMG)., Tire un plan de consignes aléatoire pour la calibration EMG.          Alternance, True (+ log/bouton RÉESSAYER) si l'enregistrement est vide., Gain EMG → position curseur 0..1 (inverse de _slider_to_emg_gain)., Remet à zéro échantillons, ports et seuils détectés.         Partagé par __init_, Stoppe/efface tout enregistrement en cours (avant un saut d'état). (+5 more)

### Community 8 - "Project Documentation"
Cohesion: 0.21
Nodes (11): _estimate_bpm_and_score, Accelerometer anti-rebound (neutral pass), EMG weak-signal amplification rationale, Full-rate 1ms polling for EMG/accel responsiveness, BioSpeedModulator (HR+EDA â†’ speed), BioState (live biosignal state), BitalinoInputHandler (sensor controls + anti-rebound), KeyboardInputHandler (+3 more)

### Community 9 - "calibration.json Schema"
Cohesion: 0.18
Nodes (10): address, dead_zone, frequency, ports, x, y, z, ppg (+2 more)

### Community 10 - "Tetris Game Layout"
Cohesion: 0.22
Nodes (9): Theme (proportional fonts), DOCUMENTATION.txt (French API docs), Inexorable time-based speed ramp, tetris_selfcheck, GameLayout responsive, Grid (10x20 board), Piece (tetromino), TetrisGame (pygame loop) (+1 more)

### Community 11 - "Live Acquisition + Sim Devices"
Cohesion: 0.25
Nodes (9): OneBITalinoAcquisitionExample, NewDevice (PLUX SignalsDev wrapper), exampleAcquisition (matplotlib live), PLUX_AVAILABLE flag, CalibrationDevice (PLUX wrapper), SimulatedDevice (demo synth), _connect_device (real or sim), draw_plots_panel (6 port plots) (+1 more)

### Community 12 - "MultiThread Acquisition Example"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 13 - "MultiThread Example (clone)"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 14 - "MultiThread Example (clone)"
Cohesion: 0.29
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 15 - "OneDevice Acquisition Example"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 16 - "OneDevice Acquisition (clone)"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 17 - "OneDevice Acquisition (clone)"
Cohesion: 0.38
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition.      Supported channel number codes:     {1 channel - 0x

### Community 18 - "OneBITalino Acquisition Example"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 19 - "OneBITalino Acquisition (clone)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 20 - "Download Acquisition Example"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 21 - "Special Channels Example"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 22 - "Schedule Acquisition Example"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 23 - "Download Acquisition (clone)"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 24 - "Special Channels (clone)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 25 - "Schedule Acquisition (clone)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 26 - "Download Acquisition (clone 2)"
Cohesion: 0.40
Nodes (3): exampleDownloadAcquisition(), NewDevice, Example of the actions needed to download a data recording that was stored in th

### Community 27 - "Special Channels (clone 2)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition using the plux.Source object to initialize specific channels

### Community 28 - "Schedule Acquisition (clone 2)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example of scheduling a future acquisition to be stored in the memory card.

### Community 29 - "Bitalino.py Example"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 30 - "OneBITalino Example (clone 2)"
Cohesion: 0.40
Nodes (3): exampleAcquisition(), NewDevice, Example acquisition. Runs indefinitely and plots the 6 ports until window is clo

### Community 31 - "Game Input Mapping (L/R/U/D)"
Cohesion: 0.40
Nodes (5): mapping, down, left, right, up

### Community 32 - "Accel Range Bounds"
Cohesion: 0.40
Nodes (5): range, x_max, x_min, y_max, y_min

### Community 33 - "Accel Rest Baseline"
Cohesion: 0.50
Nodes (4): rest, x, y, z

## Knowledge Gaps
- **40 isolated node(s):** `address`, `frequency`, `x`, `y`, `z` (+35 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `App` connect `Calibration App / State Machine` to `BITalino Device Layer`, `Calibration Recording Flow`, `Calibration Helpers`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Why does `TetrisGame (pygame loop)` connect `Tetris Game Layout` to `Project Documentation`, `Calibration App / State Machine`, `Live Acquisition + Sim Devices`, `calibration.json Schema`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `draw_gauge()` connect `Calibration App / State Machine` to `BITalino Device Layer`, `Tetris Game Layout`, `Runtime BioState + Modulator`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `App` (e.g. with `int` and `Piece`) actually correct?**
  _`App` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TetrisGame` (e.g. with `App` and `SimulatedDevice`) actually correct?**
  _`TetrisGame` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `BioState` (e.g. with `int` and `Piece`) actually correct?**
  _`BioState` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Example acquisition. Runs indefinitely and plots the 6 ports until window is clo`, `Point d'entrée — délègue au package calibrage/ (voir calibrage/__init__.py).`, `address` to the rest of the system?**
  _161 weakly-connected nodes found - possible documentation gaps or missing edges._