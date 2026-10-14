# Anova Cooker dashboard

The integration ships its own Lovelace card, `custom:anova-cook-card`, and
registers it automatically. No extra frontend cards are needed.

## Recommended layout

Put the thermostat card and the cook card in a built-in **grid card** with two
columns. Both are then the same height on desktop, and the grid stacks them on
mobile.

```yaml
type: grid
columns: 2
square: false
cards:
  - type: thermostat
    entity: climate.anova_cooker
  - type: custom:anova-cook-card
```

Notes:
- A `horizontal-stack` also equalises the height but does not stack on mobile.
- A sections view does not give the two cards the same height; prefer the grid
  card above.

## The card

`custom:anova-cook-card`:
- a countdown ring: tap Start to cook, Stop to stop;
- a duration stepper (`number.anova_cooker_cook_duration`);
- a status chip (idle / cooking);
- a low-water warning, shown only while the alarm is on.

Start and Stop react immediately (optimistic), because the cooker is slow over
BLE.

Entity ids can be overridden:

```yaml
type: custom:anova-cook-card
entities:
  start: button.anova_cooker_start_cook
  stop: button.anova_cooker_stop_cook
  duration: number.anova_cooker_cook_duration
  remaining: sensor.anova_cooker_timer_remaining
  status: sensor.anova_cooker_status
  low_water: binary_sensor.anova_cooker_low_water
```

## Entities to hide in the UI

These exist but do not belong on the dashboard:

- `switch.anova_cooker_timer` (cannot start a countdown on its own)
- `sensor.anova_cooker_timer_remaining` and `sensor.anova_cooker_status`
  (used by the card)
- `button.anova_cooker_silence_alarm` (reachable from the low-water warning)
