/**
 * Anova Cook Card
 *
 * The ring is Home Assistant's own `ha-state-control-climate-temperature` —
 * literally the element inside `hui-thermostat-card`, given our real climate
 * state object. It answers drags itself (optimistic value, debounced commit,
 * the dot when off, the orange while it heats), so this file owns only the
 * parts around it: the timer — the remaining minutes sit between - and +,
 * exactly where the duration preset sits before a cook, with a progress bar
 * above them — and Start/Stop.
 *
 *   Off        grey rail with the target dot; -/+ set the duration.
 *   Heating    orange ring from hvac_action, with the water temperature as
 *   Cooking    the marker the dial draws itself, and the countdown between - and +.
 *   Low water  the warning colour, and Start is refused.
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
  timer: "switch.anova_cooker_timer",
  status: "sensor.anova_cooker_status",
  low_water: "binary_sensor.anova_cooker_low_water",
  climate: "climate.anova_cooker",
};

// A typed duration is shown at once and kept until the cooker reports it,
// so the stepper never snaps back while the round trip is still in flight.
const WANT_TIMEOUT = 15000;

// Home Assistant's thermostat card reserves a title bar of this height.
const TITLE_HEIGHT = 48;

class AnovaCookCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = null; // optimistic: "start" while the cooker reacts
    this._timer = null;
    // The per-second countdown ticker (started/stopped from _render).
    this._countTimer = null;
    // The (remaining, duration) the interpolation is anchored to, and when
    // those numbers arrived: the wire only reports whole minutes, the
    // seconds in between are display interpolation, never device truth.
    this._countKey = null;
    this._remainingAt = 0;
  }

  disconnectedCallback() {
    // A removed card must not keep ticking in the background.
    this._syncCountdownTimer(false);
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

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card { position: relative; height: 100%; padding: 12px 0 16px;
                  display: flex; flex-direction: column; }
        .title { height: ${TITLE_HEIGHT}px; box-sizing: border-box; margin: 0;
                 padding: 0 30px; display: flex; align-items: center;
                 justify-content: center; font-size: 16px; font-weight: 400;
                 color: var(--primary-text-color);
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                 flex: none; }
        ha-icon-button.more-info { position: absolute; top: 0; right: 4px;
                                   color: var(--secondary-text-color); }
        /* The dial, with Home Assistant's own container recipe: a square with
           the control centred inside it and an 8px padding. The negative bottom
           margin cancels the dead space under the 270-degree arc, so the timer
           sits close under the ring at any card width. */
        .dial { position: relative; flex: none; display: flex;
                align-items: center; justify-content: center;
                overflow: hidden; max-width: 100%; box-sizing: border-box;
                margin-bottom: -10%; }
        .dial:before { content: ""; display: block; padding-top: 100%; }
        .dial > * { padding: 8px; }
        ha-state-control-climate-temperature { width: 100%; }
        .type-overlay { position: absolute; inset: 0; display: flex;
                        align-items: center; justify-content: center;
                        pointer-events: none; }
        .warn { color: var(--warning-color, #ffa600); }
        .bar { flex: none; margin: 0 16px; height: 4px; border-radius: 2px;
               background: var(--divider-color); overflow: hidden; }
        .bar .fill { height: 100%; border-radius: 2px;
                     transition: width .3s ease; }
        .dur { flex: none; margin: 10px 16px; display: flex;
               align-items: center; gap: 20px; justify-content: center; }
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
        .btns { display: flex; gap: 10px; margin: 0 16px; flex: none; }
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
        <div class="dial">
          <ha-state-control-climate-temperature show-secondary
              prevent-interaction-on-scroll></ha-state-control-climate-temperature>
          <div class="type-overlay">
            <input class="big-input" type="number" inputmode="decimal" step="0.1"
                   hidden aria-label="temperature" />
          </div>
        </div>
        <div class="bar"><div class="fill"></div></div>
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
      </ha-card>
    `;

    // Home Assistant's own overflow menu: open the more-info dialog.
    this.shadowRoot.querySelector(".more-info").onclick = () =>
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: this._id("climate") },
          bubbles: true,
          composed: true,
        })
      );

    // The temperature: tapping the big number inside the component's shadow
    // root still reaches us as a composed click. Opening the field is blocked
    // while the cooker cannot be reached.
    this.shadowRoot.querySelector(".dial").addEventListener("click", (ev) => {
      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      if (path.some((node) => node.localName === "ha-big-number")) {
        this._openTemperatureInput();
      }
    });

    const bigInput = this.shadowRoot.querySelector(".big-input");
    bigInput.onkeydown = (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        this._commitTemperatureInput();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        this._closeTemperatureInput();
      }
    };
    bigInput.onblur = () => this._commitTemperatureInput();

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

  _openTemperatureInput() {
    if (!this._hasClimate || this._unreachable) return;
    const input = this.shadowRoot.querySelector(".big-input");
    if (!input || !input.hidden) return;
    const target = Number(this._attrs(this._id("climate")).temperature);
    input.value = Number.isFinite(target) ? String(target) : "";
    input.hidden = false;
    input.focus();
    if (input.select) input.select();
  }

  _commitTemperatureInput() {
    const input = this.shadowRoot.querySelector(".big-input");
    if (!input || input.hidden) return;
    const typed = Number(input.value);
    input.hidden = true;
    if (Number.isFinite(typed) && typed > 0) this._setTemperature(typed);
  }

  _closeTemperatureInput() {
    const input = this.shadowRoot.querySelector(".big-input");
    if (!input || input.hidden) return;
    input.hidden = true;
  }

  _setTemperature(value) {
    const wanted = Math.round(value * 10) / 10;
    this._hass.callService("climate", "set_temperature", {
      entity_id: this._id("climate"),
      temperature: wanted,
    });
  }

  _stepSize() {
    return Number(this._config?.step) || 5;
  }

  _setDuration(value) {
    // Show it at once: the cooker takes a moment, and a stepper that does not move
    // until the next poll feels broken.
    this._wantedDuration = value;
    this._wantedAt = Date.now();
    this._render();
    this._hass.callService("number", "set_value", {
      entity_id: this._id("duration"),
      value,
    });
  }

  /** What the user last asked for, until the cooker reports it (or it expires). */
  _pendingDuration(reported) {
    const wanted = this._wantedDuration;
    if (wanted === null || wanted === undefined) return reported;
    if (wanted === reported || Date.now() - (this._wantedAt || 0) > WANT_TIMEOUT) {
      this._wantedDuration = null;
      return reported;
    }
    return wanted;
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

  /** Start or stop the per-second countdown ticker. */
  _syncCountdownTimer(active) {
    if (active && !this._countTimer) {
      this._countTimer = setInterval(() => this._tickCountdown(), 1000);
    } else if (!active && this._countTimer) {
      clearInterval(this._countTimer);
      this._countTimer = null;
    }
  }

  /**
   * Paint the countdown between - and +, interpolating the seconds the wire
   * does not carry. Remember when the cooker's numbers arrived and let the
   * clock run between polls: 26 whole minutes from the device become a
   * ticking countdown on screen. Display only — the cooker stops itself from
   * its own finish event; nothing here ever commands or measures the cook.
   */
  _tickCountdown(remaining, duration) {
    if (remaining === undefined) {
      // The per-second tick: read the cooker's numbers afresh.
      remaining = Number(this._state(this._id("remaining"))) || 0;
      duration = Number(this._state(this._id("duration"))) || 0;
    }
    const val = this.shadowRoot.querySelector(".val");
    const fill = this.shadowRoot.querySelector(".fill");
    if (!val || !fill) return;
    const now = Date.now();
    const key = `${remaining}/${duration}`;
    if (this._countKey !== key) {
      // Fresh numbers from the cooker: restart the interpolation here.
      this._countKey = key;
      this._remainingAt = now;
    } else if (now - this._remainingAt > 55000) {
      // The numbers have not moved for a minute: the poll is stale, re-anchor
      // so the display cannot drift below the truth.
      this._remainingAt = now;
    }
    const seconds = Math.max(
      0,
      Math.min(remaining * 60, remaining * 60 - (now - this._remainingAt) / 1000)
    );
    val.innerHTML = seconds >= 60
      ? `${Math.ceil(seconds / 60)}<small> min</small>`
      : `${Math.floor(seconds)}<small> s</small>`;
    // The bar runs on the same interpolated clock.
    const fraction = Math.max(0, Math.min(1, (seconds / (duration * 60)) || 0));
    fill.style.width = `${fraction * 100}%`;
  }

  _render() {
    if (!this._hass) return;
    const root = this.shadowRoot;
    const status = this._state(this._id("status"));
    const low = this._state(this._id("low_water")) === "on";
    const remaining = Number(this._state(this._id("remaining"))) || 0;
    const duration = this._pendingDuration(
      Number(this._state(this._id("duration"))) || 0
    );
    const climateState = this._hass.states[this._id("climate")];
    const climate = this._attrs(this._id("climate"));
    const target = Number(climate.temperature);
    this._hasClimate = Boolean(climateState) && Number.isFinite(target);

    if (this._pending === "start" && status === "cooking") {
      clearTimeout(this._timer);
      this._pending = null;
    }
    // No reading: say so instead of showing the last one. The cooker is switched off
    // or out of reach, and a stale temperature is worse than no temperature.
    const unreachable = status === undefined || status === "unknown" || status === "unavailable";
    this._unreachable = unreachable;
    const cooking = !unreachable && (this._pending === "start" || status === "cooking");
    this._cooking = cooking;

    this.shadowRoot.querySelector(".title").textContent =
      climate.friendly_name || "Anova Cooker";

    // The ring is Home Assistant's own element with the real state object; it
    // answers drags, draws the dot when off and turns orange while heating,
    // all by itself.
    const stc = this._stc || (this._stc = root.querySelector("ha-state-control-climate-temperature"));
    stc.hidden = !this._hasClimate;
    if (this._hasClimate) {
      stc.stateObj = climateState;
    }

    // Fault colours: low water takes the warning colour, overriding the mode
    // colour that the control would otherwise resolve.
    const card = root.querySelector("ha-card");
    card.style.setProperty(
      "--state-climate-off-color",
      low ? "var(--warning-color, #ffa600)" : ""
    );
    card.style.setProperty(
      "--state-climate-heat-color",
      low ? "var(--warning-color, #ffa600)" : ""
    );

    // The countdown lives between - and +: the preset while the cooker is off, the
    // remaining minutes while the countdown runs (with the buttons out of the way).
    // A cook without a timer says so. The bar stays in the layout either way, so the
    // spacing is the same in every state.
    const timerOn = this._state(this._id("timer")) === "on";
    const hasTimer = timerOn || remaining > 0;
    const bar = root.querySelector(".bar");
    const fill = root.querySelector(".fill");
    const val = root.querySelector(".val");
    if (cooking) {
      if (hasTimer && duration > 0) {
        this._tickCountdown(remaining, duration);    // paint once, right now
        this._syncCountdownTimer(true);              // then once per second
      } else {
        val.innerHTML = "no timer";
        fill.style.width = "0%";
        this._syncCountdownTimer(false);
      }
      bar.style.background = "var(--divider-color)";
    } else {
      this._syncCountdownTimer(false);
      val.innerHTML = unreachable ? "—" : `${duration}<small> min</small>`;
      fill.style.width = "0%";
      bar.style.background = "transparent";          // holds the space, not the eye
    }
    fill.style.background = low
      ? "var(--warning-color, #ffa600)"
      : "var(--state-climate-heat-color, #ff6f22)";
    // The buttons step aside while cooking but keep their place, so the row — and
    // with it the spacing between the ring and the timer — is the same in both states.
    const stepsAway = cooking || unreachable;
    if (this._minus) this._minus.style.visibility = stepsAway ? "hidden" : "";
    if (this._plus) this._plus.style.visibility = stepsAway ? "hidden" : "";
    root.querySelector(".dur").hidden = false;

    root.querySelector(".start").disabled = unreachable || low || cooking;
    root.querySelector(".stop").disabled = unreachable || !cooking;
  }
}

customElements.define("anova-cook-card", AnovaCookCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "anova-cook-card",
  name: "Anova Cook Card",
  description:
    "Anova Cooker card in Home Assistant's own style: the thermostat ring with the remaining time between - and +.",
  preview: false,
});
