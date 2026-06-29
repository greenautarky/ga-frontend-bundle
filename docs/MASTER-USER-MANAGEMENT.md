# Master-User Management Plane — this repo's role

> Design pointer. Authoritative design: **ADR-0006** in `ga-ihost-docs`
> (`adr/ADR-0006-master-user-management.md`). Odoo task
> [#427](https://greenautarky.odoo.com/odoo/project/17/tasks/427), KB
> [#96](https://greenautarky.odoo.com/odoo/knowledge/96). Status: **proposed**, not
> yet implemented.

## Why this repo

The Master-User is a Home Assistant **Non-Admin** whose only surface is the HA
frontend (dashboards). A Non-Admin cannot open Settings or add-on Ingress panels,
so the Master's management UI must sit **inside a dashboard**.

**This repo ships the Master front door: a custom Lovelace card / panel.** The
card calls the in-Core component's (`greenautarky_onboarding`) authenticated
scoped API for the four Master ops + the dashboard matrix.

## Planned additions

- A GA custom card placed on the Master's dashboard offering:
  - create / remove sub-user,
  - assign dashboards via a `[Sub-User × Dashboard]` matrix,
  - rename areas and entities.
- The card is a **thin client**: it only calls the in-Core component's API. All
  authorization (master flag + parent relation) is enforced server-side in the
  component — UI gating is convenience, **not** a security boundary.

## Why a card, not gated Settings

Re-using HA's native Settings for a Non-Admin would need a **frontend fork**
(Non-Admins cannot see Settings at all). The custom card works out of the box on
a dashboard with no fork. Gating native Settings stays a possible later path (see
ADR-0006) but is deferred.
