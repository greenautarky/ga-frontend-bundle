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
 *
 * WHY THE RETRY WATCHES THE EFFECT AND NOT THE DISPATCH (measured 2026-09-16).
 *
 * The first version asked `document.querySelector("home-assistant")`, fired the
 * event at whatever it found, and returned true. That element is in index.html
 * from the first byte — it EXISTS long before the app has hydrated it and
 * attached the listener. So on a real device the event went into a void, the
 * function reported success, the retry loop never started, and every resident
 * landed with the sidebar open. The asset was fetched (200) and the index did
 * import it; nothing was missing except the effect.
 *
 * Finding the element is not the same as its listener being there, and
 * "I dispatched" is not "it happened". The only honest evidence is HA writing
 * `dockedSidebar`, which it does when it handles the event — so that is what
 * is waited for.
 */
(function () {
  "use strict";
  const KEY = "dockedSidebar";
  const EVERY_MS = 250;
  const CEILING_MS = 15000;

  function chosen() {
    try {
      return localStorage.getItem(KEY) !== null;
    } catch (e) {
      // Storage can throw outright (private mode, blocked site data). Treat it
      // as "a preference may exist and we cannot see it" and do nothing: a
      // cosmetic default is never worth fighting the browser over.
      return true;
    }
  }

  function nudge() {
    try {
      const root = document.querySelector("home-assistant");
      if (!root) return;
      root.dispatchEvent(
        new CustomEvent("hass-dock-sidebar", {
          detail: { dock: "always_hidden" },
          bubbles: true,
          composed: true,
        })
      );
    } catch (e) {
      // never let a cosmetic default break the frontend
    }
  }

  if (chosen()) return;
  nudge();

  let waited = 0;
  const timer = setInterval(() => {
    waited += EVERY_MS;
    // `chosen()` is now the success condition too: HA writes the key when it
    // HANDLES the event, so its presence is the effect, not the attempt.
    if (chosen() || waited >= CEILING_MS) {
      clearInterval(timer);
      return;
    }
    nudge();
  }, EVERY_MS);
})();
