"""Constants for the ga_frontend_bundle integration."""

DOMAIN = "ga_frontend_bundle"

# Static route under which the vendored card files are served, e.g.
# /ga_frontend_bundle_static/button-card/button-card.js
STATIC_URL_BASE = "/ga_frontend_bundle_static"

# Subdir (next to this package) holding the vendored card files + cards.json.
COMMUNITY_DIRNAME = "community"

# First-party GA cards (authored here, NOT vendored from the community lock).
# Kept in a separate dir so scripts/vendor.py + bundle.lock.yaml integrity
# checks never touch them. Same load/serve/inject mechanism. e.g.
# /ga_frontend_bundle_first_party/ga-master-card/ga-master-card.js
FIRST_PARTY_DIRNAME = "first_party"
FIRST_PARTY_URL_BASE = "/ga_frontend_bundle_first_party"

# First-party assets that are Lovelace *strategies*, not cards.
#
# A strategy MUST be registered as a Lovelace resource, not merely injected via
# add_extra_js_url: the lovelace panel loads its resources BEFORE it resolves the
# dashboard's `strategy:` block, whereas an injected module races the app bootstrap.
# HA gives a strategy element only 5 s to register (MAX_WAIT_STRATEGY_LOAD) and then
# renders "Timeout waiting for strategy element …" — which is exactly what happened
# on a canary (K0, 2026-07-13): the module was fetched but lost the race.
STRATEGY_ASSET_IDS = ("ga-home-strategy",)
