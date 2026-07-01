# First-party GA cards

Most cards in this bundle are **vendored** community cards: pinned in
`bundle.lock.yaml`, downloaded by `scripts/vendor.py` into
`custom_components/ga_frontend_bundle/community/<id>/<file>.js`, and
integrity-checked (`vendor.py --check`, `test_vendored.py`).

**First-party** cards — authored by GreenAutarky — live separately in
`custom_components/ga_frontend_bundle/first_party/<id>/<file>.js` so the vendor
lock/integrity machinery never touches them. They are loaded, served, and
injected by the **same** mechanism (`_serve_inject`), but under their own static
URL base (`/ga_frontend_bundle_first_party`).

To add a first-party card: drop `first_party/<card-id>/<card-id>.js` (a vanilla
custom element that `customElements.define(...)`s and pushes to
`window.customCards`). No build step, no lock entry. `load_cards` auto-discovers
it; `__init__.py` serves + injects it on every dashboard.

## Cards

| id | element | purpose |
|---|---|---|
| `ga-master-card` | `custom:ga-master-card` | Main-user management UI: invite sub-users, assign dashboards, **lock/unlock** + **remove** sub-users, rename rooms. Thin client over the in-Core `greenautarky_onboarding` endpoints (server enforces the main-user flag + parent relation). Uses the `hass` object directly — no token handling. |

Why a card (not the served `/greenautarky-master` console): a Lovelace card gets
the `hass` object from the frontend, so there is no `localStorage` token to find
(the console breaks with "keep me logged in"). The card renders in `<ha-card>`
with its own styled `<button>`s (no `mwc-button` dependency). Canary-verified.

See **ADR-0009** (this card) and **ADR-0006** (the plane + endpoints) in
`ga-ihost-docs`, and Odoo task #427 / subtask #443.
