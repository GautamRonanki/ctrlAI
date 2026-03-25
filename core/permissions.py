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

from dotenv import load_dotenv

load_dotenv()

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
# Default Agent Registry - the baseline configuration
# ============================================================

DEFAULT_AGENT_REGISTRY: dict[str, dict] = {
    "gmail_agent": {
        "name": "gmail_agent",
        "description": "Manages your Gmail inbox - reading, composing, and organizing emails on your behalf",
        "oauth_provider": "google",
        "permitted_scopes": [
            "read_emails",
            "send_emails",
            "list_emails",
            "search_emails",
        ],
        "high_stakes_actions": ["send_emails"],
    },
    "drive_agent": {
        "name": "drive_agent",
        "description": "Manages your Google Drive - accessing, organizing, and maintaining your files and documents",
        "oauth_provider": "google",
        "permitted_scopes": [
            "list_files",
            "read_files",
            "create_files",
            "delete_files",
            "search_files",
        ],
        "high_stakes_actions": ["delete_files"],
    },
    "calendar_agent": {
        "name": "calendar_agent",
        "description": "Manages your Google Calendar - viewing your schedule and coordinating events on your behalf",
        "oauth_provider": "google",
        "permitted_scopes": [
            "list_events",
            "read_events",
            "create_events",
            "modify_events",
        ],
        "high_stakes_actions": ["create_events"],
    },
    "github_agent": {
        "name": "github_agent",
        "description": "Manages your GitHub workflow - monitoring repositories, issues, and code activity",
        "oauth_provider": "github",
        "permitted_scopes": [
            "list_repos",
            "read_repos",
            "list_issues",
            "read_issues",
            "post_comments",
        ],
        "high_stakes_actions": ["post_comments"],
    },
    "security_report_agent": {
        "name": "security_report_agent",
        "description": "Autonomous security monitor - analyzes agent activity and alerts administrators on policy violations",
        "oauth_provider": "internal",
        "permitted_scopes": ["read_audit_trail", "generate_reports"],
        "high_stakes_actions": [],
    },
    "stale_issue_monitor": {
        "name": "stale_issue_monitor",
        "description": "Autonomous GitHub monitor - identifies inactive issues and keeps your project board healthy",
        "oauth_provider": "github",
        "permitted_scopes": [
            "read_repos",
            "read_issues",
            "post_comments",
            "add_labels",
        ],
        "high_stakes_actions": ["post_comments", "add_labels"],
    },
}
# All possible scopes per provider that can be toggled on/off
AVAILABLE_SCOPES = {
    "gmail_agent": ["read_emails", "send_emails", "list_emails", "search_emails"],
    "drive_agent": [
        "list_files",
        "read_files",
        "create_files",
        "delete_files",
        "search_files",
    ],
    "calendar_agent": ["list_events", "read_events", "create_events", "modify_events"],
    "github_agent": [
        "list_repos",
        "read_repos",
        "list_issues",
        "read_issues",
        "post_comments",
    ],
    "security_report_agent": ["read_audit_trail", "generate_reports"],
    "stale_issue_monitor": ["read_repos", "read_issues", "post_comments", "add_labels"],
}

# All possible high-stakes actions per agent that can be toggled
AVAILABLE_HIGH_STAKES = {
    "gmail_agent": ["send_emails", "list_emails", "search_emails", "read_emails"],
    "drive_agent": [
        "delete_files",
        "list_files",
        "search_files",
        "read_files",
        "create_files",
    ],
    "calendar_agent": ["create_events", "modify_events", "list_events", "read_events"],
    "github_agent": [
        "post_comments",
        "list_repos",
        "list_issues",
        "read_repos",
        "read_issues",
    ],
    "security_report_agent": ["send_alert_emails", "generate_reports"],
    "stale_issue_monitor": ["post_comments", "add_labels"],
}

# ============================================================
# In-memory Agent Registry - built from defaults + overrides
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
    "security_report_agent": {
        "gmail_agent": ["send_alert_email"],
    },
}

# ============================================================
# Persistence
# ============================================================

CONFIG_DIR = Path(__file__).parent.parent / "config"
STATUS_FILE = CONFIG_DIR / "agent_status.json"
SCOPES_FILE = CONFIG_DIR / "agent_scopes.json"
HIGH_STAKES_FILE = CONFIG_DIR / "agent_high_stakes.json"
INTER_AGENT_FILE = CONFIG_DIR / "inter_agent_matrix.json"


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
# Rate Limiting - Active Protection
# ============================================================

import time as _time

# Max requests per agent per window
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW_SECONDS = 60

# In-memory request tracker: {agent_name: [timestamp, timestamp, ...]}
_agent_request_log: dict[str, list[float]] = {}
# Track which agents have already sent a rate limit alert in the current window
_rate_limit_alerted: dict[str, float] = {}

RATE_LIMIT_FILE = CONFIG_DIR / "rate_limits.json"


def _check_rate_limit(agent_name: str) -> bool:
    """
    Check if an agent has exceeded its rate limit.
    Returns True if the request is ALLOWED, False if RATE LIMITED.
    Automatically cleans up old entries outside the window.
    """
    now = _time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    # Get or create the request log for this agent
    if agent_name not in _agent_request_log:
        _agent_request_log[agent_name] = []

    # Clean up old entries outside the window
    _agent_request_log[agent_name] = [
        t for t in _agent_request_log[agent_name] if t > window_start
    ]

    # Check if limit exceeded
    if len(_agent_request_log[agent_name]) >= RATE_LIMIT_MAX:
        return False

    # Record this request
    _agent_request_log[agent_name].append(now)
    return True


def get_rate_limit_status(agent_name: str) -> dict:
    """Get current rate limit status for an agent."""
    now = _time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    if agent_name not in _agent_request_log:
        return {
            "requests_in_window": 0,
            "limit": RATE_LIMIT_MAX,
            "remaining": RATE_LIMIT_MAX,
        }

    recent = [t for t in _agent_request_log[agent_name] if t > window_start]
    return {
        "requests_in_window": len(recent),
        "limit": RATE_LIMIT_MAX,
        "remaining": max(0, RATE_LIMIT_MAX - len(recent)),
    }


# ============================================================
# Public API - Status
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
    """Suspend an agent - takes effect immediately on next request in ALL processes."""
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
    """Reactivate a suspended agent - takes effect immediately in ALL processes."""
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
# Public API - Scopes
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
# Public API - High-Stakes Actions
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
# Public API - Permission Checks
# ============================================================


def check_scope_permission(
    agent_name: str, requested_scope: str, _system_bypass_rate_limit: bool = False
) -> bool:
    """Check if an agent has permission for a specific scope.
    Enforces: agent exists → agent active → rate limit → scope check.
    """
    agent = get_agent(agent_name)
    if agent is None:
        log_permission_check(agent_name, requested_scope, False, "agent not found")
        return False

    if agent.status != AgentStatus.ACTIVE:
        log_permission_check(
            agent_name, requested_scope, False, f"agent status: {agent.status}"
        )
        return False

    # Rate limit check - before scope check (system alerts can bypass)
    if not _system_bypass_rate_limit and not _check_rate_limit(agent_name):
        log_permission_check(
            agent_name,
            requested_scope,
            False,
            f"rate limit exceeded: {RATE_LIMIT_MAX} requests per {RATE_LIMIT_WINDOW_SECONDS}s",
        )
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_exceeded",
            "denied",
            {
                "scope": requested_scope,
                "limit": RATE_LIMIT_MAX,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
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
    matrix = get_permission_matrix()
    agent_permissions = matrix.get(requesting_agent, {})
    allowed_actions = agent_permissions.get(target_agent, [])
    allowed = action in allowed_actions
    log_inter_agent(requesting_agent, target_agent, action, allowed)
    return allowed


# ============================================================
# Public API - Registry Access
# ============================================================


def get_all_agents() -> dict[str, AgentIdentity]:
    """Return the full agent registry with current state."""
    _apply_all_overrides()
    return AGENT_REGISTRY.copy()


def get_permission_matrix() -> dict:
    """Return the full inter-agent permission matrix (with persisted overrides)."""
    overrides = _load_json(INTER_AGENT_FILE)
    if overrides:
        return overrides
    return {
        k: {t: list(a) for t, a in v.items()}
        for k, v in INTER_AGENT_PERMISSIONS.items()
    }


def update_inter_agent_permission(
    requesting_agent: str, target_agent: str, actions: list[str]
):
    """Update the allowed actions between two agents. Persists to disk."""
    matrix = get_permission_matrix()
    if not actions:
        # Remove the relationship
        if requesting_agent in matrix and target_agent in matrix[requesting_agent]:
            del matrix[requesting_agent][target_agent]
            if not matrix[requesting_agent]:
                del matrix[requesting_agent]
    else:
        if requesting_agent not in matrix:
            matrix[requesting_agent] = {}
        matrix[requesting_agent][target_agent] = actions
    _save_json(INTER_AGENT_FILE, matrix)
    log_audit(
        "admin_action",
        requesting_agent,
        f"update_inter_agent:{target_agent}",
        "success",
        {"actions": actions},
    )


def get_all_inter_agent_actions() -> list[str]:
    """Return all possible inter-agent action names."""
    return [
        "store_attachment",
        "check_availability",
        "read_email_context",
        "send_alert_email",
        "send_email",
        "delete_file",
        "create_event",
    ]


async def send_rate_limit_alert(agent_name: str, limit: int, window: int):
    """Send an email alert when an agent exceeds its rate limit.
    Uses the inter-agent permission matrix - routes through Gmail Agent."""
    import os

    # Check inter-agent permission (security_report_agent → gmail_agent)
    if not check_inter_agent_permission(
        "security_report_agent", "gmail_agent", "send_alert_email"
    ):
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_blocked",
            "denied",
            {"reason": "inter-agent permission denied for email alert"},
        )
        return

    admin_email = os.getenv("ADMIN_ALERT_EMAIL", "")
    if not admin_email:
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": "no ADMIN_ALERT_EMAIL configured"},
        )
        return

    # Get Gmail token
    refresh_token = None
    token_store_path = CONFIG_DIR / "token_store.json"
    if not token_store_path.exists():
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": "token_store.json not found"},
        )
        return

    try:
        token_data = json.loads(token_store_path.read_text())
        refresh_token = token_data.get("refresh_token", "")
    except (json.JSONDecodeError, Exception):
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": "failed to read token_store.json"},
        )
        return

    if not refresh_token:
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": "no refresh token"},
        )
        return

    from core.token_service import get_google_token

    gmail_token = await get_google_token(refresh_token)
    if not gmail_token:
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": "Token Vault exchange failed"},
        )
        return

    import httpx
    import base64
    from email.mime.text import MIMEText

    alert_body = (
        f"⚠️ ctrlAI Rate Limit Alert\n\n"
        f"Agent: {agent_name}\n"
        f"Exceeded: {limit} requests in {window} seconds\n"
        f"Action: Requests from this agent are being throttled.\n\n"
        f"Review the audit log in the ctrlAI dashboard for details.\n"
        f"If this is unexpected, consider suspending the agent immediately."
    )

    msg = MIMEText(alert_body)
    msg["to"] = admin_email
    msg["subject"] = f"⚠️ ctrlAI Rate Limit Alert - {agent_name}"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {gmail_token}"},
            json={"raw": raw},
        )

    if response.status_code == 200:
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_sent",
            "success",
            {"admin_email": admin_email, "limit": limit, "window": window},
        )
    else:
        log_audit(
            "security_alert",
            agent_name,
            "rate_limit_alert_failed",
            "error",
            {"reason": f"Gmail API returned {response.status_code}"},
        )
