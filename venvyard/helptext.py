"""Rendering of the --help screens, built from the command registry."""
from __future__ import annotations

from . import __version__, __tagline__
from .colors import Palette, banner, rule, term_width, vlen
from .registry import COMMANDS, GROUP_ORDER, OPTIONS, find_command


def _wrap(text: str, width: int, indent: str = "") -> list:
    import textwrap
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) or [indent])
    return out


def usage_line(p: Palette) -> str:
    t = p("cmd", "venvyard", bold=True)
    return (f"  {t} {p('key','COMMAND')} {p('dim','[NAMES ...]')} {p('dim','[OPTIONS]')}\n"
            f"  {p('cmd','vy', bold=True)} {p('dim','... (vy is a shorter alias for venvyard)')}")


def full_help(p: Palette) -> str:
    g = p.glyph
    width = min(term_width(), 96)
    body = min(width - 26, 68)
    out = [banner(p, f"venvyard {__version__}", __tagline__), ""]

    out.append(p("header", "USAGE", bold=True))
    out.append(usage_line(p))
    out.append("")

    out.append(p("header", "THE IDEA", bold=True))
    for line in _wrap(
        "Every environment venvyard manages lives as a direct child of one "
        "folder - the yard - so there is never an index to fall out of sync. "
        "Create them here and they are all in one place, easy to list, "
        "search, copy, rename and clean up. Run venvyard with no arguments "
        "at all to open the guided menu.", width - 4, "  "):
        out.append(p("dim", line) if line else "")
    out.append("")

    for group in GROUP_ORDER:
        cmds = [c for c in COMMANDS if c.group == group]
        if not cmds:
            continue
        out.append(p("header", group.upper(), bold=True))
        for c in cmds:
            flags = p("cmd", c.long, bold=True)
            if c.short:
                flags += p("dim", ", ") + p("cmd", c.short)
            args = p("key", " " + c.args) if c.args else ""
            left = f"  {flags}{args}"
            pad = max(1, 34 - vlen(left))
            summary_width = max(24, width - 36)
            lines = _wrap(c.summary, summary_width)
            out.append(left + " " * pad + p("text", lines[0] if lines else ""))
            for extra in lines[1:]:
                out.append(" " * 34 + p("text", extra))
        out.append("")

    out.append(p("header", "OPTIONS", bold=True))
    for o in OPTIONS:
        flags = p("cmd", o.long)
        if o.short:
            flags += p("dim", ", ") + p("cmd", o.short)
        if o.arg:
            flags += " " + p("key", o.arg)
        left = f"  {flags}"
        pad = max(1, 34 - vlen(left))
        line = o.summary
        if o.applies:
            line += p("dim", f"  [{o.applies}]")
        lines = _wrap(o.summary, max(24, width - 38))
        out.append(left + " " * pad + p("text", lines[0]) +
                   (p("dim", f"  ({o.applies})") if o.applies and len(lines) == 1 else ""))
        for extra in lines[1:]:
            out.append(" " * 34 + p("text", extra))
    out.append("")

    out.append(p("header", "NAMES WITH SPACES AND PAIRS", bold=True))
    for line in [
        f"Quote any name containing a space:  {p('cmd', 'venvyard -d ' + chr(34) + 'my space' + chr(34))}",
        f"Rename, clone and copy take {p('key','OLD=NEW')} pairs so you can do many at once:",
        f"    {p('cmd','venvyard -R web=website api=backend')}",
        f"Leave the new name off and one is made for you ({p('name','web')} {g['arrow']} {p('name','web(1)')}):",
        f"    {p('cmd','venvyard -C web')}",
        f"With exactly two plain names, rename reads as OLD NEW:",
        f"    {p('cmd','venvyard -R web website')}",
    ]:
        out.append("  " + line)
    out.append("")

    out.append(p("header", "EXAMPLES", bold=True))
    for ex, note in [
        ("venvyard -c web api worker", "create three environments at once"),
        ("venvyard -c ml -P 3.12 --with numpy pandas", "a 3.12 environment with packages"),
        ("venvyard -l --sort size", "list everything, biggest first"),
        ("venvyard -a web", "activate it in this shell"),
        ("venvyard -x web pytest -q", "run a command without activating"),
        ("venvyard -K web=web-backup", "duplicate before a risky upgrade"),
        ("venvyard -s django --in-packages", "which environment has django?"),
        ("venvyard --scan ~/projects", "find environments living outside the yard"),
        ("venvyard --prune --days 60", "clean up what you stopped using"),
    ]:
        left = "  " + p("cmd", ex)
        pad = max(2, 48 - vlen(left))
        out.append(left + " " * pad + p("dim", g["dot"] + " " + note))
    out.append("")

    out.append(p("header", "EXIT CODES", bold=True))
    for code, meaning in [
        ("0", "it worked"),
        ("1", "it did not work (not found, refused, pip failed)"),
        ("2", "the command line was wrong"),
        ("3", "needs the shell integration (--activate, --deactivate)"),
        ("130", "interrupted with Ctrl-C"),
        ("*", "--run passes through whatever your command returned"),
    ]:
        out.append("  " + p("num", code.rjust(4)) + "   " + p("text", meaning))
    out.append("")

    out.append(p("header", "MORE HELP", bold=True))
    out.append(f"  {p('cmd','venvyard --help COMMAND')}   "
               + p("dim", "the full page for one command, e.g. --help clone"))
    out.append(f"  {p('cmd','venvyard --menu')}            "
               + p("dim", "the guided menu, no flags to remember"))
    out.append(f"  {p('cmd','venvyard --config')}          "
               + p("dim", "where the yard is and how to change it"))
    return "\n".join(out)


def command_help(p: Palette, token: str) -> str | None:
    cmd = find_command(token)
    if cmd is None:
        return None
    g = p.glyph
    width = min(term_width(), 92)
    out = []
    flags = p("cmd", cmd.long, bold=True)
    if cmd.short:
        flags += p("dim", "  or  ") + p("cmd", cmd.short, bold=True)
    out.append(rule(p, cmd.long.lstrip("-")))
    out.append("")
    out.append("  " + flags + (" " + p("key", cmd.args) if cmd.args else ""))
    out.append("")
    for line in _wrap(cmd.summary, width - 4, "  "):
        out.append(p("text", line))
    if cmd.details:
        out.append("")
        for line in _wrap(cmd.details, width - 4, "  "):
            out.append(p("dim", line))
    if cmd.pairs:
        out.append("")
        out.append("  " + p("warn", g["info"]) + " " +
                   p("text", "Takes OLD=NEW pairs, or a single name for an automatic one."))
    if cmd.raw_after:
        out.append("")
        out.append("  " + p("warn", g["info"]) + " " +
                   p("text", "Everything after the environment name is passed through untouched."))
    relevant = [o for o in OPTIONS
                if cmd.long.lstrip("-") in o.applies or o.applies in ("everywhere",)
                or (o.applies == "anything destructive" and cmd.key in
                    ("delete", "prune", "clone", "copy", "rename", "import"))]
    if relevant:
        out.append("")
        out.append("  " + p("header", "Options that apply", bold=True))
        for o in relevant:
            f = p("cmd", o.long) + (p("dim", ", ") + p("cmd", o.short) if o.short else "")
            if o.arg:
                f += " " + p("key", o.arg)
            left = "    " + f
            out.append(left + " " * max(2, 34 - vlen(left)) + p("text", o.summary))
    if cmd.examples:
        out.append("")
        out.append("  " + p("header", "Examples", bold=True))
        for ex in cmd.examples:
            out.append("    " + p("cmd", ex))
    out.append("")
    return "\n".join(out)


def brief(p: Palette) -> str:
    g = p.glyph
    out = [banner(p, f"venvyard {__version__}", __tagline__), ""]
    out.append("  " + p("text", "Nothing to do. Some places to start:"))
    out.append("")
    for ex, note in [
        ("venvyard --menu", "guided menu, nothing to memorise"),
        ("venvyard --list", "what you already have"),
        ("venvyard --create NAME", "make a new environment"),
        ("venvyard --help", "the full reference"),
    ]:
        left = "    " + p("cmd", ex)
        out.append(left + " " * max(2, 34 - vlen(left)) + p("dim", g["dot"] + " " + note))
    out.append("")
    return "\n".join(out)
