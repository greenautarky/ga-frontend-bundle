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

//: A radiator that answered our own write late enough to be mistaken for a hand
//: on the dial. ga_heating publishes these per room as `valves_late`; it is the
//: cause behind "the room went to MANUEL by itself", which is otherwise invisible
//: here (reported 2026-10-06 on a resident device: 58 s late after a balancing
//: run). Under 30 s is not said: a TRV reports on its own cycle, and a few seconds
//: behind is normal.
const LATE_SECONDS_WORTH_SAYING = 30;

//: Within one level, which KIND is read first: a battery outranks the radio, the
//: radio outranks what the radio cost us. Without it the sort keys of different
//: kinds are compared directly — a percentage against a link quality — and a
//: weak radio at 20 came out above a battery at 25 %.
//: A SILENT ROOM SENSOR comes first within its level. It is the one entry here
//: that changes what the heating is doing: ga_heating stops trusting the reading
//: and the room falls to the house average, so until somebody acts the room is
//: being heated on a number that is not its own.
const KIND_RANK = { sensor: 0, battery: 1, link: 2, late: 3 };

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
      sort: pct,
    });
  }
  for (const id of links || []) {
    const lqi = reading(states[id]);
    if (lqi === null) continue;        // `unknown` is not a weak signal
    const band = linkBand(lqi);
    if (!band) continue;
    rows.push({
      kind: "link", level: band.level, icon: band.icon,
      name: deviceName(states[id]) || "Gerät",
      detail: band.word,
      sort: lqi,
    });
  }

  // A LATE RADIATOR, read from the room ga_heating publishes it on. No threshold
  // band: ga_heating only records an answer it had to forgive, so the entry
  // existing IS the finding — except a lag under 30 s, which is a TRV's own
  // reporting cycle and not worth a line.
  //
  // A RADIATOR THAT ANSWERED WITH ITS OWN SETPOINT (ga_heating 0.13.3,
  // `substituted`: how many times). Switched to `heat`, a TRVZB restores the
  // setpoint it last stored instead of keeping ours, so its answer is on time
  // (lag about 0) but carries a value we never sent. The lag rule above would
  // hide it, so it is said on its own; when one radiator has done both, one line
  // says both, because the row names a device and a device gets one line.
  const late = ((states[climate] || {}).attributes || {}).valves_late || {};
  for (const [valve, info] of Object.entries(late)) {
    const lag = Number((info || {}).lag_s);
    const isLate = Number.isFinite(lag) && lag >= LATE_SECONDS_WORTH_SAYING;
    const subs = Number((info || {}).substituted);
    const isSubstituted = Number.isFinite(subs) && subs > 0;
    if (!isLate && !isSubstituted) continue;
    const said = [];
    if (isLate) said.push(`antwortet verzögert (${Math.round(lag)} s)`);
    if (isSubstituted) {
      said.push(`setzt eigenen Sollwert${subs > 1 ? ` (${Math.round(subs)}×)` : ""}`);
    }
    rows.push({
      kind: "late", level: "low",
      icon: isLate ? "mdi:timer-sand" : "mdi:swap-horizontal",
      name: deviceName(states[valve]) || "Heizkörper",
      detail: said.join(", "),
      sort: 1000 - (isLate ? lag : 0),
    });
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
  const silent = ((states[climate] || {}).attributes || {}).sensor_silent || {};
  for (const [sensor, info] of Object.entries(silent)) {
    const at = Date.parse(((info || {}).since) || "");
    if (!Number.isFinite(at)) continue;
    const quiet = (Date.now() - at) / 1000;
    if (!(quiet > 0)) continue;
    const hours = Math.floor(quiet / 3600);
    const since = hours >= 1 ? `${hours} h` : `${Math.round(quiet / 60)} min`;
    const what = (info || {}).kind === "humidity" ? "Feuchtesensor" : "Temperatursensor";
    rows.push({
      kind: "sensor", level: "critical", icon: "mdi:thermometer-off",
      name: deviceName(states[sensor]) || what,
      detail: `${what} meldet nicht (seit ${since})`,
      // Longest silence first, and negative so the shared ascending sort keeps
      // the worst one at the top like every other kind.
      sort: -quiet,
    });
  }

  // Worst first across every kind, because a resident reads the first line: a
  // flat battery outranks a weak signal outranks a slow answer. Within a level
  // each kind keeps its own sort key, so two weak radios still come out worst
  // first.
  const RANK = { critical: 0, low: 1 };
  rows.sort((a, b) => (RANK[a.level] - RANK[b.level])
    || (KIND_RANK[a.kind] - KIND_RANK[b.kind]) || (a.sort - b.sort));
  return rows;
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
    const head = title ? `<div class="hdr">${esc(title)}</div>` : "";
    // "Nothing to do" is said out loud. A card that renders empty reads as one
    // that failed to load, which is the complaint the actions card's own status
    // line exists to answer — and here it is the difference between "we checked"
    // and "nobody is checking".
    const body = rows.length
      ? `<ul>${rows.map((r) =>
          `<li class="${r.level}"><ha-icon icon="${r.icon}"></ha-icon>` +
          `<span class="who">${esc(r.name)}</span>` +
          `<span class="what">${esc(r.detail)}</span></li>`).join("")}</ul>`
      : `<p class="quiet">Keine Auffälligkeiten.</p>`;
    this.innerHTML = `<ha-card><div class="card-content">${head}${body}</div></ha-card>
      <style>
        /* MATCHED TO THE ACTIVITY CARD ABOVE IT, deliberately: the two sit one
           under the other in the same room view, and a title set in the browser
           default h2 next to one at body size read as a different level of
           heading ("make the font and size of wartung similar to aktivitat",
           2026-10-05). These are ga-heating-log-card's own numbers. */
        ga-maintenance-card .card-content { padding: 12px 16px 14px; }
        ga-maintenance-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 8px; }
        ga-maintenance-card ul { list-style: none; margin: 0; padding: 0;
          display: grid; gap: 8px; }
        ga-maintenance-card li { display: flex; align-items: center; gap: 10px;
          font-size: .95em; }
        /* The colour carries the same split as the word, so the two bands are
           told apart before either is read. */
        ga-maintenance-card ha-icon { --mdc-icon-size: 20px; flex: none; }
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
