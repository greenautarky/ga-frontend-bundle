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

/* ─── the day curve ───────────────────────────────────────────────────────
 *
 * 24 bars, each the setpoint in force in that hour. It used to carry the hour
 * in exactly one place: `title="06:00 · 21 °C"` on the bar — a HOVER TOOLTIP.
 * There is no hover on a phone, so on the device residents actually use, the
 * time axis did not exist and the bars were an abstract shape.
 *
 * Fixed with the cheapest thing that works: four labels under the curve (0, 6,
 * 12, 18, 24) and the value on TAP. Not a charting library — a resident needs
 * to see "warm in the morning, cool at night", not read off a value at 14:30.
 *
 * Kept as pure functions above the element on purpose: this is the part that
 * was wrong, and a function returning a value can be asserted on. A method
 * that assigns `innerHTML` can only be asserted on by grepping its source,
 * which is how "the hour is in an attribute" passed every check for months.
 * ------------------------------------------------------------------------- */

/** The hours the axis is labelled at. Midnight is shown at both ends. */
const AXIS_HOURS = [0, 6, 12, 18, 24];

/* --- five slots, always ----------------------------------------------------
 * The scheduler used to start EMPTY: `days` came back with no slots and the
 * only way in was "+ Zeit hinzufügen". A resident opening a fresh flat saw an
 * empty week and a blank curve, and had to invent a plan before the card could
 * show one. Decided 2026-09-23: exactly five slots per day, always present.
 *
 * Five is not a round number somebody liked. The canonical table the
 * installation has used since 2026-06 —
 * `ha-dashboard-automation/scripts/apply_default_profile_schedule.py` — has
 * exactly five entries per day per room (living room on working days:
 * 00:00=17, 09:00=19, 18:00=20, 22:00=17, 23:00=17).
 *
 * WHAT THE PADDING MUST NOT DO is invent a temperature. A number the card made
 * up looks exactly like one the resident chose, and on 2026-09-23 an invented
 * default table reached a converge step before it was caught. So a padded slot
 * takes the temperature ALREADY IN FORCE at that time of day, from whatever the
 * plan already says; with nothing to derive from it takes the thermostat's
 * current target, which is a real value the resident can see on the card above.
 */
const SLOTS_PER_DAY = 5;
/** The times a padded slot takes, in order, skipping any the day already has. */
const SLOT_LADDER = ["00:00", "06:00", "09:00", "18:00", "22:00", "23:00"];

/** The setpoint in force at `hhmm` per `slots`, wrapping midnight — or null. */
function tempAt(slots, hhmm) {
  const list = slots || [];
  if (!list.length) return null;
  const sorted = [...list].sort((a, b) => a.time.localeCompare(b.time));
  const passed = sorted.filter((x) => x.time <= hhmm);
  return passed.length ? passed[passed.length - 1].temp : sorted[sorted.length - 1].temp;
}

/**
 * `slots` grown to exactly SLOTS_PER_DAY, or returned untouched when it already
 * has that many or MORE.
 *
 * A day carrying more than five is NOT trimmed. Dropping a slot a resident
 * entered would be a silent loss of their plan, and the card would look like it
 * had merely tidied up. It says so instead (see `_render`).
 *
 * `fallback` is used only when there is nothing at all to derive from.
 */
function padDay(slots, fallback) {
  const list = [...(slots || [])];
  if (list.length >= SLOTS_PER_DAY) return list;
  for (const time of SLOT_LADDER) {
    if (list.length >= SLOTS_PER_DAY) break;
    if (list.some((x) => x.time === time)) continue;
    const t = tempAt(list, time);
    list.push({ time, temp: t != null ? t : fallback });
  }
  list.sort((a, b) => a.time.localeCompare(b.time));
  return list;
}

function curveAxisLabels() {
  return AXIS_HOURS.map(String);
}

/** `[{h, t, pct}]` — one entry per hour of the day, or [] with no slots. */
function curveModel(slots) {
  const list = slots || [];
  if (!list.length) return [];
  const bars = [];
  for (let h = 0; h < 24; h++) {
    const hm = `${String(h).padStart(2, "0")}:59`;
    const passed = list.filter((s) => s.time <= hm);
    // Before the day's first slot the plan wraps from the previous day's last.
    const t = passed.length ? passed[passed.length - 1].temp : list[list.length - 1].temp;
    const pct = Math.max(6, Math.round(((t - TMIN) / (TMAX - TMIN)) * 100));
    bars.push({ h, t, pct });
  }
  return bars;
}

/** The bar markup. `data-h`/`data-t` are what the tap readout reads. */
function curveHtml(slots) {
  return curveModel(slots)
    .map(
      (b) =>
        `<div style="height:${b.pct}%" data-h="${b.h}" data-t="${b.t}"` +
        ` title="${String(b.h).padStart(2, "0")}:00 · ${b.t} °C"></div>`,
    )
    .join("");
}

/** The axis markup. Element TEXT, not attributes — a phone can read this. */
function curveAxisHtml(slots) {
  if (!(slots || []).length) return "";
  return curveAxisLabels()
    .map((label) => `<span>${label}</span>`)
    .join("");
}

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
      this._padded = this._normalise();
      // `_dirty` stays false: padding is a PROPOSAL, not an edit the resident
      // made. Marking it dirty would arm Save on a plan nobody touched, and the
      // next press would write five slots the resident never looked at.
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

  /** The thermostat's own target — a real number on screen, not an invention. */
  _fallbackTemp() {
    const st = this._hass && this._hass.states && this._hass.states[this._config.entity];
    const t = st && st.attributes && Number(st.attributes.temperature);
    return Number.isFinite(t) && t >= TMIN && t <= TMAX ? t : null;
  }

  /** Grow every day to five slots. Returns the days that were padded. */
  _normalise() {
    const fb = this._fallbackTemp();
    const padded = [];
    for (const [d] of DAYS) {
      const before = (this._week[d] || []).length;
      if (before >= SLOTS_PER_DAY) continue;
      if (before === 0 && fb == null) continue;   // nothing to derive from: leave it
      this._week[d] = padDay(this._week[d], fb);
      if (this._week[d].length !== before) padded.push(d);
    }
    return padded;
  }

  // ─── editing (local until saved) ────────────────────────────────────────
  _slots() { return this._week[this._day] || []; }
  _sort() { this._week[this._day].sort((a, b) => a.time.localeCompare(b.time)); }

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
          <div class="axis"></div>
          <div class="readout"></div>
          <div class="actions">
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
        ga-heating-card .curve { display:flex; align-items:flex-end; gap:2px; height:56px; margin:14px 0 4px;
          border-bottom:1px solid var(--divider-color,#e0e0e0); }
        ga-heating-card .curve div { flex:1; background: var(--primary-color,#03a9f4); opacity:.35; border-radius:2px 2px 0 0;
          cursor:pointer; }
        ga-heating-card .curve div.on { opacity:.85; }
        ga-heating-card .axis { display:flex; justify-content:space-between; font-size:.75em; opacity:.65;
          margin:2px 0 0; font-variant-numeric:tabular-nums; }
        ga-heating-card .axis span:first-child { margin-left:-2px; }
        ga-heating-card .axis span:last-child { margin-right:-2px; }
        ga-heating-card .readout { min-height:1.25em; font-size:.85em; margin-top:4px; opacity:.8; }
        ga-heating-card .empty { opacity:.6; font-size:.9em; padding:8px 0; }
        ga-heating-card .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }
        ga-heating-card .btn { font-family:inherit; font-size:.9em; font-weight:600; padding:8px 14px; border:none;
          border-radius:20px; cursor:pointer; background: var(--secondary-background-color,#e8e8e8);
          color: var(--primary-text-color,#212121); }
        ga-heating-card .btn.primary { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-card .btn:disabled { opacity:.45; cursor:default; }
      </style>`;

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
          </div>`).join("")
      : '<div class="empty">Dieser Tag hat noch keinen Plan, und das Thermostat meldet gerade keine Zieltemperatur — '
        + 'sobald es eine meldet, stehen hier fünf Zeiten. Ohne Plan bleibt die Temperatur, wie du sie eingestellt hast.</div>';

    slots.querySelectorAll("input").forEach((el) => {
      el.addEventListener("change", () => this._set(+el.dataset.i, el.dataset.f, el.value));
    });

    // A day at a glance: 24 bars, each the setpoint in force in that hour,
    // with a readable time axis under them and the value on tap. See the
    // curve* functions at the top of this file for why that is not cosmetic.
    const curve = this.querySelector(".curve");
    const axis = this.querySelector(".axis");
    const readout = this.querySelector(".readout");
    curve.innerHTML = curveHtml(list);
    axis.innerHTML = curveAxisHtml(list);
    readout.textContent = "";
    curve.querySelectorAll("div").forEach((bar) => {
      bar.addEventListener("click", () => {
        curve.querySelectorAll("div.on").forEach((b) => b.classList.remove("on"));
        bar.classList.add("on");
        readout.textContent =
          `${String(bar.dataset.h).padStart(2, "0")}:00 – ` +
          `${String((+bar.dataset.h + 1) % 24).padStart(2, "0")}:00 · ${bar.dataset.t} °C`;
      });
    });

    this.querySelector(".save").disabled = !this._dirty;

    // Two things the resident must not have to guess. Only shown while nothing
    // has been edited, so it never sits on top of a save result.
    if (!this._dirty) {
      if (list.length > SLOTS_PER_DAY) {
        this._flash("ok", `Dieser Tag hat ${list.length} Zeiten — mehr als die fünf, die hier angeboten werden. `
          + `Sie bleiben erhalten; nichts wird entfernt.`);
      }
      // NO "this is only a proposal, press Save" message. gm writes the default
      // plan on converge, so five slots is what a room HAS — telling a resident
      // to save a plan that was set up for them is an instruction to fix
      // something that is not broken. (Thomas, 2026-09-23.)
    }
  }
}

customElements.define("ga-heating-card", GaHeatingCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-heating-card",
  name: "GreenAutarky — Heizplan",
  description: "Wochenplan für ein beliebiges Thermostat (climate.*). Wird vom Gerät ausgeführt.",
});
