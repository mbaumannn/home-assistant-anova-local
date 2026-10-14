"""The bundled card, rendered through node with a stub DOM.

The card is the only part of this integration a user looks at, and it is built to
match Home Assistant's own thermostat card, so what ends up on screen is asserted
here: the state inside the ring, the big number with its small decimal and unit,
the water temperature handed to Home Assistant's dial as its marker (so the dial
draws the dot itself), the colours per state, and our timer between - and +.
Skipped when node is not available.
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

STUBS = """
const nodes = new Map();
function makeElement() {
  const el = {
    textContent: "", innerHTML: "", hidden: false, disabled: false,
    min: 0, max: 0, step: 0, value: 0, current: null,
    styleProps: {},
    style: {
      setProperty: (name, value) => { el.styleProps[name] = value; },
      width: "", background: "",
    },
    classes: new Set(),
    listeners: {},
    addEventListener(type, fn) { el.listeners[type] = fn; },
    focus() {},
    select() {},
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
// The markup starts these hidden; a stub cannot parse HTML, so say so.
for (const selector of [".val-input", ".bar"]) {
  nodes.set(selector, Object.assign(makeElement(), { hidden: true }));
}
globalThis.HTMLElement = class {
  constructor() { this.shadowRoot = root; }
  attachShadow() { return root; }
};
globalThis.customElements = { define() {} };
globalThis.window = {};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
"""

ASSERTIONS = """
const card = new AnovaCookCard();
card.setConfig({ max: 240, step: 5 });
const at = (selector) => {
  if (!nodes.has(selector)) nodes.set(selector, makeElement());
  return nodes.get(selector);
};
const calls = [];
const slider = at("ha-control-circular-slider");
const setHass = (states2) => {
  card.hass = {
    states: states2,
    callService: (domain, service, data) => calls.push({ domain, service, data }),
  };
};
setHass(__STATES__);
const drag = __DRAG__;
if (drag !== null) {
  slider.listeners["value-changed"]({ detail: { value: drag } });
}
__ACTIONS__
// Each extra state is a later Home Assistant update: the trail shows what the
// dial did in response, which is how "does it jump?" is answered.
const trail = [];
for (const next of __AGAIN__) {
  setHass(next);
  trail.push({ min: slider.min, max: slider.max, value: slider.value });
}
console.log("RESULT " + JSON.stringify({
  title: at(".title").textContent,
  state: at(".state").textContent,
  warns: at(".state").classes.has("warn"),
  center: at(".big").innerHTML,
  cur: at(".cur").textContent,
  secondaryHidden: at(".label.secondary").hidden,
  sr: at(".sr").textContent,
  accent: slider.styleProps["--control-circular-slider-color"],
  markerCurrent: slider.current === undefined ? null : slider.current,
  barHidden: at(".bar").hidden,
  barWidth: at(".fill").style.width,
  barColor: at(".fill").style.background,
  valueHtml: at(".val").innerHTML,
  minusHidden: at(".minus").hidden,
  plusHidden: at(".plus").hidden,
  valHidden: at(".val").hidden,
  inputHidden: at(".val-input").hidden,
  inputValue: at(".val-input").value,
  startDisabled: at(".start").disabled,
  stopDisabled: at(".stop").disabled,
  sliderValue: slider.value,
  sliderMin: slider.min,
  sliderMax: slider.max,
  calls: calls,
  trail: trail,
}));
"""

CLIMATE = {
    "state": "heat",
    "attributes": {
        "friendly_name": "Anova Cooker",
        "temperature": 36.0,
        "current_temperature": 24.5,
        "temperature_unit": "°C",
        "min_temp": 5.0,
        "max_temp": 99.9,
    },
}


def states(
    *,
    status: str,
    remaining: int = 0,
    duration: int = 60,
    low: bool = False,
    target: float = 36.0,
    current: float = 24.5,
    with_climate: bool = True,
) -> dict:
    out = {
        "sensor.anova_cooker_status": {"state": status, "attributes": {}},
        "sensor.anova_cooker_timer_remaining": {"state": str(remaining), "attributes": {}},
        "number.anova_cooker_cook_duration": {"state": str(duration), "attributes": {}},
        "binary_sensor.anova_cooker_low_water": {
            "state": "on" if low else "off",
            "attributes": {},
        },
    }
    if with_climate:
        climate = json.loads(json.dumps(CLIMATE))
        climate["attributes"]["temperature"] = target
        climate["attributes"]["current_temperature"] = current
        out["climate.anova_cooker"] = climate
    return out


def render(
    state: dict,
    drag: float | None = None,
    actions: str = "",
    again: list[dict] | None = None,
) -> dict:
    script = (
        STUBS
        + CARD.read_text()
        + ASSERTIONS.replace("__STATES__", json.dumps(state))
        .replace("__DRAG__", "null" if drag is None else json.dumps(drag))
        .replace("__ACTIONS__", actions)
        .replace("__AGAIN__", json.dumps(again or []))
    )
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


def test_off_is_blue_and_shows_the_target_with_the_water_temperature() -> None:
    out = render(states(status="idle"))
    assert out["title"] == "Anova Cooker"                  # like the card it replaces
    assert out["state"] == "Off"                            # inside the ring
    assert out["center"] == "<span>36</span><span class=\"decimal\">.0</span><span class=\"unit\">°C</span>"
    assert out["cur"] == "24.5 °C"
    assert out["secondaryHidden"] is False
    assert out["accent"] == "var(--primary-color)"          # blue while setting up
    assert out["markerCurrent"] == 24.5                     # Home Assistant's dial draws the dot
    assert out["barHidden"] is True
    assert out["valueHtml"] == "60<small>min</small>"
    assert out["minusHidden"] is False
    assert out["sliderValue"] == 36.0
    assert (out["sliderMin"], out["sliderMax"]) == (26.0, 46.0)
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True


def test_the_state_is_said_in_the_middle_of_the_ring() -> None:
    assert render(states(status="cooking", current=36.2))["state"] == "Cooking"
    assert render(states(status="cooking", current=24.5))["state"] == "Heating"
    assert render(states(status="idle"))["state"] == "Off"


def test_heating_is_orange_and_counts_down_between_minus_and_plus() -> None:
    out = render(states(status="cooking", remaining=26))
    assert out["state"] == "Heating"
    assert out["accent"] == "var(--state-climate-heat-color, #ff6f22)"   # orange while it works
    assert out["barColor"] == "var(--state-climate-heat-color, #ff6f22)"
    assert out["valueHtml"] == "26<small>min</small>"      # the countdown, where the
    assert out["minusHidden"] is True                      # preset sits when off
    assert out["plusHidden"] is True
    assert out["barHidden"] is False
    assert 40 < float(out["barWidth"].rstrip("%")) < 45
    assert out["markerCurrent"] == 24.5                    # the marker stays visible
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is False


def test_low_water_takes_the_warning_colour() -> None:
    out = render(states(status="cooking", remaining=26, low=True))
    assert out["state"] == "Low water"
    assert out["warns"] is True
    assert out["accent"] == "var(--warning-color, #ffa600)"
    assert out["startDisabled"] is True
    assert out["valueHtml"] == "26<small>min</small>"


def test_the_target_temperature_can_be_set_before_the_cook() -> None:
    out = render(states(status="idle"), drag=57.3)
    assert out["calls"] == [
        {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": "climate.anova_cooker", "temperature": 57.3},
        }
    ]


def test_the_temperature_can_still_be_changed_mid_cook() -> None:
    out = render(states(status="cooking", remaining=26), drag=58.0)
    assert out["calls"][0]["service"] == "set_temperature"
    assert out["calls"][0]["data"]["temperature"] == 58.0


def test_a_cook_without_a_timer_says_so() -> None:
    out = render(states(status="cooking", remaining=0, duration=0))
    assert out["valueHtml"] == "no timer"
    assert out["barHidden"] is True


def test_dragging_the_temperature_does_not_recentre_the_ring() -> None:
    """Reported from real use: after a drag the knob jumped back to the middle."""
    out = render(
        states(status="idle", target=36.0),
        drag=40.0,
        again=[states(status="idle", target=40.0)],
    )
    assert out["calls"][0]["data"]["temperature"] == 40.0
    assert out["trail"][0] == {"min": 26.0, "max": 46.0, "value": 40.0}   # not 30..50 / 50%


def test_a_target_from_elsewhere_still_recentres_the_ring() -> None:
    out = render(states(status="idle", target=36.0), again=[states(status="idle", target=80.0)])
    assert out["trail"][0] == {"min": 70.0, "max": 90.0, "value": 80.0}


def test_a_state_update_while_dragging_leaves_the_dial_alone() -> None:
    out = render(
        states(status="idle", target=36.0),
        actions='slider.listeners["pointerdown"]();',
        again=[states(status="idle", target=90.0)],
    )
    assert out["trail"][0] == {"min": 26.0, "max": 46.0, "value": 36.0}   # the finger wins


def test_tapping_the_duration_opens_a_field_to_type_in() -> None:
    """Pressing the number (or holding -/+) lets you type minutes instead of stepping."""
    out = render(states(status="idle", duration=60), actions='at(".val").onclick();')
    assert out["inputHidden"] is False
    assert out["valHidden"] is True
    assert out["inputValue"] == "60"


def test_typing_a_number_sets_the_duration() -> None:
    out = render(
        states(status="idle", duration=60),
        actions=(
            'at(".val").onclick();'
            'at(".val-input").value = "45";'
            'at(".val-input").onkeydown({ key: "Enter", preventDefault() {} });'
        ),
    )
    assert out["calls"] == [
        {
            "domain": "number",
            "service": "set_value",
            "data": {"entity_id": "number.anova_cooker_cook_duration", "value": 45},
        }
    ]
    assert out["inputHidden"] is True
    assert out["valHidden"] is False


def test_a_long_press_on_minus_opens_the_same_field() -> None:
    out = render(
        states(status="idle", duration=60),
        actions='at(".minus").oncontextmenu({ preventDefault() {} });',
    )
    assert out["inputHidden"] is False
    assert out["inputValue"] == "60"
    assert out["calls"] == []


def test_escape_leaves_the_duration_alone() -> None:
    out = render(
        states(status="idle", duration=60),
        actions=(
            'at(".val").onclick();'
            'at(".val-input").value = "999";'
            'at(".val-input").onkeydown({ key: "Escape", preventDefault() {} });'
        ),
    )
    assert out["calls"] == []
    assert out["inputHidden"] is True


def test_the_preset_cannot_be_typed_over_mid_cook() -> None:
    out = render(states(status="cooking", remaining=26), actions='at(".val").onclick();')
    assert out["inputHidden"] is True


def test_without_a_climate_entity_the_ring_is_the_duration_dial() -> None:
    """A partial entity set still works, and then dragging sets the duration."""
    out = render(states(status="idle", with_climate=False), drag=90)
    assert out["center"] == "60<span class=\"unit\">min</span>"
    assert out["cur"] == ""
    assert out["secondaryHidden"] is True
    assert out["markerCurrent"] is None                   # no marker without a reading
    assert out["sliderValue"] == 60
    assert out["calls"][0]["service"] == "set_value"
    assert out["calls"][0]["data"] == {"entity_id": "number.anova_cooker_cook_duration", "value": 90}
