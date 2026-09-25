/**
 * ga-home-strategy — GreenAutarky per-user home dashboard (ADR-0006 successor).
 *
 * ONE dashboard for the whole household — HA's default Overview. It is generated
 * in the browser on every load, for whoever is logged in — but this file is now
 * PURE PRESENTATION. It asks the server for a ready, already-scoped model and
 * renders it; it never touches the device/entity registries and never re-derives
 * who may see what:
 *
 *   GET /api/greenautarky_site/home_model
 *     → { scope, reason, is_master, user_name, areas_exist,
 *         rooms:   [ { area_id, name, climate[], lights[], switches[],
 *                      temps[], hums[], batts[] }, ... ],
 *         roomless:  { climate[], lights[], ... }   // house-wide user only
 *       }
 *
 * The component computes that model with the server's FULL hass, but returns only
 * entities the calling user can actually see (live state + native read
 * permission) — so nothing null ever reaches a card. That is the whole point of
 * #569: a room-scoped sub-user used to crash here because the client re-derived
 * the board from a leak-guard-filtered registry that still listed entities absent
 * from the user's scoped hass.states (e.g. a device `update.*` config entity) →
 * `hass.states[id]` = null → the board never rendered. The server now owns that
 * decision; this file only picks card TYPES from the handed model.
 *
 * ROBUSTNESS — the states a fleet device is actually in:
 *   1. no rooms in HA        → server returns everything in `roomless` → flat view
 *   2. no household set up    → server says scope=all → show everything
 *   3. component missing/404  → assume unmanaged; render the house flat from the
 *                               state machine (dev-only safety net)
 * A blank dashboard is only ever correct for a real sub-user who was granted
 * nothing — never for a device we simply have not configured yet.
 */

const ROOM_ICON = "mdi:door-open";
const HOUSE_ICON = "mdi:home-heart";

/* ---------------------------------------------------------------------------
 * Naming — a resident must never be shown a serial number
 *
 * zigbee2mqtt names a device it was never told a name for after its IEEE
 * address (`0x00124b00294cf4a1`), and HA derives every entity's friendly_name
 * from that. A tile with no `name` falls back to the friendly_name, so a
 * resident's "Geräte" list read as a column of 16-hex-digit addresses
 * (measured on a canary, 2026-09-15). The badges above the thermostat had
 * already been given explicit names for exactly this reason; the tiles had not.
 *
 * Deliberately NOT a rename: this only strips the address and keeps whatever
 * human text was around it (`0x0012… l1` -> `l1`, an endpoint a person chose).
 * A device that carries a real name is left completely alone — a cleaner that
 * renames everything is worse than the defect it replaces.
 * ------------------------------------------------------------------------- */

/** A z2m IEEE address, with or without the `0x`, as a whole word. */
const RADIO_ADDRESS = /\b(?:0x)?[0-9a-f]{16}\b/gi;

/** Last resort when stripping the address leaves nothing human behind. */
const DEVICE_CLASS_LABELS = {
  temperature: "Temperatur",
  humidity: "Luftfeuchtigkeit",
  battery: "Batterie",
  illuminance: "Helligkeit",
  pressure: "Luftdruck",
  power: "Leistung",
  energy: "Energie",
};
const DOMAIN_LABELS = {
  light: "Licht",
  switch: "Schalter",
  climate: "Heizung",
  sensor: "Messwert",
  binary_sensor: "Sensor",
  cover: "Rollladen",
  fan: "Lüftung",
  lock: "Schloss",
};

function prettify(text) {
  return String(text || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * A label a person can read. Always non-empty.
 *
 * It ALWAYS returns a name rather than "leave it to HA when the name is fine",
 * because "leave it to HA" is precisely the state that produced the defect: a
 * card without a `name` is indistinguishable, from the outside, from a card
 * whose name happens to be right. Naming every tile makes the rendered surface
 * assertable — on the device, an e2e can read the tiles and fail on a hex
 * address, which it cannot do for a name that is never written down.
 *
 * An entity somebody has actually named comes back unchanged.
 */
function humanLabel(hass, entityId) {
  const state = (hass && hass.states && hass.states[entityId]) || null;
  const attrs = (state && state.attributes) || {};
  const raw = String(attrs.friendly_name || "");

  RADIO_ADDRESS.lastIndex = 0;
  const hasAddress = RADIO_ADDRESS.test(raw);
  RADIO_ADDRESS.lastIndex = 0;

  if (raw && !hasAddress) return raw;        // already human — verbatim

  const stripped = prettify(raw.replace(RADIO_ADDRESS, " "));
  if (stripped) return stripped;             // `0x0012… l1` -> `l1`

  const label =
    DEVICE_CLASS_LABELS[attrs.device_class] ||
    DOMAIN_LABELS[String(entityId).split(".")[0]];
  if (label) return label;

  // Nothing at all to go on. Never return "" here: an empty name would put the
  // address straight back on the tile.
  return prettify(String(entityId).split(".")[1]) || String(entityId);
}

/** A device tile that always carries a readable name. */
function deviceTile(hass, entity) {
  return { type: "tile", entity, name: humanLabel(hass, entity) };
}

/** Is Home Assistant's `history` integration loaded on this instance? */
function historyAvailable(hass) {
  const components = (hass && hass.config && hass.config.components) || [];
  return Array.prototype.includes.call(components, "history");
}

/**
 * Strategy options — set in the dashboard config:
 *   `strategy: { type: "custom:ga-home", hide_household: true, ... }`
 *
 * Defaults are the product look piloted on KIB-SON-00000050 (2026-07-21):
 *   text_tabs         true      room NAMES as tab text (a row of identical door
 *                               icons distinguishes nothing)
 *   single_thermostat true      TRVs in one room are coupled — show ONE control
 *                               (and one heating plan), not one per valve
 *   thermostat_style  "setpoint" first-party ga-thermostat-card, three looks:
 *                               "setpoint" (DEFAULT — "Sollwert-Fokus", big
 *                               target; the fleet default set by Ramin, KB #162
 *                               / #518), "classic" (big value + setpoint +
 *                               AUS/MANUEL/KI), "dial" (round drag control).
 *                               "core" = built-in HA thermostat card; "simple" =
 *                               vendored simple-thermostat fallback. ("myvibe" =
 *                               old alias for classic.) Not resident-selectable
 *                               yet — admin/config only (selector = Odoo #571).
 *   hide_household    true      drop the "Haushalt" overview view. DEFAULT hidden
 *                               (resident-clean UI); set false to show it.
 *   hide_roomless     true      drop the "Ohne Raum" view. DEFAULT hidden; set
 *                               false to show devices without an area.
 */
function gaOptions(config) {
  const c = config || {};
  return {
    textTabs: c.text_tabs !== false,
    singleThermostat: c.single_thermostat !== false,
    thermostatStyle: (() => {
      // Our first-party ga-thermostat-card ships three looks (classic|dial|
      // setpoint); "core" = the built-in HA thermostat card; "simple" = the
      // vendored simple-thermostat fallback. "myvibe" is the old alias for
      // classic. The FLEET DEFAULT is "setpoint" ("Sollwert-Fokus", Ramin's
      // decision — KB #162 / #518); anything unset/unknown falls back to it.
      const v = c.thermostat_style === "myvibe" ? "classic" : c.thermostat_style;
      return ["classic", "dial", "setpoint", "core", "simple"].includes(v) ? v : "setpoint";
    })(),
    // DEFAULT CHANGED 2026-09-23 (Thomas): shown, as the LAST tab, renamed
    // "Einstellungen". It was hidden on 2026-09-08 for a resident-clean UI, and
    // that decision was about a "Haushalt" tab sitting FIRST — a settings tab at
    // the end is a different thing. `hide_household: true` still hides it.
    hideHousehold: c.hide_household === true,
    // DEFAULT: hidden. Set hide_roomless:false to show the roomless view.
    hideRoomless: c.hide_roomless !== false,
  };
}

/**
 * Ask the server for the READY scoped model. Never guess client-side.
 * A 404 means the component is not on this device (it was never put into
 * household mode) — assume unmanaged and render the house flat, never blank.
 */
async function fetchHomeModel(hass) {
  try {
    return await hass.callApi("get", "greenautarky_site/home_model");
  } catch (err) {
    const status = err && (err.status_code || err.status);
    if (status === 404) return { scope: "nocomponent", reason: "no-component" };
    return { scope: "error", reason: String((err && err.message) || err) };
  }
}

/* ---------------------------------------------------------------------------
 * Card builders — CORE CARDS ONLY (plus the two first-party cards we own).
 *
 * Deliberately no community cards beyond the vendored simple-thermostat fallback:
 * every third-party card is one more thing that can break a customer dashboard on
 * an HA update. Modern HA covers what the old MyVibe stack was for:
 *   simple-thermostat's KI/MANUEL/AUS → ga-thermostat-card / tile hvac-modes
 *   mushroom chips                    → `heading` card badges
 *   layout-card / card-mod            → `sections` view
 *   apexcharts daily range            → core `statistics-graph`
 * Every entity below already comes pre-classified AND states-validated from the
 * server, so there are no null reads and no client-side category logic.
 * ------------------------------------------------------------------------- */

/** The heating control card for one climate entity, per the chosen style. */
function thermostatCard(entity, roomName, style) {
  if (["classic", "dial", "setpoint"].includes(style)) {
    // FIRST-PARTY ga-thermostat-card (Odoo #518): one card, three looks
    // (classic = big value + setpoint + AUS/MANUEL/KI chips [default];
    // dial = round drag control; setpoint = big target). All talk straight to
    // climate.* services. The variant is chosen per device via config.
    return {
      type: "custom:ga-thermostat-card",
      entity,
      header: "Steuerung",
      ...(style === "classic" ? {} : { variant: style }),
    };
  }
  if (style === "simple") {
    // Fallback: the vendored community simple-thermostat, kept in the bundle
    // (coexistence, 1.4.0). Same AUS/MANUEL/KI mapping as ga-thermostat-card.
    return {
      type: "custom:simple-thermostat",
      entity,
      header: { name: "Steuerung" },
      hide: { temperature: true, state: true },
      layout: { mode: { icons: true, names: true, headings: false } },
      control: { hvac: {
        auto: { name: "KI", icon: "mdi:brain" },
        heat: { name: "MANUEL", icon: "mdi:hand-back-left" },
        off: { name: "AUS" },
      } },
      card_mod: { style: "h3.current--value { font-size: 35px; }" },
      tap_action: { action: "none" },
    };
  }
  // "core": the built-in HA thermostat card. Standard names (Auto/Heat/Off,
  // not renameable); the card title IS renameable, so we pass the room name.
  return {
    type: "thermostat",
    entity,
    name: roomName,
    features: [
      { type: "climate-hvac-modes", hvac_modes: ["auto", "heat", "off"], style: "icons" },
    ],
  };
}

/**
 * The room view sections, built from ONE pre-classified, states-validated room:
 *   { name, climate[], lights[], switches[], temps[], hums[], batts[] }
 */
function roomSections(room, opt, hass) {
  // Coupled TRVs (two valves on one room's radiators) mirror each other —
  // rendering both just shows the same state twice and doubles the Heizplan.
  const climateAll = room.climate || [];
  const climate = opt.singleThermostat ? climateAll.slice(0, 1) : climateAll;
  const temps = room.temps || [];
  const hums = room.hums || [];
  const batts = room.batts || [];
  const lights = room.lights || [];
  const switches = room.switches || [];

  // Named badges — the raw entities carry IEEE-address names on fleet devices.
  const badges = [];
  // Temperature badge FIRST, then humidity. The #1060 decision (2026-09-23) had
  // dropped it — "the resident acts on the target" — and was REVERSED for this
  // badge on 2026-09-25 at Thomas's request: the measured room temperature
  // belongs next to the humidity. The thermostat card stays setpoint-only.
  // Source: temps[0] — the model does not tell a room sensor from a valve's own
  // thermometer. Without a sensor, the thermostat's current_temperature, and
  // only if it is a number; otherwise no badge (never an empty one).
  if (temps.length) {
    badges.push({ type: "entity", entity: temps[0], name: "Temperatur" });
  } else if (climate.length) {
    const st = hass && hass.states && hass.states[climate[0]];
    if (st && typeof (st.attributes || {}).current_temperature === "number") {
      badges.push({ type: "entity", entity: climate[0], name: "Temperatur",
        state_content: "current_temperature" });
    }
  }
  for (const e of hums.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Luftfeuchtigkeit" });
  for (const e of batts.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Batterie" });

  const sections = [];

  // Heating — the control MyVibe called KI / MANUEL / AUS.
  if (climate.length) {
    const cards = [{ type: "heading", heading: "Heizung", heading_style: "title", badges }];
    for (const entity of climate) cards.push(thermostatCard(entity, room.name, opt.thermostatStyle));
    sections.push({ type: "grid", cards });
  }

  // Weekly plan — our own card, executed via climate.set_temperature (so it works
  // with ANY thermostat, not just the Zigbee TRV we happen to ship).
  for (const entity of climate) {
    sections.push({ type: "grid", cards: [
      { type: "heading", heading: "Heizplan", heading_style: "title" },
      { type: "custom:ga-heating-card", entity, title: room.name },
    ] });
  }

  // Climate history — MyVibe's "Daily Temperature / Humidity Range".
  //
  // Only when HA's `history` integration is actually loaded. `statistics-graph`
  // renders "Verlauf-Integration deaktiviert" when it is not, so building the
  // section regardless hands the resident a tile whose entire content is the
  // reason it is empty (measured on a canary, 2026-09-15).
  //
  // That is NOT the same as deciding history is optional. ga_manager's converge
  // writes `recorder:` into its own package file with a 7-day retention on
  // every device (`ga_recorder.yaml`, HA_RECORDER_DEFAULTS), and `history` is a
  // `default_config` dependency — so on a correctly converged device this
  // branch never runs. A device where it DOES run has a real defect, and the
  // warning below is what makes it findable instead of merely ugly.
  const history = [];
  const hasHistory = historyAvailable(hass);
  if (!hasHistory && (temps.length || hums.length)) {
    console.warn(
      "ga-home: the `history` integration is not loaded — the 24 h curves for " +
        (room.name || room.area_id) +
        " are omitted. On a converged GA device history is always on " +
        "(ga_manager writes recorder retention into ga_recorder.yaml), so this " +
        "is a device defect, not a display setting.",
    );
  }
  // ONE statistic per sensor, on purpose. `statistics-graph` labels every
  // series with the ENTITY's name and never says WHICH statistic it is, so
  // asking for min/mean/max drew three curves from one sensor under three
  // identical labels. A legend that names the same thing three times tells a
  // reader nothing, and it is worse than no legend because it reads like three
  // sensors. Measured on a bench device 2026-09-16 (#22).
  //
  // The mean is the one a resident asks for ("how warm was it"). The band is
  // worth having back the day we draw it ourselves and can label it; until
  // then it costs comprehension and buys nothing.
  if (hasHistory && temps.length) {
    history.push({ type: "statistics-graph", title: "Temperatur (24 h)", entities: temps,
      stat_types: ["mean"], days_to_show: 1, period: "hour" });
  }
  if (hasHistory && hums.length) {
    history.push({ type: "statistics-graph", title: "Luftfeuchtigkeit (24 h)", entities: hums,
      stat_types: ["mean"], days_to_show: 1, period: "hour" });
  }
  if (history.length) {
    sections.push({ type: "grid", cards: [
      { type: "heading", heading: "Verlauf", heading_style: "title" }, ...history] });
  }

  // Everything else a resident operates, as tiles.
  const rest = [...lights, ...switches];
  if (rest.length) {
    sections.push({ type: "grid", cards: [
      { type: "heading", heading: "Geräte", heading_style: "title" },
      ...rest.map((entity) => deviceTile(hass, entity)),
    ] });
  }

  if (!sections.length) {
    sections.push({ type: "grid", cards: [
      { type: "markdown", content: "_Für diesen Raum sind noch keine Geräte eingerichtet._" }] });
  }
  return sections;
}

/** Cards for a classified section without rooms (house-wide user / flat fallback). */
function classifiedCards(sec, hass) {
  const cards = [];
  const climate = sec.climate || [];
  if (climate.length) {
    cards.push({ type: "grid", columns: climate.length > 2 ? 2 : 1, square: false,
      cards: climate.map((e) => ({ type: "thermostat", entity: e })) });
  }
  const measured = [...(sec.temps || []), ...(sec.hums || []), ...(sec.batts || [])];
  if (measured.length) cards.push({ type: "entities", title: "Messwerte",
    entities: measured.map((e) => ({ entity: e, name: humanLabel(hass, e) })) });
  const rest = [...(sec.lights || []), ...(sec.switches || [])];
  if (rest.length) cards.push({ type: "entities", title: "Schalter",
    entities: rest.map((e) => ({ entity: e, name: humanLabel(hass, e) })) });
  return cards;
}

/* ---------------------------------------------------------------------------
 * Views
 * ------------------------------------------------------------------------- */

function errorView(message) {
  return {
    title: "Fehler",
    icon: "mdi:alert",
    cards: [{
      type: "markdown",
      content:
        "## Dein Zuhause konnte nicht geladen werden\n\n`" + message + "`\n\n" +
        "Bitte lade die Seite neu. Bleibt es dabei, wende dich an den Support.",
    }],
  };
}

function emptyView(name) {
  return {
    title: "Zuhause",
    icon: HOUSE_ICON,
    cards: [{
      type: "markdown",
      content:
        "# Willkommen, " + (name || "") + "!\n\n" +
        "Dir wurde noch **kein Raum** zugewiesen.\n\n" +
        "Bitte deinen Haushalts-Verwalter, dir Räume freizugeben.",
    }],
  };
}

/** House-wide user, but the device has no rooms: render everything flat. */
function noRoomsView(name, model, hass) {
  const cards = classifiedCards(model.roomless || {}, hass);
  const hint = {
    type: "markdown",
    content:
      "# Hallo " + name + "!\n\n" +
      (model.reason === "no-component" || model.reason === "unmanaged"
        ? "Dieses Gerät ist noch **nicht als Haushalt eingerichtet** — du siehst alles.\n\n"
        : "") +
      "Für dieses Zuhause sind noch **keine Räume** angelegt. " +
      "Sobald Räume eingerichtet sind, erscheint hier je Raum eine eigene Ansicht.",
  };
  return {
    title: "Zuhause",
    path: "zuhause",
    icon: HOUSE_ICON,
    cards: cards.length
      ? [hint, ...cards]
      : [hint, { type: "markdown", content: "_Es sind noch keine Geräte eingerichtet._" }],
  };
}

/**
 * No-component fallback (dev-only): the component isn't on this device, so there
 * is no model. Render the house flat straight from the state machine — never
 * blank. This deliberately does NOT touch the registries (the crash class #569
 * removed); a device without the component also has no sub-users, so a flat
 * everything-view is both safe and correct.
 */
function flatFallbackView(name, hass) {
  const ids = Object.keys(hass.states);
  const byDomain = (d) => ids.filter((e) => e.startsWith(d + "."));
  const sec = {
    climate: byDomain("climate"),
    lights: byDomain("light"),
    switches: byDomain("switch"),
    temps: ids.filter((e) => e.startsWith("sensor.") && hass.states[e].attributes.device_class === "temperature"),
    hums: ids.filter((e) => e.startsWith("sensor.") && hass.states[e].attributes.device_class === "humidity"),
    batts: ids.filter((e) => e.startsWith("sensor.") && hass.states[e].attributes.device_class === "battery"),
  };
  const cards = classifiedCards(sec, hass);
  const hint = {
    type: "markdown",
    content:
      "# Hallo " + (name || "") + "!\n\n" +
      "Dieses Gerät ist noch **nicht als Haushalt eingerichtet** — du siehst alle Geräte.",
  };
  return {
    title: "Zuhause",
    path: "zuhause",
    icon: HOUSE_ICON,
    cards: cards.length
      ? [hint, ...cards]
      : [hint, { type: "markdown", content: "_Es sind noch keine Geräte eingerichtet._" }],
  };
}

/** Does any room have a thermostat this house can act on as a whole? */
function hasAnyRoomThermostat(hass) {
  const states = (hass && hass.states) || {};
  return Object.keys(states).some(
    (id) => id.startsWith("climate.") && Array.isArray((states[id].attributes || {}).valves));
}

function householdOverview(name, model, rooms, opt) {
  return {
    // Renamed from "Haushalt" on 2026-09-23: it is where a resident changes how
    // the home is set up, and "Einstellungen" is the word they look for.
    title: "Einstellungen",
    path: "einstellungen",
    ...(opt.textTabs ? {} : { icon: "mdi:cog" }),
    // What a resident MANAGES, not the rooms again. Until 2026-09-24 this tab
    // repeated every room as Home Assistant's stock `area` card — rooms the
    // resident already has as tabs — while users, room access and invite links
    // sat on a separate "Verwalten" tab. Thomas, the same day, looking at it as
    // a resident: the management belongs here, the room cards do not. So the
    // master's card moved in and the second tab is gone. A resident who is not
    // the master gets no card: the server refuses them anyway (ADR-0006), and a
    // tab must not offer what it will refuse.
    cards: [
      {
        type: "markdown",
        content:
          "# Hallo " + (name || "") + "!\n\n" +
          (model.is_master
            ? "Du verwaltest **" + rooms.length + " Räume**."
            : "Dieses Zuhause hat **" + rooms.length + " Räume**."),
      },
      ...(model.is_master ? [{ type: "custom:ga-master-card" }] : []),
    ],
  };
}

/**
 * The whole-home heating controls, on their own tab.
 *
 * NAMED `Profil` ON PURPOSE. The previous system had exactly this view — read in
 * `ha-dashboard-automation/templates/profile_view_template.j2` on 2026-09-23,
 * whose grid is literally `"boost override" / "schedule override"`. Residents of
 * that system look for these controls under that word, and inventing "Heizung"
 * would have been a new name for a place that already had one.
 *
 * FIRST POSITION, because "alles aus" is looked for before leaving the flat, not
 * after paging through every room.
 *
 * NOT A SECTION OF THE HOUSEHOLD VIEW, which was the first attempt: that view is
 * hidden by default ("resident-clean UI", 2026-09-08), so the controls would have
 * existed on no device at all. Measured on KIB-SON-00000031 the same day — its
 * dashboard had three room tabs and nothing else.
 *
 * The weekly plan stays in each room's own view. The old design had it here
 * because there was nowhere else; our room tabs already carry ga-heating-card,
 * and two copies would raise the question of which one is authoritative.
 */
function heatingProfileView(opt) {
  return {
    title: "Profil",
    path: "profil",
    ...(opt.textTabs ? {} : { icon: "mdi:thermostat" }),
    cards: [{ type: "custom:ga-heating-actions-card" }],
  };
}

function roomlessView(sec, opt, hass) {
  const cards = classifiedCards(sec, hass);
  if (!cards.length) return null;
  return {
    title: "Ohne Raum",
    path: "ohne-raum",
    ...(opt.textTabs ? {} : { icon: "mdi:help-circle-outline" }),
    cards: [
      {
        type: "markdown",
        content:
          "Diese Geräte sind **keinem Raum zugeordnet** und erscheinen deshalb in keiner Raum-Ansicht.",
      },
      ...cards,
    ],
  };
}

class GaHomeDashboardStrategy extends HTMLElement {
  static async generate(config, hass) {
    const opt = gaOptions(config);
    const model = await fetchHomeModel(hass);
    const userName = model.user_name || (hass.user && hass.user.name) || "";

    if (model.scope === "error") return { title: "Zuhause", views: [errorView(model.reason)] };
    if (model.scope === "nocomponent") {
      return { title: "Zuhause", views: [flatFallbackView(userName, hass)] };
    }

    const scoped = model.scope === "rooms";
    const rooms = model.rooms || [];

    // A sub-user who was granted nothing gets an honest empty state — NOT the house.
    if (scoped && !rooms.length) {
      return { title: "Zuhause", views: [emptyView(userName)] };
    }

    // A house-wide user on a device with no rooms: the server put everything in
    // `roomless` — render it flat rather than an empty room list.
    if (!scoped && !rooms.length) {
      return { title: "Zuhause", views: [noRoomsView(userName, model, hass)] };
    }

    const views = rooms.map((room) => ({
      type: "sections",
      title: room.name,
      path: room.area_id,
      // With text_tabs the tab shows the room NAME; an icon would replace it.
      ...(opt.textTabs ? {} : { icon: ROOM_ICON }),
      max_columns: 3,
      sections: roomSections(room, opt, hass),
    }));

    // The whole-house user (master / admin / unmanaged) gets an overview first,
    // his management view (master only), and anything without a room.
    if (!scoped) {
      // ORDER: the rooms a resident uses daily come first, then Profil, then
      // Einstellungen last (Thomas, 2026-09-23). Both are appended rather than
      // unshifted, so a room tab is always what opens.
      //
      // Only where it applies, and never for a scoped sub-user: "alle Räume aus"
      // must not be offered to someone who holds two of the flat's six rooms.
      if (hasAnyRoomThermostat(hass)) views.push(heatingProfileView(opt));
      if (!opt.hideHousehold) views.push(householdOverview(userName, model, rooms, opt));
      // HA cannot gate a SIDEBAR panel per user (only `require_admin`), but the
      // strategy knows exactly who is looking — so the management view simply is
      // not generated for anyone but the master. (The card's endpoints are
      // master-gated server-side anyway; this is the UI half, not the security half.)
      if (!opt.hideRoomless && model.roomless) {
        const v = roomlessView(model.roomless, opt, hass);
        if (v) views.push(v);
      }
    }

    return { title: "Zuhause", views };
  }
}

customElements.define("ll-strategy-dashboard-ga-home", GaHomeDashboardStrategy);

window.customStrategies = window.customStrategies || [];
window.customStrategies.push({
  type: "dashboard",
  strategyType: "ga-home",
  name: "GreenAutarky — Räume je Nutzer",
  description: "Erzeugt pro eingeloggtem Nutzer ein Dashboard aus den Räumen, die ihm zugewiesen sind.",
});
