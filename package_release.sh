#!/bin/bash
# Construction d'une release PCM pour KiCad.
#
# Usage : ./package_release.sh [version]
#
# Sans argument, la version est lue dans metadata.json. Le script :
#   1. construit l'archive avec la structure attendue par le PCM
#      (metadata.json + plugins/ + resources/ a la racine de l'archive),
#   2. calcule les empreintes et les tailles reelles,
#   3. met a jour packages.json, metadata.json et repository.json,
#   4. affiche les actions restantes (upload GitHub, commit).
#
# Il est idempotent : relancez-le apres toute modification du plugin.

set -euo pipefail

PLUGIN_NAME="parasitic_calculator"
IDENTIFIER="com.github.fo170.parasitic-calculator"
GITHUB_REPO="https://github.com/Fo170/kicad-parasitic-calculator"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$HERE"

if [ "$#" -ge 1 ]; then
    VERSION="$1"
else
    VERSION="$(python3 -c "import json;print(json.load(open('metadata.json'))['versions'][0]['version'])")"
fi

echo "=== Release ${PLUGIN_NAME} ${VERSION} ==="

command -v zip >/dev/null 2>&1 || { echo "zip est requis" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 est requis" >&2; exit 1; }

BUILD_DIR="${PLUGIN_NAME}-${VERSION}-pcm"
ZIP_FILE="${PLUGIN_NAME}-${VERSION}-pcm.zip"

echo "1/5 Nettoyage"
rm -rf "$BUILD_DIR" "$ZIP_FILE"

echo "2/5 Structure PCM"
mkdir -p "$BUILD_DIR/plugins" "$BUILD_DIR/resources"
cp parasitic_calculator.py "$BUILD_DIR/plugins/"
if [ -f parasitic_icon.png ]; then
    cp parasitic_icon.png "$BUILD_DIR/plugins/"
fi
if [ -f resources.zip ]; then
    unzip -p resources.zip resources/icon.png > "$BUILD_DIR/resources/icon.png" 2>/dev/null || true
fi

echo "3/5 Archive"
(
    cd "$BUILD_DIR"
    zip -qr "../${ZIP_FILE}" .
)

DOWNLOAD_SIZE="$(stat -c %s "$ZIP_FILE")"
INSTALL_SIZE="$(du -sb "$BUILD_DIR" | cut -f1)"

echo "4/5 Metadonnees"
python3 - "$VERSION" "$DOWNLOAD_SIZE" "$INSTALL_SIZE" "$IDENTIFIER" "$GITHUB_REPO" "$PLUGIN_NAME" <<'PY'
import json
import sys
import time

version, download_size, install_size, identifier, repo, plugin = sys.argv[1:7]
download_size = int(download_size)
install_size = int(install_size)
download_url = "%s/releases/download/v%s/%s-%s-pcm.zip" % (repo, version, plugin, version)
publish_date = time.strftime("%Y-%m-%d")

with open("metadata.json") as handle:
    metadata = json.load(handle)
with open("packages.json") as handle:
    packages = json.load(handle)

entry = {
    "version": version,
    "status": "stable",
    "kicad_version": "7.0",
    "download_url": download_url,
    "download_size": download_size,
    "install_size": install_size,
    "publish_date": publish_date,
}

metadata["versions"] = [entry]
with open("metadata.json", "w") as handle:
    json.dump(metadata, handle, indent=2, ensure_ascii=False)
    handle.write("\n")

package = packages["packages"][0]
package["versions"] = [dict(entry)]
package["description"] = metadata["description"]
package["description_full"] = metadata["description_full"]
with open("packages.json", "w") as handle:
    json.dump(packages, handle, indent=2, ensure_ascii=False)
    handle.write("\n")

archive_metadata = {key: value for key, value in metadata.items() if key != "versions"}
archive_metadata["versions"] = [{
    "version": version,
    "status": "stable",
    "kicad_version": "7.0",
}]
with open("%s-%s-pcm/metadata.json" % (plugin, version), "w") as handle:
    json.dump(archive_metadata, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY

# L'archive doit contenir metadata.json : on la reconstruit avec ce fichier.
rm -f "$ZIP_FILE"
(
    cd "$BUILD_DIR"
    zip -qr "../${ZIP_FILE}" .
)
DOWNLOAD_SIZE="$(stat -c %s "$ZIP_FILE")"
python3 - "$DOWNLOAD_SIZE" <<'PY'
import json
import sys

download_size = int(sys.argv[1])
for name in ("metadata.json", "packages.json"):
    with open(name) as handle:
        data = json.load(handle)
    if name == "packages.json":
        data["packages"][0]["versions"][0]["download_size"] = download_size
    else:
        data["versions"][0]["download_size"] = download_size
    with open(name, "w") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
PY

echo "5/5 Empreintes"
python3 - "$DOWNLOAD_SIZE" "$INSTALL_SIZE" <<'PY'
import hashlib
import json
import time

def digest(path):
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            sha.update(block)
    return sha.hexdigest()

now = int(time.time())
with open("repository.json") as handle:
    repository = json.load(handle)
repository["packages"]["sha256"] = digest("packages.json")
repository["packages"]["update_timestamp"] = now
repository["resources"]["sha256"] = digest("resources.zip")
with open("repository.json", "w") as handle:
    json.dump(repository, handle, indent=2, ensure_ascii=False)
    handle.write("\n")

print("  packages.json  sha256 %s" % repository["packages"]["sha256"])
print("  resources.zip  sha256 %s" % repository["resources"]["sha256"])
PY

echo
echo "=== Archive : ${ZIP_FILE} (${DOWNLOAD_SIZE} octets) ==="
echo "=== Install : ${INSTALL_SIZE} octets ==="
echo
echo "Prochaines etapes :"
echo "1. git tag v${VERSION} && git push origin v${VERSION}"
echo "2. Creer la release GitHub v${VERSION} et y joindre ${ZIP_FILE}"
echo "3. git add -A && git commit && git push"
