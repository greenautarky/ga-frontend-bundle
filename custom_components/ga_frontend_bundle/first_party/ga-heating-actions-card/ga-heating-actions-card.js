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

/**
 * How to say that in one line, or "" when no valve reports a setpoint.
 *
 * SAYS WHEN IT APPLIES. "Frostschutz bleibt aktiv" sat under a row of buttons
 * and read as a fact about the heating in general; it is only about what AUS
 * leaves behind ("here say that in AUS that happens", 2026-10-05).
 *
 * ONE NUMBER, THE LOWEST. Valves do not have to agree — on the flat this was
 * written against they read 7 and 8 — and the line used to print every distinct
 * value, "bei 7 / 8 °C", which asks a resident to work out which radiator is
 * which. The lowest is the honest single number for a safety sentence: a valve
 * set to 8 opens EARLIER than one set to 7, so 7 is the coldest any room is let
 * get, and promising the warmer number would promise more than the flat does.
 */
function frostText(states) {
  const v = frostSetpoints(states);
  if (!v.length) return "";
  return `Bei AUS bleibt der Frostschutz aktiv: die Ventile öffnen von selbst `
    + `bei ${v[0]} °C.`;
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

/**
 * The same for a running boost, including the number nobody could see.
 *
 * COUNTED FROM `until`, not from `remaining_s`. ga_heating computes the seconds
 * when the entity publishes, and a room publishes when something about it
 * CHANGES — which a boost quietly ticking down is not. The card therefore showed
 * one number and held it: "noch 4:59" for five minutes (reported 2026-10-05).
 * The deadline is an absolute timestamp, so the clock can be read here, as often
 * as the card likes. `remaining_s` stays the fallback for an override that has
 * no `until`.
 */
function boostStatus(states, roomIds) {
  const live = (roomIds || [])
    .map((id) => ((((states[id] || {}).attributes || {}).override || {}).boost) || null)
    .filter((b) => b && b.active);
  if (!live.length) return "";
  const left = (b) => {
    const until = b.until ? new Date(b.until).getTime() : NaN;
    if (!Number.isNaN(until)) return Math.max(0, Math.round((until - Date.now()) / 1000));
    return Number(b.remaining_s) || 0;
  };
  const longest = Math.max(...live.map(left));
  if (longest <= 0) return "";
  return `Boost läuft — noch ${mmss(longest)} in ${nRooms(live.length, true)}`;
}

/**
 * "1 Raum" / "3 Räume", and after a preposition "in 3 RäumeN".
 *
 * German declines, and a dashboard that does not reads like a machine talking.
 * Three places counted rooms three different ways — "1 Räume im Boost", "in 1
 * Raum/Räumen" — so this is the one of them.
 *
 * `dative` is not pedantry: both call sites below sit after "in", where the
 * plural takes -n. Writing one helper without it just moved the error from
 * "1 Räume" to "in 2 Räume" (caught in a browser against the device, 2026-10-05).
 */
function nRooms(n, dative = false) {
  if (n === 1) return `${n} Raum`;
  return `${n} ${dative ? "Räumen" : "Räume"}`;
}

/** What a room is called on screen. Never its entity id, never a radio address. */
function roomName(state) {
  const a = (state && state.attributes) || {};
  return a.friendly_name || a.area_id || "";
}

//: What a balancing run asks for, and the room temperature it needs to be worth
//: running at all.
//:
//: The hour measures each radiator's catch-up rate at a common flow, so every
//: room has to have somewhere to climb. A room already at the target makes its
//: TRV stop calling for heat the moment the run starts, and that radiator
//: contributes no rate — the run still "succeeds" and the data is empty.
//:
//: TWO LIMITS, because a warm room spoils a run in two different ways.
//:
//: CANNOT MEASURE (headroom). Under 4 K of gap the room reaches the target
//: partway through the hour and the radiator throttles for the rest of the
//: window — these rooms rise roughly 0.5-2 K in an hour. At a 30 degree target
//: that is 26, and it is a hard limit: above it the radiator contributes no
//: rate at all.
//:
//: SHOULD NOT MEASURE (comparability). The run exists to compare radiators with
//: each other, and a radiator gives up less heat into a warm room than into a
//: cool one — so rates measured across already-warm rooms compress together and
//: the differences the balance is looking for shrink into the noise. 21 is
//: ordinary room temperature and the value the product owner asked for
//: (2026-10-06); it is a recommendation, not a refusal.
const ICHB_TARGET = 30;
const ICHB_MIN_HEADROOM = 4;
const ICHB_MAX_ROOM_TEMP = ICHB_TARGET - ICHB_MIN_HEADROOM;
const ICHB_IDEAL_ROOM_TEMP = 21;

//: How many rooms fit in one row of chips before it is worth collapsing. Six is
//: two lines on a phone; a flat with more than that is the case the disclosure
//: below was written for.
const MAX_CHIPS = 6;

/**
 * The scope after one room chip is tapped: `{allRooms, rooms}`.
 *
 * Out here rather than in the click handler because this is the part with the
 * decisions in it, and a closure over a DOM node cannot be tested — the whole
 * reason `tests/js/eval.mjs` exists is to run the shipped logic, and logic
 * reachable only through a click is logic nothing runs until a resident does.
 *
 * A LIT CHIP MEANS THIS ROOM WILL BE TOUCHED, so tapping a lit one turns it
 * off. `allRooms` is shorthand for every room, so turning one off has to start
 * from the list the row is showing, in the rooms' own order.
 */
function toggleRoom(rooms, f, id) {
  const lit = f.allRooms || f.rooms.includes(id);
  const current = f.allRooms ? rooms.slice() : rooms.filter((r) => f.rooms.includes(r));
  const next = lit ? current.filter((r) => r !== id) : current.concat([id]);
  // A selection that covers the flat IS "alle". Without this the row shows every
  // room lit beside a dark `Alle`, a difference with no meaning behind it — and
  // the explicit list would also silently exclude a room added later.
  const allRooms = next.length === rooms.length;
  return { allRooms, rooms: allRooms ? [] : next };
}

/**
 * What the collapsed room list says about itself.
 *
 * "2 gewählt" is a COUNT, and a count is the one thing a resident already knows
 * — they just ticked them. What they cannot see with the list closed is WHICH
 * two, and that is the only question the line has to answer before someone
 * presses Boost or Aktivieren.
 *
 * Two names, then "+n", because the row sits beside a checkbox on a phone.
 *
 * WHY NOT A DROPDOWN (asked 2026-10-05). A `<select multiple>` hides the
 * selection behind a tap, needs a second tap to close, renders as a native
 * modal on iOS and Android that no theme reaches, and on a flat with three
 * rooms it would hide three words to save one line. The disclosure below keeps
 * the common case — all of them — to a single line and shows every room at
 * once when opened, which a dropdown cannot do while staying readable.
 */
function scopeLabel(states, rooms, f, open) {
  const caret = open ? "▾" : "▸";
  if (f.allRooms) return `${caret} Räume: alle`;
  const names = rooms
    .filter((id) => f.rooms.includes(id))
    .map((id) => roomName(states[id]) || id);
  if (!names.length) return `${caret} Kein Raum gewählt`;
  const shown = names.slice(0, 2).join(", ");
  return `${caret} Räume: ${shown}${names.length > 2 ? ` +${names.length - 2}` : ""}`;
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
  // "Aus · Frostschutz" belongs to a holiday, not to an illness. Someone in bed
  // wants the room WARMER; an off-switch on that form is an offer nobody wants
  // and a mis-tap with a cold night behind it. Sickness therefore always
  // carries a temperature, whatever `off` happens to hold.
  if (form.off && form.kind !== "sick") {
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

/**
 * Text for HTML. Names and texts from Home Assistant (entity names, room names,
 * attributes, stored plans) are escaped before they are rendered, so they show
 * as written. Every first-party card carries this same helper; a test keeps the
 * copies identical.
 */
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

  //: A countdown has to be driven by a clock, not by state updates. The card
  //: re-renders when Home Assistant pushes a change; a boost running out pushes
  //: nothing until it ends, so without this the seconds stand still.
  //:
  //: ONLY WHILE A COUNTDOWN IS RUNNING, and only while the card is on screen.
  //: The first version ticked every second, always, and every tick ran the
  //: whole render — which rebuilt the room chips. A press held across a tick
  //: went down on a chip that no longer existed when it came up, so the click
  //: never fired. The tick now updates the countdown text and nothing else
  //: (`_renderLive`), and `_syncTicker` stops it when nothing is counting down.
  connectedCallback() {
    this._connected = true;
    this._syncTicker();
  }

  disconnectedCallback() {
    this._connected = false;
    this._syncTicker();
  }

  /** True while a boost or a balancing run is counting down in some room. */
  _counting() {
    if (!this._hass) return false;
    return this._boostRooms().length > 0 || this._ichbRooms().length > 0;
  }

  /** Start the one-second clock if a countdown needs it, stop it if not. */
  _syncTicker() {
    const want = Boolean(this._connected && this._counting());
    if (want && !this._ticker) {
      this._ticker = setInterval(() => this._tick(), 1000);
    } else if (!want && this._ticker) {
      clearInterval(this._ticker);
      this._ticker = null;
    }
  }

  _tick() {
    if (!this._hass || !this._built) return;
    this._renderLive();
    this._syncTicker();
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
   * Boost the SELECTED rooms for a few minutes.
   *
   * "Open all valves 100 %" is what was asked for; what the stack can express is
   * a SETPOINT, so this asks for each room's own max_temp — the warmest thing it
   * will accept — and ga_heating drives the valves there. That is an emulation
   * and the card says so rather than claiming a valve position it never sends.
   *
   * THE SELECTION, not every room. The room picker sits directly above this
   * button and this button ignored it: pick Badezimmer, press Boost setzen, and
   * the whole flat went to 30 °C. It went unnoticed because the picker was
   * collapsed behind a disclosure and defaulted to "alle", so the two agreed in
   * the only case anybody exercised.
   *
   * `Alle → KI` and `Alle AUS` beside it keep every room on purpose: their
   * labels say "Alle", they are Ahmad's own words from the previous system, and
   * a button that says what it does is allowed to say it.
   */
  async _boostAll() {
    if (!this._rooms().length) {
      return this._say("err", "Kein Raum mit Thermostat gefunden.");
    }
    const rooms = this._selected();
    if (!rooms.length) return this._say("err", "Kein Raum ausgewählt.");
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
      this._say("ok", `${nRooms(ok)} für ${this._minutes} Minuten voll aufgedreht. `
        + `Danach gilt wieder der Plan.`);
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
    // EVERY room, not the selection — the button says "Alle AUS". See _boostAll.
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

  /**
   * "Alle → KI" — back to the plan, the old Profil view's own wording (`KI` is
   * `hvac_mode: auto` in this product, as ga-thermostat-card already labels it).
   *
   * It is ALSO the way out of a boost: his layout had three buttons, not four,
   * and a resident who wants the plan back does not care which override is in
   * the way. So this cancels the boost too — otherwise "back to the plan" would
   * leave a boost running for another four minutes and read as broken.
   */
  async _planAll() {
    // EVERY room, not the selection — the button says "Alle → KI". See _boostAll.
    const rooms = this._rooms();
    let ok = 0;
    for (const id of rooms) {
      try {
        await this._hass.callService("ga_heating", "cancel_boost", { entity_id: id });
      } catch (e) { /* no boost to cancel is the normal case */ }
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

  /**
   * The rooms too warm for a balancing run to measure, named.
   *
   * Named rather than counted, and read from the ROOM's own thermometer — the
   * same number the heading badge shows — so a resident can check the claim
   * against what is on their screen.
   */
  _tooWarmRooms() {
    const over = (limit) => (this._rooms() || []).filter((id) => {
      const t = Number(((this._hass.states[id] || {}).attributes || {}).current_temperature);
      return Number.isFinite(t) && t > limit;
    }).map((id) => roomName(this._hass.states[id]) || id);
    // `blocking` is a subset of `warm`; naming a room twice in one sentence
    // would read as two separate problems with it.
    const blocking = over(ICHB_MAX_ROOM_TEMP);
    const warm = over(ICHB_IDEAL_ROOM_TEMP).filter((n) => !blocking.includes(n));
    return { blocking, warm };
  }

  /** The rooms a balancing run is holding right now, as ga_heating reports them. */
  _ichbRooms() {
    return (this._rooms() || []).filter((id) =>
      ((((this._hass.states[id] || {}).attributes || {}).override || {}).ichb || {})
        .active === true);
  }

  /**
   * Start a hydraulic balancing run across the whole flat.
   *
   * WHOLE HOME, NOT THE SELECTION, and no room picker of its own. The point of
   * the hour is that every radiator is measured at the same flow and the rooms
   * are then comparable with each other; balancing three of six rooms produces
   * numbers that cannot be compared with anything, which is worse than no run.
   * ga_heating decides which radiators are actually measurable and reports the
   * rest — the card does not pre-empt that.
   *
   * ONE ARGUMENT IS SENT, the target temperature (ICHB_TARGET), so the number
   * in the warning above and the number the run uses cannot drift apart. The
   * duration is left to the service's default of 60 minutes, which is what the
   * rate calculation averages over; a card offering a 20-minute balance would be
   * offering a measurement nobody can use. No `rooms`: see above.
   */
  async _startIchb() {
    const { blocking, warm } = this._tooWarmRooms();
    try {
      await this._hass.callService("ga_heating", "ichb", { temperature: ICHB_TARGET });
      // Said ON THE PRESS as well as on the heading: the heading is where a
      // resident looks before deciding, the toast is what they get if they did
      // not, and an hour is too long to find out afterwards.
      if (blocking.length) {
        this._say("err", `Abgleich gestartet, aber ${blocking.join(", ")} `
          + `${blocking.length === 1 ? "ist" : "sind"} über ${ICHB_MAX_ROOM_TEMP} °C — `
          + `${blocking.length === 1 ? "dieser Raum liefert" : "diese Räume liefern"} `
          + `keine brauchbare Messung. Am besten unter ${ICHB_IDEAL_ROOM_TEMP} °C wiederholen.`);
      } else if (warm.length) {
        this._say("err", `Abgleich gestartet. ${warm.join(", ")} `
          + `${warm.length === 1 ? "ist" : "sind"} über ${ICHB_IDEAL_ROOM_TEMP} °C — `
          + `das Ergebnis wird ungenauer, weil ein Heizkörper in einen warmen Raum `
          + `weniger Wärme abgibt. Für den besten Abgleich kühl starten.`);
      } else {
        this._say("ok", "Abgleich gestartet — eine Stunde, danach gilt wieder der Plan.");
      }
    } catch (e) {
      const why = (e && (e.body && e.body.message)) || (e && e.message) || "abgelehnt";
      this._say("err", `Abgleich nicht gestartet: ${why}`);
    }
  }

  /** Stop a run early. The plan underneath was never overwritten, so this is a drop. */
  async _cancelIchb() {
    try {
      await this._hass.callService("ga_heating", "cancel_ichb", {});
      this._say("ok", "Abgleich abgebrochen — die Räume folgen wieder dem Plan.");
    } catch (e) {
      this._say("err", "Abgleich konnte nicht abgebrochen werden.");
    }
  }

  /** The rooms with a boost running — what the line above the button counts. */
  _boostRooms() {
    return (this._rooms() || []).filter((id) =>
      ((((this._hass.states[id] || {}).attributes || {}).override || {}).boost || {})
        .active === true);
  }

  /**
   * End every running boost, and put those rooms back where they were.
   *
   * SCOPED TO THE ROOMS THAT ARE BOOSTING, not to the selection — the same rule
   * as `_endAbsence`, and for the same reason: the button sits under a line that
   * says "3 Räume im Boost", and a button under that sentence has to act on
   * those three. The selection is an input to STARTING something; by the time
   * someone wants out, it may have been changed, and a Beenden that reported
   * success having ended nothing is the worst of both.
   *
   * Nothing restores a previous state here, because nothing was overwritten: a
   * boost wins over each room's stored decision while it runs and never replaces
   * it, so dropping it is the way back. A room that was AUS returns to AUS.
   */
  async _endBoost() {
    const rooms = this._boostRooms();
    if (!rooms.length) return this._say("ok", "Kein Boost aktiv.");
    let ok = 0;
    const failed = [];
    for (const id of rooms) {
      try {
        await this._hass.callService("ga_heating", "cancel_boost", { entity_id: id });
        ok += 1;
      } catch (e) { failed.push(roomName(this._hass.states[id]) || id); }
    }
    // The counts it actually reached: "Boost in 1 Raum beendet", not a fixed
    // "1 von 1 Räumen" — and on a partial failure, which rooms are still boosting.
    if (failed.length) {
      this._say("err", `Boost in ${ok} von ${nRooms(rooms.length, true)} beendet — `
        + `nicht erreicht: ${failed.join(", ")}.`);
    } else {
      this._say("ok", `Boost in ${nRooms(ok, true)} beendet.`);
    }
  }

  /** The rooms that actually have one running — what the status line counts. */
  _absenceRooms() {
    return (this._rooms() || []).filter((id) =>
      ((((this._hass.states[id] || {}).attributes || {}).override || {}).absence || {})
        .active === true);
  }

  /**
   * End the Sonderplan the status line is describing.
   *
   * NOT the selection. "Deaktivieren" inside the form is selection-scoped, which
   * is right for an editor; this button sits next to a line that says "1 von 3
   * Räumen", and a button under that sentence has to act on THAT one. With the
   * selection elsewhere it would have reported success having done nothing.
   */
  async _endAbsence() {
    const rooms = this._absenceRooms();
    if (!rooms.length) return this._say("ok", "Kein Sonderplan aktiv.");
    let ok = 0;
    for (const id of rooms) {
      try { await this._hass.callApi("delete", "ga_heating/absence", { entity_id: id }); ok += 1; }
      catch (e) { /* counted by omission */ }
    }
    this._say(ok === rooms.length ? "ok" : "err",
      `Sonderplan in ${ok} von ${rooms.length} Räumen beendet.`);
  }

  async _cancelAbsence() {
    const rooms = this._selected();
    if (!rooms.length) return this._say("err", "Kein Raum ausgewählt.");
    let ok = 0;
    for (const id of rooms) {
      try { await this._hass.callApi("delete", "ga_heating/absence", { entity_id: id }); ok += 1; }
      catch (e) { /* counted by omission */ }
    }
    this._say("ok", `Sonderplan in ${ok} von ${rooms.length} Räumen aufgehoben.`);
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  /**
   * TWO BLOCKS, BECAUSE THERE ARE TWO SCOPES.
   *
   * One heading said "Boost" over three actions, two of which are not a boost —
   * "this section isnt only about boost and teh boost button is down along alle
   * ki and..." (2026-10-05). Worse, the room picker under that heading governs
   * the first button and deliberately NOT the other two, whose labels say
   * "Alle". A reader had to know that; nothing on screen said it, which is how
   * "Boost setzen ignores the picker" stayed invisible for as long as it did.
   *
   * So the layout carries it: picker and Boost in one block, the two whole-home
   * buttons in another under a heading that states their scope, and the frost
   * line under the AUS button it explains rather than under a row where two of
   * three buttons were not AUS. Every label is unchanged.
   *
   * Written here and not as an HTML comment in the template below: a comment in
   * there is DOM. It reaches every browser, and a test looking for a button
   * found this prose instead.
   */
  _build() {
    this.innerHTML = `
      <ha-card>
        <h1 class="card-title">${esc(this._config.title || "Heizung — Ganzes Zuhause")}</h1>
        <div class="card-content">
          <div class="msg"></div>
          <h4>Boost <span class="sub boosthint"></span></h4>
          <div class="hint roomslabel">Räume wählen</div>
          <div class="rooms"></div>
          <div class="quick">
            <button class="btn primary boost">Boost setzen</button>
            <button class="btn ghost end-boost" hidden>Boost beenden</button>
          </div>
          <h4 class="rule">Ganze Wohnung</h4>
          <div class="quick">
            <button class="btn ki planall">Alle → KI</button>
            <button class="btn aus offall">Alle AUS</button>
          </div>
          <div class="hint frosthint"></div>
          <div class="ichb-section" hidden>
          <h4 class="rule">Hydraulischer Abgleich <span class="sub ichbhint"></span></h4>
          <div class="quick">
            <button class="btn ki ichb-start">Abgleich starten</button>
            <button class="btn ghost ichb-cancel" hidden>Abgleich abbrechen</button>
          </div>
          </div>
          <h4 class="rule sph">Sonderpläne (Krankheit und Urlaub)</h4>
          <div class="status"></div>
          <div class="statusactions">
            <button class="btn ghost toggle-form"></button>
            <button class="btn ghost end-absence" hidden>Sonderplan beenden</button>
          </div>
          <div class="form">
          <div class="kinds">
            <button class="btn kind" data-kind="sick">Krankheit</button>
            <button class="btn kind" data-kind="holiday">Urlaub</button>
          </div>
          <div class="fields"></div>
          <div class="actions">
            <button class="btn primary apply">Aktivieren</button>
            <button class="btn ghost cancel-absence">Deaktivieren</button>
          </div>
          </div>
        </div>
      </ha-card>
      <style>
        /* Layout: two blocks with a rule between them, and a button row that
           gives the primary action the room it needs. Everything collapses to a
           single column on a phone, which is where a resident presses "Alle AUS"
           on their way out of the door. */
        /* OUR OWN TITLE, not ha-card's header attribute.
           That one renders inside ha-card's SHADOW DOM, where this stylesheet
           cannot reach it - and it carries line-height 48px over 24px text plus
           16px of its own bottom padding, which together with the 16px we were
           padding the content with put about 44px of white between the title
           and the first heading ("gap is still huge", 2026-10-05).
           Rendered here instead, as the maintenance and log cards already do,
           it keeps the 24px size HA gives a card title while the spacing
           becomes ours.

           NOTHING IN THIS STYLE BLOCK MAY CONTAIN A BACKTICK: it lives inside
           the template literal that builds the card, so one ends the string and
           the CSS after it is parsed as JavaScript. Shipped broken twice on
           2026-10-05, the second time in the comment explaining the first.
           test_first_party.py now fails on it. */
        ga-heating-actions-card .card-title { margin: 0; padding: 16px 16px 0;
          font-size: 24px; font-weight: 400; line-height: 1.2;
          color: var(--ha-card-header-color, var(--primary-text-color, #212121)); }
        ga-heating-actions-card .card-content { padding: 12px 16px 16px;
          display: grid; gap: 14px; }
        /* A heading and the line explaining it are ONE thing, so they must not
           be spaced like two. The grid gap is 14px everywhere, which is right
           between blocks and too much between "BOOST" and the sentence under
           it ("remove gap between boost and explanation", 2026-10-05).
           Pulled back to 4px, and only where a hint follows a heading - the
           frost line sits under the button row, not under a heading, and keeps
           the full gap. */
        ga-heating-actions-card h4 + .hint { margin-top: -10px; }
        /* The explanation rides ON the heading, so it has to escape the
           heading's own shouting: no uppercase, no bold, no letter-spacing, and
           the quieter colour a caption gets everywhere else on this card. */
        ga-heating-actions-card h4 .sub { text-transform: none; font-weight: 400;
          letter-spacing: 0; color: var(--secondary-text-color, #5a6b68); }
        /* A warning that reads like the rest of the card is a warning nobody
           sees; this one costs an hour to ignore. */
        ga-heating-actions-card h4 .sub.warn { color: var(--error-color, #b3261e); }
        /* The panel below is a place where you choose; this says what to choose.
           Tight against it, because a label belongs to the thing it labels. */
        ga-heating-actions-card .roomslabel { margin-bottom: -10px; }
        /* The status line is empty until something is said, and an empty GRID
           ITEM is not free: it holds a row and the 14px gap after it, which is
           the dead band between the card title and "BOOST" ("why there is a
           huge gap between title and boost", 2026-10-05). Hiding it removes
           the item, and with it the gap, while :empty brings both back by
           itself the moment there is a message.

           NO BACKTICKS IN HERE. This comment sits inside the template literal
           that builds the card, so one would end the string and the CSS after
           it would be parsed as JavaScript — which is exactly how this rule
           shipped broken for an hour (CI, 2026-10-05). */
        ga-heating-actions-card .msg:empty { display: none; }
        /* The balancing block is one grid item, so hiding it takes its gap with
           it. Hidden until the device's ga_heating offers the service. */
        ga-heating-actions-card .ichb-section { display: grid; gap: 14px; }
        ga-heating-actions-card .ichb-section[hidden] { display: none; }
        ga-heating-actions-card h4 { margin: 0; font-size: .82em; font-weight: 700;
          letter-spacing: .07em; text-transform: uppercase; color: var(--secondary-text-color, #6b7682); }
        /* A rule above every block but the first — the blocks are the thing
           that says which buttons share a scope, so they have to look separate. */
        ga-heating-actions-card h4.rule { padding-top: 14px;
          border-top: 1px solid var(--divider-color, #e3e3e3); }
        ga-heating-actions-card .msg { display:none; padding:9px 11px; border-radius:9px; font-size:.9em; }
        ga-heating-actions-card .msg.ok { display:block; background: rgba(76,175,80,.15); color: var(--success-color,#1d7a3a); }
        ga-heating-actions-card .msg.err { display:block; background: rgba(244,67,54,.15); color: var(--error-color,#c0392b); }

        /* Boost setzen carries the weight; the two "everything" actions sit
           beside it at equal width so neither is pressed by accident. */
        ga-heating-actions-card .quick { display: grid; gap: 8px;
          grid-template-columns: minmax(150px, 1.4fr) 1fr 1fr; }
        @media (max-width: 460px) { ga-heating-actions-card .quick { grid-template-columns: 1fr; } }
        ga-heating-actions-card .actions { display: grid; gap: 8px; grid-template-columns: 1fr 1fr; }

        ga-heating-actions-card .btn { padding: 11px 12px; border: none; border-radius: 10px;
          cursor: pointer; font-weight: 600; font-size: .92em; line-height: 1.2;
          background: var(--secondary-background-color,#e8e8e8); color: inherit; }
        ga-heating-actions-card .btn:hover { filter: brightness(.97); }
        ga-heating-actions-card .btn:focus-visible { outline: 2px solid var(--primary-color,#03a9f4); outline-offset: 2px; }
        ga-heating-actions-card .btn.primary { background: var(--primary-color,#03a9f4); color:#fff; }
        ga-heating-actions-card .btn.ghost { background: transparent; box-shadow: inset 0 0 0 1px var(--divider-color,#ddd); }
        /* the two accents from the old Profil view: KI orange-red, AUS deeper red */
        ga-heating-actions-card .btn.ki { background: rgba(231,76,60,.12); box-shadow: inset 0 0 0 1px rgba(231,76,60,.3); }
        ga-heating-actions-card .btn.aus { background: rgba(192,57,43,.16); box-shadow: inset 0 0 0 1px rgba(192,57,43,.35); }
        ga-heating-actions-card .kinds { display: grid; gap: 8px; grid-template-columns: 1fr 1fr; }
        ga-heating-actions-card .btn.kind.on { background: var(--primary-color,#03a9f4); color:#fff; }

        ga-heating-actions-card .hint { font-size:.84em; color: var(--secondary-text-color,#6b7682); margin:0; }
        ga-heating-actions-card .hint.wide { grid-column: 1 / -1; }

        ga-heating-actions-card .status { font-size:.93em; padding:10px 12px; border-radius:10px;
          background: var(--secondary-background-color,#f0f0f0); display:grid; gap:3px; }
        ga-heating-actions-card .status.on { box-shadow: inset 3px 0 0 var(--ga-heat,#ff8a3d); }
        ga-heating-actions-card .status .quiet { color: var(--secondary-text-color,#6b7682); }

        ga-heating-actions-card .statusactions { display:flex; gap:8px; flex-wrap:wrap; }
        ga-heating-actions-card .statusactions .btn[hidden] { display:none; }
        ga-heating-actions-card .form[hidden] { display:none; }
        ga-heating-actions-card .form { display: grid; gap: 12px; }

        /* Label above its input, so a long German label never squeezes the field. */
        ga-heating-actions-card .fields { display: grid; gap: 10px 14px;
          grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); align-items: end; }
        ga-heating-actions-card .fields label { display: grid; gap: 4px; font-size: .86em;
          color: var(--secondary-text-color,#6b7682); }
        ga-heating-actions-card .fields label.chk { display: flex; gap: 8px; align-items: center;
          align-self: end; padding-bottom: 9px; color: inherit; font-size: .92em; }
        ga-heating-actions-card .fields .in { display: flex; gap: 6px; align-items: center; }
        ga-heating-actions-card .fields .in em { font-style: normal; color: var(--secondary-text-color,#6b7682); }
        ga-heating-actions-card .fields input[type=number],
        ga-heating-actions-card .fields input[type=date],
        ga-heating-actions-card .fields select { flex: 1 1 auto; min-width: 0; padding: 8px 9px;
          border-radius: 8px; border: 1px solid var(--divider-color,#ddd);
          background: var(--card-background-color, #fff); color: inherit; font: inherit; }

        /* THE CHIPS ARE A CHOICE; THE BUTTON UNDER THEM IS AN ACTION.
           Both were pills in the same filled green, so seven selected rooms and
           "Boost setzen" read as one row of buttons and nothing said which one
           does something ("we need to distinguish between choosing the rooms
           and the boost button", 2026-10-05). The chips now sit on their own
           surface: a panel is a place where you pick, and the action stands
           outside it on the card. */
        ga-heating-actions-card .rooms { display:flex; gap:8px; flex-wrap:wrap; align-items:center; font-size:.9em;
          background: var(--secondary-background-color, #eceff1);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 14px; padding: 10px 12px; }
        /* Filled = this room will be touched. The fill carries the state, so
           there is no checkbox beside it: two things saying the same thing is
           how the old row became unreadable. */
        ga-heating-actions-card .rooms .chip { font: inherit; font-size: .9em;
          padding: 6px 13px; border-radius: 999px; cursor: pointer;
          border: 1px solid var(--divider-color, #e0e0e0); background: transparent;
          color: var(--primary-text-color, #212121); }
        ga-heating-actions-card .rooms .chip.on { background: var(--primary-color, #4A7D59);
          border-color: var(--primary-color, #4A7D59);
          color: var(--text-primary-color, #fff); font-weight: 600; }
        ga-heating-actions-card .rooms .btn { padding: 6px 11px; font-size: .88em; }
      </style>`;

    this.querySelector(".boost").addEventListener("click", () => this._boostAll());
    this.querySelector(".offall").addEventListener("click", () => this._offAll());
    this.querySelector(".planall").addEventListener("click", () => this._planAll());
    this.querySelector(".apply").addEventListener("click", () => this._applyAbsence());
    this.querySelector(".cancel-absence").addEventListener("click", () => this._cancelAbsence());
    this.querySelector(".end-absence").addEventListener("click", () => this._endAbsence());
    this.querySelector(".end-boost").addEventListener("click", () => this._endBoost());
    this.querySelector(".ichb-start").addEventListener("click", () => this._startIchb());
    this.querySelector(".ichb-cancel").addEventListener("click", () => this._cancelIchb());
    this.querySelector(".toggle-form").addEventListener("click", () => {
      this._openForm = !this._openForm;
      this._render();
    });
    this.querySelectorAll(".kind").forEach((el) => {
      el.addEventListener("click", () => { this._form.kind = el.dataset.kind; this._render(); });
    });

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

    this._renderLive();

    const tf = this.querySelector(".toggle-form");
    if (tf) tf.textContent = this._openForm ? "Abbrechen" : "Bearbeiten";
    const formEl = this.querySelector(".form");
    if (formEl) {
      if (this._openForm) formEl.removeAttribute("hidden");
      else formEl.setAttribute("hidden", "");
    }

    this._renderFields();
    this._renderRooms();
    this._syncTicker();
  }

  /**
   * Everything that changes while a countdown runs, and nothing else.
   *
   * The once-a-second tick calls this and only this. It writes text and toggles
   * visibility; it never replaces an element a resident can press, so a press
   * held across a tick lands on the button it went down on.
   */
  _renderLive() {
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
        ? `<div><b>AKTIV</b></div>` + lines.map((l) => `<div>${esc(l)}</div>`).join("")
        : '<div class="quiet"><b>Inaktiv</b> — es gilt der Wochenplan.</div>';
    }

    // His two wordings, verbatim: idle and running.
    const bh = this.querySelector(".boosthint");
    if (bh) {
      const live = rooms0.filter((id) =>
        ((((this._hass.states[id] || {}).attributes || {}).override || {}).boost || {}).active);
      // On the heading line now, in brackets, so the section and its
      // explanation are one line rather than two ("put in parentheses same line
      // as boost not below", 2026-10-05).
      //
      // The running sentence drops the word "Boost": it sits directly after the
      // heading that already says it, and "BOOST (2 Räume im Boost …)" says it
      // twice.
      bh.textContent = live.length
        ? `(läuft in ${nRooms(live.length, true)} · Ventile ganz offen)`
        : "(Ventile kurzzeitig ganz öffnen)";
    }

    // The heading says what the hour is for; while a run is going it says how
    // much of it is left, counted from `until` for the same reason the boost
    // countdown is — a run ticking down publishes nothing.
    //
    // THE WHOLE SECTION ONLY WHERE THE SERVICE EXISTS. `ichb` and `cancel_ichb`
    // arrived in ga_heating 0.13.0; on a device still on 0.12.x the button would
    // call a service Home Assistant does not have and fail, every time.
    const isec = this.querySelector(".ichb-section");
    if (isec) {
      const offered = Boolean(((this._hass.services || {}).ga_heating || {}).ichb);
      if (offered) isec.removeAttribute("hidden");
      else isec.setAttribute("hidden", "");
    }
    const ih = this.querySelector(".ichbhint");
    const icancel = this.querySelector(".ichb-cancel");
    const istart = this.querySelector(".ichb-start");
    if (ih) {
      const live = this._ichbRooms();
      // Red only for "too warm to measure", and only before a run: once one is
      // going, the countdown is information, not a warning.
      let warn = false;
      if (live.length) {
        const ov = ((this._hass.states[live[0]].attributes || {}).override || {}).ichb || {};
        const until = ov.until ? new Date(ov.until).getTime() : NaN;
        const left = Number.isNaN(until)
          ? Number(ov.remaining_s) || 0
          : Math.max(0, Math.round((until - Date.now()) / 1000));
        ih.textContent = `(läuft — noch ${mmss(left)} in ${nRooms(live.length, true)})`;
      } else {
        const { blocking, warm } = this._tooWarmRooms();
        if (blocking.length) {
          ih.textContent = `(zu warm für eine Messung: ${blocking.join(", ")} — `
            + `unter ${ICHB_MAX_ROOM_TEMP} °C starten)`;
        } else if (warm.length) {
          ih.textContent = `(am besten unter ${ICHB_IDEAL_ROOM_TEMP} °C starten — `
            + `${warm.join(", ")} ${warm.length === 1 ? "ist" : "sind"} wärmer)`;
        } else {
          ih.textContent = "(eine Stunde gleicher Durchfluss, damit die Räume vergleichbar werden)";
        }
        warn = blocking.length > 0;
      }
      ih.classList.toggle("warn", warn);
      if (icancel) {
        if (live.length) icancel.removeAttribute("hidden");
        else icancel.setAttribute("hidden", "");
      }
      // A second run on top of a running one is not a thing ga_heating offers.
      if (istart) istart.disabled = live.length > 0;
    }

    // THE WAY OUT, BESIDE THE THING IT ENDS. "Deaktivieren" lives inside the
    // form, which starts closed — so a resident with a Sonderplan running saw a
    // status and one button labelled "Bearbeiten", and the only way to stop it
    // was to open an editor they did not want ("where is the deactivate",
    // 2026-10-05). Shown only while something is actually running: a button that
    // ends nothing is a question, not an action.
    const end = this.querySelector(".end-absence");
    if (end) {
      if (this._absenceRooms().length) end.removeAttribute("hidden");
      else end.setAttribute("hidden", "");
    }
    // Same rule for the boost: shown only while one is running. A permanent
    // "Boost beenden" beside "Boost setzen" would read as the other half of a
    // pair of settings rather than as a way out of something in progress.
    const eb = this.querySelector(".end-boost");
    if (eb) {
      if (this._boostRooms().length) eb.removeAttribute("hidden");
      else eb.setAttribute("hidden", "");
    }
  }

  /**
   * The Sonderplan fields. REBUILT ONLY WHEN THEIR MARKUP CHANGES: Home
   * Assistant pushes state changes all the time, and replacing an input a
   * resident is typing into drops what they typed and the focus with it.
   */
  _renderFields() {
    const f = this._form;
    const fields = this.querySelector(".fields");
    if (!fields) return;
    // The off-switch is a HOLIDAY field only — see absenceBody.
    const offField = f.kind === "holiday"
      ? `<label class="chk"><input type="checkbox" class="off" ${f.off ? "checked" : ""}>`
        + ` Aus · Frostschutz</label>`
      : "";
    const showTemp = !(f.off && f.kind === "holiday");
    const tempField = offField +
      (showTemp
        ? `<label>🌡️ Zieltemp.<span class="in"><input type="number" class="temp" min="${TMIN}" `
          + `max="${TMAX}" step="0.5" value="${esc(f.temperature)}"><em>°C</em></span></label>`
        : "");
    const fieldsHtml = f.kind === "sick"
      ? `<label>⏱️ Dauer ab jetzt<span class="in">`
        + `<input type="number" class="hours" min="1" max="${SICK_MAX_HOURS}" value="${esc(f.hours)}">`
        + `<em>h</em></span></label>`
        + tempField
        + `<p class="hint wide">Beginnt sofort, höchstens ${SICK_MAX_HOURS} h. Danach gilt wieder der Wochenplan.</p>`
      : `<label>Von<span class="in"><input type="date" class="start" value="${esc(f.start)}">`
        + `<select class="starttime">${timeOpts(f.startTime)}</select></span></label>`
        + `<label>Bis<span class="in"><input type="date" class="end" value="${esc(f.end)}">`
        + `<select class="endtime">${timeOpts(f.endTime)}</select></span></label>`
        + tempField
        + `<p class="hint wide">Die Uhrzeit bei „Bis“ entscheidet, ab wann wieder normal geheizt `
        + `wird — sonst ist die Wohnung am Rückreisetag noch kalt.</p>`;
    if (fieldsHtml === this._fieldsHtml) return;
    this._fieldsHtml = fieldsHtml;
    fields.innerHTML = fieldsHtml;

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
  }

  /** The room chips. Rebuilt only when what they show changes — see _renderFields. */
  _renderRooms() {
    const f = this._form;

    // Room scope. Nothing selected means ALL — said in words, because an empty
    // row of checkboxes reads as "none" and would be the opposite of the truth.
    // ROOM SCOPE: one row of toggles, `Alle` first.
    //
    // It was a checkbox, a summary button and a collapsed list of checkboxes —
    // three controls for one job, and the state was unreadable: every chip the
    // same grey, the answer in small native boxes, and with `Alle` ticked the
    // room boxes were checked AND disabled, which looks exactly like selected.
    //
    // A dropdown was the other candidate and is worse on the device this is used
    // on: `<select multiple>` is a wheel on iOS that cannot express multi-select,
    // a modal on Android that no theme reaches, and ctrl-click on desktop. It
    // also hides the one thing this control exists to answer — what will this
    // touch — behind a tap.
    //
    // So: filled means it will be touched, outlined means it will not, and the
    // row is the answer without a tap. Above MAX_CHIPS rooms it collapses again,
    // because a flat with twelve of them is a wall of chips above the button
    // somebody actually came here to press.
    const rooms = this._rooms();
    const box = this.querySelector(".rooms");
    if (!box) return;
    if (!rooms.length) {
      const empty = '<span class="hint">Kein Raum mit Thermostat gefunden.</span>';
      if (this._roomsHtml !== empty) box.innerHTML = empty;
      this._roomsHtml = empty;
    } else {
      const open = rooms.length <= MAX_CHIPS || this._openRooms;
      const chip = (label, on, attr) =>
        `<button type="button" class="chip${on ? " on" : ""}" ${attr} `
        + `aria-pressed="${on}">${esc(label)}</button>`;
      const roomsHtml =
        chip("Alle", f.allRooms, 'data-all="1"')
        + (rooms.length > MAX_CHIPS
            ? `<button class="btn ghost toggle-rooms">`
              + `${esc(scopeLabel(this._hass.states, rooms, f, this._openRooms))}</button>`
            : "")
        + (open
            ? rooms.map((id) => chip(
                roomName(this._hass.states[id]) || id,
                f.allRooms || f.rooms.includes(id),
                `data-id="${esc(id)}"`)).join("")
            : "");
      if (roomsHtml === this._roomsHtml) return;
      this._roomsHtml = roomsHtml;
      box.innerHTML = roomsHtml;

      const allChip = box.querySelector("[data-all]");
      if (allChip) allChip.addEventListener("click", () => {
        f.allRooms = true;
        f.rooms = [];
        this._render();
      });
      const tr = box.querySelector(".toggle-rooms");
      if (tr) tr.addEventListener("click", () => {
        this._openRooms = !this._openRooms;
        this._render();
      });
      box.querySelectorAll("[data-id]").forEach((el) => {
        el.addEventListener("click", () => {
          Object.assign(f, toggleRoom(rooms, f, el.dataset.id));
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
