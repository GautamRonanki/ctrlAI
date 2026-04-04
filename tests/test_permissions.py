"""
Tests for ctrlAI core permission enforcement.
Validates that scope checks, inter-agent policies, suspension,
and high-stakes identification work against the live registry.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.permissions import (
    get_all_agents,
    AgentStatus,
    check_scope_permission,
    check_inter_agent_permission,
    is_high_stakes,
    suspend_agent,
    activate_agent,
    get_permission_matrix,
    AVAILABLE_SCOPES,
)


def _first_active_agent():
    """Return (name, agent) for the first active agent with scopes."""
    for name, agent in get_all_agents().items():
        if agent.status == AgentStatus.ACTIVE and agent.permitted_scopes:
            return name, agent
    raise RuntimeError("No active agent with scopes found")


def test_active_agent_has_permitted_scope():
    """An active agent should be allowed a scope in its permitted_scopes."""
    name, agent = _first_active_agent()
    scope = agent.permitted_scopes[0]
    assert check_scope_permission(name, scope, _system_bypass_rate_limit=True) is True


def test_active_agent_denied_unpermitted_scope():
    """An active agent should be denied a scope not in its permitted_scopes."""
    name, agent = _first_active_agent()
    available = AVAILABLE_SCOPES.get(name, [])
    denied = [s for s in available if s not in agent.permitted_scopes]
    if not denied:
        # All available scopes are permitted; pick a scope from a different agent
        for other_name, other_scopes in AVAILABLE_SCOPES.items():
            if other_name != name:
                for s in other_scopes:
                    if s not in agent.permitted_scopes:
                        denied = [s]
                        break
            if denied:
                break
    assert denied, "Could not find an unpermitted scope to test"
    assert check_scope_permission(name, denied[0], _system_bypass_rate_limit=True) is False


def test_suspended_agent_denied_all():
    """A suspended agent should be denied all scope checks."""
    name, agent = _first_active_agent()
    scope = agent.permitted_scopes[0]
    try:
        suspend_agent(name)
        assert check_scope_permission(name, scope, _system_bypass_rate_limit=True) is False
    finally:
        activate_agent(name)


def test_inter_agent_allowed():
    """A pair listed in the permission matrix should be allowed."""
    matrix = get_permission_matrix()
    for requester, targets in matrix.items():
        for target, actions in targets.items():
            if actions:
                assert check_inter_agent_permission(requester, target, actions[0]) is True
                return
    raise RuntimeError("No inter-agent permission pair found")


def test_inter_agent_blocked():
    """A pair not listed in the permission matrix should be blocked."""
    matrix = get_permission_matrix()
    agents = get_all_agents()
    active = [n for n, a in agents.items() if a.status == AgentStatus.ACTIVE]
    for req in active:
        for tgt in active:
            if req == tgt:
                continue
            if not matrix.get(req, {}).get(tgt, []):
                assert check_inter_agent_permission(req, tgt, "send_email") is False
                return
    raise RuntimeError("No blocked inter-agent pair found")


def test_high_stakes_identified():
    """An action in the agent's high_stakes_actions should be flagged."""
    for name, agent in get_all_agents().items():
        if agent.status == AgentStatus.ACTIVE and agent.high_stakes_actions:
            action = agent.high_stakes_actions[0]
            assert is_high_stakes(name, action) is True
            return
    raise RuntimeError("No agent with high-stakes actions found")


def test_non_high_stakes_identified():
    """An action not in the agent's high_stakes_actions should not be flagged."""
    for name, agent in get_all_agents().items():
        if agent.status == AgentStatus.ACTIVE and agent.high_stakes_actions:
            available = AVAILABLE_SCOPES.get(name, [])
            non_hs = [a for a in available if a not in agent.high_stakes_actions]
            if non_hs:
                assert is_high_stakes(name, non_hs[0]) is False
                return
    raise RuntimeError("No agent with a non-high-stakes action found")
