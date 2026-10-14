"""The bundled card, rendered through node with a stub DOM.

The card is the only part of this integration a user looks at, so it is rendered
in every state and what ends up on screen is asserted — including the two things
that are easy to break: the target temperature must be settable *before* a cook,
and the countdown must stay visible while the ring shows the temperature.
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

# The card only asks its shadow root for a handful of selectors, and it only needs
# addEventListener for the dial, so a stub that answers those is enough to see what
# a user would see and what the card would ask Home Assistant to do.
STUBS = """
const nodes = new Map();
function makeElement() {
  const el = {
    textContent: "", innerHTML: "", hidden: false, disabled: false,
    min: 0, max: 0, step: 0, value: 0,
    style: { setProperty() {}, width: "", background: "" },
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
// The markup starts the typing field hidden; a stub cannot parse HTML, so say so.
nodes.set(".val-input", Object.assign(makeElement(), { hidden: true }));
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
  state: at(".state").textContent,
  warns: at(".state").classes.has("warn"),
  left: at(".left").textContent,
  center: at(".big").innerHTML,
  cap: at(".cap").textContent,
  barHidden: at(".bar").hidden,
  barWidth: at(".fill").style.width,
  stepperHidden: at(".dur").hidden,
  stepperValue: at(".val").textContent,
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


def test_off_shows_the_temperature_dial_and_the_duration_stepper() -> None:
    """Before a cook you set the temperature; the duration is the -/+ row."""
    out = render(states(status="idle"))
    assert out["state"] == "Off"
    assert out["left"] == "water 24.5 °C"
    assert "36.0" in out["center"]                 # the ring is the target temperature
    assert out["cap"] == "target"
    assert out["sliderValue"] == 36.0
    assert (out["sliderMin"], out["sliderMax"]) == (26.0, 46.0)
    assert out["stepperHidden"] is False           # the duration is still settable
    assert out["stepperValue"] == "60 min"
    assert out["barHidden"] is True                # nothing is counting down
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True


def test_the_target_temperature_can_be_set_before_the_cook() -> None:
    out = render(states(status="idle"), drag=57.3)
    assert out["calls"] == [
        {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": "climate.anova_cooker", "temperature": 57.3},
        }
    ]


def test_the_duration_can_still_be_set_before_the_cook() -> None:
    """The stepper is the duration control now that the ring is the temperature."""
    out = render(states(status="idle", duration=60))
    assert out["stepperHidden"] is False
    assert out["stepperValue"] == "60 min"
    assert "36.0" in out["center"]        # the ring shows the temperature, not the duration


def test_cooking_shows_temperature_and_keeps_the_countdown_visible() -> None:
    """The requirement: while the ring shows temperature, the timer stays in view."""
    out = render(states(status="cooking", remaining=26))
    assert out["state"] == "Heating"              # 24.5 is below the 36.0 target
    assert out["left"] == "26 min left"           # the countdown, always visible
    assert out["barHidden"] is False
    assert 40 < float(out["barWidth"].rstrip("%")) < 45    # 26 of 60 minutes
    assert "36.0" in out["center"]
    assert out["cap"] == "water 24.5 °C"
    assert out["stepperHidden"] is True            # the preset is not fiddled with mid-cook
    assert out["sliderValue"] == 36.0
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is False


def test_the_temperature_can_still_be_changed_mid_cook() -> None:
    out = render(states(status="cooking", remaining=26), drag=58.0)
    assert out["calls"][0]["service"] == "set_temperature"
    assert out["calls"][0]["data"]["temperature"] == 58.0


def test_at_temperature_it_says_cooking() -> None:
    out = render(states(status="cooking", remaining=26, current=36.0))
    assert out["state"] == "Cooking"


def test_low_water_warns_and_refuses_to_start() -> None:
    out = render(states(status="cooking", remaining=26, low=True))
    assert out["state"] == "Low water"
    assert out["warns"] is True
    assert out["startDisabled"] is True
    assert out["left"] == "26 min left"            # the countdown does not disappear


def test_a_cook_without_a_timer_says_so() -> None:
    out = render(states(status="cooking", remaining=0, duration=0))
    assert out["left"] == "no timer"
    assert out["barHidden"] is True
    assert out["state"] == "Heating"


def test_dragging_the_temperature_does_not_recentre_the_ring() -> None:
    """The complaint from real use: after a drag the knob jumped back to the middle.

    The dial used to be re-centred around the new target on every render, so the
    knob always sat at 50%. The range now stays put as long as it contains the
    target, which is what makes dragging feel like dragging.
    """
    out = render(states(status="idle", target=36.0), drag=40.0, again=[states(status="idle", target=40.0)])
    assert out["calls"][0]["data"]["temperature"] == 40.0
    assert out["trail"][0] == {"min": 26.0, "max": 46.0, "value": 40.0}   # not 30..50 / 50%


def test_a_target_from_elsewhere_still_recentres_the_ring() -> None:
    """An automation (or the cooker) can move the target outside the range."""
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
    assert out["inputHidden"] is False            # the field takes over from the number
    assert out["valHidden"] is True
    assert out["inputValue"] == "60"              # pre-filled with the current preset


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
    assert out["inputHidden"] is True             # and the field closes again
    assert out["valHidden"] is False


def test_a_long_press_on_minus_opens_the_same_field() -> None:
    out = render(
        states(status="idle", duration=60),
        actions='at(".minus").oncontextmenu({ preventDefault() {} });',
    )
    assert out["inputHidden"] is False
    assert out["inputValue"] == "60"
    assert out["calls"] == []                     # opening a field is not a change


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


def test_without_a_climate_entity_the_ring_is_the_duration_dial() -> None:
    """A partial entity set still works, and then dragging sets the duration."""
    out = render(states(status="idle", with_climate=False), drag=90)
    assert "60" in out["center"] and "min" in out["center"]
    assert out["cap"] == "duration"
    assert out["sliderValue"] == 60
    assert out["calls"][0]["service"] == "set_value"
    assert out["calls"][0]["data"] == {"entity_id": "number.anova_cooker_cook_duration", "value": 90}
