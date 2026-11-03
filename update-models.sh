#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$TASK_ROOT/scripts/nd.py" --root "$TASK_ROOT" models update "$@"
