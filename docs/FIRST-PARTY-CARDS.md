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
| `ga-master-card` | `custom:ga-master-card` | Master-User Management Plane UI (ADR-0006): invite sub-users, assign dashboards, rename rooms. Thin client over the in-Core `greenautarky_onboarding` endpoints (server enforces the master flag + parent relation). |

See ADR-0006 (`ga-ihost-docs`) and Odoo task #427 / subtask #443.
