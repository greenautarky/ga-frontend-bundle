# `ga_frontend_bundle` integration — technical reference

A stateless Home Assistant integration that serves the vendored Lovelace cards
and makes their `custom:*` elements available on every dashboard — a
self-contained replacement for HACS-managed Lovelace resources.

## Files

```
custom_components/ga_frontend_bundle/
├── __init__.py        # async_setup: register static dir + add_extra_js_url per card
├── bundle.py          # pure (stdlib-only) helpers: load_cards(), card_url()
├── const.py           # DOMAIN, STATIC_URL_BASE, COMMUNITY_DIRNAME
├── manifest.json      # domain, version (= bundle_version), deps: http + frontend
└── community/
    ├── cards.json     # generated index: [{id, file}, …] in load order
    └── <id>/<file>.js # the vendored card bundles
```

## Lifecycle

`async_setup(hass, config)` (no config_flow, no config entry):

1. Idempotent guard on `DOMAIN in hass.data`.
2. `load_cards()` (in the executor — it does filesystem I/O) reads
   `community/cards.json`; falls back to scanning each subdir for its single
   `.js`. Only entries whose file exists on disk are returned, so a partial
   vendor can never inject a 404 module.
3. Registers the whole `community/` dir as one static path:
   `StaticPathConfig("/ga_frontend_bundle_static", community_dir, cache=True)`.
4. For each card: `add_extra_js_url(hass, "/ga_frontend_bundle_static/<id>/<file>.js")`
   so the module is loaded by the frontend and its custom element registers.
5. Stores `{"cards": [...], "injected": N}` in `hass.data[DOMAIN]`.

It never blocks HA start: if the bundle is empty (vendoring didn't run) it logs
an error and returns `True`.

## Why stateless (no config_flow, no Store)

The integration carries no per-device state — it just publishes static assets.
Avoiding `config_flow` sidesteps the activation deadlock that bit onboarding (a
config_flow integration is discovered but never loaded until something writes its
config entry; its own views 404 so the flow can't bootstrap itself). Instead it
loads via the `async_setup` YAML path: converge ensures `ga_frontend_bundle:` is
present in `configuration.yaml` (the enable-list). Avoiding a `Store` removes the
storage-version mismatch class of bug entirely.

## Served URLs

`/ga_frontend_bundle_static/<id>/<file>.js`, e.g.
`/ga_frontend_bundle_static/button-card/button-card.js`. This is self-contained —
it does **not** depend on `/config/www` (`/local/…`) or HACS's `/hacsfiles/…`.

## Verifying it's loaded (on a device)

```bash
# integration loaded?
curl -s http://homeassistant:8123/api/config | jq '.components | map(select(. == "ga_frontend_bundle"))'
# a card served?
curl -s -o /dev/null -w '%{http_code}\n' \
  http://homeassistant:8123/ga_frontend_bundle_static/button-card/button-card.js   # -> 200
```

## Known characteristic: all cards load on every frontend page

`add_extra_js_url` injects every card module into the frontend, so all ~6 MB of
card JS is requested on first frontend load (then browser-cached). This matches
the prior HACS-resources behaviour (HACS also loads all registered resources on
dashboard load) and is not a regression. If page-weight ever matters, a future
option is to register the cards as Lovelace *resources* (loaded only on Lovelace
dashboards) instead of frontend extra-modules; that requires manipulating the
Lovelace resource store and is intentionally avoided here for robustness in
storage mode.
