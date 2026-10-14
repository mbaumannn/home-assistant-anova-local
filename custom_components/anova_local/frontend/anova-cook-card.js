/**
 * Anova Cook Card
 *
 * One card for the whole cooker, so nothing has to line up with a second card.
 * It reuses Home Assistant's own `ha-control-circular-slider` (the dial the
 * thermostat card uses), so the ring looks and behaves like Home Assistant
 * already looks and behaves.
 *
 * The ring means one thing per state, and the countdown is never hidden:
 *
 *   Off      the ring is the duration dial. Drag it (or use -/+) to set it.
 *   Heating  the ring is the target temperature; the water temperature sits under
 *   Cooking  it. The remaining time is in the top right, with a progress bar
 *            underneath, so it stays visible while the ring shows temperature.
 *   Low water the ring turns to the warning colour and Start is refused.
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

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card { height: 100%; box-sizing: border-box; }
        .wrap { height: 100%; box-sizing: border-box;
                display: flex; flex-direction: column; align-items: center;
                gap: 10px; padding: 14px 16px 16px; }
        .head { display: flex; align-items: baseline; justify-content: space-between;
                width: 100%; gap: 8px; }
        .state { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .left { font-size: 14px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums; white-space: nowrap; }
        .warn { color: var(--warning-color, #e08a00); }
        .dial { position: relative; width: 100%; max-width: 100%; }
        ha-control-circular-slider { width: 100% !important; display: block; }
        .center { position: absolute; inset: 0; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; gap: 2px;
                  padding-bottom: 15%; pointer-events: none; }
        .big { font-size: 34px; font-weight: 300; line-height: 1;
               font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .big small { font-size: 16px; color: var(--secondary-text-color); font-weight: 400; }
        .cap { font-size: 12px; color: var(--secondary-text-color); }
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
               font-variant-numeric: tabular-nums; }
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
            <span class="left"></span>
          </div>
          <div class="dial">
            <ha-control-circular-slider mode="start"></ha-control-circular-slider>
            <div class="center"><div class="big"></div><div class="cap"></div></div>
          </div>
          <div class="bar" hidden><div class="fill"></div></div>
          <div class="dur">
            <button class="step minus" aria-label="minder">−</button>
            <span class="val"></span>
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
    this.shadowRoot.querySelector(".minus").onclick = () =>
      this._stepBy(-this._stepSize());
    this.shadowRoot.querySelector(".plus").onclick = () =>
      this._stepBy(this._stepSize());
    this.shadowRoot.querySelector(".start").onclick = () => this._start();
    this.shadowRoot.querySelector(".stop").onclick = () => this._stop();
  }

  _stepSize() {
    return Number(this._config?.step) || 5;
  }

  _onSliderChanged(ev) {
    if (this._suppressSlider) return;
    const value = Number(ev.detail?.value);
    if (!Number.isFinite(value)) return;
    if (this._cooking) {
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

    // The ring: duration while off, target temperature while cooking.
    const ringIsTemperature = cooking && hasTarget;
    this._suppressSlider = true;
    if (ringIsTemperature) {
      this._slider.min = Math.max(minTemp, target - TEMP_RANGE);
      this._slider.max = Math.min(maxTemp, target + TEMP_RANGE);
      this._slider.step = 0.1;
      this._slider.value = target;
    } else {
      this._slider.min = 0;
      this._slider.max = cooking ? Math.max(duration, 1) : Number(this._config?.max) || 240;
      this._slider.step = this._stepSize();
      this._slider.value = cooking ? Math.min(remaining, this._slider.max) : duration;
    }
    this._slider.disabled = false; // drag to change the temperature mid-cook too
    this._slider.style.setProperty(
      "--control-circular-slider-color",
      low ? "var(--warning-color, #e08a00)" : "var(--primary-color)"
    );
    this._suppressSlider = false;

    // The centre: the ring's own value, with what the water is doing underneath.
    const big = root.querySelector(".big");
    const cap = root.querySelector(".cap");
    if (ringIsTemperature) {
      big.innerHTML = `${target.toFixed(1)}<small> ${unit}</small>`;
      cap.textContent = Number.isFinite(current)
        ? `water ${current.toFixed(1)} ${unit}`
        : "set temperature";
    } else {
      big.innerHTML = `${duration}<small> min</small>`;
      cap.textContent = "duration";
    }

    // The state in words, and the countdown that must stay visible while cooking.
    let stateText = "Off";
    if (low) {
      stateText = "Low water";
    } else if (cooking) {
      const reached = Number.isFinite(current) && hasTarget && current >= target - 0.5;
      stateText = reached ? "Cooking" : "Heating";
    }
    const stateEl = root.querySelector(".state");
    stateEl.textContent = stateText;
    stateEl.classList.toggle("warn", low);

    const left = root.querySelector(".left");
    const bar = root.querySelector(".bar");
    if (cooking) {
      left.textContent = duration > 0 ? `${remaining} min left` : "no timer";
      left.classList.toggle("warn", low);
      const fraction = duration > 0 ? Math.max(0, Math.min(1, remaining / duration)) : 0;
      root.querySelector(".fill").style.width = `${fraction * 100}%`;
      root.querySelector(".fill").style.background = low
        ? "var(--warning-color, #e08a00)"
        : "var(--primary-color)";
      bar.hidden = duration <= 0;
    } else {
      left.textContent = Number.isFinite(current)
        ? `water ${current.toFixed(1)} ${unit}`
        : "";
      left.classList.remove("warn");
      bar.hidden = true;
    }

    // The stepper belongs to the duration dial, so it is hidden while the ring
    // shows the temperature; Stop and Start stay put in both states.
    const dur = root.querySelector(".dur");
    dur.hidden = ringIsTemperature;
    root.querySelector(".val").textContent = `${duration} min`;

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
    "One card for the Anova Cooker: duration while off, temperature while cooking, with the remaining time always in view.",
  preview: false,
});
