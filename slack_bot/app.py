"""
ctrlAI Slack Bot — Employee-facing interface.
Now powered by the LangGraph Master Orchestrator.
Employees message the bot in natural language. The orchestrator handles routing,
permissions, CIBA, and execution through the graph.

Inter-agent commands are handled via: "inter-agent: agent1 requests action from agent2"
Cross-agent workflows are triggered by natural language (e.g., "prepare for my next meeting")
Every interaction ends with a session summary showing what was accessed and why.
"""

import os
import json
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from core.logger import log_audit
from core.inter_agent import execute_inter_agent_request, format_inter_agent_result
from core.workflows import meeting_prep_workflow, format_workflow_result

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Slack app with Socket Mode
slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))

# ============================================================
# Refresh Token Persistence
# ============================================================

TOKEN_STORE_PATH = Path(__file__).parent.parent / "config" / "token_store.json"


def get_refresh_token() -> str:
    """Get the persisted refresh token."""
    if TOKEN_STORE_PATH.exists():
        try:
            data = json.loads(TOKEN_STORE_PATH.read_text())
            return data.get("refresh_token", "")
        except (json.JSONDecodeError, Exception):
            pass
    return os.getenv("AUTH0_REFRESH_TOKEN", "")


def save_refresh_token(refresh_token: str, user_email: str = ""):
    """Persist a refresh token (called by FastAPI after login)."""
    TOKEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"refresh_token": refresh_token, "user_email": user_email}
    TOKEN_STORE_PATH.write_text(json.dumps(data))
    logger.info(f"Refresh token persisted for {user_email}")


# ============================================================
# Async Helper
# ============================================================


def run_async(coro):
    """Run an async function from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def humanize(text: str) -> str:
    """Convert underscore_text to human readable."""
    return text.replace("_", " ").title()


def humanize_lower(text: str) -> str:
    """Convert underscore_text to human readable lowercase."""
    return text.replace("_", " ")


# ============================================================
# Session Summary Builder
# ============================================================


def build_session_summary(
    steps: list,
    agent: str = "",
    action: str = "",
    ciba_status: str = None,
    source: str = "orchestrator",
) -> str:
    """
    Build a human-readable session summary from execution steps.
    This is the transparency layer — the user sees exactly what happened.
    """
    lines = []
    lines.append("🔒 *Session Summary — What ctrlAI accessed on your behalf:*")
    lines.append("")

    # Services accessed
    services_accessed = set()
    permissions_checked = []
    permissions_denied = []
    ciba_events = []
    inter_agent_events = []

    for step in steps:
        node = step.get("node") or step.get("step", "")
        status = step.get("status", "")

        if "agent" in step:
            agent_name = step["agent"]
            if agent_name and agent_name != "none":
                # Map agent to service
                service_map = {
                    "gmail_agent": "Gmail",
                    "calendar_agent": "Google Calendar",
                    "drive_agent": "Google Drive",
                    "github_agent": "GitHub",
                }
                service = service_map.get(agent_name, agent_name)
                services_accessed.add(service)

        if node == "permission_gate":
            if status == "allowed":
                permissions_checked.append(
                    f"✅ {humanize(step.get('agent', '?'))}: {humanize_lower(step.get('scope', step.get('action', '?')))} — allowed"
                )
            elif status in ("denied", "agent_suspended", "permission_denied"):
                permissions_denied.append(
                    f"🚫 {humanize(step.get('agent', '?'))}: {status.replace('_', ' ')}"
                )

        if node == "ciba_checkpoint":
            if status == "approved":
                ciba_events.append(
                    "✅ Human approval granted via Guardian push notification"
                )
            elif status == "not_required":
                pass  # Don't show — not interesting
            elif status:
                ciba_events.append(f"🚫 Human approval {status}")

        # Inter-agent events from workflow steps
        if step.get("source", "").startswith("inter-agent"):
            inter_agent_events.append(
                f"🔗 {humanize(step.get('step', '?'))}: {status} ({step.get('source', '')})"
            )

    # Build the summary
    if services_accessed:
        lines.append(f"*Services accessed:* {', '.join(sorted(services_accessed))}")
    else:
        lines.append("*Services accessed:* None")

    if agent:
        lines.append(f"*Agent used:* {humanize(agent)}")
    if action:
        lines.append(f"*Action performed:* {humanize_lower(action)}")

    if permissions_checked:
        lines.append("")
        lines.append("*Permission checks:*")
        for p in permissions_checked:
            lines.append(f"  {p}")

    if permissions_denied:
        lines.append("")
        lines.append("*Permissions denied:*")
        for p in permissions_denied:
            lines.append(f"  {p}")

    if ciba_events:
        lines.append("")
        lines.append("*Human-in-the-loop (CIBA):*")
        for c in ciba_events:
            lines.append(f"  {c}")

    if inter_agent_events:
        lines.append("")
        lines.append("*Inter-agent communication:*")
        for ia in inter_agent_events:
            lines.append(f"  {ia}")

    lines.append("")
    lines.append(
        f"_Total steps: {len(steps)} | Full trace available in the admin dashboard_"
    )

    return "\n".join(lines)


def build_workflow_summary(result: dict) -> str:
    """Build a session summary specifically for cross-agent workflows."""
    lines = []
    lines.append("🔒 *Session Summary — What ctrlAI accessed on your behalf:*")
    lines.append("")

    # Services accessed
    steps = result.get("steps", [])
    services = set()
    for step in steps:
        step_name = step.get("step", "")
        if "gmail" in step_name:
            services.add("Gmail")
        elif "calendar" in step_name:
            services.add("Google Calendar")
        elif "drive" in step_name:
            services.add("Google Drive")
        elif "github" in step_name:
            services.add("GitHub")

    lines.append(
        f"*Services accessed:* {', '.join(sorted(services)) if services else 'None'}"
    )
    lines.append(f"*Workflow:* Meeting Preparation Briefing")

    # Inter-agent permissions
    ia_results = result.get("inter_agent_results", [])
    if ia_results:
        lines.append("")
        lines.append("*Inter-agent permissions enforced:*")
        for r in ia_results:
            icon = "✅" if r["status"] == "allowed" else "🚫"
            lines.append(
                f"  {icon} {r['requesting']} → {r['target']}: {r['action']} — {r['status']}"
            )

    # Step details
    lines.append("")
    lines.append("*Execution steps:*")
    for step in steps:
        step_name = humanize(step.get("step", "?"))
        status = step.get("status", "?")
        note = step.get("note", "")
        icon = "✅" if status == "success" else "🚫" if "denied" in status else "ℹ️"
        lines.append(f"  {icon} {step_name}: {status}")
        if note:
            lines.append(f"      _{note}_")

    lines.append("")
    lines.append(
        f"_Total steps: {len(steps)} | Full trace available in the admin dashboard_"
    )

    return "\n".join(lines)


# ============================================================
# Inter-Agent Command Handler
# ============================================================


def _handle_inter_agent(text: str, event: dict, say):
    """Handle explicit inter-agent communication requests."""
    try:
        parts = text.split(":", 1)[1].strip()
        tokens = parts.split()
        if "requests" in tokens and "from" in tokens:
            req_idx = tokens.index("requests")
            from_idx = tokens.index("from")
            requesting_agent = tokens[0]
            action = "_".join(tokens[req_idx + 1 : from_idx])
            target_agent = tokens[from_idx + 1]
        else:
            say(
                "Format: `inter-agent: gmail_agent requests store_attachment from drive_agent`"
            )
            return
    except (IndexError, ValueError):
        say(
            "Format: `inter-agent: gmail_agent requests store_attachment from drive_agent`"
        )
        return

    say(
        f"🔍 Checking inter-agent permission: `{requesting_agent}` → `{target_agent}`: `{action}`..."
    )

    log_audit(
        "inter_agent_request",
        requesting_agent,
        f"{target_agent}:{action}",
        "checking",
        {"source": "slack_command"},
    )

    result = run_async(
        execute_inter_agent_request(
            requesting_agent=requesting_agent,
            target_agent=target_agent,
            action=action,
        )
    )

    response = format_inter_agent_result(result)
    say(response)


# ============================================================
# Message Handler
# ============================================================


@slack_app.event("message")
def handle_message(event, say):
    """Handle incoming Slack messages via the LangGraph orchestrator."""
    text = event.get("text", "").strip()
    slack_user_id = event.get("user", "")
    message_ts = event.get("ts")

    # Ignore bot messages
    if event.get("bot_id") or not text:
        return

    logger.info(f"Slack message from {slack_user_id}: {text}")
    log_audit(
        "slack_message", "orchestrator", "receive", "success", {"text": text[:100]}
    )

    # Inter-agent command
    if text.lower().startswith("inter-agent:") or text.lower().startswith(
        "inter agent:"
    ):
        _handle_inter_agent(text, event, say)
        return

    # Cross-agent workflow: meeting prep
    if any(
        phrase in text.lower()
        for phrase in [
            "prepare for my meeting",
            "meeting prep",
            "next meeting",
            "brief me",
            "meeting briefing",
            "prepare me for my meeting",
        ]
    ):
        refresh_token = get_refresh_token()
        if not refresh_token:
            say(
                "I don't have authentication set up yet. Please log in at the web dashboard first."
            )
            return
        say(
            "📋 Preparing your meeting briefing — checking calendar, emails, and files..."
        )
        result = run_async(meeting_prep_workflow(refresh_token))
        response = format_workflow_result(result)
        say(response)

        # Post session summary in thread
        summary = build_workflow_summary(result)
        say(summary, thread_ts=message_ts)
        return

    # Get the refresh token
    refresh_token = get_refresh_token()
    if not refresh_token:
        say(
            "I don't have authentication set up yet. Please log in at the web dashboard first, then try again."
        )
        return

    say("🤔 Processing your request...")

    # Run through the LangGraph orchestrator
    from core.orchestrator import run_orchestrator

    result = run_async(
        run_orchestrator(
            user_message=text,
            refresh_token=refresh_token,
        )
    )

    response = result.get("response", "Something went wrong.")
    agent = result.get("agent", "")
    action = result.get("action", "")
    steps = result.get("steps", [])
    ciba_status = result.get("ciba_status")

    # Log the full trace
    log_audit(
        "orchestrator_complete",
        agent or "orchestrator",
        action or "route",
        "error" if result.get("error") else "success",
        {"steps_count": len(steps), "response_length": len(response)},
    )

    # Post the response
    say(response)

    # Post session summary in thread
    if steps:
        summary = build_session_summary(
            steps=steps,
            agent=agent,
            action=action,
            ciba_status=ciba_status,
        )
        say(summary, thread_ts=message_ts)


@slack_app.event("app_mention")
def handle_mention(event, say):
    """Handle @mentions of the bot."""
    handle_message(event, say)


# ============================================================
# Start
# ============================================================


def start_slack_bot():
    """Start the Slack bot with Socket Mode."""
    handler = SocketModeHandler(slack_app, os.getenv("SLACK_APP_TOKEN"))
    logger.info("ctrlAI Slack bot starting with LangGraph orchestrator...")
    handler.start()


if __name__ == "__main__":
    start_slack_bot()
