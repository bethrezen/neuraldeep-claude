#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$TASK_ROOT/scripts/nd.py" --root "$TASK_ROOT" install "$@"
fi
printf '%s\n' 'Python 3.10+ is required: https://www.python.org/downloads/' >&2
exit 1
