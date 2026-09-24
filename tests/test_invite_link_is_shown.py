"""An invite produces a link the master can share — not six digits only.

greenautarky_site >= 2.9.4 (#61, 2026-09-22) answers `POST .../sub_user/invite`
with ``invite_url`` (``<external_url>/greenautarky-join?pin=…``) next to the PIN.
The master card never read it: on a canary on 2026-09-24 "Einladungs-PIN
erzeugen" showed a PIN and nothing to send (Thomas, as a resident). The field
arrived and nothing rendered it — declared at the seam, never read.

Runs the SHIPPED card's render function through tests/js/eval.mjs.
"""

from __future__ import annotations

import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-master-card" / "ga-master-card.js"
LINK = "https://resident.example.invalid/greenautarky-join?pin=482913"


def _render(answer: dict) -> str:
    return run_js(CARD, "renderInvite(" + json.dumps(answer) + ")")


def test_the_link_the_server_sent_is_on_the_screen():
    html = _render({"pin": "482913", "expires_at": "2026-09-25T12:00:00+00:00",
                    "invite_url": LINK})
    assert LINK in html, html
    assert "share" in html.lower(), "no way to send the link on"


def test_the_pin_stays_for_reading_out_over_the_phone():
    html = _render({"pin": "482913", "expires_at": "2026-09-25T12:00:00+00:00",
                    "invite_url": LINK})
    assert "482913" in html


def test_without_a_link_the_card_says_why_instead_of_guessing_one():
    html = _render({"pin": "482913", "expires_at": "2026-09-25T12:00:00+00:00"})
    assert "greenautarky-join" not in html, "the card invented a link the server did not send"
    assert "482913" in html


def test_a_link_cannot_inject_markup():
    html = _render({"pin": "1", "expires_at": "2026-09-25T12:00:00+00:00",
                    "invite_url": 'https://x/?pin=1"><img src=x onerror=alert(1)>'})
    assert "<img" not in html
