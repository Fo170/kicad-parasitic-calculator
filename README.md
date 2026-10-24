# KiCad Parasitic Calculator

Plugin KiCad qui calcule la **résistance**, l'**inductance** et la **capacité** parasites
d'un chemin de cuivre entre deux vias d'un même net, en choisissant automatiquement le
modèle de ligne de transmission adapté à la structure réelle de la carte.

- **Version** : 1.1.1 (2026-10-24)
- **Compatibilité** : KiCad 7.x, 8.x, 9.x, 10.x (testé sur 10.0.7)
- **Licence** : MIT

## Pourquoi cette version

La version 1.0.0 ne fonctionnait pas sur les KiCad récents et produisait des valeurs
fausses. Les écarts constatés et corrigés en 1.1.0 :

| Défaut de la 1.0.0 | Conséquence mesurée | Correction 1.1.0 |
|---|---|---|
| `pcbnew.IU_PER_MM` n'existe plus (KiCad 9+) | plantage immédiat du plugin | `PCB_IU_PER_MM` avec repli |
| `pcbnew.Board.GetStandardLayerName` n'existe plus | plantage | `pcbnew.LayerName()` |
| `list(GetCopperLayerCount())` sur un `int` | `TypeError` à chaque analyse | lecture directe de l'entier |
| Objets KiCad utilisés comme clés de dictionnaire | `TypeError: unhashable` | index par `id()` |
| `isinstance(item, PCB_TRACK)` testé avant `PCB_VIA` | vias comptés 0, analysés comme pistes de 0,6 mm | test `PCB_VIA` en premier |
| Diélectrique = `t_total/(n+1)` | 0,53 mm au lieu de 1,53 mm sur une carte 2 couches | `(t_total - n·t_cu)/(n-1)` |
| `L` et `C` issues de modèles incompatibles | `L·C·c²/ε_eff` valait 0,20 au lieu de 1,00 | `L' = Z₀√ε_eff/c` et `C' = √ε_eff/(Z₀c)` |
| Inductance microstrip `ln(2h/w+1)` | facteur 2 sur les pistes larges | modèle de ligne cohérent |
| `C` microstrip `ε_eff·ε₀·w/h` | sous-estimation de 58 % à 92 % | `C' = √ε_eff/(Z₀c)` |
| Nets de masse par sous-chaîne | `'0'` matchait `+3V0`, `D0`, `IO0` | égalité exacte, casse ignorée |
| BFS sans test de couche | chemins électriquement impossibles | intersection des jeux de couches |
| Détection des plans inopérante | option sans effet | plans recherchés par couche et par zone |
| Via toujours à l'épaisseur totale | borgne/enterré surestimé | longueur réelle entre ses couches |
| `R_via` à 20 °C, pistes à `T` | 31 % d'écart à 100 °C | même `ρ(T)` partout |
| `√(LC)` appelé « constante de temps » | sémantique fausse | retard de propagation `T_d` |

## Fonctionnalités

- Sélection tolérante : deux vias, un via + son chemin de pistes, ou tout le chemin.
- Choix automatique du modèle de ligne selon l'empilement et les plans de cuivre :
  piste isolée, microstrip, stripline symétrique, stripline asymétrique,
  coplanaire (CPW) et coplanaire avec plan arrière (CPWG).
- Classement des vias : traversant, borgne, enterré, microvia.
- Résultats détaillés par élément, avec formules et sources dans l'interface.

## Installation

### Plugin and Content Manager (recommandé)

1. `Outils > Gestionnaire de plugins et de contenus > Configurer`
2. Ajouter l'URL du dépôt :
   ```
   https://raw.githubusercontent.com/Fo170/kicad-parasitic-calculator/main/repository.json
   ```
3. Onglet `Plugins`, chercher **Calculateur de parasites R,L,C**, installer.

### Manuelle

Copier `parasitic_calculator.py` dans le dossier de plugins de script de KiCad :

| Système | Chemin |
|---|---|
| Linux | `~/.local/share/kicad/<version>/scripting/plugins/` |
| Linux (Flatpak) | `~/.var/app/org.kicad.KiCad/data/kicad/<version>/scripting/plugins/` |
| Windows | `%APPDATA%\kicad\<version>\scripting\plugins\` |
| macOS | `~/Library/Preferences/kicad/<version>/scripting/plugins/` |

## Utilisation

1. Ouvrir un PCB.
2. Sélectionner les deux extrémités à analyser — trois gestes sont acceptés :
   - **les deux vias** seuls (`Shift+Clic` sur chacun) ;
   - **un via et le chemin de pistes** qui en part ;
   - **tout le chemin de pistes** entre les deux vias : les vias d'extrémité sont
     alors déduits automatiquement.
3. `Outils > Plugins externes > Calculateur parasites R,L,C`.

Si le clic sélectionne des pistes au lieu des vias, c'est le **filtre de sélection** de
KiCad qui exclut les vias : activez `Vias` dans la barre d'outils en haut à droite de
l'éditeur PCB. Le plugin reste utilisable sans cela, puisqu'il accepte une sélection de
pistes.

Lancer le plugin sans sélection valide affiche ce qui est actuellement sélectionné et
propose d'ouvrir la configuration.

## Modèles et formules

Notations : `l` longueur, `w` largeur de piste, `t` épaisseur de cuivre, `h` hauteur de
diélectrique, `b` hauteur totale entre deux plans, `f` fréquence, `ρ` résistivité,
`ε₀` permittivité du vide, `μ₀` perméabilité du vide, `c` vitesse de la lumière.

### Matériaux

```
ρ(T)  = 1.68e-8 × (1 + 0.00393 × (T − 20))          Ω·m
t     = cuivre_oz × 35 µm
```

### Empilement

Pour `n` couches cuivre dans une carte d'épaisseur `t_total` :

```
h    = (t_total − n·t_cu) / (n − 1)                 épaisseur de diélectrique
pas  = (t_total − t_cu) / (n − 1)                   pas entre plans médians
```

Sur une carte 2 couches de 1,6 mm avec 35 µm de cuivre : `h = 1,53 mm`
(la version 1.0.0 calculait 0,53 mm, soit 3 fois moins, ce qui surestimait `C` d'autant).

### Résistance

```
R_DC  = ρ(T) · l / (w · t)
δ     = √(2ρ / (2πf μ₀))                            épaisseur de peau
R_AC  = ρ(T) · l / (2(w + t) · δ)    si t ≥ 2δ, sinon R_DC
```

À 100 MHz, `δ = 6,52 µm` pour le cuivre : une piste de 35 µm est donc en régime de peau.

### Piste isolée (aucun plan de référence)

Formule de Grover pour un conducteur rectiligne de section rectangulaire :

```
L = (μ₀·l / 2π) · [ ln(2l / (w + t)) + 0,5 + (w + t) / (3l) ]
```

`C` et `Z₀` ne sont pas définies sans plan de retour : elles sont laissées à zéro.

### Microstrip (piste externe au-dessus d'un plan)

Permittivité effective de Hammerstad-Jensen :

```
ε_eff = (εr+1)/2 + (εr−1)/2 · [ 1/√(1 + 12h/w) + 0,04·(1 − w/h)² ]   si w/h < 1
ε_eff = (εr+1)/2 + (εr−1)/2 ·   1/√(1 + 12h/w)                        si w/h ≥ 1
```

Impédance caractéristique :

```
w/h < 1  :  Z₀ = (60/√ε_eff) · ln(8h/w + w/(4h))
w/h ≥ 1  :  Z₀ = 120π / (√ε_eff · (w/h + 1,393 + 0,667·ln(w/h + 1,444)))
```

### Stripline symétrique (piste entre deux plans)

```
W    = w / b
T    = t / b
Weff = W − (0,35 − W)² / (1 + 12T)      si W < 0,35, sinon Weff = W
Z₀   = 30π / (√εr · (Weff + 0,4413))
ε_eff = εr
```

### Stripline asymétrique (hauteurs haut et bas différentes)

Méthode des deux capacités : chaque demi-structure est traitée comme une stripline
centrée de hauteur `2h`, puis les capacités sont mises en parallèle.

```
Z₀U = stripline(w, 2·h_upper)      Z₀L = stripline(w, 2·h_lower)
C₀U = √εr / (c · Z₀U)              C₀L = √εr / (c · Z₀L)
C₀  = C₀U/2 + C₀L/2
L₀  = εr / (C₀ · c²)
Z₀  = √(L₀ / C₀)
```

### Coplanaire (CPW et CPWG)

Modèle conforme de Wen / Ghione-Naldi, avec `a = w/2` et `b = a + écart` :

```
k  = a / b
Z₀ = 30π / (√ε_eff · K(k)/K'(k))
```

Sans plan arrière :

```
ε_eff = (εr + 1) / 2
```

Avec plan arrière (CPWG) :

```
k₃    = tanh(πa/2h) / tanh(πb/2h)
R₁    = K(k)/K'(k)                R₃ = K(k₃)/K'(k₃)
ε_eff = (1 + εr·R₁·R₃) / (1 + R₁·R₃)
```

Les rapports `K(k)/K'(k)` sont évalués par moyenne arithmético-géométrique, qui converge
quadratiquement et évite les approximations logarithmiques.

### Conversion ligne de transmission

Une fois `Z₀` et `ε_eff` connus, `L` et `C` sont dérivés de la même ligne, ce qui garantit
`Z₀ = √(L/C)` et `L·C = ε_eff·(l/c)²` :

```
L' = Z₀ · √ε_eff / c        C' = √ε_eff / (Z₀ · c)
T_d = l · √ε_eff / c        retard de propagation
```

C'est le correctif principal de la 1.1.0 : la 1.0.0 combinait trois modèles incompatibles
et obtenait `L·C·c²/ε_eff = 0,20` au lieu de `1,00`.

### Vias

```
R_via = ρ(T) · h_span / (π·(R² − r²))               fut cylindrique creux
L_via = (μ₀·h_span / 2π) · [ ln(4h_span/d) + 1 ]    Johnson & Graham
C_via = (1,41e-12/0,0254) · εr · h_span · D₁ / (D₂ − D₁)
```

`h_span` est la distance réelle entre les couches du via (faces externes comprises), et
non l'épaisseur totale de la carte. `D₁` est le diamètre du pad, `D₂` celui de l'anti-pad
(`pad + 2 × marge`).

## Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| Cuivre (oz) | 1,0 | épaisseur `t`, et épaisseur de cuivre de l'empilement |
| Température (°C) | 25 | correction de `ρ` |
| Permittivité relative | 4,5 | `εr` du FR4 |
| Fréquence AC (MHz) | 100 | effet de peau |
| Résistance AC | activée | inclure ou non `R_AC` |
| Détection des plans | activée | recherche automatique des plans de cuivre |
| Nets de masse | GND, VSS, 0, GROUND, AGND, DGND | égalité exacte, casse ignorée |
| H de repli (mm) | 0,2 | utilisé si la détection est désactivée |
| Écart coplanaire (mm) | 0 (auto) | `0` reprend la clearance du netclass |
| Marge anti-pad (mm) | 0,25 | utilisée pour `C_via` |

La configuration est enregistrée dans `parasitic_config.json`, à côté du plugin, ou dans
le dossier de configuration utilisateur si ce répertoire n'est pas accessible en écriture.

## Tests

Le dossier [`test_plugin/`](test_plugin/) contient neuf cartes de test (contour, footprints,
plans de cuivre, documentation sur `User.Comments`) et quatre scripts de vérification.

```bash
cd test_plugin
python3 test_physique.py        # formules contre valeurs de référence
python3 test_modeles.py         # modèle attendu par carte + Z₀ = √(L/C)
python3 test_bout_en_bout.py    # analyse complète de six cartes
python3 test_selection.py       # résolution des extrémités (3 modes de sélection)
python3 test_regression.py      # non-régression des bugs corrigés
```

Sous Flatpak :

```bash
flatpak run --filesystem=$(pwd) --command=python3 org.kicad.KiCad test_physique.py
```

Vérifications de référence (écart mesuré) : microstrip 3 mm / 1,6 mm à 50,31 Ω pour 50 Ω
visés (+0,6 %), stripline 0,716 mm / 1,6 mm à 49,99 Ω (−0,03 %), épaisseur de peau à
6,52 µm pour 6,6 µm (−1,2 %), inductance de via à 1,015 nH (référence Johnson & Graham).

## Sources

Consultées le 2026-10-24.

| Sujet | Référence | URL |
|---|---|---|
| Microstrip (Z₀, ε_eff) | Wikipedia — Microstrip | https://en.wikipedia.org/wiki/Microstrip |
| Microstrip (Z₀, pertes) | Microwaves101 — Microstrip | https://www.microwaves101.com/encyclopedias/microstrip |
| `L'` et `C'` d'une ligne | Qucs — Single microstrip line | https://qucs.sourceforge.net/tech/node75.html |
| Stripline (Z₀, asymétrique) | Wikipedia — Stripline | https://en.wikipedia.org/wiki/Stripline |
| Stripline (géométrie) | Microwaves101 — Stripline | https://www.microwaves101.com/encyclopedias/stripline |
| CPW / CPWG (Ghione-Naldi) | everything RF — Coplanar Waveguide Calculator | https://www.everythingrf.com/rf-calculators/coplanar-waveguide-calculator |
| Effet de peau | Wikipedia — Skin effect | https://en.wikipedia.org/wiki/Skin_effect |
| `ρ₂₀` et `α` du cuivre | Wikipedia — Electrical resistivity and conductivity | https://en.wikipedia.org/wiki/Electrical_resistivity_and_conductivity |
| Inductance piste isolée | Grover, *Inductance Calculations* (NIST Bull. 169) | https://nvlpubs.nist.gov/nistpubs/bulletin/08/nbsbulletinv8n1p1_A2b.pdf |
| Inductance de via | Johnson & Graham — Sierra Circuits | https://www.protoexpress.com/blog/how-via-impedance-impacts-signal-integrity-in-pcbs |
| Relation ligne de transmission | Wikipedia — Transmission line | https://en.wikipedia.org/wiki/Transmission_line |
| Format des paquets PCM | KiCad — Publishing addons | https://dev-docs.kicad.org/en/addons/ |

## Limites

- Modèles quasi-statiques : dispersion et pertes diélectriques ne sont pas modélisées.
- L'empilement est reconstruit à partir du nombre de couches et de l'épaisseur totale ;
  un stackup asymétrique réel n'est pas lu (l'API Python n'expose pas le détail).
- L'écart coplanaire est une valeur globale, pas la distance réelle à chaque segment.
- La capacité parasite entre pistes voisines n'est pas calculée.
- Les arcs sont pris en compte par leur longueur, pas par leur géométrie propre.

## Créer une release

```bash
./package_release.sh 1.1.1
```

Le script construit l'archive PCM, calcule les tailles et empreintes réelles, puis met à
jour `metadata.json`, `packages.json` et `repository.json` (dont `update_timestamp`).

L'archive contient `plugins/parasitic_calculator.py`, `plugins/parasitic_icon.png`
(icône du bouton dans KiCad), `resources/icon.png` (icône du dépôt dans le gestionnaire
de plugins) et `metadata.json`. `resources.zip` fournit l'icône du dépôt.

## Licence

MIT — voir [LICENSE](LICENSE).
