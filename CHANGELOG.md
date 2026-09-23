# Changelog

## 1.18.0

- **The whole-home heating controls, on a tab called `Profil`.** Boost every
  room for five minutes, switch every room off, and a Sonderplan for sickness or
  a holiday. The card owns no heating logic: every button calls something
  `ga_heating` already had — the engine, its validation and its expiry live in
  Core, where they survive a restart a browser tab does not.

  The name is not new. The previous system had exactly this view, read in
  `ha-dashboard-automation/templates/profile_view_template.j2` on 2026-09-23,
  whose grid is literally `"boost override" / "schedule override"`. Residents of
  that system look for these controls under that word.

  It is generated only where a room entity carries a `valves` list, and never for
  a room-scoped sub-user — "alle Räume aus" must not be offered to someone who
  holds two of the flat's six rooms. The first attempt put the card in the
  household view and reached nobody: `hide_household` defaults to true, so that
  view exists on no device.

- **Four things the old Profil view had and this card did not**, all measured in
  that template rather than invented:

  - the **status is always visible** and the form collapses behind a toggle. An
    override whose status is only visible where it was entered is the invisible
    override `ga_heating`'s own source warns about;
  - **`Alle Räume` is its own switch.** "Nothing ticked = all rooms" was the
    first implementation and reads as "none";
  - the **boost shows its remaining time**, from `ga_heating` 0.10.0's new
    `override` attribute — the number the old view had from a real timer;
  - a holiday's **end carries a time**, in literal 15-minute options. The old
    source states the reason: "option text is literal, so locale-independent -
    no native 12h/AM-PM picker". Ending at 23:59 means a cold flat on the day
    the resident comes home.

  What is deliberately NOT taken is the old design's `_saved` twin for every
  field. That two-stage commit existed because its "form" was twenty live
  entities that would otherwise take effect as they were typed.

- **"Alle Räume aus" says at which temperature the valves still open**, read from
  each valve's own `frost_protection_temperature`. On a SONOFF TRVZB
  `system_mode: off` IS the anti-freeze state, while `ga_heating`'s own OFF is
  deliberately not a low setpoint — so the protection comes from the hardware and
  the card must not promise it without looking. Measured on KIB-SON-00000031:
  7 °C, not the 5 °C the vendor documents as the default.

## 1.17.0

- **The thermostat card leads with the target, not with the measurement.** Both
  looks showed the room's current temperature — `classic` as the large number,
  `setpoint` as an "aktuell …" line above it — and put the setpoint, the one
  value a resident can act on, in a small row underneath. Asked for on
  2026-09-23: show the target only. `show_current: true` puts the measurement
  back for a diagnostic view; the default is off. The measurement itself is
  untouched — still on the entity, still drawn by the temperature/humidity view.

  The `dial` look had the same defect in a third place (`.d-cur` inside the SVG)
  and was missed by the first version of this change: it fixed the two looks a
  test drove and left the one nobody had asserted on. Found by a browser test
  against a canary, not by reading. Reachability is part of correctness.

- **The weekly plan is never an empty form.** The scheduler came back with no
  slots for a day and offered "+ Zeit hinzufügen" as the only way in, so a
  resident opening a fresh flat saw a blank week and a blank curve and had to
  invent a plan before the card could show one. Now exactly five times per day,
  always present; add and remove are gone.

  Five is not a number anyone liked: the canonical table the installation has
  used since 2026-06 (`ha-dashboard-automation`,
  `scripts/apply_default_profile_schedule.py`) has exactly five entries per day
  per room. And the padding invents nothing — a filled slot takes the
  temperature ALREADY IN FORCE at that time of day from whatever the plan
  already says, falling back only to the thermostat's own current target, which
  is a real number on the card above. A day that already carries MORE than five
  is left alone: trimming would be a silent loss of the resident's plan dressed
  up as tidying.

  Observed on KIB-SON-00000031 on 2026-09-23: the selected day went from 4 slots
  to 5, and the same browser check fails on the previous cards with
  "The plan offers 4 times for the selected day".

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
