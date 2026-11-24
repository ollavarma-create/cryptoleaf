#!/usr/bin/env bash
# Build the development CryptoLeaf x86-64 AppImage with Nuitka.
# Run from the repository root with dependencies and Nuitka installed.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPDIR="$ROOT/build/Cryptoleaf.AppDir"
OUTPUT="$ROOT/dist/Cryptoleaf-v0.3-dev-x86_64.AppImage"
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
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$APPDIR/usr/share/metainfo" "$APPDIR/usr/share/applications" "$ROOT/build"
cp -a "$ROOT/dist/Cryptoleaf.dist/." "$APPDIR/usr/bin/"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/usr/bin/Cryptoleaf" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/usr/share/applications/io.github.ollavarma-create.cryptoleaf.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Cryptoleaf
Comment=Image and audio steganography tool
Exec=Cryptoleaf
Icon=cryptoleaf
Terminal=false
Categories=Utility;Security;
EOF

ln -s "usr/share/applications/io.github.ollavarma-create.cryptoleaf.desktop" "$APPDIR/io.github.ollavarma-create.cryptoleaf.desktop"
cp "$ROOT/packaging/cryptoleaf.appdata.xml" "$APPDIR/usr/share/metainfo/cryptoleaf.appdata.xml"
cp "$ROOT/assets/icon.png" "$APPDIR/cryptoleaf.png"
cp "$ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/cryptoleaf.png"

# Verified AppImage packaging tools; extraction mode avoids FUSE.
TOOL_VERSION="1.9.1"
TOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_VERSION="20251108"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

TOOLS_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TOOLS_DIR"' EXIT
TOOL="$TOOLS_DIR/appimagetool.AppImage"
RUNTIME="$TOOLS_DIR/runtime-x86_64"

curl --fail --location --retry 3 \
  "https://github.com/AppImage/appimagetool/releases/download/${TOOL_VERSION}/appimagetool-x86_64.AppImage" \
  -o "$TOOL"
printf '%s  %s\n' "$TOOL_SHA256" "$TOOL" | sha256sum -c -

curl --fail --location --retry 3 \
  "https://github.com/AppImage/type2-runtime/releases/download/${RUNTIME_VERSION}/runtime-x86_64" \
  -o "$RUNTIME"
printf '%s  %s\n' "$RUNTIME_SHA256" "$RUNTIME" | sha256sum -c -

chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" \
  --runtime-file "$RUNTIME" "$APPDIR" "$OUTPUT"
test -s "$OUTPUT"
chmod +x "$OUTPUT"
( cd "$ROOT/dist" && sha256sum "$(basename "$OUTPUT")" > SHA256SUMS.txt && sha256sum -c SHA256SUMS.txt )
