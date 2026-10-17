#!/usr/bin/env bash
# Compatibility entrypoint. Preview by default; pass --apply to rename.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/normalize_filenames.py" "$@"
