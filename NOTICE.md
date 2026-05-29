# Third-party notices

The files under `custom_components/ga_frontend_bundle/community/` are **unmodified**
third-party Home Assistant Lovelace cards, vendored (downloaded verbatim) from
their upstream GitHub projects at the pinned versions below. Each retains its own
upstream copyright and license; this repository's own code (the integration,
vendoring tooling, tests) is MIT and does not relicense them.

Exact download URLs and sha256 hashes are recorded in
[`bundle.lock.yaml`](bundle.lock.yaml).

| Card | Version | License | Upstream project |
|---|---|---|---|
| card-mod | 4.0.0 | MIT | https://github.com/thomasloven/lovelace-card-mod |
| mushroom | 5.1.1 | Apache-2.0 | https://github.com/piitaya/lovelace-mushroom |
| button-card | 7.0.1 | MIT | https://github.com/custom-cards/button-card |
| mini-graph-card | 0.13.0 | MIT | https://github.com/kalkih/mini-graph-card |
| apexcharts-card | 2.2.3 | MIT | https://github.com/RomRider/apexcharts-card |
| auto-entities | 1.16.1 | MIT | https://github.com/thomasloven/lovelace-auto-entities |
| layout-card | 2.4.7 | MIT | https://github.com/thomasloven/lovelace-layout-card |
| vertical-stack-in-card | 1.0.1 | MIT | https://github.com/ofekashery/vertical-stack-in-card |
| slider-entity-row | 17.5.0 | MIT | https://github.com/thomasloven/lovelace-slider-entity-row |
| plotly-graph-card | 3.3.5 | see upstream repo | https://github.com/dbuezas/lovelace-plotly-graph-card |
| state-switch | 1.9.6 | MIT | https://github.com/thomasloven/lovelace-state-switch |
| template-entity-row | 1.4.1 | MIT | https://github.com/thomasloven/lovelace-template-entity-row |
| kiosk-mode | 13.0.0 | MIT | https://github.com/NemesisRE/kiosk-mode |
| simple-thermostat | 2.5.0 | MIT | https://github.com/nervetattoo/simple-thermostat |

`plotly-graph-card`: GitHub's license classifier did not auto-detect an SPDX id
for this repo; consult the upstream repository for its current license terms
before redistribution.

To regenerate the vendored files from the pinned sources, run
`python scripts/vendor.py --check` (verify) or `--update` (re-fetch).
