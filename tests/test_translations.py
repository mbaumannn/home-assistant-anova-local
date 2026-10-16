"""Every step, error and abort the flow can show is explained, in one language.

The flow tells the user what each step does before it does it; this pins that
contract, and that the file Home Assistant reads does not drift from the source.
"""
from __future__ import annotations

import json
from pathlib import Path

from anova_local.errors import FAILURES

COMPONENT = Path(__file__).parent.parent / "custom_components" / "anova_local"
# The steps the flow can show. There is no in-flow wait to display: the entry is
# created straight away and the cooker dials in afterwards, which the wifi step's
# description explains.
STEPS_WITH_TEXT = ("user", "bluetooth_confirm", "wifi")
ABORT_KEYS = ("already_configured", "not_found", "unsupported", "bluetooth_not_available")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_every_step_explains_itself() -> None:
    config = _load(COMPONENT / "strings.json")["config"]
    for step in STEPS_WITH_TEXT:
        assert config["step"][step]["title"], step
        assert config["step"][step]["description"], step


def test_every_failure_has_a_message() -> None:
    config = _load(COMPONENT / "strings.json")["config"]
    for key in FAILURES:
        assert config["error"][key], key


def test_every_abort_explains_itself() -> None:
    config = _load(COMPONENT / "strings.json")["config"]
    for key in ABORT_KEYS:
        assert config["abort"][key], key


def test_the_shipped_translations_match_strings_json() -> None:
    """The file Home Assistant actually reads must not drift from the source."""
    assert _load(COMPONENT / "translations" / "en.json") == _load(COMPONENT / "strings.json")


def test_no_em_dashes_in_user_facing_text() -> None:
    config = _load(COMPONENT / "translations" / "en.json")["config"]
    assert "\u2014" not in json.dumps(config)
