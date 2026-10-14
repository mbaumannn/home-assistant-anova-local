# Anova Bluetooth dashboard (B1)

A minimal dashboard block for the Anova Bluetooth integration: a temperature
dial (the standard thermostat card) plus one cook card with a countdown ring.

Only what you use while cooking is shown, and the low-water warning appears only
while it is actually relevant.

## Files

- `b1-cook-card.yaml` — the cook card (paste into a dashboard).
- `anova-cook-card-mockups.html` — a visual mockup of the three states
  (idle, cooking, low water). Open it in a browser.

## Required HACS frontend cards

- `mushroom` — for the duration stepper.
- `button-card` — for the countdown ring.

## How it behaves

- **Ring**: tap to start a cook (writes the duration, starts heating and the
  countdown). Hold to stop.
- **Duration stepper**: only visible while idle.
- **Low-water warning**: only visible while the alarm is on; tap it to silence
  the beeper. Starting is refused while the alarm is on.

## Install

1. Install the HACS cards above and reload the frontend.
2. Edit the dashboard, add a card, choose **Manual** and paste the contents of
   `b1-cook-card.yaml`. Or paste it into the raw dashboard config.

## Entities to hide in the UI

These exist but should not be on the dashboard:

- `switch.anova_bluetooth_timer` — cannot start a countdown on its own on this
  firmware.
- `sensor.anova_bluetooth_timer_remaining` and `sensor.anova_bluetooth_status` —
  only used by the card, not shown as tiles.
- `button.anova_bluetooth_silence_alarm` — only reachable from the warning.
- `button.anova_bluetooth_start_cook` — the ring replaces it.

Hide them per entity (Settings > Entities > your entity > Hide) or skip them on
the dashboard.

## Entities the card uses

| Purpose | Entity |
|---|---|
| Countdown | `sensor.anova_bluetooth_timer_remaining` |
| Duration | `number.anova_bluetooth_cook_duration` |
| Start | `button.anova_bluetooth_start_cook` |
| Stop | `climate.anova_bluetooth` (hvac_mode off) |
| Low water | `binary_sensor.anova_bluetooth_low_water` |
| Silence | `button.anova_bluetooth_silence_alarm` |
