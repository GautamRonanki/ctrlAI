"""
Agent Registry and Permission Model for ctrlAI.
This is the core governance layer. Every agent has a registered identity,
explicit scopes, and governed inter-agent communication rules.

Agent status, scopes, and high-stakes actions are persisted to disk so the
Streamlit dashboard and Slack bot share the same state. Changes in the
dashboard take effect immediately on the next Slack request.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from core.logger import log_permission_check, log_inter_agent, log_audit


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
# Default Agent Registry — the baseline configuration
# ============================================================

DEFAULT_AGENT_REGISTRY: dict[str, dict] = {
    "gmail_agent": {
        "name": "gmail_agent",
        "description": "Reads and sends emails via Gmail",
        "oauth_provider": "google",
        "permitted_scopes": ["gmail.readonly", "gmail.send"],
        "high_stakes_actions": ["send_email"],
    },
    "drive_agent": {
        "name": "drive_agent",
        "description": "Reads and manages files in Google Drive",
        "oauth_provider": "google",
        "permitted_scopes": ["drive.readonly", "drive.file"],
        "high_stakes_actions": ["delete_file"],
    },
    "calendar_agent": {
        "name": "calendar_agent",
        "description": "Reads and manages Google Calendar events",
        "oauth_provider": "google",
        "permitted_scopes": ["calendar.events.readonly", "calendar.events"],
        "high_stakes_actions": ["create_event"],
    },
    "github_agent": {
        "name": "github_agent",
        "description": "Reads repos and manages GitHub issues",
        "oauth_provider": "github",
        "permitted_scopes": ["repo", "read:user"],
        "high_stakes_actions": ["create_comment"],
    },
}

# All possible scopes per provider that can be toggled on/off
AVAILABLE_SCOPES = {
    "gmail_agent": ["gmail.readonly", "gmail.send"],
    "drive_agent": ["drive.readonly", "drive.file"],
    "calendar_agent": ["calendar.events.readonly", "calendar.events"],
    "github_agent": ["repo", "read:user"],
}

# All possible high-stakes actions per agent that can be toggled
AVAILABLE_HIGH_STAKES = {
    "gmail_agent": ["send_email", "list_emails", "search_emails", "read_email"],
    "drive_agent": ["delete_file", "list_files", "search_files"],
    "calendar_agent": ["create_event", "list_events"],
    "github_agent": ["create_comment", "list_repos", "list_issues"],
}

# ============================================================
# In-memory Agent Registry — built from defaults + overrides
# ============================================================

AGENT_REGISTRY: dict[str, AgentIdentity] = {}


def _build_registry():
    """Build the in-memory registry from defaults."""
    global AGENT_REGISTRY
    for name, config in DEFAULT_AGENT_REGISTRY.items():
        AGENT_REGISTRY[name] = AgentIdentity(
            name=config["name"],
            description=config["description"],
            oauth_provider=config["oauth_provider"],
            permitted_scopes=list(config["permitted_scopes"]),
            high_stakes_actions=list(config["high_stakes_actions"]),
        )


_build_registry()

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

# ============================================================
# Persistence
# ============================================================

CONFIG_DIR = Path(__file__).parent.parent / "config"
STATUS_FILE = CONFIG_DIR / "agent_status.json"
SCOPES_FILE = CONFIG_DIR / "agent_scopes.json"
HIGH_STAKES_FILE = CONFIG_DIR / "agent_high_stakes.json"


def _load_json(filepath: Path) -> dict:
    if filepath.exists():
        try:
            return json.loads(filepath.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {}


def _save_json(filepath: Path, data: dict):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(data, indent=2))


def _apply_all_overrides():
    """Apply all persisted overrides to the in-memory registry."""
    # Status overrides
    status_overrides = _load_json(STATUS_FILE)
    for name, status_str in status_overrides.items():
        if name in AGENT_REGISTRY:
            try:
                AGENT_REGISTRY[name].status = AgentStatus(status_str)
            except ValueError:
                pass

    # Scope overrides
    scope_overrides = _load_json(SCOPES_FILE)
    for name, scopes in scope_overrides.items():
        if name in AGENT_REGISTRY:
            AGENT_REGISTRY[name].permitted_scopes = list(scopes)

    # High-stakes overrides
    hs_overrides = _load_json(HIGH_STAKES_FILE)
    for name, actions in hs_overrides.items():
        if name in AGENT_REGISTRY:
            AGENT_REGISTRY[name].high_stakes_actions = list(actions)


# Apply on import
_apply_all_overrides()


# ============================================================
# Public API — Status
# ============================================================


def get_agent(name: str) -> Optional[AgentIdentity]:
    """Get an agent's identity from the registry."""
    _apply_all_overrides()
    return AGENT_REGISTRY.get(name)


def is_agent_active(name: str) -> bool:
    """Check if an agent is active."""
    agent = get_agent(name)
    return agent is not None and agent.status == AgentStatus.ACTIVE


def suspend_agent(agent_name: str) -> bool:
    """Suspend an agent — takes effect immediately on next request in ALL processes."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    agent.status = AgentStatus.SUSPENDED
    overrides = _load_json(STATUS_FILE)
    overrides[agent_name] = AgentStatus.SUSPENDED.value
    _save_json(STATUS_FILE, overrides)
    log_audit(
        "admin_action", agent_name, "suspend", "success", {"new_status": "suspended"}
    )
    return True


def activate_agent(agent_name: str) -> bool:
    """Reactivate a suspended agent — takes effect immediately in ALL processes."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    agent.status = AgentStatus.ACTIVE
    overrides = _load_json(STATUS_FILE)
    overrides[agent_name] = AgentStatus.ACTIVE.value
    _save_json(STATUS_FILE, overrides)
    log_audit(
        "admin_action", agent_name, "activate", "success", {"new_status": "active"}
    )
    return True


# ============================================================
# Public API — Scopes
# ============================================================


def get_available_scopes(agent_name: str) -> list[str]:
    """Get all possible scopes for an agent."""
    return AVAILABLE_SCOPES.get(agent_name, [])


def add_scope(agent_name: str, scope: str) -> bool:
    """Add a scope to an agent's permitted scopes."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    available = AVAILABLE_SCOPES.get(agent_name, [])
    if scope not in available:
        return False
    if scope not in agent.permitted_scopes:
        agent.permitted_scopes.append(scope)
    # Persist
    overrides = _load_json(SCOPES_FILE)
    overrides[agent_name] = list(agent.permitted_scopes)
    _save_json(SCOPES_FILE, overrides)
    log_audit("admin_action", agent_name, "add_scope", "success", {"scope": scope})
    return True


def remove_scope(agent_name: str, scope: str) -> bool:
    """Remove a scope from an agent's permitted scopes."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    if scope in agent.permitted_scopes:
        agent.permitted_scopes.remove(scope)
    # Persist
    overrides = _load_json(SCOPES_FILE)
    overrides[agent_name] = list(agent.permitted_scopes)
    _save_json(SCOPES_FILE, overrides)
    log_audit("admin_action", agent_name, "remove_scope", "success", {"scope": scope})
    return True


def update_scopes(agent_name: str, new_scopes: list[str]) -> bool:
    """Replace an agent's scopes entirely."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    available = AVAILABLE_SCOPES.get(agent_name, [])
    valid_scopes = [s for s in new_scopes if s in available]
    agent.permitted_scopes = valid_scopes
    # Persist
    overrides = _load_json(SCOPES_FILE)
    overrides[agent_name] = valid_scopes
    _save_json(SCOPES_FILE, overrides)
    log_audit(
        "admin_action", agent_name, "update_scopes", "success", {"scopes": valid_scopes}
    )
    return True


# ============================================================
# Public API — High-Stakes Actions
# ============================================================


def get_available_high_stakes(agent_name: str) -> list[str]:
    """Get all possible high-stakes actions for an agent."""
    return AVAILABLE_HIGH_STAKES.get(agent_name, [])


def update_high_stakes(agent_name: str, new_actions: list[str]) -> bool:
    """Replace an agent's high-stakes actions entirely."""
    agent = AGENT_REGISTRY.get(agent_name)
    if agent is None:
        return False
    available = AVAILABLE_HIGH_STAKES.get(agent_name, [])
    valid_actions = [a for a in new_actions if a in available]
    agent.high_stakes_actions = valid_actions
    # Persist
    overrides = _load_json(HIGH_STAKES_FILE)
    overrides[agent_name] = valid_actions
    _save_json(HIGH_STAKES_FILE, overrides)
    log_audit(
        "admin_action",
        agent_name,
        "update_high_stakes",
        "success",
        {"actions": valid_actions},
    )
    return True


# ============================================================
# Public API — Permission Checks
# ============================================================


def check_scope_permission(agent_name: str, requested_scope: str) -> bool:
    """Check if an agent has permission for a specific scope."""
    agent = get_agent(agent_name)
    if agent is None:
        log_permission_check(agent_name, requested_scope, False, "agent not found")
        return False

    if agent.status != AgentStatus.ACTIVE:
        log_permission_check(
            agent_name, requested_scope, False, f"agent status: {agent.status}"
        )
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


def check_inter_agent_permission(
    requesting_agent: str, target_agent: str, action: str
) -> bool:
    """Check if one agent is allowed to communicate with another."""
    agent_permissions = INTER_AGENT_PERMISSIONS.get(requesting_agent, {})
    allowed_actions = agent_permissions.get(target_agent, [])
    allowed = action in allowed_actions
    log_inter_agent(requesting_agent, target_agent, action, allowed)
    return allowed


# ============================================================
# Public API — Registry Access
# ============================================================


def get_all_agents() -> dict[str, AgentIdentity]:
    """Return the full agent registry with current state."""
    _apply_all_overrides()
    return AGENT_REGISTRY.copy()


def get_permission_matrix() -> dict:
    """Return the full inter-agent permission matrix."""
    return INTER_AGENT_PERMISSIONS.copy()
