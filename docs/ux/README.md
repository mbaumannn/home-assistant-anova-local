# Anova Cooker dashboard

The integration ships its own Lovelace card, `custom:anova-cook-card`, and
registers it automatically. No extra frontend cards are needed. During setup it
can also create an **Anova** dashboard (`/anova-cook`) with the card on it.

## Recommended layout

To build your own view, put the thermostat card and the cook card in a built-in
**grid card** with two columns. Both are then the same height on desktop, and
the grid stacks them on mobile.

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

`custom:anova-cook-card` shows:
- Home Assistant's own thermostat ring for the target temperature, orange while heating;
- a duration stepper (`number.anova_cooker_cook_duration`), which becomes the live countdown during a cook;
- one-tap Start and Stop;
- a low-water warning, shown only while the alarm is on.

Start and Stop react immediately, because the cooker is slow to confirm.

Options and entity overrides:

```yaml
type: custom:anova-cook-card
step: 5    # step size in minutes
entities:
  start: button.anova_cooker_start_cook
  stop: button.anova_cooker_stop_cook
  duration: number.anova_cooker_cook_duration
  remaining: sensor.anova_cooker_timer_remaining
  timer: switch.anova_cooker_timer
  status: sensor.anova_cooker_status
  low_water: binary_sensor.anova_cooker_low_water
  climate: climate.anova_cooker
```

## Entities to hide in the UI

These exist but do not belong on a dashboard:

- `switch.anova_cooker_timer` (cannot start a countdown on its own)
- `sensor.anova_cooker_timer_remaining` and `sensor.anova_cooker_status`
  (used by the card)
- `button.anova_cooker_silence_alarm` (reachable from the low-water warning)

## Previewing the card

`python3 tools/preview_card.py out.html` renders the real card file in a plain
page, without a Home Assistant instance.
