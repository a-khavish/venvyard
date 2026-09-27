"""Shared fixtures.

Every test runs against a throwaway yard in tmp_path.  Nothing here may ever
touch a real ~/PY_VENV, so the yard root and the config directory are both
redirected before venvyard is imported by a test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_yard(tmp_path, monkeypatch):
    """Point venvyard at a temporary yard, config and state directory."""
    yard = tmp_path / "yard"
    yard.mkdir()
    monkeypatch.setenv("VENVYARD_HOME", str(yard))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("VENVYARD_THEME", raising=False)
    monkeypatch.delenv("VENVYARD_SHELL", raising=False)
    monkeypatch.delenv("VENVYARD_SHELL_INTEGRATION", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    return yard


@pytest.fixture
def yard(isolated_yard):
    """A Yard object rooted in the temporary directory."""
    from venvyard import config as configmod
    from venvyard.core import Yard
    cfg = configmod.load()
    return Yard(configmod.root_path(cfg), cfg)
