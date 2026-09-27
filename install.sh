#!/usr/bin/env bash
#
# venvyard installer.  Unzip, run ./install.sh, done.
#
#   ./install.sh                 install for the current user
#   ./install.sh --system        install for everyone (needs sudo)
#   ./install.sh --prefix DIR    install somewhere specific
#   ./install.sh --no-shell      skip touching shell startup files
#   ./install.sh --quiet         install with minimal output (-q too)
#   ./install.sh --uninstall     remove everything this script installed
#
set -u

TOOL="venvyard"
ALIAS="vy"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX=""
SYSTEM=0
NO_SHELL=0
UNINSTALL=0
QUIET=0

# ---------------------------------------------------------------- appearance
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'
    OK=$'\033[92m'; WARN=$'\033[93m'; ERR=$'\033[91m'
    CY=$'\033[96m'; MA=$'\033[95m'; YE=$'\033[93m'
else
    B=""; D=""; R=""; OK=""; WARN=""; ERR=""; CY=""; MA=""; YE=""
fi

say()  { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }
ok()   { say "  ${OK}✔${R} $*"; }
warn() { say "  ${WARN}▲${R} $*"; }
die()  { printf '  %s✘%s %s\n' "$ERR" "$R" "$*" >&2; exit 1; }
step() { say ""; say "${B}${CY}$*${R}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --system)     SYSTEM=1; shift ;;
        --prefix)
            [ $# -ge 2 ] || die "--prefix needs a directory"
            PREFIX="$2"; shift 2 ;;
        --prefix=*)   PREFIX="${1#*=}"; shift ;;
        --no-shell)   NO_SHELL=1; shift ;;
        --uninstall)  UNINSTALL=1; shift ;;
        --quiet|-q)   QUIET=1; shift ;;
        -h|--help)
            # Print the leading comment block, whatever length it grows to,
            # rather than a fixed line range that overshoots into the code.
            awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
            exit 0 ;;
        *) die "unknown option $1  (try --help)" ;;
    esac
done

if [ -n "$PREFIX" ]; then
    BIN_DIR="$PREFIX/bin"
    LIB_DIR="$PREFIX/share/$TOOL"
elif [ "$SYSTEM" = 1 ]; then
    BIN_DIR="/usr/local/bin"
    LIB_DIR="/usr/local/share/$TOOL"
else
    BIN_DIR="$HOME/.local/bin"
    LIB_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$TOOL"
fi

SUDO=""
if [ "$SYSTEM" = 1 ] && [ "$(id -u)" != "0" ]; then
    command -v sudo >/dev/null 2>&1 || die "--system needs root; install sudo or run as root"
    SUDO="sudo"
fi

MARK_BEGIN="# >>> venvyard shell integration >>>"
MARK_END="# <<< venvyard shell integration <<<"

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
    step "Removing venvyard"
    $SUDO rm -f  "$BIN_DIR/$TOOL" "$BIN_DIR/$ALIAS" && ok "removed the commands from $BIN_DIR"
    $SUDO rm -rf "$LIB_DIR"                          && ok "removed $LIB_DIR"
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.config/fish/config.fish"; do
        [ -f "$rc" ] || continue
        if grep -qF "$MARK_BEGIN" "$rc" 2>/dev/null; then
            tmp="$(mktemp)"
            awk -v a="$MARK_BEGIN" -v b="$MARK_END" '
                index($0,a){skip=1} !skip{print} index($0,b){skip=0}' "$rc" > "$tmp"
            cat "$tmp" > "$rc" && rm -f "$tmp"
            ok "removed the shell integration from $rc"
        fi
    done
    rm -f "$HOME/.local/share/bash-completion/completions/$TOOL" 2>/dev/null
    say ""
    say "  ${D}Your environments in PY_VENV were left exactly where they are.${R}"
    say "  ${D}Delete them yourself if you want them gone.${R}"
    say ""
    exit 0
fi

# ---------------------------------------------------------------- banner
say ""
say "  ${B}${CY}venvyard${R} ${D}- every virtual environment, in one yard${R}"
say "  ${D}────────────────────────────────────────────────${R}"

# ---------------------------------------------------------------- checks
step "Checking this machine"

# Work out which distribution this is, so any advice we give is the right
# advice.  This all has to work before Python exists, so it is pure shell.
DISTRO_ID=""; DISTRO_NAME=""; DISTRO_LIKE=""; PKG=""
for osr in /etc/os-release /usr/lib/os-release; do
    [ -r "$osr" ] || continue
    DISTRO_ID="$(. "$osr" 2>/dev/null; printf '%s' "${ID:-}")"
    DISTRO_NAME="$(. "$osr" 2>/dev/null; printf '%s' "${PRETTY_NAME:-${NAME:-}}")"
    DISTRO_LIKE="$(. "$osr" 2>/dev/null; printf '%s' "${ID_LIKE:-}")"
    break
done
case " $DISTRO_ID $DISTRO_LIKE " in
    *debian*|*ubuntu*|*mint*|*pop*|*raspbian*) PKG=apt ;;
    *fedora*|*rhel*|*centos*|*rocky*|*alma*)   PKG=dnf ;;
    *arch*|*manjaro*)                          PKG=pacman ;;
    *suse*)                                    PKG=zypper ;;
    *alpine*)                                  PKG=apk ;;
    *) for m in apt dnf pacman zypper apk; do
           command -v "$m" >/dev/null 2>&1 && { PKG="$m"; break; }
       done ;;
esac
[ -n "$DISTRO_NAME" ] || DISTRO_NAME="this system"

py_install_cmd() {
    case "$PKG" in
        apt)    printf 'sudo apt update && sudo apt install -y python3 python3-venv python3-pip' ;;
        dnf)    printf 'sudo dnf install -y python3 python3-pip' ;;
        pacman) printf 'sudo pacman -S --needed python python-pip' ;;
        zypper) printf 'sudo zypper install -y python3 python3-pip' ;;
        apk)    printf 'sudo apk add python3 py3-pip' ;;
        *)      printf '' ;;
    esac
}
venv_install_cmd() {
    case "$PKG" in
        apt)    printf 'sudo apt install -y python3-venv' ;;
        dnf)    printf 'sudo dnf install -y python3-libs' ;;
        pacman) printf 'sudo pacman -S --needed python' ;;
        zypper) printf 'sudo zypper install -y python3' ;;
        apk)    printf 'sudo apk add python3' ;;
        *)      printf '' ;;
    esac
}

find_python() {
    PY=""
    for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10 \
                python3.9 python3.8 python; do
        command -v "$cand" >/dev/null 2>&1 || continue
        if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            PY="$(command -v "$cand")"
            return 0
        fi
    done
    return 1
}

offer_to_run() {
    # $1 = the command, $2 = what it is for
    cmd="$1"; what="$2"
    [ -n "$cmd" ] || return 1
    say ""
    say "  ${B}To $what, run:${R}"
    say ""
    say "      ${CY}${cmd}${R}"
    say ""
    if [ ! -t 0 ]; then
        say "  ${D}(not an interactive terminal, so nothing was run for you)${R}"
        return 1
    fi
    printf '  %s?%s Run that now? It needs your sudo password. [y/N] ' "$YE" "$R"
    read -r reply </dev/tty || reply=""
    case "$reply" in
        y|Y|yes|YES)
            say ""
            sh -c "$cmd" || { say ""; warn "that did not finish cleanly"; return 1; }
            say ""
            return 0 ;;
        *) return 1 ;;
    esac
}

if ! find_python; then
    say ""
    say "  ${ERR}✘${R} ${B}No Python 3.8 or newer was found on this machine.${R}"
    say ""
    say "  ${D}venvyard is written in Python and manages Python environments,${R}"
    say "  ${D}so it needs Python before it can do anything at all.${R}"
    say "  ${D}Detected system: ${R}${DISTRO_NAME}"
    if offer_to_run "$(py_install_cmd)" "install Python"; then
        if find_python; then
            ok "Python is now installed"
        else
            die "Python still cannot be found. Open a new terminal and run ./install.sh again."
        fi
    else
        say "  ${D}Install Python, then run ${R}${CY}./install.sh${R}${D} again.${R}"
        say ""
        exit 1
    fi
fi
ok "Python $("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])') at $PY"

if ! "$PY" -c 'import venv' 2>/dev/null; then
    warn "this Python has no venv module, which venvyard needs"
    if offer_to_run "$(venv_install_cmd)" "add venv support"; then
        "$PY" -c 'import venv' 2>/dev/null || die "the venv module is still missing"
        ok "venv module is now available"
    else
        die "venvyard cannot work without the venv module"
    fi
fi
if ! "$PY" -c 'import ensurepip' 2>/dev/null; then
    warn "the venv module is present but ensurepip is missing, so new environments"
    warn "will have no pip. On Debian/Ubuntu:  sudo apt install python3-venv"
else
    ok "venv and pip support are available"
fi

[ -f "$SRC/venvyard/cli.py" ] || die "run this from the unzipped folder (venvyard/cli.py not found next to install.sh)"
ok "source files found"

# ---------------------------------------------------------------- install
step "Installing"

$SUDO mkdir -p "$BIN_DIR" "$LIB_DIR" || die "cannot create $BIN_DIR or $LIB_DIR"
$SUDO rm -rf "$LIB_DIR/venvyard"
$SUDO cp -R "$SRC/venvyard" "$LIB_DIR/venvyard" || die "could not copy the package to $LIB_DIR"
for extra in README.md LICENSE; do
    [ -f "$SRC/$extra" ] && $SUDO cp "$SRC/$extra" "$LIB_DIR/" 2>/dev/null
done
$SUDO find "$LIB_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
ok "package installed in $LIB_DIR"

LAUNCHER="$(mktemp)"
cat > "$LAUNCHER" <<LAUNCHEOF
#!/usr/bin/env bash
# venvyard launcher - written by install.sh at install time
VENVYARD_LIB="$LIB_DIR"
VENVYARD_PY="$PY"

# If the interpreter venvyard was installed with is ever removed or upgraded
# away, fall back to any other suitable Python rather than failing obscurely.
if [ ! -x "\$VENVYARD_PY" ]; then
    VENVYARD_PY=""
    for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10 \\
                python3.9 python3.8 python; do
        command -v "\$cand" >/dev/null 2>&1 || continue
        if "\$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            VENVYARD_PY="\$(command -v "\$cand")"
            break
        fi
    done
fi

if [ -z "\$VENVYARD_PY" ] || [ ! -x "\$VENVYARD_PY" ]; then
    echo "venvyard: no Python 3.8 or newer could be found on this machine." >&2
    echo "          venvyard is written in Python, so it cannot run without one." >&2
    echo "          Install Python 3, then run venvyard again." >&2
    exit 127
fi

export PYTHONPATH="\$VENVYARD_LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\$VENVYARD_PY" -m venvyard "\$@"
LAUNCHEOF
$SUDO cp "$LAUNCHER" "$BIN_DIR/$TOOL" || die "could not write $BIN_DIR/$TOOL"
$SUDO chmod 755 "$BIN_DIR/$TOOL" || die "could not make $BIN_DIR/$TOOL executable"
rm -f "$LAUNCHER"
ok "command installed: $BIN_DIR/$TOOL"

$SUDO ln -sf "$BIN_DIR/$TOOL" "$BIN_DIR/$ALIAS" || die "could not create $BIN_DIR/$ALIAS"
ok "short alias installed: $BIN_DIR/$ALIAS"

# ---------------------------------------------------------------- yard
YARD="${VENVYARD_HOME:-$HOME/PY_VENV}"
if [ ! -d "$YARD" ]; then
    mkdir -p "$YARD" && ok "created the yard at $YARD"
else
    ok "the yard already exists at $YARD"
fi

# ---------------------------------------------------------------- PATH
step "Wiring up your shell"

case ":$PATH:" in
    *":$BIN_DIR:"*) ok "$BIN_DIR is already on your PATH" ; PATH_OK=1 ;;
    *)              PATH_OK=0 ;;
esac

add_block() {
    rc="$1"; shell="$2"
    [ -e "$rc" ] || : > "$rc"
    if grep -qF "$MARK_BEGIN" "$rc" 2>/dev/null; then
        tmp="$(mktemp)"
        # Drop the old block, then any blank lines it left at the end of the
        # file.  Without that second pass the leading newline below was added
        # afresh on every reinstall, so the rc file grew a blank line each time.
        awk -v a="$MARK_BEGIN" -v b="$MARK_END" '
            index($0,a){skip=1} !skip{print} index($0,b){skip=0}' "$rc" \
        | awk '{ if (NF==0) { held++; next }
                 while (held>0) { print ""; held-- }
                 print }' > "$tmp"
        cat "$tmp" > "$rc"; rm -f "$tmp"
    fi
    {
        printf '\n%s\n' "$MARK_BEGIN"
        if [ "$PATH_OK" = 0 ] && [ "$SYSTEM" = 0 ]; then
            # fish has neither "case" outside switch nor "export", so the
            # POSIX stanza turned every new fish shell into an error message.
            if [ "$shell" = fish ]; then
                printf 'if not contains %s $PATH\n    set -gx PATH %s $PATH\nend\n' \
                    "$BIN_DIR" "$BIN_DIR"
            else
                printf 'case ":$PATH:" in *":%s:"*) ;; *) export PATH="%s:$PATH" ;; esac\n' \
                    "$BIN_DIR" "$BIN_DIR"
            fi
        fi
        "$PY" -c "import sys; sys.path.insert(0,'$LIB_DIR'); from venvyard import shellint; print(shellint.integration('$shell'), end='')"
        printf '%s\n' "$MARK_END"
    } >> "$rc"
    ok "shell integration added to $rc"
}

if [ "$NO_SHELL" = 1 ]; then
    warn "skipped shell startup files (--no-shell)"
    warn "--activate will not work until you add:  eval \"\$($TOOL --shell-init bash)\""
else
    TOUCHED=0
    [ -f "$HOME/.bashrc" ] && { add_block "$HOME/.bashrc" bash; TOUCHED=1; }
    [ -f "$HOME/.zshrc" ]  && { add_block "$HOME/.zshrc"  zsh;  TOUCHED=1; }
    if [ -f "$HOME/.config/fish/config.fish" ]; then
        add_block "$HOME/.config/fish/config.fish" fish; TOUCHED=1
    fi
    # Only existing rc files were patched, so someone whose login shell has
    # never been configured got the integration written where their shell
    # would not read it.  Create the one their $SHELL actually uses.
    LOGIN_SHELL="$(basename "${SHELL:-}" 2>/dev/null || true)"
    case "$LOGIN_SHELL" in
        zsh)  [ -f "$HOME/.zshrc" ] || { add_block "$HOME/.zshrc" zsh; TOUCHED=1; } ;;
        fish) if [ ! -f "$HOME/.config/fish/config.fish" ] \
                   && mkdir -p "$HOME/.config/fish" 2>/dev/null; then
                  add_block "$HOME/.config/fish/config.fish" fish; TOUCHED=1
              fi ;;
    esac
    if [ "$TOUCHED" = 0 ]; then
        add_block "$HOME/.bashrc" bash
    fi
fi

COMPDIR="$HOME/.local/share/bash-completion/completions"
if mkdir -p "$COMPDIR" 2>/dev/null; then
    if PYTHONPATH="$LIB_DIR" "$PY" -m venvyard --completion bash > "$COMPDIR/$TOOL" 2>/dev/null; then
        ok "tab completion installed"
    fi
fi

# ---------------------------------------------------------------- verify
step "Checking it works"

# Check the command that was actually installed.  Testing the module through
# PYTHONPATH passed even when the copy to $BIN_DIR had failed, so the script
# reported success for a venvyard the user did not have.
if [ -x "$BIN_DIR/$TOOL" ] && "$BIN_DIR/$TOOL" --version >/dev/null 2>&1; then
    VER="$("$BIN_DIR/$TOOL" --version 2>/dev/null | head -1)"
    ok "venvyard responds: $(printf '%s' "$VER" | sed 's/\x1b\[[0-9;]*m//g')"
else
    die "$BIN_DIR/$TOOL was installed but will not run. Please report this."
fi

# ---------------------------------------------------------------- done
say ""
say "  ${B}${OK}Installed.${R}"
say ""
if [ "$PATH_OK" = 0 ] && [ "$SYSTEM" = 0 ]; then
    say "  ${WARN}One more step${R} - $BIN_DIR was not on your PATH, so start a new"
    say "  terminal, or run this once in this one:"
    say ""
    say "      ${CY}source ~/.bashrc${R}      ${D}(or ~/.zshrc)${R}"
    say ""
else
    say "  ${D}Open a new terminal (or ${R}${CY}source ~/.bashrc${R}${D}) so --activate works.${R}"
    say ""
fi
say "  ${B}Try these:${R}"
say ""
say "      ${CY}venvyard${R}                  ${D}the guided menu, nothing to memorise${R}"
say "      ${CY}venvyard --help${R}           ${D}every command, with examples${R}"
say "      ${CY}venvyard --create demo${R}    ${D}make your first environment${R}"
say "      ${CY}venvyard --list${R}           ${D}see what you have${R}"
say "      ${CY}venvyard --scan${R}           ${D}find venvs already on this machine${R}"
say ""
say "  ${D}Your environments live in ${R}${MA}$YARD${R}"
say "  ${D}Remove venvyard again with ${R}${CY}./install.sh --uninstall${R}"
say ""
