#!/usr/bin/env bash
set -euo pipefail
out=${1:?Pass an empty output path}
if [ -e "$out" ]; then
  echo "Output path already exists: $out" >&2
  exit 1
fi
mkdir -p "$out"
git archive 353e373 static | tar -x -C "$out"
src=${PREVIEW_SOURCE:-site}
cp "$src/index.html" "$src/preview.js" "$src/preview.css" "$out/"
python3 - "$out" <<'PY'
from pathlib import Path
import sys
out = Path(sys.argv[1])
for path in [out / 'index.html', *out.joinpath('static').rglob('*')]:
    if not path.is_file() or path.suffix not in {'.html', '.css', '.js'}:
        continue
    text = path.read_text(encoding='utf-8').replace('__APP_VERSION__', 'pages-353e373')
    if path.suffix == '.css':
        text = text.replace('/static/', './')
    if path.name == 'credits.html':
        text = text.replace('/static/images/temples/', './')
    path.write_text(text, encoding='utf-8')
PY
