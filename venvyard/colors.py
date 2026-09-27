"""ANSI colour, theming and terminal presentation helpers.

Pure standard library. Degrades from truecolor -> 256 -> 16 -> no colour,
honours NO_COLOR, --no-color and non-TTY output.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ITALIC = "\x1b[3m"
UNDER = "\x1b[4m"


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def vlen(text: str) -> int:
    """Visible length of a string, ignoring ANSI escapes."""
    return len(strip_ansi(text))


def vpad(text: str, width: int, align: str = "<") -> str:
    """Pad to a visible width, ANSI-aware."""
    gap = max(0, width - vlen(text))
    if align == ">":
        return " " * gap + text
    if align == "^":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def vtrunc(text: str, width: int) -> str:
    """Truncate to a visible width, keeping escapes balanced."""
    if vlen(text) <= width:
        return text
    out, shown = [], 0
    i = 0
    while i < len(text) and shown < width - 1:
        m = _ANSI_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(text[i])
        shown += 1
        i += 1
    out.append("…")
    if "\x1b[" in text:
        out.append(RESET)
    return "".join(out)


# --------------------------------------------------------------------------
# Themes.  Each role maps to an (r, g, b) triple; lower colour depths are
# derived from it so a single definition covers every terminal.
# --------------------------------------------------------------------------

THEMES = {
    "default": {
        "title":  (124, 214, 255),
        "header": (108, 196, 255),
        "accent": (198, 145, 255),
        "ok":     (87,  214, 141),
        "warn":   (240, 190, 90),
        "err":    (255, 110, 110),
        "info":   (120, 200, 230),
        "dim":    (140, 148, 160),
        "name":   (255, 220, 120),
        "num":    (150, 220, 255),
        "path":   (150, 200, 170),
        "key":    (255, 170, 90),
        "cmd":    (130, 230, 200),
        "border": (95, 110, 130),
        "bar":    (100, 200, 255),
        "text":   (225, 228, 235),
    },
    "ocean": {
        "title":  (90, 220, 220), "header": (80, 190, 210), "accent": (120, 170, 255),
        "ok": (80, 215, 170), "warn": (235, 200, 110), "err": (255, 120, 130),
        "info": (110, 200, 220), "dim": (130, 145, 160), "name": (180, 235, 255),
        "num": (140, 215, 235), "path": (130, 205, 190), "key": (150, 200, 255),
        "cmd": (120, 230, 215), "border": (80, 115, 135), "bar": (90, 200, 220),
        "text": (220, 232, 238),
    },
    "sunset": {
        "title":  (255, 170, 110), "header": (255, 150, 120), "accent": (255, 130, 180),
        "ok": (170, 220, 120), "warn": (255, 200, 100), "err": (255, 105, 105),
        "info": (255, 190, 150), "dim": (155, 140, 135), "name": (255, 215, 150),
        "num": (255, 195, 140), "path": (215, 200, 150), "key": (255, 175, 130),
        "cmd": (250, 200, 160), "border": (130, 100, 90), "bar": (255, 165, 110),
        "text": (240, 230, 220),
    },
    "matrix": {
        "title":  (110, 255, 140), "header": (90, 230, 120), "accent": (160, 255, 180),
        "ok": (90, 245, 130), "warn": (220, 240, 120), "err": (255, 120, 110),
        "info": (130, 230, 160), "dim": (110, 150, 120), "name": (180, 255, 190),
        "num": (140, 250, 170), "path": (120, 220, 150), "key": (170, 255, 190),
        "cmd": (140, 255, 170), "border": (60, 130, 80), "bar": (90, 240, 130),
        "text": (200, 255, 210),
    },
    "mono": {},  # no colour at all
}

_BASIC = {
    "title": "\x1b[96m", "header": "\x1b[96m", "accent": "\x1b[95m", "ok": "\x1b[92m",
    "warn": "\x1b[93m", "err": "\x1b[91m", "info": "\x1b[96m", "dim": "\x1b[90m",
    "name": "\x1b[93m", "num": "\x1b[96m", "path": "\x1b[32m", "key": "\x1b[33m",
    "cmd": "\x1b[96m", "border": "\x1b[90m", "bar": "\x1b[94m", "text": "",
}


def _rgb_to_256(r: int, g: int, b: int) -> int:
    if abs(r - g) < 12 and abs(g - b) < 12:
        grey = round(((r + g + b) / 3 - 8) / 247 * 24)
        return 232 + max(0, min(23, grey))
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


class Palette:
    """Resolves role names to escape sequences for the active terminal."""

    def __init__(self, enabled: bool = True, depth: str = "auto", theme: str = "default"):
        self.theme_name = theme if theme in THEMES else "default"
        self.enabled = enabled and self.theme_name != "mono"
        self.depth = self._detect_depth() if depth == "auto" else depth
        self._cache: dict[str, str] = {}
        self.unicode = self._detect_unicode()

    @staticmethod
    def _detect_depth() -> str:
        if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
            return "truecolor"
        term = os.environ.get("TERM", "")
        if "256" in term or "kitty" in term or "alacritty" in term:
            return "256"
        if term in ("dumb", ""):
            return "16"
        return "256"

    @staticmethod
    def _detect_unicode() -> bool:
        if os.environ.get("VENVYARD_ASCII"):
            return False
        enc = (sys.stdout.encoding or "").lower()
        return "utf" in enc or "utf" in os.environ.get("LANG", "").lower()

    def code(self, role: str) -> str:
        if not self.enabled:
            return ""
        if role in self._cache:
            return self._cache[role]
        spec = THEMES[self.theme_name].get(role)
        if spec is None:
            out = _BASIC.get(role, "")
        elif self.depth == "truecolor":
            out = "\x1b[38;2;%d;%d;%dm" % spec
        elif self.depth == "256":
            out = "\x1b[38;5;%dm" % _rgb_to_256(*spec)
        else:
            out = _BASIC.get(role, "")
        self._cache[role] = out
        return out

    def __call__(self, role: str, text, bold: bool = False, under: bool = False) -> str:
        text = str(text)
        if not self.enabled:
            return text
        pre = self.code(role)
        if bold:
            pre = BOLD + pre
        if under:
            pre = UNDER + pre
        return f"{pre}{text}{RESET}" if pre else text

    def bold(self, text) -> str:
        return f"{BOLD}{text}{RESET}" if self.enabled else str(text)

    def dim(self, text) -> str:
        return f"{DIM}{text}{RESET}" if self.enabled else str(text)

    # -- glyphs ------------------------------------------------------------
    @property
    def glyph(self) -> dict:
        if self.unicode:
            return {
                "tick": "✔", "cross": "✘", "warn": "▲", "info": "•", "arrow": "→",
                "bullet": "•", "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
                "h": "─", "v": "│", "cross_t": "┬", "cross_b": "┴",
                "cross_l": "├", "cross_r": "┤", "plus": "┼", "block": "█",
                "shade": "░", "dot": "·", "star": "★", "pkg": "▪",
            }
        return {
            "tick": "+", "cross": "x", "warn": "!", "info": "*", "arrow": "->",
            "bullet": "*", "tl": "+", "tr": "+", "bl": "+", "br": "+",
            "h": "-", "v": "|", "cross_t": "+", "cross_b": "+",
            "cross_l": "+", "cross_r": "+", "plus": "+", "block": "#",
            "shade": ".", "dot": ".", "star": "*", "pkg": "-",
        }


def term_width(default: int = 100) -> int:
    try:
        w = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        w = default
    return max(50, min(w, 200))


class Table:
    """A small ANSI-aware table renderer."""

    def __init__(self, pal: Palette, columns, border: bool = True):
        self.pal = pal
        self.columns = columns          # list of (heading, align, max_width|None)
        self.rows: list[list[str]] = []
        self.border = border

    def add(self, *cells):
        self.rows.append([str(c) for c in cells])

    def render(self) -> str:
        p, g = self.pal, self.pal.glyph
        n = len(self.columns)
        widths = []
        for i, (head, _align, maxw) in enumerate(self.columns):
            w = vlen(head)
            for r in self.rows:
                if i < len(r):
                    w = max(w, vlen(r[i]))
            if maxw:
                w = min(w, maxw)
            widths.append(w)

        avail = term_width() - (3 * n + 1 if self.border else n)
        while sum(widths) > avail and max(widths) > 6:
            widths[widths.index(max(widths))] -= 1

        b = lambda s: p("border", s)
        lines = []
        if self.border:
            lines.append(b(g["tl"] + g["cross_t"].join(g["h"] * (w + 2) for w in widths) + g["tr"]))
        head_cells = [
            p("header", vpad(vtrunc(h, widths[i]), widths[i], a), bold=True)
            for i, (h, a, _m) in enumerate(self.columns)
        ]
        sep = b(" " + g["v"] + " ") if self.border else "  "
        lines.append((b(g["v"] + " ") if self.border else "") + sep.join(head_cells)
                     + (b(" " + g["v"]) if self.border else ""))
        if self.border:
            lines.append(b(g["cross_l"] + g["plus"].join(g["h"] * (w + 2) for w in widths) + g["cross_r"]))
        for r in self.rows:
            cells = []
            for i in range(n):
                val = r[i] if i < len(r) else ""
                cells.append(vpad(vtrunc(val, widths[i]), widths[i], self.columns[i][1]))
            lines.append((b(g["v"] + " ") if self.border else "") + sep.join(cells)
                         + (b(" " + g["v"]) if self.border else ""))
        if self.border:
            lines.append(b(g["bl"] + g["cross_b"].join(g["h"] * (w + 2) for w in widths) + g["br"]))
        return "\n".join(lines)


def banner(pal: Palette, title: str, subtitle: str = "") -> str:
    g = pal.glyph
    width = min(term_width(), 78)
    inner = width - 2
    top = pal("border", g["tl"] + g["h"] * inner + g["tr"])
    bot = pal("border", g["bl"] + g["h"] * inner + g["br"])
    v = pal("border", g["v"])
    body = [top]
    body.append(f"{v}{vpad(pal('title', title, bold=True), inner, '^')}{v}")
    if subtitle:
        body.append(f"{v}{vpad(pal('dim', subtitle), inner, '^')}{v}")
    body.append(bot)
    return "\n".join(body)


def rule(pal: Palette, label: str = "") -> str:
    g = pal.glyph
    w = min(term_width(), 78)
    if not label:
        return pal("border", g["h"] * w)
    lab = pal("header", " " + label + " ", bold=True)
    fill = w - vlen(lab) - 3
    return pal("border", g["h"] * 3) + lab + pal("border", g["h"] * max(0, fill))


def bar(pal: Palette, fraction: float, width: int = 24) -> str:
    g = pal.glyph
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return pal("bar", g["block"] * filled) + pal("dim", g["shade"] * (width - filled))


class Spinner:
    """Non-intrusive progress spinner; silent when output is not a TTY."""

    FRAMES_U = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    FRAMES_A = "|/-\\"

    def __init__(self, pal: Palette, message: str, stream=None):
        self.pal = pal
        self.message = message
        self.stream = stream or sys.stderr
        self.active = self.stream.isatty() and pal.enabled
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if self.active:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def _spin(self):
        frames = self.FRAMES_U if self.pal.unicode else self.FRAMES_A
        i = 0
        while not self._stop.is_set():
            f = self.pal("accent", frames[i % len(frames)])
            self.stream.write(f"\r{f} {self.pal('dim', self.message)}  ")
            self.stream.flush()
            i += 1
            time.sleep(0.08)

    def update(self, message: str):
        self.message = message

    def __exit__(self, *exc):
        if self.active:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=0.5)
            self.stream.write("\r" + " " * (vlen(self.message) + 8) + "\r")
            self.stream.flush()
        return False
