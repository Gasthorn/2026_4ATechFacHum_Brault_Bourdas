# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

TeTrino — Tetris game controlled by BITalino biosensors (accelerometer/EMG) via Bluetooth. Uses PLUX-API for hardware communication.

## Running the Project

```bash
# MAIN entry — launcher : détection BITalino → menu Calibrer/Jouer → menu Clavier/Capteurs → jeu
python tetris.py                       # carte BITalino, fallback démo si absent (boutons RÉESSAYER/DÉMO)
python tetris.py --demo                # simulateur direct
python tetris.py BTH98:D3:51:FE:87:0E  # adresse explicite

# Calibration standalone (sans lancer le jeu derrière)
python calibrage.py [--demo] [BTH...]

# Live BITalino signal acquisition + plots
python OneBITalinoAcquisitionExample.py

# Headless verification (no pygame/hardware) — BOTH must stay "ALL GREEN" after edits
python tools/calibrage_selfcheck.py
python tools/tetris_selfcheck.py
```

**This environment has no `pygame` (cannot pip-build it) — `python calibrage.py` will not run here.** Validate logic/rendering headless instead.

## Testing without hardware/pygame

- One-liner after every edit: `python -m py_compile tetris.py runtime.py calibrage/*.py calibrage.py tools/*.py && python tools/calibrage_selfcheck.py && python tools/tetris_selfcheck.py` then `git checkout -- calibration.json`.
- `tools/tetris_selfcheck.py` reuses calibrage_selfcheck stubs via `import tools.calibrage_selfcheck` (loads pygame/plux into sys.modules side effect). Tests BioState polling, anti-rebond, EMG edge, TetrisGame render @ 4 sizes. Both selfchecks write `calibration.json`.
- Selfcheck = pygame/plux stubs + render smoke (all `STATE_*` + PORTS/RECAL panels @ 5 sizes 960×600→2560×1440) + state-flow + detection + JSON gates. Prints `ALL GREEN`. Add asserts here when changing detection/flow.
- **Stub `Font` has FIXED metrics** (`get_height()=14`, `size()=len*7`) regardless of window → selfcheck proves "no crash / logic", NOT real layout. Verify responsive/overlap math BY HAND at MIN (960×600) and a large window.
- Stub `Surface` accepts ANY size incl. **negative** → selfcheck CANNOT catch negative-height rects (modal/overlay buttons, card grids) that crash real pygame. Give modals/overlays/grids a DETERMINISTIC vertical budget (header / list-of-N / footer, each clamped ≥0) and hand-check MIN 960×600.
- The selfcheck writes `calibration.json` (sim data) in cwd → `git checkout -- calibration.json` after running.
- Detection fns in `calibrage/detection.py` are pure — unit-testable with synthetic samples.

## Gotchas

- **Port indexing CRITICAL** : `calibration.json` stocke les ports en BASE 1 (`int(x_axis + 1)` côté calibrage) mais `device.live_buf` est indexé en BASE 0. Tout consommateur de la JSON DOIT soustraire 1. Concerné : `runtime.BioState.__init__` (helper `_p()`), `tetris._port_labels_from_calib`. Le radar du calibrage lit `sample[self.x_axis]` (déjà BASE 0) donc fonctionne ; runtime se trompait sur le canal → mouvement gauche/droite parasite en jeu.
- Capteurs "sautés" (bouton PASSER) : `calibrage.app.App.skipped = {ppg, accel, emg, eda}` sérialisé dans `calibration.json` sous `"skipped"`. `runtime.BioState` dérive `sim_ppg/sim_eda/sim_emg/sim_accel` (vrai si `skipped[k]` OU port manquant) → signal démo synthétisé (sin + bruit) au lieu de planter. EMG simulé : seuil ∞ (jamais actif). Accel simulé : x_norm/y_norm = 0 (pas de mouvement parasite). `_has_valid_calibration` accepte tout JSON avec ≥ 1 capteur calibré.
- Anti-rebond accéléro (`BitalinoInputHandler`) : latch `_x_was_settled` / `_y_was_settled` = True après ≥ `SETTLE_S=0.3 s` consécutifs dans `|norm| < SETTLE_THRESH=0.15`. Le latch RESTE True quand l'axe s'écarte → sens opposé / tilt-up / hard-drop n'accepté qu'avec latch True. Empêche overshoot rapide (qui traverse 0 sans s'arrêter) de compter comme retour au repos valide. Reset après chaque emit. Cooldown `MOVE_COOLDOWN_S=0.5` (2 inputs/sec). Sources de rotation cumulatives : clavier ↑ + EMG ≥ 0.5 s + tilt-up.
- EMG rotation : `BioState.consume_emg_rotation()` (`EMG_HOLD_SEC=0.5`) tient l'état hold/fired et retourne True UNE seule fois par contraction soutenue ≥ 0.5 s. Appelé par `BitalinoInputHandler.action_rotate` ET `KeyboardInputHandler.action_rotate` (clavier reçoit `bio` optionnel → EMG fonctionne même en mode CLAVIER).
- `_save_and_finish` symétrise la plage accéléro AVANT sérialisation : `x_min/x_max` englobent l'enveloppe `rest_samples` + plancher `_MIN_HALF=100` ADC de chaque côté du repos. Sans ça, un balayage asymétrique donne un span minuscule et le bruit ADC au repos dépasse la dead-zone → pièce gauche/droite parasite au démarrage du jeu. Toucher ce bloc → vérifier qu'aucune valeur `range.*` ne reste à zéro.
- `TetrisGame._draw_right_panel` : en `game_over` ET `_history` non vide → remplace widgets+plots live par `_draw_history_panel` (grille 2×3 : STRESS large filled / BPM+EDA avec baselines repos / FACTEUR VITESSE plage [0.3, 2.0]). Données depuis `_history` (5 Hz, populées dans `update`). Renderer `_draw_history_plot` accepte `baseline`, `y_range`, `fill_under`.
- Tests time-based (cooldown, settle latch, EMG hold) dans `tools/tetris_selfcheck.py` : maintenir la condition pendant `≥ SEUIL` via boucle `while time.time() - t0 < SEUIL + 0.05: handler.get_move(); time.sleep(0.01)`. Un seul appel ne suffit PAS (le latch lit `time.time()` réel). Alternative : injecter `bio._emg_hold_since = time.time() - (EMG_HOLD_SEC + 0.05)` pour franchir le seuil sans sleeper.
- `calibrage.py` is an 8-line shim; real code is the `calibrage/` package (`app.py` ~1.3k lines — Read with offset/limit).
- Calibration step order/numbers derive from `CALIB_STEPS`/`_STEP_NO` in `calibrage/app.py` — single source, never hardcode badge numbers.
- Adding/reordering a `CALIB_STEPS` entry or a `_port_keys`/sensor key is CROSS-CUTTING. Selfcheck hardcodes asserts to update: `_STEP_NO` map, `_on_recording_done` flow list, `ports_override` set, the (4×) `_auto_ports` dicts, the render-state loop, the `_start_single_recal` map. Plus every per-key dict in app.py: `_apply_port`, `_draw_port_editor` `rows`, `_draw_step_port_ctrl` `names`, `_STEP_PORT_KEY`, recal `checks`, `_save_and_finish`. A missed dict = `KeyError` when that screen draws.
- Selfcheck flow-list ORDER = source order of branches in `_on_recording_done`; a literal `self.state = STATE_X` inserts its pair AT that branch's position (not appended at end). Reorder the expected list to match, or route the transition through a helper to stay invisible to the regex.
- Sensors detected by elimination are calibrated LAST and exclude all prior ports: PPG first → axes → EMG → EDA. New "leftover" sensors go last via `_ppg_excl(...)`.
- Test scripts via Bash heredoc: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` first — Windows console is cp1252 and crashes on `σ`/accents.
- Bash tool is POSIX (not PowerShell): use `2>/dev/null`, not `$null`.
- No PPG/cardiac dead zone (removed — was a bad idea). `ppg` block in `calibration.json` is just `{port, bpm_rest}`. PPG still auto-detected first; bpm shown only on the DONE screen.
- Dead-zone screen: LEFT col = radar + port editor always visible inline (`_draw_port_editor`, ◀▶ AUTO→P1..P6, `_cycle_port`/`_apply_port`). RIGHT col = 3 slider blocks (accel ZM, EMG, EMG AMPLI) + invert toggles + `[RECALIBRER]` + `[VALIDER]`. Block tuple is 7-wide `(lbl,acc,sld,st,stcol,gauge,vstr)`; gauge block is taller. Sliders use `Slider.draw_compact`. `slider_emg` = EMG dead-zone threshold frac; `slider_emg_gain` (block 3) sets EMG amplification live via `_slider_to_emg_gain`/`_emg_gain` (range `EMG_GAIN_MIN..MAX`). `invert_x/y` flip live radar AND saved. `[RECALIBRER]` sets `recal_select_mode=True` → draws `_draw_recal_selector` modal overlay (3 checkboxes ppg/accel/emg, confirm/cancel). Confirmed → `_start_recal(sensors)` builds `recal_queue` consumed by `_advance_recal()`. `MIN_W,MIN_H=960,600`. Any metric change needs a hand re-check at MIN 960×600 + large window (selfcheck can't catch overlap — see Testing).
- Single-sensor recalibration: `_start_single_recal(target)` jumps to that sensor's first state (`ppg`→REST, `accel`→LR, `emg`→EMG) keeping other data; the chain ends early via `_return_to_deadzone()` (HR branch returns if `recal_target=='ppg'`; UD branch if `=='accel'`; EMG branch always). EMG branch no longer assigns `self.state` directly (selfcheck flow regex updated — EMG→DEADZONE pair gone). Full restart (`_restart_calibration`, bottom button) still resets everything. LR/UD detection now also excludes `emg_port` (None-safe) so accel-only recal can't collide with the EMG port.
- EMG "toujours relâché"/"mal détecté" — two fixes: (1) `_live_emg` measures σ over the last ~`EMG_CYCLE_SECONDS` only, then amplifies the **excursion above rest** `emg_rest + gain*(raw-emg_rest)` (`gain` from `slider_emg_gain`, default `EMG_GAIN`); threshold stays raw so higher gain ⇒ weak contraction crosses. (2) `detect_emg_port(... , gain=EMG_GAIN)` amplifies the modulation (×gain) so a weak port clears the absolute `EMG_MIN_MOD` floor; returned `sigma_rest/flex` stay RAW (gain only drives the decision). `emg_rest`/`emg_flex` stored RAW. Modulation-ratio test invariant under gain.
- Selfcheck state-flow assert regexes literal `if self.state ==` / `self.state =` inside `_on_recording_done` only. Transitions via helpers (e.g. `_return_to_deadzone()`) are invisible to it — update the `flow ==` expected list when moving transitions into/out of helpers.
- When restyling visuals, keep constant/identifier names stable so logic (state machine, detection) stays untouched.
- `calibrage/` and `tools/` are **untracked** in git. Worktree agents don't get these files — they write to the main working directory regardless of `isolation: "worktree"`. Don't rely on worktree isolation for changes to these dirs.
- Responsive UI conventions: `Theme(w, h)` takes both dims, scales fonts on `min(w, h)/950`. All main-content panel draw fns use `self.screen.set_clip(rect)` / `set_clip(None)` to prevent text overflow. Vertical text positions always use `font.get_height()`, never hardcoded pixels. `_scope_rect` proportional: `btn_zone = max(100, int(panel.height * 0.24))`. When adding new pygame `Surface` methods, add a no-op to the `Surface` stub in `tools/calibrage_selfcheck.py` or the selfcheck render-smoke will crash.
- `device.live_buf` is DECIMATED 1:8 (~125 Hz @ SAMPLING_HZ=1000). Use it EVERYWHERE for live reads in calibration + runtime — `BioState._update` mirrors `calibrage.App._live_emg`/`_live_bpm`/`_live_eda` exactly. **Do NOT poll `device.latest` to build a "full-rate" buffer**: `time.sleep(0.001)` on Windows has ~15 ms resolution so the poller only samples ~60-100 Hz (worse than live_buf). σ population is preserved by decimation for stationary signal → calibrated `emg_rest`/`emg_flex` on raw `recorded` match `pstdev(live_buf[-EMG_CYCLE_SECONDS×live_freq:])` in expectation. EMG window in runtime = `int(live_freq × EMG_CYCLE_SECONDS)` from `calibrage.config`.
- `CalibrationApp(screen, address, preconnected=(device, thread))` skips DETECT phase — used when launcher already opened the device. App still posts `pygame.QUIT` on STATE_DONE main-button; event consumed INSIDE `app.run()` so the launcher resumes with empty queue.
- `TetrisGame.run()` returns `'quit' | 'recalibrate' | 'done'` — launcher loops on `'recalibrate'` to relaunch `CalibrationApp` without closing device or window.
- After `CalibrationApp.run()` / `_menu()` / anything that may `set_mode` on VIDEORESIZE, refresh main's `screen` via `pygame.display.get_surface() or screen` — old reference goes stale.
- Accel X/Y/Z detection is JOINT (`detect_accel_axes` in [calibrage/detection.py](calibrage/detection.py)) — runs at STATE_UD branch on rest+lr+ud samples. STATE_LR only sets a PROVISIONAL X via `detect_x_axis`; STATE_UD reassigns X/Y/Z together via ratio LR/UD (robust to diagonal motion).
- EMG auto-detect pre-excludes EDA port (detected via `detect_eda_port(rest_samples, ...)`) — EDA tonic drift else wins the modulation ratio. Pre-detection also fills `_auto_ports["eda"]` early.
- PowerShell `Out-File -Encoding utf8` écrit UTF-8 **avec BOM** (PS 5.1) — `json.loads()` Python plante avec `Unexpected UTF-8 BOM`. Écrire avec `[System.IO.File]::WriteAllText("$pwd\file", $txt)` (sans BOM) ou lire avec `encoding="utf-8-sig"`. Affecte tout script PowerShell générant du JSON consommé par Python (pipeline graphify, scripts d'analyse).
- `calibrage.detection._estimate_bpm_and_score` est mutualisé : calibrage l'utilise pour le BPM de repos (one-shot, raw samples @ 1 kHz), [runtime.py](runtime.py) `BioState._update` l'utilise pour le BPM live (sur `_fr_bufs[ppg_port]` plein débit, fenêtre 3 s) avec score-gating `_BPM_MIN_SCORE = 0.5`. Toucher l'algo affecte les deux ; garder la signature `(bpm, score)` et le σ floor=5.
- graphify CLI : `C:\Users\bidbi\AppData\Roaming\uv\tools\graphifyy\Scripts\graphify.exe` (installé via `uv tool install graphifyy`). Hook PreToolUse dans `.claude/settings.json` rappelle `graphify query "..."` avant grep/find. `graphify update .` rebuild incrémental (AST seul, pas d'API), à lancer après changement de code. Section `## graphify` en bas de ce fichier gère les règles d'usage.

## Architecture

**Launcher / game flow:** [tetris.py](tetris.py) is THE entry point now. Sequence: startup detection (with RÉESSAYER / MODE DÉMO buttons on fail) → menu(JOUER|CALIBRER|QUITTER) → optional `CalibrationApp` (with preconnected device) → menu(CLAVIER|CAPTEURS|QUITTER) → game loop (jeu ↔ recalibrer via menu pause). Device + acq_thread shared across all phases — never reopened.

**Runtime layer:** [runtime.py](runtime.py) holds `BioState` (1 ms poll thread on `device.latest` + 50 Hz update thread → BPM/EDA/σ EMG/accel x_norm/y_norm), `BioSpeedModulator` (drop interval × 0.3..2.0 from HR + EDA delta vs rest), `KeyboardInputHandler` / `BitalinoInputHandler`. `BitalinoInputHandler.get_move` anti-rebond : sens opposé requiert un passage par le neutre franc (`|x| < dead_zone × NEUTRAL_FRAC`) — overshoot de décélération filtré. `action_rotate` sur le FRONT MONTANT de l'activation EMG. Pause = `K_TAB` ou `K_P`. Menu pause : RECOMMENCER (reset jeu courant) / RECALIBRER (relance `CalibrationApp` avec device partagé) / QUITTER.

**Speed model:** `TetrisGame._drop_interval` = `base_drop_interval(level) × modulator.factor() × time_factor`. `modulator.factor()` ∈ [0.3, 2.0] depuis `stress = max(stress_bpm, stress_eda)` clampé [-0.8, 1.0] (mapping `1 − 0.7·stress` si ≥0 sinon `1 + 1.25·|stress|`), lissé 0.9/0.1. `modulator.stress()` expose la version positive 0..1 lissée (panneau droit du jeu : texte + barre gradient vert→ambre→rouge avec repère 0.5). `time_factor = TIME_RAMP_GAIN ** (elapsed / TIME_RAMP_SEC)` clamped at `TIME_FACTOR_MIN` — accélération inéluctable, reset au restart.

**Calibration flow:** `calibrage/` package (shim `calibrage.py` → `app.py`). Modules: `config` (constants/palette), `detection` (PPG/EMG/axis algos), `device` (real+sim), `ui` (CRT widgets/render), `app` (state machine). Order: REPOS+CŒUR → RYTHME CARDIAQUE → G/D → H/B → MUSCLE/EMG → EDA → ZONE MORTE. PPG isolated first (accel still); accel detection excludes PPG only (EMG not yet known). EMG then **EDA last**, each isolated by elimination from prior ports. EMG: PPG + xyz known → port isolated by elimination (weak signal no longer needs absolute σ), confirmed by **modulation** of an envelope. EDA: the port with a CONTINUOUS signal from the start (not periodic like PPG, not flat like a still axis) — `detect_eda_port`, calibration just records a rest level (`EDA_SECONDS`). EMG recording is 30 s of randomly-timed on-screen consignes (`_build_emg_plan`: alternating CONTRACTEZ/RELÂCHEZ, each ≥`EMG_MIN_SEG` s, ≥`EMG_MIN_CONTRACT`/`EMG_MIN_RELEASE` of each, sum = `EMG_SECONDS`). ZONE MORTE screen tunes accel dead zone + EMG dead zone (`emg.dead_zone`→`emg.threshold`) + EMG amplification, live state chip + gauge for EMG (`draw_gauge`), G/D & H/B invert toggles, optional `[PORTS]` manual port override editor. No cardiac dead zone. Writes `calibration.json` (ports, `ports_override`, rest baseline, ranges, `dead_zone`, `invert`, `ppg` {port,bpm_rest}, `emg` {port,sigma_rest,sigma_flex,gain,dead_zone,threshold}, `eda` {port,rest}).

**BITalino device layer:** `Bitalino.py` wraps the PLUX-API. `NewDevice` extends `plux.SignalsDev`, receives frames via `onRawFrame` callback, and feeds thread-safe `deque` buffers. Sampling rate: 1000 Hz (configurable in `calibration.json`).

**Game engine:** `tetris.py` implements standard Tetris — 10×20 grid, 7 tetrominos, DAS (delay-auto-shift), soft/hard drop, score/level/lines. Layout 3 colonnes : stats gauche (titre/score/biosignaux compacts), grille centre, panneau droit (widget radar accéléro + jauge EMG en haut, 6 mini-plots ports en bas via `draw_plots_panel`). Réutilise `Theme`/`Button`/`draw_block`/`draw_radar`/`draw_gauge`/`draw_panel` du package calibrage.

## Dependencies

- `pygame` — game loop and rendering
- `plux` (PLUX-API-Python3/) — vendored proprietary SDK, platform-specific binaries, not on PyPI
- `matplotlib` — live signal plots in acquisition scripts
- Standard library: `threading`, `collections.deque`, `json`, `statistics`

## Key Files

| File | Purpose |
|------|---------|
| [tetris.py](tetris.py) | MAIN entry — launcher unifié (détection → menus → calibration → jeu) + classe `TetrisGame` |
| [runtime.py](runtime.py) | `BioState` (lecture live capteurs plein débit) + `BioSpeedModulator` + handlers (`KeyboardInputHandler`/`BitalinoInputHandler`) |
| [calibrage.py](calibrage.py) | Calibrage standalone — délègue au package `calibrage/` |
| [calibrage/](calibrage/) | Calibration package: `config`/`detection`/`device`/`ui`/`app` |
| [tools/calibrage_selfcheck.py](tools/calibrage_selfcheck.py) | Headless calibration verification (`ALL GREEN`) |
| [tools/tetris_selfcheck.py](tools/tetris_selfcheck.py) | Headless tetris/runtime verification (`ALL GREEN`) |
| [Bitalino.py](Bitalino.py) | PLUX-API device wrapper |
| [calibration.json](calibration.json) | Device address, port mapping, thresholds (generated by `calibrage.py`) |
| [DOCUMENTATION.txt](DOCUMENTATION.txt) | French API docs for `tetris.py` and acquisition scripts |

## Language

Code comments and documentation are in French.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
