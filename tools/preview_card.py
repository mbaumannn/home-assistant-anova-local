#!/usr/bin/env python3
"""Build a preview page for the bundled cook card.

The card is only ever visible inside Home Assistant, which makes it awkward to
review a change. This renders the *real* card file in a plain page, with a
stand-in for ``ha-control-circular-slider`` (the same 270-degree dial, drawn with
an SVG circle) and Home Assistant's theme variables, so the layout, the wording
and the countdown can be looked at without touching a live system.

Usage:  python3 tools/preview_card.py [output.html]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
CARD = REPO / "custom_components" / "anova_local" / "frontend" / "anova-cook-card.js"

STAND_IN_SLIDER = """
// A stand-in for Home Assistant's ha-control-circular-slider: the same 270 degree
// dial, drawn with an SVG circle, an arc for the value and a knob at its end.
class StubSlider extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._min = 0; this._max = 100; this._value = 0; this._colour = "var(--primary-color)";
  }
  set min(v) { this._min = Number(v); this._paint(); }
  get min() { return this._min; }
  set max(v) { this._max = Number(v); this._paint(); }
  get max() { return this._max; }
  set value(v) { this._value = Number(v); this._paint(); }
  get value() { return this._value; }
  set step(_v) {}
  set disabled(v) { this._disabled = v; }
  get disabled() { return this._disabled; }
  // Home Assistant's own dial draws the current temperature as a marker when it is
  // given a `current` value; the stand-in does the same.
  set current(v) { this._current = Number(v); this._paint(); }
  get current() { return this._current; }
  style = { setProperty: (name, value) => { if (name.includes("color")) { this._colour = value; this._paint(); } } };
  connectedCallback() { this._paint(); }
  _paint() {
    const span = this._max - this._min;
    const fraction = span > 0 ? Math.max(0, Math.min(1, (this._value - this._min) / span)) : 0;
    // Home Assistant's own numbers, read from a live slider: radius 145 in a 320
    // unit box, from 135 degrees over 270 degrees.
    const cx = 160, cy = 160, r = 145, width = 24, sweep = 270, start = 135;
    const circumference = 2 * Math.PI * r, arc = circumference * (sweep / 360);
    const angle = ((start + sweep * fraction) * Math.PI) / 180;
    const knobX = cx + r * Math.cos(angle), knobY = cy + r * Math.sin(angle);
    let marker = "";
    if (Number.isFinite(this._current) && this._current >= this._min && this._current <= this._max) {
      const markerFraction = (this._current - this._min) / span;
      const markerAngle = ((start + sweep * markerFraction) * Math.PI) / 180;
      const mx = cx + r * Math.cos(markerAngle), my = cy + r * Math.sin(markerAngle);
      // A dot in the text colour, with a card-coloured dot under it that cuts the arc.
      marker =
        `<circle cx="${mx}" cy="${my}" r="6" fill="var(--card-background-color)"/>` +
        `<circle cx="${mx}" cy="${my}" r="4" fill="var(--primary-text-color)"/>`;
    }
    this.shadowRoot.innerHTML = `
      <svg viewBox="0 0 320 320" style="width:100%;display:block">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--divider-color)"
                stroke-width="${width}" stroke-linecap="round"
                stroke-dasharray="${arc} ${circumference}" transform="rotate(${start} ${cx} ${cy})"/>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${this._colour}"
                stroke-width="${width}" stroke-linecap="round"
                stroke-dasharray="${arc * fraction} ${circumference}" transform="rotate(${start} ${cx} ${cy})"/>
        <circle cx="${knobX}" cy="${knobY}" r="14" fill="#fff"/>
        ${marker}
      </svg>`;
  }
}
customElements.define("ha-control-circular-slider", StubSlider);
"""

THEME = """
  :root {
    --primary-color: #03a9f4;
    --primary-text-color: #ffffff;
    --secondary-text-color: #9e9e9e;
    --card-background-color: #1c1c1e;
    --divider-color: #464646;
    --warning-color: #ffa726;
    --text-primary-color: #ffffff;
  }
  body { background: #111; margin: 0; padding: 18px;
         font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; }
  .row { display: flex; gap: 18px; align-items: flex-start; }
  .tile { width: 360px; background: var(--card-background-color);
          border-radius: 14px; overflow: hidden; }
  .cap { color: var(--secondary-text-color); font-size: 12px; margin: 14px 0 6px 4px; }
  h1 { color: #fff; font-size: 15px; font-weight: 500; margin: 0 0 4px; }
  p.note { color: var(--secondary-text-color); font-size: 12px; margin: 0 0 14px; }
"""

STATES = {
    "off": {
        "sensor.anova_cooker_status": {"state": "idle", "attributes": {}},
        "sensor.anova_cooker_timer_remaining": {"state": "0", "attributes": {}},
        "number.anova_cooker_cook_duration": {"state": "60", "attributes": {}},
        "binary_sensor.anova_cooker_low_water": {"state": "off", "attributes": {}},
        "climate.anova_cooker": {
            "state": "off",
            "attributes": {
                "temperature": 36.0, "current_temperature": 24.5,
                "temperature_unit": "°C", "min_temp": 5.0, "max_temp": 99.9,
            },
        },
    },
    "cook": {
        "sensor.anova_cooker_status": {"state": "cooking", "attributes": {}},
        "sensor.anova_cooker_timer_remaining": {"state": "26", "attributes": {}},
        "number.anova_cooker_cook_duration": {"state": "60", "attributes": {}},
        "binary_sensor.anova_cooker_low_water": {"state": "off", "attributes": {}},
        "climate.anova_cooker": {
            "state": "heat",
            "attributes": {
                "temperature": 57.0, "current_temperature": 54.6,
                "temperature_unit": "°C", "min_temp": 5.0, "max_temp": 99.9,
            },
        },
    },
    "low": {
        "sensor.anova_cooker_status": {"state": "cooking", "attributes": {}},
        "sensor.anova_cooker_timer_remaining": {"state": "51", "attributes": {}},
        "number.anova_cooker_cook_duration": {"state": "60", "attributes": {}},
        "binary_sensor.anova_cooker_low_water": {"state": "on", "attributes": {}},
        "climate.anova_cooker": {
            "state": "heat",
            "attributes": {
                "temperature": 57.0, "current_temperature": 54.6,
                "temperature_unit": "°C", "min_temp": 5.0, "max_temp": 99.9,
            },
        },
    },
}


def build() -> str:
    tiles = "".join(
        f'<div><div class="cap">{caption}</div><div class="tile" id="{key}"></div></div>'
        for key, caption in (
            ("off", "Off &mdash; the ring is the duration dial"),
            ("cook", "Cooking &mdash; the ring is the temperature, the countdown stays visible"),
            ("low", "Low water &mdash; warn and refuse to start"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Anova Cook Card &mdash; preview</title>
<style>{THEME}</style>
</head>
<body>
<h1>Anova Cook Card</h1>
<p class="note">The real card file, with a stand-in for Home Assistant's own circular
slider (the same 270&deg; dial) and Home Assistant's theme variables. Home Assistant
renders the same shapes.</p>
<div class="row">{tiles}</div>
<script>
{STAND_IN_SLIDER}
</script>
<script>
{CARD.read_text()}
</script>
<script>
const STATES = {json.dumps(STATES)};
for (const [key, states] of Object.entries(STATES)) {{
  const tile = document.getElementById(key);
  const card = document.createElement("anova-cook-card");
  card.setConfig({{ max: 240, step: 5 }});
  card.hass = {{ states, callService() {{}} }};
  tile.appendChild(card);
}}
</script>
</body>
</html>
"""


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/anova-card-preview.html")
    out.write_text(build())
    print(out)


if __name__ == "__main__":
    main()
