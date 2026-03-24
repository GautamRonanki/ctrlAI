"""
Gmail Agent for ctrlAI.
Manages your Gmail inbox — reading, composing, and organizing emails on your behalf.
Each function checks permissions before executing.
"""

import base64
from email.mime.text import MIMEText

import httpx
from loguru import logger

from core.permissions import check_scope_permission, is_high_stakes
from core.logger import log_api_call, log_audit
import time

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


async def list_emails(
    google_token: str, max_results: int = 5, agent_name: str = "gmail_agent"
) -> dict:
    """List recent emails from the user's inbox."""
    if not check_scope_permission(agent_name, "list_emails"):
        return {
            "error": f"Permission denied: {agent_name} does not have list_emails scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GMAIL_BASE}/messages?maxResults={max_results}",
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "gmail", "messages.list", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Gmail API error: {response.status_code}",
            "details": response.json(),
        }

    messages = response.json().get("messages", [])

    results = []
    for msg in messages:
        detail = await _get_message_detail(google_token, msg["id"], agent_name)
        if detail:
            results.append(detail)

    return {"count": len(results), "emails": results}


async def read_email(
    google_token: str, message_id: str, agent_name: str = "gmail_agent"
) -> dict:
    """Read a specific email by ID."""
    if not check_scope_permission(agent_name, "read_emails"):
        return {
            "error": f"Permission denied: {agent_name} does not have read_emails scope"
        }

    return await _get_message_detail(google_token, message_id, agent_name)


async def send_email(
    google_token: str,
    to: str,
    subject: str,
    body: str,
    agent_name: str = "gmail_agent",
) -> dict:
    """
    Send an email. This is a HIGH-STAKES action — requires CIBA approval.
    The caller must verify CIBA approval BEFORE calling this function.
    """
    if not check_scope_permission(agent_name, "send_emails"):
        return {
            "error": f"Permission denied: {agent_name} does not have send_emails scope"
        }

    if is_high_stakes(agent_name, "send_emails"):
        log_audit(
            event_type="high_stakes_action",
            agent_name=agent_name,
            action="send_emails",
            status="executing",
            details={"to": to, "subject": subject},
        )

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GMAIL_BASE}/messages/send",
            headers={
                "Authorization": f"Bearer {google_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "gmail", "messages.send", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Send failed: {response.status_code}",
            "details": response.json(),
        }

    result = response.json()
    log_audit(
        event_type="action_completed",
        agent_name=agent_name,
        action="send_emails",
        status="success",
        details={"to": to, "subject": subject, "message_id": result.get("id")},
    )

    return {"status": "sent", "message_id": result.get("id")}


async def search_emails(
    google_token: str, query: str, max_results: int = 5, agent_name: str = "gmail_agent"
) -> dict:
    """Search emails by query string (Gmail search syntax)."""
    if not check_scope_permission(agent_name, "search_emails"):
        return {
            "error": f"Permission denied: {agent_name} does not have search_emails scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GMAIL_BASE}/messages?q={query}&maxResults={max_results}",
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "gmail", "messages.search", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Search failed: {response.status_code}",
            "details": response.json(),
        }

    messages = response.json().get("messages", [])
    results = []
    for msg in messages:
        detail = await _get_message_detail(google_token, msg["id"], agent_name)
        if detail:
            results.append(detail)

    return {"query": query, "count": len(results), "emails": results}


async def _get_message_detail(
    google_token: str, message_id: str, agent_name: str
) -> dict | None:
    """Fetch details of a single email message."""
    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GMAIL_BASE}/messages/{message_id}?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date",
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000

    if response.status_code != 200:
        return None

    data = response.json()
    headers = {
        h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])
    }

    return {
        "id": data.get("id"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "snippet": data.get("snippet", ""),
    }
