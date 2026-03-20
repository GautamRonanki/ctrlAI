"""
Agent Registry and Permission Model for ctrlAI.
This is the core governance layer. Every agent has a registered identity,
explicit scopes, and governed inter-agent communication rules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.logger import log_permission_check, log_inter_agent


class AgentStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class AgentIdentity:
    name: str
    description: str
    oauth_provider: str  # "google" or "github"
    permitted_scopes: list[str]
    high_stakes_actions: list[str]  # actions that require CIBA
    status: AgentStatus = AgentStatus.ACTIVE


# ============================================================
# Agent Registry — every agent must be registered here
# ============================================================

AGENT_REGISTRY: dict[str, AgentIdentity] = {
    "gmail_agent": AgentIdentity(
        name="gmail_agent",
        description="Reads and sends emails via Gmail",
        oauth_provider="google",
        permitted_scopes=["gmail.readonly", "gmail.send"],
        high_stakes_actions=["send_email"],
    ),
    "drive_agent": AgentIdentity(
        name="drive_agent",
        description="Reads and manages files in Google Drive",
        oauth_provider="google",
        permitted_scopes=["drive.readonly", "drive.file"],
        high_stakes_actions=["delete_file"],
    ),
    "calendar_agent": AgentIdentity(
        name="calendar_agent",
        description="Reads and manages Google Calendar events",
        oauth_provider="google",
        permitted_scopes=["calendar.events.readonly", "calendar.events"],
        high_stakes_actions=["create_event"],
    ),
    "github_agent": AgentIdentity(
        name="github_agent",
        description="Reads repos and manages GitHub issues",
        oauth_provider="github",
        permitted_scopes=["repo", "read:user"],
        high_stakes_actions=["create_comment"],
    ),
}

# ============================================================
# Inter-Agent Permission Matrix
# Format: {requesting_agent: {target_agent: [allowed_actions]}}
# Any request not listed here is DENIED.
# ============================================================

INTER_AGENT_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    "gmail_agent": {
        "drive_agent": ["store_attachment"],
        "calendar_agent": ["check_availability"],
    },
    "calendar_agent": {
        "gmail_agent": ["read_email_context"],
    },
    "github_agent": {
        "gmail_agent": ["read_email_context"],
    },
}


def get_agent(name: str) -> Optional[AgentIdentity]:
    """Get an agent's identity from the registry."""
    return AGENT_REGISTRY.get(name)


def is_agent_active(name: str) -> bool:
    """Check if an agent is active."""
    agent = get_agent(name)
    return agent is not None and agent.status == AgentStatus.ACTIVE


def check_scope_permission(agent_name: str, requested_scope: str) -> bool:
    """
    Check if an agent has permission for a specific scope.
    Returns True if allowed, False if denied. Always logs the result.
    """
    agent = get_agent(agent_name)
    if agent is None:
        log_permission_check(agent_name, requested_scope, False, "agent not found")
        return False

    if agent.status != AgentStatus.ACTIVE:
        log_permission_check(agent_name, requested_scope, False, f"agent status: {agent.status}")
        return False

    allowed = requested_scope in agent.permitted_scopes
    log_permission_check(
        agent_name,
        requested_scope,
        allowed,
        "scope permitted" if allowed else "scope not in agent's registered permissions",
    )
    return allowed


def is_high_stakes(agent_name: str, action: str) -> bool:
    """Check if an action requires CIBA approval."""
    agent = get_agent(agent_name)
    if agent is None:
        return False
    return action in agent.high_stakes_actions


def check_inter_agent_permission(requesting_agent: str, target_agent: str, action: str) -> bool:
    """
    Check if one agent is allowed to communicate with another.
    Returns True if allowed, False if denied. Always logs the result.
    """
    agent_permissions = INTER_AGENT_PERMISSIONS.get(requesting_agent, {})
    allowed_actions = agent_permissions.get(target_agent, [])
    allowed = action in allowed_actions

    log_inter_agent(requesting_agent, target_agent, action, allowed)
    return allowed


def suspend_agent(agent_name: str) -> bool:
    """Suspend an agent — takes effect immediately on next request."""
    agent = get_agent(agent_name)
    if agent is None:
        return False
    agent.status = AgentStatus.SUSPENDED
    return True


def activate_agent(agent_name: str) -> bool:
    """Reactivate a suspended agent."""
    agent = get_agent(agent_name)
    if agent is None:
        return False
    agent.status = AgentStatus.ACTIVE
    return True


def get_all_agents() -> dict[str, AgentIdentity]:
    """Return the full agent registry."""
    return AGENT_REGISTRY.copy()


def get_permission_matrix() -> dict:
    """Return the full inter-agent permission matrix."""
    return INTER_AGENT_PERMISSIONS.copy()
