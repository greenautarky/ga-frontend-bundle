"""GA frontend card bundle — the de-HACS Lovelace card set.

A stateless integration that replaces HACS for delivering GreenAutarky's curated
Lovelace cards. On setup it:

1. serves the vendored card ``.js`` files as a static directory, and
2. injects each as a frontend JS module via ``add_extra_js_url`` so the
   ``custom:*`` elements (``custom:button-card``, ``custom:mushroom-*`` …)
   resolve on every dashboard.

No GitHub access, no HACS, no per-device Lovelace-resource registration. The
cards are pinned in ``bundle.lock.yaml`` and vendored at build time
(``scripts/vendor.py``).

No ``config_flow`` and no HA ``Store`` — the integration holds no persistent
state. It is activated by ``ga_frontend_bundle:`` in ``configuration.yaml``,
which converge maintains via its enable-list. See
``ga-ihost-docs/VENDORED-INTEGRATION-DELIVERY.md`` and ``docs/CONVERGE-HANDOFF.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .bundle import card_url, load_cards
from .const import (
    COMMUNITY_DIRNAME,
    DOMAIN,
    FIRST_PARTY_DIRNAME,
    FIRST_PARTY_URL_BASE,
    STATIC_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

# HA Core 2025.11.x silently skips async_setup for yaml-only integrations
# that don't declare a CONFIG_SCHEMA (= introduced quietly in 2024.x).
# The sibling integration greenautarky_onboarding doesn't trip this
# because its manifest sets "config_flow": true (different code path).
# `cv.empty_config_schema(DOMAIN)` is the HA-canonical "I accept the bare
# `<domain>:` form, no other keys" pattern — matches every yaml-only
# integration in HA Core itself (cf. core's system_log, etc.).
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def _serve_inject(
    hass: HomeAssistant, directory: Path, url_base: str
) -> tuple[list[dict[str, str]], int]:
    """Load cards from ``directory``, serve them statically at ``url_base``, and
    inject each as a frontend JS module. Returns ``(cards, injected)``.

    Blocking dir scan runs in the executor. Missing dir → ``([], 0)``.
    """
    # iterdir()/glob()/is_file() are blocking — run the scan in the executor.
    cards = await hass.async_add_executor_job(load_cards, directory)
    if not cards:
        return [], 0

    await hass.http.async_register_static_paths(
        [StaticPathConfig(url_base, str(directory), True)]
    )

    injected = 0
    for card in cards:
        try:
            add_extra_js_url(hass, card_url(url_base, card))
        except KeyError:
            # add_extra_js_url indexes hass.data["frontend_extra_module_url"],
            # which only exists once `frontend` has set up. We declare frontend
            # as a dependency so this should not happen on a real device; stay
            # defensive for minimal/test setups.
            _LOGGER.warning(
                "%s: frontend not ready — card %s not injected", DOMAIN, card["id"]
            )
            continue
        injected += 1
    return cards, injected


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GA frontend bundle (yaml-activated, idempotent)."""
    if DOMAIN in hass.data:
        return True
    hass.data[DOMAIN] = {}

    pkg = Path(__file__).parent

    # Vendored community cards (the de-HACS set, pinned in bundle.lock.yaml).
    community_dir = pkg / COMMUNITY_DIRNAME
    cards, injected = await _serve_inject(hass, community_dir, STATIC_URL_BASE)
    if not cards:
        _LOGGER.error(
            "%s: no vendored cards under %s — bundle is empty. Did "
            "scripts/vendor.py run before packaging? Not blocking HA start.",
            DOMAIN,
            community_dir,
        )

    # First-party GA cards (authored here, e.g. ga-master-card / ADR-0006).
    # Separate dir + URL base so the vendor lock/integrity checks never touch
    # them; same load/serve/inject mechanism.
    first_party_dir = pkg / FIRST_PARTY_DIRNAME
    fp_cards, fp_injected = await _serve_inject(
        hass, first_party_dir, FIRST_PARTY_URL_BASE
    )

    hass.data[DOMAIN] = {
        "cards": cards,
        "injected": injected,
        "first_party_cards": fp_cards,
        "first_party_injected": fp_injected,
    }
    _LOGGER.info(
        "%s: community %d cards (injected %d) at %s; first-party %d (injected %d) at %s",
        DOMAIN,
        len(cards),
        injected,
        STATIC_URL_BASE,
        len(fp_cards),
        fp_injected,
        FIRST_PARTY_URL_BASE,
    )
    return True
