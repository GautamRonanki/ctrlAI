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
        <hr>
        <h3>Steps:</h3>
        <ol>
            <li>{"&#9989;" if user else "&#10060;"} <a href="/login">Login</a> (done!)</li>
            <li>{"&#9989;" if connected else "&#10145;"} <a href="/connect/google">Connect Google Account to Token Vault</a></li>
            <li><a href="/test/gmail">Test Gmail via Token Vault</a></li>
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
    access_token = request.session.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Not logged in.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "connection": "google-oauth2",
                "scopes": [
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

    if connect_uri:
        request.session["connect_auth_session"] = auth_session
        return RedirectResponse(connect_uri)
    return JSONResponse({"error": "No connect_uri", "data": data}, status_code=400)


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
    access_token = request.session.get("access_token")
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

    if response.status_code == 200:
        request.session["google_connected"] = True
        logger.info("Google Connected Account linked!")
        return RedirectResponse("/")
    logger.error(f"Connection failed: {response.text}")
    return JSONResponse(
        {"error": "Connection failed", "details": response.json()}, status_code=400
    )


@app.get("/test/gmail")
async def test_gmail(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")

    user_id = user.get("sub")

    # Step 1: Get a Management API token
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

    if mgmt_token_resp.status_code != 200:
        return JSONResponse(
            {
                "error": "Failed to get management token",
                "details": mgmt_token_resp.json(),
            },
            status_code=400,
        )

    mgmt_token = mgmt_token_resp.json().get("access_token")

    # Step 2: Get user profile with identities (includes Google access token)
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            f"https://{AUTH0_DOMAIN}/api/v2/users/{user_id}",
            headers={"Authorization": f"Bearer {mgmt_token}"},
        )

    if user_resp.status_code != 200:
        return JSONResponse(
            {"error": "Failed to get user profile", "details": user_resp.json()},
            status_code=400,
        )

    user_data = user_resp.json()
    identities = user_data.get("identities", [])

    # Find Google identity and extract access token
    google_token = None
    for identity in identities:
        if identity.get("provider") == "google-oauth2":
            google_token = identity.get("access_token")
            break

    if not google_token:
        return JSONResponse(
            {"error": "No Google access token found in user identities"},
            status_code=400,
        )

    # Step 3: Use the Google token to read Gmail
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
        "status": "SUCCESS — Google token retrieved via Management API!",
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
