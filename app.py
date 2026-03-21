"""
ctrlAI — Main FastAPI Application
Manual auth implementation with Connected Accounts flow for Token Vault.
"""

import os
import secrets
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
import httpx

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", secrets.token_hex(32))

app = FastAPI(title="ctrlAI")
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)
from agents.agent_routes import router as agent_router

app.include_router(agent_router)


@app.get("/")
async def home(request: Request):
    user = request.session.get("user")
    if user:
        connected = request.session.get("google_connected", False)
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif; max-width:600px; margin:40px auto;">
        <h1>ctrlAI</h1>
        <p>Logged in as <b>{user.get("email", user.get("sub"))}</b></p>
        <p>User ID: {user.get("sub")}</p>
        <p>Has refresh token: <b>{bool(request.session.get("refresh_token"))}</b></p>
        <p>Google Connected Account: <b>{"YES" if connected else "NO"}</b></p>
        <p>GitHub Connected Account: <b>{"YES" if request.session.get("github_connected") else "NO"}</b></p>
        <hr>
        <h3>Steps:</h3>
        <ol>
            <li>{"&#9989;" if user else "&#10060;"} <a href="/login">Login</a> (done!)</li>
            <li>{"&#9989;" if connected else "&#10145;"} <a href="/connect/google">Connect Google Account to Token Vault</a></li>
            <li>{"&#9989;" if request.session.get("github_connected") else "&#10145;"} <a href="/connect/github">Connect GitHub Account to Token Vault</a></li>
            <li><a href="/test/gmail">Test Gmail via Token Vault</a></li>
            <li><a href="/api/agents/github/repos">Test GitHub via Token Vault</a></li>
        </ol>
        <hr>
        <p><a href="/agents">View Agent Registry</a> | <a href="/audit">View Audit Log</a> | <a href="/logout">Logout</a></p>
        </body></html>
        """)
    return HTMLResponse("""
    <html><body style="font-family:sans-serif; max-width:600px; margin:40px auto;">
    <h1>ctrlAI</h1>
    <p>Identity and Permission Control Plane for AI Agents</p>
    <p><a href="/login">Login with email/password</a></p>
    </body></html>
    """)


@app.get("/login")
async def login(request: Request):
    params = {
        "response_type": "code",
        "client_id": AUTH0_CLIENT_ID,
        "redirect_uri": f"{APP_BASE_URL}/callback",
        "scope": "openid profile email offline_access",
        "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
        "connection": "google-oauth2",
        "access_type": "offline",
        "prompt": "consent",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"https://{AUTH0_DOMAIN}/authorize?{query}")


@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error:
        return JSONResponse(
            {
                "error": error,
                "description": request.query_params.get("error_description"),
            },
            status_code=400,
        )
    if not code:
        return JSONResponse(
            {"error": "No authorization code received"}, status_code=400
        )

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{APP_BASE_URL}/callback",
            },
        )
    if token_response.status_code != 200:
        return JSONResponse(
            {"error": "Token exchange failed", "details": token_response.json()},
            status_code=400,
        )

    tokens = token_response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    async with httpx.AsyncClient() as client:
        userinfo = await client.get(
            f"https://{AUTH0_DOMAIN}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    user = userinfo.json() if userinfo.status_code == 200 else {"sub": "unknown"}

    request.session["user"] = user
    request.session["access_token"] = access_token
    if refresh_token:
        request.session["refresh_token"] = refresh_token

    logger.info(
        f"Login: {user.get('email')} | refresh_token={refresh_token is not None}"
    )
    return RedirectResponse("/")


@app.get("/connect/google")
async def connect_google(request: Request):
    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="No refresh token. Login again with consent."
        )

    # Step 1: Exchange refresh token for My Account API access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "audience": f"https://{AUTH0_DOMAIN}/me/",
                "scope": "openid profile offline_access create:me:connected_accounts read:me:connected_accounts delete:me:connected_accounts",
            },
        )

    if token_resp.status_code != 200:
        logger.error(
            f"MRRT exchange failed: {token_resp.status_code} {token_resp.text}"
        )
        return JSONResponse(
            {
                "error": "Failed to get My Account API token",
                "details": token_resp.json(),
            },
            status_code=400,
        )

    me_token = token_resp.json().get("access_token")

    # Step 2: Initiate Connected Accounts flow with the My Account API token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/connect",
            headers={
                "Authorization": f"Bearer {me_token}",
                "Content-Type": "application/json",
            },
            json={
                "connection": "google-oauth2",
                "scopes": [
                    "openid",
                    "profile",
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.send",
                    "https://www.googleapis.com/auth/calendar.readonly",
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive.file",
                ],
                "redirect_uri": f"{APP_BASE_URL}/connect/google/callback",
            },
        )

    if response.status_code not in (200, 201):
        logger.error(
            f"Connected Accounts failed: {response.status_code} {response.text}"
        )
        return JSONResponse(
            {
                "error": "Connected Accounts failed",
                "status": response.status_code,
                "details": response.json(),
            },
            status_code=400,
        )

    data = response.json()
    connect_uri = data.get("connect_uri")
    auth_session = data.get("auth_session")
    connect_params = data.get("connect_params", {})
    ticket = connect_params.get("ticket")

    if connect_uri and ticket:
        request.session["connect_auth_session"] = auth_session
        request.session["me_access_token"] = me_token
        return RedirectResponse(f"{connect_uri}?ticket={ticket}")
    return JSONResponse(
        {"error": "No connect_uri or ticket", "data": data}, status_code=400
    )


@app.get("/connect/google/callback")
async def connect_google_callback(request: Request):
    connect_code = request.query_params.get("connect_code")

    if not connect_code:
        return HTMLResponse("""
        <html><body><script>
            const hash = window.location.hash.substring(1);
            const params = new URLSearchParams(hash);
            const code = params.get('connect_code');
            if (code) { window.location.href = '/connect/google/complete?connect_code=' + code; }
            else { document.body.innerHTML = '<p>Error: No connect_code. Hash: ' + window.location.hash + '</p>'; }
        </script><p>Processing...</p></body></html>
        """)

    return RedirectResponse(f"/connect/google/complete?connect_code={connect_code}")


@app.get("/connect/google/complete")
async def connect_google_complete(request: Request, connect_code: str):
    auth_session = request.session.get("connect_auth_session")
    access_token = request.session.get("me_access_token")
    if not auth_session or not access_token:
        raise HTTPException(status_code=401, detail="Session expired. Login again.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/complete",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "auth_session": auth_session,
                "connect_code": connect_code,
                "redirect_uri": f"{APP_BASE_URL}/connect/google/callback",
            },
        )

    if response.status_code in (200, 201):
        request.session["google_connected"] = True
        logger.info("Google Connected Account linked!")
        return RedirectResponse("/")
    logger.error(f"Connection failed: {response.text}")
    return JSONResponse(
        {"error": "Connection failed", "details": response.json()}, status_code=400
    )


async def get_token_via_vault(refresh_token: str, connection: str) -> dict:
    """
    Exchange an Auth0 refresh token for an external provider's access token via Token Vault.
    This is the production pattern — agents call this, never the Management API.
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


# ============================================================
# GitHub Connected Account
# ============================================================
@app.get("/connect/github")
async def connect_github(request: Request):
    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="No refresh token. Login again with consent."
        )

    # Exchange refresh token for My Account API access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "audience": f"https://{AUTH0_DOMAIN}/me/",
                "scope": "openid profile offline_access create:me:connected_accounts read:me:connected_accounts delete:me:connected_accounts",
            },
        )

    if token_resp.status_code != 200:
        logger.error(
            f"MRRT exchange failed: {token_resp.status_code} {token_resp.text}"
        )
        return JSONResponse(
            {
                "error": "Failed to get My Account API token",
                "details": token_resp.json(),
            },
            status_code=400,
        )

    me_token = token_resp.json().get("access_token")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/connect",
            headers={
                "Authorization": f"Bearer {me_token}",
                "Content-Type": "application/json",
            },
            json={
                "connection": "github",
                "scopes": ["repo", "read:user", "user:email"],
                "redirect_uri": f"{APP_BASE_URL}/connect/github/callback",
            },
        )

    if response.status_code not in (200, 201):
        logger.error(
            f"GitHub Connected Accounts failed: {response.status_code} {response.text}"
        )
        return JSONResponse(
            {
                "error": "GitHub Connected Accounts failed",
                "status": response.status_code,
                "details": response.json(),
            },
            status_code=400,
        )

    data = response.json()
    connect_uri = data.get("connect_uri")
    auth_session = data.get("auth_session")
    connect_params = data.get("connect_params", {})
    ticket = connect_params.get("ticket")

    if connect_uri and ticket:
        request.session["github_connect_auth_session"] = auth_session
        request.session["github_me_access_token"] = me_token
        return RedirectResponse(f"{connect_uri}?ticket={ticket}")
    return JSONResponse(
        {"error": "No connect_uri or ticket", "data": data}, status_code=400
    )


@app.get("/connect/github/callback")
async def connect_github_callback(request: Request):
    # Check all possible locations for the connect_code
    connect_code = request.query_params.get("connect_code")
    code = request.query_params.get("code")

    # Log everything we receive
    logger.info(f"GitHub callback - query params: {dict(request.query_params)}")
    logger.info(f"GitHub callback - full URL: {request.url}")

    if connect_code:
        return RedirectResponse(f"/connect/github/complete?connect_code={connect_code}")

    if code:
        return RedirectResponse(f"/connect/github/complete?connect_code={code}")

    # If nothing in query params, try to extract from hash via JS
    return HTMLResponse(f"""
    <html><body><script>
        const hash = window.location.hash.substring(1);
        const search = window.location.search.substring(1);
        const allParams = hash + '&' + search;
        const params = new URLSearchParams(allParams);
        const cc = params.get('connect_code') || params.get('code');
        if (cc) {{ window.location.href = '/connect/github/complete?connect_code=' + cc; }}
        else {{ document.body.innerHTML = '<p>Debug: No connect_code found.<br>Hash: ' + window.location.hash + '<br>Search: ' + window.location.search + '<br>Full URL: ' + window.location.href + '</p>'; }}
    </script><p>Processing...</p></body></html>
    """)


@app.get("/connect/github/complete")
async def connect_github_complete(request: Request, connect_code: str):
    auth_session = request.session.get("github_connect_auth_session")
    access_token = request.session.get("github_me_access_token")
    if not auth_session or not access_token:
        raise HTTPException(status_code=401, detail="Session expired. Login again.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/complete",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "auth_session": auth_session,
                "connect_code": connect_code,
                "redirect_uri": f"{APP_BASE_URL}/connect/github/callback",
            },
        )

    if response.status_code in (200, 201):
        request.session["github_connected"] = True
        logger.info("GitHub Connected Account linked!")
        return RedirectResponse("/")
    logger.error(f"GitHub connection failed: {response.text}")
    return JSONResponse(
        {"error": "GitHub connection failed", "details": response.json()},
        status_code=400,
    )


@app.get("/test/gmail")
async def test_gmail(request: Request):
    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token. Login again.")

    # Get Google token via Token Vault exchange (the proper pattern)
    token_data = await get_token_via_vault(refresh_token, "google-oauth2")
    if not token_data:
        return JSONResponse({"error": "Token Vault exchange failed"}, status_code=400)

    google_token = token_data.get("access_token")

    # Use the Google token to read Gmail
    async with httpx.AsyncClient() as client:
        gmail_response = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=5",
            headers={"Authorization": f"Bearer {google_token}"},
        )

    if gmail_response.status_code != 200:
        return JSONResponse(
            {"error": "Gmail API failed", "details": gmail_response.json()},
            status_code=400,
        )

    messages = gmail_response.json().get("messages", [])
    return {
        "status": "SUCCESS — Token retrieved via Token Vault exchange!",
        "method": "Token Vault (refresh token exchange)",
        "scopes": token_data.get("scope"),
        "expires_in": token_data.get("expires_in"),
        "gmail_messages_count": len(messages),
        "message_ids": [m["id"] for m in messages],
    }


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(
        f"https://{AUTH0_DOMAIN}/v2/logout?client_id={AUTH0_CLIENT_ID}&returnTo={APP_BASE_URL}/"
    )


@app.get("/agents")
async def list_agents():
    from core.permissions import get_all_agents

    agents = get_all_agents()
    return {
        name: {
            "description": a.description,
            "oauth_provider": a.oauth_provider,
            "permitted_scopes": a.permitted_scopes,
            "high_stakes_actions": a.high_stakes_actions,
            "status": a.status.value,
        }
        for name, a in agents.items()
    }


@app.get("/audit")
async def get_audit_log():
    import json
    from core.logger import AUDIT_LOG_PATH

    if not AUDIT_LOG_PATH.exists():
        return {"entries": []}
    entries = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return {"entries": entries[-100:]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/debug/user")
async def debug_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    user_id = user.get("sub")

    async with httpx.AsyncClient() as client:
        mgmt_token_resp = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
            },
        )

    mgmt_token = mgmt_token_resp.json().get("access_token")

    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            f"https://{AUTH0_DOMAIN}/api/v2/users/{user_id}",
            headers={"Authorization": f"Bearer {mgmt_token}"},
        )

    data = user_resp.json()
    # Show identities but mask tokens
    identities = data.get("identities", [])
    for ident in identities:
        for key in list(ident.keys()):
            if "token" in key.lower() and ident[key]:
                ident[key] = f"{str(ident[key])[:15]}... (exists)"

    return {
        "identities": identities,
        "connected_accounts": data.get("connected_accounts", []),
    }
