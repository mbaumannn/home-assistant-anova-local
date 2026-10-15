"""Render the integration's brand icon.

The icon speaks the Anova Cook card's language: the grey temperature rail,
the orange arc while it heats, and the target dot on the rail. Deterministic
Pillow, so the PNGs can be regenerated and reviewed like code.

Run:  uv run --with pillow python tools/make_brand_icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

# The card's own colours: the slate rail, orange while heating.
RAIL = (71, 80, 94, 255)
HEAT = (255, 129, 3, 255)


def render(size: int) -> Image.Image:
    """Draw the icon at ``size`` x ``size`` on a transparent background."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stroke = max(6, round(size * 11 / 100))  # ~28 px on a 256 icon
    pad = round(stroke / 2) + 2
    box = (pad, pad, size - pad, size - pad)
    draw.arc(box, start=0, end=360, fill=RAIL, width=stroke)  # the rail
    draw.arc(box, start=-55, end=55, fill=HEAT, width=stroke)  # while heating
    # The target dot, on the rail, 35 degrees to the right of the top.
    radius = size / 2 - pad - stroke / 2
    angle = math.radians(90 - 35)
    cx = size / 2 + radius * math.cos(angle)
    cy = size / 2 - radius * math.sin(angle)
    dot = max(5, round(stroke * 0.75))
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=HEAT)
    return img


def main() -> None:
    brand = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "anova_local"
        / "brand"
    )
    brand.mkdir(parents=True, exist_ok=True)
    render(256).save(brand / "icon.png")
    render(512).save(brand / "icon@2x.png")
    print(f"wrote {brand / 'icon.png'} and {brand / 'icon@2x.png'}")


if __name__ == "__main__":
    main()
