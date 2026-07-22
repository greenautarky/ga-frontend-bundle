"""ga-thermostat-card — first-party resident heating control (Odoo #518)."""
from pathlib import Path

CARD = (Path(__file__).resolve().parent.parent
        / "custom_components/ga_frontend_bundle/first_party"
        / "ga-thermostat-card/ga-thermostat-card.js")


def test_card_exists_and_registers():
    src = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-thermostat-card"' in src
    assert 'window.customCards' in src


def test_card_talks_only_to_climate_services():
    src = CARD.read_text(encoding="utf-8")
    assert 'callService("climate", "set_temperature"' in src
    assert 'callService("climate", "set_hvac_mode"' in src
    # no third-party / addon coupling
    assert "custom:simple-thermostat" not in src  # no third-party card type


def test_card_has_aus_manuel_ki_modes():
    src = CARD.read_text(encoding="utf-8")
    assert '["auto", "KI"' in src
    assert '["heat", "MANUEL"' in src
    assert '["off", "AUS"' in src


def test_card_requires_climate_entity():
    src = CARD.read_text(encoding="utf-8")
    assert 'startsWith("climate.")' in src
