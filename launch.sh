#!/usr/bin/env bash
set -euo pipefail
HUSH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HUSH_DIR"
if curl -fsS --max-time 2 http://127.0.0.1:8765/api/source 2>/dev/null | python3 -c 'import sys,json; assert json.load(sys.stdin).get("source")==sys.argv[1]' "$HUSH_DIR" 2>/dev/null; then
    xdg-open http://127.0.0.1:8765 >/dev/null 2>&1 || true
    exit 0
fi
python3 "$HUSH_DIR/server.py" &
HUSH_PID=$!
trap 'kill "$HUSH_PID" 2>/dev/null || true' EXIT INT TERM
for HUSH_ATTEMPT in {1..40}; do
    if curl -fsS --max-time 1 http://127.0.0.1:8765/api/source >/dev/null 2>&1; then
        xdg-open http://127.0.0.1:8765 >/dev/null 2>&1 || true
        break
    fi
    if ! kill -0 "$HUSH_PID" 2>/dev/null; then wait "$HUSH_PID"; exit 1; fi
    sleep 0.1
done
wait "$HUSH_PID"
