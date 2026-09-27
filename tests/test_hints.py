"""The advice printed when the shell integration is not loaded.

A fish user used to be told `eval "$(venvyard --shell-init bash)"`, which is
wrong twice over: fish has no $(...) substitution, and it would fetch the bash
snippet.  The advice has to match the shell the user is actually running.
"""
from __future__ import annotations

import pytest

from venvyard.actions import integration_hint, shell_flavour, shell_name


@pytest.mark.parametrize("shell_path,expected", [
    ("/usr/bin/fish", "fish"),
    ("/bin/bash", "bash"),
    ("/bin/zsh", "zsh"),
    ("/usr/local/bin/fish", "fish"),
    ("/bin/sh", "bash"),          # unknown -> the safe default
    ("", "bash"),
])
def test_shell_name_from_SHELL(monkeypatch, shell_path, expected):
    monkeypatch.delenv("VENVYARD_SHELL", raising=False)
    monkeypatch.setenv("SHELL", shell_path)
    assert shell_name() == expected


def test_declared_venvyard_shell_wins_over_SHELL(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("VENVYARD_SHELL", "fish")
    assert shell_name() == "fish"
    assert shell_flavour() == "fish"


def test_fish_hint_uses_a_pipe_into_source(monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.delenv("VENVYARD_SHELL", raising=False)
    load, rc = integration_hint()
    assert load == "venvyard --shell-init fish | source"
    assert "$(" not in load, "fish has no $(...) command substitution"
    assert "bash" not in load
    assert rc == "~/.config/fish/config.fish"


@pytest.mark.parametrize("shell,rc", [("bash", "~/.bashrc"), ("zsh", "~/.zshrc")])
def test_posix_hints_name_their_own_shell_and_rc_file(monkeypatch, shell, rc):
    monkeypatch.setenv("SHELL", f"/bin/{shell}")
    monkeypatch.delenv("VENVYARD_SHELL", raising=False)
    load, rc_file = integration_hint()
    assert load == f'eval "$(venvyard --shell-init {shell})"'
    assert rc_file == rc


def test_hint_never_hardcodes_bash_for_a_fish_user(monkeypatch):
    """The specific regression: bash advice reaching a fish user."""
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.delenv("VENVYARD_SHELL", raising=False)
    assert "shell-init bash" not in integration_hint()[0]
