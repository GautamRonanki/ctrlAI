"""
CIBA Service for ctrlAI.
Triggers Auth0 Client-Initiated Backchannel Authentication for high-stakes actions.
User receives a Guardian push notification and must approve before the action proceeds.
"""

import os
import time
import asyncio

import httpx
from loguru import logger
from dotenv import load_dotenv

from core.logger import log_ciba_event

load_dotenv()

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")

# Polling config
CIBA_POLL_INTERVAL = 5  # seconds between polls
CIBA_TIMEOUT = 120  # max seconds to wait for approval


async def request_approval(
    user_id: str,
    agent_name: str,
    action: str,
    binding_message: str,
) -> dict:
    """
    Trigger a CIBA approval request. Returns the auth_req_id for polling.

    Args:
        user_id: Auth0 user ID (e.g., "auth0|abc123")
        agent_name: Which agent is requesting
        action: What action needs approval
        binding_message: Human-readable message shown on Guardian
    """
    log_ciba_event(
        agent_name,
        action,
        "requested",
        {"user_id": user_id, "message": binding_message},
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/bc-authorize",
            data={
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "login_hint": f'{{ "format": "iss_sub", "iss": "https://{AUTH0_DOMAIN}/", "sub": "{user_id}" }}',
                "scope": "openid",
                "binding_message": binding_message,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        logger.error(f"CIBA request failed: {response.text}")
        log_ciba_event(agent_name, action, "request_failed", {"error": response.text})
        return {"status": "error", "error": response.json()}

    data = response.json()
    auth_req_id = data.get("auth_req_id")

    log_ciba_event(agent_name, action, "pending", {"auth_req_id": auth_req_id})
    logger.info(
        f"CIBA request sent. auth_req_id={auth_req_id}. Waiting for user approval on Guardian..."
    )

    return {"status": "pending", "auth_req_id": auth_req_id}


async def poll_for_approval(auth_req_id: str, agent_name: str, action: str) -> dict:
    """
    Poll Auth0 token endpoint for CIBA approval result.
    Returns when user approves, denies, or timeout is reached.
    """
    start_time = time.time()

    while (time.time() - start_time) < CIBA_TIMEOUT:
        await asyncio.sleep(CIBA_POLL_INTERVAL)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://{AUTH0_DOMAIN}/oauth/token",
                data={
                    "grant_type": "urn:openid:params:grant-type:ciba",
                    "client_id": AUTH0_CLIENT_ID,
                    "client_secret": AUTH0_CLIENT_SECRET,
                    "auth_req_id": auth_req_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        data = response.json()

        if response.status_code == 200:
            # User approved
            log_ciba_event(agent_name, action, "approved", {"auth_req_id": auth_req_id})
            logger.info(f"CIBA approved for {agent_name}:{action}")
            return {"status": "approved", "tokens": data}

        error = data.get("error")

        if error == "authorization_pending":
            # Still waiting - continue polling
            continue

        if error == "slow_down":
            # Polling too fast - wait longer
            await asyncio.sleep(CIBA_POLL_INTERVAL)
            continue

        if error == "access_denied":
            # User denied
            log_ciba_event(agent_name, action, "denied", {"auth_req_id": auth_req_id})
            logger.info(f"CIBA denied for {agent_name}:{action}")
            return {"status": "denied"}

        if error == "expired_token":
            # Request expired
            log_ciba_event(agent_name, action, "expired", {"auth_req_id": auth_req_id})
            logger.info(f"CIBA expired for {agent_name}:{action}")
            return {"status": "expired"}

        # Unknown error
        log_ciba_event(agent_name, action, "error", {"error": data})
        return {"status": "error", "error": data}

    # Timeout
    log_ciba_event(agent_name, action, "timeout", {"auth_req_id": auth_req_id})
    logger.warning(f"CIBA timeout for {agent_name}:{action}")
    return {"status": "timeout"}


async def request_and_wait_for_approval(
    user_id: str,
    agent_name: str,
    action: str,
    binding_message: str,
) -> dict:
    """
    Full CIBA flow: request approval and wait for result.
    Returns {"status": "approved"} or {"status": "denied"/"expired"/"timeout"/"error"}.
    """
    request_result = await request_approval(
        user_id, agent_name, action, binding_message
    )

    if request_result["status"] != "pending":
        return request_result

    return await poll_for_approval(request_result["auth_req_id"], agent_name, action)
