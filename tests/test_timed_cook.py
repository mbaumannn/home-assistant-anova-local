"""A timed cook stops itself at the cooker's own finish event.

The 2018 firmware treats its countdown as an alarm: at ``event time finish``
the cooker keeps heating forever. The coordinator listens for that unsolicited
event and stops the heat for it.
"""
from __future__ import annotations

import logging

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


# --- the poll-based fallback: Bluetooth sends no finish event -------------


class FakeClock:
    """A monotonic clock the tests advance by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _state(status: AnovaStatus, minutes: int, running: bool) -> AnovaState:
    return AnovaState(
        status=status,
        current_temp=41.5,
        target_temp=57.0,
        timer_minutes=minutes,
        timer_running=running,
        unit=AnovaUnit.CELSIUS,
    )


class ScriptedClient(FakeClient):
    """Answers polls with a script; an Exception item models a failed poll."""

    def __init__(self, script: list) -> None:
        super().__init__(running_state())
        self._script = list(script)

    async def update_state(self) -> AnovaState:
        self.updates += 1
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _polling_coordinator(hass, script: list, clock: FakeClock):
    client = ScriptedClient(script)
    coordinator = coordinator_for(hass, client)
    coordinator._now = lambda: clock.now
    return coordinator, client


async def test_a_countdown_that_runs_out_stops_the_heat_over_a_poll(hass) -> None:
    """Bluetooth sends no finish event, so the polled countdown end stops it."""
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [_state(AnovaStatus.RUNNING, 1, True), _state(AnovaStatus.RUNNING, 0, False)],
        clock,
    )

    await coordinator.async_refresh()   # the countdown is running, a minute left
    clock.advance(60)
    await coordinator.async_refresh()   # the next poll: the countdown is gone
    await hass.async_block_till_done()

    assert client.stop_calls == 1


async def test_a_finish_during_a_failed_poll_is_caught_when_the_link_returns(hass) -> None:
    """A finish during a Bluetooth gap is not lost: the last good state stands."""
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [
            _state(AnovaStatus.RUNNING, 1, True),
            OSError("the Bluetooth link is down"),
            _state(AnovaStatus.RUNNING, 0, False),
        ],
        clock,
    )

    await coordinator.async_refresh()   # running
    clock.advance(30)
    await coordinator.async_refresh()   # the poll fails; the last good state stands
    clock.advance(30)
    await coordinator.async_refresh()   # link back: the countdown is gone
    await hass.async_block_till_done()

    assert client.stop_calls == 1


async def test_a_countdown_cancelled_on_the_device_leaves_the_heat_on(hass) -> None:
    """A cancel mid-cook is not a finish: the heat must stay on."""
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [_state(AnovaStatus.RUNNING, 30, True), _state(AnovaStatus.RUNNING, 0, False)],
        clock,
    )

    await coordinator.async_refresh()   # thirty minutes on the clock
    clock.advance(60)
    await coordinator.async_refresh()   # cancelled a minute in
    await hass.async_block_till_done()

    assert client.stop_calls == 0


async def test_stopping_the_timer_from_home_assistant_leaves_the_heat_on(hass) -> None:
    """The timer switch is a cancel, even at the moment the countdown would end."""
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [_state(AnovaStatus.RUNNING, 1, True), _state(AnovaStatus.RUNNING, 0, False)],
        clock,
    )

    await coordinator.async_refresh()    # one minute left
    coordinator.note_timer_cancelled()   # the user turns the timer switch off
    clock.advance(60)                    # right at the natural finish moment
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert client.stop_calls == 0


async def test_a_countdown_gone_with_the_heat_already_off_sends_no_stop(hass) -> None:
    """A cook that already ended by hand is not touched a second time."""
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [_state(AnovaStatus.RUNNING, 1, True), _state(AnovaStatus.STOPPED, 0, False)],
        clock,
    )

    await coordinator.async_refresh()
    clock.advance(60)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert client.stop_calls == 0


async def test_the_event_and_a_poll_seeing_the_same_finish_stop_once(hass, caplog) -> None:
    """The Wi-Fi event and a poll race to one stop and one log line."""
    caplog.set_level(logging.INFO, logger="custom_components.anova_local")
    clock = FakeClock()
    coordinator, client = _polling_coordinator(
        hass,
        [_state(AnovaStatus.RUNNING, 1, True), _state(AnovaStatus.RUNNING, 0, False)],
        clock,
    )

    await coordinator.async_refresh()                            # countdown running
    coordinator.async_on_cooker_event("event ble time finish")   # the Wi-Fi fast path
    clock.advance(60)
    await coordinator.async_refresh()                            # the same finish, polled
    await hass.async_block_till_done()

    assert client.stop_calls == 1
    assert sum("countdown finished" in message for message in caplog.messages) == 1
