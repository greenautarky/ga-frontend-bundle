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
 * Hourly options for the holiday's start and end time.
 *
 * ON THE HOUR, 24 entries. It was every quarter hour, 96 of them, inherited
 * from the old generator's `input_select.override_start_time` — but that
 * precision belongs to a weekday heating plan, not to a holiday: nobody leaves
 * at 07:45 and needs the flat to know. 96 entries is a scroll on a phone to
 * reach the evening, and the quarters are 72 wrong answers in the way of the
 * right one ("no need to have time for each 15 mins, every 1 hour is enough",
 * 2026-10-20).
 *
 * STILL A LIST OF LITERAL STRINGS, which is the part of the old generator's
 * reasoning that survives: "option text is literal, so locale-independent - no
 * native 12h/AM-PM picker". A native `<input type="time">` renders as the
 * browser's locale decides, and a resident reading "02:00 PM" where the rest
 * of the card says 14:00 is a bug report.
 */
const TIME_OPTIONS = (() => {
  const out = [];
  for (let h = 0; h < 24; h++) out.push(`${String(h).padStart(2, "0")}:00`);
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
  return `Urlaub aktiv — ${what}${until ? ` · bis ${until}` : ""} · ${who}`;
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
  // ALWAYS A TEMPERATURE. "Aus · Frostschutz" was a checkbox on this form and
  // was removed on 2026-10-20 ("remove the Aus - Frostschutz option and only
  // keep the option to set the temp"): a holiday that switches the heating off
  // is one mis-tap away from a frozen flat, and "Alle AUS" already does it
  // deliberately, with the frost line beside it saying what it leaves behind.
  //
  // `switch_off` is still READ elsewhere — `overrideStatus` renders one that is
  // already stored on a device, set by an older card or by us. This card simply
  // no longer sends one.
  const t = Number(form.temperature);
  if (!Number.isFinite(t) || t < TMIN || t > TMAX) {
    return `Bitte eine Temperatur zwischen ${TMIN} und ${TMAX} °C angeben.`;
  }
  out.temperature = t;
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
    this._form = { kind: "holiday", hours: 6, temperature: 20,
                   start: "", end: "", startTime: "00:00", endTime: "12:00",
                   // `allRooms` is EXPLICIT. The first version treated "nothing
                   // ticked" as "all rooms", which reads as "none" — the old
                   // system had an `Alle Räume` switch for exactly this reason.
                   allRooms: true, rooms: [] };
    // Status is always visible; the form is not. An override whose status is only
    // visible where it was entered is the invisible override this card exists to
    // end. (ADR-0033, amendment 2026-09-23.)
    // The Urlaub box IS the section now: there is no "Bearbeiten" toggle to
    // open it, so it is always open.
    this._openForm = true;
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
      // KI FIRST, AND THE ORDER IS NOT A STYLE CHOICE.
      //
      // Why at all: a holiday does not change the room's mode — ga_heating's
      // `_HEAT_NOW` is only a boost and the balancing run — so it layers over
      // whatever each room happens to be in. Book one while two rooms are on
      // MANUELL and one on KI and the flat reads as three different things for
      // the whole holiday, with a stale manual period still counting down
      // underneath ("i activated urlaub on all rooms, now each room shows
      // different mode and tempertaure", 2026-10-21). Normalising first makes
      // the holiday the only thing in charge, and is the mirror of what ending
      // one already does.
      //
      // Why BEFORE the POST: a press on the room ends what somebody asked for
      // earlier — `_end_requested_overrides` pops an ACTIVE boost and absence.
      // Sent after, it would delete the holiday we had just written, in the one
      // case that matters most: a holiday that starts now.
      try {
        await this._hass.callService("climate", "set_hvac_mode",
          { entity_id: id, hvac_mode: "auto" });
      } catch (e) { /* the holiday still outranks the mode; carry on */ }
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
    const what = `${this._form.temperature} °C`;
    const until = this._form.kind === "sick"
      ? `für ${this._form.hours} h`
      : `vom ${this._form.start} ${this._form.startTime || "00:00"} `
        + `bis ${this._form.end} ${this._form.endTime || "12:00"}`;
    if (failed.length) {
      this._say("err", `${ok} von ${rooms.length} Räumen gesetzt — abgelehnt: ${failed.join("; ")}`);
    } else {
      this._say("ok", `Urlaub in ${ok} Räumen: ${what}, ${until}. Danach gilt wieder der Wochenplan.`);
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
  /**
   * Drop the holiday in `rooms` AND hand them back to KI. Returns how many.
   *
   * THE SECOND HALF IS THE POINT ("what happens when we deactivate the urlaub
   * schedue? it should set all thermostat back to KI", 2026-10-21).
   *
   * Deleting the override alone does NOT do it. An absence is a layer ON TOP of
   * the room's mode, never a change to it — ga_heating writes the stored mode
   * in exactly three places (a press on the room, a hand on the radiator, and a
   * takeover into manual), and ending a holiday is none of them. So removing it
   * reveals whatever was underneath: a room that was in KI comes back to KI by
   * itself, but one that was MANUELL or AUS when the holiday was booked stays
   * there — heating to a dial setting from a fortnight ago, or not heating at
   * all, with nothing on screen to explain why.
   *
   * ORDER MATTERS. The delete goes first: while the override is still stored it
   * outranks the room's own mode, so an `auto` sent before it would be
   * overwritten by the next tick.
   *
   * SCOPED TO THE ROOMS THAT HAD ONE. "All thermostats" means the ones the
   * holiday covered; a room the resident deliberately left out of it is not
   * ours to switch on because somebody came home.
   */
  async _endAbsenceIn(rooms) {
    let ok = 0;
    for (const id of rooms) {
      try {
        await this._hass.callApi("delete", "ga_heating/absence", { entity_id: id });
      } catch (e) { continue; }   // still held — do not claim it is back on plan
      try {
        await this._hass.callService("climate", "set_hvac_mode",
          { entity_id: id, hvac_mode: "auto" });
        ok += 1;
      } catch (e) { /* the holiday IS gone; counted by omission */ }
    }
    return ok;
  }

  async _endAbsence() {
    const rooms = this._absenceRooms();
    if (!rooms.length) return this._say("ok", "Kein Urlaub aktiv.");
    const ok = await this._endAbsenceIn(rooms);
    this._say(ok === rooms.length ? "ok" : "err",
      `Urlaub in ${ok} von ${rooms.length} Räumen beendet — sie folgen wieder dem Wochenplan.`);
  }

  async _cancelAbsence() {
    const rooms = this._selected();
    if (!rooms.length) return this._say("err", "Kein Raum ausgewählt.");
    // Same two steps as the button above: the holiday goes, and the rooms are
    // handed back to the plan rather than to whatever they were before it.
    const ok = await this._endAbsenceIn(rooms);
    this._say("ok",
      `Urlaub in ${ok} von ${rooms.length} Räumen aufgehoben — sie folgen wieder dem Wochenplan.`);
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
          <h4>Boost <button type="button" class="infobtn" data-tip="boost" aria-label="Erklärung Boost" aria-expanded="false">i</button></h4>
          <div class="tip boosttip" hidden>
            <span class="sub boosthint"></span>
            <span class="hint frosthint"></span>
          </div>
          <div class="quick">
            <button class="btn primary boost">Boost</button>
            <button class="btn ki planall">Alle → KI</button>
            <button class="btn aus offall">Alle AUS</button>
            <button class="btn ghost end-boost" hidden>Boost beenden</button>
          </div>
          <div class="ichb-section" hidden>
          <h4 class="rule">Hydraulischer Abgleich <span class="sub ichbhint"></span></h4>
          <div class="quick">
            <button class="btn ki ichb-start">Abgleich starten</button>
            <button class="btn ghost ichb-cancel" hidden>Abgleich abbrechen</button>
          </div>
          </div>
          <h4 class="rule sph">Urlaub <button type="button" class="infobtn" data-tip="urlaub" aria-label="Erklärung Urlaub" aria-expanded="false">i</button></h4>
          <div class="tip urlaubtip" hidden>
            <span class="hint">Die Uhrzeit bei „Bis“ entscheidet, ab wann wieder normal geheizt wird — sonst ist die Wohnung am Rückreisetag noch kalt.</span>
          </div>
          <div class="status"></div>
          <div class="statusactions">
            <button class="btn ghost end-absence" hidden>Urlaub beenden</button>
          </div>
          <div class="form">
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
        /* THE EXPLANATIONS LIVE BEHIND THIS. The page is for controls, not for
           prose ("we dont want extra text in the page", 2026-10-20), so each
           section's sentence moved into a panel the "i" opens. The button is
           sized off the heading's own font so it stays a small round marker
           next to the word and never grows into a second control. */
        ga-heating-actions-card .infobtn { font: inherit; font-size: .95em; line-height: 1;
          width: 1.5em; height: 1.5em; padding: 0; margin-left: 6px; vertical-align: middle;
          border-radius: 50%; cursor: pointer; font-weight: 700; text-transform: none;
          border: 1px solid var(--divider-color, #d8dedd);
          background: var(--secondary-background-color, #f2f5f4);
          color: var(--secondary-text-color, #5a6b68); }
        ga-heating-actions-card .infobtn[aria-expanded="true"] {
          border-color: var(--primary-color, #4A7D59); color: var(--primary-color, #4A7D59); }
        /* Open, it reads as a note ABOUT the heading above it, not as another
           row of the card: indented, quiet, and tight under the heading. */
        ga-heating-actions-card .tip { display: grid; gap: 4px; margin: -6px 0 2px;
          padding: 8px 10px; border-radius: 8px;
          background: var(--secondary-background-color, #f2f5f4);
          border-left: 3px solid var(--primary-color, #4A7D59); }
        ga-heating-actions-card .tip[hidden] { display: none; }
        /* The hints inside it were styled as part of a heading line before, so
           they need the caption treatment here instead. */
        ga-heating-actions-card .tip .sub, ga-heating-actions-card .tip .hint {
          font-size: .84em; text-transform: none; font-weight: 400; letter-spacing: 0;
          color: var(--secondary-text-color, #5a6b68); }
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

        /* THE THREE ACTIONS STAY A ROW, at every width ("place all 3 buttons
           next to each other", 2026-10-20).
           It was a grid with a 460px breakpoint that stacked them one per line,
           which is every phone this is used on — so on the device it asked for,
           the row he asked for did not exist.
           Flex rather than fixed columns because the row is not always three:
           the balancing block has two, and "Boost beenden" appears beside the
           boost only while one is running. "flex: 1 1 0" with "min-width: 0"
           gives whatever is visible equal widths and equal heights, and a
           hidden button costs nothing. */
        ga-heating-actions-card .quick { display: flex; flex-wrap: wrap; gap: 8px;
          align-items: stretch; }
        ga-heating-actions-card .quick .btn { flex: 1 1 0; min-width: 0; }
        /* The one exception: a way OUT of something running is not a fourth
           peer of the three that start things, and four across a phone is four
           things too narrow to read. Its own line, under them. */
        ga-heating-actions-card .quick .end-boost,
        ga-heating-actions-card .quick .ichb-cancel { flex: 1 0 100%; }
        /* Three German labels across 375px. The padding goes before the words
           do — "Alle AUS" wrapping to two lines is what makes a row of three
           look broken. */
        @media (max-width: 420px) {
          ga-heating-actions-card .quick .btn { padding: 11px 4px; font-size: .84em; }
        }
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
    const tfBtn = this.querySelector(".toggle-form");
    if (tfBtn) {
      tfBtn.addEventListener("click", () => {
        this._openForm = !this._openForm;
        this._render();
      });
    }
    // Explanations live behind the "i", so the page carries controls and not
    // paragraphs. Click toggles the matching .tip next to the heading.
    this.querySelectorAll(".infobtn").forEach((el) => {
      el.addEventListener("click", () => {
        const tip = this.querySelector(`.${el.dataset.tip}tip`);
        if (!tip) return;
        const open = tip.hasAttribute("hidden");
        if (open) tip.removeAttribute("hidden");
        else tip.setAttribute("hidden", "");
        el.setAttribute("aria-expanded", String(open));
      });
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
        ? `Läuft in ${nRooms(live.length, true)} · Ventile ganz offen.`
        : "Öffnet die Ventile kurzzeitig ganz.";
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
      // Internal feature: residents must not be able to start a balancing run,
      // so the service merely EXISTING no longer shows the section. It appears
      // only when we put `show_ichb: true` in the card config.
      const offered = Boolean(((this._hass.services || {}).ga_heating || {}).ichb)
        && Boolean(this._config && this._config.show_ichb);
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
   * The Urlaub fields.
   *
   * THE MARKUP CARRIES NO VALUES, and that is the whole point.
   *
   * It used to interpolate every current value into the HTML. So the markup
   * changed whenever a value did, the guard below let it through, and
   * `innerHTML` replaced the entire block — including the field the resident
   * was in the middle of. A date is typed day → month → year, and the input
   * fires `change` the moment the first two make something it can parse; that
   * re-render handed back a brand-new element, so the year had nowhere to land
   * ("i can enter day and month but year isnt working", 2026-10-20).
   *
   * Now the values go on the ELEMENTS (`_syncFieldValues`) and the markup is
   * fixed for a given kind, so the block is built once and the inputs survive.
   */
  _renderFields() {
    const f = this._form;
    const fields = this.querySelector(".fields");
    if (!fields) return;
    const tempField =
      `<label>\u{1F321}\uFE0F Zieltemp.<span class="in"><input type="number" class="temp" min="${TMIN}" `
      + `max="${TMAX}" step="0.5"><em>\u00B0C</em></span></label>`;
    const fieldsHtml = f.kind === "sick"
      ? `<label>\u23F1\uFE0F Dauer ab jetzt<span class="in">`
        + `<input type="number" class="hours" min="1" max="${SICK_MAX_HOURS}">`
        + `<em>h</em></span></label>`
        + tempField
      : `<label>Von<span class="in"><input type="date" class="start">`
        + `<select class="starttime">${timeOpts()}</select></span></label>`
        + `<label>Bis<span class="in"><input type="date" class="end">`
        + `<select class="endtime">${timeOpts()}</select></span></label>`
        + tempField;
    if (fieldsHtml !== this._fieldsHtml) {
      this._fieldsHtml = fieldsHtml;
      fields.innerHTML = fieldsHtml;

      const bind = (sel, key, cast) => {
        const el = fields.querySelector(sel);
        if (el) el.addEventListener("change", () => { f[key] = cast(el); this._render(); });
      };
      bind(".hours", "hours", (el) => Number(el.value));
      bind(".temp", "temperature", (el) => Number(el.value));
      bind(".start", "start", (el) => el.value);
      bind(".end", "end", (el) => el.value);
      bind(".starttime", "startTime", (el) => el.value);
      bind(".endtime", "endTime", (el) => el.value);

      // PICK IT, DO NOT TYPE IT ("i want to change it in a way that we a pick a
      // date from the calendar"). A date input opens its calendar only from the
      // small icon at its end, which leaves typing as the obvious path on a
      // phone. This makes the whole field open it.
      for (const sel of [".start", ".end"]) {
        const el = fields.querySelector(sel);
        if (!el) continue;
        const open = () => {
          // Throws without a user gesture, and is absent in older browsers. In
          // both cases the field still types the way it always did.
          try { if (el.showPicker) el.showPicker(); } catch (e) { /* typing still works */ }
        };
        el.addEventListener("click", open);
        el.addEventListener("focus", open);
      }
    }
    this._syncFieldValues();
  }

  /**
   * The current values, written onto the fields rather than into their markup.
   *
   * NEVER ONTO THE FIELD THAT HAS FOCUS. Assigning `.value` to a date input
   * restarts it at its first segment, which would bring back the bug the
   * method above exists to fix, from the other direction.
   */
  _syncFieldValues() {
    const f = this._form;
    const active = this.ownerDocument ? this.ownerDocument.activeElement : null;
    const set = (sel, v) => {
      const el = this.querySelector(sel);
      if (!el || el === active) return;
      if (String(el.value) !== String(v)) el.value = v;
    };
    set(".hours", f.hours);
    set(".temp", f.temperature);
    set(".start", f.start);
    set(".end", f.end);
    set(".starttime", f.startTime || "00:00");
    set(".endtime", f.endTime || "12:00");

    // THE RANGE, SAID IN THE CALENDAR. `absenceBody` still refuses a holiday
    // that runs backwards, but a refusal after pressing Aktivieren is a
    // lesson; days greyed out in the picker are an answer before the mistake.
    // A holiday cannot start in the past either — that override would be
    // stored and already over.
    const today = localISO(new Date()).slice(0, 10);
    const start = this.querySelector(".start");
    const end = this.querySelector(".end");
    if (start && start.min !== today) start.min = today;
    const endMin = f.start || today;
    if (end && end.min !== endMin) end.min = endMin;
  }
}

customElements.define("ga-heating-actions-card", GaHeatingActionsCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-heating-actions-card",
  name: "GA Heizung — Ganzes Zuhause",
  description: "Boost für alle Räume und Urlaub.",
});
