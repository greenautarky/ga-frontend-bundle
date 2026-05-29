# `ga_frontend_bundle` — converge / OS-integration hand-off

**Audience:** the agent landing the shared `converge.py` changes (the onboarding /
converge owner). **Date:** 2026-05-29.

This is the concrete, filled-in version of the "Adding a new vendored integration"
checklist in `ga-ihost-docs/VENDORED-INTEGRATION-DELIVERY.md`, specialised for
`ga_frontend_bundle`. Read that doc first for the general `bake → stage → place →
activate` chain; this doc only states **what is different / required for this
component** so you can land the shared edits once, additively, for both
integrations.

---

## 1. What `ga_frontend_bundle` is

A **stateless** HA custom integration that ships the de-HACS Lovelace card bundle
(the ~14 frontend cards we used to install via HACS). On `async_setup` it:
- registers a static dir for the vendored card `.js` files, and
- calls `frontend.add_extra_js_url(...)` for each card so the custom elements
  (`custom:button-card`, `custom:mushroom-*`, …) are defined on every dashboard.

No GitHub, no HACS, no network at runtime. Source-of-truth repo:
`/home/user/git/ga-frontend-bundle` (→ `greenautarky/ga-frontend-bundle`).

**Crucial simplifications vs. onboarding** (they reduce your work):
- **No `config_flow`.** It loads purely via `async_setup` when `ga_frontend_bundle:`
  is present in `configuration.yaml`. So there is **no** config-entry to write and
  **no** config_flow self-bootstrap deadlock to worry about.
- **No HA `Store`.** It keeps no persistent state. So **do NOT write any
  `.storage/<key>` file for it** — storage-version gotcha (delivery doc step 5)
  does **not** apply here.

---

## 2. Already generic — nothing to do

- **Bake (step 1):** I drop `ga_frontend_bundle/` into
  `buildroot-external/rootfs-overlay/usr/share/ga/custom_components/`. (My edit,
  additive new dir.)
- **Stage (step 2):** `ga-bootstrap`'s `stage_custom_components()` already loops
  `…/custom_components/*/`, so it stages `ga_frontend_bundle` to
  `/share/ga-custom-components/ga_frontend_bundle/` every boot. **No change.**

## 3. Shared `converge.py` edits you are landing

### 3a. Place — generalize `_step_place_component` (the one shared edit)
Today it's hardcoded to `greenautarky_onboarding` (`COMPONENT_SRC`/`COMPONENT_DST`).
Generalize to loop **all** staged dirs:

```
for src in sorted(Path("/share/ga-custom-components").glob("*/")):
    name = src.name
    dst  = HA_CONFIG_DIR / "custom_components" / name
    # idempotent wholesale replace (rmtree + copytree), report new vs refreshed
```

After this, `ga_frontend_bundle` is placed automatically — **no per-component code.**
Keep the "newest wins" wholesale replace so an OS update that ships a newer bundle
always overwrites `/config`.

### 3b. Activate — enable-list must include `ga_frontend_bundle`
HA will not load it unless `configuration.yaml` has the key. Add the **domain
string** `ga_frontend_bundle` to the enable-list converge maintains (alongside
`greenautarky_onboarding`). Ensure-present must be idempotent (grep-guard /
ruamel round-trip — your call), e.g. resulting file contains:

```yaml
greenautarky_onboarding:
ga_frontend_bundle:
```

Both are bare keys (empty config). One list, two entries; next integration = one
more list entry, no new code path.

### 3c. NO storage write for this component
Explicitly: do **not** create `.storage/ga_frontend_bundle`. It has no `Store`.

### 3d. `provision_verify` loaded-check
Add `ga_frontend_bundle` to the set of domains the self-check asserts are present
in Core `GET /api/config` → `.components`. (Same mechanism as the onboarding
loaded-check.) This catches a discovered-but-not-loaded regression for the bundle
exactly like for onboarding.

## 4. Bundle-drift key (held shared edit — coordinate before push)
So fleet-manager reports drift on the bundle, add to `/share/ga-fleet-bundle.yaml`:

```yaml
versions:
  frontend_bundle: "<bundle-version>"   # = ga-frontend-bundle repo release / bundle.lock version
```

and parse it in `ga_manager/.../bundle_expectation.py` (and surface in fleet-manager
drift like the other `versions.*` keys). I will provide the exact version string
once the repo's `bundle.lock` is finalised. This is in a shared repo — I'm holding
it; let's sync before either of us pushes `ga_manager` / `ha-operating-system` /
`ga-ihost-docs`.

## 5. Activation timing / restart
No new Core restart needed. `ga_frontend_bundle` loads on the **same natural
first-boot Core restart** that already loads the placed components + the MQTT
config entry (converge does not itself restart Core on a fresh device). Place
(3a) + enable-list (3b) must both be in effect before that restart — they run in
the same converge pass as the onboarding equivalents, so ordering is already
satisfied.

## 6. My integration's contract (for your reference / self-checks)
- **domain:** `ga_frontend_bundle`
- **manifest:** `config_flow: false` (key omitted), `dependencies: ["http", "frontend"]`,
  `iot_class: local_polling`, `version: <bundle-version>`.
- **served URL prefix:** card files served under `/ga_frontend_bundle_static/<card>/<file>.js`
  (registered via `hass.http.async_register_static_paths`). Not `/local/…`, not
  `/hacsfiles/…` — self-contained, no dependence on `/config/www`.
- **loaded signal:** `ga_frontend_bundle` appears in `/api/config` `components`,
  and `GET /ga_frontend_bundle_static/<card>/<file>.js` returns 200.

## 7. Ownership split
| Area | Owner |
|---|---|
| `ga-frontend-bundle` repo (integration, `bundle.lock`, `vendor.py`, tests, CI, docs) | **me** |
| `ga_frontend_bundle/` dir in `rootfs-overlay` (additive new dir) | **me** |
| `converge.py` place-generalization + enable-list (3a–3c) | **you** |
| `provision_verify` loaded-check incl. this domain (3d) | **you** |
| `ga-fleet-bundle.yaml` + `bundle_expectation.py` drift key (§4) | coordinate (held) |
| canary validation on KIB-SON-0 (I'll simulate place+activate manually first) | **me** |

## 8. Coordination
Everything additive. The placement generalization is the single shared converge
step — you land it once for both components. I will not touch `converge.py`. I'm
holding the §4 shared-repo edits and will ping before any push to `ga_manager` /
`ha-operating-system` / `ga-ihost-docs`.
