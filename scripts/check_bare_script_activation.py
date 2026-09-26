#!/usr/bin/env python3
"""Check that every bare-script spawn's child selects a dependency generation.

A bare-script spawn — ``[sys.executable, tools/foo.py, …]`` — boots a fresh
interpreter on PM's store Python, which carries NO third-party site-packages.
If ``foo.py``'s ``__main__`` does not select a generation, the child's first real
import dies with ``ModuleNotFoundError`` and the operator sees nothing. That is
exactly how every ``message_agent`` delivery was dropped: the background runner
``tools/bot_mode_dm.py`` was spawned as a bare script and its import chain
(``utils`` → ``hermes_yaml`` → ``ruamel.yaml``) had nowhere to resolve.

The gate is on the CHILD, not the caller: the caller is a long-lived module
already imported inside an activated process; only the fresh interpreter needs
to activate. And BOTH halves are required — ``import hermes_bootstrap`` without
first putting the repo root on ``sys.path`` is a no-op, because ``sys.path[0]``
for a script run as a file is the script's own directory. A narrow
``except ModuleNotFoundError`` then swallows the miss and the bootstrap never
runs: the fix looks applied and the child still dies. That shipped by accident
on ``tools/neutts_synth.py`` and every check that only read the source passed it.

A child may opt out only by declaring itself standard-library-only in its own
docstring, so the exemption stays auditable instead of a silent allowlist.

This is a static check, so it lives here rather than in the pytest suite:
AGENTS.md forbids tests that read source files, and the repo's other
source-reading invariants are ``scripts/check_*.py`` wired into ``lint.yml``.
What a static check cannot see — whether an import actually RESOLVES at runtime
— is covered by ``tests/tools/test_bot_mode_dm.py``'s invariant test, which
executes the child.

Exit codes:
  0 — every spawned child can select a generation (or is stdlib-only)
  1 — violations found
  2 — script error
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shipped code that spawns children. Tests/evals spawn too, but they are not
# shipped and are not part of the runtime path this protects.
SEARCH_ROOTS = ("tools", "agent", "gateway", "hermes_cli", "pm", "plugins")

# ``tools/`` doubles as PM's tool store (``tools/node-26.7.0-darwin-arm64/``,
# ``tools/python-3.14.7+…/``): vendored third-party source that ships inside the
# checkout but is not Hermes code, and which this check must not reason about.
# Those directories carry a version segment, so match the store's own naming
# shape instead of guessing tool names.
STORE_DIR_RE = re.compile(
    r"^(node|python|uv|ffmpeg|npm|ripgrep|agent-browser|chromium|tirith)[-_]?[0-9]"
)

SKIP_DIRS = {"__pycache__", "tests", "evals", "node_modules", ".venv", "venv"}

# A target expression that names a Python file in this repo, whether by literal
# name, ``__file__``, or a ``Path(__file__)`` expression. ``-m <module>`` is
# deliberately absent: a module entry point runs its own top-level imports, and
# every Hermes module entry point already imports hermes_bootstrap. The hazard
# is specifically a script PATH.
_PY_PATH_RE = re.compile(r"""(\.py["']|__file__)""")

_STDLIB_ONLY_RE = re.compile(r"standard[- ]library[- ]only", re.IGNORECASE)


def iter_shipped_python_files() -> list[Path]:
    """Hermes' own shipped Python, excluding the vendored tool store."""
    found: list[Path] = []
    for root_name in SEARCH_ROOTS:
        root = REPO_ROOT / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            parts = path.relative_to(REPO_ROOT).parts
            if any(part in SKIP_DIRS for part in parts):
                continue
            if any(STORE_DIR_RE.match(part) for part in parts[:-1]):
                continue
            found.append(path)
    return found


def sys_aliases(tree: ast.AST) -> set[str]:
    """Every local name bound to the ``sys`` module (``import sys`` / ``import sys as s``).

    ``import sys as s`` is legal and would make a name-only walk miss the spawn
    entirely, so resolve the aliases first. Missing one is a silent false
    negative — the check would report clean while the hazard is present.
    """
    aliases = {"sys"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    aliases.add(alias.asname or "sys")
    return aliases


def is_executable_ref(node: ast.expr, tree: ast.AST) -> bool:
    """argv[0] is the interpreter: ``sys.executable`` under any alias, or the bare
    name bound by ``from sys import executable``."""
    if isinstance(node, ast.Name) and node.id == "executable":
        return any(
            isinstance(n, ast.ImportFrom)
            and n.module == "sys"
            and any(a.name == "executable" for a in n.names)
            for n in ast.walk(tree)
        )
    if not (isinstance(node, ast.Attribute) and node.attr == "executable"):
        return False
    return isinstance(node.value, ast.Name) and node.value.id in sys_aliases(tree)


def script_nodes(tree: ast.AST):
    """Yield argv[1] of every argv list whose argv[0] is this interpreter.

    AST, not regex: the argv may be a list literal inline in the call
    (``subprocess.Popen([sys.executable, str(Path(__file__) …)])``), spread over
    several lines, or hoisted to a module constant — a text pattern misses the
    first and mangles the second.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
            continue
        if not is_executable_ref(node.elts[0], tree):
            continue
        if _PY_PATH_RE.search(ast.unparse(node.elts[1])):
            yield node.elts[1]


def script_targets(source: str) -> list[str]:
    """Every spawned script path in ``source``, rendered."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # a shipped file that does not parse
        return []
    return [ast.unparse(node) for node in script_nodes(tree)]


def resolve_child(caller: Path, literal: str) -> Path | None:
    """Locate a spawned script given a ``.py`` string literal from its argv.

    Resolved against the CALLER's directory — that is how ``Path(__file__)
    .with_name("neutts_synth.py")`` is meant to be read — then the repo root, then
    ``tools/``. A flat ``tools/``-only lookup silently missed callers that live
    anywhere else, and a miss reads as "nothing to judge".
    """
    name = Path(literal).name
    for base in (caller.parent, caller.parent.parent, REPO_ROOT, REPO_ROOT / "tools"):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def spawned_child_path(source: str, caller: Path) -> Path | None:
    """The actual child file, when the argv names a readable repo ``.py``.

    ``Path(__file__).resolve()`` carries no ``.py`` literal to key on, so a
    self-spawn (the file running itself as a script — exactly how
    ``tools/bot_mode_dm.py`` launches its own background runner) would otherwise
    read as "not statically resolvable" and be silently skipped. That is the
    original bug's own file, so exempting it would exempt the thing this check
    exists to protect.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for target in script_nodes(tree):
        rendered = ast.unparse(target)
        # A self-spawn — argv[1] is this very file, written as
        # ``Path(__file__).resolve()`` with no ``.py`` literal to key on. Resolve
        # it to the caller. Any OTHER __file__-derived path (e.g.
        # ``Path(__file__).with_name("neutts_synth.py")``) is a different file and
        # still has to be found by its literal below.
        if "__file__" in rendered and ".py" not in rendered:
            return caller
        for literal in ast.walk(target):
            if not (isinstance(literal, ast.Constant)
                    and isinstance(literal.value, str)
                    and literal.value.endswith(".py")):
                continue
            child = resolve_child(caller, literal.value)
            if child is not None:
                return child
    return None


def declares_stdlib_only(source: str) -> bool:
    """The stdlib-only exemption is a CLAIM the module makes about itself, in prose.

    ``tools/mcp_death_supervisor.py`` already documents exactly this ("deliberately
    standard-library-only and must not import anything from tools/"), so the
    convention exists — this only requires the claim to be machine-checkable.
    """
    return bool(_STDLIB_ONLY_RE.search(source))


def puts_repo_root_on_sys_path(source: str) -> bool:
    """True when the ``__main__`` body puts the repo root on ``sys.path``.

    Required, not optional: see the module docstring. Accepts
    ``sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`` and any
    equivalent that appends a ``__file__``-derived parent path.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in {"insert", "append"}):
            continue
        if not (isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id in sys_aliases(tree)):
            continue
        # The path is args[1] for insert(0, path) and args[0] for append(path);
        # check every argument rather than guessing the position.
        if any("__file__" in ast.unparse(arg) and "parent" in ast.unparse(arg)
               for arg in node.args):
            return True
    return False


def main_block_imports_bootstrap(source: str) -> bool:
    """True when the ``__main__`` guard can reach a ``hermes_bootstrap`` import.

    The child runs the ``if __name__ == "__main__":`` body, so that is the ONLY
    place a bare-script spawn can select its generation — a module-level import is
    never executed in the child, and a lazy import inside a helper is far too late
    (it fires after the import chain has already failed).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if not (isinstance(node, ast.If) and is_main_guard(node.test)):
            continue
        for statement in node.body:
            for inner in ast.walk(statement):
                if isinstance(inner, ast.Import) and any(
                    alias.name == "hermes_bootstrap" for alias in inner.names
                ):
                    return True
                if isinstance(inner, ast.ImportFrom) and inner.module == "hermes_bootstrap":
                    return True
    return False


def main_block_is_activatable(source: str) -> bool:
    """The real gate: the child's ``__main__`` both finds and runs the bootstrap."""
    return main_block_imports_bootstrap(source) and puts_repo_root_on_sys_path(source)


def is_main_guard(test: ast.expr) -> bool:
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return False
    left, op, right = test.left, test.ops[0], test.comparators[0]
    return (
        isinstance(op, ast.Eq)
        and isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def audit() -> tuple[list[str], list[str]]:
    """Return ``(violations, checked)`` describing every bare-script spawn."""
    violations: list[str] = []
    checked: list[str] = []

    for path in iter_shipped_python_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        targets = script_targets(source)
        if not targets:
            continue
        caller = path.relative_to(REPO_ROOT).as_posix()
        child = spawned_child_path(source, path)
        if child is None:
            # Target is not a repo .py we can read (external interpreter, or a
            # path built at runtime): nothing this scan can judge.
            checked.append(f"{caller} (spawn target not statically resolvable)")
            continue
        child_source = child.read_text(encoding="utf-8", errors="replace")
        if declares_stdlib_only(child_source):
            checked.append(f"{caller} → {child.name} (child is stdlib-only, exempt)")
            continue
        if main_block_is_activatable(child_source):
            checked.append(f"{caller} → {child.name} (child bootstrapped)")
            continue
        violations.append(
            f"{caller}: spawns {targets!r} as a bare script, and {child.name}'s "
            f"__main__ block does not select a dependency generation — so the child "
            f"boots on a PM store Python with no third-party packages and its first "
            f"real import dies (see the tools/bot_mode_dm.py fix). Its __main__ must "
            f"put the repo root on sys.path AND import hermes_bootstrap there, or "
            f"state in its docstring that it is standard-library-only."
        )
    return violations, checked


def main() -> int:
    try:
        violations, checked = audit()
    except Exception as exc:  # noqa: BLE001 - a checker must not traceback
        print(f"check_bare_script_activation: {exc}", file=sys.stderr)
        return 2

    if violations:
        print(f"❌ {len(violations)} bare-script spawn(s) whose child never selects "
              f"a dependency generation:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    # A guard that silently matches nothing is worse than no guard: it would let
    # the next bare-script spawn through unexamined.
    if not checked:
        print("❌ no bare-script spawns found in shipped code — the discovery "
              "pattern no longer matches the tree, so it can no longer catch a new "
              "violation", file=sys.stderr)
        return 2

    print(f"✅ {len(checked)} bare-script spawn(s), all children select a "
          f"generation or are standard-library-only:")
    for entry in checked:
        print(f"  {entry}")
    return 0


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    sys.exit(main())
