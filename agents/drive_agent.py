"""
Google Drive Agent for ctrlAI.
Manages your Google Drive - accessing, organizing, and maintaining your files and documents.
Each function checks permissions before executing.
"""

import time
import httpx
from loguru import logger

from core.permissions import check_scope_permission, is_high_stakes
from core.logger import log_api_call, log_audit

DRIVE_BASE = "https://www.googleapis.com/drive/v3"


async def list_files(
    google_token: str, max_results: int = 10, agent_name: str = "drive_agent"
) -> dict:
    """List recent files in Google Drive."""
    if not check_scope_permission(agent_name, "list_files"):
        return {
            "error": f"Permission denied: {agent_name} does not have list_files scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DRIVE_BASE}/files",
            params={
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "drive", "files.list", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Drive API error: {response.status_code}",
            "details": response.json(),
        }

    files = response.json().get("files", [])
    results = []
    for f in files:
        results.append(
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "type": f.get("mimeType", ""),
                "modified": f.get("modifiedTime", ""),
                "size": f.get("size", ""),
                "link": f.get("webViewLink", ""),
            }
        )

    return {"count": len(results), "files": results}


async def search_files(
    google_token: str,
    query: str,
    max_results: int = 10,
    agent_name: str = "drive_agent",
) -> dict:
    """Search files in Google Drive by name."""
    if not check_scope_permission(agent_name, "search_files"):
        return {
            "error": f"Permission denied: {agent_name} does not have search_files scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DRIVE_BASE}/files",
            params={
                "q": f"name contains '{query}'",
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
            },
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "drive", "files.search", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"Drive search failed: {response.status_code}",
            "details": response.json(),
        }

    files = response.json().get("files", [])
    results = []
    for f in files:
        results.append(
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "type": f.get("mimeType", ""),
                "modified": f.get("modifiedTime", ""),
                "link": f.get("webViewLink", ""),
            }
        )

    return {"query": query, "count": len(results), "files": results}


async def delete_file(
    google_token: str, file_id: str, agent_name: str = "drive_agent"
) -> dict:
    """
    Delete a file from Google Drive. HIGH-STAKES action - requires CIBA approval.
    Caller must verify CIBA approval BEFORE calling this function.
    """
    if not check_scope_permission(agent_name, "delete_files"):
        return {
            "error": f"Permission denied: {agent_name} does not have delete_files scope"
        }

    if is_high_stakes(agent_name, "delete_files"):
        log_audit(
            event_type="high_stakes_action",
            agent_name=agent_name,
            action="delete_files",
            status="executing",
            details={"file_id": file_id},
        )

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{DRIVE_BASE}/files/{file_id}",
            headers={"Authorization": f"Bearer {google_token}"},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "drive", "files.delete", response.status_code, latency)

    if response.status_code != 204:
        return {
            "error": f"Delete failed: {response.status_code}",
            "details": response.json() if response.text else {},
        }

    log_audit(
        event_type="action_completed",
        agent_name=agent_name,
        action="delete_files",
        status="success",
        details={"file_id": file_id},
    )

    return {"status": "deleted", "file_id": file_id}
