import shutil

from agent_reach.utils.process import (
    mcporter_utf8_env_args,
    resolve_command,
    utf8_subprocess_env,
)


def test_utf8_subprocess_env_forces_python_utf8():
    env = utf8_subprocess_env({"PYTHONUTF8": "0", "OTHER": "value"})

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["OTHER"] == "value"


def test_mcporter_utf8_env_args():
    assert mcporter_utf8_env_args() == [
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
    ]


def test_resolve_command_uses_windows_cmd_path(monkeypatch):
    windows_path = r"C:\Users\neo\AppData\Roaming\npm\mcporter.CMD"
    monkeypatch.setattr(shutil, "which", lambda _name: windows_path)

    assert resolve_command("mcporter") == windows_path


def test_resolve_command_preserves_name_when_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert resolve_command("mcporter") == "mcporter"
