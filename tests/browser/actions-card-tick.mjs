/**
 * Does the Urlaub form of ga-heating-actions-card survive the countdown?
 *
 * WHY A BROWSER
 * -------------
 * The card counts a running boost down once a second. The first version did
 * that by running its whole render every second, and the render rebuilt its
 * controls with innerHTML. A press held across a tick went down on one button
 * and came up over its replacement, so the browser fired no click; a date typed
 * into the form was thrown away mid-entry, focus and all. Nothing short of a
 * real pointer and a real DOM shows either: the handlers themselves were always
 * correct.
 *
 * WHAT THIS WATCHED BEFORE 2026-10-20. The room chips, which were the control
 * most exposed to it — one tap each and a whole row rebuilt. The row is gone
 * ("remove room choice section", 2026-10-20) and the hazard is not: the Urlaub
 * form is now OPEN on arrival, with two date inputs and two selects in it, so
 * it is the thing a tick can now eat. These scenarios moved onto it.
 *
 * This mounts the SHIPPED card file in Chromium with a boost running, works the
 * form across a tick, and reports what the card made of it.
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
  window.__calls = [];
  window.__hass = (boosting) => ({
    states: window.__states(boosting),
    services: { ga_heating: { boost: {}, cancel_boost: {}, ichb: {}, cancel_ichb: {} } },
    callService: async (d, s) => { window.__calls.push(d + "." + s); },
    callApi: async (m, path) => { window.__calls.push(m + " " + path); return {}; },
  });
</script>
<script src="/card.js"></script>
</body></html>`;

//: The date field a resident types a return day into: open on arrival, rebuilt
//: by `_renderFields` whenever the markup it would produce changes.
const FIELD = '.fields input.end';
const BOOST = '.quick .btn.boost';

async function mount(page, boosting) {
  await page.evaluate((b) => {
    document.body.innerHTML = "";
    window.__calls = [];
    const el = document.createElement("ga-heating-actions-card");
    el.setConfig({});
    document.body.appendChild(el);
    el.hass = window.__hass(b);
  }, boosting);
  await page.waitForSelector(FIELD, { timeout: 3000 });
}

const status = (page) => page.evaluate(() => document.querySelector(".status").textContent);
const calls = (page) => page.evaluate(() => window.__calls.slice());

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

  // 1. A press on Boost held across a tick, with a boost already counting down.
  //    The button it goes down on has to be the button it comes up on.
  await mount(page, true);
  const statusBefore = await status(page);
  const box = await page.locator(BOOST).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(1600);
  await page.mouse.up();
  await page.waitForTimeout(150);
  out.scenarios.press_across_tick = {
    calls: await calls(page), statusBefore, statusAfter: await status(page),
  };

  // 2. What the resident typed is still there after a tick, and so is the
  //    element they typed it into — a replaced input also drops the caret.
  await mount(page, true);
  await page.evaluate((sel) => { document.querySelector(sel).__mark = 1; }, FIELD);
  await page.locator(FIELD).fill("2026-12-24");
  await page.waitForTimeout(1600);
  out.scenarios.field_survives_tick = {
    survived: await page.evaluate((sel) => document.querySelector(sel).__mark === 1, FIELD),
    value: await page.locator(FIELD).inputValue(),
  };

  // 3. A state push from Home Assistant that changes nothing the form shows.
  await mount(page, false);
  await page.evaluate((sel) => { document.querySelector(sel).__mark = 1; }, FIELD);
  await page.locator(FIELD).fill("2026-12-24");
  await page.evaluate(() => {
    document.querySelector("ga-heating-actions-card").hass = window.__hass(false);
  });
  out.scenarios.field_survives_hass_push = {
    survived: await page.evaluate((sel) => document.querySelector(sel).__mark === 1, FIELD),
    value: await page.locator(FIELD).inputValue(),
  };

  // 4. THE YEAR BUG. A date is typed day -> month -> year, and the input fires
  //    `change` the moment the first two make something parseable. The card
  //    re-rendered on that change and rebuilt the whole fields block from
  //    markup that carried the values, so the element being typed into was
  //    replaced and the year had nowhere to land. Fields must survive their own
  //    change event, and so must the focus.
  await mount(page, false);
  await page.evaluate(() => {
    const el = document.querySelector("ga-heating-actions-card");
    el.querySelector(".start").__mark = "s";
    el.querySelector(".end").__mark = "e";
    el.querySelector(".temp").__mark = "t";
    const start = el.querySelector(".start");
    start.focus();
    start.value = "2026-12-24";
    start.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(150);
  out.scenarios.fields_survive_their_own_change = await page.evaluate(() => {
    const el = document.querySelector("ga-heating-actions-card");
    const start = el.querySelector(".start");
    return {
      startSurvived: start.__mark === "s",
      endSurvived: el.querySelector(".end").__mark === "e",
      tempSurvived: el.querySelector(".temp").__mark === "t",
      stillFocused: document.activeElement === start,
      startValue: start.value,
      // The end cannot be earlier than the start, said in the calendar itself.
      endMin: el.querySelector(".end").min,
    };
  });

  // 5. No clock at all while nothing counts down.
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
