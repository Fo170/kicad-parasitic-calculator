# analyse.md — kicad-parasitic-calculator

> Étape 1 du skill `code-reviews-openfox`. Inventaire factuel destiné au `code_reviewer`.
> Dépôt : `Fo170/kicad-parasitic-calculator` · HEAD `6a15dcc` · `main` = `origin/main`.
> Lecture seule : aucun fichier de code n'a été modifié.

## 0. Cadrage

| Item | Valeur |
|---|---|
| Périmètre | `parasitic_calculator.py`, `package_release.sh`, `metadata.json`, `packages.json`, `repository.json`, `repositories.json`, `README.md`, `AGENTS.md` |
| Définition d'un bug | comportement faux (calcul erroné, plantage, API mal utilisée, incohérence doc↔code, métadonnées PCM invalides) |
| Hors périmètre | `étude.txt`, `Structure requise sur ton GitHub.txt`, `Workflow de mise à jour.txt`, artefacts `.zip` / `-pcm/` |
| Langage | Python 3 (guide : `guides/code_reviews_python.md`) + Bash (`package_release.sh`) + JSON |

## 1. Architecture

Mono-fichier `parasitic_calculator.py` (864 l.), 7 blocs :

1. constantes physiques (l. 17-24)
2. `ConfigManager` (l. 27-67) — persistance JSON
3. `GroundPlaneDetector` (l. 70-182) — nets de masse + hauteurs diélectriques
4. `ParasiticCalculator` (l. 185-305) — moteur mathématique pur
5. `ConfigDialog` (l. 308-409), `ResultDialog` (l. 412-583) — wxPython
6. `ParasiticPlugin(pcbnew.ActionPlugin)` (l. 586-860) — sélection, BFS, agrégation
7. `ParasiticPlugin().register()` (l. 864) — **exécuté à l'import**

## 2. Constantes globales

| Nom | L. | Valeur | Unité | Usage |
|---|---|---|---|---|
| `RHO_CUIVRE_20C` | 17 | `1.68e-8` | Ω·m | l. 196 (ρ(T)) et l. 295 (via, **sans** correction T) |
| `TEMP_COEF_CUIVRE` | 18 | `0.00393` | 1/°C | l. 196 |
| `MU_0` | 19 | `4π·1e-7` | H/m | l. 213, 235, 237, 305 |
| `EPSILON_0` | 20 | `8.854e-12` | F/m | l. 254, 263 |
| `EPSILON_R_FR4` | 21 | `4.5` | – | **jamais utilisé** |
| `CONFIG_FILE` | 24 | `dirname(__file__)/parasitic_config.json` | chemin | l. 48, 60 |

## 3. API et signatures

### `ConfigManager` (l. 27)
| Méthode | L. | Contrat |
|---|---|---|
| `DEFAULTS` | 30-41 | schéma : `copper_oz`(1.0), `temp_c`(25.0), `default_dielectric_mm`(0.2), `er_fr4`(4.5), `freq_mhz`(100.0), `detect_ground_planes`(True), `ground_net_names`(6 noms), `via_wall_thickness_um`(25.0, **jamais lu**), `include_ac_resistance`(True), `show_intermediate_vias`(True, **jamais lu**) |
| `load()` | 47-57 | JSON + complétion ; `except:` nu l. 52 |
| `save()` | 59-61 | écrit `CONFIG_FILE` ; aucune capture `OSError` |
| `get(key)` | 63-64 | ne lève jamais |
| `set(key, val)` | 66-67 | mémoire seule |

### `GroundPlaneDetector` (l. 70)
| Méthode | L. | In → Out |
|---|---|---|
| `_find_ground_nets()` | 80-88 | board → `list[int]` ; match par **sous-chaîne** insensible à la casse (l. 86) |
| `_extract_zones()` | 90-100 | → `list[dict(layer,bbox,net)]` |
| `_build_layer_stack()` | 102-143 | → `dict[layer_id, mm]` ; `list(GetCopperLayerCount())` l. 108 ; `dielectric = total/(n+1)` l. 115 |
| `_extract_layer_number(name)` | 145-151 | regex `In(\d+)` |
| `get_distance_to_ground(layer_id, position=None)` | 153-175 | → **mm** ; branche l. 162-173 contient `pass` l. 168 et ne peut retourner qu'un repli |
| `_to_mm(x)` | 177-182 | **toujours tuple** si `.x` |

### `ParasiticCalculator` (l. 185)
| Méthode | L. | Unités entrée → sortie |
|---|---|---|
| `__init__(config)` | 188-196 | `thickness_m = copper_oz*35e-6` (m) l. 191 ; `freq_hz` l. 192 ; `rho(T)` l. 196 |
| `resistance` | 198-203 | m,m → Ω ; garde l. 200 ne teste **pas** `thickness_m` |
| `resistance_ac` | 205-224 | m,m → Ω ; `max(r_dc, r_ac)` l. 224 |
| `inductance_microstrip` | 226-239 | m,m,m → H |
| `capacite_microstrip` | 241-255 | m,m,m → F |
| `capacite_stripline` | 257-264 | m,m,m → F ; **jamais appelée** |
| `impedance_microstrip` | 266-280 | m,m → Ω |
| `via_resistance` | 282-295 | **mm,mm,mm** → Ω ; utilise `RHO_CUIVRE_20C` l. 295 |
| `via_inductance` | 297-305 | **mm,mm** → H |

### `ParasiticPlugin` (l. 586)
| Méthode | L. | Rôle |
|---|---|---|
| `defaults()` | 589-596 | métadonnées plugin |
| `Run()` | 598-651 | entrée UI ; `except Exception` l. 650 |
| `_show_config()` | 653-659 | `ConfigDialog` + `save_config()` |
| `_analyze_path(board, via1, via2)` | 661-767 | agrégation ; `ValueError` l. 675 |
| `_find_path_bfs(...)` | 769-806 | graphe + BFS ; `board` **inutilisé** |
| `_items_connected(...)` | 808-820 | 4 combinaisons d'extrémités ; **pas de test de couche** |
| `_points_touch(p1,p2,tol=1000)` | 822-826 | tolérance **1000 nm** |
| `_to_mm(x)` | 828-835 | tuple si `.x`+`.y`, scalaire sinon |
| `_fmt(val)` | 837-849 | préfixes p/n/µ/m |
| `_show_results(...)` | 851-860 | `ResultDialog` |

### Dict résultats (`_analyze_path`, l. 754-767)
`length_mm`(mm), `width_mm`(mm, **dernier** segment), `layers`(int), `segments`(int), `via_count`(int), `resistance_ohm`(Ω), `resistance_ac_ohm`(Ω), `inductance_h`(H), `capacitance_f`(F), `impedance_ohm`(Ω, recalculée avec `last_width` + `default_dielectric_mm`), `details`(str).

## 4. Flux et unités

```
sélection (l.607) → vias (l.616) → validation net (l.636)
  → tracks du net (l.669) → pos_map en IU/nm (l.778) → BFS (l.792)
  → boucle: _to_mm (mm) → *1e-3 (m) → ParasiticCalculator (SI)
  → cumuls (Ω, H, F, mm) → dict résultats → ResultDialog
```
Ruptures d'unité notables : `via_*` en mm alors que le reste est en m ; `pos_map` reste en IU ; deux `_to_mm` au comportement différent (l. 177 vs l. 828).

## 5. Formules (transcription littérale)

| # | L. | Code |
|---|---|---|
| F1 ρ(T) | 196 | `RHO_CUIVRE_20C * (1 + TEMP_COEF_CUIVRE * (temp_c - 20))` |
| F2 R_DC | 202 | `rho * length_m / (width_m * thickness_m)` |
| F3 peau | 211-213 | `omega=2πf` ; `sigma=1/rho` ; `delta=sqrt(2/(omega*MU_0*sigma))` |
| F4 R_AC | 215-224 | si `thickness_m < 2*delta` → `r_dc` ; sinon `rho*L/(2*(W+T)*delta)` puis `max(r_dc,r_ac)` |
| F5 L microstrip | 234-237 | `w_h<1` : `(µ0/2π)·ln(2πh/w+0.5)` ; sinon `(µ0/2π)·ln(2h/w+1)` |
| F6 εeff (C) | 249-252 | `(er+1)/2 + (er-1)/2·[1/√(1+12h/w) + 0.04(1-w_h)²]` si `w_h<1` |
| F7 C microstrip | 254 | `εeff·ε0·w/h` |
| F8 C stripline | 263 | `4·ε0·er·w/h` |
| F9 εeff (Z0) | 274-277 | idem F6 (terme écrit `0.04(1-w/h)²`) |
| F10 Z0 | 275,278 | `w_h<1`: `60/√εeff·ln(8h/w+0.25w/h)` ; sinon `120π/(√εeff·(w/h+1.393+0.667·ln(w/h+1.444)))` |
| F11 R via | 291-295 | `ρ20·h/(π(R²-r²))` |
| F12 L via | 305 | `(µ0·h/2π)·ln(2h/r)` |
| F13 longueur piste | 694 | `√(dx²+dy²)` |
| F14 diélectrique | 115 | `total_thickness/(n_cu+1)` |
| F15 √(LC) | 500 | `sqrt(l*c)` |
| F16 masse | 86 | sous-chaîne casse-insensible |
| F17 connexité | 817-826 | `|dx|≤1000 nm ∧ |dy|≤1000 nm` |

## 6. Points d'entrée

`register()` (l. 864, **module**) → `defaults()` → `Run()` → `_analyze_path()` → `ResultDialog` ; `ConfigDialog` accessible seulement via `Run()` sans sélection valide.

## 7. Invariants supposés

1. Unités KiCad = IU (nm) ; SI (m) dans le moteur ; **mm** pour `via_*`.
2. Exactement 2 vias sélectionnés, même net, net ≠ 0.
3. `board` non `None` (déréférencé l. 607 sans test).
4. `ConfigManager.get` ne lève jamais.
5. `GetCopperLayerCount()` serait itérable (l. 108).
6. `thickness_m > 0` non vérifié avant division (l. 202).
7. `rho > 0` non vérifié avant `1/rho` (l. 212).
8. Chemin non vide sinon `ValueError`.
9. Connexité = coïncidence d'extrémités à 1 µm, **sans test de couche ni de net**.
10. Épaisseur PCB = hauteur de via, quel que soit le span.
11. `via_count` et `length_mm` incluent les 2 vias d'extrémité (l. 745).
12. Répertoire du script inscriptible (`save()`).
13. `results` contient toutes les clés (lues sans `.get()`).
14. `ground_net_names` = liste de `str` non vides.

## 8. Commandes

| Type | Commande | État |
|---|---|---|
| Syntaxe | `python3 -m py_compile parasitic_calculator.py` | OK |
| Import | interdit hors KiCad (`register()` l. 864) | — |
| Paquet | `bash package_release.sh` | destructif, non paramétré |
| Intégrité PCM | `sha256sum packages.json resources.zip` | concordant avec `repository.json` |
| Tests / lint / CI | **aucun** | — |

## 9. Métadonnées PCM — faits

- `repository.json` : hashes **concordants** avec les fichiers locaux ; `update_timestamp` 1777653689 / 1777651161 ; pas de `$schema`.
- `packages.json` : `download_size` 9515 = taille réelle du zip ; `install_size` 45000.
- `metadata.json` : `download_size` **15000** ≠ 9515 ; `install_size` 45000 ; pas de `maintainer` ; `resources.github`+`homepage`.
- `description` diffère entre les deux fichiers ; `description_full` identique.
- `kicad_version` 7.0 vs README 7→10 ; docstring module « Version 2.0 » vs paquet 1.0.0.
- `package_release.sh` : `VERSION` en dur, pas de `set -euo pipefail`, ne recalcule ni hash ni timestamp, n'inclut pas `metadata.json`.
- `README.md` documente `releases/` (inexistant) et `~/.kicad/scripting/plugins/`.
- `AGENTS.md` non versionné (`??`).

## 10. État d'avancement

| Étape | Statut |
|---|---|
| 0 Cadrage | fait |
| 1 Analyse | fait (ce fichier) |
| 2 Relecture | à faire |
| 2.5 Triage | à faire |
| 3 Plan | à faire |
| 3.5 `criteres.md` | à faire |
| 4 Correctifs | à faire |
| 5 Vérification | à faire |
| 6 Re-relecture | à faire |
| 7 Compactage | à faire |
| 8 Capitalisation | à faire |

Invariants à préserver pendant les correctifs : unités (IU/mm/SI), non-régression KiCad 7→10, `ConfigManager.get` sans exception, hashes PCM cohérents, UI tolérante aux zéros.
