"""
Security Report Agent — Autonomous agent for ctrlAI.
Autonomous security monitor — analyzes agent activity and alerts administrators on policy violations.
This agent runs autonomously — no employee triggers it.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.llm import get_llm, call_llm
from core.logger import log_audit, AUDIT_LOG_PATH
from core.permissions import (
    check_scope_permission,
    is_agent_active,
    check_inter_agent_permission,
)


def _load_recent_audit_entries(hours: int = 24) -> list[dict]:
    """Load audit entries from the last N hours."""
    if not AUDIT_LOG_PATH.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    entries = []

    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)
                    entry_time = datetime.fromisoformat(entry["timestamp"])
                    if entry_time >= cutoff:
                        entries.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
    return entries


def _analyze_entries(entries: list[dict]) -> dict:
    """Analyze audit entries for security-relevant patterns."""
    total = len(entries)
    denied = [e for e in entries if e.get("status") == "denied"]
    ciba_events = [e for e in entries if e.get("event_type") == "ciba"]
    inter_agent_denied = [
        e
        for e in entries
        if e.get("event_type") in ("inter_agent", "inter_agent_request")
        and e.get("status") == "denied"
    ]
    permission_violations = [
        e
        for e in entries
        if e.get("event_type") == "permission_check" and e.get("status") == "denied"
    ]
    errors = [e for e in entries if e.get("status") == "error"]

    has_critical = len(denied) > 0 or len(inter_agent_denied) > 0 or len(errors) > 0

    return {
        "total_events": total,
        "denied_count": len(denied),
        "denied_entries": denied,
        "ciba_count": len(ciba_events),
        "ciba_entries": ciba_events,
        "inter_agent_denied_count": len(inter_agent_denied),
        "inter_agent_denied_entries": inter_agent_denied,
        "permission_violations_count": len(permission_violations),
        "permission_violation_entries": permission_violations,
        "error_count": len(errors),
        "error_entries": errors,
        "has_critical": has_critical,
    }


async def generate_security_report() -> dict:
    """Generate a security report from the audit trail."""

    if not is_agent_active("security_report_agent"):
        log_audit(
            "agent_execution",
            "security_report_agent",
            "generate_reports",
            "denied",
            {"reason": "agent suspended"},
        )
        return {
            "status": "blocked",
            "reason": "Security Report Agent is currently suspended by the administrator.",
        }

    if not check_scope_permission("security_report_agent", "read_audit_trail"):
        return {
            "status": "blocked",
            "reason": "Security Report Agent does not have the 'read_audit_trail' scope.",
        }

    if not check_scope_permission("security_report_agent", "generate_reports"):
        return {
            "status": "blocked",
            "reason": "Security Report Agent does not have the 'generate_reports' scope.",
        }

    log_audit(
        "agent_execution", "security_report_agent", "generate_reports", "started", {}
    )

    entries = _load_recent_audit_entries(hours=24)

    if not entries:
        log_audit(
            "agent_execution",
            "security_report_agent",
            "generate_reports",
            "success",
            {"result": "no_entries"},
        )
        return {
            "status": "success",
            "report": "No audit activity in the last 24 hours. Nothing to report.",
            "has_critical": False,
            "analysis": {"total_events": 0},
        }

    analysis = _analyze_entries(entries)

    llm = get_llm()

    analysis_str = json.dumps(
        {
            "total_events": analysis["total_events"],
            "denied_count": analysis["denied_count"],
            "denied_details": [
                {
                    "agent": e["agent_name"],
                    "action": e["action"],
                    "time": e["timestamp"][:19],
                }
                for e in analysis["denied_entries"][:10]
            ],
            "ciba_count": analysis["ciba_count"],
            "ciba_details": [
                {
                    "agent": e["agent_name"],
                    "action": e["action"],
                    "status": e["status"],
                    "time": e["timestamp"][:19],
                }
                for e in analysis["ciba_entries"][:10]
            ],
            "inter_agent_denied_count": analysis["inter_agent_denied_count"],
            "inter_agent_denied_details": [
                {
                    "agent": e["agent_name"],
                    "action": e["action"],
                    "time": e["timestamp"][:19],
                }
                for e in analysis["inter_agent_denied_entries"][:10]
            ],
            "permission_violations_count": analysis["permission_violations_count"],
            "error_count": analysis["error_count"],
        },
        indent=2,
    )

    report_prompt = f"""You are the ctrlAI Security Report Agent. Analyze this audit data and generate a concise security report.

Audit Data (last 24 hours):
{analysis_str}

Generate a security report with:
1. A one-line overall status (e.g., "All clear" or "Attention needed — 3 permission violations detected")
2. Key metrics summary (total events, denials, CIBA approvals, inter-agent violations)
3. If there are any denied actions or violations, explain what happened and which agents were involved
4. A risk assessment: Low / Medium / High based on the findings
5. Recommendations if any issues were found

Keep it concise and professional. Use Slack formatting: *single asterisks* for bold, • for lists."""

    try:
        response = await call_llm(
            llm,
            [{"role": "user", "content": report_prompt}],
            label="security_report_generator",
        )
        report_text = response.content.strip()
    except Exception as e:
        report_text = (
            f"*Security Report — Auto-generated*\n\n"
            f"• Total events: {analysis['total_events']}\n"
            f"• Denied actions: {analysis['denied_count']}\n"
            f"• CIBA events: {analysis['ciba_count']}\n"
            f"• Inter-agent violations: {analysis['inter_agent_denied_count']}\n"
            f"• Errors: {analysis['error_count']}\n\n"
            f"_LLM summary unavailable: {str(e)}_"
        )

    log_audit(
        "agent_execution",
        "security_report_agent",
        "generate_reports",
        "success",
        {
            "total_events": analysis["total_events"],
            "denied": analysis["denied_count"],
            "has_critical": analysis["has_critical"],
        },
    )

    return {
        "status": "success",
        "report": report_text,
        "has_critical": analysis["has_critical"],
        "analysis": analysis,
    }


async def send_alert_email(report: str, gmail_token: str) -> dict:
    """Send a security alert email via the Gmail Agent. Requires inter-agent permission."""

    if not check_inter_agent_permission(
        "security_report_agent", "gmail_agent", "send_alert_email"
    ):
        return {
            "status": "blocked",
            "reason": "Security Report Agent is not permitted to send emails through Gmail Agent.",
        }

    from agents.gmail_agent import send_email

    admin_email = os.getenv("ADMIN_ALERT_EMAIL", "")
    if not admin_email:
        return {
            "status": "error",
            "reason": "No admin email configured. Set ADMIN_ALERT_EMAIL in .env",
        }

    result = await send_email(
        google_token=gmail_token,
        to=admin_email,
        subject="⚠️ ctrlAI Security Alert — Action Required",
        body=report,
        agent_name="gmail_agent",
    )

    log_audit(
        "inter_agent_execution",
        "security_report_agent",
        "send_alert_emails",
        "success" if "error" not in result else "error",
        {"target_agent": "gmail_agent", "admin_email": admin_email},
    )

    return result
