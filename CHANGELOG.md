# Changelog

All notable changes to venvyard are recorded here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-27

First release.

### Added

**Managing environments**
- A single yard (`~/PY_VENV` by default) holding every environment, so the
  registry is the directory listing and can never drift out of sync.
- `--create` with any interpreter (`--python 3.12`), from a requirements file
  (`-r`), with named packages (`--with`), and with a description and tags.
- `--delete`, `--rename`, `--copy` and `--clone`, each accepting several
  environments in one command via `OLD=NEW` pairs.
- Automatic naming when no new name is given (`web` becomes `web(1)`).
- Absolute-path rewriting on rename, copy, import and repair, so renamed
  environments and the console scripts installed inside them keep working.

**Finding and inspecting**
- `--list`, `--info`, `--packages`, `--search` (including `--in-packages`),
  `--which`, `--stats` and `--size`.
- `--scan` to find environments living outside the yard and `--import` to
  adopt them, repairing their paths on the way in.
- `--prune` to remove environments unused for longer than a chosen period.

**Using**
- `--activate` and `--deactivate` through a shell function installed by the
  installer, `--shell` for a subshell, and `--run` to execute a command inside
  an environment without activating anything.

**Packages**
- `--install`, `--uninstall`, `--freeze`, `--upgrade-pip`, `--outdated`, and
  `--export` / `--create --from-export` for reproducing an environment
  elsewhere.

**Python interpreters**
- `--pythons` lists every interpreter on the machine with its version, whether
  it can create environments, its pip version, and how many of your
  environments use it. Names the versions you do not have and gives the exact
  command to install them on your distribution.
- Asking for a version that is not installed is refused rather than silently
  falling back to a different interpreter.
- The installer detects the distribution (apt, dnf, pacman, zypper, apk, xbps,
  emerge) and offers to install Python, or the missing `venv` module, when
  either is absent.
- The launcher falls back to another suitable interpreter if the one venvyard
  was installed with is later removed.

**Health**
- `--doctor` detects missing interpreters, deleted base Pythons, stale
  absolute paths, and the case where a distribution upgrade has moved the base
  Python out from under an environment.
- `--repair` fixes what path rewriting can fix, and says plainly when only a
  rebuild will do.

**Interface**
- A guided interactive menu covering every command, which prints the
  equivalent command line for each action.
- Five colour themes, Unicode and ASCII rendering, `--json` output for
  scripting, tab completion for bash and zsh, and a detailed `--help` with a
  page per command.

**Safety**
- Confirmation before anything destructive, with `--yes` and `--dry-run`.
- Refuses to delete an environment that is active in the current shell unless
  `--force` is given, and warns after renaming one.
- Refuses to touch anything outside the yard.
- Cleans up partially created environments if creation is interrupted.

**Development**
- A test suite (`pytest`), covering name validation and automatic naming,
  `OLD=NEW` operand splitting, absolute-path rewriting on rename and repair,
  registry consistency, and the integration and completion output for bash,
  zsh and fish, parsed by each shell where it is installed, and the
  installer's effect on rc files across repeated runs. Tests run against a
  throwaway yard and never touch a real `~/PY_VENV`.
- A GitHub Actions workflow running the suite on Python 3.8 through 3.13.

### Fixed

Defects found and resolved by review and testing before this release.

**Destructive operations**
- `--delete` accepted any directory inside the yard, so it would recursively
  remove an ordinary folder that `--list` never showed. Commands now require
  the target to be a virtual environment or to carry venvyard metadata,
  matching what `--list` displays.
- `--import` checked the pre-normalised name for collisions while moving to
  the normalised one, so importing as `"web "` with `web` present moved the
  import *inside* `web` and overwrote its metadata.
- `--rename`, `--copy` and `--clone` split operands on `=` and `:` before
  checking for an existing name, both of which are legal in names. An
  existing name now wins, so an environment called `data=v2` can be operated
  on instead of silently mutating `data`.
- `--prune` deleted the environment active in the current shell, which
  `--delete` refuses. It now skips it unless `--force` is given.

**Repair**
- `--doctor` recommended `--repair` for every problem it found, but repair
  had no answer for a missing `bin/python`, `pyvenv.cfg` or `bin/activate`:
  it reported "needed no repair" and left the environment broken. Those are
  now rebuilt, preserving installed packages.
- Every pip-backed command, including `--info`, died on a bare errno when the
  interpreter was missing, so the command that would have explained the
  breakage could not finish printing.
- `--doctor` could not detect an environment moved by hand on Python 3.12 or
  newer, and reported it as healthy. Up to 3.11 CPython writes the venv's own
  path into `bin/activate` as a bare `VIRTUAL_ENV=/path` at the start of a
  line; from 3.12 it writes `    export VIRTUAL_ENV=/path`, indented and inside
  an `if`/`else` whose other branch is a `$(cygpath ...)` substitution. The
  expression that read it back was anchored to the start of the line, so it
  matched only the older form and returned nothing at all on 3.12+, which
  silently disabled the stale-path check, and with it the `--repair` that
  check recommends. Every form CPython 3.8 through 3.13 emits is now read, the
  cygwin branch is never mistaken for the path, and `activate.fish` is used as
  a fallback when the POSIX script is missing.

**Input handling**
- Mistyped values no longer print tracebacks: `--prune --days abc`, `--config`
  with a non-boolean or non-numeric value, and `--from-export` given valid
  JSON of the wrong shape. A typo at the menu's prune prompt used to end the
  whole menu session.
- `--config` persisted whatever `VENVYARD_HOME`, `VENVYARD_THEME` or
  `NO_COLOR` happened to be set to, so one `--config` in a shell with a
  temporary yard silently moved the yard for good.
- `--which --python NAME` no longer treats the name as `--python`'s value.
- `--clone` works when the interpreter recorded at creation has since been
  removed, which is the case `--doctor` recommends `--clone` for.
- `--theme` reports an unknown value instead of silently using the default.

**Shells**
- The fish integration could never have worked: it sourced the POSIX
  `bin/activate` rather than `activate.fish`, and emitted POSIX syntax for
  `--deactivate`. The installer also wrote a POSIX `PATH` stanza into
  `config.fish`.
- The shell function matched only the first argument, so `vy -q -a web` and
  `vy --root DIR -a web` reported that the integration was not loaded.
- `--shell` passed `--rcfile` to `sh`, which dash rejects, so no subshell
  appeared and a temp file was left in `/tmp` each time.
- The installer now consults `$SHELL`, instead of falling back to `~/.bashrc`
  for someone whose login shell has no rc file yet.
- `--completion fish` returned the bash script, which fish cannot parse
  (`Unexpected ')' found`). The shipped bash completion also offered `fish`
  as a value for `--completion`, so tab completion led straight into it.
  There is now a real fish completion, generated from the same command
  registry as the bash and zsh ones.
- The advice printed when the shell integration is not loaded assumed bash.
  A fish user was told to run `eval "$(venvyard --shell-init bash)"`, to add
  it to `~/.bashrc`, and to source the POSIX `bin/activate`. The first is
  wrong twice over: fish has no `$(...)` substitution, and it fetches the
  bash snippet. Each hint now matches the shell in use, in `--activate`,
  `--deactivate` and the menu.

**Installer**
- Aborted with `DISTRO_LIKE: unbound variable` on any image without a
  readable `/etc/os-release`.
- `--prefix` with no value looped forever.
- A failed copy into the target directory was not fatal, and the check
  afterwards tested the module rather than the installed command, so it
  reported success for a venvyard the user did not have.
- `--help` printed `set -u` after the usage block, because it echoed a fixed
  line range that overshot into the code.
- `--quiet`/`-q` was accepted but documented nowhere.
- Re-running the installer added one blank line to every shell startup file it
  touched, because the block it strips left the blank line in front of it
  behind and a fresh one was prepended each time. Reinstalling now leaves the
  rc files byte for byte as the first install did.

**Documentation**
- `--json` is supported by eleven commands; only five were documented. The
  missing ones are `--size`, `--scan`, `--doctor`, `--outdated`, `--pythons`
  and `--version`.
- All eleven `--config` keys are now listed, with defaults; three were.
- `VENVYARD_FORCE_COLOR`, `VENVYARD_ASCII` and `VENVYARD_NO_CLEAR` were
  undocumented.
- The `--exec` and `--interpreters` aliases are noted.

**Smaller things**
- `--copy` reported "copyd".
- `--install` read the package count after pip ran, always reporting
  "(N packages now, was N)".
- `--search` labelled every hit "name", including tag and description matches.
- `--sort` is documented for `--size` but was ignored there.
- A dot-named environment was creatable but invisible to every listing.
- The `scan_skip` defaults `.local/share/Trash` and `go/pkg` could never
  match, so `--scan` walked the trash and the Go module cache.
- `--tag`, `--describe` and `--untag` reported success on a read-only yard
  while storing nothing.
- An interrupted `--create` only cleaned up if interrupted during the venv
  call, not during the pip phases that take nearly all the time.
- The `--create` help gave `--tag work` as an example, which the parser
  rejects; the option is `--tag-with`.
- `PYTHONPATH` from the installed launcher leaked into every child process,
  putting venvyard on `sys.path` for in-environment pip installs.

### Notes
- Linux, Python 3.8 or newer. No third-party dependencies.
