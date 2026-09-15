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

# First-party assets that are injected EARLY via add_extra_js_url. Everything
# else under first_party/ is delivered as a Lovelace resource instead — see
# bundle.delivery_plan() for why that distinction decides whether a card works
# at all. This is an allow-list: a new asset is a resource by default.
EARLY_INJECT_ASSET_IDS = (
    # Records every GA element defined against the pre-swap registry and shouts
    # in the console if one is not visible afterwards. Defines no element of its
    # own, so it is immune to the very failure it detects, and it has to run
    # early — after the swap there is nothing left to observe.
    "ga-registry-guard",
    # A sidebar nudge, not an element: it must run on every page, not only on a
    # dashboard, so a Lovelace resource would be the wrong carrier.
    "ga-sidebar-default",
)
