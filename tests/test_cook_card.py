"""The bundled card, rendered through node with a stub DOM.

The card's ring is Home Assistant's own `ha-state-control-climate-temperature`,
so what we assert here is the contract around it: the live climate state object
handed to the control, the warning-colour overrides for fault paths, and
everything that remains ours — the timer between - and +, the progress bar, the
Start/Stop gating, and the typed fields. Skipped when node is not available.
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
    stateObj: null,
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
// The markup starts these hidden (mirror it exactly: a stub cannot parse HTML).
for (const selector of [".val-input", ".big-input"]) {
  nodes.set(selector, Object.assign(makeElement(), { hidden: true }));
}
globalThis.HTMLElement = class {
  constructor() { this.shadowRoot = root; }
  attachShadow() { return root; }
};
globalThis.customElements = { define() {} };
globalThis.window = {};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
// The countdown ticker: captured instead of scheduled, and a clock that can
// be moved forward, so "one second later" is drivable from the tests.
globalThis.__ticks = [];
globalThis.setInterval = (fn) => { globalThis.__ticks.push(fn); return globalThis.__ticks.length; };
globalThis.clearInterval = (_handle) => {
  globalThis.__ticks = globalThis.__ticks.map(() => null);
};
let nowMs = 1_790_000_000_000;
const realNow = Date.now.bind(Date);
Date.now = () => nowMs;
globalThis.__advance = (seconds) => { nowMs += seconds * 1000; };
"""

ASSERTIONS = """
const card = new AnovaCookCard();
card.setConfig({ max: 240, step: 5 });
const at = (selector) => {
  if (!nodes.has(selector)) nodes.set(selector, makeElement());
  return nodes.get(selector);
};
const calls = [];
const stc = at("ha-state-control-climate-temperature");
const haCard = at("ha-card");
const setHass = (states2) => {
  card.hass = {
    states: states2,
    callService: (domain, service, data) => calls.push({ domain, service, data }),
  };
};
setHass(__STATES__);
__ACTIONS__
// What is on screen right after the interaction, before any later state update.
const immediate = {
  between: at(".val").innerHTML,
};
__AGAIN__
console.log("RESULT " + JSON.stringify({
  title: at(".title").textContent,
  stcPresent: nodes.has("ha-state-control-climate-temperature"),
  stcHidden: stc.hidden,
  stcState: stc.stateObj ? stc.stateObj.state : null,
  stcStateObj: stc.stateObj,
  offColorVar: haCard.styleProps["--state-climate-off-color"],
  heatColorVar: haCard.styleProps["--state-climate-heat-color"],
  barBackground: at(".bar").style.background,
  fillWidth: at(".fill").style.width,
  barColor: at(".fill").style.background,
  bigInputHidden: at(".big-input").hidden,
  bigInputValue: at(".big-input").value,
  valueHtml: at(".val").innerHTML,
  minusVisibility: at(".minus").style.visibility,
  plusVisibility: at(".plus").style.visibility,
  valHidden: at(".val").hidden,
  inputHidden: at(".val-input").hidden,
  inputValue: at(".val-input").value,
  startDisabled: at(".start").disabled,
  stopDisabled: at(".stop").disabled,
  calls: calls,
  immediate: immediate,
  capturedBetween: globalThis.__captured !== undefined ? globalThis.__captured : null,
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
    climate_state: str | None = None,
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
        if climate_state is not None:
            climate["state"] = climate_state
        out["climate.anova_cooker"] = climate
    return out


def render(
    state: dict,
    actions: str = "",
    again: list[dict] | None = None,
) -> dict:
    script = (
        STUBS
        + CARD.read_text()
        + ASSERTIONS.replace("__STATES__", json.dumps(state))
        .replace("__ACTIONS__", actions)
        .replace(
            "__AGAIN__",
            "\n".join(f"setHass({json.dumps(next)});" for next in (again or [])),
        )
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


def test_the_ring_is_home_assistants_own_control_with_the_climate_state() -> None:
    state = states(status="idle")
    out = render(state)
    assert out["stcPresent"] is True
    assert out["stcHidden"] is False
    assert out["stcStateObj"] == state["climate.anova_cooker"]
    assert out["title"] == "Anova Cooker"                  # like the card it replaces


def test_off_holds_the_timer_preset_and_refuses_stop() -> None:
    out = render(states(status="idle"))
    assert out["barBackground"] == "transparent"   # holds the space, not the eye
    assert out["fillWidth"] == "0%"
    assert out["valueHtml"] == "60<small> min</small>"
    assert out["minusVisibility"] == ""
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True
    assert out["heatColorVar"] == ""               # no override while all is well
    assert out["offColorVar"] == ""


def test_heating_fills_the_progress_bar_and_hides_the_steps() -> None:
    out = render(states(status="cooking", remaining=26))
    assert out["barColor"] == "var(--state-climate-heat-color, #ff6f22)"   # orange while it works
    assert out["valueHtml"] == "26<small> min</small>"      # the countdown, where the
    assert out["minusVisibility"] == "hidden"               # step aside, keep their place
    assert out["plusVisibility"] == "hidden"
    assert out["barBackground"] == "var(--divider-color)"
    assert 40 < float(out["fillWidth"].rstrip("%")) < 45
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is False


def test_low_water_takes_the_warning_colour() -> None:
    out = render(states(status="cooking", remaining=26, low=True))
    assert out["heatColorVar"].endswith("var(--warning-color, #ffa600)")
    assert out["offColorVar"].endswith("var(--warning-color, #ffa600)")
    assert out["barColor"] == "var(--warning-color, #ffa600)"
    assert out["startDisabled"] is True
    assert out["valueHtml"] == "26<small> min</small>"


def test_a_cook_without_a_timer_says_so() -> None:
    out = render(states(status="cooking", remaining=0, duration=0))
    assert out["valueHtml"] == "no timer"
    assert out["fillWidth"] == "0%"


def test_a_cook_whose_timer_never_ran_says_no_timer() -> None:
    """The preset exists but the countdown never started: say so, do not show 0 min."""
    state = states(status="cooking", remaining=0, duration=1)
    state["switch.anova_cooker_timer"] = {"state": "off", "attributes": {}}
    out = render(state)
    assert out["valueHtml"] == "no timer"
    assert out["fillWidth"] == "0%"


def test_the_countdown_holds_whole_minutes_and_then_shows_seconds() -> None:
    """remaining 26 is "26 min" at once and still "26 min" half a minute later."""
    state = states(status="cooking", remaining=26, duration=60)
    state["switch.anova_cooker_timer"] = {"state": "on", "attributes": {}}
    actions = "__advance(35); globalThis.__ticks.filter(Boolean).forEach((fn) => fn());"
    out = render(state, actions=actions)
    assert out["valueHtml"] == "26<small> min</small>"


def test_the_last_minute_ticks_in_seconds() -> None:
    """remaining 1 with the timer on is "1 min" at once, then seconds tick."""
    state = states(status="cooking", remaining=1, duration=60)
    state["switch.anova_cooker_timer"] = {"state": "on", "attributes": {}}
    actions = (
        # snapshotted at elapsed 0, before the clock moves
        "globalThis.__captured = at('.val').innerHTML;"
        "__advance(35);"
        "globalThis.__ticks.filter(Boolean).forEach((fn) => fn());"
    )
    out = render(state, actions=actions)
    assert out["capturedBetween"] == "1<small> min</small>"
    assert out["valueHtml"] == "25<small> s</small>"


def test_a_stale_poll_re_anchors_instead_of_drifting_below_zero() -> None:
    """If the state stops moving, the clock re-anchors; the display never lies."""
    state = states(status="cooking", remaining=1, duration=60)
    state["switch.anova_cooker_timer"] = {"state": "on", "attributes": {}}
    # Just over a minute without new numbers from the cooker: the interpolation
    # would want negative seconds; re-anchoring holds the last full minute.
    actions = "__advance(70); globalThis.__ticks.filter(Boolean).forEach((fn) => fn());"
    out = render(state, actions=actions)
    assert out["valueHtml"] == "1<small> min</small>"
    assert float(out["fillWidth"].rstrip("%")) > 1


def test_a_just_started_cook_shows_the_countdown_at_once() -> None:
    """Start pressed: the countdown is the preset at once, never "no timer"."""
    out = render(
        states(status="idle", duration=5),
        actions='at(".start").onclick();',
    )
    assert out["calls"][0] == {
        "domain": "button",
        "service": "press",
        "data": {"entity_id": "button.anova_cooker_start_cook"},
    }
    assert out["valueHtml"] == "5<small> min</small>"      # anchored at the press
    assert out["minusVisibility"] == "hidden"              # already mid-cook posture
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is False


def test_a_preset_of_one_says_no_timer_until_the_countdown_runs() -> None:
    """A sitting preset is not a countdown: a cook without one says so."""
    out = render(states(status="cooking", remaining=0, duration=1))
    assert out["valueHtml"] == "no timer"
    assert out["fillWidth"] == "0%"


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


def test_a_stepped_duration_shows_at_once() -> None:
    """A stepper that does not move until the next poll feels broken."""
    out = render(
        states(status="idle", duration=60),
        actions='at(".plus").onclick();',
        again=[states(status="idle", duration=60)],       # not caught up yet
    )
    assert out["calls"][0]["data"] == {"entity_id": "number.anova_cooker_cook_duration", "value": 65}
    assert out["immediate"]["between"] == "65<small> min</small>"   # before the poll


def test_tapping_the_ring_temperature_opens_a_field_to_type_in() -> None:
    """The big number lives inside Home Assistant's control; the composed click reaches us."""
    out = render(
        states(status="idle", target=36.0),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{}, { localName: "ha-big-number" }] });'
        ),
    )
    assert out["bigInputHidden"] is False
    assert out["bigInputValue"] == "36"


def test_typing_a_temperature_sets_it() -> None:
    out = render(
        states(status="idle", target=36.0),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{ localName: "ha-big-number" }] });'
            'at(".big-input").value = "57.5";'
            'at(".big-input").onkeydown({ key: "Enter", preventDefault() {} });'
        ),
    )
    assert out["calls"] == [
        {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": "climate.anova_cooker", "temperature": 57.5},
        }
    ]
    assert out["bigInputHidden"] is True


def test_the_temperature_can_be_typed_mid_cook_too() -> None:
    out = render(
        states(status="cooking", remaining=26, target=36.0),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{ localName: "ha-big-number" }] });'
            'at(".big-input").value = "58";'
            'at(".big-input").onkeydown({ key: "Enter", preventDefault() {} });'
        ),
    )
    assert out["calls"][0]["data"]["temperature"] == 58.0


def test_a_click_that_is_not_the_big_number_opens_nothing() -> None:
    out = render(
        states(status="idle", target=36.0),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{ localName: "ha-control-circular-slider" }] });'
        ),
    )
    assert out["bigInputHidden"] is True
    assert out["calls"] == []


def test_escape_leaves_the_temperature_alone() -> None:
    out = render(
        states(status="idle", target=36.0),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{ localName: "ha-big-number" }] });'
            'at(".big-input").value = "99";'
            'at(".big-input").onkeydown({ key: "Escape", preventDefault() {} });'
        ),
    )
    assert out["calls"] == []
    assert out["bigInputHidden"] is True


def test_an_unreachable_cooker_says_so_and_refuses_to_act() -> None:
    """The cooker being off must not leave the last reading on screen.

    A dropped link fails the coordinator's update, so the climate entity
    reports unavailable too and the control renders its unavailable form.
    """
    out = render(
        states(status="unavailable", climate_state="unavailable"),
        actions=(
            'at(".dial").listeners["click"]('
            '{ composedPath: () => [{ localName: "ha-big-number" }] });'
        ),
    )
    assert out["stcStateObj"]["state"] == "unavailable"    # the control says it
    assert out["valueHtml"] == "—"                         # and no stale timer either
    assert out["minusVisibility"] == "hidden"
    assert out["bigInputHidden"] is True                   # nothing to type into
    assert out["startDisabled"] is True
    assert out["stopDisabled"] is True


def test_without_a_climate_entity_the_ring_stays_hidden() -> None:
    """A partial entity set still works, and the timer stays usable."""
    out = render(states(status="idle", with_climate=False))
    assert out["stcHidden"] is True
    assert out["valueHtml"] == "60<small> min</small>"
    assert out["startDisabled"] is False
    assert out["stopDisabled"] is True
