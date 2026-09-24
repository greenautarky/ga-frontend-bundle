/**
 * Run one of the shipped first-party scripts and evaluate an expression in it.
 *
 * WHY THIS EXISTS
 * ---------------
 * The rest of this repo's tests read the JS as TEXT and assert that a string is
 * present. That answers "is the line there", never "does the code do it" — and
 * a card whose only defect is that a label lives in an attribute instead of in
 * the text passes every string check ever written about it.
 *
 * The first-party files are plain browser SCRIPTS (no `export`), so every
 * top-level `function` and `class` in them lands directly on the context
 * object when the file is run in a `vm`. That makes the REAL SHIPPED BYTES
 * callable with nothing but Node's stdlib — no npm install, no bundler, no
 * jsdom, and nothing between the test and the file the device serves.
 *
 * Usage:
 *   node tests/js/eval.mjs <path-to-js> <expression>
 * Prints `JSON.stringify(result)` on stdout.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , file, expression] = process.argv;
if (!file || !expression) {
  console.error("usage: node eval.mjs <file.js> <expression>");
  process.exit(2);
}

/** The few browser globals the files touch at load time. */
function browserContext() {
  const win = {};
  const ctx = {
    // Registration side effects — recorded, not executed.
    customElements: {
      _defined: {},
      define(name, cls) {
        this._defined[name] = cls;
      },
      // ga-master-card guards its define with get(), as a browser allows.
      get(name) {
        return this._defined[name];
      },
    },
    HTMLElement: class HTMLElement {},
    console,
    // `window.customCards` / `window.customStrategies` self-advertisement.
    window: win,
    setTimeout,
    clearTimeout,
    JSON,
    Math,
    Date,
    fetch: async () => {
      throw new Error("network is not available in this harness");
    },
  };
  ctx.window = ctx;
  ctx.globalThis = ctx;
  Object.assign(ctx, win);
  return vm.createContext(ctx);
}

const ctx = browserContext();
vm.runInContext(readFileSync(file, "utf8"), ctx, { filename: file });
const result = vm.runInContext(`(${expression})`, ctx, { filename: "<expression>" });
process.stdout.write(JSON.stringify(result === undefined ? null : result));
