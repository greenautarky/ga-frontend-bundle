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
 *   title: Wohnzimmer            # optional, DEFAULT NONE. The card ships no
 *                                # header: the view puts a "Heizplan" heading
 *                                # above it and the tab is the room, so a
 *                                # header inside would be a third telling.
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

//: Plan times sit on the half hour. `step="1800"` makes the picker move that
//: way, but a resident can still type 06:14 and a phone's own picker ignores
//: step entirely — so the value is snapped HERE, where every edit passes,
//: rather than trusted from the input.
const SNAP_MINUTES = 30;

/** A time on the 30-minute grid, or null when it is not a time at all. */
function snapTime(value) {
  const m = /^(\d{1,2}):(\d{2})/.exec(String(value || ""));
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  if (!(h >= 0 && h <= 23 && mi >= 0 && mi <= 59)) return null;
  let snapped = Math.round(mi / SNAP_MINUTES) * SNAP_MINUTES;
  let hour = h;
  if (snapped === 60) {
    // 23:45 rounds UP to tomorrow. Rounding it there would move the slot to the
    // start of this day and reorder the plan under the resident's hands, so the
    // last half hour of the day rounds down instead.
    if (hour === 23) snapped = 30;
    else { snapped = 0; hour += 1; }
  }
  return `${String(hour).padStart(2, "0")}:${String(snapped).padStart(2, "0")}`;
}

/**
 * What this day looks like against the one that is SAVED.
 *
 * Index by index, both lists sorted by time, because that is how a resident
 * reads them: the third row is the third row. A row whose time moved past its
 * neighbour therefore reports as two changes rather than a reorder — correct
 * enough, and the alternative (matching rows up by nearest time) guesses at an
 * intent nobody expressed.
 *
 * `null` for a field means unchanged. `added` is a row the saved day does not
 * have at all; `removed` counts rows the saved day had and this one no longer
 * does, which nothing else on screen would otherwise mention.
 */
function dayDiff(now, saved) {
  const a = now || [];
  const b = saved || [];
  const rows = a.map((s, i) => {
    const was = b[i];
    if (!was) return { added: true, time: null, temp: null };
    return {
      added: false,
      time: was.time === s.time ? null : was.time,
      temp: Number(was.temp) === Number(s.temp) ? null : was.temp,
    };
  });
  return { rows, removed: Math.max(0, b.length - a.length) };
}

/** True when any day of the week differs from the saved one. */
function changedDays(week, saved) {
  const out = [];
  for (const [id] of DAYS) {
    const d = dayDiff((week || {})[id], (saved || {})[id]);
    if (d.removed || d.rows.some((r) => r.added || r.time || r.temp)) out.push(id);
  }
  return out;
}

/**
 * The bar markup. `data-h`/`data-t` are what the tap readout reads.
 *
 * With a `saved` day the hour also carries the setpoint it has TODAY, drawn as
 * a faint outline behind the new bar: the comparison a resident actually wants
 * is "warmer or colder than now", and two numbers in a list answer that far
 * worse than two heights in the same column.
 */
function curveHtml(slots, saved) {
  const was = saved ? curveModel(saved) : [];
  return curveModel(slots)
    .map((b) => {
      const w = was[b.h];
      const ghost = w && w.t !== b.t
        ? `<i style="height:${w.pct}%" title="jetzt ${w.t} °C"></i>`
        : "";
      return `<div style="height:${b.pct}%" data-h="${b.h}" data-t="${b.t}"` +
        ` title="${String(b.h).padStart(2, "0")}:00 · ${b.t} °C">${ghost}</div>`;
    })
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
      // The plan AS IT STANDS, kept so every later render can say what an edit
      // changed. Copied after padding, because padding is this card proposing
      // rows rather than the resident changing anything (see `_dirty` below) —
      // taken before it, every padded row would show up as an edit nobody made.
      this._saved = JSON.parse(JSON.stringify(this._week));
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
      // What was just written IS the plan now; nothing is pending any more.
      this._saved = JSON.parse(JSON.stringify(this._week));
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
  /** Back to the saved plan, every day of it. */
  _discard() {
    if (!this._saved) return;
    this._week = JSON.parse(JSON.stringify(this._saved));
    this._dirty = false;
    this._render();
    this._flash("ok", "Änderungen verworfen — der gespeicherte Plan gilt weiter.");
  }

  _slots() { return this._week[this._day] || []; }
  _sort() { this._week[this._day].sort((a, b) => a.time.localeCompare(b.time)); }

  _set(i, field, value) {
    const s = this._week[this._day][i];
    if (field === "time") {
      const t = snapTime(value);
      if (t === null) return;  // not a time: leave the plan as it was
      s.time = t;
    }
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

  //: No header unless a config asks for one (2026-09-30). It used to be the room
  //: name, under a "Heizplan" heading, in a tab named after the room — the same
  //: thing three times. Defaulting to "Heizplan" instead only moved the
  //: duplication one line up, so the default is nothing at all.
  _header() {
    const title = this._config.title ?? "";
    return title ? ` header="${title}"` : "";
  }

  _build() {
    this.innerHTML = `
      <ha-card${this._header()}>
        <div class="card-content">
          <div class="msg"></div>
          <div class="pending"></div>
          <div class="days"></div>
          <div class="slots"></div>
          <div class="curve"></div>
          <div class="axis"></div>
          <div class="readout"></div>
          <div class="actions">
            <button class="btn copy-week">Auf Mo–Fr übernehmen</button>
            <button class="btn copy-all">Auf alle Tage</button>
            <button class="btn discard">Verwerfen</button>
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
        /* The row holds a time, a temperature and "jetzt …" — on a phone, in a
           card that is already one of three in a column. The inputs take only
           what they need to show their own value, and the note gets the rest and
           wraps underneath rather than pushing the row out of the card. */
        ga-heating-card .slot { display:flex; gap:6px; align-items:center; margin:6px 0;
          flex-wrap:wrap; }
        ga-heating-card .slot input[type=time] { flex:0 0 96px; }
        ga-heating-card .slot input[type=number] { flex:0 0 68px; }
        ga-heating-card .slot .unit { opacity:.6; font-size:.9em; }
        /* An edited row, and what it still is on the thermostat. The accent is
           the one the theme already uses for "you changed this" (--ga-heat). */
        ga-heating-card .slot input.changed { border-color: var(--ga-heat,#ff8a3d);
          box-shadow: inset 0 0 0 1px var(--ga-heat,#ff8a3d); }
        ga-heating-card .slot .was { font-size:.8em; opacity:.65; white-space:nowrap;
          flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; }
        ga-heating-card .pending { display:none; font-size:.85em; margin-bottom:10px;
          padding:6px 10px; border-radius:8px; background: rgba(255,138,61,.14);
          color: var(--ga-heat,#b35f1b); }
        ga-heating-card .pending.on { display:block; }
        ga-heating-card .day.edited { box-shadow: inset 0 0 0 2px var(--ga-heat,#ff8a3d); }
        ga-heating-card .removed { font-size:.85em; opacity:.7; margin-top:4px; }
        ga-heating-card input { font-family:inherit; font-size:1em; padding:6px 6px; border-radius:8px;
          box-sizing:border-box; width:100%;
          border:1px solid var(--divider-color,#e0e0e0); background: var(--card-background-color,#fff);
          color: var(--primary-text-color,#212121); }
        ga-heating-card .curve { display:flex; align-items:flex-end; gap:2px; height:56px; margin:14px 0 4px;
          border-bottom:1px solid var(--divider-color,#e0e0e0); }
        ga-heating-card .curve div { flex:1; background: var(--primary-color,#03a9f4); opacity:.35; border-radius:2px 2px 0 0;
          cursor:pointer; }
        ga-heating-card .curve div.on { opacity:.85; }
        /* The hour as it stands TODAY, behind the edited bar: the comparison a
           resident wants is "warmer or colder than now", and two heights in one
           column answer that better than two numbers in a list. */
        ga-heating-card .curve div { position:relative; }
        ga-heating-card .curve div i { position:absolute; left:0; right:0; bottom:0;
          border-top:2px dashed var(--ga-heat,#ff8a3d); opacity:.85; }
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
    this.querySelector(".discard").addEventListener("click", () => this._discard());
  }

  _render() {
    if (!this._week) return;

    const days = this.querySelector(".days");
    // A day carrying unsaved edits is marked in the strip: the resident edits one
    // day at a time and Save writes the whole WEEK, so "what am I about to send"
    // cannot be answered by the day on screen alone.
    const edited = changedDays(this._week, this._saved);
    days.innerHTML = DAYS.map(([id, label]) => {
      const has = (this._week[id] || []).length ? " has" : "";
      const ed = edited.includes(id) ? " edited" : "";
      return `<div class="day${id === this._day ? " on" : ""}${has}${ed}" data-day="${id}">${label}</div>`;
    }).join("");
    days.querySelectorAll(".day").forEach((el) => {
      el.addEventListener("click", () => { this._day = el.dataset.day; this._render(); });
    });

    const slots = this.querySelector(".slots");
    const list = this._slots();
    // Every row says what it IS and, when that differs, what it still is on the
    // thermostat — "jetzt 18,0". Without it a resident editing a plan is asked
    // to remember the number they just overwrote (asked for 2026-10-02).
    const diff = dayDiff(list, (this._saved || {})[this._day]);
    slots.innerHTML = list.length
      ? list.map((s, i) => {
          const d = diff.rows[i] || {};
          const mark = (f) => (d.added || d[f] != null ? " changed" : "");
          // ONE label, not one per field: "jetzt 00:00 · 17 °C" says the same as
          // two badges in half the width, and the row has to hold a time, a
          // temperature and this on a phone (asked for 2026-10-02).
          const parts = [];
          if (d.time != null) parts.push(d.time);
          if (d.temp != null) parts.push(`${d.temp} °C`);
          const was = d.added
            ? '<span class="was">neu</span>'
            : parts.length ? `<span class="was">jetzt ${parts.join(" · ")}</span>` : "";
          return `
          <div class="slot${d.added || parts.length ? " edited" : ""}">
            <input type="time" step="${SNAP_MINUTES * 60}" class="t${mark("time")}" value="${s.time}" data-i="${i}" data-f="time">
            <input type="number" class="v${mark("temp")}" min="${TMIN}" max="${TMAX}" step="0.5" value="${s.temp}" data-i="${i}" data-f="temp">
            <span class="unit">°C</span>${was}
          </div>`;
        }).join("")
      : '<div class="empty">Dieser Tag hat noch keinen Plan, und das Thermostat meldet gerade keine Zieltemperatur — '
        + 'sobald es eine meldet, stehen hier fünf Zeiten. Ohne Plan bleibt die Temperatur, wie du sie eingestellt hast.</div>';

    // Rows the saved day has and this one no longer does. Nothing else on
    // screen would mention them: they are gone from the list being edited.
    if (diff.removed) {
      slots.insertAdjacentHTML("beforeend",
        `<div class="removed">${diff.removed === 1 ? "Eine Zeit wird" : `${diff.removed} Zeiten werden`}` +
        ` beim Speichern entfernt.</div>`);
    }

    slots.querySelectorAll("input").forEach((el) => {
      el.addEventListener("change", () => this._set(+el.dataset.i, el.dataset.f, el.value));
    });

    // A day at a glance: 24 bars, each the setpoint in force in that hour,
    // with a readable time axis under them and the value on tap. See the
    // curve* functions at the top of this file for why that is not cosmetic.
    const curve = this.querySelector(".curve");
    const axis = this.querySelector(".axis");
    const readout = this.querySelector(".readout");
    curve.innerHTML = curveHtml(list, (this._saved || {})[this._day]);
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

    // One line for the whole week, because Save writes the whole week.
    const pending = this.querySelector(".pending");
    const names = edited.map((id) => (DAYS.find((d) => d[0] === id) || [])[1]);
    pending.textContent = names.length
      ? `Noch nicht gespeichert: ${names.join(", ")}`
      : "";
    pending.classList.toggle("on", names.length > 0);
    this.querySelector(".save").disabled = !this._dirty;
    this.querySelector(".discard").disabled = !this._dirty;

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
