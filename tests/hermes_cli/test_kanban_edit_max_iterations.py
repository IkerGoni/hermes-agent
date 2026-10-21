"""Tests: an EXISTING card can be given a new iteration budget.

``max_iterations`` (a card's own iteration budget, dispatched to the worker as
``--max-turns``) could until now only be set at CREATE time
(``hermes kanban create --max-iterations N``). That made a card that ran out of
turns a dead end: the wall reads "Iteration budget exhausted (100/100)" and the
only way to give the card more room was to recreate it, throwing away the work
it had already done — and the new card starts from zero, with none of the
context the dead one had.

So the budget has to be settable on a card that already exists. These tests pin
that path end to end through the public API (``kb.edit_task`` /
``kb.get_task``), plus the CLI surface that drives it, plus the guarantee that
matters most for the callers that were already using ``edit_task`` for other
fields: an edit that does not mention the budget must not clear it.

The value that survives all of this is the one the dispatcher reads at
``kanban_db_dispatch.py`` (``task.max_iterations`` -> ``--max-turns``), so the
last test reads the card back the way the dispatcher does.
"""

from __future__ import annotations

import argparse
import json

import pytest

from hermes_cli import kanban as kc
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB (same fixture the sibling
    iteration-budget suite uses, so both run against the same board shape)."""
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _make_card(conn, *, title="card", assignee="w", max_iterations=None) -> str:
    return kb.create_task(
        conn, title=title, assignee=assignee, max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# The budget can be set on a card that already exists.
# ---------------------------------------------------------------------------


def test_edit_task_sets_max_iterations(kanban_home):
    """A card created WITHOUT a budget can be given one later."""
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="needs more room")

        assert kb.get_task(conn, tid).max_iterations is None

        assert kb.edit_task(conn, tid, max_iterations=220) is True

        assert kb.get_task(conn, tid).max_iterations == 220


def test_edit_task_repins_an_existing_budget(kanban_home):
    """Re-pinning replaces the old number — that is the whole point of the flag.

    A card that died at 100/100 needs 220, not "100 plus 120"; and a card that
    was over-provisioned needs to come down.
    """
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="repin", max_iterations=100)

        assert kb.edit_task(conn, tid, max_iterations=220) is True
        assert kb.get_task(conn, tid).max_iterations == 220

        assert kb.edit_task(conn, tid, max_iterations=50) is True
        assert kb.get_task(conn, tid).max_iterations == 50


def test_edit_task_records_an_edited_event_with_the_changed_field(kanban_home):
    """The change is auditable: the card's history says the budget moved.

    Without an event, a board where a card's budget was raised looks exactly
    like one where it never was — and the "why did this card get 600 turns?"
    question has no answer in the card's own timeline.
    """
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="audited")
        kb.edit_task(conn, tid, max_iterations=220)

        events = kb.list_events(conn, tid)

    edited = [e for e in events if e.kind == "edited"]
    assert edited, [e.kind for e in events]
    assert "max_iterations" in (edited[-1].payload or {}).get("fields", [])


# ---------------------------------------------------------------------------
# A budget below 1 is not a budget.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bogus", [0, -5])
def test_edit_task_rejects_non_positive_max_iterations(kanban_home, bogus):
    """0 / negative are refused and NOTHING is written.

    ``resolve_turn_limit`` reads <= 0 as "unlimited" (``TURN_LIMIT_UNLIMITED``),
    so storing a 0 would hand the worker an unbounded run — the exact opposite
    of what the caller asked for. The card's real budget must survive the
    rejected edit.
    """
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="guarded", max_iterations=220)

        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            kb.edit_task(conn, tid, max_iterations=bogus)

        assert kb.get_task(conn, tid).max_iterations == 220


# ---------------------------------------------------------------------------
# An edit that does not mention the budget must not clear it.
# ---------------------------------------------------------------------------


def test_edit_task_without_max_iterations_preserves_the_existing_budget(kanban_home):
    """``edit_task(title=...)`` must not wipe a budget the card already had.

    This is the regression the other fields' callers would hit: ``edit_task``
    is how a title/priority/result is changed, and "the field I did not pass is
    untouched" is the contract every one of those calls relies on. A budget
    that silently reverted to NULL on the next title edit would send the card
    back to the profile's default — the very budget it was rescued from.
    """
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="before", max_iterations=220)

        assert kb.edit_task(conn, tid, title="after") is True

        task = kb.get_task(conn, tid)
        assert task.title == "after"
        assert task.max_iterations == 220


def test_edit_task_with_no_fields_changes_nothing(kanban_home):
    """A no-op edit leaves the card (and its budget) exactly as it was."""
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="untouched", max_iterations=220)

        assert kb.edit_task(conn, tid) is False

        task = kb.get_task(conn, tid)
        assert task.title == "untouched"
        assert task.max_iterations == 220


# ---------------------------------------------------------------------------
# The CLI surface: `hermes kanban edit <id> --max-iterations N`.
# ---------------------------------------------------------------------------


def _edit_args(task_id: str, **overrides) -> argparse.Namespace:
    """Namespace shaped like ``kanban edit``'s parsed args."""
    args = {
        "task_id": task_id, "title": None, "body": None, "priority": None,
        "result": None, "summary": None, "metadata": None, "max_iterations": None,
    }
    args.update(overrides)
    return argparse.Namespace(**args)


def test_cli_edit_sets_max_iterations(kanban_home):
    """``kanban edit <id> --max-iterations 220`` persists on the card."""
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="cli card")

    assert kc._cmd_edit(_edit_args(tid, max_iterations=220)) == 0

    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220


def test_cli_edit_rejects_a_non_positive_max_iterations(kanban_home, capsys):
    """``--max-iterations 0`` is refused, not silently ignored.

    A silent drop would let an operator believe it raised a budget the worker
    never got; and 0 is exactly the value ``resolve_turn_limit`` reads as
    "unlimited", so a later code path could act on it.
    """
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="cli card", max_iterations=220)

    rc = kc._cmd_edit(_edit_args(tid, max_iterations=0))

    assert rc == 2
    captured = capsys.readouterr()
    assert "--max-iterations must be >= 1" in captured.out + captured.err
    # The rejected edit left the card's real budget alone.
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220


def test_cli_edit_with_only_max_iterations_is_not_an_empty_edit(kanban_home):
    """A budget-only edit is a real edit: it must not trip the "provide at
    least one field" guard that exists to catch a no-op command."""
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="budget only")

    assert kc._cmd_edit(_edit_args(tid, max_iterations=300)) == 0

    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 300


def test_cli_edit_without_any_field_still_reports_the_empty_edit(kanban_home, capsys):
    """The pre-existing "provide --title, --body, ..." guard still fires."""
    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="nothing to change")

    rc = kc._cmd_edit(_edit_args(tid))

    assert rc == 2
    captured = capsys.readouterr()
    assert "kanban edit" in captured.out + captured.err


# ---------------------------------------------------------------------------
# The value the dispatcher reads is the value that was stored.
# ---------------------------------------------------------------------------


def test_the_edited_budget_is_what_the_dispatcher_would_send(kanban_home, monkeypatch, tmp_path):
    """The card the worker gets is the card the board holds.

    ``kanban_db_dispatch`` reads ``task.max_iterations`` and turns it into
    ``--max-turns``. This closes the loop from the other end: a budget set
    through ``edit_task`` is the budget the worker argv carries, which is the
    only way the new flag can actually unblock a card that died at N/N.
    """
    from hermes_cli import kanban_db_dispatch as kbd

    monkeypatch.setattr(kbd, "_resolve_hermes_argv", lambda: ["hermes"])

    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="dispatched", assignee="w")
        kb.edit_task(conn, tid, max_iterations=600)
        task = kb.get_task(conn, tid)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    kbd._default_spawn(task, str(workspace))

    cmd = captured["cmd"]
    assert "--max-turns" in cmd, cmd
    assert cmd[cmd.index("--max-turns") + 1] == "600"


# ---------------------------------------------------------------------------
# The tool surface: kanban_edit.
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_home(tmp_path, monkeypatch):
    """Isolated home for the tool surface (the tool resolves its own board)."""
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for key in ("HERMES_KANBAN_TASK", "HERMES_KANBAN_DB", "HERMES_KANBAN_BOARD",
                "HERMES_KANBAN_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def test_kanban_edit_tool_sets_max_iterations(tool_home):
    """The tool writes the budget the CLI writes, through the same DB API."""
    from tools import kanban_tools as kt

    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="tool card")

    out = json.loads(kt._handle_edit({"task_id": tid, "max_iterations": 220}))

    assert "error" not in out, out
    assert out["max_iterations"] == 220
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220


def test_kanban_edit_tool_rejects_a_non_positive_budget(tool_home):
    """The tool refuses 0/negative instead of storing an inert budget."""
    from tools import kanban_tools as kt

    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="tool card", max_iterations=220)

    out = json.loads(kt._handle_edit({"task_id": tid, "max_iterations": 0}))

    assert "error" in out, out
    assert "max_iterations must be >= 1" in out["error"], out
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220


def test_kanban_edit_tool_without_any_field_is_a_no_op_error(tool_home):
    """An empty edit is refused with a message that says what to pass."""
    from tools import kanban_tools as kt

    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="tool card", max_iterations=220)

    out = json.loads(kt._handle_edit({"task_id": tid}))

    assert "error" in out, out
    assert "max_iterations" in out["error"], out
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220


def test_kanban_edit_tool_rejects_a_fractional_budget(tool_home):
    """220.9 is not a budget: int() would silently truncate it to 220."""
    from tools import kanban_tools as kt

    with kbc.connect_closing() as conn:
        tid = _make_card(conn, title="tool card", max_iterations=220)

    out = json.loads(kt._handle_edit({"task_id": tid, "max_iterations": 220.9}))

    assert "error" in out, out
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).max_iterations == 220

