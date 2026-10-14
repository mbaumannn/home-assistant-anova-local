/**
 * Anova Cook Card
 *
 * A sous-vide cook card for the Anova Bluetooth integration. It mirrors the
 * Home Assistant thermostat card: a centred title, the same 300 degree dial
 * geometry and size, and the controls below, so the two cards line up.
 *
 * Idle:  the ring shows the configured duration.
 * Cooking: the ring depletes with the remaining time.
 *
 * Registered automatically by the integration; no extra frontend cards needed.
 *
 * Config:
 *   type: custom:anova-cook-card
 *   entities:            # optional overrides
 *     start / stop / duration / remaining / status / low_water
 */

const DEFAULTS = {
  start: "button.anova_bluetooth_start_cook",
  stop: "button.anova_bluetooth_stop_cook",
  duration: "number.anova_bluetooth_cook_duration",
  remaining: "sensor.anova_bluetooth_timer_remaining",
  status: "sensor.anova_bluetooth_status",
  low_water: "binary_sensor.anova_bluetooth_low_water",
};

// 300 degree arc, radius 108, in the same 300x210 viewBox as the HA dial
const ARC_LENGTH = 108 * ((300 * Math.PI) / 180); // 565.5

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
    return 8;
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
                gap: 10px; padding: 12px 16px 16px; }
        .header { align-self: stretch; text-align: center; font-size: 16px;
                  font-weight: 500; color: var(--primary-text-color); }
        .ring { position: relative; width: 100%; margin: 0 auto; }
        .ring svg { display: block; width: 100%; height: auto; }
        .track { fill: none; stroke: var(--secondary-background-color); stroke-width: 16;
                 stroke-linecap: round; }
        .prog { fill: none; stroke: var(--primary-color); stroke-width: 16;
                stroke-linecap: round; transition: stroke-dashoffset .6s ease; }
        .ring.low .prog { stroke: var(--warning-color, #e08a00); }
        .ring.idle .prog { opacity: .35; }
        .center { position: absolute; left: 0; right: 0; top: 32%;
                  display: flex; flex-direction: column; align-items: center; gap: 2px; }
        .big { font-size: 34px; font-weight: 300; line-height: 1;
               font-variant-numeric: tabular-nums; }
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
          <div class="header"></div>
          <div class="ring">
            <svg viewBox="0 0 300 210">
              <path class="track" d="M42 180 A108 108 0 1 1 258 180"></path>
              <path class="prog" d="M42 180 A108 108 0 1 1 258 180"
                    stroke-dasharray="${ARC_LENGTH}" stroke-dashoffset="0"></path>
            </svg>
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

    const pct = cooking
      ? duration
        ? Math.max(0, Math.min(1, remaining / duration))
        : 1
      : 1; // idle: the ring shows the full configured duration
    root.querySelector(".prog").style.strokeDashoffset = String(ARC_LENGTH * (1 - pct));
    const ring = root.querySelector(".ring");
    ring.classList.toggle("low", low);
    ring.classList.toggle("idle", !cooking);

    root.querySelector(".header").textContent = low
      ? "Low water"
      : cooking
        ? "Aan het koken"
        : "Koken";

    if (cooking) {
      root.querySelector(".big").innerHTML = `${remaining}<small> min</small>`;
      root.querySelector(".cap").textContent = `van ${duration} min`;
    } else {
      root.querySelector(".big").innerHTML = `${duration}<small> min</small>`;
      root.querySelector(".cap").textContent = "kookduur";
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
  description: "Sous-vide cook card with a countdown ring for the Anova Bluetooth integration.",
  preview: false,
});
