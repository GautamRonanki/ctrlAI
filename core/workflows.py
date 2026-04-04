"""
ctrlAI - Cross-Agent Workflows
================================
Real multi-agent collaboration where agents work together on a single task.
Every inter-agent interaction is governed by the permission matrix and logged.

Workflow: "Prepare me for my next meeting"
1. Calendar Agent → gets the next meeting (attendees, topic, time)
2. Gmail Agent → searches for recent emails from/to attendees
3. Drive Agent → searches for files related to the meeting topic
4. LLM → synthesizes everything into a single briefing
"""

import os
import json
import re
from loguru import logger

from core.permissions import (
    is_agent_active,
    check_inter_agent_permission,
    check_scope_permission,
)
from core.token_service import get_google_token
from core.llm import get_llm, call_llm
from core.logger import log_audit


async def meeting_prep_workflow(refresh_token: str) -> dict:
    """
    Cross-agent workflow: Prepare for the next meeting.

    Flow:
    1. Calendar Agent gets the next meeting
    2. Gmail Agent searches emails related to attendees (inter-agent: calendar → gmail)
    3. Drive Agent searches files related to meeting topic (inter-agent: calendar → drive - BLOCKED by matrix)
    4. LLM synthesizes a briefing

    Returns:
        {
            "status": "success" | "error",
            "briefing": str,
            "meeting": dict,
            "emails": list,
            "files": list | None,
            "steps": list,
            "inter_agent_results": list,
        }
    """
    steps = []
    inter_agent_results = []

    # ── Step 1: Get Google token ──
    google_token = await get_google_token(refresh_token)
    if not google_token:
        return {
            "status": "error",
            "briefing": "Could not retrieve Google token. Please log in at the web dashboard.",
            "steps": [{"step": "token_retrieval", "status": "failed"}],
        }
    steps.append({"step": "token_retrieval", "status": "success"})

    # ── Step 2: Calendar Agent gets the next meeting ──
    if not is_agent_active("calendar_agent"):
        return {
            "status": "error",
            "briefing": "Calendar Agent is suspended. Cannot prepare meeting briefing.",
            "steps": steps + [{"step": "calendar_agent", "status": "agent_suspended"}],
        }

    if not check_scope_permission("calendar_agent", "list_events"):
        return {
            "status": "error",
            "briefing": "Calendar Agent does not have permission to read events.",
            "steps": steps
            + [{"step": "calendar_agent", "status": "permission_denied"}],
        }

    from agents.calendar_agent import list_events

    calendar_result = await list_events(google_token, max_results=1)

    if "error" in calendar_result:
        return {
            "status": "error",
            "briefing": f"Calendar Agent error: {calendar_result['error']}",
            "steps": steps + [{"step": "calendar_agent", "status": "error"}],
        }

    events = calendar_result.get("events", [])
    if not events:
        return {
            "status": "success",
            "briefing": "You have no upcoming meetings. Enjoy your free time!",
            "meeting": None,
            "emails": [],
            "files": None,
            "steps": steps + [{"step": "calendar_agent", "status": "no_meetings"}],
            "inter_agent_results": [],
        }

    meeting = events[0]
    steps.append(
        {
            "step": "calendar_agent",
            "status": "success",
            "meeting": meeting.get("summary", ""),
            "attendees_count": len(meeting.get("attendees", [])),
        }
    )

    log_audit(
        "workflow",
        "calendar_agent",
        "get_next_meeting",
        "success",
        {
            "meeting": meeting.get("summary", ""),
            "attendees": len(meeting.get("attendees", [])),
        },
    )

    # ── Step 3: Gmail Agent searches for attendee emails ──
    # This is an inter-agent request: Calendar Agent asks Gmail Agent for context
    emails_result = []

    # Check inter-agent permission: calendar_agent → gmail_agent: read_email_context
    ia_allowed = check_inter_agent_permission(
        "calendar_agent", "gmail_agent", "read_email_context"
    )
    inter_agent_results.append(
        {
            "requesting": "Calendar Agent",
            "target": "Gmail Agent",
            "action": "read email context",
            "status": "allowed" if ia_allowed else "denied",
        }
    )

    if ia_allowed and is_agent_active("gmail_agent"):
        if check_scope_permission("gmail_agent", "search_emails"):
            from agents.gmail_agent import search_emails

            # Search for emails from attendees
            attendees = meeting.get("attendees", [])
            meeting_topic = meeting.get("summary", "")

            # Build search query from attendees and topic
            search_queries = []
            for email in attendees[:3]:  # Limit to first 3 attendees
                if email:
                    search_queries.append(f"from:{email}")

            if meeting_topic:
                search_queries.append(meeting_topic)

            all_emails = []
            for query in search_queries:
                result = await search_emails(google_token, query=query, max_results=3)
                if "error" not in result:
                    all_emails.extend(result.get("emails", []))

            # Deduplicate by email ID
            seen_ids = set()
            unique_emails = []
            for email in all_emails:
                if email.get("id") not in seen_ids:
                    seen_ids.add(email.get("id"))
                    unique_emails.append(email)

            emails_result = unique_emails[:5]  # Cap at 5

            steps.append(
                {
                    "step": "gmail_agent",
                    "status": "success",
                    "source": "inter-agent request from Calendar Agent",
                    "emails_found": len(emails_result),
                }
            )

            log_audit(
                "workflow",
                "gmail_agent",
                "search_attendee_emails",
                "success",
                {"emails_found": len(emails_result), "requested_by": "calendar_agent"},
            )
        else:
            steps.append({"step": "gmail_agent", "status": "permission_denied"})
    else:
        reason = (
            "inter-agent permission denied" if not ia_allowed else "agent suspended"
        )
        steps.append({"step": "gmail_agent", "status": reason})

    # ── Step 4: Drive Agent searches for related files ──
    # This demonstrates the permission matrix in action
    # calendar_agent does NOT have permission to request from drive_agent
    files_result = None

    ia_drive_allowed = check_inter_agent_permission(
        "calendar_agent", "drive_agent", "search_related_files"
    )
    inter_agent_results.append(
        {
            "requesting": "Calendar Agent",
            "target": "Drive Agent",
            "action": "search related files",
            "status": "allowed" if ia_drive_allowed else "denied",
        }
    )

    if ia_drive_allowed and is_agent_active("drive_agent"):
        if check_scope_permission("drive_agent", "search_files"):
            from agents.drive_agent import search_files

            meeting_topic = meeting.get("summary", "")
            if meeting_topic:
                result = await search_files(
                    google_token, query=meeting_topic, max_results=3
                )
                if "error" not in result:
                    files_result = result.get("files", [])

            steps.append(
                {
                    "step": "drive_agent",
                    "status": "success",
                    "source": "inter-agent request from Calendar Agent",
                    "files_found": len(files_result) if files_result else 0,
                }
            )
        else:
            steps.append({"step": "drive_agent", "status": "permission_denied"})
    else:
        reason = (
            "inter-agent permission denied"
            if not ia_drive_allowed
            else "agent suspended"
        )
        steps.append(
            {
                "step": "drive_agent",
                "status": reason,
                "note": "Calendar Agent cannot request file searches from Drive Agent per the permission matrix",
            }
        )

        log_audit(
            "workflow",
            "calendar_agent",
            "request:drive_agent:search_related_files",
            "denied",
            {"reason": "not in inter-agent permission matrix"},
        )

    # ── Step 5: LLM synthesizes the briefing ──
    briefing = await _generate_briefing(
        meeting, emails_result, files_result, inter_agent_results
    )
    steps.append({"step": "briefing_generation", "status": "success"})

    log_audit(
        "workflow",
        "orchestrator",
        "meeting_prep_complete",
        "success",
        {"meeting": meeting.get("summary", ""), "steps": len(steps)},
    )

    return {
        "status": "success",
        "briefing": briefing,
        "meeting": meeting,
        "emails": emails_result,
        "files": files_result,
        "steps": steps,
        "inter_agent_results": inter_agent_results,
    }


async def _generate_briefing(
    meeting: dict,
    emails: list,
    files: list | None,
    inter_agent_results: list,
) -> str:
    """Use the LLM to synthesize a meeting briefing from all gathered context."""

    # Build context
    meeting_info = (
        f"Meeting: {meeting.get('summary', 'No title')}\n"
        f"Time: {meeting.get('start', '')}\n"
        f"Location: {meeting.get('location', 'Not specified')}\n"
        f"Attendees: {', '.join(meeting.get('attendees', [])) or 'None listed'}\n"
        f"Description: {meeting.get('description', 'None')}"
    )

    email_info = "No related emails found."
    if emails:
        email_lines = []
        for e in emails:
            email_lines.append(
                f"- From: {e.get('from', '?')} | Subject: {e.get('subject', '?')} | Preview: {e.get('snippet', '')[:100]}"
            )
        email_info = "Related emails:\n" + "\n".join(email_lines)

    files_info = ""
    if files is None:
        files_info = "Drive search was blocked by the inter-agent permission matrix (Calendar Agent cannot request file searches from Drive Agent)."
    elif files:
        file_lines = [
            f"- {f.get('name', '?')} ({f.get('type', '').split('.')[-1] if '.' in f.get('type', '') else f.get('type', '')})"
            for f in files
        ]
        files_info = "Related files found:\n" + "\n".join(file_lines)
    else:
        files_info = "No related files found in Drive."

    ia_info = "Inter-agent permissions enforced:\n"
    for r in inter_agent_results:
        status_icon = "✅ Allowed" if r["status"] == "allowed" else "🚫 Denied"
        ia_info += (
            f"- {r['requesting']} → {r['target']}: {r['action']} - {status_icon}\n"
        )

    prompt = f"""You are the ctrlAI meeting preparation assistant. Generate a concise, actionable meeting briefing.

{meeting_info}

{email_info}

{files_info}

{ia_info}

Write a briefing that includes:
1. Meeting overview (who, what, when, where)
2. Key context from emails (if any relevant emails were found)
3. Note about Drive files (whether found, or if the search was blocked by permissions)
4. A brief note on which inter-agent permissions were used and which were blocked

Keep it concise and actionable. Use bullet points. Format for Slack (use * for bold)."""

    llm = get_llm()
    response = await call_llm(
        llm, [{"role": "user", "content": prompt}], label="meeting_prep_briefing"
    )

    return response.content


def format_workflow_result(result: dict) -> str:
    """Format the workflow result into a Slack message."""
    if result["status"] == "error":
        return f"❌ {result['briefing']}"

    parts = []
    parts.append("📋 *Meeting Preparation Briefing*")
    parts.append("─" * 30)
    # Convert markdown **bold** to Slack *bold*
    briefing = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result["briefing"])
    parts.append(briefing)

    # Add inter-agent transparency
    ia_results = result.get("inter_agent_results", [])
    if ia_results:
        parts.append("")
        parts.append("🔗 *Inter-Agent Permissions Used:*")
        for r in ia_results:
            icon = "✅" if r["status"] == "allowed" else "🚫"
            parts.append(f"  {icon} {r['requesting']} → {r['target']}: {r['action']}")

    # Add step count
    steps = result.get("steps", [])
    parts.append(
        f"\n📊 Workflow completed in {len(steps)} steps. Full trace logged to audit trail."
    )

    return "\n".join(parts)
