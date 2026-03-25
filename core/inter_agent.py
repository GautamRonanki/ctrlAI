"""
ctrlAI - Inter-Agent Communication Engine
==========================================
Handles agent-to-agent requests with full permission matrix enforcement.
Every inter-agent request is checked, logged, and either allowed or blocked.

This is the core differentiator of ctrlAI - no other product governs
what agents can request from each other at this level.
"""

import os
import json
from loguru import logger

from core.permissions import (
    check_inter_agent_permission,
    is_agent_active,
    get_all_agents,
    get_permission_matrix,
    is_high_stakes,
)
from core.token_service import get_google_token, get_github_token
from core.ciba_service import request_and_wait_for_approval
from core.logger import log_audit


# ============================================================
# Supported Inter-Agent Actions
# These define what actually happens when an inter-agent request is allowed.
# ============================================================

INTER_AGENT_ACTION_MAP = {
    ("gmail_agent", "drive_agent", "store_attachment"): {
        "description": "Gmail agent stores an email attachment to Google Drive",
        "requires_token": "google",
    },
    ("gmail_agent", "calendar_agent", "check_availability"): {
        "description": "Gmail agent checks calendar availability before suggesting meeting times",
        "requires_token": "google",
    },
    ("calendar_agent", "gmail_agent", "read_email_context"): {
        "description": "Calendar agent reads related emails for meeting context",
        "requires_token": "google",
    },
    ("github_agent", "gmail_agent", "read_email_context"): {
        "description": "GitHub agent reads emails related to a repository or issue",
        "requires_token": "google",
    },
}


async def execute_inter_agent_request(
    requesting_agent: str,
    target_agent: str,
    action: str,
    refresh_token: str = "",
    params: dict = None,
) -> dict:
    """
    Execute an inter-agent request with full permission enforcement.

    Returns:
        {
            "status": "allowed" | "denied" | "error",
            "requesting_agent": str,
            "target_agent": str,
            "action": str,
            "reason": str,
            "result": dict | None  (if allowed and executed)
        }
    """
    params = params or {}

    # Step 1: Check if both agents exist and are active
    if not is_agent_active(requesting_agent):
        log_audit(
            "inter_agent",
            requesting_agent,
            f"request:{target_agent}:{action}",
            "denied",
            {"reason": "requesting agent not active"},
        )
        return {
            "status": "denied",
            "requesting_agent": requesting_agent,
            "target_agent": target_agent,
            "action": action,
            "reason": f"{requesting_agent} is not active",
            "result": None,
        }

    if not is_agent_active(target_agent):
        log_audit(
            "inter_agent",
            requesting_agent,
            f"request:{target_agent}:{action}",
            "denied",
            {"reason": "target agent not active"},
        )
        return {
            "status": "denied",
            "requesting_agent": requesting_agent,
            "target_agent": target_agent,
            "action": action,
            "reason": f"{target_agent} is not active - cannot receive requests",
            "result": None,
        }

    # Step 2: Check the inter-agent permission matrix
    allowed = check_inter_agent_permission(requesting_agent, target_agent, action)

    if not allowed:
        return {
            "status": "denied",
            "requesting_agent": requesting_agent,
            "target_agent": target_agent,
            "action": action,
            "reason": f"Permission matrix does not allow {requesting_agent} to request '{action}' from {target_agent}",
            "result": None,
        }

    # Step 3: Permission granted - log and execute
    log_audit(
        "inter_agent_execution",
        requesting_agent,
        f"{target_agent}:{action}",
        "executing",
        {"params": params},
    )

    # For the hackathon demo, we simulate the inter-agent action
    # In production, this would actually call the target agent's function
    action_key = (requesting_agent, target_agent, action)
    action_info = INTER_AGENT_ACTION_MAP.get(action_key, {})

    result = {
        "status": "allowed",
        "requesting_agent": requesting_agent,
        "target_agent": target_agent,
        "action": action,
        "reason": "Permission granted by inter-agent matrix",
        "description": action_info.get("description", f"{action} executed"),
        "result": {"executed": True, "action": action, "params": params},
    }

    log_audit(
        "inter_agent_execution",
        requesting_agent,
        f"{target_agent}:{action}",
        "success",
        {"result": "executed"},
    )

    return result


def format_inter_agent_result(result: dict) -> str:
    """Format an inter-agent result into a human-readable Slack message."""
    status = result["status"]
    req = result["requesting_agent"].replace("_", " ").title()
    tgt = result["target_agent"].replace("_", " ").title()
    action = result["action"].replace("_", " ")

    if status == "allowed":
        return (
            f"✅ *Inter-agent request ALLOWED*\n"
            f"• {req} → {tgt}: `{action}`\n"
            f"• {result.get('description', 'Action executed')}\n"
            f"• Logged to audit trail"
        )
    else:
        return (
            f"🚫 *Inter-agent request DENIED*\n"
            f"• {req} → {tgt}: `{action}`\n"
            f"• Reason: {result['reason']}\n"
            f"• Violation logged to audit trail"
        )


def get_demo_scenarios() -> list[dict]:
    """
    Return a list of demo scenarios for inter-agent communication.
    Includes both allowed and denied cases for the demo.
    """
    return [
        {
            "label": "✅ Gmail → Drive: store attachment",
            "requesting_agent": "gmail_agent",
            "target_agent": "drive_agent",
            "action": "store_attachment",
            "expected": "allowed",
        },
        {
            "label": "✅ Gmail → Calendar: check availability",
            "requesting_agent": "gmail_agent",
            "target_agent": "calendar_agent",
            "action": "check_availability",
            "expected": "allowed",
        },
        {
            "label": "✅ Calendar → Gmail: read email context",
            "requesting_agent": "calendar_agent",
            "target_agent": "gmail_agent",
            "action": "read_email_context",
            "expected": "allowed",
        },
        {
            "label": "✅ GitHub → Gmail: read email context",
            "requesting_agent": "github_agent",
            "target_agent": "gmail_agent",
            "action": "read_email_context",
            "expected": "allowed",
        },
        {
            "label": "🚫 Gmail → Drive: delete file (NOT ALLOWED)",
            "requesting_agent": "gmail_agent",
            "target_agent": "drive_agent",
            "action": "delete_file",
            "expected": "denied",
        },
        {
            "label": "🚫 Drive → Gmail: send email (NOT ALLOWED)",
            "requesting_agent": "drive_agent",
            "target_agent": "gmail_agent",
            "action": "send_email",
            "expected": "denied",
        },
        {
            "label": "🚫 GitHub → Calendar: create event (NOT ALLOWED)",
            "requesting_agent": "github_agent",
            "target_agent": "calendar_agent",
            "action": "create_event",
            "expected": "denied",
        },
        {
            "label": "🚫 Calendar → GitHub: create comment (NOT ALLOWED)",
            "requesting_agent": "calendar_agent",
            "target_agent": "github_agent",
            "action": "create_comment",
            "expected": "denied",
        },
    ]
