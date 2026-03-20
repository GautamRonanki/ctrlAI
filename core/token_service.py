"""
Token Service for ctrlAI.
Retrieves third-party OAuth tokens (Google, GitHub) via Auth0 Management API.
This is the bridge between agents and external APIs.

NOTE: This uses the Management API approach. If Token Vault Connected Accounts
becomes available, replace get_google_token/get_github_token with Token Vault
token exchange — the interface stays the same.
"""

import os
from functools import lru_cache

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")

# Cache management API token (expires in 24h, we cache for shorter)
_mgmt_token_cache: dict = {"token": None}


async def _get_management_token() -> str:
    """Get a Management API access token using client credentials."""
    if _mgmt_token_cache["token"]:
        return _mgmt_token_cache["token"]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
            },
        )

    if response.status_code != 200:
        logger.error(f"Management token request failed: {response.text}")
        raise Exception(f"Failed to get management token: {response.json()}")

    token = response.json().get("access_token")
    _mgmt_token_cache["token"] = token
    return token


async def _get_user_identity(user_id: str, provider: str) -> dict | None:
    """Get a specific identity from a user's profile."""
    mgmt_token = await _get_management_token()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://{AUTH0_DOMAIN}/api/v2/users/{user_id}",
            headers={"Authorization": f"Bearer {mgmt_token}"},
        )

    if response.status_code != 200:
        logger.error(f"User profile request failed: {response.text}")
        return None

    identities = response.json().get("identities", [])
    for identity in identities:
        if identity.get("provider") == provider:
            return identity

    return None


async def get_google_token(user_id: str) -> str | None:
    """
    Get a Google access token for a user.
    Returns the access token string, or None if not available.
    """
    identity = await _get_user_identity(user_id, "google-oauth2")
    if identity and identity.get("access_token"):
        logger.info(f"Google token retrieved for user {user_id[:20]}...")
        return identity["access_token"]

    logger.warning(f"No Google token found for user {user_id}")
    return None


async def get_github_token(user_id: str) -> str | None:
    """
    Get a GitHub access token for a user.
    Returns the access token string, or None if not available.
    """
    identity = await _get_user_identity(user_id, "github")
    if identity and identity.get("access_token"):
        logger.info(f"GitHub token retrieved for user {user_id[:20]}...")
        return identity["access_token"]

    logger.warning(f"No GitHub token found for user {user_id}")
    return None


def clear_management_token_cache():
    """Clear the cached management token (call if token expires)."""
    _mgmt_token_cache["token"] = None
