#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ "${1:-}" = "--install-runtime" ]; then
    shift
    if [ "$(id -u)" -eq 0 ]; then sh tools/install-docker-ubuntu.sh; else sudo sh tools/install-docker-ubuntu.sh; fi
fi
command -v python3 >/dev/null || { echo 'Python 3.12+ is required.' >&2; exit 1; }
python3 tools/printflowctl.py doctor
# Forward explicit init options, for example --image3d --gpu amd-wsl --host-url URL.
python3 tools/printflowctl.py init "$@"
python3 tools/printflowctl.py up
