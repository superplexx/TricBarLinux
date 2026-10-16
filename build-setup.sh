#!/usr/bin/env bash
# Gera dist/TricBar-Setup-<versao>.run (instalador unico) a partir de src/ e installer/.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/tricbar.py)"
[ -n "$VERSION" ] || { echo "nao achei VERSION em src/tricbar.py" >&2; exit 1; }
OUT="dist/TricBar-Setup-$VERSION.run"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/icons" dist
cp src/tricbar.py src/tricbar.desktop LICENSE README.md "$STAGE/"
python3 - "$STAGE" <<'PY'
import sys
from PIL import Image
im = Image.open("src/tricbar.png").convert("RGBA")
for n in (256, 128, 64, 48, 32):
    im.resize((n, n), Image.LANCZOS).save(f"{sys.argv[1]}/icons/tricbar-{n}.png", optimize=True)
PY

tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='@0' -C "$STAGE" -cf - . | gzip -9n > "$STAGE.tgz"
SHA="$(sha256sum "$STAGE.tgz" | cut -d' ' -f1)"
sed -e "s|@VERSION@|$VERSION|g" -e "s|@SHA256@|$SHA|g" installer/setup-stub.sh > "$OUT"
cat "$STAGE.tgz" >> "$OUT"
rm -f "$STAGE.tgz"
chmod 755 "$OUT"
echo "Gerado: $OUT ($(du -h "$OUT" | cut -f1))  sha256 do app: $SHA"
