"""
ctrlAI Slack Bot — Employee-facing interface.
Now powered by the LangGraph Master Orchestrator.
Employees message the bot in natural language. The orchestrator handles routing,
permissions, CIBA, and execution through the graph.

Inter-agent commands are handled via: "inter-agent: agent1 requests action from agent2"
Cross-agent workflows are triggered by natural language (e.g., "prepare for my next meeting")
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
# The refresh token is obtained when a user logs in via the web UI (FastAPI).
# We persist it to a file so the Slack bot can access it without a web session.
# This file is written by the FastAPI callback and read by the Slack bot.

TOKEN_STORE_PATH = Path(__file__).parent.parent / "config" / "token_store.json"


def get_refresh_token() -> str:
    """Get the persisted refresh token."""
    if TOKEN_STORE_PATH.exists():
        try:
            data = json.loads(TOKEN_STORE_PATH.read_text())
            return data.get("refresh_token", "")
        except (json.JSONDecodeError, Exception):
            pass
    # Fallback to env var
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


# ============================================================
# Inter-Agent Command Handler
# ============================================================


def _handle_inter_agent(text: str, event: dict, say):
    """Handle explicit inter-agent communication requests."""
    # Parse: "inter-agent: gmail_agent requests store_attachment from drive_agent"
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
        # Post the execution trace in thread
        steps = result.get("steps", [])
        if steps:
            trace_lines = ["📋 *Workflow execution trace:*"]
            for step in steps:
                node = step.get("step", "?").replace("_", " ").title()
                status = step.get("status", "?")
                note = step.get("note", "")
                trace_lines.append(f"  → {node}: {status}")
                if note:
                    trace_lines.append(f"    _{note}_")
            say("\n".join(trace_lines), thread_ts=event.get("ts"))
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

    # If there are steps, post a trace summary in a thread (for observability)
    if steps and len(steps) > 1:
        trace_lines = ["📋 *Execution trace:*"]
        for step in steps:
            node = step.get("node", "?")
            status = step.get("status", "?")
            trace_lines.append(f"  → `{node}`: {status}")
        say(
            "\n".join(trace_lines),
            thread_ts=event.get("ts"),  # Reply in thread
        )


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
