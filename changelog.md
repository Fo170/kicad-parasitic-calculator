# Changelog

## 1.1.0 — 2026-10-24

Réécriture du moteur de calcul et de la couche de compatibilité KiCad. Tous les findings
de la revue de code sont traités.

### Compatibilité (le plugin ne démarrait pas sur KiCad 9/10)

| ID | Correction | Preuve |
|---|---|---|
| N1 | `pcbnew.IU_PER_MM` remplacé par `PCB_IU_PER_MM` avec repli | `test_regression.py` N1 |
| N2 | `pcbnew.Board.GetStandardLayerName` remplacé par `pcbnew.LayerName()` | N2 |
| N3 | Objets KiCad remplacés par des index `id()` dans le graphe BFS | N3 |
| N4 | `list(settings.GetCopperLayerCount())` → lecture directe de l'entier | N4 |

Avant correction, toute exécution levait `AttributeError` puis `TypeError` : le plugin
était inutilisable.

### Exactitude des calculs

| ID | Correction | Écart avant / après |
|---|---|---|
| R01 | `PCB_VIA` testé avant `PCB_TRACK` (un via *est* une piste) | vias comptés 0 → corrects ; Z₀ 37,2 Ω → 90,3 Ω |
| R04 | `L` et `C` dérivées de `Z₀` et `ε_eff` (`lc_from_z0`) | `L·C·c²/ε_eff` 0,20 → 1,00 |
| R05 | Capacité microstrip : `√ε_eff/(Z₀c)` au lieu de `ε_eff·ε₀·w/h` | sous-estimation 58 à 92 % → 0 % |
| R06 | Cohérence `Z₀ = √(L/C)` garantie sur tous les modèles | 0,000 % d'écart mesuré |
| R07 | Diélectrique `(t_total − n·t_cu)/(n−1)` | 0,533 mm → 1,530 mm sur 2 couches |
| R13 | `R_via` utilise `ρ(T)` comme les pistes | 31 % d'écart à 100 °C → 0 % |
| R14 | Longueur de via = span réel entre ses couches | traversant 1,600 mm, borgne 0,974 mm, enterré 0,661 mm |
| R15 | Z₀ du résumé = Z₀ du segment principal | 37,2 Ω → 128,97 Ω (cohérent avec le détail) |
| R25 | `√(LC)` remplacé par le retard `T_d = l·√ε_eff/c` | sémantique corrigée |

### Modèles ajoutés

- Piste isolée (Grover) quand aucun plan de référence n'entoure la piste.
- Microstrip (Hammerstad-Jensen) quand un seul plan encadre la piste.
- Stripline symétrique (Wheeler/Steer) entre deux plans équidistants.
- Stripline asymétrique (méthode des deux capacités) entre deux plans inégaux.
- Coplanaire CPW (Wen) et CPWG (Ghione-Naldi) avec plan coplanaire.
- Classification des vias : traversant, borgne, enterré, microvia.
- `C_via` (Johnson & Graham) et anti-pad configurable.

### Logique et robustesse

| ID | Correction |
|---|---|
| R08 | Nets de masse en égalité exacte : `+3V0` n'est plus pris pour `0` |
| R08b | Liste de nets vide ne détecte plus rien (avant : tout matchait) |
| R09 | Détection des plans réellement utilisée (zones par couche) |
| R10 | BFS avec intersection des couches : chemins impossibles refusés |
| R11 | `save()` retourne `(ok, message)` et n'écrit plus dans un dossier en lecture seule |
| R12 | Plus de `except:` nu |
| R19 | `_normalise()` répare une configuration corrompue au lieu de planter |
| R20 | Garde sur `pcbnew.GetBoard()` renvoyant `None` |
| R21 | Index spatial du BFS par point (au lieu de O(n²)) |
| R22 | Constantes et réglages morts supprimés |
| R23 | Un seul helper `to_mm()` au lieu de deux comportements divergents |
| R24 | Couches cuivre lues via `GetEnabledLayers().CuStack()` |

### Packaging PCM

| ID | Correction |
|---|---|
| R03 | Archive conforme : `plugins/`, `resources/`, `metadata.json` à la racine |
| R16 | `download_size` / `install_size` réels (16 818 / 62 648 octets) ; `$schema` corrigé en `https://go.kicad.org/pcm/schemas/v1` |
| R17 | `package_release.sh` idempotent : `set -euo pipefail`, version en argument, recalcul des tailles, empreintes et `update_timestamp` |

### Documentation

| ID | Correction |
|---|---|
| R18 | README réécrit : toutes les formules, sources datées, chemins d'installation réels, tableau des écarts corrigés |
| R26 | `parasitic_config.json` ajouté au `.gitignore` |
| — | `AGENTS.md` réécrit pour la nouvelle architecture |
| — | `test_plugin/` : 9 cartes de test (contour, footprints, plans, commentaires) et 4 suites de tests |

### Preuves

```
test_physique.py     : 16 vérifications, 0 échec
test_modeles.py      : 9 cartes, 6 types de via, 0 échec
test_bout_en_bout.py : 6 cartes, 0 échec
test_regression.py   : 21 vérifications, 21 corrigées, 0 échec
```

Validation croisée avec des valeurs publiées : microstrip 3 mm/1,6 mm → 50,31 Ω (réf. 50 Ω),
stripline 0,716 mm/1,6 mm → 49,99 Ω (réf. 50 Ω), épaisseur de peau 6,52 µm à 100 MHz
(réf. 6,6 µm), inductance de via 1,015 nH (réf. Johnson & Graham 1,015 nH).

### Findings écartés (faux positifs vérifiés)

`kicad_version: "7.0"` est la version **minimale** exigée par le schéma PCM, pas un
plafond : revendiquer 7 à 10 n'est pas contradictoire. L'absence de `maintainer` dans
`metadata.json`, de `$schema` dans `repository.json` et de `download_sha256` sont des
champs **optionnels**. Le chemin `~/.kicad/scripting/plugins` est bien documenté par
KiCad. Le facteur 4 de `capacite_stripline` est correct (deux gaps de `b/2`).

### Reste ouvert

- Lecture du stackup réel : l'API Python n'expose pas `BOARD_STACKUP`, l'empilement reste
  déduit du nombre de couches et de l'épaisseur totale.
- Écart coplanaire global au lieu d'une distance par segment.
- Capacité entre pistes voisines non calculée.
