"""
Token Service for ctrlAI.
Retrieves third-party OAuth tokens via Auth0 Token Vault exchange.
Agents call get_google_token/get_github_token - Token Vault handles the rest.
"""

import os

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")


async def get_token_via_vault(refresh_token: str, connection: str) -> dict | None:
    """
    Exchange an Auth0 refresh token for an external provider's access token via Token Vault.
    This is the production pattern - agents call this, never the Management API.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "subject_token": refresh_token,
                "grant_type": "urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token",
                "subject_token_type": "urn:ietf:params:oauth:token-type:refresh_token",
                "requested_token_type": "http://auth0.com/oauth/token-type/federated-connection-access-token",
                "connection": connection,
            },
        )

    if response.status_code != 200:
        logger.error(
            f"Token Vault exchange failed for {connection}: {response.status_code} {response.text}"
        )
        return None

    data = response.json()
    logger.info(
        f"Token Vault exchange success for {connection} | expires_in={data.get('expires_in')}"
    )
    return data


async def get_google_token(refresh_token: str) -> str | None:
    """Get a Google access token via Token Vault exchange."""
    result = await get_token_via_vault(refresh_token, "google-oauth2")
    if result:
        return result.get("access_token")
    return None


async def get_github_token(refresh_token: str) -> str | None:
    """Get a GitHub access token via Token Vault exchange."""
    result = await get_token_via_vault(refresh_token, "github")
    if result:
        return result.get("access_token")
    return None
