/**
 * Does a press on a room chip of ga-heating-actions-card survive the countdown?
 *
 * WHY A BROWSER
 * -------------
 * The card counts a running boost down once a second. The first version did
 * that by running its whole render every second, and the render rebuilt the
 * room chips with innerHTML. A press held across a tick went down on one button
 * and came up over its replacement, so the browser fired no click and the room
 * was not toggled. Nothing short of a real pointer down/up pair in a real DOM
 * shows that: the click handler itself was always correct.
 *
 * This mounts the SHIPPED card file in Chromium with a boost running, holds the
 * mouse on a chip for longer than a tick, and reports what the card made of it.
 *
 * Usage:  node actions-card-tick.mjs <ga-heating-actions-card.js>  → JSON on stdout
 */
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const cardPath = process.argv[2];
if (!cardPath) {
  console.error("usage: node actions-card-tick.mjs <ga-heating-actions-card.js>");
  process.exit(2);
}
const CARD_JS = readFileSync(cardPath, "utf8");
const ORIGIN = "http://ga-test.invalid";

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  window.__states = (boosting) => {
    const room = (name, area) => ({ state: "heat", attributes: {
      friendly_name: name, area_id: area, valves: ["climate.v_" + area], max_temp: 30,
      current_temperature: 19 } });
    const s = {
      "climate.wohnzimmer": room("Wohnzimmer", "wohnzimmer"),
      "climate.bad": room("Badezimmer", "bad"),
      "climate.schlaf": room("Schlafzimmer", "schlaf"),
    };
    if (boosting) {
      s["climate.wohnzimmer"].attributes.override = { boost: { active: true, temp: 30,
        until: new Date(Date.now() + 600000).toISOString() } };
    }
    return s;
  };
  window.__hass = (boosting) => ({
    states: window.__states(boosting),
    services: { ga_heating: { boost: {}, cancel_boost: {}, ichb: {}, cancel_ichb: {} } },
    callService: async () => {},
    callApi: async () => ({}),
  });
</script>
<script src="/card.js"></script>
</body></html>`;

const CHIP = '.rooms [data-id="climate.bad"]';

async function mount(page, boosting) {
  await page.evaluate((b) => {
    document.body.innerHTML = "";
    const el = document.createElement("ga-heating-actions-card");
    el.setConfig({});
    document.body.appendChild(el);
    el.hass = window.__hass(b);
  }, boosting);
  await page.waitForSelector(CHIP, { timeout: 3000 });
}

const pressed = (page) => page.evaluate(() =>
  Object.fromEntries([...document.querySelectorAll(".rooms .chip")]
    .map((c) => [c.dataset.id || "alle", c.getAttribute("aria-pressed")])));

const status = (page) => page.evaluate(() => document.querySelector(".status").textContent);

const browser = await chromium.launch({ headless: true });
const out = { scenarios: {} };

try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  await page.route(`${ORIGIN}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ status: 200, contentType: "text/html", body: PAGE });
    if (path === "/card.js") {
      return route.fulfill({ status: 200, contentType: "text/javascript", body: CARD_JS });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  await page.goto(ORIGIN + "/");

  // 1. A press held across a tick, with a boost counting down.
  await mount(page, true);
  const before = await pressed(page);
  const statusBefore = await status(page);
  const box = await page.locator(CHIP).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(1600);
  await page.mouse.up();
  await page.waitForTimeout(100);
  out.scenarios.press_across_tick = {
    before, after: await pressed(page), statusBefore, statusAfter: await status(page),
  };

  // 2. The chip element itself survives a tick (no rebuild while counting down).
  await mount(page, true);
  await page.evaluate((sel) => { document.querySelector(sel).__mark = 1; }, CHIP);
  await page.waitForTimeout(1600);
  out.scenarios.chip_survives_tick = {
    survived: await page.evaluate((sel) => document.querySelector(sel).__mark === 1, CHIP),
  };

  // 3. A state push from Home Assistant that changes nothing the chips show.
  await mount(page, false);
  await page.evaluate((sel) => { document.querySelector(sel).__mark = 1; }, CHIP);
  await page.evaluate(() => {
    document.querySelector("ga-heating-actions-card").hass = window.__hass(false);
  });
  out.scenarios.chip_survives_hass_push = {
    survived: await page.evaluate((sel) => document.querySelector(sel).__mark === 1, CHIP),
  };

  // 4. No clock at all while nothing counts down.
  await mount(page, false);
  out.scenarios.idle_has_no_ticker = {
    ticker: await page.evaluate(() =>
      Boolean(document.querySelector("ga-heating-actions-card")._ticker)),
  };

  out.errors = errors;
  await page.close();
} finally {
  await browser.close();
}

process.stdout.write(JSON.stringify(out));
