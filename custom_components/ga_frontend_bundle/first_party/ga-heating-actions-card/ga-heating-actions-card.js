/*
 * ga-heating-actions-card — the whole-home heating controls a resident reaches
 * in one tap: a short boost everywhere, and a Sonderplan (sickness / holiday)
 * that replaces the weekly plan for a period.
 *
 * WHAT THIS CARD IS NOT. It does not own any heating logic. Every button here
 * calls something ga_heating already had — `ga_heating.boost`,
 * `POST /api/ga_heating/absence`, `DELETE /api/ga_heating/absence`,
 * `ga_heating.cancel_boost`. The engine, its validation and its expiry live in
 * Core, where they survive a restart; a card that implemented a timer would
 * lose it the moment the browser tab closed.
 *
 * WHICH ROUTE, AND WHY IT IS NOT THE SAME ONE TWICE. The absence goes over the
 * HTTP route rather than the service, because ga_heating documents (measured on
 * a canary 2026-08-18) that Home Assistant's own /api/services endpoint turns a
 * ServiceValidationError into a bare 500 with no body: the reason reaches the
 * log and nobody else. The route answers 400 with the reason, and a refusal a
 * resident cannot read is barely better than silence. The boost has no HTTP
 * route, so it goes over the service — and this card always sends an explicit
 * temperature, which removes the one validation error that service can raise
 * ("no plan, so a boost needs an explicit temperature").
 *
 * WHICH ENTITIES ARE ROOMS. A ga_heating room entity carries `valves` (the list
 * it drives) and `area_id`; a raw TRV climate entity carries neither. That is
 * the discriminator, and it is read from the entity rather than from a name.
 *
 * Usage:
 *   type: custom:ga-heating-actions-card
 *   title: Heizung            # optional
 *   boost_minutes: 5          # optional, default 5, capped at 240 by ga_heating
 */

const BOOST_MINUTES = 5;
/**
 * Quarter-hour options for the holiday's start and end time.
 *
 * TAKEN FROM THE OLD GENERATOR, including its reason. `generate_yaml_new.py`
 * built `input_select.override_start_time` / `override_end_time` as literal
 * 15-minute dropdowns and says why: "option text is literal, so
 * locale-independent - no native 12h/AM-PM picker". A native `<input
 * type="time">` renders as the browser's locale decides, and a resident
 * reading "02:00 PM" where the rest of the card says 14:00 is a bug report.
 */
const TIME_OPTIONS = (() => {
  const out = [];
  for (let h = 0; h < 24; h++) for (const m of [0, 15, 30, 45]) {
    out.push(`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`);
  }
  return out;
})();
const SICK_MAX_HOURS = 48;
const TMIN = 5, TMAX = 30;

/** Room entities only: the ones ga_heating drives, not the valves themselves. */
function roomEntities(states) {
  return Object.keys(states || {})
    .filter((id) => id.startsWith("climate."))
    .filter((id) => Array.isArray((states[id].attributes || {}).valves))
    .sort();
}

/**
 * The frost-protection setpoints the VALVES themselves hold, as a sorted list.
 *
 * This is what makes "alles aus" safe to offer, and the reason it is read rather
 * than assumed. On a SONOFF TRVZB, `system_mode: off` IS the anti-freeze state:
 * the valve keeps a separate `frost_protection_temperature` and opens on its own
 * when the room falls to it. ga_heating's own OFF is deliberately NOT a low
 * setpoint ("a frost setpoint keeps the valve working against an open window"),
 * so the protection here comes from the hardware, not from us — and a card must
 * not promise it without looking.
 *
 * Measured on KIB-SON-00000031, 2026-09-23: all four valves hold 7 °C, not the
 * 5 °C the vendor documents as the default. A hardcoded 5 would have told the
 * resident a number their flat does not use.
 */
function frostSetpoints(states) {
  const vals = Object.keys(states || {})
    .filter((id) => id.startsWith("number.") && id.endsWith("_frost_protection_temperature"))
    .map((id) => Number(states[id].state))
    .filter((n) => Number.isFinite(n));
  return Array.from(new Set(vals)).sort((a, b) => a - b);
}

/** How to say that in one line, or "" when no valve reports a setpoint. */
function frostText(states) {
  const v = frostSetpoints(states);
  if (!v.length) return "";
  return v.length === 1
    ? `Frostschutz bleibt aktiv: die Ventile öffnen von selbst bei ${v[0]} °C.`
    : `Frostschutz bleibt aktiv: die Ventile öffnen von selbst bei ${v.join(" / ")} °C.`;
}

/* --- what is in force, read from the rooms -------------------------------
 * ga_heating 0.10.0 publishes `attributes.override` per room, derived from the
 * dict its own engine reads. The card does not compute "is it active" from two
 * timestamps and a clock it does not share with the engine — it reads `active`.
 * The previous system showed this and we did not; ga_heating's own source calls
 * an unseen bounded override indistinguishable from an unbounded one.
 */

/** `hh:mm` from seconds, for a countdown. Never negative — see remaining_s. */
function mmss(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** `DD.MM. HH:MM` from an ISO stamp, or "" — the format the old Profil view used. */
function whenText(iso) {
  if (typeof iso !== "string" || iso.length < 16) return "";
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}. ${iso.slice(11, 16)}`;
}

/**
 * One sentence about what is overriding these rooms, or "" when nothing is.
 *
 * Deliberately says "Räume: alle" only when EVERY room is covered — the number
 * a resident needs is "is my flat on holiday", and "3 von 3" answers it where a
 * bare list does not.
 */
function overrideStatus(states, roomIds) {
  const rooms = (roomIds || []).map((id) => (states[id] || {}).attributes || {});
  const abs = rooms.filter((a) => (((a.override || {}).absence) || {}).active);
  if (!abs.length) return "";
  const first = abs[0].override.absence;
  const what = first.off ? "Aus (Frostschutz)" : `${first.temp} °C`;
  const who = abs.length === rooms.length ? "alle Räume" : `${abs.length} von ${rooms.length} Räumen`;
  const until = whenText(first.end);
  return `Sonderplan aktiv — ${what}${until ? ` · bis ${until}` : ""} · ${who}`;
}

/** The same for a running boost, including the number nobody could see. */
function boostStatus(states, roomIds) {
  const live = (roomIds || [])
    .map((id) => ((((states[id] || {}).attributes || {}).override || {}).boost) || null)
    .filter((b) => b && b.active);
  if (!live.length) return "";
  const longest = Math.max(...live.map((b) => Number(b.remaining_s) || 0));
  return `Boost läuft — noch ${mmss(longest)} in ${live.length} Raum/Räumen`;
}

/** What a room is called on screen. Never its entity id, never a radio address. */
function roomName(state) {
  const a = (state && state.attributes) || {};
  return a.friendly_name || a.area_id || "";
}

/**
 * The end of a sickness override, as an ISO string ga_heating accepts.
 *
 * Local time on purpose: the resident said "for six hours", and the engine
 * compares against `datetime.now()`, which is local. A UTC stamp here would be
 * off by the timezone offset and the override would end at the wrong hour —
 * visibly wrong twice a year, subtly wrong the rest of the time.
 */
function localISO(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
         `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/**
 * The body for one room's absence, or a STRING saying why it cannot be built.
 *
 * ga_heating refuses an absence that runs backwards, and one with neither a
 * temperature nor switch_off — because such an override would be stored and
 * then silently never apply: the resident books a holiday, the card says saved,
 * and the heating runs as usual. Refusing HERE too means the resident sees the
 * reason next to the field they got wrong, not after a round trip.
 */
function absenceBody(entityId, form) {
  const out = { entity_id: entityId };
  if (form.kind === "sick") {
    const hours = Number(form.hours);
    if (!Number.isFinite(hours) || hours < 1 || hours > SICK_MAX_HOURS) {
      return `Die Dauer muss zwischen 1 und ${SICK_MAX_HOURS} Stunden liegen.`;
    }
    // `now` is injectable so a test can pin the clock; accepted as a Date or as
    // an ISO string, because JSON cannot carry a Date across the test harness.
    const now = form.now ? new Date(form.now) : new Date();
    if (Number.isNaN(now.getTime())) return "Der Startzeitpunkt ist unlesbar.";
    out.start = localISO(now);
    out.end = localISO(new Date(now.getTime() + hours * 3600 * 1000));
  } else {
    if (!form.start || !form.end) return "Bitte Anfang und Ende angeben.";
    // The END CARRIES A TIME, and that is not a detail. Ending at 23:59 means
    // the flat is still on holiday temperature all through the day the resident
    // comes home — they walk into a cold flat and the feature reads as broken.
    // The old system had exactly this field (`override_end_time`), and dropping
    // it would have been a regression nobody would have called one.
    const st = form.startTime || "00:00";
    const et = form.endTime || "12:00";
    out.start = `${form.start}T${st}:00`;
    out.end = `${form.end}T${et}:00`;
    if (out.end <= out.start) return "Das Ende liegt vor dem Anfang.";
  }
  if (form.off) {
    out.switch_off = true;
  } else {
    const t = Number(form.temperature);
    if (!Number.isFinite(t) || t < TMIN || t > TMAX) {
      return `Bitte eine Temperatur zwischen ${TMIN} und ${TMAX} °C angeben — oder „Heizung aus“ wählen.`;
    }
    out.temperature = t;
  }
  return out;
}

/** `<option>` list with `selected` on the current value. */
function timeOpts(current) {
  return TIME_OPTIONS.map((t) =>
    `<option value="${t}"${t === current ? " selected" : ""}>${t}</option>`).join("");
}

class GaHeatingActionsCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._minutes = Number(this._config.boost_minutes) || BOOST_MINUTES;
    this._form = { kind: "sick", hours: 6, temperature: 20, off: false,
                   start: "", end: "", startTime: "00:00", endTime: "12:00",
                   // `allRooms` is EXPLICIT. The first version treated "nothing
                   // ticked" as "all rooms", which reads as "none" — the old
                   // system had an `Alle Räume` switch for exactly this reason.
                   allRooms: true, rooms: [] };
    // Status is always visible; the form is not. An override whose status is only
    // visible where it was entered is the invisible override this card exists to
    // end. (ADR-0033, amendment 2026-09-23.)
    this._openForm = false;
    this._openRooms = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._built = true; this._build(); }
    this._render();
  }

  getCardSize() { return 6; }

  _rooms() { return roomEntities((this._hass || {}).states || {}); }

  /** The rooms this action applies to: the selection, or all of them. */
  _selected() {
    const all = this._rooms();
    if (this._form.allRooms) return all;
    return all.filter((id) => this._form.rooms.includes(id));
  }

  _say(kind, text) {
    const m = this.querySelector(".msg");
    if (!m) return;
    m.className = "msg " + kind;
    m.textContent = text;
    clearTimeout(this._t);
    this._t = setTimeout(() => { m.className = "msg"; }, 8000);
  }

  // ─── actions ──────────────────────────────────────────────────────────────

  /**
   * Boost every room for a few minutes.
   *
   * "Open all valves 100 %" is what was asked for; what the stack can express is
   * a SETPOINT, so this asks for each room's own max_temp — the warmest thing it
   * will accept — and ga_heating drives the valves there. That is an emulation
   * and the card says so rather than claiming a valve position it never sends.
   */
  async _boostAll() {
    const rooms = this._rooms();
    if (!rooms.length) return this._say("err", "Kein Raum mit Thermostat gefunden.");
    let ok = 0;
    const failed = [];
    for (const id of rooms) {
      const st = this._hass.states[id];
      const max = Number((st.attributes || {}).max_temp) || TMAX;
      try {
        await this._hass.callService("ga_heating", "boost", {
          entity_id: id, minutes: this._minutes, temperature: max,
        });
        ok += 1;
      } catch (e) {
        failed.push(roomName(st) || id);
      }
    }
    // Count what happened, never "done". A loop that failed on two of five rooms
    // and reported success is the shape of failure this project keeps paying for.
    if (failed.length) {
      this._say("err", `${ok} von ${rooms.length} Räumen auf voll — nicht erreicht: ${failed.join(", ")}.`);
    } else {
      this._say("ok", `${ok} Räume für ${this._minutes} Minuten voll aufgedreht. Danach gilt wieder der Plan.`);
    }
  }

  async _cancelBoost() {
    const rooms = this._rooms();
    let ok = 0;
    for (const id of rooms) {
      try { await this._hass.callService("ga_heating", "cancel_boost", { entity_id: id }); ok += 1; }
      catch (e) { /* counted by omission */ }
    }
    this._say("ok", `Boost in ${ok} von ${rooms.length} Räumen beendet.`);
  }

  /**
   * Switch every room off.
   *
   * `climate.set_hvac_mode(off)` — ga_heating fans that out to the valves as
   * `off`, which on a TRVZB is the anti-freeze state. So the flat is not
   * heated and is still protected, and the card says at which temperature
   * BECAUSE IT READ IT. Asked for on 2026-09-23; the frost question was settled
   * against the converter source, the vendor manual, and the devices themselves.
   */
  async _offAll() {
    const rooms = this._rooms();
    if (!rooms.length) return this._say("err", "Kein Raum mit Thermostat gefunden.");
    let ok = 0;
    const failed = [];
    for (const id of rooms) {
      try {
        await this._hass.callService("climate", "set_hvac_mode", { entity_id: id, hvac_mode: "off" });
        ok += 1;
      } catch (e) { failed.push(roomName(this._hass.states[id]) || id); }
    }
    const frost = frostText(this._hass.states);
    if (failed.length) {
      this._say("err", `${ok} von ${rooms.length} Räumen aus — nicht erreicht: ${failed.join(", ")}.`);
    } else {
      this._say("ok", `${ok} Räume ausgeschaltet. ${frost}`.trim());
    }
  }

  /** Back to the plan. An "all off" with no way back is a one-way street. */
  async _planAll() {
    const rooms = this._rooms();
    let ok = 0;
    for (const id of rooms) {
      try { await this._hass.callService("climate", "set_hvac_mode", { entity_id: id, hvac_mode: "auto" }); ok += 1; }
      catch (e) { /* counted by omission */ }
    }
    this._say("ok", `${ok} von ${rooms.length} Räumen folgen wieder dem Wochenplan.`);
  }

  async _applyAbsence() {
    const rooms = this._selected();
    if (!rooms.length) return this._say("err", "Kein Raum ausgewählt.");
    const probe = absenceBody(rooms[0], this._form);
    if (typeof probe === "string") return this._say("err", probe);

    let ok = 0;
    const failed = [];
    for (const id of rooms) {
      const body = absenceBody(id, this._form);
      try {
        await this._hass.callApi("post", "ga_heating/absence", body);
        ok += 1;
      } catch (e) {
        // The route answers 400 with the reason; show it, do not swallow it.
        const why = (e && (e.body && e.body.message)) || (e && e.message) || "abgelehnt";
        failed.push(`${roomName(this._hass.states[id]) || id} (${why})`);
      }
    }
    const what = this._form.off ? "Heizung aus" : `${this._form.temperature} °C`;
    const until = this._form.kind === "sick"
      ? `für ${this._form.hours} h`
      : `vom ${this._form.start} ${this._form.startTime || "00:00"} `
        + `bis ${this._form.end} ${this._form.endTime || "12:00"}`;
    if (failed.length) {
      this._say("err", `${ok} von ${rooms.length} Räumen gesetzt — abgelehnt: ${failed.join("; ")}`);
    } else {
      this._say("ok", `Sonderplan in ${ok} Räumen: ${what}, ${until}. Danach gilt wieder der Wochenplan.`);
    }
  }

  async _cancelAbsence() {
    const rooms = this._selected();
    let ok = 0;
    for (const id of rooms) {
      try { await this._hass.callApi("delete", "ga_heating/absence", { entity_id: id }); ok += 1; }
      catch (e) { /* counted by omission */ }
    }
    this._say("ok", `Sonderplan in ${ok} von ${rooms.length} Räumen aufgehoben.`);
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  _build() {
    this.innerHTML = `
      <ha-card header="${this._config.title || "Heizung — Ganzes Zuhause"}">
        <div class="card-content">
          <div class="msg"></div>
          <div class="quick">
            <button class="btn boost">Alle Räume ${this._minutes} Min voll aufdrehen</button>
            <button class="btn ghost cancel-boost">Boost beenden</button>
          </div>
          <div class="hint boosthint"></div>
          <div class="quick">
            <button class="btn offall">Alle Räume aus</button>
            <button class="btn ghost planall">Wieder nach Plan heizen</button>
          </div>
          <div class="hint frosthint"></div>
          <div class="status"></div>
          <h4>Sonderplan</h4>
          <button class="btn ghost toggle-form"></button>
          <div class="form">
          <div class="kinds">
            <button class="btn kind" data-kind="sick">Krankheit</button>
            <button class="btn kind" data-kind="holiday">Urlaub</button>
          </div>
          <div class="fields"></div>
          <div class="rooms"></div>
          <div class="actions">
            <button class="btn primary apply">Sonderplan setzen</button>
            <button class="btn ghost cancel-absence">Sonderplan aufheben</button>
          </div>
          </div>
        </div>
      </ha-card>
      <style>
        ga-heating-actions-card .card-content { padding: 16px; display: grid; gap: 12px; }
        ga-heating-actions-card .msg { display:none; padding:8px 10px; border-radius:8px; font-size:.9em; }
        ga-heating-actions-card .msg.ok { display:block; background: rgba(76,175,80,.15); color: var(--success-color,#1d7a3a); }
        ga-heating-actions-card .msg.err { display:block; background: rgba(244,67,54,.15); color: var(--error-color,#c0392b); }
        ga-heating-actions-card h4 { margin:4px 0 0; font-size:.95em; }
        ga-heating-actions-card .quick, ga-heating-actions-card .kinds,
        ga-heating-actions-card .actions { display:flex; gap:8px; flex-wrap:wrap; }
        ga-heating-actions-card .btn { flex:1 1 auto; padding:10px 12px; border:none; border-radius:10px;
          cursor:pointer; font-weight:600; background: var(--secondary-background-color,#e8e8e8); color: inherit; }
        ga-heating-actions-card .btn.primary { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-actions-card .btn.ghost { background: transparent; box-shadow: inset 0 0 0 1px var(--divider-color,#ddd); }
        ga-heating-actions-card .btn.kind.on { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-actions-card .hint { font-size:.82em; opacity:.7; }
        ga-heating-actions-card .status { font-size:.92em; padding:9px 11px; border-radius:9px;
          background: var(--secondary-background-color,#f0f0f0); display:grid; gap:4px; }
        ga-heating-actions-card .status.on { box-shadow: inset 3px 0 0 var(--ga-heat,#ff8a3d); }
        ga-heating-actions-card .status .quiet { opacity:.65; }
        ga-heating-actions-card .form[hidden] { display:none; }
        ga-heating-actions-card .fields { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        ga-heating-actions-card .fields label { font-size:.88em; display:flex; gap:6px; align-items:center; }
        ga-heating-actions-card .rooms { display:flex; gap:6px; flex-wrap:wrap; font-size:.86em; }
        ga-heating-actions-card .rooms label { display:flex; gap:5px; align-items:center;
          background: var(--secondary-background-color,#f0f0f0); padding:5px 9px; border-radius:999px; }
      </style>`;

    this.querySelector(".boost").addEventListener("click", () => this._boostAll());
    this.querySelector(".cancel-boost").addEventListener("click", () => this._cancelBoost());
    this.querySelector(".offall").addEventListener("click", () => this._offAll());
    this.querySelector(".planall").addEventListener("click", () => this._planAll());
    this.querySelector(".apply").addEventListener("click", () => this._applyAbsence());
    this.querySelector(".cancel-absence").addEventListener("click", () => this._cancelAbsence());
    this.querySelector(".toggle-form").addEventListener("click", () => {
      this._openForm = !this._openForm;
      this._render();
    });
    this.querySelectorAll(".kind").forEach((el) => {
      el.addEventListener("click", () => { this._form.kind = el.dataset.kind; this._render(); });
    });
    this.querySelector(".boosthint").textContent =
      `„Voll aufdrehen“ setzt jeden Raum für ${this._minutes} Minuten auf seine höchste Zieltemperatur — `
      + `das ist es, was die Thermostate annehmen. Danach gilt wieder der Wochenplan.`;
  }

  _render() {
    if (!this._built) return;
    const f = this._form;
    this.querySelectorAll(".kind").forEach((el) => {
      el.classList.toggle("on", el.dataset.kind === f.kind);
    });

    // Read on every render: a valve whose frost setpoint is changed must not
    // leave the card promising yesterday's number.
    const fh = this.querySelector(".frosthint");
    if (fh) {
      fh.textContent = frostText(this._hass.states)
        || "Kein Ventil meldet einen Frostschutz-Wert — „Alle Räume aus“ schaltet dann ohne "
           + "nachgewiesenen Frostschutz ab.";
    }

    // The status block, always visible. Two lines at most, and it says "nothing
    // is overriding" rather than staying blank — blank reads as "not loaded".
    const rooms0 = this._rooms();
    const st = this.querySelector(".status");
    if (st) {
      const a = overrideStatus(this._hass.states, rooms0);
      const b = boostStatus(this._hass.states, rooms0);
      const lines = [a, b].filter(Boolean);
      st.classList.toggle("on", lines.length > 0);
      st.innerHTML = lines.length
        ? lines.map((l) => `<div>${l}</div>`).join("")
        : '<div class="quiet">Kein Sonderplan und kein Boost aktiv — es gilt der Wochenplan.</div>';
    }

    const tf = this.querySelector(".toggle-form");
    if (tf) tf.textContent = this._openForm ? "Sonderplan schließen" : "Sonderplan ändern";
    const formEl = this.querySelector(".form");
    if (formEl) { if (this._openForm) formEl.removeAttribute("hidden"); else formEl.setAttribute("hidden", ""); }

    const fields = this.querySelector(".fields");
    const tempField =
      `<label><input type="checkbox" class="off" ${f.off ? "checked" : ""}> Heizung aus</label>` +
      `<label>Temperatur <input type="number" class="temp" min="${TMIN}" max="${TMAX}" step="0.5"
         value="${f.temperature}" ${f.off ? "disabled" : ""}> °C</label>`;
    fields.innerHTML = f.kind === "sick"
      ? `<label>Dauer <input type="number" class="hours" min="1" max="${SICK_MAX_HOURS}" value="${f.hours}"> h</label>`
        + `<span class="hint">beginnt sofort, höchstens ${SICK_MAX_HOURS} h</span>` + tempField
      : `<label>Von <input type="date" class="start" value="${f.start}">`
        + `<select class="starttime">${timeOpts(f.startTime)}</select></label>`
        + `<label>Bis <input type="date" class="end" value="${f.end}">`
        + `<select class="endtime">${timeOpts(f.endTime)}</select></label>`
        + `<span class="hint">Die Heizung läuft bis zur Rückkehr wieder normal, wenn du hier `
        + `die Uhrzeit setzt.</span>` + tempField;

    const bind = (sel, key, cast) => {
      const el = fields.querySelector(sel);
      if (el) el.addEventListener("change", () => { f[key] = cast(el); this._render(); });
    };
    bind(".hours", "hours", (el) => Number(el.value));
    bind(".temp", "temperature", (el) => Number(el.value));
    bind(".off", "off", (el) => el.checked);
    bind(".start", "start", (el) => el.value);
    bind(".end", "end", (el) => el.value);
    bind(".starttime", "startTime", (el) => el.value);
    bind(".endtime", "endTime", (el) => el.value);

    // Room scope. Nothing selected means ALL — said in words, because an empty
    // row of checkboxes reads as "none" and would be the opposite of the truth.
    // Room scope, EXPLICIT. `Alle Räume` is its own switch, as it was in the old
    // system: "nothing ticked" reads as "none", which is the opposite of what it
    // used to mean here. The per-room list collapses, so the common case — all of
    // them — is one line.
    const rooms = this._rooms();
    const box = this.querySelector(".rooms");
    if (!rooms.length) {
      box.innerHTML = '<span class="hint">Kein Raum mit Thermostat gefunden.</span>';
    } else {
      box.innerHTML =
        `<label><input type="checkbox" class="allrooms" ${f.allRooms ? "checked" : ""}>`
        + `<b>Alle Räume</b></label>`
        + `<button class="btn ghost toggle-rooms">`
        + `${this._openRooms ? "Räume ausblenden" : `Räume wählen (${f.allRooms ? rooms.length : f.rooms.length}/${rooms.length})`}`
        + `</button>`
        + (this._openRooms
            ? rooms.map((id) =>
                `<label><input type="checkbox" data-id="${id}" `
                + `${f.allRooms || f.rooms.includes(id) ? "checked" : ""} `
                + `${f.allRooms ? "disabled" : ""}>`
                + `${roomName(this._hass.states[id]) || id}</label>`).join("")
            : "");
      const all = box.querySelector(".allrooms");
      if (all) all.addEventListener("change", () => {
        f.allRooms = all.checked;
        if (f.allRooms) f.rooms = [];
        this._render();
      });
      const tr = box.querySelector(".toggle-rooms");
      if (tr) tr.addEventListener("click", () => { this._openRooms = !this._openRooms; this._render(); });
      box.querySelectorAll("input[data-id]").forEach((el) => {
        el.addEventListener("change", () => {
          f.allRooms = false;
          f.rooms = Array.from(box.querySelectorAll("input[data-id]"))
            .filter((x) => x.checked).map((x) => x.dataset.id);
          this._render();
        });
      });
    }
  }
}

customElements.define("ga-heating-actions-card", GaHeatingActionsCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-heating-actions-card",
  name: "GA Heizung — Ganzes Zuhause",
  description: "Boost für alle Räume und Sonderplan (Krankheit / Urlaub).",
});
