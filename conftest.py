"""Pytest configuration for the Anova Bluetooth integration tests."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# Make this repository's ``custom_components`` discoverable by the Home
# Assistant loader. The test plugin ships its own ``custom_components`` package
# that otherwise shadows the repository's one.
import custom_components as _custom_components  # noqa: E402

_REPO_CUSTOM_COMPONENTS = str(Path(__file__).parent / "custom_components")
if _REPO_CUSTOM_COMPONENTS not in list(_custom_components.__path__):
    _custom_components.__path__ = [
        _REPO_CUSTOM_COMPONENTS,
        *list(_custom_components.__path__),
    ]

# Home Assistant is only needed by the integration tests. The protocol tests
# import the component modules through a synthetic package so they stay fast
# and independent of the Home Assistant install.
COMPONENT_DIR = Path(__file__).parent / "custom_components" / "anova_bluetooth"
_pkg = types.ModuleType("anova_bluetooth")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules.setdefault("anova_bluetooth", _pkg)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make Home Assistant load the integration from custom_components."""
    yield
