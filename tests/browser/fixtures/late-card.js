/**
 * MUST-NOT-FLAG fixture for the registry guard.
 *
 * The same card, delivered the correct way: loaded AFTER the registry swap, as
 * a Lovelace resource is. A guard that flags this one is a guard people learn
 * to ignore, so it is asserted as hard as the must-flag case.
 */
class GaFixtureLateCard extends HTMLElement {}
customElements.define("ga-fixture-late-card", GaFixtureLateCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "ga-fixture-late-card", name: "fixture" });
