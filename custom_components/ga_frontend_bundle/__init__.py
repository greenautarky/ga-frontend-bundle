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
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .bundle import card_url, load_cards
from .const import (
    COMMUNITY_DIRNAME,
    DOMAIN,
    FIRST_PARTY_DIRNAME,
    FIRST_PARTY_URL_BASE,
    STATIC_URL_BASE,
    STRATEGY_ASSET_IDS,
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


async def _register_strategy_resources(
    hass: HomeAssistant, cards: list[dict[str, str]]
) -> int:
    """Register strategy assets as Lovelace RESOURCES (not just injected modules).

    Injection via ``add_extra_js_url`` races the app bootstrap. The Lovelace panel,
    by contrast, loads its **resources** and only then resolves the dashboard's
    ``strategy:`` block — so a strategy shipped as a resource is guaranteed to be
    defined before HA looks for it. HA waits just 5 s for the element and then
    renders "Timeout waiting for strategy element …"; on a canary over the mesh that
    race is lost regularly (K0, 2026-07-13). Cards do not care — they are resolved
    lazily, when a card is rendered.

    Same URL as the injected module, so the browser's ES-module registry executes the
    file exactly once regardless of which path pulled it in. Idempotent.
    """
    strategies = [c for c in cards if c["id"] in STRATEGY_ASSET_IDS]
    if not strategies:
        return 0

    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except ImportError:  # pragma: no cover - lovelace is always there on GA OS
        return 0

    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if resources is None:
        _LOGGER.warning(
            "%s: lovelace resources unavailable — strategies may lose the 5 s "
            "registration race and render a timeout card",
            DOMAIN,
        )
        return 0

    if not resources.loaded:
        await resources.async_load()

    known = {item.get("url") for item in resources.async_items()}
    added = 0
    for card in strategies:
        url = card_url(FIRST_PARTY_URL_BASE, card)
        if url in known:
            continue
        try:
            await resources.async_create_item({"res_type": "module", "url": url})
        except Exception as err:  # a broken resource store must not break HA start
            _LOGGER.warning(
                "%s: could not register strategy resource %s: %r", DOMAIN, url, err
            )
            continue
        added += 1
        _LOGGER.info("%s: registered strategy resource %s", DOMAIN, url)
    return added


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

    # Strategies additionally need to be Lovelace resources — see the docstring.
    # Deferred to EVENT_HOMEASSISTANT_STARTED: lovelace sets up after us.
    async def _strategies_started(_event: Event | None = None) -> None:
        await _register_strategy_resources(hass, fp_cards)

    if hass.state is CoreState.running:
        hass.async_create_task(_strategies_started())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _strategies_started)

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
