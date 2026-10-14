"""Make the component modules importable in tests (without Home Assistant)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "anova_bluetooth"
)

# Synthetic package so relative imports (from .const import ...) work without
# importing the real __init__.py (and therefore Home Assistant).
_pkg = types.ModuleType("anova_bluetooth")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["anova_bluetooth"] = _pkg
