# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

TeTrino — Tetris game controlled by BITalino biosensors (accelerometer/EMG) via Bluetooth. Uses PLUX-API for hardware communication.

## Running the Project

```bash
# Tetris (keyboard control)
python tetris.py

# Accelerometer calibration UI
python calibrage.py                        # requires BITalino hardware
python calibrage.py --demo                 # simulated data, no hardware needed
python calibrage.py BTH98:D3:51:FE:87:0E  # explicit device address

# Live BITalino signal acquisition + plots
python OneBITalinoAcquisitionExample.py

# Headless verification (no pygame/hardware) — MUST stay "ALL GREEN" after edits
python tools/calibrage_selfcheck.py
```

**This environment has no `pygame` (cannot pip-build it) — `python calibrage.py` will not run here.** Validate logic/rendering headless instead.

## Testing without hardware/pygame

- One-liner after every edit: `python -m py_compile calibrage/*.py calibrage.py tools/calibrage_selfcheck.py && python tools/calibrage_selfcheck.py` then `git checkout -- calibration.json`.
- Selfcheck = pygame/plux stubs + render smoke (all `STATE_*` + PORTS/RECAL panels @ 5 sizes 960×600→2560×1440) + state-flow + detection + JSON gates. Prints `ALL GREEN`. Add asserts here when changing detection/flow.
- **Stub `Font` has FIXED metrics** (`get_height()=14`, `size()=len*7`) regardless of window → selfcheck proves "no crash / logic", NOT real layout. Verify responsive/overlap math BY HAND at MIN (960×600) and a large window.
- Stub `Surface` accepts ANY size incl. **negative** → selfcheck CANNOT catch negative-height rects (modal/overlay buttons, card grids) that crash real pygame. Give modals/overlays/grids a DETERMINISTIC vertical budget (header / list-of-N / footer, each clamped ≥0) and hand-check MIN 960×600.
- The selfcheck writes `calibration.json` (sim data) in cwd → `git checkout -- calibration.json` after running.
- Detection fns in `calibrage/detection.py` are pure — unit-testable with synthetic samples.

## Gotchas

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

## Architecture

**Sensor integration seam:** `InputHandler` class in [tetris.py](tetris.py) is the designed connection point between game logic and sensor input. Its methods (`get_move()`, `get_soft_drop()`, `action_rotate()`, etc.) currently read from `pygame.key.get_pressed()`. To enable sensor control, replace these with BITalino data reads + threshold logic from `calibration.json`.

**Calibration flow:** `calibrage/` package (shim `calibrage.py` → `app.py`). Modules: `config` (constants/palette), `detection` (PPG/EMG/axis algos), `device` (real+sim), `ui` (CRT widgets/render), `app` (state machine). Order: REPOS+CŒUR → RYTHME CARDIAQUE → G/D → H/B → MUSCLE/EMG → EDA → ZONE MORTE. PPG isolated first (accel still); accel detection excludes PPG only (EMG not yet known). EMG then **EDA last**, each isolated by elimination from prior ports. EMG: PPG + xyz known → port isolated by elimination (weak signal no longer needs absolute σ), confirmed by **modulation** of an envelope. EDA: the port with a CONTINUOUS signal from the start (not periodic like PPG, not flat like a still axis) — `detect_eda_port`, calibration just records a rest level (`EDA_SECONDS`). EMG recording is 30 s of randomly-timed on-screen consignes (`_build_emg_plan`: alternating CONTRACTEZ/RELÂCHEZ, each ≥`EMG_MIN_SEG` s, ≥`EMG_MIN_CONTRACT`/`EMG_MIN_RELEASE` of each, sum = `EMG_SECONDS`). ZONE MORTE screen tunes accel dead zone + EMG dead zone (`emg.dead_zone`→`emg.threshold`) + EMG amplification, live state chip + gauge for EMG (`draw_gauge`), G/D & H/B invert toggles, optional `[PORTS]` manual port override editor. No cardiac dead zone. Writes `calibration.json` (ports, `ports_override`, rest baseline, ranges, `dead_zone`, `invert`, `ppg` {port,bpm_rest}, `emg` {port,sigma_rest,sigma_flex,gain,dead_zone,threshold}, `eda` {port,rest}).

**BITalino device layer:** `Bitalino.py` wraps the PLUX-API. `NewDevice` extends `plux.SignalsDev`, receives frames via `onRawFrame` callback, and feeds thread-safe `deque` buffers. Sampling rate: 1000 Hz (configurable in `calibration.json`).

**Game engine:** `tetris.py` implements standard Tetris — 10×20 grid, 7 tetrominos, DAS (delay-auto-shift), soft/hard drop, score/level/lines. Classes: `Piece`, `Grid`, `InputHandler`, `Tetris`.

## Dependencies

- `pygame` — game loop and rendering
- `plux` (PLUX-API-Python3/) — vendored proprietary SDK, platform-specific binaries, not on PyPI
- `matplotlib` — live signal plots in acquisition scripts
- Standard library: `threading`, `collections.deque`, `json`, `statistics`

## Key Files

| File | Purpose |
|------|---------|
| [tetris.py](tetris.py) | Game engine + `InputHandler` integration seam |
| [calibrage.py](calibrage.py) | Thin entry shim → `calibrage/` package |
| [calibrage/](calibrage/) | Calibration package: `config`/`detection`/`device`/`ui`/`app` |
| [tools/calibrage_selfcheck.py](tools/calibrage_selfcheck.py) | Headless verification gate (`ALL GREEN`) |
| [Bitalino.py](Bitalino.py) | PLUX-API device wrapper |
| [calibration.json](calibration.json) | Device address, port mapping, thresholds (generated by `calibrage.py`) |
| [DOCUMENTATION.txt](DOCUMENTATION.txt) | French API docs for `tetris.py` and acquisition scripts |

## Language

Code comments and documentation are in French.
