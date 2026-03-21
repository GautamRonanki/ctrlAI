"""
ctrlAI Slack Bot — Employee-facing interface.
Now powered by the LangGraph Master Orchestrator with rich Slack Block Kit formatting.

Inter-agent commands: "inter-agent: agent1 requests action from agent2"
Cross-agent workflows: "prepare for my next meeting"
Every interaction ends with a session summary in thread.
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
from core.inter_agent import execute_inter_agent_request
from core.workflows import meeting_prep_workflow, format_workflow_result
from core.slack_blocks import (
    format_orchestrator_result_blocks,
    format_session_summary_blocks,
    format_workflow_summary_blocks,
    format_inter_agent_blocks,
    processing_blocks,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))

# ============================================================
# Refresh Token Persistence
# ============================================================

TOKEN_STORE_PATH = Path(__file__).parent.parent / "config" / "token_store.json"


def get_refresh_token() -> str:
    if TOKEN_STORE_PATH.exists():
        try:
            data = json.loads(TOKEN_STORE_PATH.read_text())
            return data.get("refresh_token", "")
        except (json.JSONDecodeError, Exception):
            pass
    return os.getenv("AUTH0_REFRESH_TOKEN", "")


def save_refresh_token(refresh_token: str, user_email: str = ""):
    TOKEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"refresh_token": refresh_token, "user_email": user_email}
    TOKEN_STORE_PATH.write_text(json.dumps(data))
    logger.info(f"Refresh token persisted for {user_email}")


# ============================================================
# Async Helper
# ============================================================


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# Inter-Agent Command Handler
# ============================================================


def _handle_inter_agent(text: str, event: dict, say):
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

    say("🔍 Checking inter-agent permission...")

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

    blocks = format_inter_agent_blocks(result)
    say(blocks=blocks, text=f"Inter-agent request: {result['status']}")


# ============================================================
# Message Handler
# ============================================================


@slack_app.event("message")
def handle_message(event, say):
    text = event.get("text", "").strip()
    slack_user_id = event.get("user", "")
    message_ts = event.get("ts")

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

        say(blocks=processing_blocks(), text="Processing...")
        result = run_async(meeting_prep_workflow(refresh_token))
        response = format_workflow_result(result)
        say(response)

        # Session summary in thread with blocks
        summary_blocks = format_workflow_summary_blocks(result)
        say(blocks=summary_blocks, text="Session Summary", thread_ts=message_ts)
        return

    # Get the refresh token
    refresh_token = get_refresh_token()
    if not refresh_token:
        say(
            "I don't have authentication set up yet. Please log in at the web dashboard first, then try again."
        )
        return

    say(blocks=processing_blocks(), text="Processing...")

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

    # Post the response with blocks
    result_blocks = format_orchestrator_result_blocks(
        response, agent, action, ciba_status
    )
    say(blocks=result_blocks, text=response)

    # Post session summary in thread with blocks
    if steps:
        summary_blocks = format_session_summary_blocks(
            steps=steps,
            agent=agent,
            action=action,
            ciba_status=ciba_status,
        )
        say(blocks=summary_blocks, text="Session Summary", thread_ts=message_ts)


@slack_app.event("app_mention")
def handle_mention(event, say):
    handle_message(event, say)


# ============================================================
# Start
# ============================================================


def start_slack_bot():
    handler = SocketModeHandler(slack_app, os.getenv("SLACK_APP_TOKEN"))
    logger.info("ctrlAI Slack bot starting with LangGraph orchestrator + Block Kit...")
    handler.start()


if __name__ == "__main__":
    start_slack_bot()
