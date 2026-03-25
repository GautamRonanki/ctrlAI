"""
Google Calendar Agent for ctrlAI.
Manages your Google Calendar - viewing your schedule and coordinating events on your behalf.
Each function checks permissions before executing.
"""

import time
import httpx
from loguru import logger

from core.permissions import check_scope_permission, is_high_stakes
from core.logger import log_api_call, log_audit

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"


async def list_events(
    google_token: str, max_results: int = 5, agent_name: str = "calendar_agent"
) -> dict:
    """List upcoming calendar events."""
    if not check_scope_permission(agent_name, "list_events"):
        return {
            "error": f"Permission denied: {agent_name} does not have list_events scope"
        }

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CALENDAR_BASE}/calendars/primary/events",
            params={
                "maxResults": max_results,
                "timeMin": now,
                "singleEvents": "true",
                "orderBy": "startTime",
                "fields": "items(id,summary,start,end,location,description,attendees,status)",
            },
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "calendar", "events.list", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Calendar API error: {response.status_code}",
            "details": response.json(),
        }

    events = response.json().get("items", [])
    results = []
    for event in events:
        attendees = [a.get("email", "") for a in event.get("attendees", [])]
        results.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary", "No title"),
                "start": event.get("start", {}).get(
                    "dateTime", event.get("start", {}).get("date", "")
                ),
                "end": event.get("end", {}).get(
                    "dateTime", event.get("end", {}).get("date", "")
                ),
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "attendees": attendees,
                "status": event.get("status", ""),
            }
        )

    return {"count": len(results), "events": results}


async def create_event(
    google_token: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    agent_name: str = "calendar_agent",
) -> dict:
    """
    Create a calendar event. HIGH-STAKES action - requires CIBA approval.
    Caller must verify CIBA approval BEFORE calling this function.

    start_time and end_time should be ISO format (e.g., "2026-03-21T10:00:00-04:00")
    """
    if not check_scope_permission(agent_name, "create_events"):
        return {
            "error": f"Permission denied: {agent_name} does not have create_events scope"
        }

    if is_high_stakes(agent_name, "create_events"):
        log_audit(
            event_type="high_stakes_action",
            agent_name=agent_name,
            action="create_events",
            status="executing",
            details={"summary": summary, "start": start_time},
        )

    event_body = {
        "summary": summary,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{CALENDAR_BASE}/calendars/primary/events",
            headers={
                "Authorization": f"Bearer {google_token}",
                "Content-Type": "application/json",
            },
            json=event_body,
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "calendar", "events.create", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Create event failed: {response.status_code}",
            "details": response.json(),
        }

    result = response.json()
    log_audit(
        event_type="action_completed",
        agent_name=agent_name,
        action="create_events",
        status="success",
        details={"summary": summary, "event_id": result.get("id")},
    )

    return {
        "status": "created",
        "event_id": result.get("id"),
        "link": result.get("htmlLink", ""),
    }
