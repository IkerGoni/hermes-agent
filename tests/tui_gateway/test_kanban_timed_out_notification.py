"""The timed_out notification must not invent a runtime limit.

Regression test for a real incident: `_kb_timed_out` formatted
`int(payload.get('limit_seconds') or 0)`, so a payload without the key printed
"max_runtime=0s". That reads as "this card has a zero-second cap", which sent
someone to fix a card that had no runtime limit at all. A card that genuinely
had no limit printed exactly the same thing as a card that was killed
instantly.
"""

from tui_gateway.session_notifications import _kb_timed_out


def test_missing_limit_does_not_render_as_zero() -> None:
    text = _kb_timed_out(None, {}, "some card")
    assert "max_runtime=0s" not in text, text
    assert "no runtime limit reported" in text, text


def test_missing_limit_with_unrelated_payload_does_not_render_as_zero() -> None:
    text = _kb_timed_out(None, {"sigkill": False, "retry_status": "ready"}, "card")
    assert "max_runtime=0s" not in text, text


def test_reported_limit_is_rendered_verbatim() -> None:
    text = _kb_timed_out(None, {"limit_seconds": 1800}, "card")
    assert "max_runtime=1800s" in text, text


def test_zero_limit_is_distinguishable_from_missing_limit() -> None:
    """A real 0 must still print 0 — that is a genuine, separate condition."""
    text = _kb_timed_out(None, {"limit_seconds": 0}, "card")
    assert "max_runtime=0s" in text, text
    assert "no runtime limit reported" not in text, text
