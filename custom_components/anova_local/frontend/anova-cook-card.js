/**
 * Anova Cook Card
 *
 * One card for the whole cooker, so nothing has to line up with a second card.
 * It reuses Home Assistant's own `ha-control-circular-slider` (the dial the
 * thermostat card uses), so the ring looks and behaves like Home Assistant
 * already looks and behaves.
 *
 * The ring is the target temperature, always: that is what you set before a cook
 * and watch while it runs. The duration is set with the -/+ row while the cooker
 * is off, and the countdown is never hidden:
 *
 *   Off      the ring sets the target temperature; -/+ sets the duration.
 *   Heating  the ring keeps setting the temperature; the water temperature sits
 *   Cooking  under it and the remaining time is in the top right, with a progress
 *            bar underneath, so it stays visible while the ring shows temperature.
 *   Low water the ring turns to the warning colour and Start is refused.
 *
 * If the climate entity is missing (a partial entity set), the ring falls back to
 * being the duration dial.
 *
 * Registered automatically by the integration.
 *
 * Config:
 *   type: custom:anova-cook-card
 *   max: 240                 # duration dial range in minutes (default 240)
 *   step: 5                  # drag step in minutes (default 5)
 *   entities:                # optional overrides
 *     start / stop / duration / remaining / status / low_water / climate
 */

const DEFAULTS = {
  start: "button.anova_cooker_start_cook",
  stop: "button.anova_cooker_stop_cook",
  duration: "number.anova_cooker_cook_duration",
  remaining: "sensor.anova_cooker_timer_remaining",
  status: "sensor.anova_cooker_status",
  low_water: "binary_sensor.anova_cooker_low_water",
  climate: "climate.anova_cooker",
};

// How far the temperature ring reaches around the target, like Home Assistant's
// own climate card, so dragging stays precise.
const TEMP_RANGE = 10;

class AnovaCookCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = null; // optimistic: "start" while the cooker reacts
    this._timer = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._build();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 10;
  }

  _id(kind) {
    return (this._config?.entities && this._config.entities[kind]) || DEFAULTS[kind];
  }

  _state(id) {
    const s = this._hass && this._hass.states[id];
    return s ? s.state : undefined;
  }

  _attrs(id) {
    const s = this._hass && this._hass.states[id];
    return (s && s.attributes) || {};
  }

  _temperatureRange(target, minTemp, maxTemp, unit) {
    // Keep the range while it still contains the target: re-centring on every
    // render would snap the knob back to the middle after every drag. A target
    // that arrives from somewhere else (an automation, the cooker itself, or a
    // change of unit) lands outside it, and then the dial re-centres on purpose.
    const current = this._tempRange;
    if (
      current &&
      this._tempRangeUnit === unit &&
      target >= current.min &&
      target <= current.max
    ) {
      return current;
    }
    const range = {
      min: Math.max(minTemp, target - TEMP_RANGE),
      max: Math.min(maxTemp, target + TEMP_RANGE),
    };
    this._tempRange = range;
    this._tempRangeUnit = unit;
    return range;
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card { height: 100%; box-sizing: border-box; }
        .wrap { height: 100%; box-sizing: border-box;
                display: flex; flex-direction: column; align-items: center;
                gap: 10px; padding: 14px 16px 16px; }
        .head { display: flex; align-items: baseline; width: 100%; gap: 8px; }
        .state { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .warn { color: var(--warning-color, #e08a00); }
        .dial { position: relative; width: 100%; max-width: 100%; }
        ha-control-circular-slider { width: 100% !important; display: block; }
        .center { position: absolute; inset: 0; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; gap: 6px;
                  padding-bottom: 15%; pointer-events: none; }
        .big { font-size: 40px; font-weight: 300; line-height: 1;
               font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .big small { font-size: 19px; font-weight: 400; margin-left: 2px;
                     vertical-align: 12px; color: var(--primary-text-color); }
        .cur { display: flex; align-items: center; gap: 5px; font-size: 15px;
               color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .cur ha-icon { --mdc-icon-size: 17px; }
        .cap { font-size: 12px; color: var(--secondary-text-color); }
        .dot { position: absolute; width: 9px; height: 9px; border-radius: 50%;
               background: var(--secondary-text-color); transform: translate(-50%, -50%);
               pointer-events: none; }
        .bar { width: 100%; height: 4px; border-radius: 2px;
               background: var(--divider-color); overflow: hidden; }
        .bar .fill { height: 100%; border-radius: 2px; background: var(--primary-color);
                     transition: width .3s ease; }
        .dur { display: flex; align-items: center; gap: 14px; }
        .step { width: 44px; height: 44px; border-radius: 22px;
                border: 1px solid var(--divider-color);
                background: var(--card-background-color); color: var(--primary-text-color);
                font-size: 22px; line-height: 1; cursor: pointer; }
        .val { min-width: 84px; text-align: center; font-size: 22px; font-weight: 500;
               font-variant-numeric: tabular-nums; cursor: pointer; }
        .val-input { width: 84px; min-width: 84px; text-align: center; font-size: 22px;
                     font-weight: 500; font-variant-numeric: tabular-nums;
                     background: transparent; color: var(--primary-text-color);
                     border: none; border-bottom: 2px solid var(--primary-color);
                     outline: none; padding: 0 0 2px; }
        .btns { display: flex; gap: 10px; width: 100%; }
        button.act { flex: 1; height: 44px; border-radius: 22px; border: none; cursor: pointer;
                     font-size: 15px; font-weight: 600; }
        button.act:disabled { opacity: .4; cursor: default; }
        .start { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .stop { background: transparent; color: var(--primary-text-color);
                border: 1px solid var(--divider-color) !important; }
        [hidden] { display: none !important; }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="head">
            <span class="state"></span>
          </div>
          <div class="dial">
            <ha-control-circular-slider mode="start"></ha-control-circular-slider>
            <span class="dot" hidden></span>
            <div class="center">
              <div class="big"></div>
              <div class="cur" hidden></div>
              <div class="cap" hidden></div>
            </div>
          </div>
          <div class="bar" hidden><div class="fill"></div></div>
          <div class="dur">
            <button class="step minus" aria-label="minder">−</button>
            <span class="val" role="button" tabindex="0"
                  title="Tap to type a number of minutes"></span>
            <input class="val-input" type="number" inputmode="numeric" min="0" max="6000"
                   step="1" hidden aria-label="minutes" />
            <button class="step plus" aria-label="meer">＋</button>
          </div>
          <div class="btns">
            <button class="act start">Start cook</button>
            <button class="act stop">Stop</button>
          </div>
        </div>
      </ha-card>
    `;
    this._slider = this.shadowRoot.querySelector("ha-control-circular-slider");
    this._slider.addEventListener("value-changed", (ev) =>
      this._onSliderChanged(ev)
    );
    // While a finger is on the dial, a state update must not move it: the cooker
    // answers slowly and the next render would fight the drag.
    const endDrag = () => {
      this._dragging = false;
    };
    this._slider.addEventListener("pointerdown", () => {
      this._dragging = true;
    });
    this._slider.addEventListener("pointerup", endDrag);
    this._slider.addEventListener("pointercancel", endDrag);

    // The duration: tap the number to type one, or hold -/+ for the same field.
    const value = this.shadowRoot.querySelector(".val");
    value.onclick = () => this._openValueInput();
    value.onkeydown = (ev) => {
      if (ev.key === "Enter" || ev.key === " ") this._openValueInput();
    };
    const input = this.shadowRoot.querySelector(".val-input");
    input.onkeydown = (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        this._commitValueInput();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        this._closeValueInput();
      }
    };
    input.onblur = () => this._commitValueInput();

    const steps = [[".minus", -1], [".plus", 1]];
    for (const [selector, direction] of steps) {
      const button = this.shadowRoot.querySelector(selector);
      if (selector === ".minus") this._minus = button;
      else this._plus = button;
      let hold = null;
      button.onpointerdown = () => {
        hold = setTimeout(() => {
          this._held = true;
          this._openValueInput();
        }, 500);
      };
      button.onpointerup = button.onpointerleave = () => clearTimeout(hold);
      button.onclick = () => {
        if (this._held) {
          this._held = false; // the hold already opened the field
          return;
        }
        this._stepBy(direction * this._stepSize());
      };
      button.oncontextmenu = (ev) => {
        ev.preventDefault(); // long press on a phone, right click on a desktop
        this._openValueInput();
      };
    }

    this.shadowRoot.querySelector(".start").onclick = () => this._start();
    this.shadowRoot.querySelector(".stop").onclick = () => this._stop();
  }

  _openValueInput() {
    if (this._cooking) return;                    // the preset is fixed mid-cook
    const input = this.shadowRoot.querySelector(".val-input");
    const value = this.shadowRoot.querySelector(".val");
    if (!input || !value || !input.hidden) return;
    const minutes = Number(this._state(this._id("duration"))) || 0;
    input.value = String(minutes);
    input.hidden = false;
    value.hidden = true;
    input.focus();
    if (input.select) input.select();
  }

  _commitValueInput() {
    const input = this.shadowRoot.querySelector(".val-input");
    const value = this.shadowRoot.querySelector(".val");
    if (!input || input.hidden) return;
    const typed = Number(input.value);
    input.hidden = true;
    value.hidden = false;
    if (Number.isFinite(typed)) {
      this._setDuration(Math.max(0, Math.min(6000, Math.round(typed))));
    }
  }

  _closeValueInput() {
    const input = this.shadowRoot.querySelector(".val-input");
    const value = this.shadowRoot.querySelector(".val");
    if (!input || input.hidden) return;
    input.hidden = true;
    value.hidden = false;
  }

  _stepSize() {
    return Number(this._config?.step) || 5;
  }

  _onSliderChanged(ev) {
    if (this._suppressSlider) return;
    const value = Number(ev.detail?.value);
    if (!Number.isFinite(value)) return;
    if (this._ringIsTemperature) {
      this._setTemperature(value);
    } else {
      this._setDuration(Math.max(0, Math.round(value)));
    }
  }

  _setDuration(value) {
    this._hass.callService("number", "set_value", {
      entity_id: this._id("duration"),
      value,
    });
  }

  _setTemperature(value) {
    this._hass.callService("climate", "set_temperature", {
      entity_id: this._id("climate"),
      temperature: Math.round(value * 10) / 10,
    });
  }

  _stepBy(delta) {
    const dur = Number(this._state(this._id("duration"))) || 0;
    const next = Math.max(0, Math.min(6000, dur + delta));
    this._setDuration(next);
  }

  _start() {
    if (this._state(this._id("low_water")) === "on") return;
    // Optimistic: show the cook running immediately; the cooker is slow.
    this._pending = "start";
    this._render();
    this._hass.callService("button", "press", { entity_id: this._id("start") });
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._pending = null;
      this._render();
    }, 12000);
  }

  _stop() {
    clearTimeout(this._timer);
    this._pending = null;
    this._hass.callService("button", "press", { entity_id: this._id("stop") });
    this._render();
  }

  _render() {
    if (!this._hass) return;
    const root = this.shadowRoot;
    const status = this._state(this._id("status"));
    const low = this._state(this._id("low_water")) === "on";
    const remaining = Number(this._state(this._id("remaining"))) || 0;
    const duration = Number(this._state(this._id("duration"))) || 0;
    const climate = this._attrs(this._id("climate"));
    const target = Number(climate.temperature);
    const current = Number(climate.current_temperature);
    const hasTarget = Number.isFinite(target);
    const unit = climate.temperature_unit === "°F" ? "°F" : "°C";
    const minTemp = Number.isFinite(Number(climate.min_temp)) ? Number(climate.min_temp) : 5;
    const maxTemp = Number.isFinite(Number(climate.max_temp)) ? Number(climate.max_temp) : 99.9;

    if (this._pending === "start" && status === "cooking") {
      clearTimeout(this._timer);
      this._pending = null;
    }
    const cooking = this._pending === "start" || status === "cooking";
    this._cooking = cooking;
    // The ring is the target temperature whenever we know it: setting it before a
    // cook is the whole point. Without a climate entity it falls back to the
    // duration dial, so a partial entity set still works.
    const ringIsTemperature = hasTarget;
    this._ringIsTemperature = ringIsTemperature;   // the drag route reads this back
    this._suppressSlider = true;
    if (!this._dragging) {                         // never fight a finger on the dial
      if (ringIsTemperature) {
        const range = this._temperatureRange(target, minTemp, maxTemp, unit);
        this._slider.min = range.min;
        this._slider.max = range.max;
        this._slider.step = 0.1;
        this._slider.value = target;
      } else {
        this._slider.min = 0;
        this._slider.max = cooking ? Math.max(duration, 1) : Number(this._config?.max) || 240;
        this._slider.step = this._stepSize();
        this._slider.value = cooking ? Math.min(remaining, this._slider.max) : duration;
      }
    }
    this._slider.disabled = false; // drag to change the temperature mid-cook too
    this._slider.style.setProperty(
      "--control-circular-slider-color",
      low ? "var(--warning-color, #e08a00)" : "var(--primary-color)"
    );
    this._suppressSlider = false;

    // The centre, like the card it replaces: the target large with a small unit,
    // and the water temperature underneath with a thermometer.
    const big = root.querySelector(".big");
    const cur = root.querySelector(".cur");
    const cap = root.querySelector(".cap");
    const hasCurrent = Number.isFinite(current);
    if (ringIsTemperature) {
      big.innerHTML = `${target.toFixed(1)}<small>${unit}</small>`;
      cur.hidden = !hasCurrent;
      cur.innerHTML = hasCurrent
        ? '<ha-icon icon="mdi:thermometer"></ha-icon>' +
          `<span>${current.toFixed(1)} ${unit}</span>`
        : "";
      cap.hidden = true;
    } else {
      big.innerHTML = `${duration}<small> min</small>`;
      cur.hidden = true;
      cap.hidden = false;
      cap.textContent = "duration";
    }

    // The water temperature as a marker on the ring, on the knob's own scale.
    const dot = root.querySelector(".dot");
    if (ringIsTemperature && hasCurrent) {
      const marker = this._markerPosition(current, this._slider.min, this._slider.max);
      dot.style.left = marker.left;
      dot.style.top = marker.top;
      dot.hidden = false;
    } else {
      dot.hidden = true;
    }

    // The state in words.
    let stateText = "Off";
    if (low) {
      stateText = "Low water";
    } else if (cooking) {
      const reached = hasCurrent && hasTarget && current >= target - 0.5;
      stateText = reached ? "Cooking" : "Heating";
    }
    const stateEl = root.querySelector(".state");
    stateEl.textContent = stateText;
    stateEl.classList.toggle("warn", low);

    // The countdown lives between - and +: the preset while the cooker is off,
    // the remaining minutes while it cooks (with the buttons out of the way).
    const bar = root.querySelector(".bar");
    const val = root.querySelector(".val");
    if (cooking) {
      val.textContent = duration > 0 ? `${remaining} min` : "no timer";
      const fraction = duration > 0 ? Math.max(0, Math.min(1, remaining / duration)) : 0;
      root.querySelector(".fill").style.width = `${fraction * 100}%`;
      root.querySelector(".fill").style.background = low
        ? "var(--warning-color, #e08a00)"
        : "var(--primary-color)";
      bar.hidden = duration <= 0;
    } else {
      val.textContent = `${duration} min`;
      bar.hidden = true;
    }
    if (this._minus) this._minus.hidden = cooking;
    if (this._plus) this._plus.hidden = cooking;
    root.querySelector(".dur").hidden = false;

    root.querySelector(".start").disabled = low || cooking;
    root.querySelector(".stop").disabled = !cooking;
  }

  _markerPosition(value, min, max) {
    // Home Assistant's slider draws its arc at radius 145 in a 320 unit box, from
    // 135 degrees over 270 degrees, so a value's place on the ring is:
    const span = max - min;
    const fraction = span > 0 ? Math.max(0, Math.min(1, (value - min) / span)) : 0.5;
    const angle = ((135 + 270 * fraction) * Math.PI) / 180;
    const radius = (145 / 320) * 100;             // per cent of the dial's box
    return {
      left: `${50 + radius * Math.cos(angle)}%`,
      top: `${50 + radius * Math.sin(angle)}%`,
    };
  }
}

customElements.define("anova-cook-card", AnovaCookCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "anova-cook-card",
  name: "Anova Cook Card",
  description:
    "One card for the Anova Cooker: duration while off, temperature while cooking, with the remaining time always in view.",
  preview: false,
});
