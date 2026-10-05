"""Tests: a card's ``max_iterations`` reaches its worker as ``--max-turns``.

The iteration budget is the per-turn cap that actually stops a worker
(``agent/iteration_budget.py``, consumed at ``agent/turn_iteration_prep.py``), and
until now it was only reachable as a profile-wide ``agent.max_turns`` — one invisible
global for every card. Two JobScout cards on 2026-09-27 proved that is not enough:
``t_16701e29`` finished, committed and requested review, then the dispatcher revoked
its run with ``gave_up: Iteration budget exhausted (220/220)`` 13 seconds later, so a
*delivered* card was reported as a failure; ``t_b91348dd`` hit the same wall with 5
modified files and 0 commits, so correct work was lost because it was never committed.

Both are the same defect from two sides: the budget that decides "this card is done"
is not the budget the card was planned for. ``max_runtime_seconds`` already gives a
card its own runtime cap; this gives a card its own iteration cap, so a card that
knows it needs a full test suite says so instead of inheriting a default calibrated
for a small card.

The channel matters as much as the feature. ``HERMES_MAX_ITERATIONS`` looks like the
obvious place to put it, but ``cli_init_mixin._init_turn_limits`` resolves the cap as
"CLI arg > config > env var" — a profile that already sets ``agent.max_turns`` (the
builder profile sets 220, which is exactly the value that broke these two cards)
would shadow the env var and the card would get the profile default anyway. So the
dispatcher passes ``--max-turns``, the only channel that wins, and the tests below pin
the flag rather than an env var.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Optional

import pytest


def _make_task(kb, *, assignee: str = "w", max_iterations=None):
    return kb.Task(
        id="t_iterbudget",
        title="iteration budget",
        body=None,
        assignee=assignee,
        status="running",
        priority=0,
        created_by="test",
        created_at=1,
        started_at=None,
        completed_at=None,
        workspace_kind="dir",
        workspace_path=None,
        claim_lock="lock",
        claim_expires=None,
        tenant=None,
        current_run_id=1,
        max_iterations=max_iterations,
    )


def _capture_spawn(kb, monkeypatch, workspace: str, task) -> dict:
    from hermes_cli import kanban_db_dispatch as kbd

    monkeypatch.setattr(kbd, "_resolve_hermes_argv", lambda: ["hermes"])

    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs.get("env") or {})
        captured["cwd"] = kwargs.get("cwd")
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    kbd._default_spawn(task, workspace)
    return captured


def _max_turns_flag(cmd: list) -> Optional[str]:
    """The value the worker will enforce, read back the way the CLI resolves it."""
    return cmd[cmd.index("--max-turns") + 1] if "--max-turns" in cmd else None


def _profile_env(monkeypatch, tmp_path) -> None:
    root = tmp_path / ".hermes"
    (root / "profiles" / "w").mkdir(parents=True)
    (root / "profiles" / "w" / "config.yaml").write_text("toolsets:\n  - kanban\n", encoding="utf-8")
    root.joinpath("config.yaml").write_text("toolsets:\n  - kanban\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))


def test_card_max_iterations_reaches_the_worker_argv(monkeypatch, tmp_path):
    """A card that declares its own budget gets it, instead of inheriting the profile's."""
    _profile_env(monkeypatch, tmp_path)

    from hermes_cli import kanban_db as kb

    workspace = tmp_path / "ws"
    workspace.mkdir()

    captured = _capture_spawn(
        kb, monkeypatch, str(workspace), _make_task(kb, max_iterations=600)
    )

    assert _max_turns_flag(captured["cmd"]) == "600"


def test_absent_card_max_iterations_adds_no_flag(monkeypatch, tmp_path):
    """No card override -> no ``--max-turns``, so the profile default still wins.

    Adding the flag unconditionally would pin every card to one value and silently
    re-create the invisible global this feature exists to make explicit.
    """
    _profile_env(monkeypatch, tmp_path)
    monkeypatch.delenv("HERMES_MAX_ITERATIONS", raising=False)

    from hermes_cli import kanban_db as kb

    workspace = tmp_path / "ws"
    workspace.mkdir()

    captured = _capture_spawn(kb, monkeypatch, str(workspace), _make_task(kb))

    assert "--max-turns" not in captured["cmd"]


def test_card_max_iterations_is_not_shadowed_by_a_profile_max_turns(monkeypatch, tmp_path):
    """The flag must win over a profile that already sets agent.max_turns.

    This is the exact profile that hit the bug: builder's config.yaml pins
    agent.max_turns: 220, and 220/220 is the budget that reported a delivered card as
    failed. An env-var implementation would satisfy any assertion about
    HERMES_MAX_ITERATIONS and still leave the worker capped at 220, because config
    outranks env. Only the CLI arg clears the profile, so that is what the test pins.
    """
    _profile_env(monkeypatch, tmp_path)
    profile_cfg = tmp_path / ".hermes" / "profiles" / "w" / "config.yaml"
    profile_cfg.write_text("agent:\n  max_turns: 220\n", encoding="utf-8")
    # A dispatcher that holds the env var for its own turn must not stand in for
    # the card's budget either.
    monkeypatch.setenv("HERMES_MAX_ITERATIONS", "220")

    from hermes_cli import kanban_db as kb

    workspace = tmp_path / "ws"
    workspace.mkdir()

    captured = _capture_spawn(
        kb, monkeypatch, str(workspace), _make_task(kb, max_iterations=600)
    )

    assert _max_turns_flag(captured["cmd"]) == "600"


def test_non_positive_card_max_iterations_adds_no_flag(monkeypatch, tmp_path):
    """0 / negative are not budgets: they must never become ``--max-turns 0``.

    ``resolve_turn_limit`` reads <= 0 as "unlimited", so a 0 the card never meant
    would hand the worker a sys.maxsize cap by accident.
    """
    _profile_env(monkeypatch, tmp_path)
    monkeypatch.delenv("HERMES_MAX_ITERATIONS", raising=False)

    from hermes_cli import kanban_db as kb

    workspace = tmp_path / "ws"
    workspace.mkdir()

    for bogus in (0, -1):
        captured = _capture_spawn(
            kb, monkeypatch, str(workspace), _make_task(kb, max_iterations=bogus)
        )
        assert "--max-turns" not in captured["cmd"], bogus


def test_flag_does_not_disturb_the_other_worker_pins(monkeypatch, tmp_path):
    """Adding the budget must not reorder or drop the existing argv contract.

    ``--max-turns`` goes in with the other per-card pins but *after* ``chat``:
    it is declared only on the chat subparser, so in the pre-``chat`` block
    argparse read ``60`` as the subcommand and the worker died before running a
    turn (t_cbdfd12b). See test_kanban_worker_max_turns_argv_order.py.
    """
    _profile_env(monkeypatch, tmp_path)

    from hermes_cli import kanban_db as kb

    workspace = tmp_path / "ws"
    workspace.mkdir()

    task = _make_task(kb, max_iterations=600)
    task.model_override = "some-model"
    task.reasoning_effort = "high"
    task.skills = ["a-skill"]
    captured = _capture_spawn(kb, monkeypatch, str(workspace), task)
    cmd = captured["cmd"]

    assert cmd[cmd.index("-m") + 1] == "some-model"
    assert cmd[cmd.index("--reasoning") + 1] == "high"
    assert cmd[cmd.index("--skills") + 1] == "a-skill"
    # Chat-only flag: it must follow the subcommand it belongs to.
    assert cmd.index("--max-turns") > cmd.index("chat")
    assert cmd[-1] == f"work kanban task {task.id}"


# ---------------------------------------------------------------------------
# Persistence: the value has to survive create -> row -> dispatch, or the whole
# feature is unreachable. A card's budget that is not stored is not a budget.
# ---------------------------------------------------------------------------


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    from pathlib import Path

    from hermes_cli import kanban_db as kb

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_create_task_persists_and_round_trips_max_iterations(kanban_home):
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

    with kbc.connect_closing() as conn:
        tid = kb.create_task(conn, title="budgeted", assignee="w", max_iterations=600)
        assert kb.get_task(conn, tid).max_iterations == 600
        # A card that asks for no budget keeps the profile's authority.
        plain = kb.create_task(conn, title="unbudgeted", assignee="w")
        assert kb.get_task(conn, plain).max_iterations is None


def test_max_iterations_column_exists_on_a_fresh_board(kanban_home):
    """The fresh-schema DDL and the migration list must agree, or an old board
    migrated forward reads a column the new board never had."""
    from hermes_cli import kanban_db_connect as kbc

    with kbc.connect_closing() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert "max_iterations" in cols


def test_cli_rejects_a_non_positive_max_iterations(kanban_home, capsys):
    """--max-iterations 0 is refused, not silently ignored.

    A silent drop would let an orchestrator believe it raised a budget the worker never
    got; and 0 is exactly the value resolve_turn_limit reads as "unlimited", so a later
    code path could act on it.
    """
    from hermes_cli import kanban as kc

    rc = kc._cmd_create(argparse.Namespace(
        title="bogus", body=None, assignee="w", created_by=None,
        workspace=None, branch=None, project=None, tenant=None, priority=0,
        parent=[], triage=False, idempotency_key=None, max_runtime=None,
        skills=[], max_retries=None, model_override=None, provider_override=None,
        goal_mode=False, goal_max_turns=None, completion_contract=None,
        initial_status="running", max_iterations=0, json=False,
    ))
    assert rc == 2
    captured = capsys.readouterr()
    assert "--max-iterations must be >= 1" in captured.out + captured.err
