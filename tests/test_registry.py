"""The registry is the single source of truth, so it has to stay consistent.

The parser, both help screens, the menu and three completion scripts are all
generated from it; a duplicate or a malformed entry breaks several at once.
"""
from __future__ import annotations

from collections import Counter

from venvyard.registry import COMMANDS, GROUP_ORDER, OPTIONS


def _dupes(values):
    return [v for v, n in Counter(values).items() if n > 1]


def test_no_duplicate_long_flags():
    longs = [c.long for c in COMMANDS] + [o.long for o in OPTIONS]
    longs += [a for c in COMMANDS for a in c.aliases]
    assert _dupes(longs) == []


def test_no_duplicate_short_flags():
    shorts = [c.short for c in COMMANDS if c.short] + [o.short for o in OPTIONS if o.short]
    assert _dupes(shorts) == []


def test_flags_are_well_formed():
    for c in COMMANDS:
        assert c.long.startswith("--"), c.long
        assert c.key, f"{c.long} has no action key"
        assert c.summary, f"{c.long} has no summary"
        if c.short:
            assert len(c.short) == 2 and c.short.startswith("-"), c.short
    for o in OPTIONS:
        assert o.long.startswith("--"), o.long
        assert o.summary, f"{o.long} has no summary"


def test_no_duplicate_action_keys():
    assert _dupes([c.key for c in COMMANDS]) == []


def test_every_command_group_is_declared():
    for c in COMMANDS:
        assert c.group in GROUP_ORDER, f"{c.long} is in undeclared group {c.group!r}"


def test_every_command_has_a_dispatch_entry():
    from venvyard.actions import DISPATCH
    missing = [c.long for c in COMMANDS if c.key not in DISPATCH]
    assert missing == [], f"no action for: {missing}"


def test_examples_reference_the_command_they_document():
    for c in COMMANDS:
        for ex in c.examples:
            assert "venvyard" in ex or "vy " in ex, (c.long, ex)
