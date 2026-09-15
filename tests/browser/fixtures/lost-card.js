/**
 * MUST-FLAG fixture for the registry guard.
 *
 * A card module that registers its element BEFORE Home Assistant swaps
 * `window.customElements` for the scoped-custom-element-registry polyfill —
 * i.e. exactly what an `add_extra_js_url`-injected card does. The guard has to
 * say so out loud; nothing else in the stack ever does.
 */
class GaFixtureLostCard extends HTMLElement {}
customElements.define("ga-fixture-lost-card", GaFixtureLostCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "ga-fixture-lost-card", name: "fixture" });
