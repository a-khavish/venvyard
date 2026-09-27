"""Shell integration and completion scripts.

A child process cannot change its parent shell's environment, so activating
a virtual environment from a tool requires a shell function that evaluates
what the tool prints.  The installer writes this into the user's rc file.
"""
from __future__ import annotations

MARK_BEGIN = "# >>> venvyard shell integration >>>"
MARK_END = "# <<< venvyard shell integration <<<"

BASH_ZSH = r'''
# venvyard needs a shell function for --activate / --deactivate, because a
# child process cannot modify the shell that launched it.  Everything else
# is passed straight through to the real program.
venvyard() {
    local __vy_arg __vy_hit=0
    # Scan every argument, not just the first: "vy -q -a web" and
    # "vy --root DIR -a web" are ordinary usage, and matching only $1 sent
    # them down the plain path, where venvyard then reported that the shell
    # integration was not loaded.  Stop at "--", past which the words belong
    # to a command being run inside an environment.
    for __vy_arg in "$@"; do
        case "$__vy_arg" in
            --) break ;;
            -a|--activate|-D|--deactivate) __vy_hit=1; break ;;
        esac
    done
    if [ "$__vy_hit" -eq 1 ]; then
        local __vy_code __vy_status
        __vy_code="$(command venvyard --_shell-eval "$@")"
        __vy_status=$?
        if [ $__vy_status -ne 0 ]; then
            return $__vy_status
        fi
        eval "$__vy_code"
    else
        command venvyard "$@"
    fi
}
vy() { venvyard "$@"; }
export VENVYARD_SHELL_INTEGRATION=1
export VENVYARD_SHELL=posix
'''

FISH = r'''
# venvyard needs a shell function for --activate / --deactivate, because a
# child process cannot modify the shell that launched it.
function venvyard
    set -l __vy_hit 0
    for __vy_arg in $argv
        switch $__vy_arg
            case --
                break
            case -a --activate -D --deactivate
                set __vy_hit 1
                break
        end
    end
    if test $__vy_hit -eq 1
        set -l __vy_code (command venvyard --_shell-eval $argv)
        set -l __vy_status $status
        # "set" succeeds whatever the command substitution did, so the status
        # has to be captured and tested; "or return $status" never fired.
        if test $__vy_status -ne 0
            return $__vy_status
        end
        eval (string join \n $__vy_code)
    else
        command venvyard $argv
    end
end
function vy
    venvyard $argv
end
set -gx VENVYARD_SHELL_INTEGRATION 1
set -gx VENVYARD_SHELL fish
'''


def integration(shell: str = "bash") -> str:
    shell = (shell or "bash").lower()
    if "fish" in shell:
        return FISH.strip() + "\n"
    return BASH_ZSH.strip() + "\n"


def block(shell: str = "bash") -> str:
    return f"{MARK_BEGIN}\n{integration(shell)}{MARK_END}\n"


BASH_COMPLETION = r'''
_venvyard_complete() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    local flags="__FLAGS__"
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return 0
    fi
    case "$prev" in
        --theme) COMPREPLY=( $(compgen -W "default ocean sunset matrix mono" -- "$cur") ); return 0 ;;
        --sort)  COMPREPLY=( $(compgen -W "name size python created used packages" -- "$cur") ); return 0 ;;
        --shell-init|--completion) COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") ); return 0 ;;
        -r|--requirements|-o|--output|--from-export|--root|--import) COMPREPLY=( $(compgen -f -- "$cur") ); return 0 ;;
    esac
    local names
    names="$(command venvyard --_names 2>/dev/null)"
    local IFS=$'\n'
    COMPREPLY=( $(compgen -W "$names" -- "$cur") )
}
complete -F _venvyard_complete venvyard
complete -F _venvyard_complete vy
'''

ZSH_COMPLETION = r'''
_venvyard() {
    local -a flags names
    flags=(__FLAGS__)
    if [[ "$words[CURRENT]" == -* ]]; then
        compadd -- $flags
        return
    fi
    names=(${(f)"$(command venvyard --_names 2>/dev/null)"})
    compadd -- $names
}
compdef _venvyard venvyard vy
'''


FISH_COMPLETION = r'''
# venvyard completions for fish.
#
# fish has its own completion engine; the bash script is not valid fish, so
# this is generated separately from the same command registry.

function __venvyard_names
    command venvyard --_names 2>/dev/null
end

for __vy in venvyard vy
    # Operands are environment names, not filenames.
    complete -c $__vy -f
    complete -c $__vy -a '(__venvyard_names)' -d Environment

__BODY__
end
set -e __vy
'''


def completion(shell: str = "bash") -> str:
    from .registry import COMMANDS, OPTIONS
    flags = []
    for c in COMMANDS:
        flags.append(c.long)
        if c.short:
            flags.append(c.short)
        flags.extend(c.aliases)
    for o in OPTIONS:
        flags.append(o.long)
        if o.short:
            flags.append(o.short)
    joined = " ".join(sorted(set(flags)))
    name = (shell or "").lower()
    if "fish" in name:
        return FISH_COMPLETION.strip().replace(
            "__BODY__", _fish_body(COMMANDS, OPTIONS)) + "\n"
    template = ZSH_COMPLETION if "zsh" in name else BASH_COMPLETION
    return template.strip().replace("__FLAGS__", joined) + "\n"


# Options whose value is a path, so fish should offer files again for them.
_FISH_FILE_ARGS = {"--requirements", "--output", "--from-export"}
_FISH_DIR_ARGS = {"--root"}
# Commands whose operands are paths rather than environment names.
_FISH_PATH_CMDS = {"--import", "--scan"}
_FISH_CHOICES = {
    "--theme": "default ocean sunset matrix mono",
    "--sort": "name size python created used packages",
    "--shell-init": "bash zsh fish",
    "--completion": "bash zsh fish",
}


def _fish_quote(text: str) -> str:
    """Single-quote for fish, which only escapes \\ and ' inside '...'."""
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fish_body(commands, options) -> str:
    """Build one `complete` line per flag, from the registry.

    fish resolves the token after an option as that option's argument, so a
    command declared with -x and no -a completes nothing at all.  Commands
    whose operands are environment names therefore have to say so.
    """
    lines = []

    def emit(long, short, summary, takes_arg, kind=""):
        parts = ["    complete -c $__vy", "-l " + long.lstrip("-")]
        if short:
            parts.append("-s " + short.lstrip("-"))
        if long in _FISH_CHOICES:
            parts.append("-x -a " + _fish_quote(_FISH_CHOICES[long]))
        elif kind == "file":
            parts.append("-r -F")
        elif kind == "dir":
            parts.append("-x -a '(__fish_complete_directories)'")
        elif kind == "name":
            parts.append("-x -a '(__venvyard_names)'")
        elif takes_arg:
            parts.append("-x")
        if summary:
            parts.append("-d " + _fish_quote(summary))
        lines.append(" ".join(parts))

    for c in commands:
        if c.long in _FISH_PATH_CMDS:
            kind = "file"
        elif "NAME" in c.args or "OLD" in c.args:
            kind = "name"
        else:
            kind = ""
        emit(c.long, c.short, c.summary, bool(c.args), kind)
        for alias in c.aliases:
            emit(alias, "", c.summary, bool(c.args), kind)

    for o in options:
        kind = ("file" if o.long in _FISH_FILE_ARGS
                else "dir" if o.long in _FISH_DIR_ARGS else "")
        emit(o.long, o.short, o.summary, bool(o.arg), kind)

    return "\n".join(lines)
