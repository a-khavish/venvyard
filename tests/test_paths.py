"""Absolute-path rewriting on rename.

A virtual environment has its own path written into pyvenv.cfg, bin/activate
and the shebang of every console script.  This is why `mv` breaks one, and it
is the single most important thing venvyard does, so it is tested against a
real environment rather than a fixture.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow


@pytest.fixture
def real_venv(yard):
    """A genuine venv in the temporary yard, built without pip for speed."""
    venv = yard.create("original", upgrade_pip=False, without_pip=True)
    return venv


def test_rename_moves_the_directory(yard, real_venv):
    yard.rename("original", "renamed")
    assert (yard.root / "renamed").is_dir()
    assert not (yard.root / "original").exists()


def test_rename_rewrites_pyvenv_cfg(yard, real_venv):
    """Only 3.11+ records the venv path in pyvenv.cfg, via `command =`."""
    before = (yard.root / "original" / "pyvenv.cfg").read_text()
    mentioned_before = str(yard.root / "original") in before
    yard.rename("original", "renamed")
    cfg = (yard.root / "renamed" / "pyvenv.cfg").read_text()
    assert str(yard.root / "original") not in cfg
    if mentioned_before:
        assert str(yard.root / "renamed") in cfg
    else:
        pytest.skip("this Python does not write the venv path into pyvenv.cfg")


def test_rename_rewrites_the_posix_activate_script(yard, real_venv):
    yard.rename("original", "renamed")
    text = (yard.root / "renamed" / "bin" / "activate").read_text()
    assert str(yard.root / "original") not in text
    assert str(yard.root / "renamed") in text


def test_rename_rewrites_the_fish_activate_script(yard, real_venv):
    """activate.fish carries the same absolute path and is easy to forget."""
    fish = yard.root / "renamed" / "bin" / "activate.fish"
    yard.rename("original", "renamed")
    if not fish.is_file():
        pytest.skip("this Python's venv module did not write activate.fish")
    text = fish.read_text()
    assert str(yard.root / "original") not in text
    assert str(yard.root / "renamed") in text


def test_the_interpreter_still_runs_after_a_rename(yard, real_venv):
    """The point of the rewriting: the environment keeps working."""
    yard.rename("original", "renamed")
    python = yard.root / "renamed" / "bin" / "python"
    done = subprocess.run([str(python), "-c", "import sys; print(sys.prefix)"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(yard.root / "renamed")


def test_doctor_reports_a_healthy_environment_after_rename(yard, real_venv):
    yard.rename("original", "renamed")
    venv = yard.get("renamed")
    healthy, problems = venv.health()
    assert healthy, f"doctor found problems after a clean rename: {problems}"


def test_doctor_spots_an_environment_moved_by_hand(yard, real_venv):
    """`mv` behind venvyard's back is exactly what --repair exists for."""
    (yard.root / "original").rename(yard.root / "moved")
    venv = yard.get("moved")
    healthy, problems = venv.health()
    assert not healthy and problems


def test_repair_fixes_an_environment_moved_by_hand(yard, real_venv):
    (yard.root / "original").rename(yard.root / "moved")
    # Assert the breakage is visible first, so this cannot pass merely because
    # doctor failed to notice anything was wrong.
    before_healthy, before_problems = yard.get("moved").health()
    assert not before_healthy and before_problems, "the move was not detected at all"
    yard.repair("moved")
    healthy, problems = yard.get("moved").health()
    assert healthy, f"repair left problems behind: {problems}"


def test_repair_clears_the_stale_prefix_from_activate(yard, real_venv):
    """The concrete outcome, whichever form this Python writes activate in."""
    old_path = str(yard.root / "original")
    (yard.root / "original").rename(yard.root / "moved")
    venv = yard.get("moved")
    assert venv.recorded_prefix() == old_path
    yard.repair("moved")
    assert yard.get("moved").recorded_prefix() == str(yard.root / "moved")
    assert old_path not in (yard.root / "moved" / "bin" / "activate").read_text()
