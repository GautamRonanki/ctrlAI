"""
ctrlAI — LangGraph Master Orchestrator
=======================================
This is the brain of ctrlAI. It replaces the hand-rolled routing in slack_bot/app.py
with a proper LangGraph state machine.

Graph structure:
  [router] → [permission_gate] → [agent_node] → [response_formatter]
                                       ↓ (if high-stakes)
                                  [ciba_checkpoint]
                                       ↓
                                  [agent_node]

Every edge enforces permissions. Every node logs to the audit trail.
"""

import os
import json
import asyncio
from typing import TypedDict, Literal, Any, Optional
from dataclasses import dataclass

from langgraph.graph import StateGraph, END
from loguru import logger

from core.llm import get_llm, call_llm
from core.permissions import (
    get_all_agents,
    is_agent_active,
    check_scope_permission,
    is_high_stakes,
    check_inter_agent_permission,
)
from core.token_service import get_google_token, get_github_token
from core.ciba_service import request_and_wait_for_approval
from core.logger import log_audit


# ============================================================
# State Definition
# ============================================================


class OrchestratorState(TypedDict):
    """State that flows through the entire graph."""

    # Input
    user_message: str
    refresh_token: str
    ciba_user_id: str  # Auth0 user ID for CIBA (email/password user with Guardian)

    # Routing
    agent: str  # which agent to dispatch
    action: str  # which action to perform
    params: dict  # action parameters

    # Execution
    token: Optional[str]  # OAuth token for the current agent
    agent_result: Optional[dict]  # raw result from agent function
    ciba_status: Optional[str]  # approved/denied/timeout/skipped

    # Output
    response: str  # human-readable response for the user
    error: Optional[str]  # error message if something went wrong

    # Audit
    steps: list[dict]  # trace of every step for observability


# ============================================================
# Node: Router
# ============================================================


async def router_node(state: OrchestratorState) -> dict:
    """Use the LLM to determine which agent and action to dispatch."""
    llm = get_llm()
    agents = get_all_agents()

    agent_descriptions = "\n".join(
        f"- {name}: {a.description} | scopes: {', '.join(a.permitted_scopes)} | "
        f"high-stakes: {', '.join(a.high_stakes_actions)}"
        for name, a in agents.items()
    )

    prompt = f"""You are the ctrlAI Master Orchestrator. Route the user's request to the correct agent.

Available agents:
{agent_descriptions}

User request: "{state["user_message"]}"

Respond with ONLY valid JSON. No markdown, no explanation, no code fences.

Action names by agent:
- gmail_agent: list_emails, search_emails, send_email, read_email
- calendar_agent: list_events, create_event
- drive_agent: list_files, search_files, delete_file
- github_agent: list_repos, list_issues, create_comment

For send_email: include "to", "subject", "body" in params.
For search_emails: include "query" in params.
For search_files: include "query" in params.
For create_event: include "summary", "start_time", "end_time" in params.
For list_issues: include "owner", "repo" in params.
For create_comment: include "owner", "repo", "issue_number", "body" in params.
For delete_file: include "file_id" in params.

If the request doesn't match any agent, respond: {{"agent": "none", "action": "none", "params": {{}}}}

JSON response:"""

    try:
        response = await call_llm(
            llm, [{"role": "user", "content": prompt}], label="orchestrator_router"
        )
        content = response.content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        routing = json.loads(content)
    except Exception as e:
        logger.error(f"Router LLM failed: {e}")
        return {
            "agent": "none",
            "action": "none",
            "params": {},
            "error": f"Routing failed: {str(e)}",
            "steps": state.get("steps", [])
            + [{"node": "router", "status": "error", "error": str(e)}],
        }

    agent = routing.get("agent", "none")
    action = routing.get("action", "none")
    params = routing.get("params", {})

    log_audit(
        "routing", "orchestrator", f"{agent}/{action}", "success", {"params": params}
    )

    return {
        "agent": agent,
        "action": action,
        "params": params,
        "steps": state.get("steps", [])
        + [{"node": "router", "agent": agent, "action": action, "params": params}],
    }


# ============================================================
# Node: Permission Gate
# ============================================================


async def permission_gate_node(state: OrchestratorState) -> dict:
    """Check if the agent is active and has the required permissions."""
    agent = state["agent"]
    action = state["action"]

    if agent == "none":
        return {
            "error": "no_agent",
            "response": "I'm not sure how to help with that. I can read emails, check your calendar, search Drive, or look at GitHub repos.",
            "steps": state.get("steps", [])
            + [{"node": "permission_gate", "status": "no_agent"}],
        }

    # Check agent is active
    if not is_agent_active(agent):
        log_audit(
            "permission_check", agent, action, "denied", {"reason": "agent not active"}
        )
        return {
            "error": "agent_suspended",
            "response": f"The {agent.replace('_', ' ')} is currently suspended by the administrator.",
            "steps": state.get("steps", [])
            + [{"node": "permission_gate", "status": "agent_suspended"}],
        }

    # Map actions to required scopes
    scope_map = {
        "gmail_agent": {
            "list_emails": "list_emails",
            "search_emails": "search_emails",
            "read_email": "read_emails",
            "send_email": "send_emails",
        },
        "calendar_agent": {
            "list_events": "list_events",
            "create_event": "create_events",
        },
        "drive_agent": {
            "list_files": "list_files",
            "search_files": "search_files",
            "delete_file": "delete_files",
        },
        "github_agent": {
            "list_repos": "list_repos",
            "list_issues": "list_issues",
            "create_comment": "post_comments",
        },
    }

    required_scope = scope_map.get(agent, {}).get(action)
    if required_scope and not check_scope_permission(agent, required_scope):
        return {
            "error": "permission_denied",
            "response": f"Permission denied: {agent.replace('_', ' ')} does not have the '{required_scope}' scope.",
            "steps": state.get("steps", [])
            + [
                {"node": "permission_gate", "status": "denied", "scope": required_scope}
            ],
        }

    return {
        "steps": state.get("steps", [])
        + [
            {
                "node": "permission_gate",
                "status": "allowed",
                "agent": agent,
                "action": action,
            }
        ],
    }


# ============================================================
# Node: Token Retrieval
# ============================================================


async def token_retrieval_node(state: OrchestratorState) -> dict:
    """Fetch the appropriate OAuth token from Token Vault."""
    agent = state["agent"]
    refresh_token = state["refresh_token"]

    if not refresh_token:
        return {
            "error": "no_refresh_token",
            "response": "I can't access services right now. Please log in at the web dashboard first.",
            "steps": state.get("steps", [])
            + [{"node": "token_retrieval", "status": "no_refresh_token"}],
        }

    # Determine which provider
    google_agents = {"gmail_agent", "calendar_agent", "drive_agent"}
    github_agents = {"github_agent"}

    try:
        if agent in google_agents:
            token = await get_google_token(refresh_token)
        elif agent in github_agents:
            token = await get_github_token(refresh_token)
        else:
            token = None

        if not token:
            return {
                "error": "token_failed",
                "response": f"Token Vault exchange failed for {agent.replace('_', ' ')}. Please reconnect your account at the web dashboard.",
                "steps": state.get("steps", [])
                + [{"node": "token_retrieval", "status": "failed", "agent": agent}],
            }

        return {
            "token": token,
            "steps": state.get("steps", [])
            + [{"node": "token_retrieval", "status": "success", "agent": agent}],
        }

    except Exception as e:
        logger.error(f"Token retrieval error: {e}")
        return {
            "error": "token_error",
            "response": f"Failed to retrieve token: {str(e)}",
            "steps": state.get("steps", [])
            + [{"node": "token_retrieval", "status": "error", "error": str(e)}],
        }


# ============================================================
# Node: CIBA Checkpoint
# ============================================================


async def ciba_checkpoint_node(state: OrchestratorState) -> dict:
    """Check if action is high-stakes. If so, trigger CIBA and wait for approval."""
    agent = state["agent"]
    action = state["action"]

    if not is_high_stakes(agent, action):
        return {
            "ciba_status": "skipped",
            "steps": state.get("steps", [])
            + [{"node": "ciba_checkpoint", "status": "not_required"}],
        }

    # High-stakes — trigger CIBA
    ciba_user_id = state.get("ciba_user_id") or os.getenv(
        "EMERGENCY_COORDINATOR_USER_ID", ""
    )
    if not ciba_user_id:
        return {
            "error": "no_ciba_user",
            "response": "Cannot request approval — no CIBA user configured.",
            "steps": state.get("steps", [])
            + [{"node": "ciba_checkpoint", "status": "no_user"}],
        }

    binding_message = (
        f"ctrlAI {agent.replace('_', ' ').title()}: {action.replace('_', ' ')}"
    )

    log_audit("ciba", agent, action, "requesting_approval", {"user_id": ciba_user_id})

    try:
        result = await request_and_wait_for_approval(
            user_id=ciba_user_id,
            agent_name=agent,
            action=action,
            binding_message=binding_message,
        )

        ciba_status = result.get("status", "error")

        if ciba_status != "approved":
            return {
                "ciba_status": ciba_status,
                "error": "ciba_not_approved",
                "response": f"Action '{action.replace('_', ' ')}' was {ciba_status}. The action was blocked for your safety.",
                "steps": state.get("steps", [])
                + [{"node": "ciba_checkpoint", "status": ciba_status}],
            }

        return {
            "ciba_status": "approved",
            "steps": state.get("steps", [])
            + [{"node": "ciba_checkpoint", "status": "approved"}],
        }

    except Exception as e:
        logger.error(f"CIBA error: {e}")
        return {
            "ciba_status": "error",
            "error": "ciba_error",
            "response": f"Approval request failed: {str(e)}",
            "steps": state.get("steps", [])
            + [{"node": "ciba_checkpoint", "status": "error", "error": str(e)}],
        }


# ============================================================
# Node: Agent Executor
# ============================================================


async def agent_executor_node(state: OrchestratorState) -> dict:
    """Execute the agent action with the retrieved token."""
    agent = state["agent"]
    action = state["action"]
    params = state.get("params", {})
    token = state.get("token")

    if not token:
        return {
            "error": "no_token",
            "response": "Cannot execute — no token available.",
            "steps": state.get("steps", [])
            + [{"node": "agent_executor", "status": "no_token"}],
        }

    try:
        result = await _dispatch_agent(agent, action, token, params)

        if "error" in result:
            log_audit(
                "agent_execution", agent, action, "error", {"error": result["error"]}
            )
            return {
                "agent_result": result,
                "error": "agent_error",
                "response": f"Agent error: {result['error']}",
                "steps": state.get("steps", [])
                + [
                    {
                        "node": "agent_executor",
                        "status": "error",
                        "error": result["error"],
                    }
                ],
            }

        log_audit(
            "agent_execution",
            agent,
            action,
            "success",
            {"result_keys": list(result.keys())},
        )
        return {
            "agent_result": result,
            "steps": state.get("steps", [])
            + [
                {
                    "node": "agent_executor",
                    "status": "success",
                    "agent": agent,
                    "action": action,
                }
            ],
        }

    except Exception as e:
        logger.error(f"Agent execution error: {e}")
        log_audit("agent_execution", agent, action, "error", {"error": str(e)})
        return {
            "error": "execution_error",
            "response": f"Something went wrong: {str(e)}",
            "steps": state.get("steps", [])
            + [{"node": "agent_executor", "status": "exception", "error": str(e)}],
        }


async def _dispatch_agent(agent: str, action: str, token: str, params: dict) -> dict:
    """Dispatch to the correct agent function."""

    if agent == "gmail_agent":
        from agents.gmail_agent import (
            list_emails,
            search_emails,
            send_email,
            read_email,
        )

        if action == "list_emails":
            return await list_emails(token, max_results=params.get("max_results", 5))
        elif action == "search_emails":
            return await search_emails(token, query=params.get("query", ""))
        elif action == "send_email":
            return await send_email(
                token,
                to=params.get("to", ""),
                subject=params.get("subject", ""),
                body=params.get("body", ""),
            )
        elif action == "read_email":
            return await read_email(token, message_id=params.get("message_id", ""))

    elif agent == "calendar_agent":
        from agents.calendar_agent import list_events, create_event

        if action == "list_events":
            return await list_events(token, max_results=params.get("max_results", 5))
        elif action == "create_event":
            return await create_event(
                token,
                summary=params.get("summary", ""),
                start_time=params.get("start_time", ""),
                end_time=params.get("end_time", ""),
            )

    elif agent == "drive_agent":
        from agents.drive_agent import list_files, search_files, delete_file

        if action == "list_files":
            return await list_files(token, max_results=params.get("max_results", 10))
        elif action == "search_files":
            return await search_files(token, query=params.get("query", ""))
        elif action == "delete_file":
            return await delete_file(token, file_id=params.get("file_id", ""))

    elif agent == "github_agent":
        from agents.github_agent import list_repos, list_issues, create_comment

        if action == "list_repos":
            return await list_repos(token, max_results=params.get("max_results", 10))
        elif action == "list_issues":
            return await list_issues(
                token, owner=params.get("owner", ""), repo=params.get("repo", "")
            )
        elif action == "create_comment":
            return await create_comment(
                token,
                owner=params.get("owner", ""),
                repo=params.get("repo", ""),
                issue_number=params.get("issue_number", 0),
                body=params.get("body", ""),
            )

    return {"error": f"Unknown agent/action: {agent}/{action}"}


# ============================================================
# Node: Response Formatter
# ============================================================


async def response_formatter_node(state: OrchestratorState) -> dict:
    """Use LLM to generate an intelligent, conversational response from agent results."""
    # If there's already an error response, pass it through
    if state.get("error") and state.get("response"):
        return {}

    result = state.get("agent_result")
    if not result:
        return {"response": "Something went wrong — no result from the agent."}

    agent = state["agent"]
    action = state["action"]
    user_message = state.get("user_message", "")

    # For simple confirmations (send_email, create_event, delete_file, create_comment),
    # use the hardcoded formatter — no need to burn tokens
    simple_actions = {"send_email", "create_event", "delete_file", "create_comment"}
    if action in simple_actions:
        try:
            response = _format_result(agent, action, result)
            return {
                "response": response,
                "steps": state.get("steps", [])
                + [
                    {
                        "node": "response_formatter",
                        "status": "success",
                        "method": "direct",
                    }
                ],
            }
        except Exception:
            pass  # Fall through to LLM formatting

    # For read/list/search actions, use LLM to give an intelligent answer
    try:
        llm = get_llm()

        # Truncate result to avoid blowing up the context
        result_str = json.dumps(result, indent=2, default=str)
        if len(result_str) > 8000:
            result_str = result_str[:8000] + "\n... (truncated)"

        format_prompt = f"""You are ctrlAI, an intelligent AI assistant that helps users interact with their services (Gmail, Calendar, Drive, GitHub).

The user asked: "{user_message}"

The {agent.replace("_", " ")} retrieved this data:
{result_str}

Your job:
1. Answer the user's question directly and conversationally based on the data above
2. Highlight the most relevant information — don't just list everything
3. If there are details worth noting (attachments, conflicts, deadlines), mention them
4. At the end, suggest 1-2 natural follow-up actions the user might want (e.g., "Want me to save the attachment to Drive?" or "Should I create a calendar event for this?")

Keep it concise. Use Slack formatting: *single asterisks* for bold (NOT **double**), • for lists. Never use markdown formatting like **bold** or ### headers — only Slack mrkdwn. Do not make up information not present in the data."""

        response = await call_llm(
            llm,
            [{"role": "user", "content": format_prompt}],
            label="response_formatter",
        )

        return {
            "response": response.content.strip(),
            "steps": state.get("steps", [])
            + [{"node": "response_formatter", "status": "success", "method": "llm"}],
        }

    except Exception as e:
        logger.error(
            f"LLM response formatting failed: {e}, falling back to direct format"
        )
        # Fallback to hardcoded formatter
        try:
            response = _format_result(agent, action, result)
        except Exception:
            response = json.dumps(result, indent=2)
        return {
            "response": response,
            "steps": state.get("steps", [])
            + [{"node": "response_formatter", "status": "fallback", "error": str(e)}],
        }


def _format_result(agent: str, action: str, result: dict) -> str:
    """Format agent results into clean Slack messages."""

    if agent == "gmail_agent":
        if action in ("list_emails", "search_emails"):
            emails = result.get("emails", [])
            if not emails:
                return (
                    "No emails found."
                    if action == "list_emails"
                    else f"No emails matching '{result.get('query', '')}' found."
                )
            lines = [
                f"Found {result['count']} {'recent ' if action == 'list_emails' else ''}emails:"
            ]
            for e in emails:
                lines.append(
                    f"• *{e['subject']}* from {e['from']} ({e.get('date', '')[:16]})"
                )
            return "\n".join(lines)
        elif action == "send_email":
            return f"✅ Email sent! Message ID: {result.get('message_id', 'unknown')}"
        elif action == "read_email":
            return f"*{result.get('subject', 'No subject')}*\nFrom: {result.get('from', '')}\nDate: {result.get('date', '')}\n\n{result.get('snippet', '')}"

    elif agent == "calendar_agent":
        if action == "list_events":
            events = result.get("events", [])
            if not events:
                return "No upcoming events found."
            lines = [f"Found {result['count']} upcoming events:"]
            for e in events:
                lines.append(f"• *{e['summary']}* — {e['start'][:16]}")
            return "\n".join(lines)
        elif action == "create_event":
            return f"✅ Event created! Link: {result.get('link', '')}"

    elif agent == "drive_agent":
        if action in ("list_files", "search_files"):
            files = result.get("files", [])
            if not files:
                return (
                    "No files found."
                    if action == "list_files"
                    else f"No files matching '{result.get('query', '')}' found."
                )
            lines = [f"Found {result['count']} files:"]
            for f in files:
                ftype = (
                    f.get("type", "").split(".")[-1]
                    if "." in f.get("type", "")
                    else f.get("type", "")
                )
                lines.append(f"• *{f['name']}* ({ftype})")
            return "\n".join(lines)
        elif action == "delete_file":
            return f"✅ File deleted (ID: {result.get('file_id', 'unknown')})"

    elif agent == "github_agent":
        if action == "list_repos":
            repos = result.get("repos", [])
            if not repos:
                return "No repositories found."
            lines = [f"Found {result['count']} repos:"]
            for r in repos:
                lang = f" [{r['language']}]" if r.get("language") else ""
                lines.append(f"• *{r['name']}*{lang} ⭐{r.get('stars', 0)}")
            return "\n".join(lines)
        elif action == "list_issues":
            issues = result.get("issues", [])
            if not issues:
                return f"No open issues in {result.get('repo', '')}."
            lines = [
                f"Found {result['count']} open issues in {result.get('repo', '')}:"
            ]
            for i in issues:
                lines.append(f"• #{i['number']} *{i['title']}* by {i['author']}")
            return "\n".join(lines)
        elif action == "create_comment":
            return f"✅ Comment posted! {result.get('url', '')}"

    # Fallback
    return json.dumps(result, indent=2)


# ============================================================
# Graph Construction
# ============================================================


def _should_continue(state: OrchestratorState) -> str:
    """Determine next node based on state."""
    if state.get("error"):
        return "end"
    return "continue"


def build_orchestrator_graph() -> StateGraph:
    """Build and compile the ctrlAI orchestrator graph."""

    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("permission_gate", permission_gate_node)
    graph.add_node("token_retrieval", token_retrieval_node)
    graph.add_node("ciba_checkpoint", ciba_checkpoint_node)
    graph.add_node("agent_executor", agent_executor_node)
    graph.add_node("response_formatter", response_formatter_node)

    # Set entry point
    graph.set_entry_point("router")

    # Router → Permission Gate (always)
    graph.add_edge("router", "permission_gate")

    # Permission Gate → Token Retrieval or END
    graph.add_conditional_edges(
        "permission_gate",
        _should_continue,
        {"continue": "token_retrieval", "end": "response_formatter"},
    )

    # Token Retrieval → CIBA Checkpoint or END
    graph.add_conditional_edges(
        "token_retrieval",
        _should_continue,
        {"continue": "ciba_checkpoint", "end": "response_formatter"},
    )

    # CIBA Checkpoint → Agent Executor or END
    graph.add_conditional_edges(
        "ciba_checkpoint",
        _should_continue,
        {"continue": "agent_executor", "end": "response_formatter"},
    )

    # Agent Executor → Response Formatter (always)
    graph.add_edge("agent_executor", "response_formatter")

    # Response Formatter → END
    graph.add_edge("response_formatter", END)

    return graph.compile()


# ============================================================
# Public Interface
# ============================================================

# Compile once at import time
orchestrator = build_orchestrator_graph()


async def run_orchestrator(
    user_message: str,
    refresh_token: str,
    ciba_user_id: str = "",
) -> dict:
    """
    Run a user message through the orchestrator.
    Returns: {"response": str, "steps": list, "agent": str, "action": str}
    """
    if not ciba_user_id:
        ciba_user_id = os.getenv("EMERGENCY_COORDINATOR_USER_ID", "")

    initial_state: OrchestratorState = {
        "user_message": user_message,
        "refresh_token": refresh_token,
        "ciba_user_id": ciba_user_id,
        "agent": "",
        "action": "",
        "params": {},
        "token": None,
        "agent_result": None,
        "ciba_status": None,
        "response": "",
        "error": None,
        "steps": [],
    }

    result = await orchestrator.ainvoke(initial_state)

    return {
        "response": result.get("response", "Something went wrong."),
        "agent": result.get("agent", ""),
        "action": result.get("action", ""),
        "steps": result.get("steps", []),
        "ciba_status": result.get("ciba_status"),
        "error": result.get("error"),
    }
