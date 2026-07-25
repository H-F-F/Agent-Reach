#!/usr/bin/env bash
# Agent Reach 本地完整验收：当前源码、完整 pytest、CLI 和只读 Doctor。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-reach-test.XXXXXX")"
HOME="$TEST_DIR/home"
export HOME
mkdir -p "$HOME"

cleanup() {
    if command -v deactivate >/dev/null 2>&1; then
        deactivate || true
    fi
    rm -rf -- "$TEST_DIR"
}
trap cleanup EXIT INT TERM

find_python() {
    local candidate
    for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
        if [ -z "$candidate" ] || ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi
        if "$candidate" -c \
            'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python)" || {
    echo "需要 Python 3.10 或更高版本" >&2
    exit 1
}
VENV_DIR="$TEST_DIR/venv"

echo "╔════════════════════════════════════════════╗"
echo "║    👁️  Agent Reach 本地完整验收             ║"
echo "╚════════════════════════════════════════════╝"
echo "Python: $("$PYTHON_BIN" --version 2>&1)"

if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --seed --python "$PYTHON_BIN" "$VENV_DIR"
else
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --quiet --disable-pip-version-check -e "$SCRIPT_DIR[dev]"

echo "🧪 运行完整测试..."
python -m pytest "$SCRIPT_DIR/tests" -q

echo "🔎 验证真实 CLI..."
agent-reach version
agent-reach install --env=local
agent-reach install --env=local --system --dry-run
agent-reach doctor --json > "$TEST_DIR/doctor.json"

DOCTOR_JSON="$TEST_DIR/doctor.json" python - <<'PY'
import json
import os
from pathlib import Path

report = json.loads(Path(os.environ["DOCTOR_JSON"]).read_text(encoding="utf-8"))
if not isinstance(report, dict) or not report:
    raise SystemExit("doctor --json did not return a channel report")
PY

python - <<'PY'
from agent_reach.channels.github import GitHubChannel
from agent_reach.channels.web import WebChannel
from agent_reach.channels.youtube import YouTubeChannel

assert GitHubChannel().can_handle("https://github.com/Panniantong/Agent-Reach")
assert YouTubeChannel().can_handle("https://www.youtube.com/watch?v=test")
assert WebChannel().can_handle("https://example.com")
PY

echo "✅ 完整验收通过：源码安装、pytest、默认安全安装、dry-run、Doctor、渠道路由"
