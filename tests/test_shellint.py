"""Shell integration and completion output, per shell.

Every bug this file guards against was the same mistake: a fish user handed
POSIX syntax.  It has happened in the integration snippet, in the installer's
PATH stanza, in the completion script and in the "integration is not loaded"
advice, so each shell's output is checked for its own syntax here -- and, when
that shell is installed, actually parsed by it.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from venvyard.shellint import MARK_BEGIN, MARK_END, block, completion, integration

POSIX_ONLY = ('export ', 'case "', 'COMPREPLY', 'compgen', '$(')
FISH_ONLY = ("set -gx", "function ", "end")


# ---------------------------------------------------------------- integration

@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_posix_integration_uses_posix_syntax(shell):
    out = integration(shell)
    assert "export VENVYARD_SHELL_INTEGRATION=1" in out
    assert "set -gx" not in out


def test_fish_integration_uses_fish_syntax():
    out = integration("fish")
    assert "set -gx VENVYARD_SHELL_INTEGRATION 1" in out
    assert "set -gx VENVYARD_SHELL fish" in out
    for token in ("export ", 'case "', "esac"):
        assert token not in out, f"POSIX token {token!r} leaked into the fish integration"


def test_fish_integration_sources_the_fish_activate_script():
    """It must not source the POSIX bin/activate, which fish cannot parse."""
    out = integration("fish")
    assert "--_shell-eval" in out
    assert "string join" in out  # rejoins the captured lines before eval


def _code_lines(text):
    """Drop comments, so prose about an old bug cannot satisfy an assertion."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_fish_integration_captures_the_command_substitution_status():
    """`set` succeeds whatever the substitution did, so $status must be saved."""
    code = _code_lines(integration("fish"))
    assert "set -l __vy_status $status" in code
    # The old form relied on `set` failing, which it never does.
    assert "or return $status" not in code


def test_integration_scans_every_argument_not_just_the_first():
    """`vy -q -a web` and `vy --root DIR -a web` are ordinary usage."""
    for shell in ("bash", "fish"):
        out = integration(shell)
        assert "--activate" in out and "--deactivate" in out
        assert "for " in out  # a loop over the arguments, not a test of $1


def test_unknown_shell_falls_back_to_posix():
    assert integration("nushell") == integration("bash")


def test_block_is_wrapped_in_markers():
    out = block("fish")
    assert out.startswith(MARK_BEGIN)
    assert out.rstrip().endswith(MARK_END)
    assert integration("fish").strip() in out


# ----------------------------------------------------------------- completion

def test_bash_completion_is_bash():
    out = completion("bash")
    assert "COMPREPLY" in out and "complete -F" in out


def test_zsh_completion_is_zsh():
    out = completion("zsh")
    assert "compdef" in out
    assert "COMPREPLY" not in out


def test_fish_completion_is_fish_not_bash():
    """`--completion fish` used to silently hand back the bash script."""
    out = completion("fish")
    assert "complete -c" in out
    for token in ("COMPREPLY", "compgen", "complete -F", "${COMP_WORDS"):
        assert token not in out, f"bash token {token!r} leaked into the fish completion"


def test_fish_completion_differs_from_bash():
    assert completion("fish") != completion("bash")


def test_fish_completion_offers_environment_names_for_name_operands():
    """-x without -a completes nothing, so name commands must supply names."""
    out = completion("fish")
    assert "__venvyard_names" in out
    assert "-l activate -s a -x -a '(__venvyard_names)'" in out


def test_fish_completion_offers_files_for_path_commands():
    out = completion("fish")
    assert "-l import -r -F" in out
    assert "-l scan -r -F" in out


def test_every_completion_advertises_only_shells_it_can_emit():
    """The suggestion list must not offer a shell the generator cannot produce."""
    from venvyard.registry import COMMANDS
    advertised = {c.args for c in COMMANDS if c.long == "--completion"}.pop()
    for shell in ("bash", "zsh", "fish"):
        if shell in advertised:
            out = completion(shell)
            assert out.strip(), f"--completion advertises {shell} but emits nothing"


# -------------------------------------------------- parsed by the real shells

@pytest.mark.parametrize("shell,binary,flag", [
    ("bash", "bash", "-n"),
    ("zsh", "zsh", "-n"),
    ("fish", "fish", "-n"),
])
@pytest.mark.parametrize("producer", [integration, completion])
def test_output_parses_under_its_own_shell(shell, binary, flag, producer, tmp_path):
    exe = shutil.which(binary)
    if not exe:
        pytest.skip(f"{binary} is not installed")
    if producer is completion and shell == "zsh":
        pytest.skip("zsh completion needs compinit, which -n does not run")
    script = tmp_path / f"snippet.{shell}"
    script.write_text(producer(shell))
    done = subprocess.run([exe, flag, str(script)], capture_output=True, text=True)
    assert done.returncode == 0, f"{binary} rejected its own snippet:\n{done.stderr}"
