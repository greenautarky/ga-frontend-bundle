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
