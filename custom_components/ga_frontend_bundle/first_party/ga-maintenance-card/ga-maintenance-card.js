/**
 * Wartung — what in this room needs a person, and nothing else.
 *
 * Asked for on 2026-10-05: the battery reading had been a single badge at the
 * top of the room, `batts.slice(0, 1)` — one number for a room that may hold
 * three battery devices, with no way to tell WHICH one it came from. A room
 * with a healthy valve and a dying thermometer showed 100 %.
 *
 * So the reading moves here and becomes a STATEMENT instead of a number: a line
 * appears only when something is actually low, and it names the device. A
 * resident does not want to read five percentages and do the comparing; they
 * want to be told when to buy batteries.
 *
 * WHOSE BATTERIES. Only the room's own heating devices — its valves and its
 * thermometers — and the card is given that list rather than finding one. "Any
 * battery entity in this area" would have swept up the Home Assistant companion
 * app: on the first device this was written against, a phone's
 * `sensor.<name>_battery_level` sat at 15 %. Telling a resident their
 * heating needs maintenance because someone's phone is flat is worse than
 * saying nothing.
 *
 * ROOM FOR WHAT COMES NEXT. Heating malfunctions belong in this section too (a
 * valve that stopped answering, a plan that will not mirror) — `_rows()` is
 * where they join, and the empty state already speaks for the whole section
 * rather than for batteries alone.
 */

/**
 * What a battery reading MEANS, because a percentage does not mean anything.
 *
 * "i want to have classes and not show numbers" (2026-10-05), and the reading
 * on screen the day that was said proves the point: 46 %. Is that fine? Worth a
 * trip to the shop? A resident cannot know, and neither can we — a TRVZB at
 * 46 % may run all winter. The number is the card's working, not its answer.
 *
 * TWO BANDS, because there are two different actions:
 *
 *   NIEDRIG     put batteries on the shopping list. Home Assistant's own German
 *               for a `battery` binary_sensor in its low state is "Niedrig", so
 *               taking that word means this card and a stock HA page never call
 *               the same condition two things — the same rule that gave us
 *               "Leerlauf" and "Aktivität".
 *   FAST LEER   change them now. Said in plain German rather than "kritisch":
 *               it tells a resident what is true of the battery instead of how
 *               alarmed to be, and "kritisch" on a heating dashboard reads like
 *               a fault in the heating.
 *
 * 30 AND 20, decided by the product owner on 2026-10-05. A resident gets a
 * month or so of "niedrig" to buy batteries and a clear second warning once a
 * valve is genuinely near the end.
 *
 * The known cost, written down so nobody rediscovers it as a bug: a TRVZB
 * reports coarsely — 100, 97, 80, 46 observed across one flat in one afternoon
 * — so a valve can step from above 30 straight into the critical band and the
 * "niedrig" warning is never seen for that device. The second band still fires,
 * which is the one that must not be missed. If that turns out to happen often,
 * widening the gap is the fix, not lowering both.
 */
const BATTERY_BANDS = [
  { at: 20, level: "critical", word: "Batterie fast leer",
    icon: "mdi:battery-alert-variant-outline" },
  { at: 30, level: "low", word: "Batterie niedrig", icon: "mdi:battery-low" },
];

//: The reading above which nothing is said at all — the widest band's edge, so
//: the threshold cannot drift away from the bands it is meant to match.
const LOW_BATTERY_PCT = Math.max(...BATTERY_BANDS.map((b) => b.at));

/** The band a reading falls in, or null when the battery is fine. */
function batteryBand(pct) {
  return BATTERY_BANDS.find((b) => pct <= b.at) || null;
}

/**
 * A GA asset label, tidied — `THD-SON-00000202` becomes `THD-SON-202`.
 *
 * Returns null for anything that is not one. The zeros are padding for a
 * database key, and reading them off a sticker to compare with a screen is work
 * the screen should have done.
 */
function gaLabel(text) {
  const m = /^([A-Z]{2,4})-([A-Z]{2,4})-0*(\d+)$/.exec(String(text || "").trim());
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

//: The suffixes Zigbee2MQTT and HA append to a DEVICE's name to make a sensor's.
//: Stripped so the row names the device, not the reading: a line reading
//: "Thermostat 1 Linkqualität — Funkverbindung schwach" says the same word twice
//: (CI, 2026-10-06). Both languages, because the fleet runs German front ends over
//: English integration defaults.
const SENSOR_SUFFIX = /\s*(Batterie|Battery( level)?|Linkqualit(ä|ae)t|Link ?quality|Signal(stärke|starke)?)\s*$/i;

//: What a MEASUREMENT sensor's name ends with. Stripped only where the row is
//: about the device rather than about one reading, which is what lets
//: "Klimasensor 1 Temperatur" and "Klimasensor 1 Luftfeuchtigkeit" be
//: recognised as one box on one wall ("its either completely offline, then we
//: just say offline not 2 messages", 2026-10-27).
//:
//: NOT added to SENSOR_SUFFIX. That one names the device for a battery or a
//: radio row, where the reading is already implied by the row's own words; this
//: one has to leave "Temperatursensor" available to say WHICH half went quiet
//: when only one did.
const MEASURE_SUFFIX = /\s*(Temperatur(e)?|Luftfeuchtigkeit|Feuchtigkeit|Feuchte|Humidity)\s*$/i;

/**
 * "Heute 14:32", "Gestern 09:15", "Mo 07:00", "28.09. 07:00".
 *
 * The same function, deliberately, as ga-heating-log-card's: the two cards sit
 * one under the other in a room and a time written two ways in one column of
 * the eye is a worse bug than the duplication is. A test keeps the copies
 * identical, as it does for `esc`.
 */
function formatWhen(iso, now) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86400000);
  if (days <= 0) return `Heute ${hhmm}`;
  if (days === 1) return `Gestern ${hhmm}`;
  if (days < 7) return `${["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"][d.getDay()]} ${hhmm}`;
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}. ${hhmm}`;
}

/**
 * What to call the device a maintenance row is about.
 *
 * In order: a GA label if anything carries one, then the name a person gave it,
 * then the sensor's own name with its reading suffix removed — and never
 * the radio address, which is the one answer that cannot help anybody standing
 * in the room holding a screwdriver.
 *
 * No device on the fleet publishes a label yet (checked 2026-10-05: no label
 * registry, devices named "Thermostat 1"). The chain is written so that the day
 * one does, it is used without a second change.
 */
function deviceName(state) {
  const a = (state && state.attributes) || {};
  // STRIPPED BEFORE the label is looked for, not after. A battery sensor is
  // named after its device plus " Batterie", so `THD-SON-00000202 Batterie`
  // never matched the label shape and fell through to the raw name — the padded
  // form, which is the one thing this was asked to stop showing (caught in a
  // browser, 2026-10-05).
  const friendly = String(a.friendly_name || "").trim()
    .replace(SENSOR_SUFFIX, "").trim();
  return gaLabel(a.ga_label) || gaLabel(friendly) || friendly || null;
}

//: LINK QUALITY, as Zigbee2MQTT reports it: 0-255, higher is better. The exact
//: number means different things on different coordinators, so these are
//: deliberately low: a radiator this far down is struggling on anyone's scale,
//: and the row says "weak", never a number a resident would try to compare.
//:
//: Enabled across the fleet on 2026-10-06. Every sensor reads `unknown` until its
//: device next reports, which for a battery TRV can be a long time - so an absent
//: or non-numeric reading must render NOTHING. Same rule, and the same reason, as
//: the battery band above: a missing value is not a bad value.
const LINK_BANDS = [
  { at: 15, level: "critical", word: "Funkverbindung sehr schwach",
    icon: "mdi:wifi-strength-alert-outline" },
  { at: 40, level: "low", word: "Funkverbindung schwach",
    icon: "mdi:wifi-strength-1" },
];

function linkBand(lqi) {
  return LINK_BANDS.find((b) => lqi <= b.at) || null;
}

//: NOT SHOWN HERE ANY MORE, deliberately. ga_heating still records every one of
//: them on the room as `valves_late` — a radiator that answered our own write
//: late ("antwortet verzögert"), and one that answered with a setpoint of its
//: own ("setzt eigenen Sollwert") — and still logs them. The card simply stopped
//: rendering them on 2026-10-20:
//:
//:   "that not something to include in the maintenance section, that a normal
//:    behavior, also the time it takes for teh command to be applied is not of
//:    interest to the user, we can keep this information hidden and logged in
//:    ga heating but dont show it"
//:
//: He is right about who it is for. A TRVZB restoring its stored setpoint when
//: we switch it to `heat` is firmware habit, not a fault, and ga_heating already
//: forgives it and drives the valve back; a 66 s answer is the radio being slow,
//: which nobody can act on by visiting the flat. Wartung is "what needs a
//: person" — a battery to buy, a sensor that stopped talking — and a line that
//: needs no person is how a maintenance section stops being read.
//:
//: Read them from `valves_late` on the room entity, or from the ga_heating log,
//: when diagnosing "the room went to MANUEL by itself".

//: Within one level, which KIND is read first: a battery outranks the radio, the
//: radio outranks what the radio cost us. Without it the sort keys of different
//: kinds are compared directly — a percentage against a link quality — and a
//: weak radio at 20 came out above a battery at 25 %.
//: A SILENT ROOM SENSOR comes first within its level. It is the one entry here
//: that changes what the heating is doing: ga_heating stops trusting the reading
//: An icon name is CONFIG that lands in an HTML attribute, so it cannot be
//: escaped as text the way a title is — a quote in it would close the attribute
//: and everything after would be parsed as markup. Only a plain mdi name passes;
//: anything else renders no icon rather than something unsafe. (Same reasoning as
//: the escaping pass in 1.23.3.)
const SAFE_ICON = /^mdi:[a-z0-9-]+$/;

//: and the room falls to the house average, so until somebody acts the room is
//: being heated on a number that is not its own.
const KIND_RANK = { sensor: 0, battery: 1, link: 2 };

//: How long ga_heating has to have heard nothing before it stops believing a room
//: sensor (ROOM_SENSOR_SILENCE, three hours). Not re-decided here — the card only
//: renders what the engine already concluded, so the two cannot disagree about
//: whether a room is measuring itself.

/** A reading that is actually a number, or null. Never `Number("")`, which is 0. */
function reading(state) {
  if (!state || state.state == null) return null;
  const text = String(state.state).trim();
  if (text === "") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/**
 * The maintenance lines for one room: `[{ kind, name, detail, sort }]`.
 *
 * Worst first, because a resident reads the first line. Exported shape rather
 * than markup so the ordering and the thresholds can be tested without a DOM.
 */
function maintenanceRows(states, batteries, extra) {
  const rows = [];
  const { links, climate } = extra || {};
  for (const id of batteries || []) {
    const s = states[id];
    if (!s) continue;
    // A sensor that has not reported is not a flat battery, and saying "0 %"
    // for one would send somebody to a radiator that is fine. Silence here is
    // honest; a device that has genuinely stopped answering is a MALFUNCTION,
    // which is the next thing this section learns to say.
    //
    // `Number()` IS NOT THE TEST. `Number("")` is 0, and so are `Number(null)`
    // and `Number("   ")` — all finite, all rendering "Batterie 0 %" for a
    // sensor that said nothing at all (caught in a browser, 2026-10-05; the
    // same shape as the missing setpoint that logged "Soll 0,0 °C"). A real
    // `"0"` is a reading and must still count, so the emptiness is tested
    // before the number is.
    if (s.state == null) continue;
    const text = String(s.state).trim();
    if (text === "") continue;
    const pct = Number(text);
    if (!Number.isFinite(pct)) continue;
    const band = batteryBand(pct);
    if (!band) continue;
    rows.push({
      kind: "battery",
      level: band.level,
      icon: band.icon,
      name: deviceName(s) || "Gerät",
      // The percentage never reaches the screen. It stays here as the sort key
      // so two devices in the same band still come out worst-first.
      detail: band.word,
      // WHEN this became true, as well as can be known: the percentage last
      // changed when it fell to where it is. Not the moment it crossed the
      // threshold, which nothing records — but on a battery that only falls,
      // the two are the same reading.
      when: (s.last_changed || s.last_updated) || null,
      sort: pct,
    });
  }
  // THE ROOM'S OWN VERDICT, WHERE THERE IS ONE (ga_heating 0.13.8+, `link_weak`).
  //
  // LQI is noisy by nature — it moves with the mains, a door, a person in the
  // hall. Measured on KIB-SON-00000055 on 2026-10-27, one climate sensor read
  // 108 and then 44 inside the same hour. Banding whatever arrived last does not
  // report a weak radio, it reports the last packet, and a device sitting near
  // the line makes this row appear and vanish between two refreshes of the same
  // screen ("only warn when the link has been weak for a while", 2026-10-27).
  //
  // The engine has the clock and the history, so it decides, exactly as it does
  // for `sensor_silent`: it publishes the band and when the link first fell into
  // it, and the card renders. The WORDS stay here — what crosses the wire is a
  // level, so the two cannot disagree about where the line is.
  //
  // `since` from the verdict is also a truer timestamp than the link sensor's
  // `last_changed`, which moves on every packet whether or not anything changed.
  const verdict = ((states[climate] || {}).attributes || {}).link_weak;
  if (verdict && typeof verdict === "object") {
    for (const [id, info] of Object.entries(verdict)) {
      const band = LINK_BANDS.find((b) => b.level === ((info || {}).level));
      if (!band) continue;
      const lqi = Number((info || {}).lqi);
      rows.push({
        kind: "link", level: band.level, icon: band.icon,
        name: deviceName(states[id]) || "Gerät",
        detail: band.word,
        when: (info || {}).since || null,
        sort: Number.isFinite(lqi) ? lqi : 0,
      });
    }
  } else {
    // A DEVICE STILL ON 0.13.7 OR OLDER publishes no verdict, and the attribute
    // is absent rather than empty — which is why this branches on the attribute
    // and not on its size. Falling back to the per-packet band keeps the row
    // working there; it flickers, as it always did, instead of disappearing.
    for (const id of links || []) {
      const lqi = reading(states[id]);
      if (lqi === null) continue;        // `unknown` is not a weak signal
      const band = linkBand(lqi);
      if (!band) continue;
      rows.push({
        kind: "link", level: band.level, icon: band.icon,
        name: deviceName(states[id]) || "Gerät",
        detail: band.word,
        when: (states[id].last_changed || states[id].last_updated) || null,
        sort: lqi,
      });
    }
  }

  // A ROOM SENSOR THAT HAS STOPPED TALKING (ga_heating 0.13.5+, `sensor_silent`).
  // The engine decides this, not the card: it has the device's heartbeat and the
  // measured threshold behind it. A dead sensor usually shows up as a flat battery
  // too, and both lines are shown — the battery says what to buy, this says what
  // it is costing.
  // SINCE, NOT A DURATION, and the card does the arithmetic. ga_heating publishes
  // when the device was last heard from and rewrites the room only when the
  // VERDICT changes; a duration in the attribute would differ every tick and cost
  // a state write per room per minute. So the age is computed here, which also
  // means the line stays current between republishes instead of ageing with them.
  //: ONE ROW PER DEVICE, not per entity. A climate sensor publishes a
  //: temperature and a humidity, so a box that stops talking stops talking
  //: TWICE and used to say so twice — two critical lines, same wall, same
  //: screwdriver ("when something is wrong with T&H, its either completely
  //: offline, then we just say offline not 2 messages", 2026-10-27).
  //:
  //: Grouped on the device name with its measurement suffix removed, which is
  //: the only handle the card has: `hass.states` carries no device id.
  const silent = ((states[climate] || {}).attributes || {}).sensor_silent || {};
  const quietDevices = new Map();
  for (const [sensor, info] of Object.entries(silent)) {
    const at = Date.parse(((info || {}).since) || "");
    if (!Number.isFinite(at)) continue;
    const quiet = (Date.now() - at) / 1000;
    if (!(quiet > 0)) continue;
    const named = deviceName(states[sensor]) || "";
    const device = named.replace(MEASURE_SUFFIX, "").trim() || named || "Sensor";
    const kind = (info || {}).kind === "humidity" ? "humidity" : "temperature";
    const seen = quietDevices.get(device)
      || { kinds: new Set(), at, quiet, since: (info || {}).since };
    seen.kinds.add(kind);
    // The longest silence wins: if one half stopped an hour before the other,
    // the box has been unreachable since the earlier one.
    if (at < seen.at) { seen.at = at; seen.quiet = quiet; seen.since = (info || {}).since; }
    quietDevices.set(device, seen);
  }
  for (const [device, seen] of quietDevices) {
    const hours = Math.floor(seen.quiet / 3600);
    const since = hours >= 1 ? `${hours} h` : `${Math.round(seen.quiet / 60)} min`;
    // Both halves gone means the DEVICE is gone, and that is what the line
    // should say. One half gone is a different fault and keeps the old words,
    // because then "meldet nicht" without a subject would be wrong.
    const what = seen.kinds.size > 1
      ? "Meldet nicht"
      : (seen.kinds.has("humidity") ? "Feuchtesensor meldet nicht"
                                    : "Temperatursensor meldet nicht");
    rows.push({
      kind: "sensor", level: "critical", icon: "mdi:thermometer-off",
      name: device,
      detail: `${what} (seit ${since})`,
      device,
      when: seen.since || null,
      // Longest silence first, and negative so the shared ascending sort keeps
      // the worst one at the top like every other kind.
      sort: -seen.quiet,
    });
  }

  //: A DEVICE THAT IS NOT TALKING HAS NO CURRENT SIGNAL STRENGTH. Its link
  //: sensor holds whatever it read when the device was last heard from, so a
  //: silent box used to collect a second, softer row saying its radio was weak
  //: — which reads as a contradiction of the critical row right above it
  //: ("if its still connected but has low LQI then it contradicts the other
  //: message that its offline", 2026-10-27).
  //:
  //: The reading is not thrown away: a weak last signal is the likeliest REASON
  //: the device went quiet, so it joins the silence row as a cause instead of
  //: standing against it as a separate claim.
  for (const row of rows) {
    if (row.kind !== "link" || !quietDevices.has(row.name)) continue;
    row.drop = true;
    const silentRow = rows.find((r) => r.kind === "sensor" && r.device === row.name);
    if (silentRow) silentRow.detail += " · Funk war zuletzt schwach";
  }

  // Worst first across every kind, because a resident reads the first line: a
  // flat battery outranks a weak signal outranks a slow answer. Within a level
  // each kind keeps its own sort key, so two weak radios still come out worst
  // first.
  const RANK = { critical: 0, low: 1 };
  const kept = rows.filter((r) => !r.drop);
  kept.sort((a, b) => (RANK[a.level] - RANK[b.level])
    || (KIND_RANK[a.kind] - KIND_RANK[b.kind]) || (a.sort - b.sort));
  return kept;
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

class GaMaintenanceCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._batteries = Array.isArray(config.batteries) ? config.batteries : [];
    this._links = Array.isArray(config.links) ? config.links : [];
    this._climate = typeof config.climate === "string" ? config.climate : null;
    this._icon = typeof config.icon === "string" ? config.icon : "";
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 2;
  }

  _rows() {
    const states = (this._hass && this._hass.states) || {};
    return maintenanceRows(states, this._batteries,
      { links: this._links, climate: this._climate });
  }

  _render() {
    if (!this._hass) return;
    const rows = this._rows();
    const title = this._config.title == null ? "Wartung" : this._config.title;
    const ic = SAFE_ICON.test(this._icon || "")
      ? `<ha-icon icon="${this._icon}"></ha-icon>` : "";
    const head = title ? `<div class="hdr">${ic}${esc(title)}</div>` : "";
    // "Nothing to do" is said out loud. A card that renders empty reads as one
    // that failed to load, which is the complaint the actions card's own status
    // line exists to answer — and here it is the difference between "we checked"
    // and "nobody is checking".
    // WHEN IT STARTED, in the column the activity card above puts it in. A
    // maintenance line without one answers "what is wrong" and not "since
    // when", and the second question is the one that says whether a weak radio
    // is a storm last night or a wall somebody built ("add the time when the
    // issue was logged", 2026-10-27).
    const now = new Date();
    const body = rows.length
      ? `<ul>${rows.map((r) =>
          `<li class="${r.level}">` +
          `<span class="when">${esc(r.when ? formatWhen(r.when, now) : "")}</span>` +
          `<span class="line"><ha-icon icon="${r.icon}"></ha-icon>` +
          `<span class="who">${esc(r.name)}</span> ` +
          `<span class="what">${esc(r.detail)}</span></span></li>`).join("")}</ul>`
      : `<p class="quiet">Keine Auffälligkeiten.</p>`;
    this.innerHTML = `<ha-card><div class="card-content">${head}${body}</div></ha-card>
      <style>
        /* MATCHED TO THE ACTIVITY CARD ABOVE IT, deliberately: the two sit one
           under the other in the same room view, and a title set in the browser
           default h2 next to one at body size read as a different level of
           heading ("make the font and size of wartung similar to aktivitat",
           2026-10-05). These are ga-heating-log-card's own numbers. */
        ga-maintenance-card .card-content { padding: 12px 16px 14px; }
        ga-maintenance-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 8px;
    display: flex; align-items: center; gap: 7px; }
  ga-maintenance-card .hdr ha-icon { --mdc-icon-size: 19px; opacity: .85; }
        /* THE ACTIVITY CARD'S OWN NUMBERS, not a second set that looks
           close ("make the maintenance section scrollable and same layout as
           activities", 2026-10-27). Three rows visible, the fourth clipped
           mid-line so the list reads as scrollable rather than as if it ended;
           overscroll-behavior keeps a flick inside the card instead of
           scrolling the dashboard behind it. */
        ga-maintenance-card ul { list-style: none; margin: 0; padding: 0;
          max-height: 96px; overflow-y: auto; overscroll-behavior: contain;
          scrollbar-width: thin; }
        ga-maintenance-card li { display: flex; align-items: baseline; gap: 10px;
          padding: 5px 0; font-size: 14px; }
        ga-maintenance-card li + li {
          border-top: 1px solid var(--divider-color, #e0e0e0); }
        /* The time is the column a reader scans, so it is fixed-width and
           first — the same 104px the activity card uses, so the two line up. */
        ga-maintenance-card .when { flex: 0 0 auto; min-width: 104px;
          font-size: 13px; opacity: .6; font-variant-numeric: tabular-nums; }
        ga-maintenance-card .line { flex: 1 1 auto; }
        /* The colour carries the same split as the word, so the two bands are
           told apart before either is read. */
        ga-maintenance-card .line ha-icon { --mdc-icon-size: 16px;
          vertical-align: -3px; margin-right: 4px; }
        ga-maintenance-card li.critical ha-icon { color: var(--error-color, #b3261e); }
        ga-maintenance-card li.low ha-icon { color: var(--warning-color, #f9a825); }
        ga-maintenance-card li.critical .what { color: var(--error-color, #b3261e); }
        /* The name carries the weight: it is the thing a resident has to find
           in the room. The reading is the reason, not the instruction. */
        ga-maintenance-card .who { font-weight: 600; }
        ga-maintenance-card .what { color: var(--secondary-text-color, #5a6b68); }
        ga-maintenance-card .quiet { margin: 0; font-size: .95em;
          color: var(--secondary-text-color, #5a6b68); }
      </style>`;
  }
}

customElements.define("ga-maintenance-card", GaMaintenanceCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-maintenance-card",
  name: "GA Maintenance Card",
  description: "What in a room needs a person: low batteries now, heating faults next — first-party.",
});
