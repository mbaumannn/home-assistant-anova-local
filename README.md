# Anova Bluetooth for Home Assistant

Local Home Assistant integration for Bluetooth Anova sous-vide cookers.
No app, no cloud, no account. It uses Home Assistant's own `bluetooth`
component, so it works with any connectable Bluetooth adapter or ESPHome
Bluetooth proxy.

Requires Home Assistant 2026.5.0 or newer.

## Installation (HACS)
1. HACS > Integrations > menu > Custom repositories, add this repository with category Integration.
2. Install "Anova Bluetooth" and restart Home Assistant.
3. Turn the cooker on. Home Assistant discovers it automatically, then select Configure, or add it manually with its MAC address.

## Entities
- `climate.anova_bluetooth`: off/heat, target temperature, current water temperature
- `number.anova_bluetooth_cook_duration`: stored duration preset in minutes, stays put during a cook
- `switch.anova_bluetooth_timer`: start and stop the timer
- `sensor.anova_bluetooth_status`: idle, cooking, low water
- `sensor.anova_bluetooth_timer_remaining`: live remaining minutes
- `button.anova_bluetooth_start_cook`: start heating and the timer in one tap

Entity IDs depend on the device name; the list above shows the defaults.
The timer starts on `start time` and runs on the wall clock, so warm-up time is
included in the countdown.

## Auto-connect
Turn the cooker on and the entities come online. Turn it off and they become
`unavailable`. The cooker supports a single BLE connection at a time, so keep
the Anova app closed.

## Notifications
Import the blueprints from Settings > Automations > Blueprints:
- `anova_cook_finished.yaml`: notifies when the timer runs out, not when the cook is stopped manually.
- `anova_reached_temperature.yaml`: notifies when the water reaches the target temperature, only during an active cook and when the device is available.

## Range
Bluetooth range matters. Keep the adapter, or a Bluetooth proxy, close to the
cooker. An ESPHome Bluetooth proxy in the kitchen is recommended when the
server is far away.

## Tested with
Anova Precision Cooker (2018, Bluetooth and WiFi, EU), firmware ver 6.1.1.
