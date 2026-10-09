"""Tests: a card's ``--max-turns`` must land AFTER ``chat`` in the worker argv.

`--max-turns` is declared only on the `chat` subparser (`hermes_cli/_parser.py`,
`_build_chat_parser`), not on the top-level parser. The dispatcher used to build

    hermes -p w --cli … --max-turns 60 chat -q "work kanban task t_x"

so argparse treated `60` as the subcommand and the worker died before it ran:

    hermes: '60' is not a `hermes` command. Run `hermes --help` to see all commands.

Measured on the jobscout board (t_c89adccb, archived): two runs crashed on that
message and `gave_up` spent the card's whole retry budget — a worker that never
started, reported as a failed card. It stayed latent because
`cmd.extend(["--max-turns", …])` only fires when `max_iterations is not None`, and
no card on any of the 5 active boards carried one.

These tests pin the argv, not the spawn: the failure was a malformed command line,
so a test that only asserted "the flag is somewhere in the list" would have kept
passing against the broken builder.
"""

from __future__ import annotations

import subprocess

import pytest


def _make_task(kb, *, assignee: str = "w", **overrides):
    base = dict(
        id="t_maxturns_argv",
        title="argv order",
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
    )
    base.update(overrides)
    return kb.Task(**base)


def _argv(kbd, monkeypatch, tmp_path, task) -> list[str]:
    """The argv the dispatcher would exec, with the config reads stubbed out."""
    from hermes_cli import kanban_db as kb

    monkeypatch.setattr(kbd, "_resolve_hermes_argv", lambda: ["hermes"])
    monkeypatch.setattr(kbd, "_resolve_worker_cli_toolsets", lambda home: None)
    return kbd._worker_argv(task, "w", str(tmp_path))


@pytest.fixture(autouse=True)
def _isolate_profile(monkeypatch, tmp_path):
    root = tmp_path / ".hermes"
    (root / "profiles" / "w").mkdir(parents=True)
    (root / "profiles" / "w" / "config.yaml").write_text("{}\n", encoding="utf-8")
    root.joinpath("config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))


def _parse_through_the_real_cli(monkeypatch, cmd: list[str]):
    """Parse a worker argv with the REAL parser, minus the ``-p`` prefix.

    ``-p`` is consumed by ``main._apply_profile_override`` before argparse runs, so
    it is not on the parser; the argv from index 3 onward is what argparse sees.
    """
    from hermes_cli._parser import build_top_level_parser

    assert cmd[1:3] == ["-p", "w"]
    parser, _subparsers, _chat_parser = build_top_level_parser()
    return parser.parse_args(cmd[3:])


def test_max_turns_comes_after_the_chat_subcommand(monkeypatch, tmp_path):
    """The regression itself: the flag is chat-only, so it must follow ``chat``.

    Asserting only that ``--max-turns 60`` is present would pass on the broken argv
    too — the whole defect is *where* in the list it sits.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    cmd = _argv(kbd, monkeypatch, tmp_path, _make_task(kb, max_iterations=60))

    assert cmd.index("--max-turns") > cmd.index("chat")
    assert cmd[cmd.index("--max-turns") + 1] == "60"
    # `chat` must be the first bare token: a value the top-level parser has no home
    # for (here the "60") would otherwise be read as the subcommand.
    assert cmd[cmd.index("chat") - 1].startswith("-")


def test_worker_argv_with_max_turns_survives_the_real_parser(monkeypatch, tmp_path):
    """The exact failure the board recorded, reproduced against the real parser.

    Before the fix this raised ``SystemExit(2)`` with
    ``hermes: '60' is not a `hermes` command`` — the message two runs of t_c89adccb
    died on. An argv that parses and carries the budget is the acceptance criterion.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    cmd = _argv(kbd, monkeypatch, tmp_path, _make_task(kb, max_iterations=60))

    args = _parse_through_the_real_cli(monkeypatch, cmd)

    assert args.command == "chat"
    assert args.max_turns == 60
    assert args.query == "work kanban task t_maxturns_argv"


def test_no_max_iterations_keeps_the_flag_off_and_still_parses(monkeypatch, tmp_path):
    """The sibling path: a card that asks for no budget dispatches exactly as before.

    Adding the flag unconditionally would pin every card to one number and
    re-create the invisible profile-wide global this per-card budget exists to
    replace.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    cmd = _argv(kbd, monkeypatch, tmp_path, _make_task(kb))

    assert "--max-turns" not in cmd
    args = _parse_through_the_real_cli(monkeypatch, cmd)
    assert args.command == "chat"
    assert args.max_turns is None  # the profile's agent.max_turns stays in charge


def test_non_positive_budget_never_reaches_the_argv(monkeypatch, tmp_path):
    """0 / negative are not budgets: they must never become ``--max-turns 0``.

    ``resolve_turn_limit`` reads <= 0 as "unlimited" (sys.maxsize), so a 0 the card
    never meant would hand the worker an unbounded turn instead of no override.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    for bogus in (0, -5):
        cmd = _argv(kbd, monkeypatch, tmp_path, _make_task(kb, max_iterations=bogus))
        assert "--max-turns" not in cmd, bogus
        assert _parse_through_the_real_cli(monkeypatch, cmd).max_turns is None


def test_every_pre_chat_flag_is_accepted_by_the_top_level_parser(monkeypatch, tmp_path):
    """No sibling flag carries the same defect.

    ``--max-turns`` was not a one-off accident of a badly ordered call site: it is
    the only flag ``_worker_argv`` emits before ``chat`` that the top-level parser
    does not declare. This pins that, so the next flag someone adds to the
    pre-``chat`` block cannot repeat the bug silently.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd
    from hermes_cli._parser import build_top_level_parser

    cmd = _argv(
        kbd,
        monkeypatch,
        tmp_path,
        _make_task(
            kb,
            model_override="gpt-5.6-sol",
            provider_override="openrouter",
            reasoning_effort="high",
            skills=["kanban-run-lessons"],
            max_iterations=60,
        ),
    )

    top_level = {o for a in build_top_level_parser()[0]._actions for o in a.option_strings}
    # Walk the argv the way argparse does before the subcommand: a value-taking
    # flag consumes the next token, so anything value-shaped is skipped.
    value_flags = {
        opt for a in build_top_level_parser()[0]._actions
        if a.nargs != 0 for opt in a.option_strings
    }
    pre_chat = []
    i = 3
    while i < len(cmd):
        tok = cmd[i]
        if not tok.startswith("-"):
            pre_chat.append(tok)
            break
        pre_chat.append(tok)
        if "=" not in tok and tok in value_flags:
            pre_chat.append(cmd[i + 1])
            i += 2
        else:
            i += 1

    assert pre_chat[-1] == "chat"
    strays = [
        tok for tok in pre_chat
        if tok.startswith("-") and tok not in top_level and tok != "chat"
    ]
    assert strays == [], f"pre-chat flags the top-level parser does not declare: {strays}"


def test_spawn_puts_max_turns_after_chat_on_the_executed_command(monkeypatch, tmp_path):
    """Same guarantee one level up, on the argv actually handed to Popen.

    The unit tests above pin the builder; this pins that nothing downstream
    (``_restart_safe_worker_argv``, multiplex wrappers) rebuilds the order.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    workspace = tmp_path / "ws"
    workspace.mkdir()
    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeProc()

    monkeypatch.setattr(kbd, "_resolve_hermes_argv", lambda: ["hermes"])
    monkeypatch.setattr(kbd, "_resolve_worker_cli_toolsets", lambda home: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    kbd._default_spawn(_make_task(kb, max_iterations=60), str(workspace))

    cmd = captured["cmd"]
    assert cmd.index("--max-turns") > cmd.index("chat")
    assert cmd[cmd.index("--max-turns") + 1] == "60"
