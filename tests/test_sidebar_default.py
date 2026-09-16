"""The sidebar default must survive the app not being ready yet.

THE DEFECT THIS FILE EXISTS FOR, measured on a bench device on 2026-09-16: a
resident landed on their dashboard with the sidebar open, every time. The asset
was imported by the index and fetched with 200; `dockedSidebar` was simply
never written.

The cause was one line of optimism:

    const root = document.querySelector("home-assistant");
    if (!root) return false;
    root.dispatchEvent(...);
    return true;              // "I dispatched" treated as "it worked"

`home-assistant` is in index.html from the first byte — it EXISTS long before
the app hydrates it and attaches the listener. The event went into a void, the
function reported success, and the retry loop therefore never started. Firing
the same event by hand a few seconds later collapsed the sidebar immediately,
which is what proved where the fault was.

These run the SHIPPED bytes in a fake DOM whose listener attaches LATE, which
is the condition the defect needs. Against a DOM that is ready from the first
millisecond the old code passes too.
"""
import json
import subprocess

from conftest import PKG
from test_rendered_output import _node

ASSET = PKG / "first_party" / "ga-sidebar-default" / "ga-sidebar-default.js"

#: A DOM just real enough: `home-assistant` is present immediately, its
#: listener appears after `attach_after_ms`, and HA's own behaviour of writing
#: `dockedSidebar` when it HANDLES the event is modelled.
HARNESS = r"""
const store = new Map(%(seed)s);
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
let handled = 0;
const root = {
  _listener: null,
  addEventListener(type, fn) { if (type === "hass-dock-sidebar") this._listener = fn; },
  dispatchEvent(ev) {
    if (this._listener) { handled++; this._listener(ev); }
    return true;
  },
};
globalThis.CustomEvent = class {
  constructor(type, init) { this.type = type; Object.assign(this, init); }
};
globalThis.document = { querySelector: (sel) => (sel === "home-assistant" ? root : null) };

// The app hydrates late: only THEN does the listener exist, and only then does
// HA persist the preference it was asked for.
setTimeout(() => {
  root.addEventListener("hass-dock-sidebar", (ev) => {
    globalThis.localStorage.setItem("dockedSidebar", JSON.stringify(ev.detail.dock));
  });
}, %(attach_after_ms)d);

%(asset)s

setTimeout(() => {
  const docked = globalThis.localStorage.getItem("dockedSidebar");
  console.log(JSON.stringify({ docked, handled }));
  process.exit(0);
}, %(observe_ms)d);
"""


def _run(attach_after_ms=1500, observe_ms=4000, seed="[]"):
    script = HARNESS % {
        "asset": ASSET.read_text(encoding="utf-8"),
        "attach_after_ms": attach_after_ms,
        "observe_ms": observe_ms,
        "seed": seed,
    }
    proc = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[:400]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_sidebar_collapses_even_though_the_app_hydrates_late():
    """THE RED ONE. The element is there from the first byte; its listener is
    not. The old code fired once into the void and called that success."""
    out = _run(attach_after_ms=1500)
    assert out["docked"] == '"always_hidden"', out
    assert out["handled"] >= 1


def test_it_still_works_when_the_app_is_ready_immediately():
    """Must-not-flag: the fast path must not have been traded away."""
    out = _run(attach_after_ms=0, observe_ms=1500)
    assert out["docked"] == '"always_hidden"', out


def test_a_user_who_chose_is_never_overridden():
    """The rule. HA writes this key the moment a user toggles the sidebar, so
    its presence means a person decided — and a cosmetic default must lose."""
    out = _run(attach_after_ms=0, observe_ms=1500, seed='[["dockedSidebar", "\\"docked\\""]]')
    assert out["docked"] == '"docked"', out
    assert out["handled"] == 0, "no event may be fired at all once a preference exists"


def test_it_stops_instead_of_nudging_for_ever():
    """A dashboard nobody hydrates must not be poked every 250 ms until the tab
    is closed. The ceiling is ~15 s; nothing is written and nothing loops."""
    out = _run(attach_after_ms=10**6, observe_ms=16500)
    assert out["docked"] is None
    assert out["handled"] == 0
