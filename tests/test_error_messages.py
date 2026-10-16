"""Every failure maps to a message key that exists, and says what to check next."""
from __future__ import annotations

import json
from pathlib import Path

from anova_local.errors import FAILURES, failure_for

COMPONENT = Path(__file__).parent.parent / "custom_components" / "anova_local"


def _english() -> dict:
    return json.loads((COMPONENT / "translations" / "en.json").read_text())["config"]


def test_every_failure_has_a_message() -> None:
    config = _english()
    for key in FAILURES:
        assert config["error"].get(key), key


def test_every_failure_says_what_to_check() -> None:
    for key, failure in FAILURES.items():
        assert failure.check.endswith("."), key
        assert len(failure.check) > 30, key


def test_every_failure_names_a_cause() -> None:
    for key, failure in FAILURES.items():
        assert failure.cause, key
        assert failure.cause != failure.check, key


def test_unknown_ids_fall_back_to_a_generic_failure() -> None:
    generic = failure_for("something_new")
    assert generic.key == "provision_failed"
    assert generic.check  # still tells the user something
