"""
Agent API routes for ctrlAI.
These endpoints expose agent functionality via HTTP for testing.
In production, these are called by the LangGraph orchestrator, not directly.
"""

import os
from fastapi import APIRouter, Request, HTTPException, Query
from core.token_service import get_google_token

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _get_google_token_or_fail(request: Request) -> str:
    """Helper to get Google token from the logged-in user."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    user_id = user.get("sub")
    token = await get_google_token(user_id)
    if not token:
        raise HTTPException(
            status_code=400, detail="No Google token available. Re-login with Google."
        )

    return token


@router.get("/gmail/list")
async def gmail_list(request: Request, max_results: int = Query(default=5, le=20)):
    """List recent emails."""
    from agents.gmail_agent import list_emails

    token = await _get_google_token_or_fail(request)
    result = await list_emails(token, max_results=max_results)
    return result


@router.get("/gmail/read/{message_id}")
async def gmail_read(request: Request, message_id: str):
    """Read a specific email."""
    from agents.gmail_agent import read_email

    token = await _get_google_token_or_fail(request)
    result = await read_email(token, message_id)
    return result


@router.get("/gmail/search")
async def gmail_search(
    request: Request, q: str = Query(...), max_results: int = Query(default=5, le=20)
):
    """Search emails."""
    from agents.gmail_agent import search_emails

    token = await _get_google_token_or_fail(request)
    result = await search_emails(token, query=q, max_results=max_results)
    return result


@router.get("/gmail/unauthorized-test")
async def gmail_unauthorized_test(request: Request):
    """
    Test that a non-Gmail agent cannot access Gmail.
    This demonstrates permission enforcement — the core of ctrlAI.
    """
    from agents.gmail_agent import list_emails

    token = await _get_google_token_or_fail(request)
    # Try to use Gmail with the github_agent identity — should be BLOCKED
    result = await list_emails(token, max_results=1, agent_name="github_agent")
    return result


@router.get("/gmail/send")
async def gmail_send_with_ciba(
    request: Request,
    to: str,
    subject: str = "Test from ctrlAI",
    body: str = "This email was sent by the ctrlAI Gmail Agent after CIBA approval.",
):
    """
    Send an email with CIBA approval.
    Triggers Guardian push notification — user must approve on their phone.
    """
    from agents.gmail_agent import send_email
    from core.ciba_service import request_and_wait_for_approval
    from core.permissions import is_high_stakes

    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    token = await _get_google_token_or_fail(request)

    # Check if this is a high-stakes action
    if is_high_stakes("gmail_agent", "send_email"):
        # Trigger CIBA — user must approve on Guardian
        ciba_result = await request_and_wait_for_approval(
            user_id=os.getenv("EMERGENCY_COORDINATOR_USER_ID"),
            agent_name="gmail_agent",
            action="send_email",
            binding_message=f"ctrlAI Gmail Agent: send email",
        )

        if ciba_result["status"] != "approved":
            return {
                "status": "blocked",
                "reason": f"CIBA {ciba_result['status']}",
                "details": ciba_result,
            }

    # CIBA approved — send the email
    result = await send_email(token, to=to, subject=subject, body=body)
    return result
