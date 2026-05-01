# KiCad Parasitic Calculator

Plugin KiCad pour calculer les paramètres parasites (Résistance, Inductance, Capacité) des interconnexions PCB entre deux vias.

## Fonctionnalités

- **Sélection intuitive** : Shift+Clic sur deux vias
- **Détection automatique** des plans de masse pour estimation précise de L et C
- **Calcul complet** :
  - Résistance DC
  - Résistance AC (effet de peau)
  - Inductance (modèle microstrip)
  - Capacité (modèle piste-plan de masse)
  - Impédance caractéristique Z₀
- **Paramètres configurables** : épaisseur cuivre, température, εr FR4, fréquence AC
- **Détails par segment** : analyse individuelle de chaque piste et via

## Installation

### Via Plugin and Content Manager (KiCad 10+)

1. Ouvrir **Outils → Plugin and Content Manager → Configurer** (icône engrenage)
2. Ajouter l'URL du dépôt :
   ```
   https://raw.githubusercontent.com/Fo170/kicad-parasitic-calculator/main/repository.json
   ```
3. Retourner dans l'onglet **Plugins**
4. Chercher "Parasitic Calculator" → **Installer**

### Manuel (Legacy)

```bash
mkdir -p ~/.kicad/scripting/plugins/
cp parasitic_calculator.py ~/.kicad/scripting/plugins/
```

## Utilisation

1. Ouvrir un PCB dans KiCad
2. Sélectionner **deux vias** avec Shift+Clic (même net)
3. **Outils → Plugins externes → Calculateur parasites R,L,C**
4. Les résultats s'affichent dans une fenêtre dédiée

## Configuration

Lancer le plugin sans sélection → cliquer **"Oui"** pour ouvrir les paramètres :

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| Cuivre (oz) | 1.0 | Épaisseur du cuivre |
| Température | 25°C | Correction résistivité |
| εr FR4 | 4.5 | Permittivité diélectrique |
| Fréquence AC | 100 MHz | Pour l'effet de peau |
| Détection plans de masse | Activé | Auto-détection des GND |

## Structure du dépôt

```
.
├── parasitic_calculator.py    # Code source du plugin
├── metadata.json              # Métadonnées PCM
├── repository.json            # Définition du dépôt PCM
├── README.md                  # Ce fichier
└── releases/
    └── parasitic_calculator-1.0.0-pcm.zip
```

## Créer une release PCM

```bash
# 1. Créer l'archive
mkdir -p parasitic_calculator-1.0.0-pcm
mkdir -p parasitic_calculator-1.0.0-pcm/plugins
mkdir -p parasitic_calculator-1.0.0-pcm/resources

cp parasitic_calculator.py parasitic_calculator-1.0.0-pcm/plugins/
# cp icon.png parasitic_calculator-1.0.0-pcm/resources/

zip -r parasitic_calculator-1.0.0-pcm.zip parasitic_calculator-1.0.0-pcm/

# 2. Uploader sur GitHub Releases
# 3. Mettre à jour les URLs dans metadata.json et repository.json
```

## Compatibilité

| KiCad | Support |
|-------|---------|
| 7.x | ✓ |
| 8.x | ✓ |
| 9.x | ✓ |
| 10.x | ✓ (PCM natif) |

## License

MIT
