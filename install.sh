#!/bin/sh
# Thin POSIX wrapper — delegates to install.py
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
