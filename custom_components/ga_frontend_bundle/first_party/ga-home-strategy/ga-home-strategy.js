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

/**
 * Strategy options — set in the dashboard config:
 *   `strategy: { type: "custom:ga-home", hide_household: true, ... }`
 *
 * Defaults are the product look piloted on KIB-SON-00000050 (2026-07-21):
 *   text_tabs         true      room NAMES as tab text (a row of identical door
 *                               icons distinguishes nothing)
 *   single_thermostat true      TRVs in one room are coupled — show ONE control
 *                               (and one heating plan), not one per valve
 *   thermostat_style  "classic" first-party ga-thermostat-card, three looks:
 *                               "classic" (default: big value + setpoint +
 *                               AUS/MANUEL/KI), "dial" (round drag control),
 *                               "setpoint" (big target). "core" = built-in HA
 *                               thermostat card; "simple" = vendored simple-
 *                               thermostat fallback. ("myvibe" = old alias for classic.)
 *   hide_household    false     drop the "Haushalt" overview view (pilot devices
 *                               with a hand-built overview don't need a second one)
 *   hide_roomless     false     drop the "Ohne Raum" view
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
      // classic. Anything unknown falls back to classic (the default).
      const v = c.thermostat_style === "myvibe" ? "classic" : c.thermostat_style;
      return ["classic", "dial", "setpoint", "core", "simple"].includes(v) ? v : "classic";
    })(),
    hideHousehold: !!c.hide_household,
    hideRoomless: !!c.hide_roomless,
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
function roomSections(room, opt) {
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
  for (const e of temps.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Temperatur" });
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
  const history = [];
  if (temps.length) {
    history.push({ type: "statistics-graph", title: "Temperatur (24 h)", entities: temps,
      stat_types: ["min", "mean", "max"], days_to_show: 1, period: "hour" });
  }
  if (hums.length) {
    history.push({ type: "statistics-graph", title: "Luftfeuchtigkeit (24 h)", entities: hums,
      stat_types: ["min", "mean", "max"], days_to_show: 1, period: "hour" });
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
      ...rest.map((entity) => ({ type: "tile", entity })),
    ] });
  }

  if (!sections.length) {
    sections.push({ type: "grid", cards: [
      { type: "markdown", content: "_Für diesen Raum sind noch keine Geräte eingerichtet._" }] });
  }
  return sections;
}

/** Cards for a classified section without rooms (house-wide user / flat fallback). */
function classifiedCards(sec) {
  const cards = [];
  const climate = sec.climate || [];
  if (climate.length) {
    cards.push({ type: "grid", columns: climate.length > 2 ? 2 : 1, square: false,
      cards: climate.map((e) => ({ type: "thermostat", entity: e })) });
  }
  const measured = [...(sec.temps || []), ...(sec.hums || []), ...(sec.batts || [])];
  if (measured.length) cards.push({ type: "entities", title: "Messwerte", entities: measured });
  const rest = [...(sec.lights || []), ...(sec.switches || [])];
  if (rest.length) cards.push({ type: "entities", title: "Schalter", entities: rest });
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
function noRoomsView(name, model) {
  const cards = classifiedCards(model.roomless || {});
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
  const cards = classifiedCards(sec);
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

function householdOverview(name, model, rooms, opt) {
  return {
    title: "Haushalt",
    path: "haushalt",
    ...(opt.textTabs ? {} : { icon: HOUSE_ICON }),
    cards: [
      {
        type: "markdown",
        content:
          "# Hallo " + (name || "") + "!\n\n" +
          (model.is_master
            ? "Du verwaltest **" + rooms.length + " Räume**. Nutzer und Raum-Freigaben: [Haushalt verwalten](/greenautarky-master)"
            : "Dieses Zuhause hat **" + rooms.length + " Räume**."),
      },
      ...rooms.map((a) => ({ type: "area", area: a.area_id, navigation_path: a.area_id })),
    ],
  };
}

function manageView(opt) {
  return {
    title: "Verwalten",
    path: "verwalten",
    ...(opt.textTabs ? {} : { icon: "mdi:account-cog" }),
    cards: [{ type: "custom:ga-master-card" }],
  };
}

function roomlessView(sec, opt) {
  const cards = classifiedCards(sec);
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
      return { title: "Zuhause", views: [noRoomsView(userName, model)] };
    }

    const views = rooms.map((room) => ({
      type: "sections",
      title: room.name,
      path: room.area_id,
      // With text_tabs the tab shows the room NAME; an icon would replace it.
      ...(opt.textTabs ? {} : { icon: ROOM_ICON }),
      max_columns: 3,
      sections: roomSections(room, opt),
    }));

    // The whole-house user (master / admin / unmanaged) gets an overview first,
    // his management view (master only), and anything without a room.
    if (!scoped) {
      if (!opt.hideHousehold) views.unshift(householdOverview(userName, model, rooms, opt));
      // HA cannot gate a SIDEBAR panel per user (only `require_admin`), but the
      // strategy knows exactly who is looking — so the management view simply is
      // not generated for anyone but the master. (The card's endpoints are
      // master-gated server-side anyway; this is the UI half, not the security half.)
      if (model.is_master) views.push(manageView(opt));
      if (!opt.hideRoomless && model.roomless) {
        const v = roomlessView(model.roomless, opt);
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
