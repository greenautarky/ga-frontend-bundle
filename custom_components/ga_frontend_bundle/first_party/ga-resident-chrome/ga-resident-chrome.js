/**
 * ga-resident-chrome — no search and no Assist in a resident's top bar.
 *
 * Thomas 2026-11-16 (Odoo #2146, BOSv1.6.1-rc1 hand test): a resident has no use
 * for the entity search (magnifier, shortcut E / Ctrl+K) or for Assist
 * (shortcut A); both open Home Assistant internals the resident view is not
 * meant to expose. The admin / service view stays exactly as it is.
 *
 * WHO IS A RESIDENT: anyone whose Home Assistant user is NOT an administrator
 * (`hass.user.is_admin === false`). That is what the service view differs in,
 * and it is read from the live `hass` object, not from a name or a URL.
 *
 * TWO HALVES, because either alone leaves the feature reachable:
 *   1. the BUTTONS in the dashboard's top bar (and their entries in the
 *      overflow menu on a phone) are hidden;
 *   2. the SHORTCUTS are neutralised. Home Assistant's own handlers bail out
 *      when `event.defaultPrevented`, so a capturing listener that calls
 *      `preventDefault()` first stops them — but only where the key press is not
 *      typing into a field, otherwise a resident could not type the letter "a".
 *
 * HOW THE BUTTONS ARE FOUND. By the icon they are drawn with (the two mdi paths
 * Home Assistant's top bar uses) and, as a fallback for a frontend that changes
 * the icon, by their label. Both live inside shadow roots, which a
 * MutationObserver on the document cannot see, so the dashboard element
 * (`hui-root`) is found by walking shadow roots and observed on its own.
 *
 * An asset that defines no custom element, injected early like
 * ga-sidebar-default (see const.py EARLY_INJECT_ASSET_IDS). A cosmetic and
 * hygiene layer: every step is guarded so it can never break the frontend.
 * This is presentation, not a permission boundary — the server still decides.
 */
(function () {
  "use strict";

  // The icons hui-root draws its two buttons with: mdiMagnify and
  // mdiCommentProcessingOutline (@mdi/js).
  var ICON_PATHS = [
    "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
    "M9,22A1,1 0 0,1 8,21V18H4A2,2 0 0,1 2,16V4C2,2.89 2.9,2 4,2H20A2,2 0 0,1 22,4V16A2,2 0 0,1 20,18H13.9L10.2,21.71C10,21.9 9.75,22 9.5,22V22H9M10,16V19.08L13.08,16H20V4H4V16H10M17,11H15V9H17V11M13,11H11V9H13V11M9,11H7V9H9V11Z",
  ];
  var LABEL = /assist|such|search/i;
  // Fast while the app is booting (the buttons would otherwise be on screen for
  // up to a second), slow afterwards. Once a dashboard is found its own observer
  // takes over, so the poll only has to find a NEW dashboard element.
  var FAST_MS = 200;
  var SLOW_MS = 1000;
  var FAST_FOR_MS = 60000;
  var HIDDEN_ATTR = "data-ga-resident-hidden";

  /** Command letters and numbers only, so a different separator style still matches. */
  function tokens(p) {
    return (String(p).match(/[a-zA-Z]|-?\d*\.?\d+/g) || []).join(" ");
  }

  var KNOWN = ICON_PATHS.map(tokens);

  function matchesPath(p) {
    if (typeof p !== "string" || p.length < 20) return false;
    return KNOWN.indexOf(tokens(p)) >= 0;
  }

  function isResident() {
    try {
      var root = document.querySelector("home-assistant");
      var hass = root && root.hass;
      // Unknown is not "resident": until the user object exists nothing is hidden
      // and no key is blocked, so an admin is never locked out by a slow start.
      return !!(hass && hass.user && hass.user.is_admin === false);
    } catch (e) {
      return false;
    }
  }

  // ── 2. shortcuts ────────────────────────────────────────────────────────

  function typingInto(ev) {
    var path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
    var el = path[0] || ev.target;
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    return (
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      el.isContentEditable === true ||
      tag.indexOf("textfield") >= 0 ||
      tag.indexOf("textarea") >= 0
    );
  }

  function onKeydown(ev) {
    try {
      if (!isResident()) return;
      var key = (ev.key || "").toLowerCase();
      var code = ev.code || "";

      // Ctrl/Cmd+K — the global search chord. Never typing, so always taken.
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (key === "k" || code === "KeyK")) {
        ev.preventDefault();
        ev.stopImmediatePropagation();
        return;
      }
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return;

      // A = Assist, E / C / D = the entity, command and device quick bars.
      var hit =
        key === "a" || key === "e" || key === "c" || key === "d" ||
        code === "KeyA" || code === "KeyE" || code === "KeyC" || code === "KeyD";
      if (hit && !typingInto(ev)) {
        // Home Assistant's handlers return on `defaultPrevented`. Not stopping
        // propagation: nothing else on the page needs these letters either, but
        // a listener that is not ours is none of our business.
        ev.preventDefault();
      }
    } catch (e) {
      /* never break the frontend over a shortcut */
    }
  }

  try {
    window.addEventListener("keydown", onKeydown, true);
  } catch (e) {
    /* ignore */
  }

  // ── 1. buttons ──────────────────────────────────────────────────────────

  var observed = new WeakSet();

  /** Every element under `root`, descending through open shadow roots. */
  function deepAll(root, out) {
    var nodes = root.querySelectorAll("*");
    for (var i = 0; i < nodes.length; i++) {
      out.push(nodes[i]);
      if (nodes[i].shadowRoot) deepAll(nodes[i].shadowRoot, out);
    }
    return out;
  }

  function hideTarget(el) {
    var target =
      (el.closest && el.closest("ha-md-menu-item, ha-list-item, mwc-list-item, ha-icon-button")) || el;
    if (target.getAttribute(HIDDEN_ATTR) === "1") return false;
    target.setAttribute(HIDDEN_ATTR, "1");
    target.hidden = true;
    target.style.setProperty("display", "none", "important");
    return true;
  }

  function sweep(scope) {
    var nodes = deepAll(scope, []);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var tag = el.localName || "";
      var byIcon = matchesPath(el.path);
      var byLabel = false;
      if (!byIcon && (tag === "ha-icon-button" || tag === "ha-md-menu-item")) {
        var label = el.label || (el.getAttribute && el.getAttribute("aria-label")) || "";
        byLabel = LABEL.test(String(label));
      }
      if (byIcon || byLabel) hideTarget(el);
    }
  }

  function watch(rootEl) {
    var sr = rootEl.shadowRoot;
    if (!sr) return;
    sweep(sr);
    if (observed.has(rootEl)) return;
    observed.add(rootEl);
    new MutationObserver(function () {
      try {
        if (isResident()) sweep(sr);
      } catch (e) {
        /* ignore */
      }
    }).observe(sr, { childList: true, subtree: true });
  }

  function tick() {
    try {
      if (!isResident()) return;
      var app = document.querySelector("home-assistant");
      if (!app || !app.shadowRoot) return;
      var all = deepAll(app.shadowRoot, []);
      for (var i = 0; i < all.length; i++) {
        if (all[i].localName === "hui-root") watch(all[i]);
      }
    } catch (e) {
      /* never break the frontend over a cosmetic rule */
    }
  }

  var started = Date.now();
  function schedule() {
    setTimeout(function () {
      tick();
      schedule();
    }, Date.now() - started < FAST_FOR_MS ? FAST_MS : SLOW_MS);
  }
  schedule();
  tick();
})();
