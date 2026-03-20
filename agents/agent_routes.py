"""
Agent API routes for ctrlAI.
Exposes all four agents via HTTP endpoints for testing.
In production, these are called by the LangGraph orchestrator.
"""

import os
from fastapi import APIRouter, Request, HTTPException, Query
from core.token_service import get_google_token, get_github_token

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _get_google_token_or_fail(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")
    token = await get_google_token(user.get("sub"))
    if not token:
        raise HTTPException(
            status_code=400, detail="No Google token. Re-login with Google."
        )
    return token


async def _get_github_token_or_fail(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")
    token = await get_github_token(user.get("sub"))
    if not token:
        raise HTTPException(
            status_code=400, detail="No GitHub token. Login with GitHub required."
        )
    return token


# ============================================================
# Gmail Agent
# ============================================================
@router.get("/gmail/list")
async def gmail_list(request: Request, max_results: int = Query(default=5, le=20)):
    from agents.gmail_agent import list_emails

    token = await _get_google_token_or_fail(request)
    return await list_emails(token, max_results=max_results)


@router.get("/gmail/read/{message_id}")
async def gmail_read(request: Request, message_id: str):
    from agents.gmail_agent import read_email

    token = await _get_google_token_or_fail(request)
    return await read_email(token, message_id)


@router.get("/gmail/search")
async def gmail_search(
    request: Request, q: str = Query(...), max_results: int = Query(default=5, le=20)
):
    from agents.gmail_agent import search_emails

    token = await _get_google_token_or_fail(request)
    return await search_emails(token, query=q, max_results=max_results)


@router.get("/gmail/send")
async def gmail_send_with_ciba(
    request: Request,
    to: str = Query(...),
    subject: str = Query(default="Test from ctrlAI"),
    body: str = Query(
        default="This email was sent by the ctrlAI Gmail Agent after CIBA approval."
    ),
):
    from agents.gmail_agent import send_email
    from core.ciba_service import request_and_wait_for_approval
    from core.permissions import is_high_stakes

    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    token = await _get_google_token_or_fail(request)

    if is_high_stakes("gmail_agent", "send_email"):
        ciba_result = await request_and_wait_for_approval(
            user_id=os.getenv("EMERGENCY_COORDINATOR_USER_ID"),
            agent_name="gmail_agent",
            action="send_email",
            binding_message="ctrlAI Gmail Agent: send email",
        )
        if ciba_result["status"] != "approved":
            return {
                "status": "blocked",
                "reason": f"CIBA {ciba_result['status']}",
                "details": ciba_result,
            }

    return await send_email(token, to=to, subject=subject, body=body)


@router.get("/gmail/unauthorized-test")
async def gmail_unauthorized_test(request: Request):
    from agents.gmail_agent import list_emails

    token = await _get_google_token_or_fail(request)
    return await list_emails(token, max_results=1, agent_name="github_agent")


# ============================================================
# Calendar Agent
# ============================================================
@router.get("/calendar/list")
async def calendar_list(request: Request, max_results: int = Query(default=5, le=20)):
    from agents.calendar_agent import list_events

    token = await _get_google_token_or_fail(request)
    return await list_events(token, max_results=max_results)


@router.get("/calendar/create")
async def calendar_create_with_ciba(
    request: Request,
    summary: str = Query(...),
    start_time: str = Query(
        ..., description="ISO format e.g. 2026-03-21T10:00:00-04:00"
    ),
    end_time: str = Query(..., description="ISO format e.g. 2026-03-21T11:00:00-04:00"),
    description: str = Query(default=""),
):
    from agents.calendar_agent import create_event
    from core.ciba_service import request_and_wait_for_approval
    from core.permissions import is_high_stakes

    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    token = await _get_google_token_or_fail(request)

    if is_high_stakes("calendar_agent", "create_event"):
        ciba_result = await request_and_wait_for_approval(
            user_id=os.getenv("EMERGENCY_COORDINATOR_USER_ID"),
            agent_name="calendar_agent",
            action="create_event",
            binding_message="ctrlAI Calendar Agent: create event",
        )
        if ciba_result["status"] != "approved":
            return {
                "status": "blocked",
                "reason": f"CIBA {ciba_result['status']}",
                "details": ciba_result,
            }

    return await create_event(
        token,
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        description=description,
    )


# ============================================================
# Drive Agent
# ============================================================
@router.get("/drive/list")
async def drive_list(request: Request, max_results: int = Query(default=10, le=50)):
    from agents.drive_agent import list_files

    token = await _get_google_token_or_fail(request)
    return await list_files(token, max_results=max_results)


@router.get("/drive/search")
async def drive_search(
    request: Request, q: str = Query(...), max_results: int = Query(default=10, le=50)
):
    from agents.drive_agent import search_files

    token = await _get_google_token_or_fail(request)
    return await search_files(token, query=q, max_results=max_results)


# ============================================================
# GitHub Agent
# ============================================================
@router.get("/github/repos")
async def github_repos(request: Request, max_results: int = Query(default=10, le=50)):
    from agents.github_agent import list_repos

    token = await _get_github_token_or_fail(request)
    return await list_repos(token, max_results=max_results)


@router.get("/github/issues")
async def github_issues(
    request: Request,
    owner: str = Query(...),
    repo: str = Query(...),
    max_results: int = Query(default=10, le=50),
):
    from agents.github_agent import list_issues

    token = await _get_github_token_or_fail(request)
    return await list_issues(token, owner=owner, repo=repo, max_results=max_results)
