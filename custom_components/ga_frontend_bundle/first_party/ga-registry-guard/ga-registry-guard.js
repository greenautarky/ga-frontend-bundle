/**
 * ga-registry-guard — say it out loud when a GreenAutarky element cannot register.
 *
 * WHY THIS EXISTS
 * ---------------
 * On a freshly flashed canary (2026-09-15) none of the first-party cards
 * registered. Every file was fetched and served 200, every file contained its
 * `customElements.define(...)`, the dashboard showed Home Assistant's red
 * "Custom element doesn't exist" box — and NOTHING said so anywhere: no console
 * error, no server-side log line. Three operator complaints, one cause, and no
 * signal pointing at it. This module is that signal.
 *
 * THE FAILURE IT DETECTS
 * ----------------------
 * `home-assistant-frontend`'s app bundle imports
 * `@webcomponents/scoped-custom-element-registry` on its first line, and that
 * polyfill REPLACES `window.customElements` with a brand-new, empty registry
 * whose `get()` reads only its own map. Anything defined before that line sits
 * in the native registry and is invisible to Home Assistant forever. The define
 * succeeded, so nothing throws.
 *
 * HOW IT DETECTS IT, without a list of card names to keep in sync:
 *   1. it patches `CustomElementRegistry.prototype.define` and records every
 *      `ga-*` / `ll-strategy-*` tag that goes through the NATIVE registry;
 *   2. it also reads `window.customCards`, which cards push themselves onto —
 *      so a card that beat the patch is still covered;
 *   3. after the app has had time to boot it asks the LIVE
 *      `window.customElements` for each of them, and reports the ones that are
 *      gone.
 *
 * It defines no element of its own, so it cannot be a victim of the failure it
 * watches. If Home Assistant ever stops swapping the registry, every tag stays
 * visible and the guard says nothing — it flags a real defect or nothing at all.
 */
(function () {
  "use strict";

  var INTERESTING = /^(ga-|ll-strategy-)/;
  var DELAY_MS = 8000; // the app bundle is up long before this on any device
  var seen = [];

  function remember(name) {
    if (INTERESTING.test(name) && seen.indexOf(name) === -1) seen.push(name);
  }

  try {
    var proto = window.CustomElementRegistry && window.CustomElementRegistry.prototype;
    if (proto && typeof proto.define === "function") {
      var nativeDefine = proto.define;
      proto.define = function (name, ctor, options) {
        try {
          remember(String(name));
        } catch (e) {
          /* never let bookkeeping break a define */
        }
        return nativeDefine.call(this, name, ctor, options);
      };
    }
  } catch (e) {
    /* a guard must never break the frontend */
  }

  /** Tags that were defined but are not in the registry HA actually reads. */
  function audit() {
    var lost = [];
    var candidates = seen.slice();
    try {
      var advertised = window.customCards || [];
      for (var i = 0; i < advertised.length; i++) {
        var t = advertised[i] && advertised[i].type;
        if (t && INTERESTING.test(t) && candidates.indexOf(t) === -1) candidates.push(t);
      }
    } catch (e) {
      /* ignore */
    }
    for (var j = 0; j < candidates.length; j++) {
      try {
        if (!window.customElements.get(candidates[j])) lost.push(candidates[j]);
      } catch (e) {
        lost.push(candidates[j]);
      }
    }
    return lost;
  }

  window.__gaRegistryAudit = audit;

  function report() {
    var lost;
    try {
      lost = audit();
    } catch (e) {
      lost = [];
    }
    if (lost.length) {
      console.error(
        "ga-frontend-bundle: " +
          lost.length +
          " GreenAutarky element(s) are defined but NOT in the live custom-element " +
          "registry: " +
          lost.join(", ") +
          ". They registered before Home Assistant replaced window.customElements " +
          "(scoped-custom-element-registry), so HA will render \"Custom element " +
          "doesn't exist\" for them. Such an asset must be delivered as a Lovelace " +
          "RESOURCE, not injected with add_extra_js_url."
      );
    }
    window.__gaRegistryGuardLost = lost;
    window.__gaRegistryGuardReported = true;
  }

  try {
    setTimeout(report, DELAY_MS);
  } catch (e) {
    /* ignore */
  }
})();
