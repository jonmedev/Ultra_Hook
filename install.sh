#!/bin/sh
set -eu
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.11+ is required: https://www.python.org/downloads/' >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.11+ is required: https://www.python.org/downloads/' >&2
    exit 1
fi
exec python3 -B "$script_dir/scripts/install.py" --with-agentcontroller "$@"
