"""The bundled card, rendered through node with a stub DOM.

The card is the only part of this integration a user looks at, so it is rendered
in every state and what ends up on screen is asserted — including the things that
are easy to break: the target temperature must be settable before a cook, the
countdown must count between - and +, and the water-temperature marker must land
on the ring at the right place. Skipped when node is not available.
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
    min: 0, max: 0, step: 0, value: 0,
    style: { setProperty() {}, width: "", background: "", left: "", top: "" },
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
for (const selector of [".val-input", ".cur", ".cap", ".dot"]) {
  nodes.set(selector, Object.assign(makeElement(), { hidden: true }));
}
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
  center: at(".big").innerHTML,
  cur: at(".cur").innerHTML,
  curHidden: at(".cur").hidden,
  capText: at(".cap").textContent,
  capHidden: at(".cap").hidden,
  dotHidden: at(".dot").hidden,
  dotLeft: at(".dot").style.left,
  dotTop: at(".dot").style.top,
  barHidden: at(".bar").hidden,
  barWidth: at(".fill").style.width,
  valueBetween: at(".val").textContent,
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


def test_off_shows_the_target_large_with_the_water_temperature_below_it() -> None:
    """The look that was preferred: big target, small unit, current temp under it."""
    out = render(states(status="idle"))
    assert out["state"] == "Off"
    assert "36.0" in out["center"]
    assert "<small>°C</small>" in out["center"]       # the unit stays small
    assert "24.5 °C" in out["cur"]                    # the water temperature,
    assert "mdi:thermometer" in out["cur"]            # with the thermometer
    assert out["curHidden"] is False
    assert out["capHidden"] is True                   # no "target" label needed
    assert out["barHidden"] is True
    assert out["valueBetween"] == "60 min"            # the preset
    assert out["minusHidden"] is False                # -/+ stay available
    assert out["sliderValue"] == 36.0
    assert (out["sliderMin"], out["sliderMax"]) == (26.0, 46.0)
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True


def test_the_water_temperature_is_a_marker_on_the_ring() -> None:
    """A current temperature in the middle of the dial sits at the top of the ring."""
    # The range is the target plus/minus ten, so 36.0 with a target of 36.0 is the
    # middle of the arc: 135 + 270/2 = 270 degrees, which is the top of the dial.
    out = render(states(status="idle", target=36.0, current=36.0))
    assert out["dotHidden"] is False
    assert abs(float(out["dotLeft"].rstrip("%")) - 50.0) < 0.5
    assert abs(float(out["dotTop"].rstrip("%")) - 4.7) < 0.5

    # A colder reading sits further back along the arc, on the knob's own scale.
    cold = render(states(status="idle", target=36.0, current=26.0))
    assert abs(float(cold["dotLeft"].rstrip("%")) - 18.0) < 0.5
    assert abs(float(cold["dotTop"].rstrip("%")) - 82.0) < 0.5


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
    out = render(states(status="idle", duration=60))
    assert out["valueBetween"] == "60 min"
    assert out["minusHidden"] is False
    assert "36.0" in out["center"]        # the ring shows the temperature now


def test_cooking_counts_down_between_minus_and_plus() -> None:
    """The requirement: the remaining minutes live between - and +, not in a corner."""
    out = render(states(status="cooking", remaining=26))
    assert out["state"] == "Heating"              # 24.5 is below the 36.0 target
    assert out["valueBetween"] == "26 min"        # the countdown, exactly where the
    assert out["minusHidden"] is True             # preset was; the buttons step aside
    assert out["plusHidden"] is True
    assert out["barHidden"] is False
    assert 40 < float(out["barWidth"].rstrip("%")) < 45        # 26 of 60 minutes
    assert "36.0" in out["center"]
    assert "24.5 °C" in out["cur"]
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
    assert out["valueBetween"] == "26 min"        # the countdown does not disappear


def test_a_cook_without_a_timer_says_so() -> None:
    out = render(states(status="cooking", remaining=0, duration=0))
    assert out["valueBetween"] == "no timer"
    assert out["barHidden"] is True
    assert out["state"] == "Heating"


def test_dragging_the_temperature_does_not_recentre_the_ring() -> None:
    """The complaint from real use: after a drag the knob jumped back to the middle."""
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


def test_the_preset_cannot_be_typed_over_mid_cook() -> None:
    """The number between -/+ is the countdown then, not something to edit."""
    out = render(
        states(status="cooking", remaining=26), actions='at(".val").onclick();'
    )
    assert out["inputHidden"] is True


def test_without_a_climate_entity_the_ring_is_the_duration_dial() -> None:
    """A partial entity set still works, and then dragging sets the duration."""
    out = render(states(status="idle", with_climate=False), drag=90)
    assert "60" in out["center"] and "min" in out["center"]
    assert out["capHidden"] is False and out["capText"] == "duration"
    assert out["curHidden"] is True
    assert out["dotHidden"] is True
    assert out["sliderValue"] == 60
    assert out["calls"][0]["service"] == "set_value"
    assert out["calls"][0]["data"] == {"entity_id": "number.anova_cooker_cook_duration", "value": 90}
