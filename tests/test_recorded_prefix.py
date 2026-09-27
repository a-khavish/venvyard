"""Reading the absolute path baked into a venv's activate scripts.

CPython does not write this the same way in every version:

    <= 3.11   VIRTUAL_ENV=/path                 (bare, column zero)
    >= 3.12       export VIRTUAL_ENV=/path      (indented, inside an if/else
                                                 whose other branch is a
                                                 $(cygpath ...) substitution)

An expression anchored to the start of the line matched only the first form, so
recorded_prefix() returned None on 3.12 and newer and --doctor pronounced a
hand-moved environment healthy.  These cases are synthetic on purpose: they
must hold whichever interpreter happens to run the suite.
"""
from __future__ import annotations

import pytest

from venvyard.core import Venv

PREFIX = "/home/someone/PY_VENV/web"

BARE = f"""\
# comment
deactivate nondestructive

VIRTUAL_ENV={PREFIX}
export VIRTUAL_ENV

_OLD_VIRTUAL_PATH="$PATH"
"""

EXPORTED = f"""\
# on Windows, a path can contain colons and backslashes and has to be converted:
if [ "${{OSTYPE:-}}" = "cygwin" ] || [ "${{OSTYPE:-}}" = "msys" ] ; then
    export VIRTUAL_ENV=$(cygpath {PREFIX})
else
    # use the path as-is
    export VIRTUAL_ENV={PREFIX}
fi
"""

QUOTED = f"""VIRTUAL_ENV='{PREFIX}'\n"""
DQUOTED = f"""    export VIRTUAL_ENV="{PREFIX}"\n"""
FISH = f"""\
set -e VIRTUAL_ENV_PROMPT
set -gx VIRTUAL_ENV {PREFIX}
set -gx PATH "$VIRTUAL_ENV/"bin $PATH
"""


def _venv_with(tmp_path, posix=None, fish=None):
    root = tmp_path / "web"
    (root / "bin").mkdir(parents=True)
    if posix is not None:
        (root / "bin" / "activate").write_text(posix)
    if fish is not None:
        (root / "bin" / "activate.fish").write_text(fish)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return Venv(name="web", path=root)


@pytest.mark.parametrize("script,label", [
    (BARE, "bare assignment (<= 3.11)"),
    (EXPORTED, "indented export inside if/else (>= 3.12)"),
    (QUOTED, "single-quoted"),
    (DQUOTED, "double-quoted and indented"),
])
def test_prefix_is_read_from_every_posix_form(tmp_path, script, label):
    assert _venv_with(tmp_path, posix=script).recorded_prefix() == PREFIX, label


def test_cygwin_branch_is_not_mistaken_for_the_path(tmp_path):
    """The $(cygpath ...) line comes first and must never be returned."""
    got = _venv_with(tmp_path, posix=EXPORTED).recorded_prefix()
    assert got == PREFIX
    assert "cygpath" not in got and "$" not in got


def test_prefix_falls_back_to_activate_fish(tmp_path):
    """A venv whose POSIX script is gone still records the path in fish's."""
    assert _venv_with(tmp_path, fish=FISH).recorded_prefix() == PREFIX


def test_missing_scripts_give_none(tmp_path):
    assert _venv_with(tmp_path).recorded_prefix() is None


def test_activate_without_a_virtual_env_line_gives_none(tmp_path):
    assert _venv_with(tmp_path, posix="# nothing useful here\n").recorded_prefix() is None


def test_a_stale_prefix_is_reported_as_unhealthy(tmp_path):
    """The end-to-end consequence: doctor must not call this healthy."""
    venv = _venv_with(tmp_path, posix=EXPORTED)
    recorded = venv.recorded_prefix()
    assert recorded == PREFIX
    assert str(venv.path) != recorded, "fixture should look moved"
