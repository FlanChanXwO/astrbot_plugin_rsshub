#!/usr/bin/env bash
set -euo pipefail

show_help() {
    cat <<'EOF'
RSSHub Plugin Test Runner - Bash Version

Usage:
  tests/run_tests.sh [options]

Options:
  -v, --verbose                 Show verbose output
  -q, --quick                   Quick mode
  -c, --category <category>     Test category: unit, integration, all
  -h, --help                    Show this help message

Environment:
  RSSHUB_TEST_PYTHON=/path/to/python
      Override the Python interpreter. By default the script prefers
      the active virtualenv, then `uv run python` from the AstrBot root,
      then the local AstrBot venv, then system python.
  UV_CACHE_DIR=/path/to/cache
      Override uv cache directory. If unset, uv runs use a temp cache
      to avoid IDE/sandbox permission issues in ~/.cache/uv.

Examples:
  tests/run_tests.sh
  tests/run_tests.sh --verbose
  tests/run_tests.sh --category unit
  tests/run_tests.sh --quick
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tests_dir="$script_dir"
plugin_dir="$(cd "$tests_dir/.." && pwd)"
astrbot_root="$(cd "$plugin_dir/../../.." && pwd)"
run_tests_py="$tests_dir/run_tests.py"

python_cmd=()
uses_uv=0
if [[ -n "${RSSHUB_TEST_PYTHON:-}" ]]; then
    python_cmd=("$RSSHUB_TEST_PYTHON")
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    python_cmd=("$VIRTUAL_ENV/bin/python")
elif command -v uv >/dev/null 2>&1 && { [[ -f "$astrbot_root/uv.lock" ]] || [[ -f "$astrbot_root/pyproject.toml" ]]; }; then
    uses_uv=1
    export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/rsshub-plugin-uv-cache}"
    python_cmd=(uv --directory "$astrbot_root" run python)
elif [[ -x "$astrbot_root/.venv/bin/python" ]]; then
    python_cmd=("$astrbot_root/.venv/bin/python")
elif command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
elif command -v python >/dev/null 2>&1; then
    python_cmd=(python)
else
    echo "Python not found. Please install Python 3.9 or later." >&2
    exit 1
fi

args=()
category="all"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verbose)
            args+=("-v")
            shift
            ;;
        -q|--quick)
            args+=("--quick")
            shift
            ;;
        -c|--category)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for $1" >&2
                exit 2
            fi
            category="$2"
            args+=("--category" "$2")
            shift 2
            ;;
        --category=*)
            category="${1#*=}"
            args+=("--category" "$category")
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

case "$category" in
    unit|integration|all)
        ;;
    *)
        echo "Invalid category: $category. Expected unit, integration, or all." >&2
        exit 2
        ;;
esac

printf "Using command:"
printf " %q" "${python_cmd[@]}"
echo
echo "Using: $("${python_cmd[@]}" --version 2>&1)"
echo
echo "Running RSSHub Plugin Tests..."
echo "Category: $category"
echo

export PYTHONPATH="$plugin_dir${PYTHONPATH:+:$PYTHONPATH}"
set +e
if [[ ${#args[@]} -gt 0 ]]; then
    "${python_cmd[@]}" "$run_tests_py" "${args[@]}"
else
    "${python_cmd[@]}" "$run_tests_py"
fi
exit_code=$?
set -e

echo
if [[ $exit_code -eq 0 ]]; then
    echo "All tests passed!"
else
    echo "Some tests failed!" >&2
fi

exit "$exit_code"
