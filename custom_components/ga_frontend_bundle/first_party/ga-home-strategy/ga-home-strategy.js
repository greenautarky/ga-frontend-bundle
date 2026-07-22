/**
 * ga-home-strategy — GreenAutarky per-user home dashboard (ADR-0006 successor).
 *
 * ONE dashboard for the whole household — HA's default Overview. It is generated
 * in the browser on every load, for whoever is logged in:
 *
 *   hass.user  →  GET /api/greenautarky_onboarding/my_rooms  →  {scope, reason, areas}
 *              →  views built from HA's area/device/entity registries
 *
 * Nothing per-user is stored server-side: no per-user dashboard, no per-view
 * `visible` lists — and therefore no orphaned board when a user is removed.
 *
 * The scope decision is made by the COMPONENT, never here. This file must not
 * invent who may see what; it only renders what the server allows.
 *
 * ROBUSTNESS — the three states a fleet device is actually in today:
 *   1. no rooms in HA        → group the house by device class instead ("Zuhause")
 *   2. no household set up   → server says scope=all/unmanaged → show everything
 *   3. component missing/404 → assume unmanaged and show everything
 * A blank dashboard is only ever correct for a real sub-user who was granted
 * nothing — never for a device we simply have not configured yet.
 *
 * ⚠️ SCOPE NOTE: this file is only the PRESENTATION half. Real per-user entity
 * isolation exists since greenautarky-onboarding 1.4.0 (Stage A: native HA
 * permission groups) + 1.6.0 (Stage B: leak_guard closes render_template /
 * history / registry-list side channels) — opt-in via `entity_scoping_enabled`,
 * default OFF. With the flag off this remains presentation scoping only.
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
 *   thermostat_style  "myvibe"  the Steuerung card the residents already know
 *                               (simple-thermostat: big value + AUS/MANUEL/KI);
 *                               "core" = HA thermostat dial + hvac-mode feature row
 *   hide_household    false     drop the "Haushalt" overview view (pilot devices
 *                               with a hand-built overview don't need a second one)
 *   hide_roomless     false     drop the "Ohne Raum" view
 */
function gaOptions(config) {
  const c = config || {};
  return {
    textTabs: c.text_tabs !== false,
    singleThermostat: c.single_thermostat !== false,
    thermostatStyle: ["core", "simple"].includes(c.thermostat_style) ? c.thermostat_style : "myvibe",
    hideHousehold: !!c.hide_household,
    hideRoomless: !!c.hide_roomless,
  };
}

/** Ask the server WHO this user is and WHAT he may see. Never guess client-side. */
async function myScope(hass) {
  try {
    const r = await hass.callApi("get", "greenautarky_onboarding/my_rooms");
    return { scope: r.scope, reason: r.reason, areas: r.areas || [], areasExist: r.areas_exist };
  } catch (err) {
    // 404 = the component is not on this device → it was never put into household
    // mode. Show the house; a missing component must not blank the dashboard.
    const status = err && (err.status_code || err.status);
    if (status === 404) return { scope: "all", reason: "no-component", areas: [], areasExist: false };
    return { scope: "error", reason: String((err && err.message) || err), areas: [] };
  }
}

const areaOfEntity = (e, deviceArea) =>
  e.area_id || (e.device_id ? deviceArea[e.device_id] : null);

/** Sensors of a given device_class inside a set of entity_ids. */
function sensorsOf(entityIds, hass, deviceClass) {
  return entityIds.filter((e) => {
    if (!e.startsWith("sensor.")) return false;
    const st = hass.states[e];
    return st && st.attributes.device_class === deviceClass;
  });
}

/** The house's weather entity, if the tenant has one. */
function weatherEntity(hass) {
  return Object.keys(hass.states).find((e) => e.startsWith("weather."));
}

/**
 * The room view — CORE CARDS ONLY.
 *
 * Deliberately no community cards. The MyVibe layout leaned on mushroom +
 * simple-thermostat + button-card + card-mod; `simple-thermostat` is already broken
 * on our HA version (renders an error card, 0 elements — measured on K0), and every
 * vendored card is one more thing that can break a customer's dashboard on an HA
 * update. Modern HA covers what those cards were for:
 *
 *   simple-thermostat's KI/MANUEL/AUS  →  `tile` + `climate-hvac-modes` feature
 *   mushroom chips header              →  `heading` card with badges
 *   layout-card / card-mod             →  `sections` view
 *   apexcharts daily range             →  core `statistics-graph`
 *
 * If the GA face needs more than core cards give, the answer is ONE first-party
 * card we own (like ga-master-card) — not a stack of third-party ones.
 */
function roomSections(roomName, entityIds, hass, opt) {
  const cat = hass.__gaCat || {};
  const isPrimary = (e) => !cat[e];                      // no entity_category = resident-facing
  const primary = entityIds.filter(isPrimary);
  const inDomain = (d) => primary.filter((e) => e.startsWith(d + "."));

  // Coupled TRVs (two valves on the radiators of one room) mirror each other —
  // rendering both just shows the same state twice and doubles the Heizplan.
  const climateAll = inDomain("climate");
  const climate = opt.singleThermostat ? climateAll.slice(0, 1) : climateAll;
  const temps = sensorsOf(primary, hass, "temperature");
  const hums = sensorsOf(primary, hass, "humidity");
  // Battery is `diagnostic` — useful to glance at, not something to operate: badge only.
  const batts = sensorsOf(entityIds, hass, "battery");
  const switches = inDomain("switch");
  const lights = inDomain("light");

  // Named badges — the raw entities carry IEEE-address names on fleet devices.
  const badges = [];
  for (const e of temps.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Temperatur" });
  for (const e of hums.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Luftfeuchtigkeit" });
  for (const e of batts.slice(0, 1)) badges.push({ type: "entity", entity: e, name: "Batterie" });

  const sections = [];

  // Heating — the dial plus the mode control MyVibe called KI / MANUEL / AUS.
  if (climate.length) {
    const cards = [
      { type: "heading", heading: "Heizung", heading_style: "title", badges },
    ];
    for (const entity of climate) {
      if (opt.thermostatStyle === "myvibe") {
        // The Steuerung card residents were trained on: big value + setpoint + an
        // explicit AUS / MANUEL / KI mode row. FIRST-PARTY ga-thermostat-card
        // (Odoo #518) — talks straight to climate.* services. The default.
        cards.push({
          type: "custom:ga-thermostat-card",
          entity,
          header: "Steuerung",
        });
      } else if (opt.thermostatStyle === "simple") {
        // Fallback: the vendored community simple-thermostat, kept in the bundle
        // (coexistence, 1.4.0) so hand-built dashboards that still reference
        // `custom:simple-thermostat` keep working, and as a fallback while the
        // first-party card matures. Same AUS/MANUEL/KI mapping as ga-thermostat-card.
        cards.push({
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
        });
      } else {
        // "core": the dial carries the mode control as a card FEATURE.
        cards.push({
          type: "thermostat",
          entity,
          features: [
            { type: "climate-hvac-modes", hvac_modes: ["auto", "heat", "off"], style: "icons" },
          ],
        });
      }
    }
    sections.push({ type: "grid", cards });
  }

  // Weekly plan — our own card, our own backend, executed via climate.set_temperature
  // (so it works with ANY thermostat, not just the Zigbee TRV we happen to ship).
  for (const entity of climate) {
    sections.push({ type: "grid", cards: [
      { type: "heading", heading: "Heizplan", heading_style: "title" },
      { type: "custom:ga-heating-card", entity, title: roomName },
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

  // Everything else a resident operates, as tiles. Config knobs (open-window,
  // child-lock, valve degrees …) and diagnostics never appear here.
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

/** Cards for entities without a room (house-wide user only). */
function plainCards(entityIds, hass) {
  const cards = [];
  const inDomain = (d) => entityIds.filter((e) => e.startsWith(d + "."));

  const climate = inDomain("climate");
  if (climate.length) {
    cards.push({ type: "grid", columns: climate.length > 2 ? 2 : 1, square: false,
      cards: climate.map((e) => ({ type: "thermostat", entity: e })) });
  }
  const measured = [
    ...sensorsOf(entityIds, hass, "temperature"),
    ...sensorsOf(entityIds, hass, "humidity"),
    ...sensorsOf(entityIds, hass, "battery"),
  ];
  if (measured.length) cards.push({ type: "entities", title: "Messwerte", entities: measured });
  const rest = [...inDomain("light"), ...inDomain("switch")];
  if (rest.length) cards.push({ type: "entities", title: "Schalter", entities: rest });
  return cards;
}

function errorView(message) {
  return {
    title: "Fehler",
    icon: "mdi:alert",
    cards: [
      {
        type: "markdown",
        content:
          "## Dein Zuhause konnte nicht geladen werden\n\n`" + message + "`\n\n" +
          "Bitte lade die Seite neu. Bleibt es dabei, wende dich an den Support.",
      },
    ],
  };
}

function emptyView(name) {
  return {
    title: "Zuhause",
    icon: HOUSE_ICON,
    cards: [
      {
        type: "markdown",
        content:
          "# Willkommen, " + (name || "") + "!\n\n" +
          "Dir wurde noch **kein Raum** zugewiesen.\n\n" +
          "Bitte deinen Haushalts-Verwalter, dir Räume freizugeben.",
      },
    ],
  };
}

class GaHomeDashboardStrategy extends HTMLElement {
  static async generate(config, hass) {
    const opt = gaOptions(config);
    const me = await myScope(hass);
    const userName = (hass.user && hass.user.name) || "";

    if (me.scope === "error") return { title: "Zuhause", views: [errorView(me.reason)] };

    // A sub-user who was granted nothing gets an honest empty state — NOT the house.
    if (me.scope === "rooms" && !me.areas.length) {
      return { title: "Zuhause", views: [emptyView(userName)] };
    }

    const [devices, entities] = await Promise.all([
      hass.callWS({ type: "config/device_registry/list" }),
      hass.callWS({ type: "config/entity_registry/list" }),
    ]);
    const deviceArea = {};
    for (const d of devices) deviceArea[d.id] = d.area_id;

    // HA already classifies what is a knob and what is a feature: `entity_category`
    // is "config" (child-lock, open-window, valve degrees, weekly-schedule texts …)
    // or "diagnostic" (battery, linkquality, valve voltages). Only entities WITHOUT a
    // category are the ones a resident actually operates. We show those — no
    // hand-maintained blocklist, and it stays right when a device firmware adds knobs.
    const catOf = {};
    for (const e of entities) catOf[e.entity_id] = e.entity_category || null;
    hass.__gaCat = catOf;

    const visible = entities.filter((e) => !e.hidden_by && !e.disabled_by);
    const scoped = me.scope === "rooms";
    const allowed = new Set(me.areas.map((a) => a.area_id));

    const perArea = {};
    const roomless = [];
    for (const e of visible) {
      const aid = areaOfEntity(e, deviceArea);
      if (aid) {
        if (scoped && !allowed.has(aid)) continue; // ← the whole point
        (perArea[aid] ||= []).push(e.entity_id);
      } else if (!scoped) {
        roomless.push(e.entity_id); // only the house-wide user sees these
      }
    }

    const rooms = me.areas
      .filter((a) => (perArea[a.area_id] || []).length) // an empty room is noise
      .sort((a, b) => a.name.localeCompare(b.name, "de"));

    // FALLBACK — the device has no rooms (or nothing is assigned to one): render the
    // house by device class rather than an empty room list.
    if (!scoped && !rooms.length) {
      const cards = plainCards(visible.map((e) => e.entity_id), hass);
      const hint = {
        type: "markdown",
        content:
          "# Hallo " + userName + "!\n\n" +
          (me.reason === "no-component" || me.reason === "unmanaged"
            ? "Dieses Gerät ist noch **nicht als Haushalt eingerichtet** — du siehst alles.\n\n"
            : "") +
          "Für dieses Zuhause sind noch **keine Räume** angelegt. " +
          "Sobald Räume eingerichtet sind, erscheint hier je Raum eine eigene Ansicht.",
      };
      return {
        title: "Zuhause",
        views: [
          {
            title: "Zuhause",
            path: "zuhause",
            icon: HOUSE_ICON,
            cards: cards.length
              ? [hint, ...cards]
              : [hint, { type: "markdown", content: "_Es sind noch keine Geräte eingerichtet._" }],
          },
        ],
      };
    }

    const views = rooms.map((a) => ({
      type: "sections",
      title: a.name,
      path: a.area_id,
      // With text_tabs the tab shows the room NAME; an icon would replace it.
      ...(opt.textTabs ? {} : { icon: ROOM_ICON }),
      max_columns: 3,
      sections: roomSections(a.name, perArea[a.area_id], hass, opt),
    }));

    // The whole-house user (master / admin / unmanaged device) gets an overview
    // first, plus anything that has no room yet — so nothing is ever invisible to him.
    if (!scoped) {
      if (!opt.hideHousehold) views.unshift({
        title: "Haushalt",
        path: "haushalt",
        ...(opt.textTabs ? {} : { icon: HOUSE_ICON }),
        cards: [
          {
            type: "markdown",
            content:
              "# Hallo " + userName + "!\n\n" +
              (me.reason === "master"
                ? "Du verwaltest **" + rooms.length + " Räume**. Nutzer und Raum-Freigaben: [Haushalt verwalten](/greenautarky-master)"
                : "Dieses Zuhause hat **" + rooms.length + " Räume**."),
          },
          ...rooms.map((a) => ({ type: "area", area: a.area_id, navigation_path: a.area_id })),
        ],
      });

      // The master gets his household management right in the dashboard. HA cannot
      // gate a SIDEBAR panel per user (only `require_admin`), but the strategy knows
      // exactly who is looking — so the management view simply is not generated for
      // anyone else. (The card's endpoints are master-gated server-side anyway; this
      // is the UI half of that, not the security half.)
      if (me.reason === "master") {
        views.push({
          title: "Verwalten",
          path: "verwalten",
          ...(opt.textTabs ? {} : { icon: "mdi:account-cog" }),
          cards: [{ type: "custom:ga-master-card" }],
        });
      }

      if (!opt.hideRoomless && roomless.length) {
        const cards = plainCards(roomless, hass);
        if (cards.length) {
          views.push({
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
          });
        }
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
