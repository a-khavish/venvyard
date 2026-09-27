"""The single source of truth for every command venvyard understands.

The parser, the --help screens, the interactive menu and the shell
completions are all generated from this list, so they cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cmd:
    key: str                     # internal action name
    long: str                    # --long
    short: str = ""              # -s  (may be empty)
    args: str = ""               # operand hint shown in help
    group: str = "Other"
    summary: str = ""
    details: str = ""
    examples: list = field(default_factory=list)
    multi: bool = False          # accepts many operands
    pairs: bool = False          # operands are OLD[=NEW] pairs
    raw_after: int = 0           # N operands parsed, then everything is literal
    aliases: list = field(default_factory=list)


G_SEE = "Seeing what you have"
G_MAKE = "Creating and reshaping environments"
G_USE = "Using an environment"
G_PKG = "Packages inside an environment"
G_LABEL = "Labels and notes"
G_FIX = "Health and repair"
G_TOOL = "The tool itself"

COMMANDS = [
    # ---------------------------------------------------------------- seeing
    Cmd("list", "--list", "-l", "[NAME ...]", G_SEE,
        "List every environment in the yard",
        "Shows name, Python version, package count, size, age and health for "
        "each environment. Give names to list only those. Combine with --sort "
        "to order by name, size, python, created, used or packages, and with "
        "--json for machine-readable output.",
        ["venvyard --list",
         "venvyard -l --sort size",
         "venvyard -l --json",
         "venvyard -l web api"],
        multi=True),

    Cmd("info", "--info", "-i", "NAME [NAME ...]", G_SEE,
        "Show everything known about an environment",
        "Prints the full record: path, interpreter and its base, pip version, "
        "package count, size on disk, creation time, last use, origin "
        "(created / cloned / copied / imported), description, tags and any "
        "health problems.",
        ["venvyard --info web", "venvyard -i web api \"my space\""],
        multi=True),

    Cmd("packages", "--packages", "-p", "NAME [NAME ...]", G_SEE,
        "List the packages installed in an environment",
        "Reads package names and versions directly from site-packages, so it "
        "is fast and works even when pip is missing. Add --pip to ask pip "
        "itself instead.",
        ["venvyard --packages web", "venvyard -p web --json"],
        multi=True),

    Cmd("search", "--search", "-s", "PATTERN", G_SEE,
        "Find environments by name, tag, description or package",
        "Matches the pattern against names, descriptions and tags. Add "
        "--in-packages to also search the installed packages of every "
        "environment, which answers 'which venv has django in it?'.",
        ["venvyard --search api", "venvyard -s django --in-packages"]),

    Cmd("which", "--which", "-w", "NAME", G_SEE,
        "Print the absolute path of an environment",
        "Prints just the path, with nothing else, so it can be used in "
        "scripts and in IDE interpreter settings. Add --python to print the "
        "path of the interpreter instead.",
        ["venvyard --which web",
         "venvyard -w web --python",
         "cd \"$(venvyard -w web)\""]),

    Cmd("pythons", "--pythons", "-I", "", G_SEE,
        "List every Python interpreter on this machine",
        "Shows each python3.x found on your PATH with its version, whether it "
        "can create virtual environments, its pip version, and how many of your "
        "environments were built with it. Also lists the versions you do not "
        "have and the exact command to install them on your distribution.",
        ["venvyard --pythons", "venvyard --pythons --json"],
        aliases=["--interpreters"]),

    Cmd("stats", "--stats", "", "", G_SEE,
        "Summarise the whole yard",
        "Total environments, combined disk usage, a breakdown by Python "
        "version, the largest and newest environment, and anything unhealthy.",
        ["venvyard --stats"]),

    Cmd("size", "--size", "", "[NAME ...]", G_SEE,
        "Report disk usage, largest first",
        "Sizes every environment and prints them as a ranked bar chart with "
        "the total at the bottom.",
        ["venvyard --size", "venvyard --size web api"],
        multi=True),

    # ---------------------------------------------------------------- making
    Cmd("create", "--create", "-c", "NAME [NAME ...]", G_MAKE,
        "Create one or more environments",
        "Creates each named environment inside the yard. Use --python to pick "
        "an interpreter (3.12, python3.12 or a full path), --requirements to "
        "install a requirements file straight away, --with to install named "
        "packages, --system-site to expose the system packages, and --desc / "
        "--tag-with to label it as it is created. pip is upgraded automatically "
        "unless you pass --no-pip-upgrade.",
        ["venvyard --create web",
         "venvyard -c web api worker",
         "venvyard -c ml --python 3.12 --with numpy pandas",
         "venvyard -c site -r requirements.txt --desc \"client site\" --tag-with work"],
        multi=True),

    Cmd("delete", "--delete", "-d", "NAME [NAME ...]", G_MAKE,
        "Delete one or more environments",
        "Removes the environment directory for good. You are asked to confirm "
        "unless you pass --yes. Nothing outside the yard can ever be deleted. "
        "Use --dry-run to see exactly what would go.",
        ["venvyard --delete old",
         "venvyard -d old scratch \"my space\" --yes",
         "venvyard -d old --dry-run"],
        multi=True),

    Cmd("clone", "--clone", "-C", "OLD[=NEW] ...", G_MAKE,
        "Rebuild an environment from its package list",
        "Creates a brand new environment and installs the same packages into "
        "it. Slower than --copy but the result is clean, has no stale paths "
        "and can be built against a different Python with --python. Leave the "
        "new name off and one is generated for you.",
        ["venvyard --clone web=web-staging",
         "venvyard -C web",
         "venvyard -C web=web312 --python 3.12",
         "venvyard -C web=web2 api=api2"],
        multi=True, pairs=True),

    Cmd("copy", "--copy", "-K", "OLD[=NEW] ...", G_MAKE,
        "Duplicate an environment byte for byte",
        "Copies the whole directory and then rewrites every absolute path "
        "baked into it, so the duplicate works immediately. Faster than "
        "--clone and preserves editable installs, but keeps any existing mess.",
        ["venvyard --copy web=web-backup",
         "venvyard -K web",
         "venvyard -K web=w1 api=a1"],
        multi=True, pairs=True),

    Cmd("rename", "--rename", "-R", "OLD[=NEW] ...", G_MAKE,
        "Rename one or more environments",
        "Moves the directory and rewrites the absolute paths inside it, "
        "which is what makes a renamed environment still work. With exactly "
        "two plain names it reads as OLD NEW. For several at once use "
        "OLD=NEW pairs. Leave the new name off for an automatic one.",
        ["venvyard --rename web website",
         "venvyard -R web=website api=backend",
         "venvyard -R web"],
        multi=True, pairs=True),

    Cmd("import", "--import", "", "PATH [PATH ...]", G_MAKE,
        "Adopt an existing environment into the yard",
        "Moves a virtual environment from anywhere on disk into the yard, "
        "repairs its internal paths and starts tracking it. Pass --keep to "
        "copy instead of moving, and --as NAME to choose the new name.",
        ["venvyard --import ~/projects/site/.venv",
         "venvyard --import ~/old/.venv --as legacy --keep"],
        multi=True),

    Cmd("scan", "--scan", "", "[DIR ...]", G_MAKE,
        "Find virtual environments living outside the yard",
        "Walks your home directory (or the directories you name) looking for "
        "anything that is a virtual environment, and reports each one with "
        "its size and Python version. Add --import-found to adopt every hit, "
        "or copy the suggested commands.",
        ["venvyard --scan",
         "venvyard --scan ~/projects ~/work",
         "venvyard --scan ~/projects --import-found"],
        multi=True),

    Cmd("prune", "--prune", "", "", G_MAKE,
        "Find and remove environments you have stopped using",
        "Lists every environment untouched for longer than --days (90 by "
        "default), shows how much space they occupy, and offers to delete "
        "them. Nothing is removed without confirmation unless --yes is given.",
        ["venvyard --prune", "venvyard --prune --days 30", "venvyard --prune --dry-run"]),

    # ---------------------------------------------------------------- using
    Cmd("activate", "--activate", "-a", "NAME", G_USE,
        "Activate an environment in the current shell",
        "Needs the shell integration that the installer sets up, because no "
        "program can change its parent shell on its own. If the integration "
        "is not loaded, venvyard tells you exactly what to run. Only one "
        "environment can be active at a time; activating a second one "
        "replaces the first.",
        ["venvyard --activate web", "venvyard -a web"]),

    Cmd("deactivate", "--deactivate", "-D", "", G_USE,
        "Deactivate the environment active in this shell",
        "Leaves whichever environment is currently active. Also needs the "
        "shell integration.",
        ["venvyard --deactivate", "venvyard -D"]),

    Cmd("shell", "--shell", "-S", "NAME", G_USE,
        "Open a new shell with an environment already active",
        "Starts a subshell with the environment activated. This always works, "
        "with or without the shell integration. Type exit to come back.",
        ["venvyard --shell web", "venvyard -S web"]),

    Cmd("run", "--run", "-x", "NAME CMD [ARGS ...]", G_USE,
        "Run a command inside an environment without activating it",
        "Everything after the environment name is passed through untouched, "
        "so flags meant for your command are never eaten by venvyard. Use -- "
        "if you want to be explicit.",
        ["venvyard --run web python manage.py migrate",
         "venvyard -x web pytest -q",
         "venvyard -x web -- pip list"],
        raw_after=1, aliases=["--exec"]),

    # ---------------------------------------------------------------- packages
    Cmd("install", "--install", "", "NAME PKG [PKG ...]", G_PKG,
        "Install packages into an environment",
        "Runs pip install inside the named environment. Anything after the "
        "name goes to pip verbatim, so pip's own flags work. That also means "
        "venvyard's own options must come before the environment name.",
        ["venvyard --install web requests flask",
         "venvyard --install web -U requests",
         "venvyard --install web -r extra-requirements.txt",
         "venvyard --verbose --install web numpy"],
        raw_after=1),

    Cmd("uninstall", "--uninstall", "", "NAME PKG [PKG ...]", G_PKG,
        "Remove packages from an environment",
        "Runs pip uninstall -y inside the named environment. Everything after "
        "the name goes to pip, so put venvyard's own options before it.",
        ["venvyard --uninstall web flask"],
        raw_after=1),

    Cmd("freeze", "--freeze", "-f", "NAME [NAME ...]", G_PKG,
        "Write a requirements file from an environment",
        "Prints pip freeze output. With --output it writes to a file instead; "
        "when several environments are frozen, --output is treated as a "
        "directory and one file is written per environment.",
        ["venvyard --freeze web",
         "venvyard -f web -o requirements.txt",
         "venvyard -f web api -o ./reqs/"],
        multi=True),

    Cmd("upgrade_pip", "--upgrade-pip", "-u", "[NAME ...]", G_PKG,
        "Upgrade pip, setuptools and wheel",
        "Upgrades the packaging tools inside each named environment, or in "
        "every environment when no name is given.",
        ["venvyard --upgrade-pip web", "venvyard -u", "venvyard -u web api"],
        multi=True),

    Cmd("outdated", "--outdated", "", "NAME [NAME ...]", G_PKG,
        "Show packages with newer releases available",
        "Asks pip which installed packages have a newer version on PyPI and "
        "prints the current and latest version side by side. Needs network "
        "access.",
        ["venvyard --outdated web"],
        multi=True),

    Cmd("export", "--export", "", "NAME [NAME ...]", G_PKG,
        "Write a portable bundle describing an environment",
        "Writes a JSON file holding the Python version, the full package "
        "list, the description and tags. Feed it back with --create "
        "--from-export to reproduce the environment anywhere.",
        ["venvyard --export web -o web.json",
         "venvyard --create web2 --from-export web.json"],
        multi=True),

    # ---------------------------------------------------------------- labels
    Cmd("describe", "--describe", "", "NAME TEXT", G_LABEL,
        "Attach a note to an environment",
        "Stores a short description shown in listings and in --info. Pass an "
        "empty string to clear it.",
        ["venvyard --describe web \"the customer portal\"",
         "venvyard --describe web \"\""],
        raw_after=1),

    Cmd("tag", "--tag", "", "NAME TAG [TAG ...]", G_LABEL,
        "Add tags to an environment",
        "Tags are free-form labels you can search on with --search.",
        ["venvyard --tag web work django"],
        raw_after=1),

    Cmd("untag", "--untag", "", "NAME TAG [TAG ...]", G_LABEL,
        "Remove tags from an environment",
        "",
        ["venvyard --untag web django"],
        raw_after=1),

    # ---------------------------------------------------------------- health
    Cmd("doctor", "--doctor", "", "[NAME ...]", G_FIX,
        "Check every environment for problems",
        "Looks for missing interpreters, deleted base Pythons, absolute paths "
        "left pointing somewhere else and missing metadata, then tells you "
        "which ones --repair can fix.",
        ["venvyard --doctor", "venvyard --doctor web"],
        multi=True),

    Cmd("repair", "--repair", "", "NAME [NAME ...]", G_FIX,
        "Fix an environment whose paths have gone stale",
        "Rewrites the absolute paths baked into the environment so they point "
        "at where it actually lives, re-points a missing base interpreter and "
        "recreates missing metadata. This is what to run after moving a venv "
        "by hand. Pass --all to repair everything that needs it.",
        ["venvyard --repair web", "venvyard --repair --all"],
        multi=True),

    # ---------------------------------------------------------------- tool
    Cmd("menu", "--menu", "-m", "", G_TOOL,
        "Open the guided interactive menu",
        "A step-by-step menu covering every command, for when you would "
        "rather be asked than remember flags. It prints the equivalent "
        "command line for each action so you can learn the flags as you go.",
        ["venvyard --menu", "venvyard -m", "venvyard"]),

    Cmd("config", "--config", "", "[KEY [VALUE]]", G_TOOL,
        "Show or change venvyard's own settings",
        "With no arguments it prints every setting and where the file lives. "
        "With a key it prints that one. With a key and a value it saves the "
        "change. --config --reset restores the defaults.",
        ["venvyard --config",
         "venvyard --config theme ocean",
         "venvyard --config root ~/PY_VENV",
         "venvyard --config --reset"]),

    Cmd("shell_init", "--shell-init", "", "[bash|zsh|fish]", G_TOOL,
        "Print the shell integration snippet",
        "The installer already adds this to your shell startup file. Print it "
        "yourself if you want to install it somewhere else or inspect it.",
        ["venvyard --shell-init bash",
         "eval \"$(venvyard --shell-init zsh)\""]),

    Cmd("completion", "--completion", "", "[bash|zsh|fish]", G_TOOL,
        "Print a tab-completion script",
        "Completes command flags and the names of your environments.",
        ["venvyard --completion bash > ~/.local/share/bash-completion/completions/venvyard"]),

    Cmd("help", "--help", "-h", "[COMMAND]", G_TOOL,
        "Show help, optionally for one command",
        "With no argument it prints the full reference. With a command name "
        "or flag it prints that command's own page, with every option and "
        "example.",
        ["venvyard --help", "venvyard --help create", "venvyard -h --clone"]),

    Cmd("version", "--version", "-V", "", G_TOOL,
        "Print the version and where things live",
        "", ["venvyard --version"]),
]

# -------------------------------------------------------------------- options

@dataclass
class Opt:
    long: str
    short: str = ""
    arg: str = ""          # "" means it is a switch
    summary: str = ""
    applies: str = ""
    repeatable: bool = False
    greedy: bool = False   # consumes every following bare token


OPTIONS = [
    Opt("--python", "-P", "SPEC", "Interpreter to build with: 3.12, python3.12 or a full path",
        "create, clone"),
    Opt("--requirements", "-r", "FILE", "Install this requirements file after creating",
        "create"),
    Opt("--with", "", "PKG...", "Install these packages after creating", "create",
        repeatable=True, greedy=True),
    Opt("--tag-with", "", "TAG...", "Tag the environment as it is created", "create",
        repeatable=True, greedy=True),
    Opt("--desc", "", "TEXT", "Describe the environment as it is created", "create"),
    Opt("--system-site", "", "", "Let the environment see system-wide packages", "create"),
    Opt("--no-pip-upgrade", "", "", "Skip the automatic pip upgrade after creating", "create"),
    Opt("--without-pip", "", "", "Create the environment with no pip at all", "create"),
    Opt("--from-export", "", "FILE", "Rebuild from a file written by --export", "create"),
    Opt("--as", "", "NAME", "Name to give the imported environment", "import"),
    Opt("--keep", "", "", "Copy instead of moving the original", "import"),
    Opt("--import-found", "", "", "Adopt every environment the scan turns up", "scan"),
    Opt("--output", "-o", "PATH", "Write output to this file or directory",
        "freeze, export"),
    Opt("--days", "", "N", "Age threshold in days", "prune"),
    Opt("--sort", "", "KEY", "Order by name, size, python, created, used or packages",
        "list, size"),
    Opt("--in-packages", "", "", "Search inside installed packages too", "search"),
    Opt("--pip", "", "", "Ask pip rather than reading site-packages", "packages"),
    Opt("--all", "", "", "Apply to every environment", "repair, upgrade-pip"),
    Opt("--broken", "", "", "Restrict the listing to unhealthy environments", "list"),
    Opt("--yes", "-y", "", "Answer yes to every confirmation", "anything destructive"),
    Opt("--dry-run", "", "", "Show what would happen and change nothing", "anything destructive"),
    Opt("--force", "", "", "Carry on past non-fatal problems", "several"),
    Opt("--json", "-J", "", "Emit JSON instead of a table", "list, info, packages, stats, search"),
    Opt("--quiet", "-q", "", "Only print what was asked for", "everywhere"),
    Opt("--verbose", "-v", "", "Show the underlying commands and their output", "everywhere"),
    Opt("--no-color", "", "", "Disable colour (NO_COLOR is honoured too)", "everywhere"),
    Opt("--theme", "", "NAME", "Colour theme: default, ocean, sunset, matrix, mono", "everywhere"),
    Opt("--root", "", "DIR", "Use a different yard for this one command", "everywhere"),
    Opt("--ascii", "", "", "Use ASCII box drawing instead of Unicode", "everywhere"),
]

BY_LONG = {c.long: c for c in COMMANDS}
BY_SHORT = {c.short: c for c in COMMANDS if c.short}
BY_KEY = {c.key: c for c in COMMANDS}
for _c in COMMANDS:
    for _a in _c.aliases:
        BY_LONG[_a] = _c

OPT_BY_LONG = {o.long: o for o in OPTIONS}
OPT_BY_SHORT = {o.short: o for o in OPTIONS if o.short}

GROUP_ORDER = [G_SEE, G_MAKE, G_USE, G_PKG, G_LABEL, G_FIX, G_TOOL]


def find_command(token: str):
    """Resolve '--create', 'create', '-c' or 'c' to a Cmd."""
    token = token.strip()
    if token in BY_LONG:
        return BY_LONG[token]
    if token in BY_SHORT:
        return BY_SHORT[token]
    if not token.startswith("-"):
        guess = "--" + token.replace("_", "-")
        if guess in BY_LONG:
            return BY_LONG[guess]
        for cmd in COMMANDS:
            if cmd.key == token.replace("-", "_"):
                return cmd
    return None


def _assert_no_flag_collisions() -> None:
    """Command flags and option flags share one namespace on the command line,
    so they must never overlap.  Checked at import time."""
    seen: dict[str, str] = {}
    for cmd in COMMANDS:
        for flag in filter(None, [cmd.long, cmd.short, *cmd.aliases]):
            if flag in seen:
                raise AssertionError(f"flag {flag} used by both {seen[flag]} and {cmd.key}")
            seen[flag] = cmd.key
    for opt in OPTIONS:
        for flag in filter(None, [opt.long, opt.short]):
            if flag in seen:
                raise AssertionError(
                    f"flag {flag} used by both {seen[flag]} and option {opt.long}")
            seen[flag] = f"option {opt.long}"


_assert_no_flag_collisions()
