# ga-frontend-bundle

GreenAutarky's curated set of Home Assistant **Lovelace frontend cards**, shipped
as a single **vendored custom integration** instead of via HACS.

On GA devices (Sonoff iHost / KIB-SON) these cards used to be installed with HACS,
which means a runtime dependency on the GitHub API, a device-flow auth token,
rate limits, a background integration, and manual per-device updates. This repo
replaces all of that: the cards are **pinned** in [`bundle.lock.yaml`](bundle.lock.yaml),
**vendored** (downloaded + hash-verified) at build time, and served by a tiny
stateless integration that registers them as frontend modules. No HACS, no
GitHub access at runtime, no per-device clicks.

## The bundle

14 cards (see [`bundle.lock.yaml`](bundle.lock.yaml) for the exact pinned URLs +
sha256, and [NOTICE.md](NOTICE.md) for upstream attribution):

| id | version | license | upstream |
|---|---|---|---|
| card-mod | 4.0.0 | MIT | thomasloven/lovelace-card-mod |
| mushroom | 5.1.1 | Apache-2.0 | piitaya/lovelace-mushroom |
| button-card | 7.0.1 | MIT | custom-cards/button-card |
| mini-graph-card | 0.13.0 | MIT | kalkih/mini-graph-card |
| apexcharts-card | 2.2.3 | MIT | RomRider/apexcharts-card |
| auto-entities | 1.16.1 | MIT | thomasloven/lovelace-auto-entities |
| layout-card | 2.4.7 | MIT | thomasloven/lovelace-layout-card |
| vertical-stack-in-card | 1.0.1 | MIT | ofekashery/vertical-stack-in-card |
| slider-entity-row | 17.5.0 | MIT | thomasloven/lovelace-slider-entity-row |
| plotly-graph-card | 3.3.5 | see upstream | dbuezas/lovelace-plotly-graph-card |
| state-switch | 1.9.6 | MIT | thomasloven/lovelace-state-switch |
| template-entity-row | 1.4.1 | MIT | thomasloven/lovelace-template-entity-row |
| kiosk-mode | 13.0.0 | MIT | NemesisRE/kiosk-mode |
| simple-thermostat | 2.5.0 | MIT | nervetattoo/simple-thermostat |

## How it works

```
bundle.lock.yaml ──(scripts/vendor.py)──> custom_components/ga_frontend_bundle/community/<id>/<file>.js
                                           custom_components/ga_frontend_bundle/community/cards.json
HA loads ga_frontend_bundle (async_setup):
  • serves community/ as a static dir at /ga_frontend_bundle_static/
  • add_extra_js_url(<base>/<id>/<file>.js) for each card
  → custom:* elements resolve on every dashboard
```

The integration is **stateless**: no `config_flow`, no HA `Store`. It is
activated by `ga_frontend_bundle:` in `configuration.yaml`. See
[docs/INTEGRATION.md](docs/INTEGRATION.md) for the technical detail.

## How it ships on GA devices

Same `bake → stage → place → activate` chain as the onboarding integration:

1. **Bake** — `custom_components/ga_frontend_bundle/` is copied into the GA OS
   image at `…/rootfs-overlay/usr/share/ga/custom_components/`.
2. **Stage** — `ga-bootstrap` stages it to `/share/ga-custom-components/` on boot.
3. **Place** — the ga_manager `converge` step copies it into `/config/custom_components/`.
4. **Activate** — converge ensures `ga_frontend_bundle:` is in `configuration.yaml`.

Delivery is **OS-rootfs-first** (fleet-push carrier comes later). The exact
converge contract for the onboarding/converge owner is in
[docs/CONVERGE-HANDOFF.md](docs/CONVERGE-HANDOFF.md); the shared OS-side reference
is `ga-ihost-docs/VENDORED-INTEGRATION-DELIVERY.md`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest PyYAML ruff

# verify the committed vendored tree matches the lock (offline)
python scripts/vendor.py --check

# lint + unit tests
ruff check . && pytest -q
```

### Updating / adding a card

1. Edit the card's `version` + `url` (+ `source`) in `bundle.lock.yaml`, or add a
   new entry.
2. Re-vendor and refresh hashes:
   ```bash
   python scripts/vendor.py --update
   ```
   This re-downloads, rewrites `sha256` in the lock, regenerates `community/cards.json`,
   and syncs the integration manifest `version` to `bundle_version`.
3. Bump `bundle_version` in `bundle.lock.yaml` when you cut a bundle release.
4. Commit the changed lock **and** the changed `community/` files together.

CI (`.github/workflows/ci.yml`) re-downloads every card and fails if the bytes no
longer match the committed `sha256` (supply-chain gate), plus runs the offline
integrity check, ruff, and the unit tests.

## License

GreenAutarky's own code here is MIT ([LICENSE](LICENSE)). The vendored card files
each retain their upstream license — see [NOTICE.md](NOTICE.md).
