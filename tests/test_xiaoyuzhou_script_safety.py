# -*- coding: utf-8 -*-
"""Safety contract for the bundled Xiaoyuzhou transcription script."""

import os
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "agent_reach"
    / "scripts"
    / "transcribe_xiaoyuzhou.sh"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_script_rejects_non_xiaoyuzhou_url_before_network_access(tmp_path):
    marker = tmp_path / "curl-was-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"#!/bin/sh\ntouch {marker}\nexit 99\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = os.environ.copy()
    env["GROQ_API_KEY"] = "gsk_test"
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(SCRIPT), "http://127.0.0.1/private"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "小宇宙" in result.stderr
    assert not marker.exists()


def test_script_bounds_resources_and_uses_random_private_workdir():
    content = SCRIPT.read_text(encoding="utf-8")

    assert "set -euo pipefail" in content
    assert "mktemp -d" in content
    assert 'chmod 700 "$WORK_DIR"' in content
    assert '/tmp/xiaoyuzhou_$$' not in content
    assert "MAX_AUDIO_SECONDS=" in content
    assert "MAX_AUDIO_BYTES=" in content
    assert "MAX_CHUNKS=" in content
    assert "--max-filesize" in content
    assert "--connect-timeout" in content
    assert "--max-time" in content


def test_script_completes_with_bounded_fake_dependencies(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir()
    output = tmp_path / "transcript.md"

    _write_executable(
        fake_bin / "curl",
        """#!/bin/sh
case "$*" in
  *xiaoyuzhoufm.com/episode/*)
    printf '%s\\n' '{"title":"安全测试","audio":"https://media.xyzcdn.net/test.mp3"}'
    ;;
  *media.xyzcdn.net/test.mp3*)
    previous=""
    for argument in "$@"; do
      if [ "$previous" = "--output" ]; then
        printf 'fake-audio' > "$argument"
        exit 0
      fi
      previous="$argument"
    done
    exit 2
    ;;
  *api.groq.com/openai/v1/audio/transcriptions*)
    printf '测试转录结果\\n200'
    ;;
  *)
    exit 3
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ffprobe",
        "#!/bin/sh\nprintf '60.0\\n'\n",
    )
    _write_executable(
        fake_bin / "ffmpeg",
        """#!/bin/sh
for argument in "$@"; do
  output="$argument"
done
printf 'compressed-audio' > "$output"
""",
    )

    env = os.environ.copy()
    env["GROQ_API_KEY"] = "gsk_test"
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["TMPDIR"] = str(runtime_tmp)
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "https://www.xiaoyuzhoufm.com/episode/test",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    transcript = output.read_text(encoding="utf-8")
    assert "# 安全测试" in transcript
    assert "测试转录结果" in transcript
    assert list(runtime_tmp.iterdir()) == []
