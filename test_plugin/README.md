# Cartes de test

Cartes KiCad servant a verifier le calculateur de parasites. Chaque carte est ouvrable
directement dans KiCad et contient :

- un contour de carte sur `Edge.Cuts` ;
- deux footprints (bornes `PinHeader_1x02_P2.54mm_Vertical` de `Connector_PinHeader_2.54mm`) ;
- un routage `SIG` reliant deux vias selectionnables avec `Shift+Clic` ;
- les plans de cuivre `GND` necessaires au cas teste ;
- une documentation en francais sur la couche `User.Comments`.

## Cartes fournies

| Fichier | Couches | Modele attendu | Ce qui est verifie |
|---|---|---|---|
| `t_microstrip.kicad_pcb` | 2 | microstrip | piste `F.Cu` au-dessus du plan `GND` de `B.Cu` |
| `t_stripline.kicad_pcb` | 4 | stripline symetrique | piste `In1.Cu` entre les plans `F.Cu` et `In2.Cu` |
| `t_stripline_asym.kicad_pcb` | 6 | stripline asymetrique | piste `In1.Cu`, plans `F.Cu` et `In3.Cu` |
| `t_cpw.kicad_pcb` | 2 | coplanaire (CPW) | plan coplanaire seul, aucun plan arriere |
| `t_cpwg.kicad_pcb` | 4 | coplanaire avec plan arriere (CPWG) | plan coplanaire `F.Cu` + plan arriere `In1.Cu` |
| `t_piste_isolee.kicad_pcb` | 2 | piste isolee | aucun plan de cuivre : L seule, C et Z0 nulles |
| `t_vias.kicad_pcb` | 6 | piste isolee | chaine traversant / borgne / enterre + microvia isolee |
| `t_no_fake_path.kicad_pcb` | 4 | aucun chemin | pistes `F.Cu` et `B.Cu` aux extremites superposees : doit refuser |
| `t_ground_match.kicad_pcb` | 2 | microstrip | le net `+3V3` ne doit pas etre pris pour un net de masse |

## Utilisation manuelle

1. Ouvrir une carte dans KiCad.
2. Selectionner le chemin a analyser : les deux vias du net `SIG`, un via et son
   chemin de pistes, ou tout le chemin entre les deux vias.
3. `Outils > Plugins externes > Calculateur parasites R,L,C`.

L'onglet `Modeles et formules` de la fenetre de resultats rappelle le modele retenu et
ses references.

## Regeneration

Les cartes sont produites par `generer_cartes_test.py`, qui utilise l'API `pcbnew` :

```bash
python3 generer_cartes_test.py [dossier_de_sortie]
```

## Tests automatises

Les scripts suivants s'executent avec le Python de KiCad (le module `pcbnew` doit etre
disponible) :

| Script | Role |
|---|---|
| `test_modeles.py` | verifie que chaque carte donne le modele attendu et que `Z0 = sqrt(L/C)` |
| `test_physique.py` | compare les formules a des valeurs de reference publiees |
| `test_bout_en_bout.py` | analyse complete de plusieurs cartes |
| `test_regression.py` | verifie que chaque bug corrige le reste |

```bash
kicad-cli version          # verifier la version
python3 test_physique.py   # depuis ce dossier
```

Sous Flatpak :

```bash
flatpak run --filesystem=$(pwd) --command=python3 org.kicad.KiCad test_physique.py
```

Les scripts resolvent le module du plugin depuis `..` ; aucune installation prealable
n'est necessaire.
