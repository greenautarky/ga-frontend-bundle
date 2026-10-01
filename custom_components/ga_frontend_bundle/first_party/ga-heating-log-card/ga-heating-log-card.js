/**
 * ga-heating-log-card — the last few changes to a room, with timestamps.
 *
 * Asked for on 2026-09-30: "what happened to this room, and when".
 *
 * WHY NOT THE CORE LOGBOOK CARD. Two reasons, and either one is fatal:
 *
 *  1. A GA device has no `default_config`, and `ga_packages/ga_integrations.yaml`
 *     loads `history:` and NOT `logbook:` — so `/api/logbook` answers 404 here.
 *     Measured on 100.126.209.15, 2026-09-30.
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

const DEFAULT_COUNT = 3;
const DEFAULT_HOURS = 72;

//: A room's own modes, in the resident's words. Same mapping as
//: ga-thermostat-card: KI = auto, MANUEL = heat, AUS = off.
const MODE_WORDS = { auto: "KI", heat: "MANUEL", off: "AUS" };

//: ga_heating's `source` vocabulary, in the resident's words. A source we do not
//: know is rendered as nothing rather than as its raw key: a newer component
//: inventing a reason must not put "window_contact_2" on someone's wall.
const SOURCE_WORDS = {
  resident: "Bedienung",
  valve: "am Heizkörper",
  plan: "Heizplan",
  boost: "Boost",
  absence: "Urlaub",
  window: "Fenster",
  expiry: "manuelle Zeit abgelaufen",
};

//: Re-reading the whole window on every state update would hammer the recorder
//: for a card that changes a few times a day. A refetch is scheduled only when
//: the entity reports a NEW last_updated, and then not more often than this.
const REFETCH_DEBOUNCE_MS = 2000;

const STYLE = `
  ga-heating-log-card .ga-body { padding: 12px 16px 14px; }
  ga-heating-log-card .hdr { font-weight: 600; opacity: .8; margin-bottom: 8px; }
  ga-heating-log-card ul { list-style: none; margin: 0; padding: 0; }
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
    const t = Number(a.temperature);
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
    .filter((e) => e && (e.kind === "mode" || e.kind === "target"))
    .map((e) => ({ when: e.at, kind: e.kind, from: e.from, to: e.to, source: e.source }));
}

/** One entry as `{icon, text, why}` — the words a resident reads. */
function describe(entry) {
  const why = SOURCE_WORDS[entry.source] || "";
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

class GaHeatingLogCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !String(config.entity).startsWith("climate.")) {
      throw new Error("ga-heating-log-card: `entity` must be a climate entity");
    }
    this._config = config;
    this._count = Number(config.count) > 0 ? Number(config.count) : DEFAULT_COUNT;
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
    return t ? `<div class="hdr">${t}</div>` : "";
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
        `<span class="what"><ha-icon icon="${d.icon}"></ha-icon>${d.text}${why}</span></li>`;
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
