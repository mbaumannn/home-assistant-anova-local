"""Validate the blueprints and render their templates with Home Assistant.

The templates are rendered with Home Assistant's own template engine against
``hass`` states, so the real ``states()``/``state_attr()`` semantics are used
rather than a hand-rolled mock.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

BLUEPRINT_DIR = Path(__file__).parent.parent / "blueprints" / "automation" / "anova_local"


class _Loader(yaml.SafeLoader):
    """Load blueprint YAML while tolerating the ``!input`` tag."""


_Loader.add_multi_constructor("!input", lambda _loader, _suffix, node: {"__input__": node.value})


def _load(name: str) -> dict:
    return yaml.load((BLUEPRINT_DIR / name).read_text(), Loader=_Loader)


async def _render(hass: HomeAssistant, value_template: str, variables: dict):
    template = Template(value_template, hass)
    return template.async_render(variables, parse_result=True)


# --- Anova reached temperature -------------------------------------------------


def test_reached_temperature_exposes_entity_to_the_trigger():
    data = _load("anova_reached_temperature.yaml")

    assert data["blueprint"]["domain"] == "automation"
    # The climate entity must be reachable from the template trigger. Regular
    # automation variables are not available in triggers, trigger_variables are.
    assert "anova" in data["trigger_variables"]

    value_template = data["trigger"][0]["value_template"]
    assert "anova" in value_template
    assert "'temperature'" in value_template
    assert "target_temperature" not in value_template


@pytest.mark.parametrize(
    ("state", "attributes", "expected"),
    [
        ("heat", {"temperature": 55.0, "current_temperature": 55.5}, True),
        ("heat", {"temperature": 55.0, "current_temperature": 54.0}, False),
        ("heat", {"temperature": 55.0, "current_temperature": None}, False),
        ("heat", {"temperature": None, "current_temperature": 60.0}, False),
        ("off", {"temperature": 55.0, "current_temperature": 60.0}, False),
        ("unavailable", {}, False),
        ("unknown", {}, False),
    ],
)
async def test_reached_temperature_template(hass, state, attributes, expected):
    data = _load("anova_reached_temperature.yaml")
    value_template = data["trigger"][0]["value_template"]

    hass.states.async_set("climate.anova_cooker", state, attributes)

    result = await _render(hass, value_template, {"anova": "climate.anova_cooker"})
    assert bool(result) is expected


# --- Anova cook finished -------------------------------------------------------


async def _cook_finished_satisfied(
    hass: HomeAssistant, remaining: str, timer_state: str = "off"
) -> bool:
    data = _load("anova_cook_finished.yaml")
    hass.states.async_set("sensor.anova_remaining", remaining)
    hass.states.async_set("switch.anova_timer", timer_state)
    variables = {
        "remaining_entity": "sensor.anova_remaining",
        "timer_entity": "switch.anova_timer",
    }
    results = [
        await _render(hass, condition["value_template"], variables)
        for condition in data["condition"]
    ]
    return all(bool(result) for result in results)


def test_cook_finished_trigger_is_on_to_off():
    data = _load("anova_cook_finished.yaml")
    trigger = data["trigger"][0]
    assert trigger["platform"] == "state"
    assert trigger["from"] == "on"
    assert trigger["to"] == "off"


async def test_cook_finished_reports_on_timer_stop(hass):
    assert await _cook_finished_satisfied(hass, "0") is True


async def test_cook_finished_also_fires_on_cancellation(hass):
    # Measured on firmware 6.1.1: expiry and cancellation both show
    # `0 stopped`, so a cancellation also fires. This is documented, not a bug.
    assert await _cook_finished_satisfied(hass, "1") is True


async def test_cook_finished_does_not_report_connection_loss(hass):
    assert await _cook_finished_satisfied(hass, "0", timer_state="unavailable") is False
    assert await _cook_finished_satisfied(hass, "unavailable") is False


def test_blueprints_validate_against_home_assistant_schema():
    # Real Home Assistant validation: the blueprint metadata and the automation
    # body (with !input handled by Home Assistant's own YAML loader).
    from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
    from homeassistant.util.yaml import loader as yloader

    for name in ("anova_cook_finished.yaml", "anova_reached_temperature.yaml"):
        data = yloader.load_yaml(str(BLUEPRINT_DIR / name))
        AUTOMATION_BLUEPRINT_SCHEMA(data)
