#!/usr/bin/env bash
set -euo pipefail

# Generate rsshelp_light.png and rsshelp_dark.png for astrbot_plugin_rsshub.
# Usage:
#   ./scripts/gen_rsshelp.sh
#   ./scripts/gen_rsshelp.sh --theme light
#   ./scripts/gen_rsshelp.sh --theme dark
#   ./scripts/gen_rsshelp.sh light

ARGC=$#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ASTRBOT_ROOT="$(cd "$PLUGIN_DIR/../../.." && pwd)"

python_cmd=()
if [[ -n "${RSSHUB_HELP_PYTHON:-}" ]]; then
    python_cmd=("$RSSHUB_HELP_PYTHON")
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    python_cmd=("$VIRTUAL_ENV/bin/python")
elif command -v uv >/dev/null 2>&1 && { [[ -f "$ASTRBOT_ROOT/uv.lock" ]] || [[ -f "$ASTRBOT_ROOT/pyproject.toml" ]]; }; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/rsshub-plugin-uv-cache}"
    python_cmd=(uv --directory "$ASTRBOT_ROOT" run python)
elif [[ -x "$ASTRBOT_ROOT/.venv/bin/python" ]]; then
    python_cmd=("$ASTRBOT_ROOT/.venv/bin/python")
elif command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
elif command -v python >/dev/null 2>&1; then
    python_cmd=(python)
else
    echo "Python not found. Please install Python 3.12 or later." >&2
    exit 1
fi

cd "$PLUGIN_DIR" || exit 1

if [[ $ARGC -eq 0 ]]; then
    echo "Generating rsshelp_light.png and rsshelp_dark.png..."
else
    echo "Generating rsshelp image..."
fi
printf "Using command:"
printf " %q" "${python_cmd[@]}"
echo

if [[ $ARGC -eq 0 ]]; then
    "${python_cmd[@]}" "$SCRIPT_DIR/generate_rsshelp_image.py" --require-playwright
elif [[ "${1:-}" == "light" || "${1:-}" == "dark" ]]; then
    "${python_cmd[@]}" "$SCRIPT_DIR/generate_rsshelp_image.py" --require-playwright --theme "$1" "${@:2}"
else
    "${python_cmd[@]}" "$SCRIPT_DIR/generate_rsshelp_image.py" --require-playwright "$@"
fi
