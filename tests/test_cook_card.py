"""The bundled card, rendered through node with a stub DOM.

The card is the only part of this integration a user actually looks at, and the
whole point of it is that the countdown stays visible while the ring shows the
temperature. So it is rendered in every state and what ends up on screen is
asserted. Skipped when node is not available.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

CARD = (
    Path(__file__).parent.parent
    / "custom_components"
    / "anova_local"
    / "frontend"
    / "anova-cook-card.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The card only asks its shadow root for a handful of selectors, so a stub that
# answers those is enough to see what a user would see.
STUBS = """
const nodes = new Map();
function makeElement() {
  const el = {
    textContent: "", innerHTML: "", hidden: false, disabled: false,
    min: 0, max: 0, step: 0, value: 0,
    style: { setProperty() {}, width: "", background: "" },
    classes: new Set(),
    addEventListener() {},
  };
  el.classList = {
    toggle: (name, on) => (on ? el.classes.add(name) : el.classes.delete(name)),
    add: (name) => el.classes.add(name),
    remove: (name) => el.classes.delete(name),
  };
  return el;
}
const root = {
  set innerHTML(_html) {},
  querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, makeElement());
    return nodes.get(selector);
  },
};
globalThis.HTMLElement = class {
  constructor() { this.shadowRoot = root; }
  attachShadow() { return root; }
};
globalThis.customElements = { define() {} };
globalThis.window = {};
"""

ASSERTIONS = """
const card = new AnovaCookCard();
card.setConfig({ max: 240, step: 5 });
card.hass = { states: __STATES__, callService() {} };
const at = (selector) => {
  if (!nodes.has(selector)) nodes.set(selector, makeElement());
  return nodes.get(selector);
};
console.log("RESULT " + JSON.stringify({
  state: at(".state").textContent,
  warns: at(".state").classes.has("warn"),
  left: at(".left").textContent,
  center: at(".big").innerHTML,
  cap: at(".cap").textContent,
  barHidden: at(".bar").hidden,
  barWidth: at(".fill").style.width,
  stepperHidden: at(".dur").hidden,
  stepperValue: at(".val").textContent,
  startDisabled: at(".start").disabled,
  stopDisabled: at(".stop").disabled,
  sliderValue: at("ha-control-circular-slider").value,
  sliderMin: at("ha-control-circular-slider").min,
  sliderMax: at("ha-control-circular-slider").max,
}));
"""

CLIMATE = {
    "state": "heat",
    "attributes": {
        "temperature": 36.0,
        "current_temperature": 24.5,
        "temperature_unit": "°C",
        "min_temp": 5.0,
        "max_temp": 99.9,
    },
}


def states(*, status: str, remaining: int = 0, duration: int = 60, low: bool = False,
           target: float = 36.0, current: float = 24.5) -> dict:
    climate = json.loads(json.dumps(CLIMATE))
    climate["attributes"]["temperature"] = target
    climate["attributes"]["current_temperature"] = current
    return {
        "sensor.anova_cooker_status": {"state": status, "attributes": {}},
        "sensor.anova_cooker_timer_remaining": {"state": str(remaining), "attributes": {}},
        "number.anova_cooker_cook_duration": {"state": str(duration), "attributes": {}},
        "binary_sensor.anova_cooker_low_water": {
            "state": "on" if low else "off",
            "attributes": {},
        },
        "climate.anova_cooker": climate,
    }


def render(state: dict) -> dict:
    script = STUBS + CARD.read_text() + ASSERTIONS.replace("__STATES__", json.dumps(state))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            ["node", str(path)], capture_output=True, text=True, timeout=30, check=False
        )
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("RESULT "))
    return json.loads(line.removeprefix("RESULT "))


def test_off_shows_the_duration_dial_and_the_water_temperature() -> None:
    out = render(states(status="idle"))
    assert out["state"] == "Off"
    assert out["left"] == "water 24.5 °C"
    assert "60" in out["center"] and "min" in out["center"]
    assert out["cap"] == "duration"
    assert out["barHidden"] is True              # no countdown while nothing runs
    assert out["stepperHidden"] is False
    assert out["stepperValue"] == "60 min"
    assert out["sliderValue"] == 60              # the ring is the duration
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True


def test_cooking_shows_temperature_and_keeps_the_countdown_visible() -> None:
    """The requirement: while the ring shows temperature, the timer stays in view."""
    out = render(states(status="cooking", remaining=26))
    assert out["state"] == "Heating"             # 24.5 is below the 36.0 target
    assert out["left"] == "26 min left"          # the countdown, always visible
    assert out["barHidden"] is False
    assert 40 < float(out["barWidth"].rstrip("%")) < 45   # 26 of 60 minutes
    assert "36.0" in out["center"]                # the ring is the temperature
    assert out["cap"] == "water 24.5 °C"
    assert out["stepperHidden"] is True           # the stepper belongs to the dial
    assert out["sliderValue"] == 36.0
    assert (out["sliderMin"], out["sliderMax"]) == (26.0, 46.0)
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is False


def test_at_temperature_it_says_cooking() -> None:
    out = render(states(status="cooking", remaining=26, current=36.0))
    assert out["state"] == "Cooking"


def test_low_water_warns_and_refuses_to_start() -> None:
    out = render(states(status="cooking", remaining=26, low=True))
    assert out["state"] == "Low water"
    assert out["warns"] is True
    assert out["startDisabled"] is True
    assert out["left"] == "26 min left"           # the countdown does not disappear


def test_a_cook_without_a_timer_says_so() -> None:
    out = render(states(status="cooking", remaining=0, duration=0))
    assert out["left"] == "no timer"
    assert out["barHidden"] is True
    assert out["state"] == "Heating"
