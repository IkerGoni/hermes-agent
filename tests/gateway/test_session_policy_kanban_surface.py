"""A kanban worker's ``session.create`` with ``source='kanban'`` is admitted, not refused.

Kanban workers asked the gateway to create their turn's session with ``source='kanban'`` and got
``invalid_params`` (JSON-RPC 4001) back, because ``build_policy`` gates every creation label on
``SURFACES`` and ``'kanban'`` was missing from it. The restore path already accepted the label as
``{**SURFACES, 'cron': 'cron', 'kanban': 'cli', 'bot_room': 'bot_room'}`` and
``gateway/session_kanban.py`` already creates kanban policies with ``source='kanban'``,
``platform='cli'``, so the create path was the only one that never learned it.

``kanban`` is a producer label like ``tool`` and ``oneshot``: it runs as the CLI but keeps its own
stored label, which is what hides its sessions from human pickers (``INTERNAL_LISTING_SOURCES``).
Listing it in ``SURFACES`` must not fold it into ``cli``.
"""

import pytest

from gateway.session_policy import STORED_AS_LOCAL, SURFACES, build_policy, created_surface

# A profile config with no plugins, MCP servers or picks: build_policy must not need a real profile.
_CONFIG = {'model': {'default': 'fixture-model'}, 'platform_toolsets': {'cli': []}}


def _build(params, tmp_path):
    return build_policy({**params, 'cwd': str(tmp_path)}, _CONFIG, private_secrets={})


def test_kanban_is_a_creation_surface_as_the_cli():
    assert 'kanban' in SURFACES
    assert SURFACES['kanban'] == 'cli'


def test_create_policy_accepts_source_kanban(tmp_path):
    policy = _build({'source': 'kanban'}, tmp_path)
    assert policy.source == 'kanban'
    assert policy.platform == 'cli'


def test_create_policy_accepts_the_kanban_toolsets_the_dispatcher_sends(tmp_path):
    """The 'kanban' toolset is only admissible on a CLI policy, so the refusal cleared both checks."""
    policy = _build({'source': 'kanban', 'toolsets': ['terminal', 'file', 'kanban']}, tmp_path)
    assert policy.platform == 'cli'
    assert 'kanban' in policy.toolsets


def test_kanban_keeps_its_own_stored_label():
    """Pickers hide kanban workers by label; folding it into ``local``/``cli`` would list them."""
    assert created_surface('kanban') == 'kanban'
    assert 'kanban' not in STORED_AS_LOCAL


def test_an_unknown_source_is_still_refused(tmp_path):
    from hermes_state_runtime import RuntimeStoreError

    with pytest.raises(RuntimeStoreError) as caught:
        _build({'source': 'not-a-real-surface'}, tmp_path)
    assert caught.value.reason == 'invalid_params'
    assert caught.value.field == 'source'
