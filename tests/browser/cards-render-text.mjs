/**
 * Do the first-party cards render names and texts from Home Assistant as TEXT?
 *
 * Each scenario mounts one SHIPPED card file in Chromium, hands it a `hass`
 * whose names, titles and attributes contain markup (PROBE below), and reads
 * the DOM back:
 *
 *   probeElements  how many elements the markup produced — must be 0
 *   text           the card's textContent — must contain PROBE literally,
 *                  which also proves the text site was actually reached
 *   attrs          selected attribute values — must equal PROBE exactly
 *
 * `hass.callApi` is the only thing faked: it answers each path with the JSON
 * the scenario gives, as Home Assistant's would.
 *
 * Usage:  node cards-render-text.mjs <first_party dir>  → JSON on stdout
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright";

const dir = process.argv[2];
if (!dir) {
  console.error("usage: node cards-render-text.mjs <first_party dir>");
  process.exit(2);
}
const ORIGIN = "http://ga-test.invalid";

// One string for both contexts: in text it would become an <i> element, inside
// a double-quoted attribute it would close the attribute and add one.
const PROBE = '"><i data-probe="1">x</i>';
const NOW = new Date().toISOString();
const climate = (friendly, attrs = {}) => ({
  state: "auto",
  attributes: {
    friendly_name: friendly, valves: ["climate.v1"], hvac_modes: ["off", "heat", "auto"],
    temperature: 20, current_temperature: 19, min_temp: 5, max_temp: 30, ...attrs,
  },
  last_updated: NOW,
});

const SCENARIOS = [
  {
    name: "maintenance",
    file: "ga-maintenance-card/ga-maintenance-card.js",
    tag: "ga-maintenance-card",
    config: { title: PROBE, batteries: ["sensor.b"], links: ["sensor.l"], climate: "climate.r" },
    states: {
      "sensor.b": { state: "10", attributes: { friendly_name: PROBE + " Batterie" } },
      "sensor.l": { state: "5", attributes: { friendly_name: PROBE } },
      "climate.r": climate("Raum", { valves_late: { "climate.v1": { lag_s: 60 } } }),
      "climate.v1": { state: "heat", attributes: { friendly_name: PROBE } },
    },
    attrs: [],
  },
  {
    name: "heating_log",
    file: "ga-heating-log-card/ga-heating-log-card.js",
    tag: "ga-heating-log-card",
    config: { entity: "climate.r", title: PROBE },
    states: {
      "climate.r": climate("Raum", {
        changes: [{ kind: "mode", from: PROBE, to: "auto", at: NOW, source: "plan" }],
      }),
    },
    attrs: [],
  },
  {
    name: "thermostat",
    file: "ga-thermostat-card/ga-thermostat-card.js",
    tag: "ga-thermostat-card",
    config: { entity: "climate.r", header: PROBE },
    states: { "climate.r": climate("Raum") },
    attrs: [],
  },
  {
    name: "heating_schedule",
    file: "ga-heating-card/ga-heating-card.js",
    tag: "ga-heating-card",
    config: { entity: "climate.r", title: PROBE },
    states: { "climate.r": climate("Raum") },
    api: {
      "ga_heating/schedule": {
        days: Object.fromEntries(
          ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            .map((d) => [d, [{ time: PROBE, temp: PROBE }]])),
      },
    },
    attrs: [["ha-card", "header"], ["input.t", "value"], ["input.v", "value"]],
  },
  {
    name: "heating_actions",
    file: "ga-heating-actions-card/ga-heating-actions-card.js",
    tag: "ga-heating-actions-card",
    config: { title: PROBE },
    states: {
      "climate.r": climate(PROBE, {
        override: { absence: { active: true, temp: PROBE, end: "2026-10-09T12:00:00" } },
      }),
    },
    attrs: [],
  },
  {
    name: "master",
    file: "ga-master-card/ga-master-card.js",
    tag: "ga-master-card",
    config: {},
    states: {},
    api: {
      "greenautarky_site/sub_user/list": {
        areas: [{ area_id: PROBE, name: PROBE }],
        dashboards: [],
        sub_users: [{ user_id: PROBE, name: PROBE, username: PROBE, rooms: [] }],
      },
    },
    attrs: [["select.area-sel option", "value"], ["button.tgl", "data-uid"], ["button.rm", "data-name"]],
  },
];

const browser = await chromium.launch({ headless: true });
const out = { probe: PROBE, scenarios: {} };

try {
  for (const sc of SCENARIOS) {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e.message || e)));
    const cardJs = readFileSync(join(dir, sc.file), "utf8");
    await page.route(`${ORIGIN}/**`, (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") {
        return route.fulfill({ status: 200, contentType: "text/html",
          body: '<!doctype html><html><head><meta charset="utf-8"></head><body>'
            + '<script type="module" src="/card.js"></script></body></html>' });
      }
      if (path === "/card.js") return route.fulfill({ status: 200, contentType: "text/javascript", body: cardJs });
      return route.fulfill({ status: 404, body: "" });
    });
    await page.goto(ORIGIN + "/");
    await page.waitForFunction((t) => !!customElements.get(t), sc.tag, { timeout: 5000 });

    const res = await page.evaluate(async ({ sc }) => {
      const hass = {
        states: sc.states,
        services: { ga_heating: { ichb: {} } },
        user: { name: "Test" },
        async callApi(method, path) {
          const key = Object.keys(sc.api || {}).find((k) => path.startsWith(k));
          if (method.toLowerCase() === "get" && key) return JSON.parse(JSON.stringify(sc.api[key]));
          throw { message: "not available in this harness: " + path };
        },
        async callService() {},
      };
      const el = document.createElement(sc.tag);
      el.setConfig(sc.config);
      document.body.appendChild(el);
      el.hass = hass;
      // Cards that load over callApi render after their first await.
      await new Promise((r) => setTimeout(r, 400));
      el.hass = hass;
      await new Promise((r) => setTimeout(r, 100));
      return {
        probeElements: document.querySelectorAll("[data-probe]").length,
        text: el.textContent,
        attrs: Object.fromEntries(sc.attrs.map(([sel, attr]) => {
          const node = el.querySelector(sel);
          return [`${sel}@${attr}`, node ? node.getAttribute(attr) : null];
        })),
      };
    }, { sc });

    out.scenarios[sc.name] = { ...res, errors };
    await page.close();
  }
} finally {
  await browser.close();
}

process.stdout.write(JSON.stringify(out));
