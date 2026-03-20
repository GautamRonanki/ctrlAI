"""
ctrlAI Slack Bot — Employee-facing interface.
Employees message the bot in natural language. The bot routes to the appropriate agent,
enforces permissions, triggers CIBA for high-stakes actions, and returns results.
"""

import os
import asyncio
import logging

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from core.llm import get_llm
from core.permissions import get_all_agents, is_high_stakes, check_scope_permission
from core.token_service import get_google_token
from core.logger import log_audit

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Slack app with Socket Mode
slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))

# Store user sessions (user_id -> auth0_user_id mapping)
# In production, this would be a database. For hackathon, in-memory is fine.
USER_SESSIONS = {}

# The Auth0 user ID of the logged-in Google user — set this after login
# For the hackathon demo, we hardcode the Google user since Slack users
# aren't directly mapped to Auth0 users
DEFAULT_AUTH0_USER_ID = os.getenv("DEFAULT_AUTH0_USER_ID", "")


def get_auth0_user_id(slack_user_id: str) -> str:
    """Map a Slack user to their Auth0 user ID."""
    return USER_SESSIONS.get(slack_user_id, DEFAULT_AUTH0_USER_ID)


def run_async(coro):
    """Run an async function from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def route_message(text: str) -> dict:
    """
    Use the LLM to determine which agent should handle this message.
    Returns: {"agent": "gmail_agent", "action": "list_emails", "params": {...}}
    """
    llm = get_llm()
    agents = get_all_agents()

    agent_descriptions = "\n".join(
        f"- {name}: {a.description} (actions: {', '.join(a.high_stakes_actions + ['read/list'])})"
        for name, a in agents.items()
    )

    prompt = f"""You are the ctrlAI orchestrator. Route the user's request to the correct agent.

Available agents:
{agent_descriptions}

User request: "{text}"

Respond with ONLY valid JSON, no markdown, no explanation:
{{"agent": "agent_name", "action": "action_name", "params": {{}}}}

Action names:
- gmail_agent: list_emails, search_emails, send_email, read_email
- calendar_agent: list_events, create_event
- drive_agent: list_files, search_files
- github_agent: list_repos, list_issues

For send_email, include "to", "subject", "body" in params.
For search_emails, include "query" in params.
For search_files, include "query" in params.
For create_event, include "summary", "start_time", "end_time" in params.

If the request doesn't match any agent, respond: {{"agent": "none", "action": "none", "params": {{}}}}
"""

    import json
    response = run_async(llm.ainvoke([{"role": "user", "content": prompt}]))
    
    try:
        # Strip markdown code fences if present
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"LLM routing failed: {e}, response: {response.content}")
        return {"agent": "none", "action": "none", "params": {}}


async def execute_agent_action(auth0_user_id: str, agent: str, action: str, params: dict) -> str:
    """Execute an agent action and return a human-readable result."""
    
    # Get the appropriate token
    if agent in ("gmail_agent", "calendar_agent", "drive_agent"):
        token = await get_google_token(auth0_user_id)
        if not token:
            return "I can't access Google services right now. Please make sure you're logged in at the web dashboard."
    elif agent == "github_agent":
        return "GitHub agent is not connected yet. Please link your GitHub account first."
    else:
        return "I don't know how to handle that request."

    # Execute the action
    try:
        if agent == "gmail_agent":
            from agents.gmail_agent import list_emails, search_emails, send_email

            if action == "list_emails":
                result = await list_emails(token)
                if "error" in result:
                    return f"Permission denied: {result['error']}"
                emails = result.get("emails", [])
                if not emails:
                    return "No recent emails found."
                lines = [f"Found {result['count']} recent emails:"]
                for e in emails:
                    lines.append(f"• *{e['subject']}* from {e['from']} ({e['date'][:16]})")
                return "\n".join(lines)

            elif action == "search_emails":
                query = params.get("query", "")
                result = await search_emails(token, query=query)
                if "error" in result:
                    return f"Permission denied: {result['error']}"
                emails = result.get("emails", [])
                if not emails:
                    return f"No emails found matching '{query}'."
                lines = [f"Found {result['count']} emails for '{query}':"]
                for e in emails:
                    lines.append(f"• *{e['subject']}* from {e['from']}")
                return "\n".join(lines)

            elif action == "send_email":
                # High-stakes — trigger CIBA
                from core.ciba_service import request_and_wait_for_approval
                
                to = params.get("to", "")
                subject = params.get("subject", "")
                body = params.get("body", "")
                
                if not to:
                    return "I need a recipient email address to send an email."

                ciba_result = await request_and_wait_for_approval(
                    user_id=os.getenv("EMERGENCY_COORDINATOR_USER_ID"),
                    agent_name="gmail_agent",
                    action="send_email",
                    binding_message="ctrlAI Gmail Agent: send email",
                )

                if ciba_result["status"] != "approved":
                    return f"Email send was {ciba_result['status']}. The action was blocked."

                result = await send_email(token, to=to, subject=subject, body=body)
                if "error" in result:
                    return f"Failed to send email: {result['error']}"
                return f"Email sent to {to} with subject '{subject}'."

        elif agent == "calendar_agent":
            from agents.calendar_agent import list_events, create_event

            if action == "list_events":
                result = await list_events(token)
                if "error" in result:
                    return f"Permission denied: {result['error']}"
                events = result.get("events", [])
                if not events:
                    return "No upcoming events found."
                lines = [f"Found {result['count']} upcoming events:"]
                for e in events:
                    lines.append(f"• *{e['summary']}* — {e['start'][:16]}")
                return "\n".join(lines)

            elif action == "create_event":
                from core.ciba_service import request_and_wait_for_approval

                summary = params.get("summary", "New Event")
                start_time = params.get("start_time", "")
                end_time = params.get("end_time", "")

                if not start_time or not end_time:
                    return "I need a start time and end time to create an event (ISO format)."

                ciba_result = await request_and_wait_for_approval(
                    user_id=os.getenv("EMERGENCY_COORDINATOR_USER_ID"),
                    agent_name="calendar_agent",
                    action="create_event",
                    binding_message="ctrlAI Calendar: create event",
                )

                if ciba_result["status"] != "approved":
                    return f"Event creation was {ciba_result['status']}. The action was blocked."

                result = await create_event(token, summary=summary, start_time=start_time, end_time=end_time)
                if "error" in result:
                    return f"Failed to create event: {result['error']}"
                return f"Event '{summary}' created. Link: {result.get('link', '')}"

        elif agent == "drive_agent":
            from agents.drive_agent import list_files, search_files

            if action == "list_files":
                result = await list_files(token)
                if "error" in result:
                    return f"Permission denied: {result['error']}"
                files = result.get("files", [])
                if not files:
                    return "No files found in Drive."
                lines = [f"Found {result['count']} recent files:"]
                for f in files:
                    lines.append(f"• *{f['name']}* ({f['type'].split('.')[-1]})")
                return "\n".join(lines)

            elif action == "search_files":
                query = params.get("query", "")
                result = await search_files(token, query=query)
                if "error" in result:
                    return f"Permission denied: {result['error']}"
                files = result.get("files", [])
                if not files:
                    return f"No files found matching '{query}'."
                lines = [f"Found {result['count']} files for '{query}':"]
                for f in files:
                    lines.append(f"• *{f['name']}*")
                return "\n".join(lines)

    except Exception as e:
        logger.error(f"Agent execution error: {e}")
        return f"Something went wrong: {str(e)}"

    return "I'm not sure how to handle that action."


@slack_app.event("message")
def handle_message(event, say):
    """Handle incoming Slack messages."""
    text = event.get("text", "").strip()
    slack_user_id = event.get("user", "")

    # Ignore bot messages
    if event.get("bot_id") or not text:
        return

    logger.info(f"Slack message from {slack_user_id}: {text}")
    log_audit("slack_message", "orchestrator", "receive", "success", {"text": text[:100]})

    # Route the message to the appropriate agent
    say("Thinking... 🤔")
    routing = route_message(text)

    agent = routing.get("agent", "none")
    action = routing.get("action", "none")
    params = routing.get("params", {})

    logger.info(f"Routed to: {agent}/{action} with params: {params}")
    log_audit("routing", "orchestrator", f"{agent}/{action}", "success", {"params": params})

    if agent == "none":
        say("I'm not sure how to help with that. I can read emails, check your calendar, search your Drive, or look at GitHub repos. What would you like?")
        return

    # Execute the action
    auth0_user_id = get_auth0_user_id(slack_user_id)
    if not auth0_user_id:
        say("I don't have your account linked yet. Please log in at the web dashboard first.")
        return

    result = run_async(execute_agent_action(auth0_user_id, agent, action, params))
    say(result)


@slack_app.event("app_mention")
def handle_mention(event, say):
    """Handle @mentions of the bot."""
    handle_message(event, say)


def start_slack_bot():
    """Start the Slack bot with Socket Mode."""
    handler = SocketModeHandler(slack_app, os.getenv("SLACK_APP_TOKEN"))
    logger.info("ctrlAI Slack bot starting...")
    handler.start()


if __name__ == "__main__":
    start_slack_bot()
