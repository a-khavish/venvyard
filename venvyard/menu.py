"""The guided interactive menu.

Plain prompts rather than curses, so it works over ssh, in tmux, in small
terminals and in editors' built-in shells.  Every action prints the command
line it is equivalent to, so the menu teaches the flags while you use it.
"""
from __future__ import annotations

import os
import shlex
import sys

from . import __version__, __tagline__
from .colors import Table, banner, rule, term_width
from .core import (KNOWN_VERSIONS, VenvyardError, available_pythons, detect_distro,
                   human_age, human_size, install_commands, interpreter_report)
from .registry import COMMANDS, GROUP_ORDER


class Back(Exception):
    """Raised to bounce back to the previous menu."""


def clear(ctx):
    if sys.stdout.isatty() and not os.environ.get("VENVYARD_NO_CLEAR"):
        print("\x1b[2J\x1b[H", end="")


def header(ctx, subtitle=""):
    p = ctx.pal
    clear(ctx)
    print(banner(p, f"venvyard {__version__}", subtitle or __tagline__))
    venvs = ctx.yard.list()
    broken = [v for v in venvs if v.broken]
    line = (p("dim", "  yard: ") + p("path", str(ctx.yard.root))
            + p("dim", f"   {len(venvs)} environment(s)"))
    if broken:
        line += p("warn", f"   {p.glyph['warn']} {len(broken)} need attention")
    active = os.environ.get("VIRTUAL_ENV")
    if active:
        line += p("dim", "   active: ") + p("ok", os.path.basename(active))
    print(line)
    print()


def choose(ctx, title, options, allow_back=True, footer=""):
    """options: [(label, value, hint)] -> value, or None for back."""
    p, g = ctx.pal, ctx.pal.glyph
    print(p("header", title, bold=True))
    print()
    for idx, (label, _value, hint) in enumerate(options, 1):
        num = p("accent", str(idx).rjust(3) + ".")
        line = f"  {num} {p('text', label)}"
        if hint:
            pad = max(2, 42 - len(label))
            line += " " * pad + p("dim", g["dot"] + " " + hint)
        print(line)
    print()
    if allow_back:
        print(f"  {p('dim', '  0.')} {p('dim', 'back')}")
    print(f"  {p('dim', '  q.')} {p('dim', 'quit')}")
    if footer:
        print()
        print("  " + p("dim", footer))
    print()
    while True:
        try:
            answer = input(p("accent", "> ") + p("text", "choose") + p("dim", ": ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(0)
        if answer.lower() in ("q", "quit", "exit"):
            raise SystemExit(0)
        if answer in ("0", "b", "back", "") and allow_back:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][1]
        print("  " + p("err", g["cross"]) + " " +
              p("dim", f"type a number between 1 and {len(options)}"))


def pick_venv(ctx, prompt="Which environment?", multiple=False, filter_fn=None):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = ctx.yard.list()
    if filter_fn:
        venvs = [v for v in venvs if filter_fn(v)]
    if not venvs:
        print("  " + p("warn", g["warn"] + " there are no environments to choose from"))
        pause(ctx)
        raise Back
    print(p("header", prompt, bold=True))
    print()
    for idx, v in enumerate(venvs, 1):
        status = p("ok", g["tick"]) if not v.broken else p("err", g["cross"])
        line = (f"  {p('accent', str(idx).rjust(3) + '.')} {status} "
                + p("name", v.name.ljust(26))
                + p("dim", f"Python {v.python_version}   "
                           f"{v.package_count} packages   "
                           f"used {human_age(v.last_used)}"))
        if v.description:
            line += p("dim", "   " + v.description[:28])
        print(line)
    print()
    if multiple:
        print("  " + p("dim", "several at once: 1 3 4   |   everything: a   |   back: 0"))
    else:
        print("  " + p("dim", "back: 0"))
    print()
    while True:
        try:
            answer = input(p("accent", "> ") + p("text", "number") + p("dim", ": ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise Back
        if answer.lower() in ("q", "quit"):
            raise SystemExit(0)
        if answer in ("0", "", "b", "back"):
            raise Back
        if multiple and answer.lower() in ("a", "all"):
            return venvs
        picks, bad = [], False
        for part in answer.replace(",", " ").split():
            if not part.isdigit() or not (1 <= int(part) <= len(venvs)):
                bad = True
                break
            picks.append(venvs[int(part) - 1])
        if bad or not picks:
            print("  " + p("err", g["cross"]) + " " + p("dim", "try again"))
            continue
        return picks if multiple else picks[0]


def ask(ctx, question, default="", allow_blank=True):
    p = ctx.pal
    hint = p("dim", f"  [{default}]") if default else ""
    while True:
        try:
            answer = input(p("accent", "> ") + p("text", question) + hint
                           + p("dim", ": ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise Back
        answer = answer or default
        if answer or allow_blank:
            return answer
        print("  " + p("dim", "that cannot be empty"))


def yes_no(ctx, question, default=False):
    p = ctx.pal
    suffix = " [y/N]" if not default else " [Y/n]"
    try:
        answer = input(p("warn", "? ") + p("text", question)
                       + p("dim", suffix + " ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def pause(ctx):
    p = ctx.pal
    print()
    try:
        input(p("dim", "  press Enter to continue "))
    except (EOFError, KeyboardInterrupt):
        print()


def show_command(ctx, argv):
    """Teach the equivalent command line."""
    p, g = ctx.pal, ctx.pal.glyph
    line = "venvyard " + " ".join(shlex.quote(a) for a in argv)
    print()
    print("  " + p("dim", "same as: ") + p("cmd", line))
    print()


def run(ctx, key, operands, opts=None, raw=None):
    """Run a real action with a temporary option overlay."""
    from .actions import DISPATCH
    saved_opts, saved_raw = ctx.opts, ctx.raw
    ctx.opts = dict(saved_opts)
    ctx.opts.update(opts or {})
    ctx.raw = list(raw or [])
    ctx.dry_run = bool(ctx.opts.get("dry_run"))
    ctx.yes = bool(ctx.opts.get("yes"))
    try:
        return DISPATCH[key](ctx, operands)
    except VenvyardError as exc:
        ctx.err(str(exc))
        return 1
    finally:
        ctx.opts, ctx.raw = saved_opts, saved_raw
        ctx.dry_run = bool(ctx.opts.get("dry_run"))
        ctx.yes = bool(ctx.opts.get("yes"))


# ---------------------------------------------------------------------------
# individual flows
# ---------------------------------------------------------------------------

def flow_create(ctx):
    p, g = ctx.pal, ctx.pal.glyph
    header(ctx, "create an environment")
    print(p("dim", "  Step 1 of 4  " + g["dot"] + "  name"))
    print()
    existing = set(ctx.yard.names())
    while True:
        names_raw = ask(ctx, "Name it (several names separated by spaces)", allow_blank=False)
        names = shlex.split(names_raw) if names_raw else []
        if not names:
            continue
        clash = [n for n in names if n in existing]
        if clash:
            print("  " + p("err", g["cross"]) + " " +
                  p("text", f"already taken: {', '.join(clash)}"))
            continue
        break

    print()
    print(p("dim", "  Step 2 of 4  " + g["dot"] + "  interpreter"))
    print()
    rows = interpreter_report()
    opts = [("the one venvyard is running on", "", f"Python {sys.version.split()[0]}")]
    for r in rows:
        usable = r.get("venv") and r.get("ensurepip")
        hint = r.get("path", "")
        label = f"Python {r.get('version', r.get('short'))}"
        if not usable:
            label += "  (cannot create environments)"
            hint = "missing venv or pip support"
        elif r.get("environments"):
            hint += f"   {r['environments']} environment(s) use it"
        opts.append((label, r.get("short", ""), hint))
    opts.append(("type a path myself", "__custom__", ""))
    opts.append(("I need a version I do not have", "__missing__", "show me how to install it"))
    chosen = choose(ctx, "Which Python?", opts, allow_back=True)
    if chosen is None:
        raise Back
    if chosen == "__missing__":
        flow_pythons(ctx)
        raise Back
    if chosen == "__custom__":
        chosen = ask(ctx, "Path or version", allow_blank=False)

    print()
    print(p("dim", "  Step 3 of 4  " + g["dot"] + "  packages"))
    print()
    pkg_mode = choose(ctx, "Install anything straight away?", [
        ("nothing for now", "none", "just pip, setuptools and wheel"),
        ("packages I name", "pkgs", "e.g. requests flask"),
        ("a requirements file", "req", "e.g. ./requirements.txt"),
    ], allow_back=True)
    if pkg_mode is None:
        raise Back
    packages, requirements = [], None
    if pkg_mode == "pkgs":
        packages = shlex.split(ask(ctx, "Packages, separated by spaces"))
    elif pkg_mode == "req":
        requirements = ask(ctx, "Path to the requirements file", "requirements.txt")

    print()
    print(p("dim", "  Step 4 of 4  " + g["dot"] + "  label it (optional)"))
    print()
    desc = ask(ctx, "A short description")
    tags = shlex.split(ask(ctx, "Tags, separated by spaces"))

    argv = ["--create", *names]
    if chosen:
        argv += ["--python", chosen]
    if packages:
        argv += ["--with", *packages]
    if requirements:
        argv += ["--requirements", requirements]
    if desc:
        argv += ["--desc", desc]
    if tags:
        argv += ["--tag-with", *tags]
    show_command(ctx, argv)
    if not yes_no(ctx, f"Create {len(names)} environment(s)?", default=True):
        return
    print()
    run(ctx, "create", names, {"python": chosen or None, "with_packages": packages,
                               "requirements": requirements, "desc": desc, "tags": tags})
    pause(ctx)


def flow_delete(ctx):
    header(ctx, "delete environments")
    venvs = pick_venv(ctx, "Which should go? (this cannot be undone)", multiple=True)
    names = [v.name for v in venvs]
    show_command(ctx, ["--delete", *names])
    run(ctx, "delete", names)
    pause(ctx)


def flow_pair(ctx, key, title, explain):
    p, g = ctx.pal, ctx.pal.glyph
    header(ctx, title)
    print("  " + p("dim", explain))
    print()
    venv = pick_venv(ctx, "Which environment?")
    print()
    suggested = ctx.yard.auto_name(venv.name)
    new = ask(ctx, f"New name (blank for {suggested})", "")
    target = new or None
    show_command(ctx, [f"--{key}", f"{venv.name}={new}" if new else venv.name])
    run(ctx, key, [f"{venv.name}={new}"] if new else [venv.name])
    pause(ctx)


def flow_inspect(ctx, key, title, multiple=False):
    header(ctx, title)
    picked = pick_venv(ctx, "Which environment?", multiple=multiple)
    names = [v.name for v in picked] if multiple else [picked.name]
    show_command(ctx, [f"--{key}", *names])
    run(ctx, key, names)
    pause(ctx)


def flow_activate(ctx):
    p, g = ctx.pal, ctx.pal.glyph
    header(ctx, "activate an environment")
    venv = pick_venv(ctx, "Which environment?")
    print()
    print("  " + p("text", "A menu running inside venvyard cannot change the shell you "
                           "started it from,"))
    print("  " + p("text", "so here are the two things that do work:"))
    print()
    pick = choose(ctx, "How would you like to use it?", [
        ("open a subshell with it active", "shell", "works everywhere, exit to come back"),
        ("show me the command for my own shell", "cmd", "if the integration is loaded"),
    ], allow_back=True)
    if pick is None:
        raise Back
    if pick == "shell":
        show_command(ctx, ["--shell", venv.name])
        print("  " + p("dim", "starting a subshell - type ") + p("cmd", "exit")
              + p("dim", " to return to the menu"))
        print()
        run(ctx, "shell", [venv.name])
    else:
        print()
        print("  " + p("header", "In your shell, run:", bold=True))
        print("    " + p("cmd", f"venvyard -a {shlex.quote(venv.name)}"))
        print()
        from .actions import integration_hint, shell_flavour
        print("  " + p("dim", "If that says the integration is not loaded:"))
        print("    " + p("cmd", integration_hint()[0]))
        print()
        print("  " + p("dim", "Or source it directly:"))
        print("    " + p("cmd", venv.activate_command(shell_flavour())))
        pause(ctx)


def flow_install(ctx):
    p = ctx.pal
    header(ctx, "install packages")
    venv = pick_venv(ctx, "Install into which environment?")
    print()
    pkgs = shlex.split(ask(ctx, "Packages, separated by spaces", allow_blank=False))
    if not pkgs:
        return
    show_command(ctx, ["--install", venv.name, *pkgs])
    run(ctx, "install", [venv.name], raw=pkgs)
    pause(ctx)


def flow_uninstall(ctx):
    header(ctx, "remove packages")
    venv = pick_venv(ctx, "Remove from which environment?")
    print()
    pkgs = venv.packages()
    if not pkgs:
        ctx.info("Nothing is installed there.")
        pause(ctx)
        return
    ctx.out("  " + ctx.pal("dim", "installed: ")
            + ctx.pal("name", ", ".join(n for n, _ in pkgs[:24]))
            + (ctx.pal("dim", " ...") if len(pkgs) > 24 else ""))
    print()
    names = shlex.split(ask(ctx, "Which packages should go?", allow_blank=False))
    if not names:
        return
    show_command(ctx, ["--uninstall", venv.name, *names])
    run(ctx, "uninstall", [venv.name], raw=names)
    pause(ctx)


def flow_freeze(ctx):
    header(ctx, "write a requirements file")
    venv = pick_venv(ctx, "Freeze which environment?")
    print()
    out = ask(ctx, "Write to which file (blank to print here)", "")
    show_command(ctx, ["--freeze", venv.name] + (["-o", out] if out else []))
    run(ctx, "freeze", [venv.name], {"output": out or None})
    pause(ctx)


def flow_run(ctx):
    header(ctx, "run a command inside an environment")
    venv = pick_venv(ctx, "Run inside which environment?")
    print()
    cmd = shlex.split(ask(ctx, "Command to run", "python -V", allow_blank=False))
    if not cmd:
        return
    show_command(ctx, ["--run", venv.name, *cmd])
    print()
    run(ctx, "run", [venv.name], raw=cmd)
    pause(ctx)


def flow_label(ctx):
    header(ctx, "describe and tag")
    venv = pick_venv(ctx, "Which environment?")
    print()
    print("  " + ctx.pal("dim", "current description: ")
          + (ctx.pal("text", venv.description) if venv.description
             else ctx.pal("dim", "none")))
    print("  " + ctx.pal("dim", "current tags:        ")
          + (ctx.pal("accent", " ".join("#" + t for t in venv.tags)) if venv.tags
             else ctx.pal("dim", "none")))
    print()
    desc = ask(ctx, "New description (blank to leave it)", "")
    if desc:
        run(ctx, "describe", [venv.name], raw=[desc])
    tags = shlex.split(ask(ctx, "Tags to add (blank to skip)", ""))
    if tags:
        run(ctx, "tag", [venv.name], raw=tags)
    if desc or tags:
        show_command(ctx, ["--describe", venv.name, desc or "..."])
    pause(ctx)


def flow_search(ctx):
    header(ctx, "search")
    pattern = ask(ctx, "Search for", allow_blank=False)
    if not pattern:
        return
    deep = yes_no(ctx, "Search inside installed packages too?", default=True)
    show_command(ctx, ["--search", pattern] + (["--in-packages"] if deep else []))
    run(ctx, "search", [pattern], {"in_packages": deep})
    pause(ctx)


def flow_scan(ctx):
    header(ctx, "find environments outside the yard")
    where = ask(ctx, "Where should I look", "~")
    show_command(ctx, ["--scan", where])
    print()
    run(ctx, "scan", [where])
    pause(ctx)


def flow_import(ctx):
    header(ctx, "adopt an existing environment")
    path = ask(ctx, "Path to the environment", allow_blank=False)
    if not path:
        return
    keep = yes_no(ctx, "Leave the original in place (copy instead of move)?", default=False)
    show_command(ctx, ["--import", path] + (["--keep"] if keep else []))
    run(ctx, "import", [path], {"keep": keep})
    pause(ctx)


def flow_prune(ctx):
    header(ctx, "clean up what you stopped using")
    days = ask(ctx, "Unused for how many days", str(ctx.cfg.get("prune_days", 90)))
    show_command(ctx, ["--prune", "--days", days])
    run(ctx, "prune", [], {"days": days})
    pause(ctx)


def flow_simple(ctx, key, title, operands=None, opts=None):
    header(ctx, title)
    show_command(ctx, [f"--{key.replace('_', '-')}", *(operands or [])])
    run(ctx, key, operands or [], opts)
    pause(ctx)


def flow_pythons(ctx):
    p, g = ctx.pal, ctx.pal.glyph
    header(ctx, "Python interpreters")
    show_command(ctx, ["--pythons"])
    run(ctx, "pythons", [])
    print()
    present = {r.get("short") for r in interpreter_report(ctx.yard)}
    missing = [v for v in KNOWN_VERSIONS if v not in present]
    if not missing:
        print("  " + p("ok", g["tick"]) + " "
              + p("text", "You have every version venvyard knows about."))
        pause(ctx)
        return
    if not yes_no(ctx, "Want the command to install one of the missing versions?",
                  default=False):
        return
    pick = choose(ctx, "Which version?",
                  [(f"Python {v}", v, "not installed") for v in missing],
                  allow_back=True)
    if pick is None:
        return
    help_ = install_commands(pick)
    where = help_["distro"].get("name") or "this system"
    print()
    print("  " + p("header", f"To install Python {pick} on {where}", bold=True))
    print()
    for cmd in help_["commands"]:
        print("      " + p("cmd", cmd))
    if help_["note"]:
        print()
        for line in help_["note"].splitlines():
            stripped = line.strip()
            if stripped.startswith(("sudo", "pyenv", "uv ")):
                print("      " + p("cmd", stripped))
            elif stripped:
                print("  " + p("dim", stripped))
            else:
                print()
    print()
    print("  " + p("warn", g["warn"]) + " "
          + p("text", "venvyard does not run this for you - installing system packages "
                      "needs root"))
    print("  " + p("dim", "  and should be something you choose to type yourself. "
                          "Copy it into your shell."))
    print()
    print("  " + p("dim", "Afterwards, check it worked with ") + p("cmd", "venvyard --pythons"))
    pause(ctx)


def flow_config(ctx):
    p = ctx.pal
    header(ctx, "settings")
    run(ctx, "config", [])
    print()
    if not yes_no(ctx, "Change one?", default=False):
        return
    from . import config as configmod
    keys = sorted(configmod.DEFAULTS)
    pick = choose(ctx, "Which setting?",
                  [(k, k, str(ctx.cfg.get(k))) for k in keys], allow_back=True)
    if pick is None:
        return
    value = ask(ctx, f"New value for {pick}", str(ctx.cfg.get(pick)))
    show_command(ctx, ["--config", pick, value])
    run(ctx, "config", [pick, value])
    ctx.cfg = configmod.load()
    pause(ctx)


def flow_reference(ctx):
    p, g = ctx.pal, ctx.pal.glyph
    header(ctx, "every command")
    for group in GROUP_ORDER:
        cmds = [c for c in COMMANDS if c.group == group]
        if not cmds:
            continue
        print(p("header", "  " + group, bold=True))
        for c in cmds:
            flags = p("cmd", c.long) + (p("dim", ", ") + p("cmd", c.short) if c.short else "")
            left = "    " + flags
            from .colors import vlen
            print(left + " " * max(2, 30 - vlen(left)) + p("dim", c.summary))
        print()
    print("  " + p("dim", "Full detail for any of them: ")
          + p("cmd", "venvyard --help COMMAND"))
    pause(ctx)


# ---------------------------------------------------------------------------
# the menus
# ---------------------------------------------------------------------------

MENUS = {
    "main": ("What would you like to do?", [
        ("See my environments", "see", "list, info, packages, search"),
        ("Create a new environment", "create", "with any Python and packages"),
        ("Copy, clone or rename", "reshape", "duplicate or rebuild an existing one"),
        ("Use an environment", "use", "activate, subshell, run a command"),
        ("Manage packages", "packages", "install, remove, freeze, upgrade"),
        ("Delete or clean up", "cleanup", "delete, prune unused, reclaim space"),
        ("Find and adopt strays", "adopt", "scan the disk, import into the yard"),
        ("Check health and repair", "health", "doctor, repair broken paths"),
        ("Labels and notes", "label", "describe and tag environments"),
        ("Settings and reference", "tool", "config, every command, version"),
    ]),
    "see": ("What would you like to see?", [
        ("List everything", "a_list", "name, Python, packages, size, age"),
        ("Everything about one environment", "a_info", "the full record"),
        ("Packages in an environment", "a_packages", "names and versions"),
        ("Search", "a_search", "by name, tag or installed package"),
        ("Disk usage", "a_size", "ranked, with a total"),
        ("Summary of the whole yard", "a_stats", "counts, sizes, Python versions"),
    ]),
    "reshape": ("How would you like to reshape it?", [
        ("Copy", "a_copy", "byte for byte, paths rewritten, fast"),
        ("Clone", "a_clone", "rebuild clean from the package list"),
        ("Rename", "a_rename", "move and fix the paths inside"),
    ]),
    "use": ("How do you want to use it?", [
        ("Activate it", "a_activate", "subshell, or the command for your shell"),
        ("Run a single command in it", "a_run", "without activating anything"),
        ("Show me its path", "a_which", "for IDE settings and scripts"),
    ]),
    "packages": ("What would you like to do with packages?", [
        ("Install", "a_install", "pip install, inside the environment"),
        ("Remove", "a_uninstall", "pip uninstall"),
        ("Write a requirements file", "a_freeze", "pip freeze to a file"),
        ("Upgrade pip, setuptools and wheel", "a_upgrade", "one or all environments"),
        ("Check for outdated packages", "a_outdated", "needs network access"),
        ("Export a portable bundle", "a_export", "rebuild it anywhere later"),
    ]),
    "cleanup": ("What would you like to clean up?", [
        ("Delete environments I choose", "a_delete", "pick from a list"),
        ("Find and remove unused ones", "a_prune", "by how long since last use"),
        ("Show me what is taking space", "a_size", "largest first"),
    ]),
    "adopt": ("Find environments living elsewhere", [
        ("Scan for them", "a_scan", "walk a folder and report what is there"),
        ("Import one I know about", "a_import", "move or copy it into the yard"),
    ]),
    "health": ("Health", [
        ("Check everything", "a_doctor", "find broken interpreters and stale paths"),
        ("Repair one", "a_repair", "rewrite paths so it works again"),
        ("Repair everything that needs it", "a_repair_all", ""),
    ]),
    "tool": ("The tool itself", [
        ("Python interpreters on this machine", "a_pythons",
         "versions, pip, and how to install more"),
        ("Settings", "a_config", "where the yard is, theme, defaults"),
        ("Every command, at a glance", "a_reference", "the whole reference"),
        ("Version and environment", "a_version", ""),
        ("Shell integration snippet", "a_shellinit", "for --activate to work"),
    ]),
}

ACTIONS = {
    "create": flow_create,
    "a_list": lambda c: flow_simple(c, "list", "everything in the yard"),
    "a_info": lambda c: flow_inspect(c, "info", "environment details", multiple=True),
    "a_packages": lambda c: flow_inspect(c, "packages", "installed packages", multiple=True),
    "a_search": flow_search,
    "a_size": lambda c: flow_simple(c, "size", "disk usage"),
    "a_stats": lambda c: flow_simple(c, "stats", "the yard at a glance"),
    "a_copy": lambda c: flow_pair(c, "copy", "copy an environment",
                                  "A byte-for-byte duplicate. Fast, and the paths inside "
                                  "are rewritten so it works immediately."),
    "a_clone": lambda c: flow_pair(c, "clone", "clone an environment",
                                   "Builds a fresh environment and installs the same "
                                   "packages. Slower, but the result is clean."),
    "a_rename": lambda c: flow_pair(c, "rename", "rename an environment",
                                    "Moves it and rewrites the absolute paths baked "
                                    "inside, which is what keeps it working."),
    "a_activate": flow_activate,
    "a_run": flow_run,
    "a_which": lambda c: flow_inspect(c, "which", "where an environment lives"),
    "a_install": flow_install,
    "a_uninstall": flow_uninstall,
    "a_freeze": flow_freeze,
    "a_upgrade": lambda c: flow_inspect(c, "upgrade_pip", "upgrade pip", multiple=True),
    "a_outdated": lambda c: flow_inspect(c, "outdated", "outdated packages", multiple=True),
    "a_export": lambda c: flow_inspect(c, "export", "export a bundle"),
    "a_delete": flow_delete,
    "a_prune": flow_prune,
    "a_scan": flow_scan,
    "a_import": flow_import,
    "a_doctor": lambda c: flow_simple(c, "doctor", "health check"),
    "a_repair": lambda c: flow_inspect(c, "repair", "repair an environment", multiple=True),
    "a_repair_all": lambda c: flow_simple(c, "repair", "repair everything", opts={"all": True}),
    "a_label": flow_label,
    "a_pythons": flow_pythons,
    "a_config": flow_config,
    "a_reference": flow_reference,
    "a_version": lambda c: flow_simple(c, "version", "version"),
    "a_shellinit": lambda c: flow_simple(c, "shell_init", "shell integration"),
}

MENUS["label"] = ("Labels and notes", [
    ("Describe or tag an environment", "a_label", "shown in listings and search"),
    ("Search by tag", "a_search", ""),
])


def run_menu(ctx) -> int:
    p, g = ctx.pal, ctx.pal.glyph
    if not sys.stdin.isatty():
        ctx.err("the menu needs a terminal; use the flags instead "
                "(venvyard --help)")
        return 2
    ctx.yard.ensure_root()
    stack = ["main"]
    try:
        while stack:
            key = stack[-1]
            title, options = MENUS[key]
            header(ctx)
            footer = ("every choice prints the command it is equivalent to, so the "
                      "flags stick") if key == "main" else ""
            pick = choose(ctx, title, options, allow_back=len(stack) > 1, footer=footer)
            if pick is None:
                if len(stack) > 1:
                    stack.pop()
                else:
                    return 0
                continue
            if pick in MENUS:
                stack.append(pick)
                continue
            action = ACTIONS.get(pick)
            if action is None:
                continue
            try:
                action(ctx)
            except Back:
                continue
            except VenvyardError as exc:
                ctx.err(str(exc))
                pause(ctx)
    except SystemExit:
        clear(ctx)
        print(p("dim", "bye"))
        return 0
    except KeyboardInterrupt:
        print()
        return 130
    return 0
