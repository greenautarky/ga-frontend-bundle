/**
 * ga-heating-log-card — the last few changes to a room, with timestamps.
 *
 * Asked for on 2026-09-30: "what happened to this room, and when".
 *
 * WHY NOT THE CORE LOGBOOK CARD. Two reasons, and either one is fatal:
 *
 *  1. A GA device has no `default_config`, and `ga_packages/ga_integrations.yaml`
 *     loads `history:` and NOT `logbook:` — so `/api/logbook` answers 404 here.
 *     Measured on a resident test device, 2026-09-30.
 *  2. Even with it loaded it would show the wrong half. The logbook records
 *     STATE changes; a room's setpoint is an ATTRIBUTE. "21 → 23 °C" — the thing
 *     a resident actually did — would never appear in it.
 *
 * So this reads `history/period`, which records state AND attributes, and diffs
 * consecutive points itself.
 *
 * TWO SOURCES, AND THE BETTER ONE WINS. Since ga_heating 0.12.0 the room entity
 * publishes `attributes.changes` — the same events, each carrying WHY it happened
 * (resident, plan, boost, window, absence, a hand on the radiator, a manual period
 * expiring). That is knowledge only the component has: in the recorder, a boost and
 * a resident pressing + are the same two numbers. When the attribute is there the
 * card renders it and makes no request at all; where it is missing — an older
 * device — it falls back to diffing `history/period`, and then says only WHAT
 * changed, never why, because guessing the reason is exactly the failure this card
 * would otherwise institutionalise.
 *
 * Config:
 *   type: custom:ga-heating-log-card
 *   entity: climate.wohnzimmer
 *   count: 3                       # optional, default 3
 *   hours: 72                      # optional, default 72 — the window searched
 *   title: "Letzte Änderungen"     # optional, default none
 */

//: KEPT, not shown. Five entries are held and the list is capped at the height
//: of three, so the card looks the same until a resident scrolls — a balancing
//: run alone writes four lines into a room (started, the setpoint up, the
//: An icon name is CONFIG that lands in an HTML attribute, so it cannot be
//: escaped as text the way a title is — a quote in it would close the attribute
//: and everything after would be parsed as markup. Only a plain mdi name passes;
//: anything else renders no icon rather than something unsafe. (Same reasoning as
//: the escaping pass in 1.23.3.)
const SAFE_ICON = /^mdi:[a-z0-9-]+$/;

//: setpoint back, ended) and three would hide everything that came before it
//: (asked for 2026-10-08).
const DEFAULT_COUNT = 5;

//: How many rows are visible before the list scrolls. Rows vary in height, so
//: this is applied as a max-height computed from the row height below rather
//: than as a count.
const VISIBLE_ROWS = 3;
const DEFAULT_HOURS = 72;

//: A room's own modes, in the resident's words. Same mapping as
//: ga-thermostat-card: KI = auto, MANUEL = heat, AUS = off.
const MODE_WORDS = { auto: "KI", heat: "MANUEL", off: "AUS" };

//: ga_heating's `source` vocabulary, in the resident's words: WHO, and then WHY
//: where the why is not obvious from the who.
//:
//: "Benutzer" / "System" is the question a resident actually asks of a log —
//: was that me, or did the heating do it? — and it is the first thing each line
//: answers (asked for 2026-10-04). A boost and a holiday sit on the BENUTZER
//: side: somebody asked for them, even though the system carried them out at a
//: moment nobody picked.
//:
//: "Manuell" would have been the obvious German for the user side and is
//: deliberately not used: MANUEL is a MODE on the thermostat card beside this
//: one, and a log saying "Manuell" about a press that chose KI would read as a
//: contradiction. Home Assistant's own German has no user/system pair to borrow
//: — its logbook says "ausgelöst durch <X>" — so this follows that shape with
//: the actor first.
//:
//: The reason is dropped where it would only restate the actor: a resident
//: pressing a button needs no "· Bedienung" after "· Benutzer", and a hand on
//: the radiator is still the user.
const SOURCE_WORDS = {
  resident: { who: "Benutzer", why: "" },
  valve: { who: "Benutzer", why: "" },
  boost: { who: "Benutzer", why: "Boost" },
  absence: { who: "Benutzer", why: "Urlaub" },
  plan: { who: "System", why: "Heizplan" },
  window: { who: "System", why: "Fenster" },
  expiry: { who: "System", why: "Zeit abgelaufen" },
  balancing: { who: "System", why: "Einregulierung" },
};

//: Re-reading the whole window on every state update would hammer the recorder
//: for a card that changes a few times a day. A refetch is scheduled only when
//: the entity reports a NEW last_updated, and then not more often than this.
const REFETCH_DEBOUNCE_MS = 2000;

const STYLE = `
  ga-heating-log-card .ga-body { padding: 12px 16px 14px; }
  ga-heating-log-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 8px;
    display: flex; align-items: center; gap: 7px; }
  ga-heating-log-card .hdr ha-icon { --mdc-icon-size: 19px; opacity: .85; }
  /* FIVE KEPT, THREE SHOWN. A row is 14px text with 5px padding either side and
     a 1px rule between, so three come to about 90px; the cap is set a little
     over that so the fourth row is clipped mid-line and the list reads as
     scrollable rather than as if it ended. overscroll-behavior keeps a flick
     inside the card instead of scrolling the dashboard behind it. */
  ga-heating-log-card ul { list-style: none; margin: 0; padding: 0;
    max-height: 96px; overflow-y: auto; overscroll-behavior: contain;
    scrollbar-width: thin; }
  ga-heating-log-card li { display: flex; align-items: baseline; gap: 10px;
    padding: 5px 0; font-size: 14px; }
  ga-heating-log-card li + li { border-top: 1px solid var(--divider-color, #e0e0e0); }
  /* The time is the column a reader scans, so it is fixed-width and first. */
  ga-heating-log-card .when { flex: 0 0 auto; min-width: 104px; font-size: 13px;
    opacity: .6; font-variant-numeric: tabular-nums; }
  ga-heating-log-card .what { flex: 1 1 auto; }
  ga-heating-log-card .what ha-icon { --mdc-icon-size: 16px; vertical-align: -3px;
    opacity: .7; margin-right: 4px; }
  ga-heating-log-card .why { opacity: .55; }
  ga-heating-log-card .quiet { opacity: .6; font-size: 13px; padding: 4px 0; }
`;

/** `21` -> `"21,0"`. German decimal comma, one place, like the rest of the UI. */
function temp(v) {
  return Number(v).toFixed(1).replace(".", ",");
}

/**
 * The changes in a history window, oldest first.
 *
 * A point is emitted only when the MODE or the SETPOINT differs from the one
 * before it. History carries a point per recorded update — on a quiet room most
 * of them are the measured temperature moving by a tenth, and a log that listed
 * those would bury the one line a resident is looking for.
 *
 * The first point is the state at the start of the window, not a change, so it
 * seeds `prev` and is never emitted. A window whose first point IS the change
 * therefore shows one entry fewer than a longer window would — correct, because
 * we cannot know what came before without asking for more history.
 */
function changesFrom(points) {
  const out = [];
  let prev = null;
  for (const p of points || []) {
    if (!p || typeof p.state !== "string") continue;
    const a = p.attributes || {};
    // `Number(null)` is 0, not NaN — so a thermostat reporting no setpoint used
    // to enter the log as "Soll 0,0 °C", a temperature nobody set and the valve
    // cannot hold. Caught by CI, 2026-10-01.
    const raw = a.temperature;
    const t = raw == null ? NaN : Number(raw);
    const cur = { mode: p.state, target: Number.isFinite(t) ? t : null };
    const when = p.last_changed || p.last_updated;
    if (prev) {
      if (cur.mode !== prev.mode) {
        out.push({ when, kind: "mode", from: prev.mode, to: cur.mode });
      }
      // A setpoint that moves WITH the mode is one event, not two: switching a
      // room off takes its target with it, and two lines for one press reads
      // like the heating did something twice.
      if (cur.target !== prev.target && cur.mode === prev.mode && cur.target != null) {
        out.push({ when, kind: "target", from: prev.target, to: cur.target });
      }
    }
    prev = cur;
  }
  return out;
}

/**
 * The component's own entries, in this card's shape.
 *
 * `attributes.changes` is already newest-first (changelog.recent reverses the
 * ring), and `at` is its timestamp. Renaming it here rather than at every use
 * keeps one shape in the renderer whichever source answered.
 */
function fromAttribute(changes) {
  if (!Array.isArray(changes)) return null;
  return changes
    .filter((e) => e && (e.kind === "mode" || e.kind === "target" || e.kind === "event"))
    .map((e) => ({ when: e.at, kind: e.kind, from: e.from, to: e.to, source: e.source }));
}

//: WHAT HAPPENED, for the entries that are an event rather than a value moving.
//: A balancing run writes its setpoints into the log already; these are the two
//: lines that say what those setpoints were for, so a resident who was out can
//: read the hour without knowing what "Einregulierung" means.
const EVENT_WORDS = {
  ichb_started: { icon: "mdi:scale-balance", text: "Hydraulischer Abgleich gestartet" },
  ichb_ended: { icon: "mdi:scale-balance", text: "Hydraulischer Abgleich beendet" },
  ichb_cancelled: { icon: "mdi:scale-balance", text: "Hydraulischer Abgleich abgebrochen" },
};

/** One entry as `{icon, text, why}` — the words a resident reads. */
function describe(entry) {
  const s = SOURCE_WORDS[entry.source];
  const why = s ? [s.who, s.why].filter(Boolean).join(" · ") : "";
  if (entry.kind === "event") {
    // THE ACTOR ONLY. An event names itself — "Hydraulischer Abgleich
    // abgebrochen" — so appending the reason gave "... · System ·
    // Einregulierung", which says the same thing twice in two vocabularies
    // (seen on a device, 2026-10-08). Same rule the table above already
    // follows for a resident at a button: drop the reason where it only
    // restates what the line says.
    //
    // An unknown event renders its own key rather than nothing: a line a
    // resident cannot read still beats a line that silently disappears.
    const e = EVENT_WORDS[entry.to];
    return { icon: e ? e.icon : "mdi:information-outline",
             text: e ? e.text : String(entry.to), why: s ? s.who : "" };
  }
  if (entry.kind === "mode") {
    const from = MODE_WORDS[entry.from] || entry.from;
    const to = MODE_WORDS[entry.to] || entry.to;
    return { icon: "mdi:tune-variant", text: `${from} → ${to}`, why };
  }
  return {
    icon: "mdi:thermometer",
    text: `Soll ${entry.from == null ? "–" : temp(entry.from)} → ${temp(entry.to)} °C`,
    why,
  };
}

/**
 * "Heute 14:32", "Gestern 09:15", "Mo 07:00", "28.09. 07:00".
 *
 * A bare clock time is ambiguous the moment an entry is older than today, and a
 * full date on something that happened an hour ago is noise. `now` is a
 * parameter so the test can pin a day boundary instead of waiting for one.
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
 * Text for HTML. Names and texts from Home Assistant (entity names, room names,
 * attributes, stored plans) are escaped before they are rendered, so they show
 * as written. Every first-party card carries this same helper; a test keeps the
 * copies identical.
 */
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

class GaHeatingLogCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !String(config.entity).startsWith("climate.")) {
      throw new Error("ga-heating-log-card: `entity` must be a climate entity");
    }
    this._config = config;
    this._count = Number(config.count) > 0 ? Number(config.count) : DEFAULT_COUNT;
    this._icon = typeof config.icon === "string" ? config.icon : "";
    this._hours = Number(config.hours) > 0 ? Number(config.hours) : DEFAULT_HOURS;
    this._entries = null;
    this._error = null;
  }

  getCardSize() { return 2; }

  set hass(hass) {
    this._hass = hass;
    const s = hass && hass.states[this._config.entity];
    const published = s && fromAttribute(s.attributes && s.attributes.changes);
    if (published) {
      // The component answered. No request, no recorder read, and every entry
      // carries its reason — so the history path below is never entered on a
      // device running ga_heating 0.12.0 or newer.
      this._entries = published;
      this._error = null;
      this._render();
      return;
    }
    const stamp = s && (s.last_updated || s.last_changed);
    if (this._entries === null && !this._loading) {
      this._load();
    } else if (stamp && stamp !== this._stamp) {
      // The room just reported something. It may or may not be a change we log —
      // the diff decides that, not this — but it is the only signal we get.
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this._load(), REFETCH_DEBOUNCE_MS);
    }
    this._stamp = stamp;
    if (!this._root) this._render();
  }

  async _load() {
    if (!this._hass) return;
    this._loading = true;
    const start = new Date(Date.now() - this._hours * 3600000).toISOString();
    const path = `history/period/${start}?filter_entity_id=${encodeURIComponent(this._config.entity)}`;
    try {
      const res = await this._hass.callApi("get", path);
      const points = Array.isArray(res) && Array.isArray(res[0]) ? res[0] : [];
      // Oldest-first from the diff; the renderer wants newest-first, which is the
      // order the component's own attribute already uses.
      this._entries = changesFrom(points).reverse();
      this._error = null;
    } catch (e) {
      // A window with nothing in it and a window we could not read are different
      // answers, and a card that renders both as "keine Änderungen" is lying
      // about one of them.
      this._error = String((e && e.message) || e);
      this._entries = null;
    }
    this._loading = false;
    this._render();
  }

  _render() {
    if (!this._root) {
      this._root = document.createElement("ha-card");
      const style = document.createElement("style");
      style.textContent = STYLE;
      this.appendChild(style);
      this.appendChild(this._root);
    }
    this._root.innerHTML = `<div class="ga-body">${this._headerHtml()}${this._listHtml()}</div>`;
  }

  _headerHtml() {
    const t = this._config.title;
    if (!t) return "";
    // The icon is config, so it is NOT escaped as text — it is an attribute
    // value, and a quote in it would break out of the attribute. Only an mdi
    // name is let through.
    const ic = SAFE_ICON.test(this._icon || "")
      ? `<ha-icon icon="${this._icon}"></ha-icon>` : "";
    return `<div class="hdr">${ic}${esc(t)}</div>`;
  }

  _listHtml() {
    if (this._error) {
      return `<div class="quiet">Verlauf nicht verfügbar.</div>`;
    }
    if (this._entries === null) {
      return `<div class="quiet">Wird geladen …</div>`;
    }
    if (!this._entries.length) {
      return `<div class="quiet">Keine Änderungen in den letzten ${this._hours} Stunden.</div>`;
    }
    const now = new Date();
    const last = this._entries.slice(0, this._count);
    return `<ul>${last.map((e) => {
      const d = describe(e);
      const why = d.why ? `<span class="why"> · ${d.why}</span>` : "";
      return `<li><span class="when">${formatWhen(e.when, now)}</span>` +
        `<span class="what"><ha-icon icon="${d.icon}"></ha-icon>${esc(d.text)}${why}</span></li>`;
    }).join("")}</ul>`;
  }
}

customElements.define("ga-heating-log-card", GaHeatingLogCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ga-heating-log-card",
  name: "GA Heating Log Card",
  description: "The last few changes to a room's heating, with timestamps — first-party.",
});
