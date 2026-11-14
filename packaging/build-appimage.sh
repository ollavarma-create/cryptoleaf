#!/usr/bin/env bash
# Build the development Cryptoleaf x86-64 AppImage.
# Run from the repository root with Python dependencies and PyInstaller installed.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPDIR="$ROOT/build/Cryptoleaf.AppDir"
OUTPUT="$ROOT/dist/Cryptoleaf-v0.3-dev-x86_64.AppImage"
TOOL="$ROOT/build/appimagetool-x86_64.AppImage"

python -m PyInstaller \
    --noconfirm --clean --onedir --windowed \
    --name Cryptoleaf \
    --collect-all soundfile \
    --collect-all pydub \
    --collect-all pywt \
    Cryptoleaf.py

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$ROOT/dist"
cp -a "$ROOT/dist/Cryptoleaf/." "$APPDIR/usr/bin/"

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

cp "$ROOT/assets/icon.png" "$APPDIR/cryptoleaf.png"
cp "$ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/cryptoleaf.png"

# appimagetool is itself an AppImage. Extraction mode avoids dependence on FUSE
# on GitHub-hosted runners.
curl -fL --retry 3 --output "$TOOL" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUTPUT"
test -s "$OUTPUT"
chmod +x "$OUTPUT"
sha256sum "$OUTPUT"
