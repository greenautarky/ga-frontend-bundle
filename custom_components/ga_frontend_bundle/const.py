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
# Vendored community cards that are INJECTED on every dashboard. The other
# eleven stay vendored and statically served — a Lovelace resource can still
# load one — but they no longer ride along on every page load.
#
# Measured on a device on 2026-09-22, over the resident URL: injecting all
# thirteen pulls 6.1 MB before the browser even starts our own cards. The
# GA cards (13–23 KB each) began downloading at 10.2 s and the heating card
# appeared at 11.3 s in one run and 28 s in another; ahead of them sat
# plotly-graph-card (3.1 MB, 10.2 s), apexcharts-card (1.6 MB) and mushroom
# (700 KB). None of those three is referenced anywhere in this repository or
# in greenautarky_site — they appear only in ga-home-strategy's own comment
# explaining that HA core replaced them:
#
#     mushroom chips          -> `heading` card badges
#     apexcharts daily range  -> core `statistics-graph`
#     layout-card / card-mod  -> `sections` view
#
# The intent was already written down ("Deliberately no community cards beyond
# the vendored simple-thermostat fallback"); only the filter was never set.
#
# An allow-list, like EARLY_INJECT_ASSET_IDS above: a newly vendored card is
# NOT injected until something places it. test_injected_community_cards_are_
# the_ones_we_place.py reads the live sources and fails when the two drift —
# in either direction, because a card we place and do not inject is a broken
# dashboard, and one we inject and do not place is this defect again.
COMMUNITY_INJECT_ASSET_IDS = (
    # `type: "custom:simple-thermostat"` — ga-home-strategy's `simple` style,
    # a per-device configuration and therefore live code, not legacy.
    "simple-thermostat",
    # `card_mod:` inside that same card's config. Not a card type: a style key
    # the card-mod module has to be present to interpret.
    "card-mod",
)

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
