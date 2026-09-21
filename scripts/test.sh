#!/usr/bin/env sh
# Run every repository test suite and the production frontend build.
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_root=$(mktemp -d "${TMPDIR:-/tmp}/dmarc-control-tests.XXXXXX")
trap 'rm -rf "$test_root"' EXIT HUP INT TERM
if [ -n "${PYTHON:-}" ]; then
    python_bin=$PYTHON
elif command -v python3.12 >/dev/null 2>&1; then
    python_bin=python3.12
else
    python_bin=python3
fi
"$python_bin" -m venv "$test_root/venv"
python_bin="$test_root/venv/bin/python"

# Some bundled pnpm installations carry their own Node binary. Normal
# developer and CI installations already expose node directly, so this only
# fills that gap.
if ! command -v node >/dev/null 2>&1; then
    pnpm_path=$(command -v pnpm || true)
    if [ -n "$pnpm_path" ]; then
        bundled_node_dir=$(CDPATH= cd -- "$(dirname -- "$pnpm_path")/../../node/bin" 2>/dev/null && pwd || true)
        if [ -n "$bundled_node_dir" ] && [ -x "$bundled_node_dir/node" ]; then
            PATH="$bundled_node_dir:$PATH"
            export PATH
        fi
    fi
fi

export DASHBOARD_DATABASE_PATH="$test_root/dashboard.db"
export DASHBOARD_CONNECTION_KEY_PATH="$test_root/connection.key"
export DASHBOARD_BACKUP_KEY_PATH="$test_root/backup.key"
export PARSER_CONTROL_TOKEN_FILE="$test_root/parser-control/control.token"
export BACKUP_MAINTENANCE_LOCK_FILE="$test_root/parser-control/backup.lock"

"$python_bin" -m pip install --upgrade pip
"$python_bin" -m pip install --requirement "$repository_root/dashboard/backend/requirements.txt"

(
    cd "$repository_root/dashboard/frontend"
    if command -v corepack >/dev/null 2>&1; then
        corepack enable
        corepack prepare pnpm@11.9.0 --activate
    fi
    pnpm install --frozen-lockfile
    pnpm test
    pnpm build
)

PYTHONPATH="$repository_root/dashboard/backend${PYTHONPATH:+:$PYTHONPATH}" \
    "$python_bin" -m unittest discover -s "$repository_root/dashboard/backend/tests" -v
"$python_bin" -m unittest discover -s "$repository_root/parser/tests" -v
"$python_bin" -m unittest discover -s "$repository_root/backup/tests" -v
