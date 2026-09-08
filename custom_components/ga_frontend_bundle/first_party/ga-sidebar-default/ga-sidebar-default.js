/**
 * ga-sidebar-default — collapse the Home Assistant sidebar by default.
 *
 * Thomas 2026-09-08: a resident should land on their dashboard with the sidebar
 * out of the way. HA has no server-set default for this — `dockedSidebar` is
 * per-user client state — so this is a first-load nudge, injected globally via
 * add_extra_js_url (same mechanism as the first-party cards).
 *
 * It acts ONLY while the user has expressed no preference: HA persists
 * `dockedSidebar` to localStorage the moment the user toggles the sidebar, so a
 * user who opens it is never fought again. Everything is wrapped in try/catch —
 * a cosmetic default must never break the frontend.
 */
(function () {
  "use strict";
  const KEY = "dockedSidebar";
  function apply() {
    try {
      if (localStorage.getItem(KEY) !== null) return true; // user already chose
      const root = document.querySelector("home-assistant");
      if (!root) return false; // app not mounted yet
      root.dispatchEvent(
        new CustomEvent("hass-dock-sidebar", {
          detail: { dock: "always_hidden" },
          bubbles: true,
          composed: true,
        })
      );
      return true;
    } catch (e) {
      return true; // never loop on a cosmetic default
    }
  }
  if (apply()) return;
  let tries = 0;
  const timer = setInterval(() => {
    if (apply() || ++tries > 40) clearInterval(timer); // ~10 s ceiling
  }, 250);
})();
