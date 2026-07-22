/**
 * ga-thermostat-card — the resident "Steuerung" control, first-party.
 *
 * The MyVibe look residents were trained on: a big current-temperature value,
 * a +/- setpoint, and an explicit AUS / MANUEL / KI mode row. Talks ONLY to the
 * standard climate.* services (`climate.set_temperature`, `climate.set_hvac_mode`)
 * — the ones every thermostat implements — so it works on a Zigbee TRV today and
 * a heat pump tomorrow. No third-party card, no add-on: it replaces the vendored
 * community `simple-thermostat` (Odoo #518), shrinking the bundle's supply-chain
 * surface to our own code.
 *
 * A resident (Non-Admin) can use it: it only calls climate services on the
 * entity, which their room scope already permits.
 *
 * Mode mapping (ga_heating semantics — see ga-home-strategy / ADR-0014):
 *   KI     = hvac_mode "auto"  (the plan runs)   [mdi:brain]
 *   MANUEL = hvac_mode "heat"  (resident's dial)  [mdi:hand-back-left]
 *   AUS    = hvac_mode "off"
 * Only modes the entity actually exposes (hvac_modes) are shown.
 *
 * Config:
 *   type: custom:ga-thermostat-card
 *   entity: climate.wohnzimmer
 *   header: "Steuerung"     # optional, default "Steuerung"
 */

const MODE_LABELS = [
  ["auto", "KI", "mdi:brain"],
  ["heat", "MANUEL", "mdi:hand-back-left"],
  ["off", "AUS", "mdi:power"],
];

class GaThermostatCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("climate.")) {
      throw new Error("ga-thermostat-card: 'entity' muss eine climate.* Entity sein");
    }
    this._config = config;
    this._root = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 3;
  }

  _state() {
    return this._hass && this._hass.states[this._config.entity];
  }

  _setTemp(delta) {
    const s = this._state();
    if (!s) return;
    const step = Number(s.attributes.target_temp_step) || 0.5;
    const min = Number(s.attributes.min_temp);
    const max = Number(s.attributes.max_temp);
    let t = Number(s.attributes.temperature);
    if (Number.isNaN(t)) return;
    t = Math.round((t + delta * step) / step) * step;
    if (!Number.isNaN(min)) t = Math.max(min, t);
    if (!Number.isNaN(max)) t = Math.min(max, t);
    this._hass.callService("climate", "set_temperature", {
      entity_id: this._config.entity,
      temperature: t,
    });
  }

  _setMode(mode) {
    this._hass.callService("climate", "set_hvac_mode", {
      entity_id: this._config.entity,
      hvac_mode: mode,
    });
  }

  _render() {
    const s = this._state();
    if (!this._root) {
      this._root = document.createElement("ha-card");
      this._root.className = "ga-thermostat";
      const style = document.createElement("style");
      style.textContent = `
        ga-thermostat-card .ga-thermostat { padding: 16px; }
        ga-thermostat-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 10px; }
        ga-thermostat-card .val { text-align: center; font-size: 35px; font-weight: 500;
          line-height: 1.1; }
        ga-thermostat-card .val small { font-size: 15px; opacity: .6; }
        ga-thermostat-card .set { display: flex; align-items: center; justify-content: center;
          gap: 18px; margin: 10px 0 14px; }
        ga-thermostat-card .set button { width: 44px; height: 44px; border-radius: 50%;
          border: none; cursor: pointer; font-size: 22px; line-height: 1;
          background: var(--secondary-background-color, #e8e8e8);
          color: var(--primary-text-color, #212121); }
        ga-thermostat-card .set .target { min-width: 82px; text-align: center;
          font-size: 22px; font-weight: 600; }
        ga-thermostat-card .modes { display: flex; gap: 8px; }
        ga-thermostat-card .modes .m { flex: 1; padding: 9px 0; border-radius: 10px;
          text-align: center; cursor: pointer; font-weight: 600; font-size: .9em;
          background: var(--secondary-background-color, #e8e8e8);
          color: var(--primary-text-color, #212121); border: none; }
        ga-thermostat-card .modes .m.on { background: var(--primary-color, #03a9f4); color: #fff; }
        ga-thermostat-card .modes .m ha-icon { --mdc-icon-size: 20px; display: block; margin: 0 auto 2px; }
        ga-thermostat-card .off { text-align: center; opacity: .6; padding: 20px 0; }
      `;
      this.appendChild(style);
      this.appendChild(this._root);
    }

    if (!s) {
      this._root.innerHTML = `<div class="ga-thermostat off">Thermostat nicht verfügbar</div>`;
      return;
    }

    const header = this._config.header || "Steuerung";
    const cur = s.attributes.current_temperature;
    const target = s.attributes.temperature;
    const modes = s.attributes.hvac_modes || [];
    const active = s.state;

    const curTxt = cur != null ? `${Number(cur).toFixed(1)}<small> °C</small>` : "–";
    const modeBtns = MODE_LABELS
      .filter(([m]) => modes.includes(m))
      .map(([m, label, icon]) =>
        `<button class="m ${active === m ? "on" : ""}" data-mode="${m}">` +
        `<ha-icon icon="${icon}"></ha-icon>${label}</button>`)
      .join("");

    // A setpoint only makes sense when the thermostat is actually heating.
    const showSet = target != null && active !== "off";
    const setRow = showSet
      ? `<div class="set">
           <button data-delta="-1" aria-label="kälter">−</button>
           <div class="target">${Number(target).toFixed(1)} °C</div>
           <button data-delta="1" aria-label="wärmer">+</button>
         </div>`
      : "";

    this._root.innerHTML =
      `<div class="ga-thermostat">
         <div class="hdr">${header}</div>
         <div class="val">${curTxt}</div>
         ${setRow}
         <div class="modes">${modeBtns}</div>
       </div>`;

    this._root.querySelectorAll(".set button").forEach((b) =>
      b.addEventListener("click", () => this._setTemp(Number(b.dataset.delta))));
    this._root.querySelectorAll(".modes .m").forEach((b) =>
      b.addEventListener("click", () => this._setMode(b.dataset.mode)));
  }
}

customElements.define("ga-thermostat-card", GaThermostatCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-thermostat-card",
  name: "GA Thermostat Card",
  description: "Resident heating control (AUS/MANUEL/KI + setpoint) — first-party.",
});
