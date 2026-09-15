/**
 * Does every shipped first-party card end up in the registry Home Assistant
 * actually looks in?
 *
 * WHY A BROWSER
 * -------------
 * The rest of this repo can answer "does the file contain
 * `customElements.define(...)`". On a freshly flashed canary (2026-09-15) that
 * was TRUE for every first-party card while `customElements.get()` returned
 * nothing for all of them and the dashboard rendered Home Assistant's red
 * "Custom element doesn't exist" box. A file-content assertion is green in
 * exactly the state the operator calls broken, so it cannot be the gate.
 *
 * THE MECHANISM THIS HARNESS REPRODUCES
 * -------------------------------------
 * `home-assistant-frontend`'s `app.ts` imports
 * `@webcomponents/scoped-custom-element-registry` on its FIRST line, and that
 * polyfill ends with
 *
 *     Object.defineProperty(window, 'customElements', {
 *       value: new CustomElementRegistry(), configurable: true, writable: true });
 *
 * — a brand-new, EMPTY registry. Its `get()` reads only its own map. So a
 * `customElements.define()` that ran before that line lands in the native
 * registry and is invisible to every `customElements.get()` afterwards: the
 * define succeeds, no error is thrown, and the element never exists as far as
 * Home Assistant is concerned.
 *
 * Modules injected with `add_extra_js_url` are started by an inline
 * `<script>import("…")</script>` in `index.html`, side by side with the import
 * of the app bundle — so a small card file regularly finishes first. This
 * harness does not gamble on that race: it pins the WORST CASE (injected
 * modules execute before the swap) because that is the case observed on the
 * device, and asserts that the shipped delivery survives it.
 *
 * The three phases mirror the real page:
 *   1  `extra_modules`      — injected, races the app bootstrap (pre-swap)
 *   2  app bundle           — installs the polyfill, replaces window.customElements
 *   3  Lovelace resources   — loaded by the Lovelace panel, always post-swap
 *
 * Which asset goes in phase 1 and which in phase 3 is NOT decided here: it is
 * read from the delivery plan the integration itself produces (see
 * tests/test_cards_register_in_browser.py). This file only reports what the
 * browser did.
 *
 * Usage:  node cards-register.mjs <plan.json>     → JSON result on stdout
 */
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const POLYFILL = join(
  HERE,
  "node_modules/@webcomponents/scoped-custom-element-registry/scoped-custom-element-registry.min.js"
);

const planPath = process.argv[2];
if (!planPath) {
  console.error("usage: node cards-register.mjs <plan.json>");
  process.exit(2);
}
const plan = JSON.parse(readFileSync(planPath, "utf8"));
if (!existsSync(POLYFILL)) {
  console.error(
    "the scoped-custom-element-registry polyfill is missing — run `npm ci` in tests/browser"
  );
  process.exit(2);
}

/* ─── a server that serves what the device serves ──────────────────────── */

const PAGE = `<!doctype html><html><head><meta charset="utf-8"></head>
<body><home-assistant></home-assistant></body></html>`;

// The app bundle, reduced to the one thing that matters here: its first line.
const APP_JS =
  readFileSync(POLYFILL, "utf8") + "\n;window.__gaAppLoaded = true;\n";

const MIME = { ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json" };

const server = createServer((req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  const path = url.pathname;
  const send = (body, type) => {
    res.writeHead(200, { "content-type": type, "cache-control": "no-store" });
    res.end(body);
  };
  if (path === "/") return send(PAGE, "text/html");
  if (path === "/app/app.js") return send(APP_JS, "text/javascript");

  let file = null;
  if (path.startsWith("/fp/")) file = join(plan.root, path.slice("/fp/".length));
  else if (path.startsWith("/fixtures/")) file = join(HERE, "fixtures", path.slice("/fixtures/".length));

  if (file && existsSync(file)) return send(readFileSync(file), MIME[extname(file)] || "text/plain");
  res.writeHead(404, { "content-type": "text/plain" });
  res.end("not found");
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const fpUrl = (c) => `${base}/fp/${c.id}/${c.file}` + (plan.version ? `?v=${plan.version}` : "");

const browser = await chromium.launch({ headless: true });
const result = { defines: {}, live: {}, tagOwner: {}, errors: [], guard: null };

try {
  /* ─── phase 0: what does each shipped asset define? ──────────────────────
   * Measured by RUNNING it, one asset per pristine page — never by reading the
   * source, which is the check that was green while the cards were broken.
   * An asset that defines nothing (a global side-effect module) reports [].
   */
  for (const card of [...plan.inject, ...plan.resource]) {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    await page.goto(base);
    const tags = await page.evaluate(async (url) => {
      window.__defined = [];
      const reg = window.CustomElementRegistry.prototype;
      const native = reg.define;
      reg.define = function (name, ...rest) {
        window.__defined.push(name);
        return native.call(this, name, ...rest);
      };
      try {
        await import(url);
      } catch (err) {
        return { error: String(err) };
      }
      return { tags: window.__defined };
    }, fpUrl(card));
    await page.close();
    if (tags.error || pageErrors.length) {
      result.errors.push({ id: card.id, error: tags.error || pageErrors[0] });
      result.defines[card.id] = [];
      continue;
    }
    result.defines[card.id] = tags.tags;
    for (const t of tags.tags) result.tagOwner[t] = card.id;
  }

  /* ─── phases 1-3: the real page order ─────────────────────────────────── */
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => result.errors.push({ id: "<page>", error: String(e) }));
  await page.goto(base);
  // Identity of the pre-swap registry, so "was it replaced" is an observation,
  // not a guess about a constructor name.
  await page.evaluate(() => {
    window.__nativeRegistry = window.customElements;
  });

  const injected = plan.inject.map(fpUrl).concat([`${base}/fixtures/lost-card.js`]);
  const resources = plan.resource.map(fpUrl).concat([`${base}/fixtures/late-card.js`]);

  // 1 — extra_modules, before the app bundle finishes (the observed worst case)
  await page.evaluate(async (urls) => {
    for (const u of urls) {
      try {
        await import(u);
      } catch (e) {
        (window.__importFailures ||= []).push(`${u}: ${e}`);
      }
    }
  }, injected);

  // 2 — the app bundle installs the scoped-registry polyfill
  await page.evaluate(async (u) => import(u), `${base}/app/app.js`);
  const swapped = await page.evaluate(
    () => !!window.__gaAppLoaded && window.customElements !== window.__nativeRegistry
  );

  // 3 — the Lovelace panel loads its resources, long after the swap
  await page.evaluate(async (urls) => {
    for (const u of urls) {
      try {
        await import(u);
      } catch (e) {
        (window.__importFailures ||= []).push(`${u}: ${e}`);
      }
    }
  }, resources);

  const expected = Object.values(result.defines).flat();
  result.live = await page.evaluate((tags) => {
    const out = {};
    for (const t of tags) out[t] = !!window.customElements.get(t);
    return out;
  }, expected);
  result.importFailures = await page.evaluate(() => window.__importFailures || []);
  // Diagnostic: what the card self-advertisement array holds at the end. A card
  // that executed pushes here even when its element is lost to the swap, so a
  // report of "customCards is empty" means something ELSE than a lost define.
  result.customCards = await page.evaluate(() =>
    (window.customCards || []).map((c) => c && c.type)
  );
  result.appLoaded = swapped;

  /* ─── the guard: it must shout about the must-flag fixture and stay quiet
   * about the must-not-flag one. Waits for the guard's own timer — no test
   * hook is called, so a guard that never fires reads as a failure.        */
  const hasGuard = plan.inject.some((c) => c.id === "ga-registry-guard");
  if (hasGuard) {
    await page.waitForFunction(() => window.__gaRegistryGuardReported === true, null, {
      timeout: 20000,
    });
  }
  result.guard = {
    present: hasGuard,
    consoleErrors,
    flaggedLostFixture: consoleErrors.some((t) => t.includes("ga-fixture-lost-card")),
    flaggedLateFixture: consoleErrors.some((t) => t.includes("ga-fixture-late-card")),
  };
  await page.close();
} finally {
  await browser.close();
  server.close();
}

process.stdout.write(JSON.stringify(result, null, 2));
