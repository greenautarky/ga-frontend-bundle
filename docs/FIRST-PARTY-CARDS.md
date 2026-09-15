## ga-thermostat-card (1.3.0, Odoo #518)

The resident **Steuerung** control — big current value, +/- setpoint, and an
explicit **AUS / MANUEL / KI** mode row — talking straight to `climate.*`
services (`set_temperature` / `set_hvac_mode`). First-party: it **replaced the
vendored community `simple-thermostat`** (dropped from the bundle in 1.3.0),
so the Steuerung look now ships as our own code. `thermostat_style: "core"`
still selects the plain HA thermostat dial.

```yaml
type: custom:ga-thermostat-card
entity: climate.wohnzimmer
header: Steuerung   # optional
```

# First-party GA cards

Most cards in this bundle are **vendored** community cards: pinned in
`bundle.lock.yaml`, downloaded by `scripts/vendor.py` into
`custom_components/ga_frontend_bundle/community/<id>/<file>.js`, and
integrity-checked (`vendor.py --check`, `test_vendored.py`).

**First-party** cards — authored by GreenAutarky — live separately in
`custom_components/ga_frontend_bundle/first_party/<id>/<file>.js` so the vendor
lock/integrity machinery never touches them. They are loaded and served by the
**same** mechanism (`_serve_inject`), under their own static URL base
(`/ga_frontend_bundle_first_party`).

### How a first-party asset reaches the browser — and why it matters

There are two delivery paths and only one of them works for a card:

| path | when the module runs | use it for |
|---|---|---|
| `add_extra_js_url` (early injection) | during the frontend's bootstrap | assets that define **no** custom element |
| Lovelace **resource** | when the Lovelace panel loads, after bootstrap | everything that calls `customElements.define()` |

`home-assistant-frontend`'s app bundle imports
`@webcomponents/scoped-custom-element-registry` on its **first line**, and that
polyfill ends by replacing `window.customElements` with a brand-new, empty
registry whose `get()` reads only its own map. Injected modules are started by an
inline `<script>import(...)</script>` in `index.html`, side by side with the
import of the app bundle — so a small card file regularly finishes first, its
`customElements.define()` lands in the pre-swap registry, and
`customElements.get()` returns nothing for it forever after. Nothing throws.
Home Assistant then renders *"Custom element doesn't exist"* (card) or *"Timeout
waiting for strategy element"* (strategy).

That is what broke **every** first-party card on a freshly flashed canary on
2026-09-15, while every file was fetched, served 200 and contained its
`define()`. The strategy had been moved to the resource path in an earlier fix;
the note that "cards do not care, they resolve lazily" was wrong — lazily
resolved or not, a card is resolved against the **post-swap** registry.

So the injection list (`const.EARLY_INJECT_ASSET_IDS`) is an **allow-list**:
anything not on it is a Lovelace resource. See `bundle.delivery_plan()`.

`first_party/ga-registry-guard/` is the watchdog for this failure class: it
records every `ga-*` / `ll-strategy-*` element defined against the pre-swap
registry and writes a `console.error` naming the ones that are not in the live
registry afterwards. It defines no element itself, so it cannot be a victim of
what it watches.

To add a first-party card: drop `first_party/<card-id>/<card-id>.js` (a vanilla
custom element that `customElements.define(...)`s and pushes to
`window.customCards`). No build step, no lock entry, and **no list to edit**:
`load_cards` auto-discovers it and it is delivered as a Lovelace resource by
default. `tests/test_cards_register_in_browser.py` picks it up automatically and
proves in a headless Chromium that it really registers.

## Cards

| id | element | purpose |
|---|---|---|
| `ga-master-card` | `custom:ga-master-card` | Main-user management UI: invite sub-users, assign dashboards, **lock/unlock** + **remove** sub-users, rename rooms. Thin client over the in-Core `greenautarky_site` endpoints (server enforces the main-user flag + parent relation). Uses the `hass` object directly — no token handling. |

Why a card (not the served `/greenautarky-master` console): a Lovelace card gets
the `hass` object from the frontend, so there is no `localStorage` token to find
(the console breaks with "keep me logged in"). The card renders in `<ha-card>`
with its own styled `<button>`s (no `mwc-button` dependency). Canary-verified.

See **ADR-0009** (this card) and **ADR-0006** (the plane + endpoints) in
`ga-ihost-docs`, and Odoo task #427 / subtask #443.

## ga-home-strategy — the generated per-user home dashboard

`custom:ga-home` (a dashboard **strategy**, not a card). The whole household uses
ONE dashboard whose stored config is nothing but
`{"strategy": {"type": "custom:ga-home"}}`; views are generated in the browser on
every load from the rooms the server grants the logged-in user
(`GET /api/greenautarky_site/my_rooms`). See KB #152 for the architecture.

### Options (1.2.0)

Set in the dashboard config: `strategy: { type: "custom:ga-home", <option>: … }`.
Defaults are the look piloted live on KIB-SON-00000050 (2026-07-21):

| option | default | effect |
|---|---|---|
| `text_tabs` | `true` | Views carry **no icon**, so HA renders the room **name** in the tab bar. A row of identical door icons distinguishes nothing; names do. `false` restores the icons. |
| `single_thermostat` | `true` | TRVs in one room are **coupled** (they mirror each other) — render **one** Steuerung card and **one** Heizplan per room instead of one per valve. |
| `thermostat_style` | `"myvibe"` | The Steuerung card residents know from the MyVibe dashboards: `simple-thermostat` (vendored, 2.5.0) with the big value and an explicit **AUS / MANUEL / KI** mode row (KI = auto, MANUEL = heat). `"core"` renders HA's thermostat dial with an hvac-mode feature row instead. |
| `hide_household` | `false` | Drop the "Haushalt" overview view. For pilot devices that keep their hand-built overview dashboard next to GA Home. |
| `hide_roomless` | `false` | Drop the "Ohne Raum" view (devices without an area). |

Room badges (temperature / humidity / battery) are labeled **Temperatur /
Luftfeuchtigkeit / Batterie** — the raw entities carry IEEE-address names on
fleet devices.

Origin: piloted additively on Ramin's device (KIB-SON-00000050) next to his
original dashboards — old and new design stay switchable via the sidebar; the
device pins nothing, this bundle is the single source of the new look.
