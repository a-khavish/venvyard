"""Command line parsing and the execution context."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__
from . import config as configmod
from .actions import DISPATCH
from .colors import Palette
from .core import VenvyardError, Yard
from .registry import (BY_LONG, BY_SHORT, COMMANDS, OPT_BY_LONG, OPT_BY_SHORT,
                       find_command)

INTERNAL = {"--_shell-eval", "--_names"}

VALUE_OPTS = {
    "--python": "python", "-P": "python",
    "--requirements": "requirements", "-r": "requirements",
    "--output": "output", "-o": "output",
    "--from-export": "from_export",
    "--as": "as_name",
    "--days": "days",
    "--sort": "sort",
    "--theme": "theme",
    "--root": "root",
    "--desc": "desc",
    "--description": "desc",
}

SWITCH_OPTS = {
    "--system-site": "system_site",
    "--no-pip-upgrade": "no_pip_upgrade",
    "--without-pip": "without_pip",
    "--keep": "keep",
    "--import-found": "import_found",
    "--in-packages": "in_packages",
    "--pip": "pip",
    "--all": "all",
    "--broken": "broken",
    "--reset": "reset",
    "--yes": "yes", "-y": "yes",
    "--dry-run": "dry_run",
    "--force": "force",
    "--json": "json", "-J": "json",
    "--quiet": "quiet", "-q": "quiet",
    "--verbose": "verbose", "-v": "verbose",
    "--no-color": "no_color",
    "--ascii": "ascii",
}

GREEDY_OPTS = {"--with": "with_packages", "--tag-with": "tags"}


class Context:
    """Everything an action needs, plus all output funnelled through one place."""

    def __init__(self, pal: Palette, cfg: dict, yard: Yard, opts: dict,
                 raw: list, shell_eval: bool = False):
        self.pal = pal
        self.cfg = cfg
        self.yard = yard
        self.opts = opts
        self.raw = raw
        self.shell_eval = shell_eval
        self.json = bool(opts.get("json"))
        self.quiet = bool(opts.get("quiet"))
        self.verbose = bool(opts.get("verbose"))
        self.dry_run = bool(opts.get("dry_run"))
        self.yes = bool(opts.get("yes"))
        # In shell-eval mode stdout is reserved for shell code.
        self._human = sys.stderr if shell_eval else sys.stdout

    # -- output ------------------------------------------------------------
    def out(self, text=""):
        if not self.quiet:
            print(text, file=self._human)

    def raw_out(self, text=""):
        """Always printed: this is the thing the user actually asked for."""
        print(text, file=sys.stdout if not self.shell_eval else sys.stderr)

    def note(self, text):
        print(text, file=sys.stderr)

    def ok(self, text):
        if not self.quiet:
            print(self.pal("ok", self.pal.glyph["tick"]) + " " + text, file=self._human)

    def info(self, text):
        if not self.quiet:
            print(self.pal("info", self.pal.glyph["info"]) + " " + text, file=self._human)

    def err(self, text):
        print(self.pal("err", self.pal.glyph["cross"]) + " " + text, file=sys.stderr)

    def emit_json(self, data):
        print(json.dumps(data, indent=2, default=str),
              file=sys.stdout if not self.shell_eval else sys.stderr)

    def shell_out(self, code: str):
        print(code, file=sys.stdout)

    # -- input -------------------------------------------------------------
    def confirm(self, question: str, default: bool = False) -> bool:
        if self.yes or not self.cfg.get("confirm_destructive", True):
            return True
        if not sys.stdin.isatty():
            self.err(f"{question}  Not a terminal, so nothing was assumed. "
                     f"Pass --yes to go ahead.")
            return False
        p = self.pal
        suffix = p("dim", " [y/N] ") if not default else p("dim", " [Y/n] ")
        try:
            answer = input(p("warn", "? ") + p("text", question) + suffix).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(file=self._human)
            return False
        if not answer:
            return default
        return answer in ("y", "yes")

    def ask(self, question: str, default: str = "") -> str:
        p = self.pal
        hint = p("dim", f" [{default}]") if default else ""
        try:
            answer = input(p("accent", "> ") + p("text", question) + hint + p("dim", ": ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(file=self._human)
            raise KeyboardInterrupt
        return answer or default


class ParseError(VenvyardError):
    pass


def parse(argv: list) -> tuple:
    """Return (command_key, operands, opts, raw, shell_eval)."""
    opts: dict = {}
    operands: list = []
    raw: list = []
    command = None
    shell_eval = False
    raw_mode = False
    raw_budget = 0

    i = 0
    while i < len(argv):
        token = argv[i]

        if raw_mode:
            if token == "--" and not raw:
                i += 1        # an explicit separator, not an argument
                continue
            raw.append(token)
            i += 1
            continue

        if token == "--":
            raw_mode = True
            i += 1
            continue

        if token == "--_shell-eval":
            shell_eval = True
            i += 1
            continue
        if token == "--_names":
            command = "_names"
            i += 1
            continue

        if token.startswith("--"):
            name, eq, inline = token.partition("=")

            if name in GREEDY_OPTS:
                key = GREEDY_OPTS[name]
                values = opts.setdefault(key, [])
                if eq:
                    values.append(inline)
                    i += 1
                    continue
                i += 1
                while i < len(argv) and not argv[i].startswith("-"):
                    values.append(argv[i])
                    i += 1
                if not values:
                    raise ParseError(f"{name} needs at least one value")
                continue

            if name in VALUE_OPTS:
                key = VALUE_OPTS[name]
                if eq:
                    opts[key] = inline
                    i += 1
                    continue
                nxt = argv[i + 1] if i + 1 < len(argv) else None
                if nxt is None or nxt.startswith("-"):
                    # --python doubles as a switch for --which
                    if name in ("--python", "-P"):
                        opts["_dangling_python"] = True
                        i += 1
                        continue
                    raise ParseError(f"{name} needs a value")
                opts[key] = nxt
                i += 2
                continue

            if name in SWITCH_OPTS:
                opts[SWITCH_OPTS[name]] = True
                i += 1
                continue

            cmd = BY_LONG.get(name)
            if cmd:
                if command == "help":
                    operands.append(name)
                    i += 1
                    continue
                if command and command != cmd.key:
                    raise ParseError(
                        f"{token} cannot be combined with --{command.replace('_', '-')}; "
                        f"run them as two commands")
                command = cmd.key
                if eq:
                    operands.append(inline)
                if cmd.raw_after:
                    raw_budget = cmd.raw_after
                i += 1
                continue

            near = _suggest_flag(name)
            raise ParseError(f"unknown option {token}"
                             + (f".  Did you mean {near}?" if near else "")
                             + "\n  Run venvyard --help to see everything.")

        if token.startswith("-") and len(token) > 1:
            # --python used as -P value, etc.
            if token in VALUE_OPTS:
                if i + 1 >= len(argv):
                    raise ParseError(f"{token} needs a value")
                opts[VALUE_OPTS[token]] = argv[i + 1]
                i += 2
                continue
            if token in SWITCH_OPTS:
                opts[SWITCH_OPTS[token]] = True
                i += 1
                continue
            cmd = BY_SHORT.get(token)
            if cmd:
                if command == "help":
                    operands.append(token)
                    i += 1
                    continue
                if command and command != cmd.key:
                    raise ParseError(f"{token} cannot be combined with "
                                     f"--{command.replace('_', '-')}")
                command = cmd.key
                if cmd.raw_after:
                    raw_budget = cmd.raw_after
                i += 1
                continue
            # a cluster of single-letter switches, e.g. -ly
            letters = list(token[1:])
            if all(f"-{ch}" in SWITCH_OPTS or f"-{ch}" in BY_SHORT for ch in letters):
                for ch in letters:
                    flag = f"-{ch}"
                    if flag in SWITCH_OPTS:
                        opts[SWITCH_OPTS[flag]] = True
                    else:
                        cmd = BY_SHORT[flag]
                        if command and command != cmd.key:
                            raise ParseError(f"-{ch} cannot be combined with "
                                             f"--{command.replace('_', '-')}")
                        command = cmd.key
                        if cmd.raw_after:
                            raw_budget = cmd.raw_after
                i += 1
                continue
            near = _suggest_flag(token)
            raise ParseError(f"unknown option {token}"
                             + (f".  Did you mean {near}?" if near else ""))

        # a bare word
        if raw_budget > 0:
            operands.append(token)
            raw_budget -= 1
            if raw_budget == 0:
                raw_mode = True
            i += 1
            continue
        operands.append(token)
        i += 1

    # --python doubles as a switch for --which; elsewhere it needs a value
    if opts.pop("_dangling_python", False):
        if command == "which":
            opts["python_flag"] = True
        else:
            raise ParseError("--python needs a value, e.g. --python 3.12")
    if command == "which" and "python" in opts:
        opts["python_flag"] = True
        # "--which --python web" put the name in --python's value slot and left
        # no operand, so it complained that no environment was given.  For
        # --which, --python is a switch, so hand the word back as the name.
        swallowed = opts.pop("python", None)
        if swallowed and not operands:
            operands.append(swallowed)

    return command, operands, opts, raw, shell_eval


def _suggest_flag(token: str) -> str | None:
    import difflib
    pool = list(BY_LONG) + list(BY_SHORT) + list(VALUE_OPTS) + list(SWITCH_OPTS) \
        + list(GREEDY_OPTS)
    match = difflib.get_close_matches(token, sorted(set(pool)), n=1, cutoff=0.55)
    return match[0] if match else None


def build_context(opts: dict, raw: list, shell_eval: bool) -> Context:
    cfg = configmod.load()
    if opts.get("theme"):
        cfg["theme"] = opts["theme"]
    if opts.get("root"):
        cfg["root"] = opts["root"]
    color = cfg.get("color", True) and not opts.get("no_color")
    if not sys.stdout.isatty() and not shell_eval:
        color = color and os.environ.get("VENVYARD_FORCE_COLOR") is not None
    if shell_eval and not sys.stderr.isatty():
        color = False
    if opts.get("ascii"):
        os.environ["VENVYARD_ASCII"] = "1"
    theme = cfg.get("theme", "default")
    if opts.get("theme"):
        from .colors import THEMES
        if theme not in THEMES:
            raise ParseError("--theme expects one of: " + ", ".join(sorted(THEMES)))
    pal = Palette(enabled=bool(color), theme=theme)
    yard = Yard(configmod.root_path(cfg), cfg)
    return Context(pal, cfg, yard, opts, raw, shell_eval)


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        command, operands, opts, raw, shell_eval = parse(argv)
    except ParseError as exc:
        pal = Palette(enabled=sys.stderr.isatty())
        print(pal("err", pal.glyph["cross"]) + " " + str(exc), file=sys.stderr)
        return 2

    try:
        ctx = build_context(opts, raw, shell_eval)
    except VenvyardError as exc:
        pal = Palette(enabled=sys.stderr.isatty())
        print(pal("err", pal.glyph["cross"]) + " " + str(exc), file=sys.stderr)
        return 2

    if command == "_names":
        for name in ctx.yard.names():
            print(name)
        return 0

    if command is None:
        from . import helptext
        if operands:
            near = find_command(operands[0])
            if near:
                ctx.err(f"'{operands[0]}' needs to be written as a flag: "
                        f"{ctx.pal('cmd', near.long)}"
                        + (f" or {ctx.pal('cmd', near.short)}" if near.short else ""))
                return 2
            ctx.err(f"unrecognised argument '{operands[0]}'.  "
                    f"Run {ctx.pal('cmd', 'venvyard --help')} to see the commands.")
            return 2
        if sys.stdin.isatty() and sys.stdout.isatty():
            return DISPATCH["menu"](ctx, [])
        ctx.out(helptext.brief(ctx.pal))
        return 0

    if command == "help":
        return DISPATCH["help"](ctx, operands)

    handler = DISPATCH.get(command)
    if handler is None:
        ctx.err(f"'{command}' is not implemented")
        return 2

    try:
        return handler(ctx, operands) or 0
    except VenvyardError as exc:
        ctx.err(str(exc))
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        ctx.err("interrupted")
        return 130
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except PermissionError as exc:
        ctx.err(f"permission denied: {exc}")
        return 1
    except ValueError as exc:
        # Anything that parses user input can raise this; a traceback is never
        # the right answer to a mistyped option.
        ctx.err(str(exc))
        return 2
    except OSError as exc:
        ctx.err(f"{exc}")
        return 1
