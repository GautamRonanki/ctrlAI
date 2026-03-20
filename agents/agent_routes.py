"""
Agent API routes for ctrlAI.
These endpoints expose agent functionality via HTTP for testing.
In production, these are called by the LangGraph orchestrator, not directly.
"""

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
        raise HTTPException(status_code=400, detail="No Google token available. Re-login with Google.")

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
async def gmail_search(request: Request, q: str = Query(...), max_results: int = Query(default=5, le=20)):
    """Search emails."""
    from agents.gmail_agent import search_emails

    token = await _get_google_token_or_fail(request)
    result = await search_emails(token, query=q, max_results=max_results)
    return result
