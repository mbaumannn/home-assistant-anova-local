# Anova Cooker (local) for Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mbaumannn&repository=home-assistant-anova-local)
[![Add the Anova Cooker integration to Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=anova_local)

Local Home Assistant integration for Bluetooth Anova sous-vide cookers.
No app, no cloud, no account. It uses Home Assistant's own `bluetooth`
component, so it works with any connectable Bluetooth adapter or ESPHome
Bluetooth proxy.

Requires Home Assistant 2026.5.0 or newer.

## Installation

### As a custom repository (available now)
1. HACS → Integrations → the menu (⋮, top right) → **Custom repositories**.
2. Add `https://github.com/mbaumannn/home-assistant-anova-local`, category **Integration**.
3. Download **Anova Cooker (local)** and restart Home Assistant.

### From the HACS store (once listed)
1. In HACS, search for **Anova Cooker** and download it.
2. Restart Home Assistant.

### After installation
Turn the cooker on. Home Assistant discovers it within a minute — select
**Configure** — or add it manually with its Bluetooth address.

### Removing it
Settings → Devices & services → Anova Cooker → ⋮ → **Delete**, then HACS →
Anova Cooker (local) → ⋮ → **Remove**, and restart. Deleting the last cooker
also removes the card's dashboard resource and the **Anova** dashboard the
integration created — unless you changed that dashboard, in which case it
stays and you can delete it under Settings → Dashboards. Your other dashboards
are never touched; one that still uses the card shows an error until you remove
the card from it. Uninstalling through HACS without deleting the cooker first
leaves both behind. A cooker you moved to
Wi-Fi keeps its Wi-Fi settings — see **Undo**.

## Entities
- `climate.anova_cooker`: off/heat, target temperature, current water temperature
- `number.anova_cooker_cook_duration`: stored duration preset in minutes, stays put during a cook
- `switch.anova_cooker_timer`: start and stop the timer
- `sensor.anova_cooker_status`: idle, cooking, low water
- `sensor.anova_cooker_timer_remaining`: live remaining minutes
- `button.anova_cooker_start_cook`: start heating and the timer in one tap

Entity IDs depend on the device name; the list above shows the defaults.
The timer starts on `start time` and runs on the wall clock, so warm-up time is
included in the countdown.

## Auto-connect
Turn the cooker on and the entities come online. Turn it off and they become
`unavailable`. The cooker supports a single BLE connection at a time, so keep
the Anova app closed.

## Notifications
Two automation blueprints ship with this repository. Import them once via
their links (Settings → Automations & scenes → Blueprints → **Import Blueprint**):

- [Cook timer stopped](https://my.home-assistant.io/redirect/blueprint_import?blueprint_url=https://raw.githubusercontent.com/mbaumannn/home-assistant-anova-local/main/blueprints/automation/anova_local/anova_cook_finished.yaml) — notifies when the timer runs out. On firmware 6.1.1 the cooker reports the same state for a finished and a cancelled timer, so the blueprint fires on either; a lost connection does not fire it.
- [Water reached temperature](https://my.home-assistant.io/redirect/blueprint_import?blueprint_url=https://raw.githubusercontent.com/mbaumannn/home-assistant-anova-local/main/blueprints/automation/anova_local/anova_reached_temperature.yaml) — notifies when the water reaches the target temperature, only during an active cook and while the cooker is connected.

## Range
Bluetooth range matters. Keep the adapter, or a Bluetooth proxy, close to the
cooker. An ESPHome Bluetooth proxy in the kitchen is recommended when the
server is far away.

## Security and privacy
- No cloud, no account, no telemetry. The integration talks to the cooker on
  your network and nothing else.
- The optional Wi-Fi transport listens on your Home Assistant host (default
  port 8080, configurable during setup). During setup Home Assistant gives the
  cooker a fresh random key over Bluetooth; a cooker that dials in must report
  that key, or it is dropped. The connection is plain TCP on your own network,
  as the cooker's firmware speaks it — treat it like any other local IoT device.
- Another device connecting to that port cannot push the cooker off: the
  cooker's link is only replaced by a connection that passed the key check.
- The Wi-Fi password is used once during setup. It is never stored, and never
  written to the log, not even at debug level.

## Support
Problems and questions: [open an issue](https://github.com/mbaumannn/home-assistant-anova-local/issues).
Attach the Diagnostics download from the integration page
(Settings → Devices & services → Anova Cooker → ⋮ → Download diagnostics).
Tested with firmware ver 6.1.1 — reports from other cookers and firmware
versions are welcome.

## Tested with
Anova Precision Cooker (2018, Bluetooth and WiFi, EU), firmware ver 6.1.1.
