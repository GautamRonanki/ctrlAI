"""
ctrlAI Slack Bot — Employee-facing interface.
Now powered by the LangGraph Master Orchestrator.
Employees message the bot in natural language. The orchestrator handles routing,
permissions, CIBA, and execution through the graph.
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
    log_audit("slack_message", "orchestrator", "receive", "success", {"text": text[:100]})

    # Get the refresh token
    refresh_token = get_refresh_token()
    if not refresh_token:
        say("I don't have authentication set up yet. Please log in at the web dashboard first, then try again.")
        return

    say("🤔 Processing your request...")

    # Run through the LangGraph orchestrator
    from core.orchestrator import run_orchestrator

    result = run_async(run_orchestrator(
        user_message=text,
        refresh_token=refresh_token,
    ))

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
