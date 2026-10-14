/**
 * Anova Cook Card
 *
 * A compact sous-vide cook card for the Anova Bluetooth integration:
 * a countdown ring with the duration stepper and Start/Stop, plus a low-water
 * warning. Registered automatically by the integration, so no extra frontend
 * cards are required.
 *
 * Config:
 *   type: custom:anova-cook-card
 *   # optional overrides
 *   entities:
 *     start: button.anova_bluetooth_start_cook
 *     stop: button.anova_bluetooth_stop_cook
 *     duration: number.anova_bluetooth_cook_duration
 *     remaining: sensor.anova_bluetooth_timer_remaining
 *     status: sensor.anova_bluetooth_status
 *     low_water: binary_sensor.anova_bluetooth_low_water
 */

const DEFAULTS = {
  start: "button.anova_bluetooth_start_cook",
  stop: "button.anova_bluetooth_stop_cook",
  duration: "number.anova_bluetooth_cook_duration",
  remaining: "sensor.anova_bluetooth_timer_remaining",
  status: "sensor.anova_bluetooth_status",
  low_water: "binary_sensor.anova_bluetooth_low_water",
};

const RING_RADIUS = 52;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

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
    return 4;
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
        ha-card { padding: 16px; }
        .wrap { display: flex; gap: 18px; align-items: center; }
        .ring { position: relative; width: 150px; height: 150px; flex: 0 0 auto; }
        .ring svg { width: 150px; height: 150px; transform: rotate(-90deg); }
        .ring .track { fill: none; stroke: var(--secondary-background-color); stroke-width: 12; }
        .ring .prog { fill: none; stroke: var(--primary-color); stroke-width: 12;
                      stroke-linecap: round; transition: stroke-dashoffset .6s ease; }
        .ring ha-card.low .prog { stroke: var(--warning-color, #e08a00); }
        .center { position: absolute; inset: 0; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; gap: 1px; }
        .big { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
        .cap { font-size: 11px; color: var(--secondary-text-color); }
        .ctrl { flex: 1; display: flex; flex-direction: column; gap: 12px; }
        .dur { display: flex; align-items: center; gap: 10px; }
        .dur .label { flex: 1; color: var(--secondary-text-color); font-size: 13px; }
        .step { width: 38px; height: 38px; border-radius: 12px; border: 1px solid var(--divider-color);
                background: var(--card-background-color); color: var(--primary-text-color);
                font-size: 19px; cursor: pointer; }
        .val { min-width: 62px; text-align: center; font-size: 19px; font-weight: 600;
               font-variant-numeric: tabular-nums; }
        .btns { display: flex; gap: 10px; }
        button.act { flex: 1; height: 44px; border-radius: 22px; border: none; cursor: pointer;
                     font-size: 15px; font-weight: 600; }
        button.act:disabled { opacity: .45; cursor: default; }
        .start { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .stop { background: transparent; color: var(--primary-text-color);
                border: 1px solid var(--divider-color) !important; }
        .chip { align-self: flex-start; font-size: 12px; padding: 3px 10px; border-radius: 999px;
                background: var(--secondary-background-color); color: var(--secondary-text-color); }
        .chip.good { background: rgba(46,158,91,.15); color: #2e9e5b; }
        .chip.warn { background: rgba(224,138,0,.15); color: #c47a00; }
        .billow { color: var(--secondary-text-color); font-size: 12px; }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="ring">
            <svg viewBox="0 0 120 120">
              <circle class="track" cx="60" cy="60" r="${RING_RADIUS}"></circle>
              <circle class="prog" cx="60" cy="60" r="${RING_RADIUS}"
                      stroke-dasharray="${RING_CIRCUMFERENCE}"
                      stroke-dashoffset="${RING_CIRCUMFERENCE}"></circle>
            </svg>
            <div class="center"><div class="big"></div><div class="cap"></div></div>
          </div>
          <div class="ctrl">
            <div class="dur">
              <span class="label">Duur</span>
              <button class="step minus" aria-label="minder">−</button>
              <span class="val"></span>
              <button class="step plus" aria-label="meer">＋</button>
            </div>
            <div class="btns">
              <button class="act start">Start cook</button>
              <button class="act stop">Stop</button>
            </div>
            <div class="chips"></div>
          </div>
        </div>
      </ha-card>
    `;
    this.shadowRoot.querySelector(".minus").onclick = () => this._step(-5);
    this.shadowRoot.querySelector(".plus").onclick = () => this._step(5);
    this.shadowRoot.querySelector(".start").onclick = () => this._start();
    this.shadowRoot.querySelector(".stop").onclick = () => this._stop();
  }

  _step(delta) {
    const dur = Number(this._state(this._id("duration"))) || 0;
    const value = Math.max(0, Math.min(6000, dur + delta));
    this._hass.callService("number", "set_value", {
      entity_id: this._id("duration"),
      value,
    });
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

    const pct = cooking && duration ? Math.max(0, Math.min(1, remaining / duration)) : 0;
    root.querySelector(".prog").style.strokeDashoffset = String(
      RING_CIRCUMFERENCE * (1 - pct)
    );

    root.querySelector(".big").textContent = cooking ? `${remaining} min` : "Start";
    root.querySelector(".cap").textContent = cooking
      ? `${duration} min ingesteld`
      : "tik op Start";
    root.querySelector(".val").textContent = `${duration} min`;

    const startBtn = root.querySelector(".start");
    const stopBtn = root.querySelector(".stop");
    startBtn.disabled = low || cooking;
    stopBtn.disabled = !cooking;

    const chips = root.querySelector(".chips");
    chips.innerHTML = low
      ? '<span class="chip warn">low water: vul water bij</span>'
      : cooking
        ? '<span class="chip good">cooking</span>'
        : '<span class="chip">idle</span>';
    root.querySelector("ha-card").classList.toggle("low", low);
  }
}

customElements.define("anova-cook-card", AnovaCookCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "anova-cook-card",
  name: "Anova Cook Card",
  description: "Sous-vide cook card with a countdown ring for the Anova Bluetooth integration.",
  preview: false,
});
