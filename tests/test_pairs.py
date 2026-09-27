"""OLD=NEW operand splitting.

'=' and ':' are legal in environment names, so an existing environment has to
win over the pair shape.  Getting this wrong silently mutated the wrong
environment, which is why every branch is pinned here.
"""
from __future__ import annotations

import pytest

from venvyard.actions import _pair_targets
from venvyard.core import VenvyardError


class _FakeYard:
    def __init__(self, existing):
        self._existing = set(existing)

    def exists(self, name):
        return name in self._existing


class _FakeCtx:
    def __init__(self, existing=()):
        self.yard = _FakeYard(existing)


def pairs(names, existing=()):
    return _pair_targets(_FakeCtx(existing), names, "rename")


def test_no_operands_is_an_error():
    with pytest.raises(VenvyardError):
        pairs([])


def test_single_name_has_no_target():
    assert pairs(["web"]) == [("web", None)]


def test_equals_pair():
    assert pairs(["web=site"]) == [("web", "site")]


def test_colon_pair():
    assert pairs(["web:site"]) == [("web", "site")]


def test_two_bare_names_read_as_old_new():
    assert pairs(["web", "site"]) == [("web", "site")]


def test_three_bare_names_are_three_targets():
    assert pairs(["a", "b", "c"]) == [("a", None), ("b", None), ("c", None)]


def test_several_pairs_at_once():
    assert pairs(["web=site", "api=backend"]) == [("web", "site"), ("api", "backend")]


def test_existing_name_containing_equals_wins_over_pair_shape():
    """`--copy data=v2` must operate on the environment called 'data=v2'."""
    assert pairs(["data=v2"], existing=["data=v2"]) == [("data=v2", None)]


def test_existing_name_containing_colon_wins():
    assert pairs(["a:b"], existing=["a:b"]) == [("a:b", None)]


def test_mixed_existing_and_pair_in_one_command():
    got = pairs(["data=v2", "web=site"], existing=["data=v2"])
    assert got == [("data=v2", None), ("web", "site")]


def test_whitespace_around_operands_is_trimmed():
    assert pairs([" web = site "]) == [("web", "site")]


def test_empty_new_half_means_no_target():
    assert pairs(["web="]) == [("web", None)]
