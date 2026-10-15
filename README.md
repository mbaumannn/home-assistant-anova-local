# Anova Cooker (local) for Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mbaumannn&repository=home-assistant-anova-local)
[![Add the Anova Cooker integration to Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=anova_local)

Local Home Assistant integration for Anova sous-vide cookers with Bluetooth.
No Anova app, no cloud, no account.

It talks to the cooker in one of two ways, which you choose during setup:

- **Bluetooth (direct):** works straight away, through Home Assistant's own
  `bluetooth` component, with any connectable Bluetooth adapter or ESPHome
  Bluetooth proxy within range.
- **Wi-Fi (local server):** after a one-time setup over Bluetooth, the cooker
  joins your Wi-Fi and Home Assistant takes the place of Anova's cloud, so
  distance stops mattering.

The integration also ships a Lovelace cook card (ready to use, no extra
frontend cards needed) and can create an **Anova** dashboard with that card for
you.

Requires Home Assistant 2026.5.0 or newer.

## Installation

### As a custom repository (available now)
1. HACS → Integrations → the menu (⋮, top right) → **Custom repositories**.
2. Add `https://github.com/mbaumannn/home-assistant-anova-local`, category **Integration**.
3. Download **Anova Cooker (local)** and restart Home Assistant.

### From the HACS store (once listed)
1. In HACS, search for **Anova Cooker** and download it.
2. Restart Home Assistant.

## Setting up the cooker
Turn the cooker on. Home Assistant discovers it within a minute; select
**Configure**. Choose how Home Assistant should talk to it: **Wi-Fi (local
server)**, which is offered first, or **Bluetooth (direct)**.

You can also add it yourself: Settings → Devices & services → **Add
integration** → Anova Cooker. The cookers Home Assistant has seen over
Bluetooth are listed to pick from; type the address printed under the cooker
only if yours is not in the list.

For Wi-Fi you then enter your network name (2.4 GHz only) and password.
Home Assistant writes a fresh security key, its own address and the network to
the cooker over Bluetooth, and the cooker joins your Wi-Fi about a minute later.
Close the Anova app first: the cooker accepts one Bluetooth connection at a
time.

Both setup forms have a checkbox that creates the **Anova** dashboard with the
cook card. It is ticked by default and never touches your other dashboards.

### Removing it
Settings → Devices & services → Anova Cooker → ⋮ → **Delete**, then HACS →
Anova Cooker (local) → ⋮ → **Remove**, and restart. Deleting the last cooker
also removes the card's dashboard resource and the **Anova** dashboard the
integration created, unless you changed that dashboard; then it stays, and you
can delete it under Settings → Dashboards. Your other dashboards are never
touched; one that still uses the card shows an error until you remove the card
from it. Uninstalling through HACS without deleting the cooker first leaves
both behind.

A cooker you moved to Wi-Fi keeps its Wi-Fi and server settings after the
integration is removed; only the Anova app resets them.

## Entities
- `climate.anova_cooker`: off/heat, target temperature, current water temperature
- `number.anova_cooker_cook_duration`: stored duration preset in minutes, stays put during a cook
- `switch.anova_cooker_timer`: start and stop the timer
- `sensor.anova_cooker_status`: idle, cooking, low water
- `sensor.anova_cooker_timer_remaining`: live remaining minutes
- `binary_sensor.anova_cooker_low_water`: on while the cooker reports low water
- `button.anova_cooker_start_cook`: start heating and the timer in one tap
- `button.anova_cooker_stop_cook`: stop heating and the timer
- `button.anova_cooker_silence_alarm`: turn the cooker's speaker off to silence an alarm

Entity IDs depend on the device name; the list above shows the defaults. The
timer starts on `start time` and runs on the wall clock, so warm-up time is
included in the countdown.

## Cook card
`custom:anova-cook-card` is registered automatically. It shows Home Assistant's
own thermostat ring for the target temperature, a duration stepper, the live
countdown and one-tap Start and Stop, and it warns when the water is low. Add
it to any dashboard, or use the **Anova** dashboard created during setup.

## Connection
- **Bluetooth:** turn the cooker on and the entities come online; turn it off
  and they become `unavailable`. The cooker supports one Bluetooth connection
  at a time, so keep the Anova app closed while Home Assistant holds the link.
- **Wi-Fi:** the cooker dials in to Home Assistant on its own and stays
  connected as long as it is powered and on your network. Bluetooth is only
  needed for the one-time setup.

Bluetooth range matters. Keep the adapter, or a Bluetooth proxy, close to the
cooker. An ESPHome Bluetooth proxy in the kitchen is recommended when the
server is far away.

## Notifications
Two automation blueprints ship with this repository. Import them once via
their links (Settings → Automations & scenes → Blueprints → **Import Blueprint**):

- [Cook timer stopped](https://my.home-assistant.io/redirect/blueprint_import?blueprint_url=https://raw.githubusercontent.com/mbaumannn/home-assistant-anova-local/main/blueprints/automation/anova_local/anova_cook_finished.yaml): notifies when the timer runs out. On firmware 6.1.1 the cooker reports the same state for a finished and a cancelled timer, so the blueprint fires on either; a lost connection does not fire it.
- [Water reached temperature](https://my.home-assistant.io/redirect/blueprint_import?blueprint_url=https://raw.githubusercontent.com/mbaumannn/home-assistant-anova-local/main/blueprints/automation/anova_local/anova_reached_temperature.yaml): notifies when the water reaches the target temperature, only during an active cook and while the cooker is connected.

## Security and privacy
- No cloud, no account, no telemetry. The integration talks to the cooker on
  your network and nothing else.
- The optional Wi-Fi transport listens on your Home Assistant host (default
  port 8080, configurable during setup). During setup Home Assistant gives the
  cooker a fresh random key over Bluetooth; a cooker that dials in must report
  that key, or it is dropped. The connection is plain TCP on your own network,
  as the cooker's firmware speaks it, so treat it like any other local IoT
  device.
- Another device connecting to that port cannot push the cooker off: the
  cooker's link is only replaced by a connection that passed the key check.
- The Wi-Fi password is used once during setup. It is never stored, and never
  written to the log, not even at debug level.

## Support
Problems and questions: [open an issue](https://github.com/mbaumannn/home-assistant-anova-local/issues).
Please include your Home Assistant version, the integration version, which
connection you use (Bluetooth or Wi-Fi) and the debug log around the problem
(Settings → Devices & services → Anova Cooker → ⋮ → **Enable debug logging**).
Reports from other cookers and firmware versions are welcome.

## Tested with
Anova Precision Cooker (2018, Bluetooth and Wi-Fi, EU), firmware ver 6.1.1.
