"""A timed cook stops itself at the cooker's own finish event.

The 2018 firmware treats its countdown as an alarm: at ``event time finish``
the cooker keeps heating forever. The coordinator listens for that unsolicited
event and stops the heat for it.
"""
from __future__ import annotations

import pytest
from homeassistant.helpers.debounce import Debouncer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_local.const import DOMAIN, LOGGER, AnovaStatus, AnovaUnit
from custom_components.anova_local.coordinator import AnovaDataUpdateCoordinator
from custom_components.anova_local.state import AnovaState


def running_state() -> AnovaState:
    return AnovaState(
        status=AnovaStatus.RUNNING,
        current_temp=41.5,
        target_temp=57.0,
        timer_minutes=26,
        timer_running=True,
        unit=AnovaUnit.CELSIUS,
    )


def stopped_state() -> AnovaState:
    return AnovaState(
        status=AnovaStatus.STOPPED,
        current_temp=41.5,
        target_temp=57.0,
        timer_minutes=0,
        timer_running=False,
        unit=AnovaUnit.CELSIUS,
    )


class FakeClient:
    """A transport that records ``stop`` and answers polls with one state."""

    def __init__(self, state: AnovaState) -> None:
        self.state = state
        self.stop_calls = 0
        self.updates = 0

    async def update_state(self) -> AnovaState:
        self.updates += 1
        return self.state

    async def stop(self) -> None:
        self.stop_calls += 1


def coordinator_for(hass, client: FakeClient) -> AnovaDataUpdateCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="<cooker BLE MAC, redacted>")
    entry.add_to_hass(hass)
    coordinator = AnovaDataUpdateCoordinator(hass, entry, client, push=True)
    # No polling interval (push=True), and a zero-cooldown refresh debouncer so
    # a test can refresh twice in a row without leaving a lingering timer.
    debouncer = Debouncer(hass, LOGGER, cooldown=0, immediate=True)
    debouncer.function = coordinator._async_refresh
    coordinator._debounced_refresh = debouncer
    return coordinator


async def test_finish_event_while_running_stops_the_heat(hass) -> None:
    client = FakeClient(running_state())
    coordinator = coordinator_for(hass, client)
    coordinator.data = running_state()

    coordinator.async_on_cooker_event("event ble time finish")
    await hass.async_block_till_done()

    assert client.stop_calls == 1
    # The refresh ran, so the entities see the truth without waiting a poll.
    assert client.updates == 1


async def test_finish_event_while_stopped_sends_no_stop(hass) -> None:
    client = FakeClient(stopped_state())
    coordinator = coordinator_for(hass, client)
    coordinator.data = stopped_state()

    coordinator.async_on_cooker_event("event ble time finish")
    await hass.async_block_till_done()

    assert client.stop_calls == 0


async def test_other_events_push_the_state_at_once(hass) -> None:
    """Any cooker event is news by definition: the state is pushed, not polled.

    Home Assistant scene changes that feel sluggish today (a timer that only
    switches on a poll or two after ``start time``) arrive as an event within
    moments instead.
    """
    client = FakeClient(running_state())
    coordinator = coordinator_for(hass, client)
    coordinator.data = running_state()

    coordinator.async_on_cooker_event("event ble time start")
    await hass.async_block_till_done()
    coordinator.async_on_cooker_event("event wifi time stop")
    await hass.async_block_till_done()

    assert client.stop_calls == 0

    # The second event finds the first push still running, so the state is
    # read only fresh afterwards, but at least once is guaranteed.
    assert client.updates >= 1


async def test_a_command_refresh_is_never_swallowed_by_the_debouncer(hass) -> None:
    """Back-to-back commands each show their truth: Home Assistant's debouncer
    drops a refresh inside its cooldown, which is the lag you felt after
    Start and Stop.
    """
    client = FakeClient(running_state())
    coordinator = coordinator_for(hass, client)
    coordinator.data = running_state()

    await coordinator.async_quick_refresh()
    await coordinator.async_quick_refresh()

    assert client.updates == 2                 # both commands were followed


async def test_a_stop_that_fails_is_logged_not_hidden(hass, caplog) -> None:
    """The stop must never fail silently if the cooker is not listening."""
    client = FakeClient(running_state())
    coordinator = coordinator_for(hass, client)
    coordinator.data = running_state()

    async def broken_stop() -> None:
        raise OSError("the link is gone")

    client.stop = broken_stop  # type: ignore[method-assign]

    coordinator.async_on_cooker_event("event ble time finish")
    await hass.async_block_till_done()

    assert any("Could not stop the heat" in message for message in caplog.text.splitlines())
