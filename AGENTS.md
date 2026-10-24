# AGENTS.md

Guide for AI coding agents working in this repository.

## 1. Project Overview

A single-file **KiCad Python Action Plugin** ("Calculateur de parasites R,L,C") that computes
parasitic **R, L, C**, characteristic impedance `Z₀` and propagation delay of a copper path
between two vias of the same net, plus via parasitics. It auto-selects the transmission-line
model from the real stackup and the copper planes around the trace.

- **Version** 1.1.1 · **Stack**: Python 3 (KiCad's bundled interpreter, 3.9+), `pcbnew`,
  `wxPython`, stdlib only otherwise (`math`, `os`, `json`, `collections.deque`, `glob`).
- **No build system, no test runner, no linter config, no CI.** Tests are plain scripts run
  with KiCad's Python because `pcbnew` is required.
- **Architecture** (`parasitic_calculator.py`, top to bottom):
  1. Physical constants + `SOURCES` (formula references shown in the UI)
  2. Compatibility shims: `IU_PER_MM`, `layer_name()`, `to_mm()`, `is_copper()`,
     `copper_stack()`, `agm()`, `k_over_kp()`
  3. Model labels (`MODEL_*`, `VIA_*`)
  4. `ConfigManager` — JSON persistence, schema in `DEFAULTS`, `_normalise()` repairs bad values
  5. `Stackup` — derives dielectric thickness / pitch / span from layer count + board thickness
  6. `BoardModel` — ground nets, copper zones, reference planes per layer
  7. `ParasiticCalculator` — pure math engine, SI in / SI out, no KiCad objects
  8. `PathAnalyser` — BFS over the net, model selection, per-item records, aggregation
  9. `ConfigDialog`, `ResultDialog` — wx UI
  10. `ParasiticPlugin(pcbnew.ActionPlugin)` + `ParasiticPlugin().register()` at module scope
- **Packaging**: KiCad PCM chain `repository.json` → `packages.json` → `metadata.json` → release ZIP.

## 2. Directory Structure

```
.
├── parasitic_calculator.py     # THE plugin (single file, ~1490 lines)
├── metadata.json               # PCM v1 package metadata (standalone)
├── packages.json               # PCM repository package list
├── repository.json             # PCM repo index: URLs + sha256 + update_timestamp
├── repositories.json           # Local helper: repo list to paste in KiCad PCM
├── resources.zip               # Repo resources archive (tracked on purpose)
├── package_release.sh          # Builds the PCM zip and refreshes all hashes/sizes
├── README.md                   # User docs (FR) + all formulas + sources
├── AGENTS.md                   # This file
├── analyse.md                  # Bug-hunt inventory (FR, kept for traceability)
├── changelog.md                # Version history and fixes (FR)
├── test_plugin/
│   ├── README.md               # What each test board covers
│   ├── generer_cartes_test.py  # Regenerates the 9 test boards via pcbnew
│   ├── t_*.kicad_pcb           # Test boards (outline, footprints, planes, comments)
│   ├── test_physique.py        # Formulas vs published reference values
│   ├── test_modeles.py         # Expected model per board + Z₀ = √(L/C)
│   ├── test_selection.py       # Tolerant endpoint resolution (3 selection modes)
│   ├── test_bout_en_bout.py    # End-to-end analysis of six boards
│   └── test_regression.py      # Non-regression for every fixed bug
└── parasitic_calculator-*-pcm/ + .zip   # BUILD ARTIFACTS (gitignored)
```

## 3. Build, Lint, Test Commands

```bash
# Syntax check only — works without KiCad, ALWAYS run after editing
python3 -m py_compile parasitic_calculator.py

# Full test suite (needs pcbnew). Run from test_plugin/.
python3 test_physique.py         # formulas vs reference values
python3 test_modeles.py          # model selection + L/C/Z₀ coherence
python3 test_bout_en_bout.py     # end-to-end on six boards
python3 test_regression.py       # 21 non-regression checks, exits 1 on failure

# Same, with KiCad installed as Flatpak
flatpak run --filesystem=$(pwd) --command=python3 org.kicad.KiCad test_physique.py

# Optional style check if available
ruff check parasitic_calculator.py

# Package build: rebuilds the zip, rewrites sizes/hashes in all three JSON files
./package_release.sh 1.1.1

# PCM integrity: these MUST match repository.json
sha256sum packages.json resources.zip

# Regenerate the test boards
python3 test_plugin/generer_cartes_test.py
```

`import parasitic_calculator` **fails outside KiCad** because `register()` runs at module
scope. Never use it as a smoke test.

## 4. Code Conventions

- **Language**: identifiers in English; comments, docstrings, UI strings and README in
  **French, without accents** in the plugin source (wx/`pcbnew` portability). Keep new
  user-visible strings French.
- **Comments**: sparse, one-line docstrings stating the formula and its reference. The repo
  deliberately carries no inline commentary noise — do not add any.
- **Naming**: `PascalCase` classes, `snake_case` functions, `_private` helpers,
  `UPPER_SNAKE` constants. Model/via labels are French strings (`MODEL_STRIPLINE = "stripline symetrique"`).
- **Units**: SI (m, H, F, Ω, s) inside `ParasiticCalculator`. KiCad API values are integer
  nanometres — convert with `to_mm()`. `Stackup` and geometry work in **mm**; `via_*`
  methods take **mm**. Respect the boundary; do not mix.
- **Config keys**: `snake_case` with unit suffix; every new key MUST be added to
  `ConfigManager.DEFAULTS` and to `_normalise()` type coercion.
- **Results dict** (`PathAnalyser.analyse`): `length_mm`, `track_length_mm`, `via_length_mm`,
  `width_mm`, `layers`, `layer_names`, `segments`, `via_count`, `resistance_ohm`,
  `resistance_ac_ohm`, `inductance_h`, `capacitance_f`, `impedance_ohm`, `delay_s`,
  `model_counts`, `via_counts`, `records`, `stackup`, `cpw_gap_mm`, `details`.
  `ResultDialog` reads these directly — changing a key means updating the dialog.
- **Formatting**: use `fmt_value()` (engineering prefixes) everywhere numbers are displayed.
- **Adding a model**: add a `MODEL_*` label, a method on `ParasiticCalculator`, a branch in
  `PathAnalyser.select_model`, a formula line in `ResultDialog._models_text`, a `SOURCES`
  entry, a README section, and a test board in `test_plugin/`.

## 5. Key Abstractions

| Entity | Role | Contract |
|---|---|---|
| `ConfigManager` | Persisted settings | `.get()` never raises; `.save()` returns `(ok, message)` |
| `Stackup(board, t_cu_mm)` | Layer geometry | `dielectric(a,b)` = mm of dielectric between two layers (the `h` of the line models); `distance(a,b)` = median-plane distance; `span_length(a,b)` = via barrel length |
| `BoardModel(board, config)` | Ground nets + zones | `nearest_planes(layer, stackup, pos)` → `(above, below)`; `has_plane()` / `has_ground_plane()` |
| `ParasiticCalculator(config)` | Pure math | SI floats in/out; returns `0.0` on invalid input instead of raising |
| `PathAnalyser(board, config)` | Orchestration | `.find_path()` → ordered item list or `[]`; `.analyse()` → results dict, raises `ValueError` when no path |
| `ParasiticPlugin.Run` | KiCad entry point | `resolve_endpoints()` accepts 2 vias, 1 via + tracks, or a full track path; endpoints must share a non-zero net |

Design invariant worth preserving: **L and C always come from `lc_from_z0(Z₀, ε_eff, l)`**,
so that `Z₀ = √(L/C)` and `L·C = ε_eff·(l/c)²` hold for every model. Never compute L and C
from independent formulas again — that was the core bug of 1.0.0.

## 6. Common Pitfalls

1. **Never `import` the module outside KiCad.** `register()` runs at import; `pcbnew`/`wx`
   are absent in plain CPython. Verify with `py_compile`, not import.
2. **KiCad API drift is real.** `IU_PER_MM` → `PCB_IU_PER_MM`, `Board.GetStandardLayerName`
   → `pcbnew.LayerName`, `PCB_VIA` subclasses `PCB_TRACK`. Always go through the shims in
   the compatibility section instead of calling `pcbnew` directly.
3. **Test `PCB_VIA` before `PCB_TRACK`.** `PCB_VIA` *is* a `PCB_TRACK`; the reverse order
   silently routes vias through the track branch (`via_count` = 0, width = pad diameter).
4. **KiCad objects are not hashable, and SWIG recreates them.** Index by `id(item)`, never
   use board items as dict keys — but never compare two wrappers with `is` across separate
   `GetTracks()` calls either: they are different Python objects for the same item. Compare
   with `_same_point()` / `_same_item()` (position based). `find_path()` re-anchors its
   endpoints on one snapshot for this reason.
5. **Two different heights.** `dielectric()` (h, used by line models) ≠ `distance()` (pitch
   between median planes, used by `span_length()`). Swapping them skews every result.
6. **`h = (t_total − n·t_cu)/(n−1)`**, not `t_total/(n+1)`. On a 2-layer 1.6 mm board that
   is 1.53 mm vs 0.53 mm — a 3× error on C.
7. **Ground-net matching is exact** (case-insensitive). Substring matching made `'0'` hit
   `+3V0`/`D0`/`IO0` and an empty field match every net. Do not reintroduce `in`.
8. **BFS must check layer overlap.** Coincident endpoints on different layers are not a
   connection. `item_layers()` intersection enforces this.
9. **`repository.json` hashes are load-bearing.** Any edit to `packages.json` or
   `resources.zip` requires `sha256` + `update_timestamp` refresh — that is exactly what
   `package_release.sh` does; run it instead of editing JSON by hand.
10. **PCM archive layout.** The zip root must contain `plugins/`, `resources/` and
    `metadata.json` directly (no intermediate folder). The archive's `metadata.json` must
    not carry `download_url`/`download_size`/`install_size`/`publish_date`.
11. **Version lives in 3 JSON files + the zip name.** `package_release.sh <version>` updates
    all of them from one argument.
12. **Config file must never be committed** — it is in `.gitignore`.
13. **`resources.zip` is tracked despite `*.zip`** — `.gitignore` has an explicit
    `!resources.zip`. Do not "clean" it.
14. **wx UI must tolerate zeros**: `C` is 0 for isolated traces, so `Z₀`, delay and the AC
    resistance rows are conditional. Preserve those guards.
15. **Only the files listed in §2 belong here.** Historical notes (`étude.txt`, the two
    `*.txt` workflows) and `repositories.json` were removed in 1.1.0 as obsolete. Do not
    reintroduce scratch files at the repo root.
16. **Synology Drive + Flatpak quirk**: the Flatpak sandbox may see a stale snapshot of the
    mounted tree. When a test cannot find `parasitic_calculator.py`, copy the repo (or just
    the plugin + `test_plugin/`) into `/tmp` and run from there.
