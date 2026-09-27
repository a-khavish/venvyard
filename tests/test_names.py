"""Name validation and automatic naming.

A dot-named environment used to be creatable but invisible to every listing,
and the autoname styles are user-configurable, so both are pinned here.
"""
from __future__ import annotations

import pytest

from venvyard.core import VenvyardError, validate_name


@pytest.mark.parametrize("name", ["web", "api-2", "data=v2", "a:b", "with space", ".dotty", "x" * 120])
def test_accepts_legal_names(name):
    assert validate_name(name) == name.strip()


@pytest.mark.parametrize("name", ["a/b", "a\\b", "-leading", "x" * 121, "a\0b"])
def test_rejects_illegal_names(name):
    with pytest.raises(VenvyardError):
        validate_name(name)


def test_strips_surrounding_whitespace():
    assert validate_name("  web  ") == "web"


def test_autoname_paren_style(yard):
    (yard.root / "web").mkdir()
    assert yard.auto_name("web") == "web(1)"


def test_autoname_dash_style(yard):
    yard.cfg["autoname_style"] = "dash"
    (yard.root / "web").mkdir()
    assert yard.auto_name("web") == "web-1"


def test_autoname_returns_base_when_free(yard):
    assert yard.auto_name("fresh") == "fresh"


def test_autoname_skips_taken_suffixes(yard):
    for n in ("web", "web(1)", "web(2)"):
        (yard.root / n).mkdir()
    assert yard.auto_name("web") == "web(3)"
