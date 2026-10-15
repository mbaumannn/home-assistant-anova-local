"""The brand assets HACS and Home Assistant look for, and what they claim to be."""
from __future__ import annotations

import struct
from pathlib import Path

BRAND = Path(__file__).parent.parent / "custom_components" / "anova_local" / "brand"


def _png_size(path: Path) -> tuple[int, int]:
    """Read width and height from a PNG IHDR chunk."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_the_brand_icon_exists_and_is_square():
    assert _png_size(BRAND / "icon.png") == (256, 256)


def test_the_hidpi_icon_exists_and_is_the_double():
    assert _png_size(BRAND / "icon@2x.png") == (512, 512)
