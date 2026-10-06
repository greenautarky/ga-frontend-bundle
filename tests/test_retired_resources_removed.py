"""A first-party card the bundle no longer ships must not stay a Lovelace resource.

Measured 2026-10-06 on a device running bundle 1.22.0: ga_manager's
``ga.frontend_cards`` check reported ``stale_registrations:
["ga-maintenance-card"]``. The card had been dropped from ``first_party/``, but
its resource entry survived every update: registration only ever ADDS, and the
per-asset clean-up only replaces an old ``?v=`` of an asset that still ships.
The Lovelace panel then imports a URL that Core answers with its HTML index.

Light CI has no Home Assistant, so this drives the REAL ``async_setup`` and the
REAL ``_register_resource_assets`` with only Home Assistant's framework imports
stubbed (the integration code is never replaced). The Lovelace resource store is
a fake with the four methods the integration calls.

The ownership rule is the half that must not regress the other way: only URLs
under the first-party static path are ours. A resident's ``/local/...``
resource, a HACS card and a community-card URL are never touched.
"""

from __future__ import annotations

import asyncio
import enum
import importlib
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "custom_components" / "ga_frontend_bundle"

FP = "/ga_frontend_bundle_first_party"  # pinned, not read from const.py
RETIRED = f"{FP}/ga-maintenance-card/ga-maintenance-card.js?v=1.21.0"
RESIDENT = "/local/my-own-card.js"
HACS = "/hacsfiles/button-card/button-card.js"
COMMUNITY = "/ga_frontend_bundle_static/simple-thermostat/simple-thermostat.js"
# Looks like ours by name, is not ours by path: must survive.
LOOKALIKE = "/local/ga_frontend_bundle_first_party/ga-maintenance-card.js"


class FakeResources:
    """The four calls the integration makes on lovelace's ResourceStorageCollection."""

    def __init__(self, urls: list[str]) -> None:
        self.loaded = True
        self._items = [{"id": f"r{i}", "res_type": "module", "url": u} for i, u in enumerate(urls)]
        self.deleted: list[str] = []

    async def async_load(self) -> None:  # pragma: no cover - loaded=True
        self.loaded = True

    def async_items(self) -> list[dict]:
        return [dict(i) for i in self._items]

    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(next(i["url"] for i in self._items if i["id"] == item_id))
        self._items = [i for i in self._items if i["id"] != item_id]

    async def async_create_item(self, data: dict) -> dict:
        item = {"id": f"r{len(self._items) + 100}", **data}
        self._items.append(item)
        return item

    def urls(self) -> list[str]:
        return [i["url"] for i in self._items]


@pytest.fixture
def integration(monkeypatch):
    """Import the real package against stubbed Home Assistant framework modules.

    Every module this test adds to ``sys.modules`` is removed again, so the
    stubs can never make ``tests/test_integration_ha.py`` believe a real Home
    Assistant is installed.
    """
    before = set(sys.modules)

    class CoreState(enum.Enum):
        not_running = "NOT_RUNNING"
        running = "RUNNING"

    def mod(name: str, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    for name in ("homeassistant", "homeassistant.components", "homeassistant.helpers",
                 "homeassistant.components.lovelace"):
        mod(name)
    mod("homeassistant.components.frontend",
        add_extra_js_url=lambda hass, url: hass.data.setdefault("_extra", []).append(url))
    mod("homeassistant.components.http", StaticPathConfig=lambda *a: a)
    mod("homeassistant.const", EVENT_HOMEASSISTANT_STARTED="homeassistant_started")
    mod("homeassistant.core", CoreState=CoreState, Event=object, HomeAssistant=object)
    mod("homeassistant.helpers.config_validation", empty_config_schema=lambda d: None)
    mod("homeassistant.helpers.typing", ConfigType=dict)
    mod("homeassistant.components.lovelace.const", LOVELACE_DATA="lovelace")

    monkeypatch.syspath_prepend(str(REPO))
    pkg = importlib.import_module("custom_components.ga_frontend_bundle")
    yield pkg, CoreState
    for name in set(sys.modules) - before:
        sys.modules.pop(name, None)


def _setup(pkg, CoreState, resources: FakeResources) -> dict:
    """Run the real async_setup on a running fake hass; return hass.data."""

    class Http:
        async def async_register_static_paths(self, _paths):
            return None

    class Hass:
        def __init__(self) -> None:
            self.data = {"lovelace": types.SimpleNamespace(resources=resources)}
            self.state = CoreState.running
            self.http = Http()
            self.tasks: list = []
            self.bus = types.SimpleNamespace(async_listen_once=lambda *a: None)

        async def async_add_executor_job(self, fn, *args):
            return fn(*args)

        def async_create_task(self, coro):
            self.tasks.append(coro)

    hass = Hass()

    async def run() -> None:
        assert await pkg.async_setup(hass, {})
        assert hass.tasks, "async_setup scheduled no resource registration"
        for t in hass.tasks:
            await t

    asyncio.run(run())
    return hass.data


def _shipped_resource_paths(pkg) -> set[str]:
    from custom_components.ga_frontend_bundle.bundle import delivery_plan, load_cards
    from custom_components.ga_frontend_bundle.const import EARLY_INJECT_ASSET_IDS

    _inject, res = delivery_plan(load_cards(PKG / "first_party"), EARLY_INJECT_ASSET_IDS)
    assert len(res) >= 4, "fewer first-party resource assets than expected — wrong dir?"
    return {f"{FP}/{c['id']}/{c['file']}" for c in res}


def test_retired_ga_resource_is_removed_on_update(integration):
    pkg, CoreState = integration
    store = FakeResources([RETIRED, RESIDENT, HACS, COMMUNITY, LOOKALIKE])
    _setup(pkg, CoreState, store)
    assert RETIRED in store.deleted, (
        f"retired first-party resource still registered: {store.urls()}"
    )
    assert RETIRED not in store.urls()


def test_resources_that_are_not_ours_survive(integration):
    pkg, CoreState = integration
    store = FakeResources([RETIRED, RESIDENT, HACS, COMMUNITY, LOOKALIKE])
    _setup(pkg, CoreState, store)
    for url in (RESIDENT, HACS, COMMUNITY, LOOKALIKE):
        assert url in store.urls(), f"{url} is not ours and was removed"
        assert url not in store.deleted


def test_every_shipped_resource_asset_is_still_registered(integration):
    """The sweep must never take a card that ships with it."""
    pkg, CoreState = integration
    store = FakeResources([RETIRED])
    _setup(pkg, CoreState, store)
    registered = {u.split("?", 1)[0] for u in store.urls() if u.startswith(FP + "/")}
    assert registered == _shipped_resource_paths(pkg)


def test_no_shipped_assets_means_no_sweep(integration):
    """A broken package (first_party/ missing) must not read as 'everything retired'."""
    from custom_components.ga_frontend_bundle.bundle import retired_resources

    items = [{"id": "r0", "url": RETIRED}, {"id": "r1", "url": f"{FP}/ga-master-card/x.js"}]
    assert retired_resources(items, set(), FP) == []
    assert retired_resources(items, {"ga-master-card"}, FP) == [items[0]]
