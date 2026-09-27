"""The installer's effect on shell startup files.

Re-running the installer must leave the rc files exactly as the first run did.
It used to add one blank line per run, because the block it strips left the
blank line in front of it behind and a fresh one was prepended each time.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"

RC_FILES = (".bashrc", ".zshrc", ".config/fish/config.fish")
OWN_CONTENT = "# my own settings\nexport EDITOR=vim\n"


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "fish").mkdir(parents=True)
    for rc in RC_FILES:
        (home / rc).write_text(OWN_CONTENT)
    return home


def _install(home, prefix, *extra):
    done = subprocess.run(
        ["bash", str(INSTALLER), "--prefix", str(prefix), "-q", *extra],
        capture_output=True, text=True, cwd=ROOT,
        env={"HOME": str(home), "SHELL": "/bin/bash", "PATH": "/usr/bin:/bin",
             "VENVYARD_HOME": str(home / "PY_VENV")},
    )
    assert done.returncode == 0, done.stderr or done.stdout
    return done


def test_reinstalling_does_not_change_the_rc_files(fake_home, tmp_path):
    prefix = tmp_path / "prefix"
    _install(fake_home, prefix)
    first = {rc: (fake_home / rc).read_bytes() for rc in RC_FILES}
    for _ in range(4):
        _install(fake_home, prefix)
    for rc in RC_FILES:
        assert (fake_home / rc).read_bytes() == first[rc], (
            f"{rc} drifted across reinstalls")


def test_exactly_one_integration_block_per_rc(fake_home, tmp_path):
    prefix = tmp_path / "prefix"
    for _ in range(3):
        _install(fake_home, prefix)
    for rc in RC_FILES:
        text = (fake_home / rc).read_text()
        assert text.count("# >>> venvyard shell integration >>>") == 1, rc
        assert text.count("# <<< venvyard shell integration <<<") == 1, rc


def test_the_users_own_rc_content_survives(fake_home, tmp_path):
    prefix = tmp_path / "prefix"
    _install(fake_home, prefix)
    for rc in RC_FILES:
        assert OWN_CONTENT in (fake_home / rc).read_text(), rc


def test_uninstall_removes_every_trace(fake_home, tmp_path):
    prefix = tmp_path / "prefix"
    _install(fake_home, prefix)
    _install(fake_home, prefix, "--uninstall")
    for rc in RC_FILES:
        text = (fake_home / rc).read_text()
        assert "venvyard" not in text.lower(), f"{rc} still mentions venvyard"
        assert OWN_CONTENT in text, f"{rc} lost the user's own content"
    assert not (prefix / "bin" / "venvyard").exists()


@pytest.mark.parametrize("rc,binary", [
    (".bashrc", "bash"), (".zshrc", "zsh"), (".config/fish/config.fish", "fish"),
])
def test_each_rc_still_parses_under_its_shell(fake_home, tmp_path, rc, binary):
    exe = shutil.which(binary)
    if not exe:
        pytest.skip(f"{binary} is not installed")
    _install(fake_home, tmp_path / "prefix")
    done = subprocess.run([exe, "-n", str(fake_home / rc)],
                          capture_output=True, text=True)
    assert done.returncode == 0, f"{binary} rejected {rc}:\n{done.stderr}"
