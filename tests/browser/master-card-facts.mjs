/**
 * The two read-only blocks of ga-master-card, mounted as shipped in Chromium
 * (Odoo #2144 Zigbee list, #2145 version tile).
 *
 * `hass.callApi` is the one fake, and only as far as Home Assistant's own is: a
 * `fetch` to `/api/<path>` that rejects with the body on non-2xx. The fake
 * device answers /zigbee_devices and /versions from variables the scenario can
 * change between loads — which is what proves nothing is cached in the card.
 *
 * Usage:  node master-card-facts.mjs <ga-master-card.js>  → JSON on stdout
 */
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const cardPath = process.argv[2];
if (!cardPath) {
  console.error("usage: node master-card-facts.mjs <ga-master-card.js>");
  process.exit(2);
}
const CARD_JS = readFileSync(cardPath, "utf8");
const ORIGIN = "http://ga-test.invalid";

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  window.__hass = {
    async callApi(method, path, data) {
      const r = await fetch("/api/" + path, {
        method,
        headers: { "content-type": "application/json" },
        body: data === undefined ? undefined : JSON.stringify(data),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw { status_code: r.status, body };
      return body;
    },
  };
</script>
<script src="/card.js"></script>
</body></html>`;

const DEVICES = {
  devices: [
    { device_id: "d1", name: "Thermostat Küche", area: "Küche", area_id: "kitchen", battery: 9, lqi: 21 },
    { device_id: "d2", name: "Thermostat Wohnzimmer", area: "Wohnzimmer", area_id: "living", battery: 88, lqi: 120 },
    { device_id: "d3", name: "Steckdose Flur", area: null, area_id: null, battery: null, lqi: 200 },
  ],
};
const VERSIONS = (release, core) => ({
  status: "ok",
  bundle: release,
  reported_at: "2026-11-16T10:00:00Z",
  components: [
    { group: "system", id: "os", name: "Betriebssystem (OS)", version: "17.1.ga1" },
    { group: "system", id: "core", name: "Home Assistant Core", version: core },
    { group: "addon", id: "ga_manager", name: "GA Manager", version: "0.277.6" },
    { group: "integration", id: "ga_heating", name: "GA Heating", version: "0.16.1" },
  ],
});

const browser = await chromium.launch({ headless: true });
const out = { scenarios: {} };

async function mount(state) {
  const page = await browser.newPage();
  const errors = [];
  const calls = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  await page.route(`${ORIGIN}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (status, body) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    calls.push(path);
    if (path === "/") return route.fulfill({ status: 200, contentType: "text/html", body: PAGE });
    if (path === "/card.js") return route.fulfill({ status: 200, contentType: "text/javascript", body: CARD_JS });
    if (path === "/api/greenautarky_site/sub_user/list")
      return json(200, { sub_users: [], dashboards: [], areas: [] });
    if (path === "/api/greenautarky_site/zigbee_devices") return state.zigbee(json);
    if (path === "/api/greenautarky_site/versions") return state.versions(json);
    return json(404, { message: "not found: " + path });
  });
  await page.goto(ORIGIN + "/");
  await page.evaluate(() => {
    const el = document.createElement("ga-master-card");
    el.setConfig({});
    document.body.appendChild(el);
    el.hass = window.__hass;
  });
  return { page, errors, calls };
}

try {
  // 1. Everything renders, in the right place, with the right highlights.
  {
    const state = {
      zigbee: (json) => json(200, DEVICES),
      versions: (json) => json(200, VERSIONS("BOSv1.6.1-rc2", "2026.10.4")),
    };
    const { page, errors } = await mount(state);
    await page.waitForSelector(".sw-bundle", { timeout: 5000 });
    await page.waitForSelector(".zb-row", { timeout: 5000 });
    out.scenarios.renders = await page.evaluate(() => {
      const card = document.querySelector("ga-master-card");
      const q = (s) => card.querySelector(s);
      const idx = (el) => [...card.querySelectorAll("h4")].indexOf(el);
      const h4 = (t) => [...card.querySelectorAll("h4")].find((h) => h.textContent.includes(t));
      return {
        rows: [...card.querySelectorAll(".zb-row")].map((r) => ({
          name: r.querySelector(".zb-name").textContent,
          room: r.querySelector(".zb-room").textContent,
          batt: r.querySelector(".zb-batt").textContent,
          battBad: !!r.querySelector(".zb-batt .bad"),
          lqi: r.querySelector(".zb-lqi").textContent,
          lqiBad: !!r.querySelector(".zb-lqi .bad"),
        })),
        headline: q(".sw-bundle").textContent,
        tileOpenAtStart: q(".sw-tile").open,
        order: {
          zigbee: idx(h4("Zigbee")),
          software: idx(h4("Software")),
          danger: idx(h4("Gefahrenbereich")),
        },
        subVersions: [...card.querySelectorAll(".sw-row")].map((r) => [
          r.querySelector("td").textContent,
          r.querySelector(".sw-ver").textContent,
        ]),
        dangerZonePresent: !!q(".danger-zone"),
      };
    });
    // Expand it, as a person would.
    await page.click(".sw-tile summary");
    out.scenarios.renders.tileOpenAfterClick = await page.evaluate(
      () => document.querySelector(".sw-tile").open
    );
    out.scenarios.renders.errors = errors;
    await page.close();
  }

  // 2. A changed version is shown as it is on the next load (no stale value).
  {
    const state = {
      zigbee: (json) => json(200, DEVICES),
      versions: (json) => json(200, VERSIONS("BOSv1.6.1-rc1", "2026.10.3")),
    };
    const { page } = await mount(state);
    await page.waitForSelector(".sw-bundle", { timeout: 5000 });
    const first = await page.evaluate(() => document.querySelector(".sw-bundle").textContent);
    state.versions = (json) => json(200, VERSIONS("BOSv1.6.1-rc2", "2026.10.4"));
    // _load() is what every user action calls; the facts are re-asked each time.
    await page.evaluate(() => document.querySelector("ga-master-card")._load());
    await page.waitForFunction(
      () => document.querySelector(".sw-bundle").textContent === "BOSv1.6.1-rc2",
      null, { timeout: 5000 }
    );
    out.scenarios.no_stale_version = {
      first,
      second: await page.evaluate(() => document.querySelector(".sw-bundle").textContent),
      core: await page.evaluate(
        () => [...document.querySelectorAll(".sw-row")].find((r) => r.dataset.id === "core")
          .querySelector(".sw-ver").textContent
      ),
    };
    await page.close();
  }

  // 3. One block failing does not take the others (or the danger zone) with it.
  {
    const state = {
      zigbee: (json) => json(500, { message: "boom-zb" }),
      versions: (json) => json(200, { status: "missing", bundle: null, components: [] }),
    };
    const { page } = await mount(state);
    await page.waitForSelector(".sw-bundle", { timeout: 5000 });
    await page.waitForFunction(() => document.querySelector(".zb").textContent.includes("boom-zb"), null, { timeout: 5000 });
    out.scenarios.isolated_failures = await page.evaluate(() => ({
      zb: document.querySelector(".zb").textContent,
      headline: document.querySelector(".sw-bundle").textContent,
      dangerZonePresent: !!document.querySelector(".danger-zone"),
      householdButton: !!document.querySelector(".household-reset"),
    }));
    await page.close();
  }
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(out));
