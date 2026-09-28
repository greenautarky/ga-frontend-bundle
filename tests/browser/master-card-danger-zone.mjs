/**
 * Do the two Danger Zone buttons of ga-master-card actually send their request?
 *
 * WHY A BROWSER, AND WHY THE NETWORK
 * ----------------------------------
 * Until 1.21.0 both dialogs opened, both accepted their input, both buttons
 * enabled — and a click sent nothing. Opening a dialog cleared its message line
 * with `el.className = "dlg-msg " + kind`, which also removed the class
 * (`.hh-msg` / `.site-msg`) the card uses to FIND that line again. The click
 * handler then looked it up, got null, and threw
 * `Cannot set properties of null (setting 'className')` before the request was
 * built. Everything a person sees up to the click was correct, so only the
 * request leaving the page proves the action works.
 *
 * This harness therefore mounts the SHIPPED card file in Chromium, drives each
 * dialog like a person (open, type, click) and records what reaches the
 * network, via a Playwright route on `/api/**`. `hass.callApi` is the one
 * thing that is faked, and only as far as Home Assistant's own does it: a
 * `fetch` to `/api/<path>` that rejects with the response body on non-2xx —
 * so the request the test sees is the request the card made.
 *
 * Usage:  node master-card-danger-zone.mjs <ga-master-card.js>  → JSON on stdout
 */
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const cardPath = process.argv[2];
if (!cardPath) {
  console.error("usage: node master-card-danger-zone.mjs <ga-master-card.js>");
  process.exit(2);
}
const CARD_JS = readFileSync(cardPath, "utf8");
const ORIGIN = "http://ga-test.invalid";

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  // Home Assistant's hass.callApi, reduced to its contract: JSON in, JSON out,
  // reject with the parsed body on a non-2xx answer.
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

/** Each scenario: the answers the fake device gives, in order, per endpoint. */
const HH = "/api/greenautarky_site/household/reset";
const SITE = "/api/greenautarky_site/site_reset/request";

const SCENARIOS = [
  {
    name: "household_reset_sends",
    answers: { [HH]: [[200, { removed: ["u1"] }]] },
    steps: [["open", ".household-reset"], ["fill", ".hh-confirm", "LÖSCHEN"], ["click", ".hh-go"]],
  },
  {
    name: "household_reset_retry_after_failure_sends",
    answers: { [HH]: [[500, { message: "boom-hh" }], [200, { removed: [] }]] },
    steps: [
      ["open", ".household-reset"], ["fill", ".hh-confirm", "LÖSCHEN"],
      ["click", ".hh-go"], ["waitText", ".household-dlg .dlg-msg", "boom-hh"],
      ["click", ".hh-go"],
    ],
  },
  {
    name: "household_reset_reopened_dialog_sends",
    answers: { [HH]: [[200, { removed: [] }]] },
    steps: [
      ["open", ".household-reset"], ["click", ".household-dlg .dlg-cancel"],
      ["open", ".household-reset"], ["fill", ".hh-confirm", "LÖSCHEN"], ["click", ".hh-go"],
    ],
  },
  {
    name: "site_reset_sends",
    answers: { [SITE]: [[200, { accepted: true }]] },
    steps: [
      ["open", ".site-reset"], ["fill", ".site-pin", "123-456"],
      ["fill", ".site-confirm", "LÖSCHEN"], ["check", ".site-zigbee"], ["click", ".site-go"],
    ],
  },
  {
    name: "site_reset_retry_after_failure_sends",
    answers: { [SITE]: [[403, { message: "boom-site" }], [200, { accepted: true }]] },
    steps: [
      ["open", ".site-reset"], ["fill", ".site-pin", "123456"],
      ["fill", ".site-confirm", "löschen"], ["click", ".site-go"],
      ["waitText", ".site-dlg .dlg-msg", "boom-site"], ["click", ".site-go"],
    ],
  },
];

const browser = await chromium.launch({ headless: true });
const out = { scenarios: {} };

try {
  for (const sc of SCENARIOS) {
    const page = await browser.newPage();
    const errors = [];
    const posts = [];
    page.on("pageerror", (e) => errors.push(String(e.message || e)));
    const queues = Object.fromEntries(
      Object.entries(sc.answers).map(([k, v]) => [k, [...v]])
    );

    await page.route(`${ORIGIN}/**`, async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      const json = (status, body) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (path === "/") return route.fulfill({ status: 200, contentType: "text/html", body: PAGE });
      if (path === "/card.js") return route.fulfill({ status: 200, contentType: "text/javascript", body: CARD_JS });
      if (path === "/api/greenautarky_site/sub_user/list")
        return json(200, { sub_users: [], dashboards: [], areas: [] });
      if (path === "/api/greenautarky_site/site_reset/status")
        return json(200, { status: { state: "accepted" }, pending: false });
      if (req.method() === "POST" && queues[path]) {
        posts.push({ path, body: JSON.parse(req.postData() || "null") });
        const next = queues[path].shift() || [599, { message: "unexpected extra request" }];
        return json(next[0], next[1]);
      }
      return json(404, { message: "not found: " + path });
    });

    await page.goto(ORIGIN + "/");
    await page.evaluate(() => {
      const el = document.createElement("ga-master-card");
      el.setConfig({});
      document.body.appendChild(el);
      el.hass = window.__hass;
    });

    const expected = Object.values(sc.answers).reduce((n, a) => n + a.length, 0);
    let stepError = null;
    try {
      for (const [op, sel, arg] of sc.steps) {
        if (op === "open" || op === "click") await page.click(sel, { timeout: 3000 });
        else if (op === "fill") await page.fill(sel, arg, { timeout: 3000 });
        else if (op === "check") await page.check(sel, { timeout: 3000 });
        else if (op === "waitText")
          await page.waitForFunction(
            ([s, t]) => (document.querySelector(s)?.textContent || "").includes(t),
            [sel, arg],
            { timeout: 3000 }
          );
      }
      // Give the last click the time a request needs to leave the page.
      await page.waitForTimeout(500);
    } catch (e) {
      stepError = String(e.message || e).split("\n")[0];
    }

    out.scenarios[sc.name] = { posts, errors, stepError, expected };
    await page.close();
  }
} finally {
  await browser.close();
}

process.stdout.write(JSON.stringify(out));
