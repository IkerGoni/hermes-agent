"""Regression: a worker whose workspace is a hermes-agent worktree must boot.

Every kanban worker whose workspace sits inside the Hermes install's own
repository died before reading its card. The dispatcher's module-form argv
(``sys.executable -m hermes_cli.main``) puts the workspace (the cwd) at the
front of the child's ``sys.path``, so the checkout's own versioned
``hermes_bootstrap.py`` shadowed the install's: ``_root`` resolved to the
worktree, PM hashed that worktree into a different ``installs/<key>``, found no
committed dependency environment there, and the CLI exited 1 with
``no dependency environment is committed for this install`` -- a remedy
(``hermes pm repair``) that could never help, because the install does have one.

The fix keeps the argv's ``-m hermes_cli.main`` shape -- other code matches it
positionally -- and closes the cwd entry instead, with ``-P``.
"""

from __future__ import annotations

import subprocess
import sys


def _make_task(kb, *, assignee: str):
    return kb.Task(
        id="t_safepath",
        title="safe path",
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
        current_run_id=7,
    )


def test_module_hermes_argv_keeps_the_cwd_off_the_workers_path():
    """The module-form worker argv must not let the workspace shadow Hermes.

    ``-P`` (PYTHONSAFEPATH) drops the implicit cwd entry ``-m`` would otherwise
    place in front of ``sys.path``. It must sit *before* ``-m`` so Python still
    treats the next argument as the module, and the ``-m hermes_cli.main``
    target must stay where the rest of the codebase looks for it.
    """
    from hermes_cli import kanban_db_dispatch as kbd

    argv = kbd._module_hermes_argv()

    assert argv[0] == sys.executable
    assert "-P" in argv, argv
    assert argv.index("-P") < argv.index("-m"), argv


def test_propagate_module_import_root_still_matches_with_safe_path():
    """The PYTHONPATH pin must survive the ``-P`` insertion.

    ``_propagate_module_import_root`` keys off ``cmd[1:3] == ["-m",
    "hermes_cli.main"]``. Slipping ``-P`` in at index 1 would shift that window
    and silently drop the import root -- the exact failure the pin exists to
    prevent (#122299), reintroduced under a new shape.
    """
    from hermes_cli import kanban_db_dispatch as kbd

    argv = kbd._module_hermes_argv()
    env: dict[str, str] = {}
    kbd._propagate_module_import_root(argv, env)

    # The install root, resolved the same way the dispatcher resolves it.
    from hermes_cli.kanban_db_dispatch import Path

    root = str(Path(kbd.__file__).resolve().parents[1])
    assert root in env.get("PYTHONPATH", ""), (argv, env)


def test_default_spawn_argv_carries_safe_path(monkeypatch, tmp_path):
    """The dispatched worker command, as Popen receives it, must carry ``-P``."""
    root = tmp_path / ".hermes"
    (root / "profiles" / "elias").mkdir(parents=True)
    root.joinpath("config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))

    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    captured: dict = {}

    class FakeProc:
        pid = 4243

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert kbd._default_spawn(_make_task(kb, assignee="elias"), str(workspace)) == 4243

    cmd = captured["cmd"]
    assert "-P" in cmd, cmd
    # The module target must still be reachable as the argv the CLI is launched
    # with; every positional matcher in the tree keys on these two entries.
    assert cmd[cmd.index("-m") + 1] == "hermes_cli.main", cmd