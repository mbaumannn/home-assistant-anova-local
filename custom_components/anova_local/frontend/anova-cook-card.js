/**
 * Anova Cook Card
 *
 * A sous-vide cook card for the Anova Cooker integration. It reuses Home
 * Assistant's own `ha-control-circular-slider` (the same dial the thermostat
 * card uses), so the timer ring looks and behaves exactly like the temperature
 * ring: drag it to set the duration.
 *
 * Idle:    drag the ring (or use -/+) to set the duration.
 * Cooking: the ring shows the remaining time and is not draggable.
 *
 * Registered automatically by the integration.
 *
 * Config:
 *   type: custom:anova-cook-card
 *   max: 240                 # duration dial range in minutes (default 240)
 *   step: 5                  # drag step in minutes (default 5)
 *   entities:                # optional overrides
 *     start / stop / duration / remaining / status / low_water
 */

const DEFAULTS = {
  start: "button.anova_cooker_start_cook",
  stop: "button.anova_cooker_stop_cook",
  duration: "number.anova_cooker_cook_duration",
  remaining: "sensor.anova_cooker_timer_remaining",
  status: "sensor.anova_cooker_status",
  low_water: "binary_sensor.anova_cooker_low_water",
};

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

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card { height: 100%; box-sizing: border-box; }
        .wrap { height: 100%; box-sizing: border-box;
                display: flex; flex-direction: column; align-items: center;
                gap: 8px; padding: 12px 16px 16px; }
        .title { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .dial { position: relative; width: 100%; max-width: 100%; }
        ha-control-circular-slider { width: 100% !important; display: block; }
        .center { position: absolute; inset: 0; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; gap: 2px;
                  padding-bottom: 15%; pointer-events: none; }
        .big { font-size: 34px; font-weight: 300; line-height: 1;
               font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .big small { font-size: 16px; color: var(--secondary-text-color); font-weight: 400; }
        .cap { font-size: 12px; color: var(--secondary-text-color); }
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
      </style>
      <ha-card>
        <div class="wrap">
          <div class="title"></div>
          <div class="dial">
            <ha-control-circular-slider mode="start"></ha-control-circular-slider>
            <div class="center"><div class="big"></div><div class="cap"></div></div>
          </div>
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
    const duration = Math.max(0, Math.round(value));
    this._setDuration(duration);
  }

  _setDuration(value) {
    this._hass.callService("number", "set_value", {
      entity_id: this._id("duration"),
      value,
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

    if (this._pending === "start" && status === "cooking") {
      clearTimeout(this._timer);
      this._pending = null;
    }
    const cooking = this._pending === "start" || status === "cooking";

    // The dial range: while cooking it is the configured duration so the ring
    // empties with the remaining time; while idle it is the configured max.
    const max = cooking ? Math.max(duration, 1) : Number(this._config?.max) || 240;
    const value = cooking ? Math.min(remaining, max) : duration;

    // Avoid echoing a programmatic value change back to the service.
    this._suppressSlider = true;
    this._slider.min = 0;
    this._slider.max = max;
    this._slider.step = this._stepSize();
    this._slider.value = value;
    this._slider.disabled = cooking;
    this._slider.style.setProperty(
      "--control-circular-slider-color",
      low ? "var(--warning-color, #e08a00)" : "var(--primary-color)"
    );
    this._suppressSlider = false;

    root.querySelector(".title").textContent = low
      ? "Low water"
      : cooking
        ? "Cooking"
        : "Cook";

    if (cooking) {
      root.querySelector(".big").innerHTML = `${remaining}<small> min</small>`;
      root.querySelector(".cap").textContent = `of ${duration} min`;
    } else {
      root.querySelector(".big").innerHTML = `${duration}<small> min</small>`;
      root.querySelector(".cap").textContent = "duration";
    }
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
  description: "Sous-vide cook card with a draggable duration dial for the Anova Cooker integration.",
  preview: false,
});
