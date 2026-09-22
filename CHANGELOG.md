# Changelog

## 1.16.0

- **Only the community cards we actually place are injected.** All thirteen
  vendored cards rode along on every dashboard load; two are used. Measured on
  a device over the resident URL on 2026-09-22: 6.1 MB arrived before the
  browser started our own assets — plotly-graph-card 3.1 MB / 10.2 s,
  apexcharts-card 1.6 MB, mushroom 700 KB — while ga-heating-card (13 KB) only
  began downloading at 10.2 s and appeared at 11.3 s in one run and 28 s in
  another. Not one of those three is referenced anywhere in this repository or
  in `greenautarky_site`; they are named only in ga-home-strategy's own comment
  recording that HA core replaced them. The allow-list is `simple-thermostat`
  (the `simple` style's card) and `card-mod` (the style key inside it) —
  160 KB instead of 6.1 MB. The other eleven stay vendored and statically
  served, so a Lovelace resource can still load one.
- **The injected set has a byte budget**: 256 KB, deterministic, no browser and
  no network, so it can fail a pull request. Today's number is 155 KB
  (card-mod 87, simple-thermostat 62, ga-registry-guard 4, ga-sidebar-default 3).
  A wall-clock threshold on a mesh-linked device would flake and then be
  ignored; the time this buys is measured separately on a real device. The
  budget carries its own red proof — the largest vendored card alone is over
  it — because a limit that cannot be exceeded measures nothing.
- A gate reads the live sources and the live constant and compares both
  directions: a card placed but not injected is a dashboard that renders an
  error card; a card injected but not placed is this defect coming back. A
  mention in a comment does not count as a use — that distinction is why this
  went unnoticed.

## 1.12.0 — the cards actually register (2026-09-15)

**Fixed — no first-party card existed in the browser.** Measured in a real
browser on a freshly flashed canary: `customElements.get()` returned nothing for
`ga-heating-card`, `ga-thermostat-card` and `ga-master-card`, while every file
was fetched, served 200 and contained its `customElements.define(...)`. The
operator saw three separate symptoms with one cause — the heating plan card
rendering Home Assistant's red *"Custom element doesn't exist"*, the
**Verwalten** tab not loading, and the sidebar staying expanded.

*Mechanism:* the frontend's app bundle imports
`@webcomponents/scoped-custom-element-registry` on its first line, and that
polyfill replaces `window.customElements` with a new, empty registry whose
`get()` reads only its own map — so a card injected via `add_extra_js_url`, which
`index.html` starts with an inline `import()` racing that bundle, registers into
the pre-swap registry and is invisible afterwards, with nothing thrown or logged.
This is the same hazard that was already fixed for the dashboard *strategy* in an
earlier release; the note that "cards do not care, they resolve lazily" was
wrong.

*Fix:* every first-party asset is now delivered as a **Lovelace resource** — the
path the Lovelace panel loads after bootstrap — and `EARLY_INJECT_ASSET_IDS`
became an allow-list of assets that define no custom element. A card added later
is therefore delivered correctly without anyone editing a list.

**Added — `ga-registry-guard`.** Records every `ga-*` / `ll-strategy-*` element
defined against the pre-swap registry, cross-checks `window.customCards`, and
writes a `console.error` naming any element that is not in the live registry. It
defines no element itself, so it cannot be a victim of the failure it watches.
Server side, a first-party asset that cannot be delivered as a resource is now an
`ERROR` with the asset name, not a `warning` about strategies.

**Added — a headless-browser gate.** `tests/test_cards_register_in_browser.py`
drives Chromium through the load order `index.html` produces (injected modules →
the real registry-swap polyfill → Lovelace resources) and asserts every element
the shipped assets define is in the live registry. The asset list comes from
scanning `first_party/`, the element names from *running* each asset, and zero
assets or zero elements fail the run. Two fixtures pin both directions: an
element registered pre-swap must be flagged, one registered post-swap must not.

**Changed — tests that encoded the false belief.** `test_card_is_not_a_strategy`
asserted that cards keep the injection path, and `test_strategy_is_injected`
asserted an injection the code deliberately does not do. Both are replaced.
`STRATEGY_ASSET_IDS` is gone — one delivery policy, not two.
