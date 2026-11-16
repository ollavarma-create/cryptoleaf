#!/usr/bin/env bash
# Build the development CryptoLeaf x86-64 AppImage with Nuitka.
# Run from the repository root with dependencies and Nuitka installed.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPDIR="$ROOT/build/Cryptoleaf.AppDir"
OUTPUT="$ROOT/dist/Cryptoleaf-v0.3-dev-x86_64.AppImage"
TOOL="$ROOT/build/appimagetool-x86_64.AppImage"
PYTHON="${PYTHON:-python}"

"$PYTHON" -m nuitka \
    --mode=standalone \
    --enable-plugin=pyqt6 \
    --include-package=soundfile \
    --include-package=pydub \
    --include-package=pywt \
    --output-dir=dist \
    --output-filename=Cryptoleaf \
    --remove-output \
    Cryptoleaf.py

test -x "$ROOT/dist/Cryptoleaf.dist/Cryptoleaf"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$APPDIR/usr/share/metainfo" "$ROOT/build"
cp -a "$ROOT/dist/Cryptoleaf.dist/." "$APPDIR/usr/bin/"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/usr/bin/Cryptoleaf" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/cryptoleaf.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Cryptoleaf
Comment=Image and audio steganography tool
Exec=Cryptoleaf
Icon=cryptoleaf
Terminal=false
Categories=Utility;Security;
EOF

cp "$ROOT/packaging/cryptoleaf.appdata.xml" "$APPDIR/usr/share/metainfo/cryptoleaf.appdata.xml"
cp "$ROOT/assets/icon.png" "$APPDIR/cryptoleaf.png"
cp "$ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/cryptoleaf.png"

# Extraction mode avoids requiring FUSE on GitHub-hosted runners.
if [[ ! -s "$TOOL" ]]; then
  curl -fL --retry 3 --output "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
fi
chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUTPUT"
test -s "$OUTPUT"
chmod +x "$OUTPUT"
( cd "$ROOT/dist" && sha256sum "$(basename "$OUTPUT")" > SHA256SUMS.txt && sha256sum -c SHA256SUMS.txt )
