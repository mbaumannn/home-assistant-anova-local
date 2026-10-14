/**
 * Anova Cook Card
 *
 * Built to look like Home Assistant's own thermostat card, because that is the
 * card it replaces: the same dial, the same typography, the same colours —
 * blue while you are setting up, the heat colour while it works. One thing is
 * ours: the timer. The remaining minutes sit between - and +, exactly where the
 * duration preset sits before a cook, with a progress bar above them.
 *
 *   Off        blue ring on the target temperature; -/+ set the duration.
 *   Heating    orange ring, still on the target temperature, with the water
 *   Cooking    temperature as the marker Home Assistant's own dial draws, and the
 *              countdown between - and +.
 *   Low water  the warning colour, and Start is refused.
 *
 * The numbers follow Home Assistant's own `ha-big-number`: 44px for the digits,
 * the decimal at 0.42em and the unit at 0.33em. The values for those, for the
 * label sizes and for the marker were read from a live card, not guessed.
 *
 * Config:
 *   type: custom:anova-cook-card
 *   max: 240                 # duration dial range in minutes (default 240)
 *   step: 5                  # drag/step size in minutes (default 5)
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

// Home Assistant's thermostat card reserves a title bar of this height, and its
// text block sits slightly above the middle of the dial because the dial has a gap
// at the bottom.
const TITLE_HEIGHT = 48;
const INFO_LIFT = 3.5; // per cent of the dial's width

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
    return 11;
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
        ha-card { position: relative; height: 100%; box-sizing: border-box; }
        .title { height: ${TITLE_HEIGHT}px; box-sizing: border-box; margin: 0;
                 padding: 0 30px; display: flex; align-items: center;
                 justify-content: center; font-size: 16px; font-weight: 400;
                 color: var(--primary-text-color);
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        ha-icon-button.more-info { position: absolute; top: 0; right: 4px;
                                   color: var(--secondary-text-color); }
        .wrap { box-sizing: border-box; display: flex; flex-direction: column;
                align-items: center; gap: 10px; padding: 0 16px 16px; }
        .dial { position: relative; width: 100%; max-width: 100%; }
        ha-control-circular-slider { width: 100% !important; display: block; }
        .info { position: absolute; inset: 0; display: flex; flex-direction: column;
                align-items: center; justify-content: center; gap: 6px;
                padding-bottom: ${INFO_LIFT}%; pointer-events: none; }
        .label { margin: 0; font-size: 16px; font-weight: 500;
                 color: var(--primary-text-color); }
        .label.secondary { display: flex; align-items: center; gap: 4px; }
        .label.secondary ha-icon { --mdc-icon-size: 16px; }
        .big { font-size: 44px; font-weight: 400; line-height: 1.12;
               font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .big .decimal { font-size: 0.42em; }
        .big .unit { font-size: 0.33em; }
        .sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
              overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
        .warn { color: var(--warning-color, #ffa600); }
        .bar { width: 100%; height: 4px; border-radius: 2px;
               background: var(--divider-color); overflow: hidden; }
        .bar .fill { height: 100%; border-radius: 2px;
                     transition: width .3s ease; }
        .dur { display: flex; align-items: center; gap: 20px; }
        .step { width: 44px; height: 44px; border-radius: 22px;
                border: 1px solid var(--divider-color);
                background: var(--card-background-color); color: var(--primary-text-color);
                font-size: 22px; line-height: 1; cursor: pointer; }
        .val { min-width: 96px; text-align: center; font-size: 28px; font-weight: 400;
               font-variant-numeric: tabular-nums; cursor: pointer;
               color: var(--primary-text-color); }
        .val small { font-size: 0.42em; margin-left: 3px; }
        .val-input { width: 96px; min-width: 96px; text-align: center; font-size: 28px;
                     font-weight: 400; font-variant-numeric: tabular-nums;
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
        <p class="title"></p>
        <ha-icon-button class="more-info" aria-label="More information">
          <ha-icon icon="mdi:dots-vertical"></ha-icon>
        </ha-icon-button>
        <div class="wrap">
          <div class="dial">
            <ha-control-circular-slider mode="start"></ha-control-circular-slider>
            <div class="info">
              <p class="label state"></p>
              <div class="big" aria-hidden="true"></div>
              <p class="label secondary">
                <ha-icon icon="mdi:thermometer"></ha-icon><span class="cur"></span>
              </p>
              <span class="sr"></span>
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
    this._slider.addEventListener("value-changed", (ev) => this._onSliderChanged(ev));
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

    // Home Assistant's own overflow menu: open the more-info dialog.
    this.shadowRoot.querySelector(".more-info").onclick = () =>
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: this._id("climate") },
          bubbles: true,
          composed: true,
        })
      );

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

  /** A number the way Home Assistant shows it: no trailing zero. */
  _short(value) {
    return String(Number(value.toFixed(1)));
  }

  /** The big number, split like Home Assistant's own: digits, decimal, unit. */
  _bigNumberHtml(value, unit) {
    const [whole, decimal] = value.toFixed(1).split(".");
    return (
      `<span>${whole}</span>` +
      `<span class="decimal">.${decimal}</span>` +
      `<span class="unit">${unit}</span>`
    );
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
    const hasCurrent = Number.isFinite(current);
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
    // cook is the whole point. Without a climate entity it falls back to being the
    // duration dial, so a partial entity set still works.
    const ringIsTemperature = hasTarget;
    this._ringIsTemperature = ringIsTemperature;   // the drag route reads this back

    this.shadowRoot.querySelector(".title").textContent =
      climate.friendly_name || "Anova Cooker";

    // Blue while you are setting up, the heat colour while it works, warning when
    // something is wrong: the same colours Home Assistant's own card uses.
    const accent = low
      ? "var(--warning-color, #ffa600)"
      : cooking
        ? "var(--state-climate-heat-color, #ff6f22)"
        : "var(--primary-color)";

    this._suppressSlider = true;
    if (!this._dragging) {                         // never fight a finger on the dial
      if (ringIsTemperature) {
        const range = this._temperatureRange(target, minTemp, maxTemp, unit);
        this._slider.min = range.min;
        this._slider.max = range.max;
        this._slider.step = 0.1;
        this._slider.value = target;
        // Let Home Assistant's own dial draw the water temperature as its marker.
        this._slider.current = hasCurrent ? current : undefined;
      } else {
        this._slider.min = 0;
        this._slider.max = cooking ? Math.max(duration, 1) : Number(this._config?.max) || 240;
        this._slider.step = this._stepSize();
        this._slider.value = cooking ? Math.min(remaining, this._slider.max) : duration;
        this._slider.current = undefined;
      }
    }
    this._slider.disabled = false; // drag to change the temperature mid-cook too
    this._slider.style.setProperty("--control-circular-slider-color", accent);
    this._suppressSlider = false;

    // The state in words, in the middle of the ring, like the card it replaces.
    let stateText = "Off";
    if (low) {
      stateText = "Low water";
    } else if (cooking) {
      const reached = hasCurrent && hasTarget && current >= target - 0.5;
      stateText = reached ? "Cooking" : "Heating";
    }

    // The centre, exactly like the card this replaces: the state, the target with
    // a small decimal and unit, and the water temperature with a thermometer.
    const big = root.querySelector(".big");
    const cur = root.querySelector(".cur");
    const sr = root.querySelector(".sr");
    const stateEl = root.querySelector(".state");
    if (ringIsTemperature) {
      big.innerHTML = this._bigNumberHtml(target, unit);
      cur.textContent = hasCurrent ? `${this._short(current)} ${unit}` : "";
      sr.textContent = `${stateText} ${this._short(target)} ${unit}`.trim();
    } else {
      big.innerHTML = `${duration}<span class="unit">min</span>`;
      cur.textContent = "";
      sr.textContent = `${stateText} ${duration} min`.trim();
    }
    root.querySelector(".label.secondary").hidden = !hasCurrent || !ringIsTemperature;
    stateEl.textContent = stateText;
    stateEl.classList.toggle("warn", low);

    // The countdown lives between - and +: the preset while the cooker is off,
    // the remaining minutes while it cooks (with the buttons out of the way).
    const bar = root.querySelector(".bar");
    const val = root.querySelector(".val");
    if (cooking) {
      val.innerHTML = duration > 0
        ? `${this._short(remaining)}<small> min</small>`
        : "no timer";
      const fraction = duration > 0 ? Math.max(0, Math.min(1, remaining / duration)) : 0;
      root.querySelector(".fill").style.width = `${fraction * 100}%`;
      bar.hidden = duration <= 0;
    } else {
      val.innerHTML = `${duration}<small> min</small>`;
      bar.hidden = true;
    }
    root.querySelector(".fill").style.background = accent;
    if (this._minus) this._minus.hidden = cooking;
    if (this._plus) this._plus.hidden = cooking;
    root.querySelector(".dur").hidden = false;

    root.querySelector(".start").disabled = low || cooking;
    root.querySelector(".stop").disabled = !cooking;
  }
}

customElements.define("anova-cook-card", AnovaCookCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "anova-cook-card",
  name: "Anova Cook Card",
  description:
    "Anova Cooker card in Home Assistant's own style, with the remaining time between - and +.",
  preview: false,
});
