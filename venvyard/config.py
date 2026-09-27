"""Configuration handling for venvyard."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core import VenvyardError

APP = "venvyard"
ENV_ROOT = "VENVYARD_HOME"
ENV_THEME = "VENVYARD_THEME"

DEFAULTS = {
    "root": "~/PY_VENV",
    "theme": "default",
    "color": True,
    "autoname_style": "paren",      # paren -> name(1)   |  dash -> name-1
    "confirm_destructive": True,
    "default_python": "",           # "" = the interpreter running venvyard
    "with_pip_upgrade": True,       # upgrade pip right after creating
    "list_show_size": True,
    "scan_roots": ["~"],
    "scan_skip": [
        ".git", "node_modules", "__pycache__", ".cache", "snap",
        ".local/share/Trash", ".steam", ".mozilla", "go/pkg",
    ],
    "prune_days": 90,
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / APP


def config_file() -> Path:
    return config_dir() / "config.json"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(base).expanduser() / APP


def load_stored() -> dict:
    """Only what is actually in the config file, with no environment overlay.

    Writing back the result of load() persisted whatever VENVYARD_HOME,
    VENVYARD_THEME or NO_COLOR happened to be set to at the time, so a single
    `--config` in a shell with a temporary yard moved the user's yard for good.
    Anything that saves settings must start from this.
    """
    cfg = dict(DEFAULTS)
    path = config_file()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception:
            pass
    return cfg


def load() -> dict:
    """Stored settings plus this process's environment overrides."""
    cfg = load_stored()
    if os.environ.get(ENV_ROOT):
        cfg["root"] = os.environ[ENV_ROOT]
    if os.environ.get(ENV_THEME):
        cfg["theme"] = os.environ[ENV_THEME]
    if os.environ.get("NO_COLOR") is not None:
        cfg["color"] = False
    return cfg


def save(cfg: dict) -> Path:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items() if k in DEFAULTS}
    path.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def coerce(key: str, value: str):
    """Turn a command-line string into the right type for a config key."""
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        low = str(value).strip().lower()
        if low in ("1", "true", "yes", "on", "y"):
            return True
        if low in ("0", "false", "no", "off", "n"):
            return False
        raise VenvyardError(
            f"{key} expects a boolean (true/false), got {value!r}")
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except ValueError:
            raise VenvyardError(
                f"{key} expects a whole number, got {value!r}") from None
    if isinstance(default, list):
        return [p.strip() for p in str(value).split(",") if p.strip()]
    return str(value)


def root_path(cfg: dict) -> Path:
    return Path(os.path.expanduser(str(cfg.get("root", DEFAULTS["root"])))).resolve()
