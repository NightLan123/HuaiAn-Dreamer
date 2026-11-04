#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -c 'import numpy, PIL, tzdata' 2>/dev/null || .venv/bin/python -m pip install -r requirements.txt
exec .venv/bin/python run.py "$@"
