/**
 * ga-thermostat-card — the resident "Steuerung" control, first-party.
 *
 * One card, three looks (Odoo #518), chosen with `variant`:
 *   classic  (default) big current value + a +/- setpoint + AUS/MANUEL/KI chips
 *   dial               a round control (drag the ring to set), same chips
 *   setpoint           the target is the big number, large +/- buttons
 *
 * All three talk ONLY to the standard climate.* services
 * (`climate.set_temperature`, `climate.set_hvac_mode`) — the ones every
 * thermostat implements — so they work on a Zigbee TRV today and a heat pump
 * tomorrow. No third-party card, no add-on. The built-in HA thermostat card
 * (the round dial with HA's default mode names) is a separate strategy option
 * (`thermostat_style: "core"`); this card is our own KI/MANUEL/AUS look.
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
 *   header: "Steuerung"             # optional, default "Steuerung"
 *   variant: classic|dial|setpoint  # optional, default "classic"
 */

//: How long a run of presses is allowed to accumulate before one command is
//: sent. Long enough that a human pressing repeatedly produces ONE call, short
//: enough that a single press still feels immediate.
const COMMIT_DELAY_MS = 400;

const MODE_LABELS = [
  ["auto", "KI", "mdi:brain"],
  ["heat", "MANUEL", "mdi:hand-back-left"],
  ["off", "AUS", "mdi:power"],
];

// Dial geometry: a 270° arc with a 90° gap at the bottom (0° = top, clockwise).
const DIAL = { size: 200, c: 100, r: 82, start: -135, sweep: 270 };

const STYLE = `
  ga-thermostat-card .ga-body { padding: 16px; }
  ga-thermostat-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 10px; }
  /* The running state is a WORD first; the colour only reinforces it. A badge
     that says nothing without colour says nothing to a reader who cannot
     distinguish it. */
  ga-thermostat-card .act { float: right; font-size: 12px; font-weight: 600;
    padding: 1px 8px; border-radius: 10px; opacity: 1; }
  ga-thermostat-card .act-heating { background: rgba(230,126,34,.16); color: #b95b0b; }
  ga-thermostat-card .act-idle { background: rgba(127,140,141,.16); color: #5d6d6e; }
  ga-thermostat-card .act-off { background: rgba(127,140,141,.12); color: #7f8c8d; }
  ga-thermostat-card .val { text-align: center; font-size: 35px; font-weight: 500; line-height: 1.1; }
  ga-thermostat-card .val small { font-size: 15px; opacity: .6; }
  ga-thermostat-card .set { display: flex; align-items: center; justify-content: center;
    gap: 18px; margin: 10px 0 14px; }
  ga-thermostat-card .set button { width: 44px; height: 44px; border-radius: 50%;
    border: none; cursor: pointer; font-size: 22px; line-height: 1;
    background: var(--secondary-background-color, #e8e8e8);
    color: var(--primary-text-color, #212121); }
  ga-thermostat-card .set .target { min-width: 82px; text-align: center; font-size: 22px; font-weight: 600; }
  ga-thermostat-card .modes { display: flex; gap: 8px; }
  ga-thermostat-card .modes .m { flex: 1; padding: 9px 0; border-radius: 10px; text-align: center;
    cursor: pointer; font-weight: 600; font-size: .9em; border: none;
    background: var(--secondary-background-color, #e8e8e8);
    color: var(--primary-text-color, #212121); }
  ga-thermostat-card .modes .m.on { background: var(--primary-color, #03a9f4); color: #fff; }
  ga-thermostat-card .modes .m.on.heat { background: var(--ga-heat, #ff8a3d); }
  ga-thermostat-card .modes .m ha-icon { --mdc-icon-size: 20px; display: block; margin: 0 auto 2px; }
  ga-thermostat-card .off, ga-thermostat-card .offmsg { text-align: center; opacity: .6; padding: 20px 0; }
  /* setpoint */
  ga-thermostat-card .sp .cur { text-align: center; opacity: .6; font-size: 13px; margin-bottom: 4px; }
  ga-thermostat-card .sp .big { display: flex; align-items: center; justify-content: center;
    gap: 16px; margin: 2px 0 14px; }
  ga-thermostat-card .sp .big button { width: 52px; height: 52px; border-radius: 16px; border: none;
    cursor: pointer; font-size: 26px; line-height: 1;
    background: var(--secondary-background-color, #e8e8e8); color: var(--primary-text-color, #212121); }
  ga-thermostat-card .sp .big .t { font-size: 50px; font-weight: 600; line-height: 1; min-width: 118px; text-align: center; }
  ga-thermostat-card .sp .big .t small { font-size: 17px; opacity: .55; font-weight: 500; }
  /* dial */
  ga-thermostat-card .dialwrap { display: flex; justify-content: center; margin: 4px 0 12px; }
  ga-thermostat-card svg.dial { touch-action: none; cursor: pointer; width: 200px; max-width: 100%; }
  ga-thermostat-card svg.dial text { fill: var(--primary-text-color, #212121); }
  ga-thermostat-card svg.dial .d-act { font-size: 12px; fill: var(--secondary-text-color, #888); }
  ga-thermostat-card svg.dial .d-tgt { font-size: 30px; font-weight: 600; }
  ga-thermostat-card svg.dial .d-cur { font-size: 12px; fill: var(--secondary-text-color, #888); }
`;

class GaThermostatCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("climate.")) {
      throw new Error("ga-thermostat-card: 'entity' muss eine climate.* Entity sein");
    }
    this._config = config;
    this._variant = ["dial", "setpoint"].includes(config.variant) ? config.variant : "classic";
    this._root = null;
  }

  set hass(hass) {
    this._hass = hass;
    const s = this._state();
    this._reconcilePending(s);
    if (this._dragging) return;
    if (this._pending != null) {
      // A press run is still in flight. Rebuilding now would both replace the
      // buttons under the resident's finger and overwrite their intent with
      // the value the backend has not yet been told about.
      this._showPending();
      return;
    }
    this._render();
  }

  getCardSize() { return this._variant === "dial" ? 4 : 3; }

  _state() { return this._hass && this._hass.states[this._config.entity]; }
  _step(s) { return Number(s.attributes.target_temp_step) || 0.5; }
  _clamp(s, t) {
    const min = Number(s.attributes.min_temp), max = Number(s.attributes.max_temp);
    if (!Number.isNaN(min)) t = Math.max(min, t);
    if (!Number.isNaN(max)) t = Math.min(max, t);
    return t;
  }
  _commitTemp(t) {
    this._hass.callService("climate", "set_temperature", { entity_id: this._config.entity, temperature: t });
  }

  /**
   * Step the setpoint. Presses accumulate; none of them is lost.
   *
   * THE DEFECT THIS REPLACES, measured on a bench device on 2026-09-16: nine
   * presses produced seven steps. Two independent causes, and fixing either
   * alone still loses presses.
   *
   * 1. READ-MODIFY-WRITE AGAINST A STALE VALUE. Each press read
   *    `attributes.temperature` — the value the BACKEND last confirmed — and
   *    wrote that plus one step. Two presses inside one round trip therefore
   *    both read 19.5 and both wrote 20.0, and the second one vanished. The
   *    faster the resident presses, the more they lose, which is precisely
   *    backwards.
   * 2. THE BUTTON IS REPLACED MID-CLICK. Every state update re-renders the
   *    whole card with `innerHTML`, so the element a press is travelling to
   *    can be detached before the event lands (observed as "Element is not
   *    attached to the DOM"). Handled separately by delegating the listener
   *    to the root, which survives a re-render.
   *
   * The pending value is the resident's intent, and it is what the card shows
   * until the backend confirms it. The service call is debounced so a run of
   * presses is one command, not one per press — a TRV that is asked five times
   * in two seconds obeys the last answer anyway.
   */
  _setTemp(delta) {
    const s = this._state();
    if (!s) return;
    const step = this._step(s);
    const base = this._pending != null ? this._pending : Number(s.attributes.temperature);
    if (Number.isNaN(base)) return;
    this._pending = this._clamp(s, Math.round((base + delta * step) / step) * step);
    this._showPending();
    clearTimeout(this._commitTimer);
    this._commitTimer = setTimeout(() => this._flushTemp(), COMMIT_DELAY_MS);
  }

  /** Send the accumulated intent, once. */
  _flushTemp() {
    if (this._pending == null || !this._hass) return;
    this._commitTemp(this._pending);
  }

  /**
   * Paint the pending value without rebuilding the card.
   *
   * A full re-render here would replace the very buttons being pressed, which
   * is cause 2 above. Only the number changes.
   */
  _showPending() {
    if (!this._root || this._pending == null) return;
    const el = this._root.querySelector(".target, .sp .t");
    if (!el) return;
    el.innerHTML = this._variant === "setpoint"
      ? `${this._pending.toFixed(1)}<small> °C</small>`
      : `${this._pending.toFixed(1)} °C`;
  }

  /**
   * Has the backend caught up with what the resident asked for?
   *
   * Cleared only when the confirmed value MATCHES the pending one. Clearing on
   * any update instead would drop the intent every time an unrelated attribute
   * changes — a TRV reports its local temperature every few seconds, so that
   * is most updates.
   */
  _reconcilePending(s) {
    if (this._pending == null) return;
    const confirmed = Number(s && s.attributes && s.attributes.temperature);
    if (!Number.isNaN(confirmed) && Math.abs(confirmed - this._pending) < 1e-6) {
      this._pending = null;
    }
  }
  _setMode(mode) {
    this._hass.callService("climate", "set_hvac_mode", { entity_id: this._config.entity, hvac_mode: mode });
  }

  _modeRow(s) {
    const modes = s.attributes.hvac_modes || [];
    return `<div class="modes">` + MODE_LABELS
      .filter(([m]) => modes.includes(m))
      .map(([m, label, icon]) =>
        `<button class="m ${s.state === m ? "on" : ""} ${m === "heat" ? "heat" : ""}" data-mode="${m}">` +
        `<ha-icon icon="${icon}"></ha-icon>${label}</button>`)
      .join("") + `</div>`;
  }

  _render() {
    const s = this._state();
    if (!this._root) {
      this._root = document.createElement("ha-card");
      this._root.className = "ga-thermostat";
      const style = document.createElement("style");
      style.textContent = STYLE;
      this.appendChild(style);
      this.appendChild(this._root);
    }
    if (!s) {
      this._root.innerHTML = `<div class="ga-body off">Thermostat nicht verfügbar</div>`;
      return;
    }
    const header = this._config.header || "Steuerung";
    if (this._variant === "dial") this._renderDial(s, header);
    else if (this._variant === "setpoint") this._renderSetpoint(s, header);
    else this._renderClassic(s, header);
    this._wireCommon();
    if (this._variant === "dial") this._wireDial(s);
  }

  _renderClassic(s, header) {
    const cur = s.attributes.current_temperature;
    const target = s.attributes.temperature;
    const heating = s.state !== "off";
    const curTxt = cur != null ? `${Number(cur).toFixed(1)}<small> °C</small>` : "–";
    const setRow = (target != null && heating)
      ? `<div class="set"><button data-delta="-1" aria-label="kälter">−</button>` +
        `<div class="target">${Number(target).toFixed(1)} °C</div>` +
        `<button data-delta="1" aria-label="wärmer">+</button></div>`
      : "";
    this._root.innerHTML = `<div class="ga-body"><div class="hdr">${header}${this._actionBadge(s)}</div>` +
      `<div class="val">${curTxt}</div>${setRow}${this._modeRow(s)}</div>`;
  }

  _renderSetpoint(s, header) {
    const cur = s.attributes.current_temperature;
    const target = s.attributes.temperature;
    const heating = s.state !== "off";
    const body = heating
      ? `<div class="cur">aktuell ${cur != null ? Number(cur).toFixed(1) : "–"} °C</div>` +
        `<div class="big"><button data-delta="-1">−</button>` +
        `<div class="t">${target != null ? Number(target).toFixed(1) : "–"}<small> °C</small></div>` +
        `<button data-delta="1">+</button></div>`
      : `<div class="offmsg">Heizung aus</div>`;
    this._root.innerHTML = `<div class="ga-body sp"><div class="hdr">${header}${this._actionBadge(s)}</div>${body}${this._modeRow(s)}</div>`;
  }

  _renderDial(s, header) {
    this._root.innerHTML = `<div class="ga-body dl"><div class="hdr">${header}${this._actionBadge(s)}</div>` +
      `<div class="dialwrap">${this._dialSVG(s)}</div>${this._modeRow(s)}</div>`;
  }

  // --- dial helpers ---
  _angle(s, t) {
    const min = Number(s.attributes.min_temp) || 5, max = Number(s.attributes.max_temp) || 30;
    return DIAL.start + ((t - min) / (max - min)) * DIAL.sweep;
  }
  _pt(deg, r) { const a = deg * Math.PI / 180; return [DIAL.c + r * Math.sin(a), DIAL.c - r * Math.cos(a)]; }
  _arc(a0, a1, r) {
    const [x0, y0] = this._pt(a0, r), [x1, y1] = this._pt(a1, r);
    const large = (a1 - a0) > 180 ? 1 : 0;
    return `M${x0.toFixed(1)} ${y0.toFixed(1)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }
  /**
   * What the heating is DOING right now — read, not guessed.
   *
   * `hvac_action` is the thermostat's own answer and Home Assistant keeps it
   * current; it is the only source here that can tell "the valve is open" from
   * "the target is above the room". Those differ in practice: a valve holds
   * `idle` with a target above the room when a window contact is open or the
   * valve is closed, and reports `heating` at equal temperatures while it
   * catches up. The comparison this used to make gets both of those wrong, and
   * it gets them wrong silently.
   *
   * The comparison survives as a FALLBACK for a thermostat that publishes no
   * `hvac_action` at all, and it is marked as an inference so the caller can
   * word it less definitely. Guessing is acceptable; presenting a guess as a
   * reading is not.
   */
  _action(s) {
    if (s.state === "off") return { key: "off", label: "Aus", inferred: false };
    const action = s.attributes.hvac_action;
    if (action === "heating") return { key: "heating", label: "Heizt", inferred: false };
    if (action === "idle") return { key: "idle", label: "Bereit", inferred: false };
    if (action === "off") return { key: "off", label: "Aus", inferred: false };
    const cur = s.attributes.current_temperature, t = s.attributes.temperature;
    if (cur != null && t != null) {
      return Number(t) > Number(cur)
        ? { key: "heating", label: "Heizt", inferred: true }
        : { key: "idle", label: "Bereit", inferred: true };
    }
    return { key: "unknown", label: "", inferred: true };
  }

  /** The badge every variant shows. Empty string when there is nothing to say. */
  _actionBadge(s) {
    const a = this._action(s);
    if (!a.label) return "";
    const title = a.inferred
      ? ' title="abgeleitet aus Soll und Ist — dieses Thermostat meldet seinen Betriebszustand nicht"'
      : "";
    return `<span class="act act-${a.key}"${title}>${a.label}</span>`;
  }

  _actionLabel(s) { return this._action(s).label; }
  _dialSVG(s) {
    const heating = s.state !== "off";
    const target = Number(s.attributes.temperature), cur = s.attributes.current_temperature;
    const ang = heating && !Number.isNaN(target) ? this._angle(s, target) : DIAL.start;
    const [kx, ky] = this._pt(ang, DIAL.r);
    const col = heating ? "var(--ga-heat, #ff8a3d)" : "var(--secondary-text-color, #888)";
    return `<svg class="dial" viewBox="0 0 ${DIAL.size} ${DIAL.size}">` +
      `<path class="track" d="${this._arc(DIAL.start, DIAL.start + DIAL.sweep, DIAL.r)}" fill="none" stroke="var(--divider-color,#e0e0e0)" stroke-width="12" stroke-linecap="round"/>` +
      `<path class="prog" d="${this._arc(DIAL.start, ang, DIAL.r)}" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round"/>` +
      `<circle class="knob" cx="${kx.toFixed(1)}" cy="${ky.toFixed(1)}" r="9" fill="#fff" stroke="${col}" stroke-width="2"/>` +
      `<text class="d-act" x="${DIAL.c}" y="${DIAL.c - 16}" text-anchor="middle">${this._actionLabel(s)}</text>` +
      `<text class="d-tgt" x="${DIAL.c}" y="${DIAL.c + 10}" text-anchor="middle">${heating && !Number.isNaN(target) ? Number(target).toFixed(1) : "–"}</text>` +
      `<text class="d-cur" x="${DIAL.c}" y="${DIAL.c + 30}" text-anchor="middle">${cur != null ? Number(cur).toFixed(1) + " °C" : ""}</text>` +
      `</svg>`;
  }
  _wireDial(s) {
    const dial = this._root.querySelector("svg.dial");
    if (!dial || s.state === "off") return;
    const step = this._step(s);
    const min = Number(s.attributes.min_temp) || 5, max = Number(s.attributes.max_temp) || 30;
    const toTemp = (ev) => {
      const r = dial.getBoundingClientRect();
      const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) * DIAL.size / r.width - DIAL.c;
      const py = ((ev.touches ? ev.touches[0].clientY : ev.clientY) - r.top) * DIAL.size / r.height - DIAL.c;
      let deg = Math.atan2(px, -py) * 180 / Math.PI;
      deg = Math.max(DIAL.start, Math.min(DIAL.start + DIAL.sweep, deg));
      return this._clamp(s, Math.round((min + ((deg - DIAL.start) / DIAL.sweep) * (max - min)) / step) * step);
    };
    // Redraw the arc/knob/target LIVE while dragging; commit to the device only
    // on release (so a zigbee TRV is not spammed on every pointermove).
    const live = (t) => {
      const ang = this._angle(s, t), [kx, ky] = this._pt(ang, DIAL.r);
      dial.querySelector(".prog").setAttribute("d", this._arc(DIAL.start, ang, DIAL.r));
      const k = dial.querySelector(".knob");
      k.setAttribute("cx", kx.toFixed(1)); k.setAttribute("cy", ky.toFixed(1));
      dial.querySelector(".d-tgt").textContent = Number(t).toFixed(1);
    };
    dial.addEventListener("pointerdown", (e) => { this._dragging = true; dial.setPointerCapture(e.pointerId); live(toTemp(e)); });
    dial.addEventListener("pointermove", (e) => { if (this._dragging) live(toTemp(e)); });
    const end = (e) => { if (!this._dragging) return; this._dragging = false; this._commitTemp(toTemp(e)); };
    dial.addEventListener("pointerup", end);
    dial.addEventListener("pointercancel", end);
  }

  /**
   * One listener on the root, bound once, instead of one per button per render.
   *
   * The second cause of lost presses: `_render()` rebuilds the card with
   * `innerHTML`, so every re-render throws away the button a press may already
   * be travelling to — the press then lands on a node that is no longer in the
   * document and does nothing ("Element is not attached to the DOM", observed
   * while driving the card on 2026-09-16). Re-binding faster does not fix it;
   * not depending on the element's identity does.
   *
   * The root survives every re-render, so a listener here cannot be detached
   * mid-click, and rendering no longer has to re-wire anything.
   */
  _wireCommon() {
    if (this._wired) return;
    this._wired = true;
    this._root.addEventListener("click", (ev) => {
      const target = ev.target && ev.target.closest && ev.target.closest(
        ".set button, .big button, .modes .m");
      if (!target || !this._root.contains(target)) return;
      if (target.dataset.mode) {
        this._setMode(target.dataset.mode);
      } else if (target.dataset.delta) {
        this._setTemp(Number(target.dataset.delta));
      }
    });
  }
}

customElements.define("ga-thermostat-card", GaThermostatCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-thermostat-card",
  name: "GA Thermostat Card",
  description: "Resident heating control (AUS/MANUEL/KI + setpoint) — first-party, variant: classic|dial|setpoint.",
});
