/**
 * ga-resident-chrome in a browser: buttons hidden and shortcuts dead for a
 * resident, everything untouched for an admin (Odoo #2146).
 *
 * The page imitates only the SHAPE Home Assistant has: <home-assistant> with a
 * `hass.user`, and inside nested shadow roots a <hui-root> whose toolbar holds
 * <ha-icon-button .path=...> buttons for search, Assist and one unrelated
 * button, plus an overflow menu entry per action. The SHIPPED asset runs
 * unmodified. A bubbling `window` listener plays the part of Home Assistant's
 * tinykeys handlers: it opens the quick bar / Assist unless the event arrives
 * `defaultPrevented` — the contract the asset relies on.
 *
 * The real thing (a real Core, the real frontend, admin vs tenant) is proven by
 * greenautarky-onboarding tests/e2e/test_resident_settings_e2e.py.
 *
 * Usage:  node resident-chrome.mjs <ga-resident-chrome.js>  → JSON on stdout
 */
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const assetPath = process.argv[2];
if (!assetPath) {
  console.error("usage: node resident-chrome.mjs <ga-resident-chrome.js>");
  process.exit(2);
}
const ASSET_JS = readFileSync(assetPath, "utf8");
const ORIGIN = "http://ga-test.invalid";

// mdiMagnify, mdiCommentProcessingOutline and mdiRefresh as @mdi/js spells them.
const MAGNIFY = "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z";
const ASSIST = "M9,22A1,1 0 0,1 8,21V18H4A2,2 0 0,1 2,16V4C2,2.89 2.9,2 4,2H20A2,2 0 0,1 22,4V16A2,2 0 0,1 20,18H13.9L10.2,21.71C10,21.9 9.75,22 9.5,22V22H9M10,16V19.08L13.08,16H20V4H4V16H10M17,11H15V9H17V11M13,11H11V9H13V11M9,11H7V9H9V11Z";
const OTHER = "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z";

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  window.__opened = [];
  // Home Assistant's handlers: act unless an earlier listener prevented it.
  window.addEventListener("keydown", (ev) => {
    if (ev.defaultPrevented) return;
    // canOverrideAlphanumericInput: a letter typed into a field is not a shortcut.
    if (ev.composedPath()[0].tagName === "INPUT") return;
    const k = (ev.key || "").toLowerCase();
    if ((ev.ctrlKey || ev.metaKey) && k === "k") window.__opened.push("search-ctrlk");
    else if (!ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      if (k === "a") window.__opened.push("assist");
      if (k === "e") window.__opened.push("quickbar");
    }
  });
  window.__build = (isAdmin) => {
    const app = document.createElement("home-assistant");
    app.hass = { user: { is_admin: isAdmin } };
    const mk = (tag, parent, props) => {
      const el = document.createElement(tag);
      Object.assign(el, props || {});
      parent.appendChild(el);
      return el;
    };
    const sr1 = app.attachShadow({ mode: "open" });
    const panel = mk("ha-panel-lovelace", sr1);
    const sr2 = panel.attachShadow({ mode: "open" });
    const root = mk("hui-root", sr2);
    const sr3 = root.attachShadow({ mode: "open" });
    const bar = mk("div", sr3);
    mk("ha-icon-button", bar, { path: ${JSON.stringify(MAGNIFY)}, id: "btn-search" });
    mk("ha-icon-button", bar, { path: ${JSON.stringify(ASSIST)}, id: "btn-assist" });
    mk("ha-icon-button", bar, { path: ${JSON.stringify(OTHER)}, id: "btn-refresh" });
    // A frontend that changed the icon: only the label gives it away.
    mk("ha-icon-button", bar, { path: "M0,0L1,1Z", label: "Assist", id: "btn-assist-new-icon" });
    const item = mk("ha-md-menu-item", bar, { id: "menu-search" });
    mk("ha-svg-icon", item, { path: ${JSON.stringify(MAGNIFY)} });
    document.body.appendChild(app);
    // A button Home Assistant adds later, on a re-render.
    setTimeout(() => mk("ha-icon-button", bar, { path: ${JSON.stringify(MAGNIFY)}, id: "btn-search-late" }), 300);
  };
</script>
<input id="field">
</body></html>`;

const browser = await chromium.launch({ headless: true });
const out = { scenarios: {} };

async function run(name, isAdmin, steps) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  await page.route(`${ORIGIN}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/asset.js") return route.fulfill({ status: 200, contentType: "text/javascript", body: ASSET_JS });
    return route.fulfill({ status: 200, contentType: "text/html", body: PAGE });
  });
  await page.goto(ORIGIN + "/");
  await page.addScriptTag({ url: ORIGIN + "/asset.js" });
  await page.evaluate((a) => window.__build(a), isAdmin);
  await page.waitForTimeout(1600); // > the 1 s poll + the late button at 300 ms
  const state = await page.evaluate(() => {
    const sr = document.querySelector("home-assistant").shadowRoot
      .querySelector("ha-panel-lovelace").shadowRoot.querySelector("hui-root").shadowRoot;
    const vis = (id) => {
      const el = sr.querySelector("#" + id);
      return el ? getComputedStyle(el).display !== "none" && !el.hidden : null;
    };
    const menu = sr.querySelector("#menu-search");
    return {
      searchVisible: vis("btn-search"),
      assistVisible: vis("btn-assist"),
      refreshVisible: vis("btn-refresh"),
      assistRelabelledVisible: vis("btn-assist-new-icon"),
      lateSearchVisible: vis("btn-search-late"),
      menuSearchVisible: menu.hidden === false && getComputedStyle(menu).display !== "none",
    };
  });
  const keys = {};
  for (const [label, press] of steps) {
    await page.evaluate(() => { window.__opened.length = 0; document.getElementById("field").blur(); });
    if (label === "typing-a-in-a-field") await page.focus("#field");
    await page.keyboard.press(press);
    keys[label] = await page.evaluate(() => ({
      opened: [...window.__opened],
      value: document.getElementById("field").value,
    }));
  }
  out.scenarios[name] = { ...state, keys, errors };
  await page.close();
}

const STEPS = [
  ["a", "a"],
  ["e", "e"],
  ["ctrl-k", "Control+k"],
  ["typing-a-in-a-field", "a"],
];

try {
  await run("resident", false, STEPS);
  await run("admin", true, STEPS);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(out));
