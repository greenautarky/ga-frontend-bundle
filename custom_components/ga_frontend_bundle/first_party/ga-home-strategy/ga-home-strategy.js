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
 * ⚠️ HONEST LIMIT: this is PRESENTATION scoping. HA still serves every entity to
 * any authenticated non-admin over the WebSocket API (render_template / history /
 * the registry lists are not permission-checked). Real isolation would need
 * auth-group entity policies on top. Do not sell it as tenant isolation.
 */

const ROOM_ICON = "mdi:door-open";
const HOUSE_ICON = "mdi:home-heart";

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

/** Cards for a set of entity_ids — the same shape whether it is a room or the house. */
function cardsFor(entityIds, hass) {
  const inDomain = (d) => entityIds.filter((e) => e.startsWith(d + "."));
  const cards = [];

  const climate = inDomain("climate");
  if (climate.length) {
    cards.push({
      type: "grid",
      columns: climate.length > 2 ? 2 : 1,
      square: false,
      cards: climate.map((e) => ({ type: "thermostat", entity: e })),
    });
  }

  const lights = inDomain("light");
  if (lights.length) cards.push({ type: "entities", title: "Licht", entities: lights });

  const measured = inDomain("sensor").filter((e) => {
    const st = hass.states[e];
    const dc = st && st.attributes.device_class;
    return dc === "temperature" || dc === "humidity" || dc === "battery";
  });
  if (measured.length) cards.push({ type: "entities", title: "Messwerte", entities: measured });

  const switches = inDomain("switch");
  if (switches.length) cards.push({ type: "entities", title: "Schalter", entities: switches });

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
      const cards = cardsFor(visible.map((e) => e.entity_id), hass);
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
      title: a.name,
      path: a.area_id,
      icon: ROOM_ICON,
      cards: cardsFor(perArea[a.area_id], hass),
    }));

    // The whole-house user (master / admin / unmanaged device) gets an overview
    // first, plus anything that has no room yet — so nothing is ever invisible to him.
    if (!scoped) {
      views.unshift({
        title: "Haushalt",
        path: "haushalt",
        icon: HOUSE_ICON,
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

      if (roomless.length) {
        const cards = cardsFor(roomless, hass);
        if (cards.length) {
          views.push({
            title: "Ohne Raum",
            path: "ohne-raum",
            icon: "mdi:help-circle-outline",
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
