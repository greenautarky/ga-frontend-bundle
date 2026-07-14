/**
 * ga-heating-card — weekly heating plan, for any thermostat.
 *
 * Talks ONLY to the ga_heating component (`/api/ga_heating/schedule`). It never
 * touches a device's own schedule format: the Zigbee TRV's
 * `text.<id>_weekly_schedule_<day>` is Tuya-shaped, write-only (reads back as None)
 * and exists on one product line. The plan lives with us and is executed by calling
 * `climate.set_temperature` — the service every thermostat implements. Same card,
 * same backend, any hardware.
 *
 * A resident (Non-Admin) can use this: our endpoint is a plain authenticated HTTP
 * view, and the executor runs in Core. No Settings access, no admin rights, no
 * add-on, no third-party card.
 *
 * Config:
 *   type: custom:ga-heating-card
 *   entity: climate.wohnzimmer
 *   title: Wohnzimmer
 */

const DAYS = [
  ["monday", "Mo"], ["tuesday", "Di"], ["wednesday", "Mi"], ["thursday", "Do"],
  ["friday", "Fr"], ["saturday", "Sa"], ["sunday", "So"],
];
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"];
const TMIN = 5, TMAX = 30;

class GaHeatingCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity || !config.entity.startsWith("climate.")) {
      throw new Error("ga-heating-card: 'entity' muss eine climate.* Entity sein");
    }
    this._config = config;
    this._day = DAYS[new Date().getDay() === 0 ? 6 : new Date().getDay() - 1][0];
    this._week = null;   // {monday: [{time,temp}], …} — the whole week, edited locally
    this._dirty = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._build();
      this._load();
    }
  }

  getCardSize() { return 7; }

  // ─── backend ────────────────────────────────────────────────────────────
  async _load() {
    try {
      const r = await this._hass.callApi(
        "get", `ga_heating/schedule?entity_id=${encodeURIComponent(this._config.entity)}`);
      this._week = r.days || {};
      for (const [d] of DAYS) this._week[d] = this._week[d] || [];
      this._dirty = false;
      this._render();
    } catch (e) {
      this._flash("err", "Plan konnte nicht geladen werden.");
    }
  }

  async _save() {
    try {
      await this._hass.callApi("post", "ga_heating/schedule",
        { entity_id: this._config.entity, days: this._week });
      this._dirty = false;
      this._render();
      this._flash("ok", "Heizplan gespeichert — er gilt ab sofort.");
    } catch (e) {
      this._flash("err", "Speichern fehlgeschlagen.");
    }
  }

  // ─── editing (local until saved) ────────────────────────────────────────
  _slots() { return this._week[this._day] || []; }
  _sort() { this._week[this._day].sort((a, b) => a.time.localeCompare(b.time)); }

  _add() {
    this._week[this._day].push({ time: "12:00", temp: 21 });
    this._sort(); this._dirty = true; this._render();
  }
  _remove(i) {
    this._week[this._day].splice(i, 1);
    this._dirty = true; this._render();
  }
  _set(i, field, value) {
    const s = this._week[this._day][i];
    if (field === "time") s.time = value;
    else s.temp = Math.min(TMAX, Math.max(TMIN, parseFloat(value) || 20));
    this._sort(); this._dirty = true; this._render();
  }
  _copyTo(days) {
    const src = JSON.parse(JSON.stringify(this._slots()));
    for (const d of days) this._week[d] = JSON.parse(JSON.stringify(src));
    this._dirty = true; this._render();
    this._flash("ok", `Übernommen auf ${days.length} Tage — noch nicht gespeichert.`);
  }

  // ─── UI ─────────────────────────────────────────────────────────────────
  _flash(kind, text) {
    const m = this.querySelector(".msg");
    if (!m) return;
    m.className = "msg " + kind;
    m.textContent = text;
    clearTimeout(this._t);
    this._t = setTimeout(() => { m.className = "msg"; }, 4000);
  }

  _build() {
    this.innerHTML = `
      <ha-card header="${this._config.title || "Heizplan"}">
        <div class="card-content">
          <div class="msg"></div>
          <div class="days"></div>
          <div class="slots"></div>
          <div class="curve"></div>
          <div class="actions">
            <button class="btn add">+ Zeit hinzufügen</button>
            <button class="btn copy-week">Auf Mo–Fr übernehmen</button>
            <button class="btn copy-all">Auf alle Tage</button>
            <button class="btn primary save">Speichern</button>
          </div>
        </div>
      </ha-card>
      <style>
        ga-heating-card .card-content { padding: 16px; }
        ga-heating-card .msg { display:none; padding:8px 10px; border-radius:8px; margin-bottom:10px; font-size:.9em; }
        ga-heating-card .msg.ok { display:block; background: rgba(76,175,80,.15); color: var(--success-color,#1d7a3a); }
        ga-heating-card .msg.err { display:block; background: rgba(244,67,54,.15); color: var(--error-color,#c0392b); }
        ga-heating-card .days { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px; }
        ga-heating-card .day { flex:1; min-width:40px; padding:8px 0; text-align:center; border-radius:10px;
          cursor:pointer; font-weight:600; font-size:.9em; background: var(--secondary-background-color,#e8e8e8); }
        ga-heating-card .day.on { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-card .day.has::after { content:"·"; display:block; line-height:0; font-size:1.6em; opacity:.6; }
        ga-heating-card .slot { display:flex; gap:8px; align-items:center; margin:6px 0; }
        ga-heating-card .slot input[type=time] { flex:0 0 110px; }
        ga-heating-card .slot input[type=number] { flex:0 0 90px; }
        ga-heating-card .slot .unit { opacity:.6; font-size:.9em; }
        ga-heating-card input { font-family:inherit; font-size:1em; padding:6px 8px; border-radius:8px;
          border:1px solid var(--divider-color,#e0e0e0); background: var(--card-background-color,#fff);
          color: var(--primary-text-color,#212121); }
        ga-heating-card .rm { border:none; background:none; cursor:pointer; color: var(--error-color,#c0392b); font-size:1.2em; }
        ga-heating-card .curve { display:flex; align-items:flex-end; gap:2px; height:56px; margin:14px 0 4px;
          border-bottom:1px solid var(--divider-color,#e0e0e0); }
        ga-heating-card .curve div { flex:1; background: var(--primary-color,#03a9f4); opacity:.35; border-radius:2px 2px 0 0; }
        ga-heating-card .empty { opacity:.6; font-size:.9em; padding:8px 0; }
        ga-heating-card .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }
        ga-heating-card .btn { font-family:inherit; font-size:.9em; font-weight:600; padding:8px 14px; border:none;
          border-radius:20px; cursor:pointer; background: var(--secondary-background-color,#e8e8e8);
          color: var(--primary-text-color,#212121); }
        ga-heating-card .btn.primary { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-card .btn:disabled { opacity:.45; cursor:default; }
      </style>`;

    this.querySelector(".add").addEventListener("click", () => this._add());
    this.querySelector(".copy-week").addEventListener("click", () => this._copyTo(WEEKDAYS));
    this.querySelector(".copy-all").addEventListener("click", () => this._copyTo(DAYS.map((d) => d[0])));
    this.querySelector(".save").addEventListener("click", () => this._save());
  }

  _render() {
    if (!this._week) return;

    const days = this.querySelector(".days");
    days.innerHTML = DAYS.map(([id, label]) => {
      const has = (this._week[id] || []).length ? " has" : "";
      return `<div class="day${id === this._day ? " on" : ""}${has}" data-day="${id}">${label}</div>`;
    }).join("");
    days.querySelectorAll(".day").forEach((el) => {
      el.addEventListener("click", () => { this._day = el.dataset.day; this._render(); });
    });

    const slots = this.querySelector(".slots");
    const list = this._slots();
    slots.innerHTML = list.length
      ? list.map((s, i) => `
          <div class="slot">
            <input type="time" value="${s.time}" data-i="${i}" data-f="time">
            <input type="number" min="${TMIN}" max="${TMAX}" step="0.5" value="${s.temp}" data-i="${i}" data-f="temp">
            <span class="unit">°C</span>
            <button class="rm" data-i="${i}" title="Entfernen">✕</button>
          </div>`).join("")
      : '<div class="empty">Für diesen Tag ist noch keine Zeit hinterlegt. Ohne Plan bleibt die Temperatur, wie du sie eingestellt hast.</div>';

    slots.querySelectorAll("input").forEach((el) => {
      el.addEventListener("change", () => this._set(+el.dataset.i, el.dataset.f, el.value));
    });
    slots.querySelectorAll(".rm").forEach((el) => {
      el.addEventListener("click", () => this._remove(+el.dataset.i));
    });

    // A day at a glance: 24 bars, each the setpoint in force in that hour.
    const curve = this.querySelector(".curve");
    if (list.length) {
      const bars = [];
      for (let h = 0; h < 24; h++) {
        const hm = `${String(h).padStart(2, "0")}:59`;
        const passed = list.filter((s) => s.time <= hm);
        const t = passed.length ? passed[passed.length - 1].temp : list[list.length - 1].temp;
        const pct = Math.max(6, Math.round(((t - TMIN) / (TMAX - TMIN)) * 100));
        bars.push(`<div style="height:${pct}%" title="${String(h).padStart(2, "0")}:00 · ${t} °C"></div>`);
      }
      curve.innerHTML = bars.join("");
    } else {
      curve.innerHTML = "";
    }

    this.querySelector(".save").disabled = !this._dirty;
  }
}

customElements.define("ga-heating-card", GaHeatingCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-heating-card",
  name: "GreenAutarky — Heizplan",
  description: "Wochenplan für ein beliebiges Thermostat (climate.*). Wird vom Gerät ausgeführt.",
});
