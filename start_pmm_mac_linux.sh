#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
exec python3 launcher.py --pmm "$@"
