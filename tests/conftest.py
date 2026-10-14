"""Zorg dat de component-modules importeerbaar zijn in tests (zonder HA)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "anova_bluetooth"
)

# Synthetische package zodat relatieve imports (from .const import …) werken
# zonder de echte __init__.py (en dus Home Assistant) te importeren.
_pkg = types.ModuleType("anova_bluetooth")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["anova_bluetooth"] = _pkg
