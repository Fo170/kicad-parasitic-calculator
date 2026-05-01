#!/bin/bash
# Script de création d'une release PCM pour KiCad

VERSION="1.0.0"
PLUGIN_NAME="parasitic_calculator"

echo "=== Création de la release ${PLUGIN_NAME}-${VERSION} ==="

# Nettoyage
rm -rf "${PLUGIN_NAME}-${VERSION}-pcm" "${PLUGIN_NAME}-${VERSION}-pcm.zip"

# Structure PCM
mkdir -p "${PLUGIN_NAME}-${VERSION}-pcm/plugins"
mkdir -p "${PLUGIN_NAME}-${VERSION}-pcm/resources"

# Copier les fichiers
cp parasitic_calculator.py "${PLUGIN_NAME}-${VERSION}-pcm/plugins/"
# cp icon.png "${PLUGIN_NAME}-${VERSION}-pcm/resources/" 2>/dev/null || true

# Créer l'archive
zip -r "${PLUGIN_NAME}-${VERSION}-pcm.zip" "${PLUGIN_NAME}-${VERSION}-pcm/"

echo "=== Archive créée : ${PLUGIN_NAME}-${VERSION}-pcm.zip ==="
echo ""
echo "Prochaines étapes :"
echo "1. Uploader ${PLUGIN_NAME}-${VERSION}-pcm.zip sur GitHub Releases"
echo "2. Mettre à jour les URLs dans metadata.json et repository.json"
echo "3. Commiter et pousser"
