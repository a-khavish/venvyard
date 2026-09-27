"""Implementations of every venvyard command."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .colors import Spinner, Table, bar, rule, term_width, vlen
from .core import (KNOWN_VERSIONS, Venv, VenvyardError, Yard, available_pythons,
                   detect_distro, human_age, human_size, install_commands,
                   interpreter_report, iso, looks_like_venv, read_pyvenv_cfg,
                   resolve_python, validate_name)
from . import config as configmod

SORT_KEYS = ("name", "size", "python", "created", "used", "packages")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def health_glyph(ctx, venv: Venv) -> str:
    g = ctx.pal.glyph
    if venv.broken:
        return ctx.pal("err", g["cross"])
    if ctx.yard.is_active(venv):
        return ctx.pal("accent", g["star"])
    return ctx.pal("ok", g["tick"])


def sort_venvs(venvs: list, key: str, yard: Yard) -> list:
    key = (key or "name").lower()
    if key not in SORT_KEYS:
        raise VenvyardError(f"--sort expects one of: {', '.join(SORT_KEYS)}")
    if key == "size":
        yard.with_sizes(venvs)
        return sorted(venvs, key=lambda v: v.size(), reverse=True)
    if key == "python":
        def pyk(v):
            try:
                return [int(x) for x in v.python_version.split(".")]
            except ValueError:
                return [0]
        return sorted(venvs, key=pyk)
    if key == "created":
        return sorted(venvs, key=lambda v: v.created_at or 0, reverse=True)
    if key == "used":
        return sorted(venvs, key=lambda v: v.last_used or 0, reverse=True)
    if key == "packages":
        return sorted(venvs, key=lambda v: v.package_count, reverse=True)
    return sorted(venvs, key=lambda v: v.name.lower())


def select(ctx, names: list, allow_empty_all: bool = False) -> list:
    """Resolve operand names into Venv objects."""
    if not names:
        if allow_empty_all or ctx.opts.get("all"):
            return ctx.yard.list()
        raise VenvyardError("no environment name given")
    return [ctx.yard.get(n) for n in names]


def venv_json(venv: Venv, with_packages: bool = False) -> dict:
    healthy, problems = venv.health()
    data = {
        "name": venv.name,
        "path": str(venv.path),
        "python_version": venv.python_version,
        "base_interpreter": venv.base_prefix,
        "system_site_packages": venv.system_site_packages,
        "packages": venv.package_count,
        "size_bytes": venv.size(),
        "size_human": human_size(venv.size()),
        "created_at": venv.created_at,
        "created_iso": iso(venv.created_at),
        "last_used": venv.last_used,
        "last_used_iso": iso(venv.last_used),
        "origin": venv.origin,
        "description": venv.description,
        "tags": venv.tags,
        "healthy": healthy,
        "problems": problems,
    }
    if with_packages:
        data["package_list"] = [{"name": n, "version": v} for n, v in venv.packages()]
    return data


# ---------------------------------------------------------------------------
# seeing what you have
# ---------------------------------------------------------------------------

def act_list(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = [ctx.yard.get(n) for n in names] if names else ctx.yard.list()
    if ctx.opts.get("broken"):
        venvs = [v for v in venvs if v.broken]
    venvs = sort_venvs(venvs, ctx.opts.get("sort", "name"), ctx.yard)

    if ctx.json:
        ctx.yard.with_sizes(venvs)
        ctx.emit_json({"root": str(ctx.yard.root),
                       "count": len(venvs),
                       "environments": [venv_json(v) for v in venvs]})
        return 0

    if not venvs:
        if not ctx.yard.root.is_dir():
            ctx.info(f"The yard {p('path', ctx.yard.root)} does not exist yet.")
        else:
            ctx.info(f"The yard {p('path', ctx.yard.root)} is empty.")
        ctx.info(f"Create your first environment with "
                 f"{p('cmd', 'venvyard --create NAME')}")
        return 0

    show_size = ctx.cfg.get("list_show_size", True)
    if show_size:
        with Spinner(p, "measuring environments"):
            ctx.yard.with_sizes(venvs)

    cols = [("", "<", 2), ("NAME", "<", 30), ("PYTHON", "<", 9), ("PKGS", ">", 5)]
    if show_size:
        cols.append(("SIZE", ">", 9))
    cols += [("CREATED", "<", 10), ("LAST USED", "<", 10), ("NOTES", "<", 30)]
    table = Table(p, cols)
    for v in venvs:
        notes = []
        if v.description:
            notes.append(p("text", v.description))
        if v.tags:
            notes.append(p("accent", " ".join("#" + t for t in v.tags)))
        row = [health_glyph(ctx, v), p("name", v.name), p("info", v.python_version),
               p("num", v.package_count)]
        if show_size:
            row.append(p("num", human_size(v.size())))
        row += [p("dim", human_age(v.created_at)), p("dim", human_age(v.last_used)),
                "  ".join(notes)]
        table.add(*row)
    ctx.out(table.render())

    total = sum(v.size() for v in venvs) if show_size else 0
    broken = [v for v in venvs if v.broken]
    summary = f"{len(venvs)} environment{'s' if len(venvs) != 1 else ''}"
    if show_size:
        summary += f", {human_size(total)} in {ctx.yard.root}"
    if any(ctx.yard.is_active(v) for v in venvs):
        summary += f"   {g['star']} = active in this shell"
    ctx.out(p("dim", "  " + summary))
    if broken:
        ctx.out("  " + p("warn", f"{g['warn']} {len(broken)} need attention: ")
                + p("name", ", ".join(v.name for v in broken))
                + p("dim", "   run ") + p("cmd", "venvyard --doctor"))
    return 0


def act_info(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = select(ctx, names)
    if ctx.json:
        ctx.emit_json([venv_json(v, with_packages=True) for v in venvs])
        return 0
    for idx, v in enumerate(venvs):
        if idx:
            ctx.out("")
        healthy, problems = v.health()
        ctx.out(rule(p, v.name))
        rows = [
            ("Path", p("path", v.path)),
            ("Python", p("info", v.python_version) + p("dim", f"   (base: {v.base_prefix})")),
            ("Interpreter", p("path", v.python)),
            ("Packages", p("num", v.package_count)),
            ("Size on disk", p("num", human_size(v.size()))),
            ("Created", p("text", iso(v.created_at)) + p("dim", f"   {human_age(v.created_at)}")),
            ("Last used", p("text", iso(v.last_used)) + p("dim", f"   {human_age(v.last_used)}")),
            ("Origin", p("text", v.origin or "unknown")),
            ("System packages", p("text", "visible" if v.system_site_packages else "isolated")),
        ]
        if v.description:
            rows.append(("Description", p("text", v.description)))
        if v.tags:
            rows.append(("Tags", p("accent", " ".join("#" + t for t in v.tags))))
        pipv = v.pip_version()
        rows.append(("pip", p("info", pipv)))
        if ctx.yard.is_active(v):
            rows.append(("Status", p("ok", g["tick"] + " active in this shell")))
        rows.append(("Health", p("ok", g["tick"] + " healthy") if healthy
                     else p("err", g["cross"] + " " + str(len(problems)) + " problem(s)")))
        for label, value in rows:
            ctx.out("  " + p("key", (label + ":").ljust(18)) + " " + str(value))
        if problems:
            ctx.out("")
            for prob in problems:
                ctx.out("  " + p("err", g["cross"]) + " " + p("text", prob))
            ctx.out("  " + p("dim", "Try ") + p("cmd", f'venvyard --repair {shlex.quote(v.name)}'))
        ctx.out("")
        ctx.out("  " + p("dim", "Activate with ") + p("cmd", f"venvyard -a {shlex.quote(v.name)}")
                + p("dim", "   packages with ") + p("cmd", f"venvyard -p {shlex.quote(v.name)}"))
    return 0


def act_packages(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = select(ctx, names)
    payload = {}
    for idx, v in enumerate(venvs):
        if ctx.opts.get("pip"):
            proc = v.pip(["list", "--format=json"], timeout=180)
            try:
                pkgs = [(d["name"], d["version"]) for d in json.loads(proc.stdout or "[]")]
            except Exception:
                pkgs = v.packages()
        else:
            pkgs = v.packages()
        payload[v.name] = [{"name": n, "version": ver} for n, ver in pkgs]
        if ctx.json:
            continue
        if idx:
            ctx.out("")
        ctx.out(rule(p, f"{v.name}  {g['dot']}  {len(pkgs)} packages  {g['dot']}  "
                        f"Python {v.python_version}"))
        if not pkgs:
            ctx.out("  " + p("dim", "nothing installed yet"))
            continue
        width = term_width()
        longest = max(len(n) for n, _ in pkgs) + 2
        colw = longest + 12
        per_row = max(1, min(4, (width - 2) // colw))
        cells = [f"{p('name', n)}{' ' * (longest - len(n))}{p('dim', ver or '?')}"
                 for n, ver in pkgs]
        for i in range(0, len(cells), per_row):
            chunk = cells[i:i + per_row]
            ctx.out("  " + "".join(c + " " * max(1, colw - vlen(c)) for c in chunk).rstrip())
    if ctx.json:
        ctx.emit_json(payload)
    return 0


def act_search(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if not names:
        raise VenvyardError("give something to search for, e.g. venvyard --search api")
    pattern = names[0]
    hits = ctx.yard.search(pattern, in_packages=bool(ctx.opts.get("in_packages")))
    if ctx.json:
        ctx.emit_json({"pattern": pattern,
                       "matches": [dict(venv_json(v), matched_on=why) for v, why in hits]})
        return 0
    if not hits:
        ctx.info(f"Nothing matched {p('name', pattern)}.")
        if not ctx.opts.get("in_packages"):
            ctx.info(f"Add {p('cmd', '--in-packages')} to search inside installed packages too.")
        return 1
    ctx.out(rule(p, f"{len(hits)} match{'es' if len(hits) != 1 else ''} for '{pattern}'"))
    for v, why in hits:
        line = ("  " + health_glyph(ctx, v) + " " + p("name", v.name)
                + p("dim", f"   Python {v.python_version}  {g['dot']}  "
                           f"{v.package_count} packages  {g['dot']}  matched on {why}"))
        ctx.out(line)
        if why == "package":
            matching = [f"{n}=={ver}" for n, ver in v.packages()
                        if pattern.lower() in n.lower()]
            ctx.out("      " + p("accent", ", ".join(matching[:6])
                                 + (" ..." if len(matching) > 6 else "")))
        elif v.description:
            ctx.out("      " + p("dim", v.description))
    return 0


def act_which(ctx, names):
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --which web")
    venv = ctx.yard.get(names[0])
    target = venv.python if ctx.opts.get("python_flag") else venv.path
    ctx.raw_out(str(target))
    return 0


def act_stats(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    with Spinner(p, "measuring the yard"):
        s = ctx.yard.stats()
    if ctx.json:
        s2 = dict(s)
        for key in ("largest", "newest", "oldest_used"):
            s2[key] = s[key].name if s[key] else None
        s2["broken"] = [v.name for v in s["broken"]]
        ctx.emit_json(s2)
        return 0
    ctx.out(rule(p, "the yard at a glance"))
    ctx.out("  " + p("key", "Location:".ljust(18)) + " " + p("path", ctx.yard.root))
    ctx.out("  " + p("key", "Environments:".ljust(18)) + " " + p("num", s["count"]))
    ctx.out("  " + p("key", "Disk used:".ljust(18)) + " " + p("num", human_size(s["total_size"])))
    ctx.out("  " + p("key", "Packages:".ljust(18)) + " " + p("num", s["packages"])
            + p("dim", " installed across all environments"))
    if s["largest"]:
        ctx.out("  " + p("key", "Largest:".ljust(18)) + " " + p("name", s["largest"].name)
                + p("dim", f"  ({human_size(s['largest'].size())})"))
    if s["newest"]:
        ctx.out("  " + p("key", "Newest:".ljust(18)) + " " + p("name", s["newest"].name)
                + p("dim", f"  {human_age(s['newest'].created_at)}"))
    if s["oldest_used"] and s["count"] > 1:
        ctx.out("  " + p("key", "Least recent:".ljust(18)) + " " + p("name", s["oldest_used"].name)
                + p("dim", f"  last used {human_age(s['oldest_used'].last_used)}"))
    if s["versions"]:
        ctx.out("")
        ctx.out("  " + p("header", "By Python version", bold=True))
        total = max(1, s["count"])
        for ver, count in sorted(s["versions"].items()):
            ctx.out("    " + p("info", ver.ljust(10)) + bar(p, count / total, 20)
                    + p("num", f"  {count}"))
    if s["broken"]:
        ctx.out("")
        ctx.out("  " + p("warn", f"{g['warn']} {len(s['broken'])} environment(s) need attention: ")
                + p("name", ", ".join(v.name for v in s["broken"])))
        ctx.out("  " + p("dim", "  run ") + p("cmd", "venvyard --doctor")
                + p("dim", " for the details"))
    return 0


SIZE_SORTS = {"name": lambda v: v.name.lower(),
              "size": lambda v: -v.size(),
              "python": lambda v: v.python_version or "",
              "created": lambda v: -(v.created_at or 0),
              "used": lambda v: -(v.last_used or 0),
              "packages": lambda v: -v.package_count}


def act_size(ctx, names):
    p = ctx.pal
    venvs = [ctx.yard.get(n) for n in names] if names else ctx.yard.list()
    if not venvs:
        ctx.info("Nothing to measure yet.")
        return 0
    with Spinner(p, "measuring environments"):
        ctx.yard.with_sizes(venvs)
    # --sort is documented for --size but was ignored here entirely.
    sort_key = (ctx.opts.get("sort") or "size").strip().lower()
    if sort_key not in SIZE_SORTS:
        raise VenvyardError("--sort expects one of: "
                            + ", ".join(SIZE_SORTS))
    venvs = sorted(venvs, key=SIZE_SORTS[sort_key])
    if ctx.json:
        ctx.emit_json([{"name": v.name, "size_bytes": v.size(),
                        "size_human": human_size(v.size())} for v in venvs])
        return 0
    total = sum(v.size() for v in venvs) or 1
    ctx.out(rule(p, "disk usage"))
    width = max(10, min(30, term_width() - 55))
    for v in venvs:
        ctx.out("  " + p("name", v.name[:26].ljust(26)) + " "
                + bar(p, v.size() / total, width) + " "
                + p("num", human_size(v.size()).rjust(9))
                + p("dim", f"  {v.size() / total * 100:4.1f}%"))
    ctx.out("  " + p("dim", "-" * 26) + " " + " " * width + " "
            + p("num", human_size(total).rjust(9), bold=True) + p("dim", "  total"))
    return 0


# ---------------------------------------------------------------------------
# creating and reshaping
# ---------------------------------------------------------------------------

def act_create(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    export_file = ctx.opts.get("from_export")
    spec = None
    if export_file:
        path = Path(os.path.expanduser(export_file))
        if not path.is_file():
            raise VenvyardError(f"export file not found: {path}")
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise VenvyardError(f"{path} is not a readable export file: {exc}") from exc
        # Valid JSON of the wrong shape used to get past this and blow up later
        # with an AttributeError or a KeyError deep in the package list.
        if not isinstance(spec, dict):
            raise VenvyardError(
                f"{path} is not a venvyard export file "
                f"(expected an object, found {type(spec).__name__}).\n"
                f"  Write one with venvyard --export NAME -o FILE")
        raw_packages = spec.get("packages", [])
        if not isinstance(raw_packages, list) or any(
                not isinstance(d, dict) or not d.get("name") for d in raw_packages):
            raise VenvyardError(
                f"{path} has a malformed package list; "
                f"each entry needs at least a \"name\".")
        if not names:
            names = [spec.get("name", "restored")]
    if not names:
        raise VenvyardError("give a name, e.g. venvyard --create web")

    packages = list(ctx.opts.get("with_packages") or [])
    if spec:
        packages += [f"{d['name']}=={d['version']}" if d.get("version") else d["name"]
                     for d in spec.get("packages", [])]
    python = ctx.opts.get("python") or (spec or {}).get("python_version") or None

    if ctx.dry_run:
        for n in names:
            ctx.out(p("dim", "would create ") + p("name", n)
                    + p("dim", f" in {ctx.yard.root}"
                               + (f" with Python {python}" if python else "")))
        return 0

    made, failed = [], []
    for name in names:
        try:
            with Spinner(p, f"creating {name}") as sp:
                venv = ctx.yard.create(
                    name,
                    python=python,
                    system_site=bool(ctx.opts.get("system_site")),
                    requirements=ctx.opts.get("requirements"),
                    packages=packages or None,
                    upgrade_pip=not ctx.opts.get("no_pip_upgrade")
                                and ctx.cfg.get("with_pip_upgrade", True),
                    description=ctx.opts.get("desc", "") or (spec or {}).get("description", ""),
                    tags=ctx.opts.get("tags") or (spec or {}).get("tags"),
                    without_pip=bool(ctx.opts.get("without_pip")),
                    progress=sp.update,
                )
            made.append(venv)
            ctx.ok(f"created {p('name', venv.name)} "
                   + p("dim", f"Python {venv.python_version}, "
                              f"{venv.package_count} packages, {human_size(venv.size())}"))
        except VenvyardError as exc:
            failed.append((name, str(exc)))
            ctx.err(str(exc))
    if made:
        first = made[0]
        ctx.out("")
        ctx.out("  " + p("dim", "Activate it with ")
                + p("cmd", f"venvyard -a {shlex.quote(first.name)}"))
        ctx.out("  " + p("dim", "Install into it with ")
                + p("cmd", f"venvyard --install {shlex.quote(first.name)} requests"))
    return 1 if failed else 0


def act_delete(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if not names:
        raise VenvyardError("give at least one name, e.g. venvyard --delete old")
    venvs, missing = [], []
    for n in names:
        try:
            venvs.append(ctx.yard.get(n))
        except VenvyardError as exc:
            missing.append(str(exc))
    for m in missing:
        ctx.err(m)
    if not venvs:
        return 1
    active = [v for v in venvs if ctx.yard.is_active(v)]
    if active and not ctx.opts.get("force"):
        ctx.err(f"'{active[0].name}' is active in this shell right now.")
        ctx.out("  " + p("dim", "Leave it first with ") + p("cmd", "venvyard -D")
                + p("dim", ", or delete it anyway with ") + p("cmd", "--force"))
        return 1

    ctx.yard.with_sizes(venvs)
    total = sum(v.size() for v in venvs)

    ctx.out(p("warn", f"{g['warn']} About to permanently delete "
                      f"{len(venvs)} environment{'s' if len(venvs) != 1 else ''}:"))
    for v in venvs:
        ctx.out("    " + p("name", v.name) + p("dim", f"   {human_size(v.size())}, "
                                                      f"{v.package_count} packages, "
                                                      f"last used {human_age(v.last_used)}"))
    ctx.out("  " + p("dim", f"reclaiming {human_size(total)} from {ctx.yard.root}"))
    if ctx.dry_run:
        ctx.info("--dry-run: nothing was deleted.")
        return 0
    if not ctx.confirm(f"Delete {len(venvs)} environment(s)?"):
        ctx.info("Nothing was deleted.")
        return 1
    failed = 0
    for v in venvs:
        try:
            ctx.yard.delete(v.name)
            ctx.ok(f"deleted {p('name', v.name)}")
        except (VenvyardError, OSError) as exc:
            failed += 1
            ctx.err(f"could not delete {v.name}: {exc}")
    if not failed:
        ctx.out("  " + p("dim", f"{human_size(total)} reclaimed"))
    return 1 if failed else 0


PAST_TENSE = {"copy": "copied", "clone": "cloned", "rename": "renamed"}


def _pair_targets(ctx, names, verb):
    """Turn operands into [(old, new|None), ...]."""
    if not names:
        raise VenvyardError(f"give something to {verb}, e.g. venvyard --{verb} old=new")
    # An existing environment wins over the OLD=NEW shape.  '=' and ':' are
    # legal in names, so splitting first made 'vy --copy data=v2' duplicate
    # 'data' instead of the environment actually called 'data=v2'.
    seps = [n for n in names
            if ("=" in n or ":" in n) and not ctx.yard.exists(n.strip())]
    if seps:
        pairs = []
        for token in names:
            if ctx.yard.exists(token.strip()):
                pairs.append((token.strip(), None))
                continue
            if "=" in token:
                old, _, new = token.partition("=")
            elif ":" in token:
                old, _, new = token.partition(":")
            else:
                old, new = token, ""
            pairs.append((old.strip(), new.strip() or None))
        return pairs
    if len(names) == 2:
        return [(names[0], names[1])]
    return [(n, None) for n in names]


def _pair_op(ctx, names, verb, fn, extra_note=""):
    p = ctx.pal
    pairs = _pair_targets(ctx, names, verb)
    if ctx.dry_run:
        for old, new in pairs:
            ctx.yard.get(old)
            target = new or ctx.yard.auto_name(old)
            ctx.out(p("dim", f"would {verb} ") + p("name", old)
                    + p("dim", " to ") + p("name", target))
        return 0
    failed = 0
    for old, new in pairs:
        try:
            with Spinner(p, f"{verb}: {old}") as sp:
                result = fn(old, new, sp)
            ctx.ok(f"{PAST_TENSE.get(verb, verb + 'd')} {p('name', old)} "
                   + p("dim", "->") + " "
                   + p("name", result.name)
                   + p("dim", f"   {result.package_count} packages, "
                              f"{human_size(result.size())}"))
        except VenvyardError as exc:
            failed += 1
            ctx.err(str(exc))
    if extra_note and not failed:
        ctx.out("  " + p("dim", extra_note))
    return 1 if failed else 0


def act_rename(ctx, names):
    p = ctx.pal
    was_active = None
    for old, _new in _pair_targets(ctx, names, "rename"):
        try:
            if ctx.yard.is_active(ctx.yard.get(old)):
                was_active = old
        except VenvyardError:
            pass
    rc = _pair_op(ctx, names, "rename",
                  lambda old, new, sp: ctx.yard.rename(old, new),
                  "Paths inside the environment were rewritten, so it still works.")
    if was_active and rc == 0:
        ctx.out("  " + p("warn", ctx.pal.glyph["warn"])
                + p("text", f" '{was_active}' was active in this shell. The old path is "
                            f"gone, so activate it again under its new name."))
    return rc


def act_copy(ctx, names):
    return _pair_op(ctx, names, "copy",
                    lambda old, new, sp: ctx.yard.copy(old, new, progress=sp.update))


def act_clone(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    python = ctx.opts.get("python")
    made = []

    def _do(old, new, sp):
        result = ctx.yard.clone(old, new, python=python, progress=sp.update)
        made.append(result)
        return result

    rc = _pair_op(ctx, names, "clone", _do)
    for venv in made:
        skipped = venv.meta.get("clone_skipped_editable") or []
        if skipped:
            ctx.out("  " + p("warn", g["warn"]) + " "
                    + p("text", f"{len(skipped)} editable install(s) were not carried "
                                f"into '{venv.name}':"))
            for line in skipped[:5]:
                ctx.out("      " + p("dim", line))
            ctx.out("      " + p("dim", "reinstall them with ")
                    + p("cmd", f"venvyard --install {shlex.quote(venv.name)} -e PATH"))
    return rc


def act_import(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("give a path, e.g. venvyard --import ~/projects/site/.venv")
    move = not ctx.opts.get("keep")
    as_name = ctx.opts.get("as_name")
    if as_name and len(names) > 1:
        raise VenvyardError("--as can only be used when importing a single environment")
    failed = 0
    for raw in names:
        src = Path(os.path.expanduser(raw))
        if ctx.dry_run:
            ctx.out(p("dim", f"would {'move' if move else 'copy'} ") + p("path", src)
                    + p("dim", " into ") + p("path", ctx.yard.root))
            continue
        try:
            with Spinner(p, f"importing {src.name}"):
                venv = ctx.yard.adopt(src, new=as_name, move=move)
            ctx.ok(f"imported {p('path', src)} " + p("dim", "as") + " " + p("name", venv.name)
                   + p("dim", f"   {venv.package_count} packages, {human_size(venv.size())}"))
            if move:
                ctx.out("    " + p("dim", "the original location is now empty"))
        except VenvyardError as exc:
            failed += 1
            ctx.err(str(exc))
    return 1 if failed else 0


def act_scan(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    roots = names or ctx.cfg.get("scan_roots") or ["~"]
    with Spinner(p, "scanning") as sp:
        found = ctx.yard.scan(roots=roots, progress=sp.update)
    if ctx.json:
        ctx.emit_json([{"path": str(f), "python": read_pyvenv_cfg(f).get("version", "unknown"),
                        "size_bytes": Venv(f.name, f).size()} for f in found])
        return 0
    if not found:
        ctx.ok(f"No virtual environments found outside the yard in "
               + ", ".join(str(Path(os.path.expanduser(r))) for r in roots))
        return 0
    ctx.out(rule(p, f"{len(found)} environment(s) outside the yard"))
    table = Table(p, [("PATH", "<", 58), ("PYTHON", "<", 9), ("SIZE", ">", 9)])
    total = 0
    for f in found:
        v = Venv(f.name, f)
        size = v.size()
        total += size
        table.add(p("path", str(f)), p("info", v.python_version), p("num", human_size(size)))
    ctx.out(table.render())
    ctx.out("  " + p("dim", f"{human_size(total)} in total"))
    if ctx.opts.get("import_found"):
        if not ctx.confirm(f"Import all {len(found)} into {ctx.yard.root}?"):
            ctx.info("Nothing was imported.")
            return 1
        for f in found:
            try:
                venv = ctx.yard.adopt(f, move=True)
                ctx.ok(f"imported {p('name', venv.name)}")
            except VenvyardError as exc:
                ctx.err(str(exc))
    else:
        ctx.out("")
        ctx.out("  " + p("dim", "Adopt one with   ")
                + p("cmd", f"venvyard --import {shlex.quote(str(found[0]))}"))
        ctx.out("  " + p("dim", "Adopt them all   ")
                + p("cmd", "venvyard --scan --import-found"))
    return 0


def act_prune(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    raw_days = ctx.opts.get("days")
    if raw_days is None:
        raw_days = ctx.cfg.get("prune_days", 90)
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        raise VenvyardError(
            f"--days expects a whole number of days, got {raw_days!r}") from None
    if days < 0:
        raise VenvyardError("--days cannot be negative")
    stale = ctx.yard.stale(days)
    if not stale:
        ctx.ok(f"Nothing has been unused for more than {days} days.")
        return 0
    # --delete refuses the environment that is active in this shell, and
    # README promises that; prune has to honour the same guarantee.
    active = [v for v in stale if ctx.yard.is_active(v)]
    if active and not ctx.opts.get("force"):
        stale = [v for v in stale if v not in active]
        ctx.info(f"skipping {p('name', active[0].name)} "
                 + p("dim", "- it is active in this shell (--force overrides)"))
        if not stale:
            ctx.ok("Nothing left to prune.")
            return 0
    ctx.yard.with_sizes(stale)
    stale = sorted(stale, key=lambda v: v.last_used or 0)
    total = sum(v.size() for v in stale)
    ctx.out(rule(p, f"unused for more than {days} days"))
    for v in stale:
        ctx.out("  " + p("name", v.name[:30].ljust(30))
                + p("dim", f"last used {human_age(v.last_used):>10}   ")
                + p("num", human_size(v.size()).rjust(9))
                + p("dim", f"   {v.package_count} packages"))
    ctx.out("  " + p("dim", f"{len(stale)} environment(s), {human_size(total)} reclaimable"))
    if ctx.dry_run:
        ctx.info("--dry-run: nothing was deleted.")
        return 0
    if not ctx.confirm(f"Delete these {len(stale)} environment(s)?"):
        ctx.info("Nothing was deleted.")
        return 1
    for v in stale:
        try:
            ctx.yard.delete(v.name)
            ctx.ok(f"deleted {p('name', v.name)}")
        except (VenvyardError, OSError) as exc:
            ctx.err(f"could not delete {v.name}: {exc}")
    ctx.out("  " + p("dim", f"{human_size(total)} reclaimed"))
    return 0


# ---------------------------------------------------------------------------
# using an environment
# ---------------------------------------------------------------------------

def shell_flavour() -> str:
    """Which shell syntax to emit for --activate / --deactivate.

    The integration exports VENVYARD_SHELL; fall back to $SHELL for anyone
    calling --_shell-eval by hand.
    """
    declared = (os.environ.get("VENVYARD_SHELL") or "").strip().lower()
    if declared:
        return "fish" if "fish" in declared else "posix"
    if "fish" in os.path.basename(os.environ.get("SHELL", "")).lower():
        return "fish"
    return "posix"


def shell_name() -> str:
    """The user's shell by name, for advice that differs between shells.

    shell_flavour() answers "which syntax"; this answers "which shell", so the
    hints below can name the right rc file and the right way to load the
    snippet instead of assuming bash.
    """
    declared = (os.environ.get("VENVYARD_SHELL") or "").strip().lower()
    base = declared or os.path.basename(os.environ.get("SHELL", "")).lower()
    for known in ("fish", "zsh", "bash"):
        if known in base:
            return known
    return "bash"


def integration_hint():
    """(command that loads the integration now, rc file that makes it stick)."""
    name = shell_name()
    if name == "fish":
        return ("venvyard --shell-init fish | source",
                "~/.config/fish/config.fish")
    return ('eval "$(venvyard --shell-init %s)"' % name, "~/.%src" % name)


def act_activate(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --activate web")
    venv = ctx.yard.get(names[0])
    healthy, problems = venv.health()
    if not healthy and not ctx.opts.get("force"):
        raise VenvyardError(
            f"'{venv.name}' is not healthy: {problems[0]}\n"
            f"  Fix it with: venvyard --repair {shlex.quote(venv.name)}\n"
            f"  Or activate anyway with --force")
    venv.touch_used()
    if ctx.shell_eval:
        current = os.environ.get("VIRTUAL_ENV")
        flavour = shell_flavour()
        lines = []
        if current and Path(current) != venv.path:
            lines.append(venv.deactivate_command(flavour))
            ctx.note(p("dim", f"leaving {Path(current).name} first"))
        lines.append(venv.activate_command(flavour))
        ctx.shell_out("\n".join(lines))
        ctx.note(p("ok", g["tick"]) + " " + p("name", venv.name) + " "
                 + p("dim", f"active  (Python {venv.python_version}, "
                            f"{venv.package_count} packages)"))
        return 0
    ctx.out(p("warn", f"{g['warn']} The shell integration is not loaded in this shell, so "
                      f"venvyard cannot change it from here."))
    ctx.out("")
    ctx.out("  " + p("text", "A program can never modify the shell that started it - that is "
                             "why every tool"))
    ctx.out("  " + p("text", "that does this ships a shell function. Pick whichever suits you:"))
    ctx.out("")
    load_cmd, rc_file = integration_hint()
    ctx.out("  " + p("header", "1. Load the integration now (this shell only)", bold=True))
    ctx.out("     " + p("cmd", load_cmd))
    ctx.out("     " + p("dim", "then ") + p("cmd", f"venvyard -a {shlex.quote(venv.name)}")
            + p("dim", f" works, and so does every future one if you add it to {rc_file}"))
    ctx.out("")
    ctx.out("  " + p("header", "2. Open a subshell with it active (always works)", bold=True))
    ctx.out("     " + p("cmd", f"venvyard --shell {shlex.quote(venv.name)}"))
    ctx.out("")
    ctx.out("  " + p("header", "3. Source it by hand, just this once", bold=True))
    ctx.out("     " + p("cmd", venv.activate_command(shell_flavour())))
    return 3


def act_deactivate(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    current = os.environ.get("VIRTUAL_ENV")
    if ctx.shell_eval:
        if not current:
            ctx.note(p("dim", "no environment is active in this shell"))
            ctx.shell_out(":")
            return 0
        from .core import Venv
        ctx.shell_out(Venv.deactivate_command(shell_flavour()))
        ctx.note(p("ok", g["tick"]) + " " + p("dim", f"left {Path(current).name}"))
        return 0
    if not current:
        ctx.info("No environment is active in this shell.")
        return 0
    ctx.out(p("warn", f"{g['warn']} The shell integration is not loaded, so venvyard cannot "
                      f"change this shell."))
    ctx.out("  " + p("text", f"Currently active: ") + p("name", Path(current).name))
    ctx.out("  " + p("dim", "Run ") + p("cmd", "deactivate")
            + p("dim", " directly, or load the integration with ")
            + p("cmd", integration_hint()[0]))
    return 3


def act_shell(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --shell web")
    venv = ctx.yard.get(names[0])
    healthy, problems = venv.health()
    if not healthy and not ctx.opts.get("force"):
        raise VenvyardError(f"'{venv.name}' is not healthy: {problems[0]}\n"
                            f"  Fix it with: venvyard --repair {shlex.quote(venv.name)}")
    venv.touch_used()
    shell = os.environ.get("SHELL") or "/bin/bash"
    base = os.path.basename(shell)
    ctx.note(p("ok", g["tick"]) + " " + p("dim", f"opening a {base} with ")
             + p("name", venv.name) + p("dim", " active - type ") + p("cmd", "exit")
             + p("dim", " to come back"))
    env = dict(os.environ)
    env["VENVYARD_ACTIVE"] = venv.name
    activate = str(venv.activate_script)

    if base == "bash":
        fd, rc = tempfile.mkstemp(prefix="venvyard-rc-", suffix=".sh")
        with os.fdopen(fd, "w") as fh:
            fh.write(f'[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n')
            fh.write(f". {shlex.quote(activate)}\n")
            fh.write(f'rm -f {shlex.quote(rc)}\n')
        os.execve(shell, [shell, "--rcfile", rc, "-i"], env)
    elif base in ("sh", "dash", "ash"):
        # dash -- the usual /bin/sh -- has no --rcfile and exits on it, so the
        # promised subshell never appeared and the rc file, which deleted
        # itself from inside, was left behind in /tmp every time.  An
        # interactive sh reads $ENV instead.
        fd, rc = tempfile.mkstemp(prefix="venvyard-rc-", suffix=".sh")
        with os.fdopen(fd, "w") as fh:
            fh.write(f". {shlex.quote(activate)}\n")
            fh.write(f'rm -f {shlex.quote(rc)}\n')
        env["ENV"] = rc
        os.execve(shell, [shell, "-i"], env)
    elif base == "fish":
        fish_activate = str(venv.activate_script_for("fish"))
        os.execve(shell, [shell, "-i", "-C", f"source {shlex.quote(fish_activate)}"], env)
    elif base == "zsh":
        zdot = tempfile.mkdtemp(prefix="venvyard-zdot-")
        with open(os.path.join(zdot, ".zshrc"), "w") as fh:
            fh.write(f'[ -f "$HOME/.zshrc" ] && . "$HOME/.zshrc"\n')
            fh.write(f". {shlex.quote(activate)}\n")
            fh.write(f'rm -rf {shlex.quote(zdot)}\n')
        env["ZDOTDIR"] = zdot
        os.execve(shell, [shell, "-i"], env)
    else:
        env["VIRTUAL_ENV"] = str(venv.path)
        env["PATH"] = f"{venv.bin}{os.pathsep}" + env.get("PATH", "")
        env.pop("PYTHONHOME", None)
        os.execve(shell, [shell, "-i"], env)
    return 0


def act_run(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --run web pytest")
    venv = ctx.yard.get(names[0])
    command = list(ctx.raw)
    if not command:
        raise VenvyardError(f"give a command to run, e.g. "
                            f"venvyard --run {shlex.quote(venv.name)} python -V")
    venv.touch_used()
    if ctx.dry_run:
        ctx.out(p("dim", "would run ") + p("cmd", " ".join(shlex.quote(c) for c in command))
                + p("dim", " in ") + p("name", venv.name))
        return 0
    if ctx.verbose:
        ctx.note(p("dim", f"in {venv.name}: ") + p("cmd", " ".join(command)))
    exe = shutil.which(command[0], path=str(venv.bin)) or command[0]
    proc = venv.run([exe, *command[1:]], capture=False)
    return proc.returncode


# ---------------------------------------------------------------------------
# packages
# ---------------------------------------------------------------------------

def act_install(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --install web requests")
    venv = ctx.yard.get(names[0])
    pkgs = list(ctx.raw)
    if not pkgs:
        raise VenvyardError(f"which packages? e.g. venvyard --install "
                            f"{shlex.quote(venv.name)} requests flask")
    if ctx.dry_run:
        ctx.out(p("dim", "would install ") + p("name", " ".join(pkgs))
                + p("dim", " into ") + p("name", venv.name))
        return 0
    venv.touch_used()
    before = venv.package_count          # must be read before pip runs
    ctx.note(p("dim", f"installing into {venv.name}: ") + p("name", " ".join(pkgs)))
    proc = venv.pip(["install", *pkgs], capture=not ctx.verbose, timeout=3600)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "") if not ctx.verbose else ""
        raise VenvyardError(f"pip failed in '{venv.name}':\n{detail.strip()[:1200]}")
    venv._pkgs = None
    ctx.ok(f"installed into {p('name', venv.name)} "
           + p("dim", f"({venv.package_count} packages now, was {before})"))
    return 0


def act_uninstall(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("which environment? e.g. venvyard --uninstall web flask")
    venv = ctx.yard.get(names[0])
    pkgs = list(ctx.raw)
    # pip uninstall always runs with -y, so a -y/--yes here is venvyard's own
    if any(flag in pkgs for flag in ("-y", "--yes")):
        ctx.yes = True
        pkgs = [x for x in pkgs if x not in ("-y", "--yes")]
    if not pkgs:
        raise VenvyardError("which packages should be removed?")
    if ctx.dry_run:
        ctx.out(p("dim", "would remove ") + p("name", " ".join(pkgs))
                + p("dim", " from ") + p("name", venv.name))
        return 0
    if not ctx.confirm(f"Remove {', '.join(pkgs)} from '{venv.name}'?"):
        ctx.info("Nothing was removed.")
        return 1
    proc = venv.pip(["uninstall", "-y", *pkgs], capture=not ctx.verbose, timeout=1800)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "") if not ctx.verbose else ""
        raise VenvyardError(f"pip failed in '{venv.name}':\n{detail.strip()[:1200]}")
    venv._pkgs = None
    ctx.ok(f"removed from {p('name', venv.name)} "
           + p("dim", f"({venv.package_count} packages left)"))
    return 0


def act_freeze(ctx, names):
    p = ctx.pal
    venvs = select(ctx, names)
    out_path = ctx.opts.get("output")
    if not out_path:
        for idx, v in enumerate(venvs):
            text = v.freeze()
            if len(venvs) > 1:
                ctx.out(p("dim", f"# {v.name}  (Python {v.python_version})"))
            ctx.raw_out(text.rstrip("\n"))
            if idx < len(venvs) - 1:
                ctx.out("")
        return 0

    target = Path(os.path.expanduser(out_path))
    if len(venvs) > 1 or out_path.endswith("/") or target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for v in venvs:
            safe = v.name.replace("/", "_").replace(" ", "_")
            path = target / f"{safe}.requirements.txt"
            path.write_text(v.freeze(), encoding="utf-8")
            ctx.ok(f"wrote {p('path', path)} " + p("dim", f"({v.package_count} packages)"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(venvs[0].freeze(), encoding="utf-8")
        ctx.ok(f"wrote {p('path', target)} "
               + p("dim", f"({venvs[0].package_count} packages from {venvs[0].name})"))
    return 0


def act_upgrade_pip(ctx, names):
    p = ctx.pal
    venvs = select(ctx, names, allow_empty_all=True)
    if not venvs:
        ctx.info("No environments to upgrade.")
        return 0
    if ctx.dry_run:
        for v in venvs:
            ctx.out(p("dim", "would upgrade pip, setuptools and wheel in ") + p("name", v.name))
        return 0
    failed = 0
    for v in venvs:
        before = v.pip_version()
        with Spinner(p, f"upgrading pip in {v.name}"):
            proc = v.pip(["install", "--upgrade", "pip", "setuptools", "wheel"], timeout=900)
        if proc.returncode != 0:
            failed += 1
            ctx.err(f"{v.name}: {(proc.stderr or proc.stdout or '').strip()[:200]}")
            continue
        after = v.pip_version()
        if before == after:
            ctx.ok(f"{p('name', v.name)} " + p("dim", f"already on pip {after}"))
        else:
            ctx.ok(f"{p('name', v.name)} " + p("dim", f"pip {before} -> ") + p("info", after))
    return 1 if failed else 0


def act_outdated(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = select(ctx, names)
    payload = {}
    for idx, v in enumerate(venvs):
        with Spinner(p, f"checking {v.name} against PyPI"):
            try:
                rows = v.outdated()
            except VenvyardError as exc:
                ctx.err(str(exc))
                continue
        payload[v.name] = rows
        if ctx.json:
            continue
        if idx:
            ctx.out("")
        if not rows:
            ctx.ok(f"{p('name', v.name)} " + p("dim", "is fully up to date"))
            continue
        ctx.out(rule(p, f"{v.name}: {len(rows)} package(s) have newer releases"))
        table = Table(p, [("PACKAGE", "<", 34), ("INSTALLED", "<", 14),
                          ("LATEST", "<", 14), ("TYPE", "<", 8)])
        for r in rows:
            table.add(p("name", r.get("name", "?")), p("dim", r.get("version", "?")),
                      p("ok", r.get("latest_version", "?")), p("dim", r.get("latest_filetype", "")))
        ctx.out(table.render())
        ctx.out("  " + p("dim", "Upgrade one with ")
                + p("cmd", f"venvyard --install {shlex.quote(v.name)} -U "
                           f"{rows[0].get('name', 'PKG')}"))
    if ctx.json:
        ctx.emit_json(payload)
    return 0


def act_export(ctx, names):
    p = ctx.pal
    venvs = select(ctx, names)
    out_path = ctx.opts.get("output")
    for v in venvs:
        data = {
            "venvyard_export": 1,
            "exported_at": iso(time.time()),
            "name": v.name,
            "python_version": ".".join(v.python_version.split(".")[:2]),
            "python_full": v.python_version,
            "description": v.description,
            "tags": v.tags,
            "system_site_packages": v.system_site_packages,
            "packages": [{"name": n, "version": ver} for n, ver in v.packages()],
        }
        text = json.dumps(data, indent=2) + "\n"
        if not out_path:
            ctx.raw_out(text.rstrip("\n"))
            continue
        target = Path(os.path.expanduser(out_path))
        if len(venvs) > 1 or out_path.endswith("/") or target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            target = target / f"{v.name.replace(' ', '_')}.venvyard.json"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        ctx.ok(f"exported {p('name', v.name)} " + p("dim", "to ") + p("path", target))
        ctx.out("  " + p("dim", "Rebuild it anywhere with ")
                + p("cmd", f"venvyard --create NEWNAME --from-export {shlex.quote(str(target))}"))
    return 0


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

def act_describe(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError('usage: venvyard --describe NAME "some text"')
    venv = ctx.yard.get(names[0])
    text = " ".join(ctx.raw).strip()
    venv.write_meta(description=text)
    if text:
        ctx.ok(f"{p('name', venv.name)} " + p("dim", "is now described as ") + p("text", text))
    else:
        ctx.ok(f"cleared the description on {p('name', venv.name)}")
    return 0


def act_tag(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("usage: venvyard --tag NAME tag1 tag2")
    venv = ctx.yard.get(names[0])
    new = [t.lstrip("#") for t in ctx.raw if t.strip()]
    if not new:
        raise VenvyardError("give at least one tag")
    tags = sorted(set(venv.tags) | set(new))
    venv.write_meta(tags=tags)
    ctx.ok(f"{p('name', venv.name)} " + p("dim", "tags: ")
           + p("accent", " ".join("#" + t for t in tags)))
    return 0


def act_untag(ctx, names):
    p = ctx.pal
    if not names:
        raise VenvyardError("usage: venvyard --untag NAME tag1")
    venv = ctx.yard.get(names[0])
    drop = {t.lstrip("#") for t in ctx.raw if t.strip()}
    tags = sorted(set(venv.tags) - drop)
    venv.write_meta(tags=tags)
    ctx.ok(f"{p('name', venv.name)} " + p("dim", "tags: ")
           + (p("accent", " ".join("#" + t for t in tags)) if tags else p("dim", "none")))
    return 0


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def act_doctor(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    venvs = [ctx.yard.get(n) for n in names] if names else ctx.yard.list()
    if not venvs:
        ctx.info("No environments to check.")
        return 0
    problems = {}
    for v in venvs:
        healthy, issues = v.health()
        if not healthy:
            problems[v.name] = issues
    if ctx.json:
        ctx.emit_json({"checked": len(venvs), "unhealthy": problems})
        return 0
    ctx.out(rule(p, f"checked {len(venvs)} environment(s)"))
    if not problems:
        ctx.out("  " + p("ok", g["tick"] + " everything is healthy"))
        pythons = available_pythons()
        ctx.out("  " + p("dim", f"interpreters available: ")
                + p("info", ", ".join(v for v, _ in pythons)))
        return 0
    for name, issues in problems.items():
        venv = ctx.yard.get(name)
        ctx.out("  " + p("err", g["cross"]) + " " + p("name", name))
        for issue in issues:
            ctx.out("      " + p("text", issue))
        if venv.repairable:
            ctx.out("      " + p("dim", "fix: ")
                    + p("cmd", f"venvyard --repair {shlex.quote(name)}"))
        else:
            ctx.out("      " + p("dim", "rewriting paths cannot fix this; rebuild it: ")
                    + p("cmd", f"venvyard --clone {shlex.quote(name)}=<newname>"))
    ctx.out("")
    fixable = sum(1 for name in problems if ctx.yard.get(name).repairable)
    line = f"{len(problems)} of {len(venvs)} need attention."
    if fixable:
        ctx.out("  " + p("dim", line + "  Repair them all: ")
                + p("cmd", "venvyard --repair --all"))
    else:
        ctx.out("  " + p("dim", line + "  None can be fixed by rewriting paths; "
                                       "rebuild them with ") + p("cmd", "--clone"))
    return 1


def act_repair(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if names:
        venvs = [ctx.yard.get(n) for n in names]
    elif ctx.opts.get("all"):
        venvs = [v for v in ctx.yard.list() if v.broken]
        if not venvs:
            ctx.ok("Nothing needed repairing.")
            return 0
    else:
        raise VenvyardError("give a name, or use --all to repair everything that needs it")
    if ctx.dry_run:
        for v in venvs:
            healthy, issues = v.health()
            ctx.out(p("dim", "would repair ") + p("name", v.name)
                    + p("dim", f"  ({len(issues)} issue(s))" if issues else "  (healthy)"))
        return 0
    failed = 0
    for v in venvs:
        if not v.repairable:
            ctx.err(f"'{v.name}' cannot be repaired by rewriting paths.")
            ctx.out("      " + p("text", v.health()[1][0]))
            ctx.out("      " + p("dim", "rebuild it instead: ")
                    + p("cmd", f"venvyard --clone {shlex.quote(v.name)}=<newname>"))
            failed += 1
            continue
        try:
            fixed = ctx.yard.repair(v.name)
        except VenvyardError as exc:
            failed += 1
            ctx.err(str(exc))
            continue
        if not fixed:
            ctx.ok(f"{p('name', v.name)} " + p("dim", "needed no repair"))
            continue
        ctx.ok(f"repaired {p('name', v.name)}")
        for item in fixed:
            ctx.out("      " + p("dim", g["arrow"] + " " + item))
        still_healthy, issues = ctx.yard.get(v.name).health()
        if not still_healthy:
            ctx.out("      " + p("warn", g["warn"] + " still reporting: " + issues[0]))
            ctx.out("      " + p("dim", "a clone may be quicker: ")
                    + p("cmd", f"venvyard --clone {shlex.quote(v.name)}"))
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# the tool itself
# ---------------------------------------------------------------------------

def act_pythons(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    with Spinner(p, "probing the interpreters on this machine"):
        rows = interpreter_report(ctx.yard)
    distro = detect_distro()

    if ctx.json:
        ctx.emit_json({"distro": distro, "interpreters": rows,
                       "missing": [v for v in KNOWN_VERSIONS
                                   if v not in {r.get("short") for r in rows}]})
        return 0

    if not rows:
        ctx.err("No Python interpreter could be found on PATH.")
        ctx.out("  " + p("dim", "This is unusual, since venvyard itself runs on Python."))
        _print_install_help(ctx, "", distro)
        return 1

    ctx.out(rule(p, f"Python interpreters on this machine"))
    table = Table(p, [("", "<", 2), ("VERSION", "<", 9), ("PATH", "<", 30),
                      ("VENV", "<", 6), ("PIP", "<", 10), ("ENVIRONMENTS", ">", 12)])
    for r in rows:
        usable = r.get("ok") and r.get("venv") and r.get("ensurepip")
        mark = p("ok", g["tick"]) if usable else p("warn", g["warn"])
        name = p("info", r.get("version") or r.get("short", "?"))
        if r.get("is_default"):
            name += p("dim", "*")
        venv_cell = (p("ok", "yes") if r.get("venv") and r.get("ensurepip")
                     else p("err", "no"))
        pip_cell = p("num", r.get("pip")) if r.get("pip") else p("dim", "-")
        used = r.get("environments", 0)
        table.add(mark, name, p("path", r.get("path", "")), venv_cell, pip_cell,
                  p("num", used) if used else p("dim", "none"))
    ctx.out(table.render())
    if any(r.get("is_default") for r in rows):
        ctx.out("  " + p("dim", "* the default python3 on your PATH; venvyard uses it "
                                "unless you pass --python"))

    broken = [r for r in rows if not (r.get("venv") and r.get("ensurepip"))]
    for r in broken:
        ctx.out("")
        ctx.out("  " + p("warn", g["warn"]) + " " + p("info", r.get("version", "?"))
                + p("text", " cannot create environments: ")
                + p("dim", "the venv module or pip support is missing"))
        help_ = install_commands(r.get("short", ""), want="venv")
        for cmd in help_["commands"]:
            ctx.out("      " + p("cmd", cmd))

    present = {r.get("short") for r in rows}
    missing = [v for v in KNOWN_VERSIONS if v not in present]
    if missing:
        ctx.out("")
        ctx.out("  " + p("header", "Not installed", bold=True) + " "
                + p("dim", ", ".join(missing)))
        _print_install_help(ctx, missing[0] if missing else "", distro)

    ctx.out("")
    ctx.out("  " + p("dim", "Build an environment with a specific one: ")
            + p("cmd", f"venvyard --create NAME --python {rows[0].get('short', '3.12')}"))
    return 0


def _print_install_help(ctx, version, distro):
    p = ctx.pal
    help_ = install_commands(version)
    where = distro.get("name") or "this system"
    if distro.get("manager"):
        ctx.out("  " + p("dim", f"To install one on {where}:"))
        for cmd in help_["commands"]:
            ctx.out("      " + p("cmd", cmd))
    if help_["note"]:
        ctx.out("")
        for line in help_["note"].splitlines():
            stripped = line.strip()
            if stripped.startswith(("pyenv", "uv ", "sudo")):
                ctx.out("      " + p("cmd", stripped))
            elif stripped:
                ctx.out("  " + p("dim", stripped))
            else:
                ctx.out("")


def act_config(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if ctx.opts.get("reset"):
        path = configmod.save(dict(configmod.DEFAULTS))
        ctx.ok(f"settings reset to defaults in {p('path', path)}")
        return 0
    if not names:
        path = configmod.config_file()
        ctx.out(rule(p, "settings"))
        for key in sorted(configmod.DEFAULTS):
            value = ctx.cfg.get(key, configmod.DEFAULTS[key])
            shown = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            changed = value != configmod.DEFAULTS[key]
            ctx.out("  " + p("key", key.ljust(22)) + " "
                    + (p("name", shown) if changed else p("text", shown))
                    + (p("dim", "   (default)") if not changed else ""))
        ctx.out("")
        ctx.out("  " + p("dim", "File:      ") + p("path", path)
                + (p("dim", "   (not created yet)") if not path.is_file() else ""))
        ctx.out("  " + p("dim", "Yard:      ") + p("path", ctx.yard.root))
        ctx.out("  " + p("dim", "Override the yard per command with ") + p("cmd", "--root DIR")
                + p("dim", " or the ") + p("key", "VENVYARD_HOME") + p("dim", " variable"))
        ctx.out("  " + p("dim", "Change one with ") + p("cmd", "venvyard --config KEY VALUE"))
        return 0
    key = names[0]
    if key not in configmod.DEFAULTS:
        close = ", ".join(sorted(configmod.DEFAULTS))
        raise VenvyardError(f"unknown setting '{key}'. Known settings: {close}")
    if len(names) == 1:
        value = ctx.cfg.get(key)
        ctx.raw_out(", ".join(map(str, value)) if isinstance(value, list) else str(value))
        return 0
    value = configmod.coerce(key, " ".join(names[1:]))
    stored = configmod.load_stored()
    stored[key] = value
    path = configmod.save(stored)
    ctx.ok(f"{p('key', key)} " + p("dim", "is now ") + p("name", value))
    ctx.out("  " + p("dim", f"saved to {path}"))
    if key == "root":
        ctx.out("  " + p("warn", f"{g['warn']} existing environments are not moved; "
                                 f"import them with ") + p("cmd", "venvyard --scan"))
    return 0


def act_shell_init(ctx, names):
    from . import shellint
    shell = (names[0] if names else os.path.basename(os.environ.get("SHELL", "bash")))
    ctx.raw_out(shellint.integration(shell).rstrip("\n"))
    return 0


def act_completion(ctx, names):
    from . import shellint
    shell = (names[0] if names else os.path.basename(os.environ.get("SHELL", "bash")))
    ctx.raw_out(shellint.completion(shell).rstrip("\n"))
    return 0


def act_version(ctx, names):
    p, g = ctx.pal, ctx.pal.glyph
    if ctx.json:
        ctx.emit_json({"version": __version__, "root": str(ctx.yard.root),
                       "python": sys.version.split()[0],
                       "config": str(configmod.config_file())})
        return 0
    ctx.out(p("title", f"venvyard {__version__}", bold=True))
    ctx.out("  " + p("key", "yard:".ljust(12)) + " " + p("path", ctx.yard.root)
            + p("dim", f"   {len(ctx.yard.list())} environment(s)"))
    ctx.out("  " + p("key", "settings:".ljust(12)) + " " + p("path", configmod.config_file()))
    ctx.out("  " + p("key", "running on:".ljust(12)) + " " + p("info", f"Python {sys.version.split()[0]}")
            + p("dim", f"  ({sys.executable})"))
    pys = available_pythons()
    if pys:
        ctx.out("  " + p("key", "available:".ljust(12)) + " "
                + p("info", ", ".join(v for v, _ in pys)))
    ctx.out("  " + p("key", "integration:".ljust(12)) + " "
            + (p("ok", g["tick"] + " loaded") if os.environ.get("VENVYARD_SHELL_INTEGRATION")
               else p("warn", g["warn"] + " not loaded in this shell")))
    return 0


def act_help(ctx, names):
    from . import helptext
    if names:
        page = helptext.command_help(ctx.pal, names[0])
        if page is None:
            raise VenvyardError(f"no command called '{names[0]}'. "
                                f"Run venvyard --help for the full list.")
        ctx.out(page)
        return 0
    ctx.out(helptext.full_help(ctx.pal))
    return 0


def act_menu(ctx, names):
    from .menu import run_menu
    return run_menu(ctx)


DISPATCH = {
    "list": act_list, "info": act_info, "packages": act_packages, "search": act_search,
    "which": act_which, "stats": act_stats, "size": act_size,
    "create": act_create, "delete": act_delete, "clone": act_clone, "copy": act_copy,
    "rename": act_rename, "import": act_import, "scan": act_scan, "prune": act_prune,
    "activate": act_activate, "deactivate": act_deactivate, "shell": act_shell, "run": act_run,
    "install": act_install, "uninstall": act_uninstall, "freeze": act_freeze,
    "upgrade_pip": act_upgrade_pip, "outdated": act_outdated, "export": act_export,
    "describe": act_describe, "tag": act_tag, "untag": act_untag,
    "doctor": act_doctor, "repair": act_repair,
    "pythons": act_pythons,
    "menu": act_menu, "config": act_config, "shell_init": act_shell_init,
    "completion": act_completion, "help": act_help, "version": act_version,
}
