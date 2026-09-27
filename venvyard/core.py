"""The venv engine: discovery, creation, mutation and inspection.

Every virtual environment lives as a direct child of the yard root
(``~/PY_VENV`` by default), so the "registry" is simply the directory
listing - there is no index that can drift out of sync with reality.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

META_NAME = ".venvyard.json"
BAD_NAME_CHARS = set('/\\\0')
RESERVED_NAMES = {"", ".", "..", META_NAME}


class VenvyardError(Exception):
    """Any user-facing failure."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def human_age(ts: float | None) -> str:
    if not ts:
        return "unknown"
    delta = time.time() - ts
    if delta < 0:
        return "just now"
    mins = delta / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    hours = mins / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 30:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days / 30)}mo ago"
    return f"{days / 365:.1f}y ago"


def iso(ts: float | None) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def validate_name(name: str) -> str:
    name = name.strip()
    if name in RESERVED_NAMES:
        raise VenvyardError(f"'{name}' is not a usable environment name")
    if any(ch in BAD_NAME_CHARS for ch in name):
        raise VenvyardError(f"name {name!r} may not contain '/', '\\' or null bytes")
    if name.startswith("-"):
        raise VenvyardError(f"name {name!r} may not start with '-'")
    if len(name) > 120:
        raise VenvyardError("name is too long (max 120 characters)")
    return name


def dir_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                st = os.lstat(fp)
            except OSError:
                continue
            blocks = getattr(st, "st_blocks", None)
            total += blocks * 512 if blocks is not None else st.st_size
    return total


def looks_like_venv(path: Path) -> bool:
    return (path / "pyvenv.cfg").is_file() or (
        (path / "bin" / "activate").is_file() and (path / "bin" / "python").exists()
    )


def read_pyvenv_cfg(path: Path) -> dict:
    cfg_file = path / "pyvenv.cfg"
    data: dict[str, str] = {}
    if not cfg_file.is_file():
        return data
    try:
        for line in cfg_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return data


def _is_text_file(path: Path, probe: int = 4096) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(probe)
    except OSError:
        return False
    if b"\0" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# a single environment
# ---------------------------------------------------------------------------

@dataclass
class Venv:
    name: str
    path: Path
    _meta: dict | None = field(default=None, repr=False)
    _size: int | None = field(default=None, repr=False)
    _pkgs: list | None = field(default=None, repr=False)

    # -- basic locations ---------------------------------------------------
    @property
    def bin(self) -> Path:
        return self.path / "bin"

    @property
    def python(self) -> Path:
        for cand in ("python", "python3"):
            p = self.bin / cand
            if p.exists():
                return p
        return self.bin / "python"

    @property
    def activate_script(self) -> Path:
        return self.bin / "activate"

    @property
    def meta_file(self) -> Path:
        return self.path / META_NAME

    # -- metadata ----------------------------------------------------------
    @property
    def meta(self) -> dict:
        if self._meta is None:
            data = {}
            if self.meta_file.is_file():
                try:
                    loaded = json.loads(self.meta_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:
                    data = {}
            self._meta = data
        return self._meta

    def write_meta(self, quiet: bool = False, **updates) -> None:
        """Persist metadata.

        Failures used to be swallowed, so --tag, --describe and --untag
        printed a tick on a read-only yard while nothing was written.  Callers
        that record a timestamp as a side effect pass quiet=True, since losing
        one of those should not break the command the user actually asked for.
        """
        data = dict(self.meta)
        data.update(updates)
        data.setdefault("schema", 1)
        self._meta = data
        try:
            self.meta_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        except OSError as exc:
            if quiet:
                return
            raise VenvyardError(
                f"could not write {self.meta_file}: {exc}") from exc

    def touch_used(self) -> None:
        self.write_meta(quiet=True, last_used=time.time())

    @property
    def created_at(self) -> float | None:
        value = self.meta.get("created_at")
        if isinstance(value, (int, float)):
            return float(value)
        cfg = self.path / "pyvenv.cfg"
        try:
            return (cfg if cfg.exists() else self.path).stat().st_mtime
        except OSError:
            return None

    @property
    def last_used(self) -> float | None:
        value = self.meta.get("last_used")
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return self.bin.stat().st_atime
        except OSError:
            return None

    @property
    def description(self) -> str:
        return str(self.meta.get("description", "") or "")

    @property
    def tags(self) -> list:
        tags = self.meta.get("tags")
        return sorted(tags) if isinstance(tags, list) else []

    @property
    def origin(self) -> str:
        return str(self.meta.get("origin", "") or "")

    # -- interpreter -------------------------------------------------------
    @property
    def cfg(self) -> dict:
        if not hasattr(self, "_cfg_cache"):
            self._cfg_cache = read_pyvenv_cfg(self.path)
        return self._cfg_cache

    @property
    def python_version(self) -> str:
        version = self.cfg.get("version") or self.cfg.get("version_info", "")
        if version:
            return version.split()[0]
        try:
            out = subprocess.run([str(self.python), "-V"], capture_output=True,
                                 text=True, timeout=10)
            return (out.stdout + out.stderr).strip().replace("Python ", "") or "unknown"
        except Exception:
            return "unknown"

    @property
    def base_prefix(self) -> str:
        return self.cfg.get("home", "") or "unknown"

    @property
    def system_site_packages(self) -> bool:
        return str(self.cfg.get("include-system-site-packages", "false")).lower() == "true"

    @property
    def lib_version(self) -> str | None:
        """The X.Y that site-packages was built for, e.g. '3.11'."""
        sp = self.site_packages
        if sp is None:
            return None
        m = re.search(r"python(\d+\.\d+)", sp.parent.name)
        return m.group(1) if m else None

    @property
    def interpreter_version(self) -> str | None:
        """The X.Y bin/python actually resolves to right now.

        Read from the resolved symlink name rather than by running the
        interpreter, so listing hundreds of environments stays fast.
        """
        py = self.python
        try:
            real = Path(os.path.realpath(py))
        except OSError:
            return None
        if not real.exists():
            return None
        m = re.match(r"python(\d+\.\d+)$", real.name)
        return m.group(1) if m else None

    @property
    def site_packages(self) -> Path | None:
        lib = self.path / "lib"
        if not lib.is_dir():
            return None
        for child in sorted(lib.glob("python*")):
            sp = child / "site-packages"
            if sp.is_dir():
                return sp
        return None

    # -- health ------------------------------------------------------------
    def health(self) -> tuple[bool, list]:
        """(healthy, [problem, ...])"""
        problems = []
        if not (self.path / "pyvenv.cfg").is_file():
            problems.append("pyvenv.cfg is missing")
        if not self.activate_script.is_file():
            problems.append("bin/activate is missing")
        py = self.python
        if not py.exists():
            problems.append("the interpreter bin/python is missing or a broken symlink")
        else:
            base = self.cfg.get("home", "")
            if base and not Path(base).is_dir():
                problems.append(f"the base interpreter directory {base} no longer exists")
        recorded = self.recorded_prefix()
        if recorded and Path(recorded) != self.path:
            problems.append(f"paths inside the venv still point at {recorded}")
        if self.site_packages is None:
            problems.append("site-packages could not be located")
        else:
            lib_v, real_v = self.lib_version, self.interpreter_version
            if lib_v and real_v and lib_v != real_v:
                problems.append(
                    f"the base Python moved from {lib_v} to {real_v}; the packages in "
                    f"lib/python{lib_v} are invisible to it (rebuild with --clone)")
        return (not problems), problems

    @property
    def broken(self) -> bool:
        return not self.health()[0]

    @property
    def repairable(self) -> bool:
        """False when only a rebuild can help, so we can say so up front."""
        for problem in self.health()[1]:
            if "base Python moved" in problem or "site-packages could not" in problem:
                return False
        return True

    # Python writes the venv's own path into bin/activate, but not always the
    # same way.  Up to 3.11 it is a bare `VIRTUAL_ENV=/path` at the start of a
    # line; from 3.12 it is `    export VIRTUAL_ENV=/path`, indented and inside
    # an if/else whose other branch is a `$(cygpath ...)` substitution.  An
    # expression anchored to the line start missed the 3.12 form entirely, so
    # --doctor called a hand-moved environment healthy on every modern Python.
    _PREFIX_RES = (
        re.compile(r'''^[ \t]*(?:export[ \t]+)?VIRTUAL_ENV=(?![\'"]?\$)[\'"]?(.+?)[\'"]?[ \t]*$''', re.M),
        re.compile(r'''^[ \t]*set[ \t]+-gx[ \t]+VIRTUAL_ENV[ \t]+(?![\'"]?\$)[\'"]?(.+?)[\'"]?[ \t]*$''', re.M),
    )

    def recorded_prefix(self) -> str | None:
        """The absolute path baked into the activate scripts, whatever it is now."""
        for script in (self.activate_script, self.bin / "activate.fish"):
            try:
                text = script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern in self._PREFIX_RES:
                m = pattern.search(text)
                if m:
                    found = m.group(1).strip()
                    if found:
                        return found
        return None

    # -- contents ----------------------------------------------------------
    def packages(self, refresh: bool = False) -> list:
        """[(name, version), ...] read straight from dist-info/egg-info."""
        if self._pkgs is not None and not refresh:
            return self._pkgs
        found: dict[str, str] = {}
        sp = self.site_packages
        if sp and sp.is_dir():
            try:
                entries = list(sp.iterdir())
            except OSError:
                entries = []
            for entry in entries:
                if entry.name.endswith(".dist-info") and entry.is_dir():
                    stem = entry.name[: -len(".dist-info")]
                    pkg, _, ver = stem.rpartition("-")
                    if pkg:
                        found[pkg.replace("_", "-")] = ver
                elif entry.name.endswith(".egg-info"):
                    stem = entry.name[: -len(".egg-info")]
                    pkg, _, ver = stem.rpartition("-")
                    found.setdefault((pkg or stem).replace("_", "-"), ver or "?")
        self._pkgs = sorted(found.items(), key=lambda kv: kv[0].lower())
        return self._pkgs

    @property
    def package_count(self) -> int:
        return len(self.packages())

    def size(self, refresh: bool = False) -> int:
        if self._size is None or refresh:
            self._size = dir_size(self.path)
        return self._size

    # -- running things ----------------------------------------------------
    def run(self, args: list, capture: bool = True, timeout: int | None = None,
            check: bool = False) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["VIRTUAL_ENV"] = str(self.path)
        env["PATH"] = f"{self.bin}{os.pathsep}" + env.get("PATH", "")
        env.pop("PYTHONHOME", None)
        # The installed launcher exports PYTHONPATH so it can find venvyard
        # itself; leaking that into the environment's own interpreter would
        # put venvyard on sys.path for every pip install and every --run.
        env.pop("PYTHONPATH", None)
        return subprocess.run(args, capture_output=capture, text=True, env=env,
                              timeout=timeout, check=check)

    def require_interpreter(self) -> Path:
        """The environment's interpreter, or a message saying how to fix it.

        Without this every pip-backed command died on a bare
        FileNotFoundError errno, including --info, which meant the one
        command that would have explained the breakage could not print.
        """
        py = self.python
        if not py.exists():
            raise VenvyardError(
                f"'{self.name}' has no working interpreter at {py}.\n"
                f"  Repair it with venvyard --repair {shlex.quote(self.name)}, "
                f"or inspect it with venvyard --doctor {shlex.quote(self.name)}")
        return py

    def pip(self, args: list, capture: bool = True,
            timeout: int | None = None) -> subprocess.CompletedProcess:
        return self.run([str(self.require_interpreter()), "-m", "pip",
                         "--disable-pip-version-check", *args],
                        capture=capture, timeout=timeout)

    def freeze(self) -> str:
        proc = self.pip(["freeze"], timeout=180)
        if proc.returncode != 0:
            raise VenvyardError(
                f"pip freeze failed in '{self.name}': {(proc.stderr or '').strip()[:300]}")
        return proc.stdout

    def pip_version(self) -> str:
        try:
            proc = self.pip(["--version"], timeout=60)
        except (VenvyardError, OSError, subprocess.SubprocessError):
            return "not available"
        if proc.returncode != 0:
            return "not available"
        m = re.match(r"pip\s+(\S+)", proc.stdout.strip())
        return m.group(1) if m else proc.stdout.strip()[:40]

    def outdated(self) -> list:
        proc = self.pip(["list", "--outdated", "--format=json"], timeout=300)
        if proc.returncode != 0:
            raise VenvyardError(
                f"pip could not check '{self.name}': {(proc.stderr or '').strip()[:300]}")
        try:
            return json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return []

    def activate_script_for(self, flavour: str = "posix") -> Path:
        """The activate script matching the calling shell.

        fish has its own; sourcing the POSIX one into fish just produces
        syntax errors, which is what the fish integration used to do.
        """
        if flavour == "fish":
            fish = self.bin / "activate.fish"
            if fish.is_file():
                return fish
        return self.activate_script

    def activate_command(self, flavour: str = "posix") -> str:
        target = shlex.quote(str(self.activate_script_for(flavour)))
        if flavour == "fish":
            return f"source {target}"
        return f". {target}"

    @staticmethod
    def deactivate_command(flavour: str = "posix") -> str:
        if flavour == "fish":
            return ("if functions -q deactivate; deactivate; "
                    "else; set -e VIRTUAL_ENV; end")
        return ("if type deactivate >/dev/null 2>&1; then deactivate; "
                "else unset VIRTUAL_ENV; fi")


# ---------------------------------------------------------------------------
# the yard
# ---------------------------------------------------------------------------

class Yard:
    def __init__(self, root: Path, cfg: dict | None = None):
        self.root = Path(root)
        self.cfg = cfg or {}

    # -- discovery ---------------------------------------------------------
    def ensure_root(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise VenvyardError(f"cannot create the yard at {self.root}: {exc}") from exc
        return self.root

    def list(self, include_broken: bool = True) -> list:
        if not self.root.is_dir():
            return []
        out = []
        try:
            children = sorted(self.root.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            raise VenvyardError(f"cannot read the yard at {self.root}: {exc}") from exc
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name.startswith(".") and child.name != META_NAME:
                continue
            if looks_like_venv(child):
                out.append(Venv(child.name, child))
            elif include_broken and (child / META_NAME).is_file():
                out.append(Venv(child.name, child))
        return out

    def names(self) -> list:
        return [v.name for v in self.list()]

    def exists(self, name: str) -> bool:
        return (self.root / name).exists()

    def managed(self, path: Path) -> bool:
        """True when this directory is an environment venvyard may act on.

        Mirrors list(): either it still looks like a virtual environment, or
        venvyard has metadata for it -- which covers ones broken badly enough
        that they no longer do.  Anything else is somebody's ordinary folder
        that happens to sit in the yard, and destructive commands must not
        touch it.
        """
        return looks_like_venv(path) or (path / META_NAME).is_file()

    def get(self, name: str) -> Venv:
        name = validate_name(name)
        path = self.root / name
        if not path.is_dir():
            near = self.suggest(name)
            hint = f"  Did you mean '{near}'?" if near else ""
            raise VenvyardError(f"no environment named '{name}' in {self.root}.{hint}")
        if not self.managed(path):
            raise VenvyardError(
                f"'{name}' is a directory in the yard but not a virtual "
                f"environment, so venvyard will not touch it.\n"
                f"  {path}\n"
                f"  Only environments venvyard manages can be used here; "
                f"list them with venvyard --list.")
        return Venv(name, path)

    def suggest(self, name: str) -> str | None:
        import difflib
        matches = difflib.get_close_matches(name, self.names(), n=1, cutoff=0.6)
        return matches[0] if matches else None

    def search(self, pattern: str, in_packages: bool = False) -> list:
        pat = pattern.lower()
        hits = []
        for venv in self.list():
            # Say which field matched.  Everything used to report "name", so a
            # tag hit claimed to have matched a name that did not contain the
            # pattern at all.
            if pat in venv.name.lower():
                hits.append((venv, "name"))
                continue
            if any(pat in tag.lower() for tag in venv.tags):
                hits.append((venv, "tag"))
                continue
            if pat in venv.description.lower():
                hits.append((venv, "description"))
                continue
            if in_packages and any(pat in pkg.lower() for pkg, _ in venv.packages()):
                hits.append((venv, "package"))
        return hits

    # -- naming ------------------------------------------------------------
    def auto_name(self, base: str) -> str:
        style = self.cfg.get("autoname_style", "paren")
        if not self.exists(base):
            return base
        for i in range(1, 10000):
            cand = f"{base}({i})" if style == "paren" else f"{base}-{i}"
            if not self.exists(cand):
                return cand
        raise VenvyardError(f"could not find a free name based on '{base}'")

    # -- create ------------------------------------------------------------
    def create(self, name: str, python: str | None = None, system_site: bool = False,
               requirements: str | None = None, packages: list | None = None,
               upgrade_pip: bool = True, description: str = "",
               tags: list | None = None, without_pip: bool = False,
               progress=None) -> Venv:
        name = validate_name(name)
        if name.startswith("."):
            # list() skips dot directories, so a dot-named environment was
            # creatable but then invisible to --list, --stats, --doctor,
            # --prune and completion while still occupying disk.
            raise VenvyardError(
                f"name {name!r} may not start with '.'; venvyard would not "
                f"be able to list it")
        target = self.root / name
        if target.exists():
            raise VenvyardError(f"'{name}' already exists at {target}")
        self.ensure_root()

        interpreter = resolve_python(python or self.cfg.get("default_python") or "")
        cmd = [interpreter, "-m", "venv"]
        if system_site:
            cmd.append("--system-site-packages")
        if without_pip:
            cmd.append("--without-pip")
        cmd.append(str(target))

        if progress:
            progress(f"creating '{name}' with {interpreter}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except KeyboardInterrupt:
            shutil.rmtree(target, ignore_errors=True)
            raise
        if proc.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            err = (proc.stderr or proc.stdout or "").strip()
            if "ensurepip" in err or "python3-venv" in err:
                err += ("\n\nThe venv module is present but pip support is missing. "
                        "On Debian/Ubuntu install it with:\n"
                        "    sudo apt install python3-venv")
            raise VenvyardError(f"could not create '{name}':\n{err}")

        venv = Venv(name, target)
        venv._partial = True
        venv.write_meta(
            created_at=time.time(),
            created_with=interpreter,
            python_version=venv.python_version,
            origin="created",
            description=description,
            tags=sorted(set(tags or [])),
            system_site_packages=bool(system_site),
            venvyard_version=_version(),
        )

        # Everything from here on is the long part -- pip -- and interrupting
        # it used to leave the directory behind, after which --create refused
        # the same name.  README says an interrupted creation cleans up, so
        # make that true for the whole of it, not just the venv call.
        try:
            if not without_pip and upgrade_pip:
                if progress:
                    progress(f"upgrading pip in '{name}'")
                venv.pip(["install", "--upgrade", "pip", "setuptools", "wheel"],
                         timeout=600)

            if requirements:
                req = Path(os.path.expanduser(requirements))
                if not req.is_file():
                    raise VenvyardError(f"requirements file not found: {req}")
                if progress:
                    progress(f"installing requirements into '{name}'")
                proc = venv.pip(["install", "-r", str(req)], timeout=3600)
                if proc.returncode != 0:
                    raise VenvyardError(
                        f"'{name}' was created but installing {req} failed:\n"
                        f"{(proc.stderr or proc.stdout or '').strip()[:800]}")
                venv.write_meta(requirements_source=str(req))

            if packages:  # noqa: SIM102
                if progress:
                    progress(f"installing {len(packages)} package(s) into '{name}'")
                proc = venv.pip(["install", *packages], timeout=3600)
                if proc.returncode != 0:
                    raise VenvyardError(
                        f"'{name}' was created but installing packages failed:\n"
                        f"{(proc.stderr or proc.stdout or '').strip()[:800]}")
        except KeyboardInterrupt:
            shutil.rmtree(target, ignore_errors=True)
            raise
        venv._partial = False
        return venv

    # -- delete ------------------------------------------------------------
    @staticmethod
    def active_path() -> Path | None:
        current = os.environ.get("VIRTUAL_ENV")
        if not current:
            return None
        try:
            return Path(current).resolve()
        except OSError:
            return None

    def is_active(self, venv: "Venv") -> bool:
        active = self.active_path()
        try:
            return active is not None and active == venv.path.resolve()
        except OSError:
            return False

    def delete(self, name: str) -> Path:
        venv = self.get(name)
        path = venv.path.resolve()
        root = self.root.resolve()
        if path == root or root not in path.parents:
            raise VenvyardError(f"refusing to delete {path}: it is not inside the yard")
        if str(path) in ("/", str(Path.home())):
            raise VenvyardError(f"refusing to delete {path}")
        shutil.rmtree(path)
        return path

    # -- rename / move -----------------------------------------------------
    def rename(self, old: str, new: str | None = None) -> Venv:
        venv = self.get(old)
        new = self.auto_name(old) if not new else validate_name(new)
        if new == old:
            raise VenvyardError(f"'{old}' is already called that")
        target = self.root / new
        if target.exists():
            raise VenvyardError(f"'{new}' already exists")
        old_path = venv.path
        os.rename(old_path, target)
        moved = Venv(new, target)
        rewrite_paths(moved, str(old_path), str(target))
        moved.write_meta(renamed_from=old, renamed_at=time.time())
        return moved

    # -- copy (byte-for-byte) ---------------------------------------------
    def copy(self, source: str, new: str | None = None, progress=None) -> Venv:
        src = self.get(source)
        new = self.auto_name(source) if not new else validate_name(new)
        target = self.root / new
        if target.exists():
            raise VenvyardError(f"'{new}' already exists")
        if progress:
            progress(f"copying '{source}' to '{new}'")
        try:
            shutil.copytree(src.path, target, symlinks=True, ignore_dangling_symlinks=True)
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise VenvyardError(f"could not copy '{source}': {exc}") from exc
        copied = Venv(new, target)
        rewrite_paths(copied, str(src.path), str(target))
        copied.write_meta(created_at=time.time(), origin=f"copy of {source}",
                          copied_from=source, copied_at=time.time())
        return copied

    # -- clone (rebuild from package list) ---------------------------------
    def clone(self, source: str, new: str | None = None, python: str | None = None,
              progress=None) -> Venv:
        src = self.get(source)
        new = self.auto_name(source) if not new else validate_name(new)
        if self.exists(new):
            raise VenvyardError(f"'{new}' already exists")
        if progress:
            progress(f"reading packages from '{source}'")
        try:
            frozen = src.freeze()
        except VenvyardError:
            frozen = "\n".join(f"{p}=={v}" for p, v in src.packages() if v and v != "?")

        # created_with is an absolute path recorded when the environment was
        # built.  If that interpreter is gone, resolve_python() refuses it --
        # and a vanished base Python is exactly the case --doctor tells people
        # to fix with --clone.  Fall back rather than dead-ending.
        recorded = src.meta.get("created_with") or None
        if recorded and not python:
            try:
                resolve_python(recorded)
            except VenvyardError:
                recorded = src.python_version or None
        venv = self.create(new, python=python or recorded or None,
                           system_site=src.system_site_packages, upgrade_pip=True,
                           description=src.description, tags=src.tags, progress=progress)
        reqs = [line.strip() for line in frozen.splitlines()
                if line.strip() and not line.strip().startswith("#")
                and not line.strip().startswith("-e ")]
        editable = [line.strip() for line in frozen.splitlines()
                    if line.strip().startswith("-e ")]
        failed = []
        if reqs:
            if progress:
                progress(f"installing {len(reqs)} package(s) into '{new}'")
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
                fh.write("\n".join(reqs) + "\n")
                req_path = fh.name
            try:
                proc = venv.pip(["install", "-r", req_path], timeout=3600)
                if proc.returncode != 0:
                    failed.append((proc.stderr or proc.stdout or "").strip()[:600])
            finally:
                try:
                    os.unlink(req_path)
                except OSError:
                    pass
        venv.write_meta(origin=f"clone of {source}", cloned_from=source,
                        cloned_at=time.time(),
                        clone_skipped_editable=editable or None)
        if failed:
            raise VenvyardError(
                f"'{new}' was created from '{source}' but some packages did not "
                f"install:\n{failed[0]}")
        return venv

    # -- repair ------------------------------------------------------------
    def _base_for_rebuild(self, venv: Venv) -> str:
        """The interpreter to rebuild an environment's scaffolding with.

        It has to match lib/pythonX.Y, or the packages already installed
        become invisible to the restored interpreter.  Fall back through the
        version recorded in pyvenv.cfg to whatever is running venvyard.
        """
        for spec in (venv.lib_version, read_pyvenv_cfg(venv.path).get("version", "")):
            spec = (spec or "").strip()
            if not spec:
                continue
            try:
                return resolve_python(".".join(spec.split(".")[:2]))
            except VenvyardError:
                continue
        return sys.executable

    def _rebuild_scaffolding(self, venv: Venv) -> str | None:
        """Restore bin/python, the activate scripts and pyvenv.cfg.

        Re-running the venv module over an existing directory recreates the
        missing machinery and leaves site-packages alone, which is what the
        missing-file problems need -- repair() used to have no answer for
        them at all and reported 'needed no repair' while --doctor went on
        telling people to run it.
        """
        base = self._base_for_rebuild(venv)
        cfg = read_pyvenv_cfg(venv.path)
        # Clear out interpreter symlinks that no longer resolve.  A venv's
        # python links form a chain (python -> python3 -> pythonX.Y), so
        # losing one leaves the others dangling, and the venv module then
        # trips over them with ELOOP instead of rebuilding.  Only broken
        # symlinks go; a real file is never touched.
        if venv.bin.is_dir():
            for entry in sorted(venv.bin.glob("python*")):
                if entry.is_symlink() and not entry.exists():
                    try:
                        entry.unlink()
                    except OSError:
                        pass
        args = [base, "-m", "venv"]
        if str(cfg.get("include-system-site-packages", "")).lower() == "true":
            args.append("--system-site-packages")
        if not (venv.bin / "pip").exists():
            args.append("--without-pip")
        args.append(str(venv.path))
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            raise VenvyardError(
                f"could not rebuild '{venv.name}' with {base}: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise VenvyardError(
                f"could not rebuild '{venv.name}' with {base}:\n{detail}")
        return f"rebuilt the environment scaffolding using {base}"

    def repair(self, name: str) -> list:
        venv = self.get(name)
        fixed = []

        # The missing-file problems first: everything below reads bin/activate
        # and pyvenv.cfg, so they have to exist before the rest can run.
        missing = [problem for problem in venv.health()[1]
                   if "is missing" in problem or "broken symlink" in problem]
        if missing:
            note = self._rebuild_scaffolding(venv)
            if note:
                fixed.append(note)
            venv._cfg_cache = read_pyvenv_cfg(venv.path)
            venv._pkgs = None

        recorded = venv.recorded_prefix()
        if recorded and Path(recorded) != venv.path:
            rewrite_paths(venv, recorded, str(venv.path))
            fixed.append(f"rewrote internal paths from {recorded} to {venv.path}")
        cfg = read_pyvenv_cfg(venv.path)
        home = cfg.get("home", "")
        if home and not Path(home).is_dir():
            new_home = str(Path(sys.executable).resolve().parent)
            _set_cfg_key(venv.path / "pyvenv.cfg", "home", new_home)
            fixed.append(f"pointed the base interpreter at {new_home}")
        if not venv.meta_file.is_file():
            venv.write_meta(created_at=venv.created_at or time.time(),
                            origin="adopted", python_version=venv.python_version)
            fixed.append("created the missing venvyard metadata file")
        venv._cfg_cache = read_pyvenv_cfg(venv.path)
        return fixed

    # -- import / adopt ----------------------------------------------------
    def adopt(self, source: Path, new: str | None = None, move: bool = True) -> Venv:
        source = Path(os.path.expanduser(str(source))).resolve()
        if not source.is_dir():
            raise VenvyardError(f"{source} is not a directory")
        if not looks_like_venv(source):
            raise VenvyardError(f"{source} does not look like a virtual environment")
        if self.root in source.parents:
            raise VenvyardError(f"{source} is already inside the yard")
        base = new or source.name
        if base in (".venv", "venv", "env", ".env"):
            base = source.parent.name or base
        # Normalise FIRST, then resolve collisions: validate_name() strips
        # whitespace, so exists(base) can be False while the name it actually
        # lands on is already taken.  Checking the wrong one moved the import
        # *inside* the existing environment and overwrote its metadata.
        base = validate_name(base)
        name = base if not self.exists(base) else self.auto_name(base)
        self.ensure_root()
        target = self.root / name
        if target.exists():
            raise VenvyardError(
                f"'{name}' already exists at {target}; refusing to import over it")
        if move:
            try:
                shutil.move(str(source), str(target))
            except Exception as exc:
                raise VenvyardError(f"could not move {source}: {exc}") from exc
        else:
            shutil.copytree(source, target, symlinks=True, ignore_dangling_symlinks=True)
        venv = Venv(name, target)
        rewrite_paths(venv, str(source), str(target))
        venv.write_meta(created_at=venv.created_at or time.time(),
                        origin=f"imported from {source}", imported_from=str(source),
                        imported_at=time.time())
        return venv

    # -- scan the filesystem ----------------------------------------------
    def scan(self, roots: list | None = None, skip: list | None = None,
             max_depth: int = 8, progress=None) -> list:
        roots = [Path(os.path.expanduser(r)).resolve()
                 for r in (roots or self.cfg.get("scan_roots") or ["~"])]
        raw_skip = list(skip or self.cfg.get("scan_skip") or [])
        # Entries are matched against one path component at a time, so
        # defaults like ".local/share/Trash" and "go/pkg" could never match
        # anything -- scan walked the trash and the Go module cache, and
        # --scan --import-found would happily adopt a venv out of the trash.
        # Split them into a separate suffix list.
        skip_names = {s for s in raw_skip if "/" not in s}
        skip_paths = [s.strip("/") for s in raw_skip if "/" in s]
        yard = self.root.resolve()
        found = []
        seen = set()
        for base in roots:
            if not base.is_dir():
                continue
            base_depth = len(base.parts)
            for dirpath, dirnames, filenames in os.walk(base, onerror=lambda e: None,
                                                        followlinks=False):
                here = Path(dirpath)
                if len(here.parts) - base_depth >= max_depth:
                    dirnames[:] = []
                    continue
                dirnames[:] = [
                    d for d in dirnames
                    if d not in skip_names and not d.startswith(".Trash")
                    and not any(str((here / d)).endswith(os.sep + sp)
                                for sp in skip_paths)]
                if here == yard or yard in here.parents:
                    dirnames[:] = []
                    continue
                if progress and len(seen) % 200 == 0:
                    progress(f"scanning {str(here)[:60]}")
                if "pyvenv.cfg" in filenames or (
                        "bin" in dirnames and (here / "bin" / "activate").is_file()):
                    if looks_like_venv(here) and str(here) not in seen:
                        seen.add(str(here))
                        found.append(here)
                        dirnames[:] = []
        return sorted(found)

    # -- aggregate ---------------------------------------------------------
    def with_sizes(self, venvs: list, workers: int = 8) -> None:
        """Populate sizes in parallel so listings stay responsive."""
        if not venvs:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(v.size): v for v in venvs}
            concurrent.futures.wait(futures, timeout=120)

    def stats(self) -> dict:
        venvs = self.list()
        self.with_sizes(venvs)
        total = sum(v.size() for v in venvs)
        versions: dict[str, int] = {}
        for v in venvs:
            versions[v.python_version] = versions.get(v.python_version, 0) + 1
        broken = [v for v in venvs if v.broken]
        return {
            "count": len(venvs),
            "total_size": total,
            "versions": versions,
            "broken": broken,
            "packages": sum(v.package_count for v in venvs),
            "largest": max(venvs, key=lambda v: v.size()) if venvs else None,
            "newest": max(venvs, key=lambda v: v.created_at or 0) if venvs else None,
            "oldest_used": min(venvs, key=lambda v: v.last_used or 0) if venvs else None,
        }

    def stale(self, days: int) -> list:
        cutoff = time.time() - days * 86400
        return [v for v in self.list() if (v.last_used or 0) < cutoff]


# ---------------------------------------------------------------------------
# path rewriting - the part that makes rename/copy/repair actually work
# ---------------------------------------------------------------------------

def rewrite_paths(venv: Venv, old_prefix: str, new_prefix: str) -> int:
    """Replace every baked-in absolute path inside a venv.  Returns file count."""
    old_prefix = str(old_prefix).rstrip("/")
    new_prefix = str(new_prefix).rstrip("/")
    if old_prefix == new_prefix:
        return 0
    old_b, new_b = old_prefix.encode(), new_prefix.encode()
    changed = 0

    targets: list[Path] = []
    cfg = venv.path / "pyvenv.cfg"
    if cfg.is_file():
        targets.append(cfg)
    if venv.bin.is_dir():
        for entry in venv.bin.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            targets.append(entry)
    sp = venv.site_packages
    if sp and sp.is_dir():
        for pattern in ("*.pth", "*.egg-link", "**/*.pth"):
            for entry in sp.glob(pattern):
                if entry.is_file() and not entry.is_symlink():
                    targets.append(entry)
    for extra in ("lib64", "share"):
        d = venv.path / extra
        if d.is_dir() and not d.is_symlink():
            for entry in d.rglob("*"):
                if entry.is_file() and not entry.is_symlink() and entry.stat().st_size < 262144:
                    targets.append(entry)

    for path in dict.fromkeys(targets):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if old_b not in raw:
            continue
        if b"\0" in raw[:4096]:
            continue
        try:
            mode = path.stat().st_mode
            path.write_bytes(raw.replace(old_b, new_b))
            os.chmod(path, stat.S_IMODE(mode))
            changed += 1
        except OSError:
            continue

    venv._cfg_cache = read_pyvenv_cfg(venv.path)
    return changed


def _set_cfg_key(cfg_path: Path, key: str, value: str) -> None:
    if not cfg_path.is_file():
        return
    lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()
    out, done = [], False
    for line in lines:
        if "=" in line and line.split("=")[0].strip().lower() == key.lower():
            out.append(f"{key} = {value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key} = {value}")
    cfg_path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# interpreter resolution
# ---------------------------------------------------------------------------

def resolve_python(spec: str) -> str:
    """Turn '3.11', 'python3.11' or '/usr/bin/python3' into a usable executable.

    A specific version must resolve to *that* version.  Falling back to
    whatever python3 happens to be would hand back a different interpreter
    than the one that was asked for, silently.
    """
    spec = (spec or "").strip()
    if not spec:
        return sys.executable

    candidate = Path(os.path.expanduser(spec))
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    if os.sep in spec:
        raise VenvyardError(f"{spec} is not an executable file")

    wanted = ""
    if re.fullmatch(r"\d+", spec):                       # "3"
        names = [f"python{spec}"]
    elif re.fullmatch(r"\d+\.\d+(\.\d+)?", spec):        # "3.12" or "3.12.1"
        wanted = ".".join(spec.split(".")[:2])
        names = [f"python{wanted}"]
    elif spec.startswith("python"):
        names = [spec]
        m = re.match(r"python(\d+\.\d+)", spec)
        wanted = m.group(1) if m else ""
    else:
        names = [spec, f"python{spec}"]

    for name in names:
        found = shutil.which(name)
        if not found:
            continue
        if wanted:
            try:
                proc = subprocess.run(
                    [found, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                    capture_output=True, text=True, timeout=15)
                actual = proc.stdout.strip()
            except Exception:
                actual = ""
            if actual and actual != wanted:
                continue          # a mislabelled or symlinked interpreter
        return found

    have = ", ".join(v for v, _ in available_pythons()) or "none"
    lines = [f"no Python interpreter matching '{spec}' was found on PATH.",
             f"  Installed here: {have}",
             "  See them all with: venvyard --pythons"]
    if wanted:
        help_ = install_commands(wanted)
        if help_["commands"]:
            where = help_["distro"].get("name") or "this system"
            lines.append(f"  To install it on {where}:")
            lines += [f"      {cmd}" for cmd in help_["commands"]]
    raise VenvyardError("\n".join(lines))


def available_pythons() -> list:
    """Every distinct python3.x on PATH, as (version, path)."""
    seen: dict[str, str] = {}
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            if not re.fullmatch(r"python3(\.\d+)?", entry):
                continue
            full = os.path.join(d, entry)
            if not os.access(full, os.X_OK):
                continue
            real = str(Path(full).resolve())
            if real in seen.values():
                continue
            try:
                proc = subprocess.run([full, "-c",
                                       "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                                      capture_output=True, text=True, timeout=10)
            except Exception:
                continue
            ver = proc.stdout.strip()
            if ver and ver not in seen:
                seen[ver] = real
    return sorted(seen.items(), key=lambda kv: [int(x) for x in kv[0].split(".")])


def _version() -> str:
    from . import __version__
    return __version__


# ---------------------------------------------------------------------------
# the host system: which distribution, and how it installs Python
# ---------------------------------------------------------------------------

_PKG = {
    "apt": {
        "family": ("debian", "ubuntu", "linuxmint", "pop", "elementary",
                   "kali", "raspbian", "devuan", "zorin"),
        "base": "sudo apt update && sudo apt install -y python3 python3-venv python3-pip",
        "venv": "sudo apt install -y python3-venv",
        "versioned": "sudo apt install -y python{v} python{v}-venv",
        "note": ("Ubuntu carries only a few versions. For others add the deadsnakes "
                 "archive first:\n    sudo add-apt-repository ppa:deadsnakes/ppa"),
    },
    "dnf": {
        "family": ("fedora", "rhel", "centos", "rocky", "almalinux", "ol"),
        "base": "sudo dnf install -y python3 python3-pip",
        "venv": "sudo dnf install -y python3-libs",
        "versioned": "sudo dnf install -y python{v}",
        "note": "",
    },
    "pacman": {
        "family": ("arch", "manjaro", "endeavouros", "garuda", "artix"),
        "base": "sudo pacman -S --needed python python-pip",
        "venv": "sudo pacman -S --needed python",
        "versioned": "",     # Arch ships only the current release
        "note": ("Arch packages only the current Python. For older versions use "
                 "pyenv or the AUR."),
    },
    "zypper": {
        "family": ("opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles", "sled"),
        "base": "sudo zypper install -y python3 python3-pip",
        "venv": "sudo zypper install -y python3",
        "versioned": "sudo zypper install -y python{vv}",
        "note": "openSUSE names packages without the dot, e.g. python311.",
    },
    "apk": {
        "family": ("alpine",),
        "base": "sudo apk add python3 py3-pip",
        "venv": "sudo apk add python3",
        "versioned": "",
        "note": "Alpine packages only the current Python.",
    },
    "xbps": {
        "family": ("void",),
        "base": "sudo xbps-install -S python3 python3-pip",
        "venv": "sudo xbps-install -S python3",
        "versioned": "",
        "note": "",
    },
    "emerge": {
        "family": ("gentoo",),
        "base": "sudo emerge --ask dev-lang/python",
        "venv": "sudo emerge --ask dev-lang/python",
        "versioned": "sudo emerge --ask =dev-lang/python-{v}*",
        "note": "",
    },
}

UNIVERSAL_NOTE = (
    "Any version, on any distribution, without touching system packages:\n"
    "    pyenv install {v}          (https://github.com/pyenv/pyenv)\n"
    "    uv python install {v}      (https://github.com/astral-sh/uv)")


def detect_distro() -> dict:
    """Identify the distribution and how it installs packages."""
    info = {"id": "", "name": "", "manager": "", "detected": False}
    data = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "=" in line:
                        k, _, v = line.partition("=")
                        data[k.strip()] = v.strip().strip('"').strip("'")
            break
        except OSError:
            continue
    info["id"] = (data.get("ID") or "").lower()
    info["name"] = data.get("PRETTY_NAME") or data.get("NAME") or ""
    ids = [info["id"]] + (data.get("ID_LIKE", "").lower().split())

    for manager, spec in _PKG.items():
        if any(i and any(i.startswith(f) for f in spec["family"]) for i in ids):
            info["manager"] = manager
            info["detected"] = True
            break
    if not info["manager"]:
        # fall back to whichever package manager is actually on PATH
        for manager in ("apt", "dnf", "pacman", "zypper", "apk", "xbps", "emerge"):
            probe = {"apt": "apt", "dnf": "dnf", "pacman": "pacman", "zypper": "zypper",
                     "apk": "apk", "xbps": "xbps-install", "emerge": "emerge"}[manager]
            if shutil.which(probe):
                info["manager"] = manager
                break
    return info


def install_commands(version: str = "", want: str = "base") -> dict:
    """Suggested commands for installing Python (or just venv support)."""
    distro = detect_distro()
    spec = _PKG.get(distro["manager"])
    out = {"distro": distro, "commands": [], "note": ""}
    if not spec:
        out["note"] = UNIVERSAL_NOTE.format(v=version or "3.12")
        return out
    short = ".".join(version.split(".")[:2]) if version else ""
    if want == "venv":
        out["commands"] = [spec["venv"]]
    elif short and spec["versioned"]:
        out["commands"] = [spec["versioned"].format(v=short, vv=short.replace(".", ""))]
    else:
        out["commands"] = [spec["base"]]
    note = spec["note"]
    if short:
        note = (note + "\n\n" if note else "") + UNIVERSAL_NOTE.format(v=short)
    out["note"] = note
    return out


# ---------------------------------------------------------------------------
# probing the interpreters installed on this machine
# ---------------------------------------------------------------------------

_PROBE = (
    "import sys,json;"
    "d={'version':'%d.%d.%d'%sys.version_info[:3],'prefix':sys.prefix};"
    "\ntry:\n import venv; d['venv']=True\nexcept Exception: d['venv']=False\n"
    "try:\n import ensurepip; d['ensurepip']=True\nexcept Exception: d['ensurepip']=False\n"
    "try:\n import pip; d['pip']=pip.__version__\nexcept Exception: d['pip']=''\n"
    "print(json.dumps(d))"
)


def probe_interpreter(path: str) -> dict:
    """Everything worth knowing about one interpreter, in a single subprocess."""
    result = {"path": str(path), "version": "", "venv": False, "ensurepip": False,
              "pip": "", "ok": False, "error": ""}
    try:
        proc = subprocess.run([str(path), "-c", _PROBE], capture_output=True,
                              text=True, timeout=20)
    except Exception as exc:
        result["error"] = str(exc)[:80]
        return result
    if proc.returncode != 0:
        result["error"] = (proc.stderr or "").strip().splitlines()[-1][:80] if proc.stderr else "failed"
        return result
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        result["error"] = "unreadable output"
        return result
    result.update(data)
    result["ok"] = True
    return result


def interpreter_report(yard=None) -> list:
    """Probe every python3.x on PATH, in parallel, and count what uses each."""
    found = available_pythons()
    default = shutil.which("python3") or ""
    default_real = str(Path(default).resolve()) if default else ""

    usage: dict[str, int] = {}
    if yard is not None:
        for venv in yard.list():
            short = ".".join(venv.python_version.split(".")[:2])
            usage[short] = usage.get(short, 0) + 1

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(probe_interpreter, path): (ver, path)
                   for ver, path in found}
        for future in concurrent.futures.as_completed(futures, timeout=90):
            ver, path = futures[future]
            try:
                info = future.result()
            except Exception:
                info = {"path": path, "version": ver, "ok": False, "error": "probe failed",
                        "venv": False, "ensurepip": False, "pip": ""}
            short = ".".join((info.get("version") or ver).split(".")[:2])
            info["short"] = short
            info["is_default"] = (str(Path(path).resolve()) == default_real)
            info["environments"] = usage.get(short, 0)
            rows.append(info)

    def key(row):
        try:
            return [int(x) for x in row.get("short", "0").split(".")]
        except ValueError:
            return [0]
    return sorted(rows, key=key, reverse=True)


KNOWN_VERSIONS = ["3.14", "3.13", "3.12", "3.11", "3.10", "3.9", "3.8"]
