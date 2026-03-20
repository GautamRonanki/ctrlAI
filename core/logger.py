"""
Centralized logging for ctrlAI.
Every agent action, permission check, and CIBA event is logged here.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# File logging - all events
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.add(
    LOG_DIR / "ctrlai.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{function}:{line} | {message}",
)

# Audit log - structured JSON lines for dashboard consumption
AUDIT_LOG_PATH = LOG_DIR / "audit.jsonl"


def log_audit(
    event_type: str,
    agent_name: str,
    action: str,
    status: str,
    details: dict | None = None,
    user_id: str | None = None,
):
    """Write a structured audit log entry. Every agent action flows through here."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "agent_name": agent_name,
        "action": action,
        "status": status,
        "user_id": user_id,
        "details": details or {},
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    logger.info(f"AUDIT | {event_type} | {agent_name} | {action} | {status}")
    return entry


def log_permission_check(agent_name: str, requested_action: str, allowed: bool, reason: str = ""):
    """Log a permission check result."""
    return log_audit(
        event_type="permission_check",
        agent_name=agent_name,
        action=requested_action,
        status="allowed" if allowed else "denied",
        details={"reason": reason},
    )


def log_ciba_event(agent_name: str, action: str, status: str, details: dict | None = None):
    """Log a CIBA approval flow event."""
    return log_audit(
        event_type="ciba",
        agent_name=agent_name,
        action=action,
        status=status,
        details=details,
    )


def log_api_call(agent_name: str, service: str, endpoint: str, status_code: int, latency_ms: float):
    """Log an external API call."""
    return log_audit(
        event_type="api_call",
        agent_name=agent_name,
        action=f"{service}:{endpoint}",
        status="success" if 200 <= status_code < 300 else "error",
        details={"status_code": status_code, "latency_ms": round(latency_ms, 2)},
    )


def log_inter_agent(requesting_agent: str, target_agent: str, action: str, allowed: bool):
    """Log an inter-agent communication attempt."""
    return log_audit(
        event_type="inter_agent",
        agent_name=requesting_agent,
        action=f"request:{target_agent}:{action}",
        status="allowed" if allowed else "denied",
    )
