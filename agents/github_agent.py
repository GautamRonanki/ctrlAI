"""
GitHub Agent for ctrlAI.
Manages your GitHub workflow — monitoring repositories, issues, and code activity.
Each function checks permissions before executing.
"""

import time
import httpx
from loguru import logger

from core.permissions import check_scope_permission, is_high_stakes
from core.logger import log_api_call, log_audit

GITHUB_BASE = "https://api.github.com"


async def list_repos(
    github_token: str, max_results: int = 10, agent_name: str = "github_agent"
) -> dict:
    """List user's repositories."""
    if not check_scope_permission(agent_name, "list_repos"):
        return {
            "error": f"Permission denied: {agent_name} does not have list_repos scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_BASE}/user/repos",
            params={"per_page": max_results, "sort": "updated"},
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "github", "repos.list", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"GitHub API error: {response.status_code}",
            "details": response.json(),
        }

    repos = response.json()
    results = []
    for repo in repos:
        results.append(
            {
                "name": repo.get("full_name"),
                "description": repo.get("description", ""),
                "language": repo.get("language", ""),
                "stars": repo.get("stargazers_count", 0),
                "updated": repo.get("updated_at", ""),
                "url": repo.get("html_url", ""),
                "private": repo.get("private", False),
            }
        )

    return {"count": len(results), "repos": results}


async def list_issues(
    github_token: str,
    owner: str,
    repo: str,
    max_results: int = 10,
    agent_name: str = "github_agent",
) -> dict:
    """List issues for a repository."""
    if not check_scope_permission(agent_name, "list_issues"):
        return {
            "error": f"Permission denied: {agent_name} does not have list_issues scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_BASE}/repos/{owner}/{repo}/issues",
            params={"per_page": max_results, "state": "open"},
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "github", "issues.list", response.status_code, latency)

    if response.status_code != 200:
        return {
            "error": f"GitHub API error: {response.status_code}",
            "details": response.json(),
        }

    issues = response.json()
    results = []
    for issue in issues:
        results.append(
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "author": issue.get("user", {}).get("login", ""),
                "created": issue.get("created_at", ""),
                "url": issue.get("html_url", ""),
                "labels": [l.get("name") for l in issue.get("labels", [])],
            }
        )

    return {"repo": f"{owner}/{repo}", "count": len(results), "issues": results}


async def create_comment(
    github_token: str,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
    agent_name: str = "github_agent",
) -> dict:
    """
    Create a comment on a GitHub issue. HIGH-STAKES action — requires CIBA approval.
    Caller must verify CIBA approval BEFORE calling this function.
    """
    if not check_scope_permission(agent_name, "post_comments"):
        return {
            "error": f"Permission denied: {agent_name} does not have post_comments scope"
        }

    if is_high_stakes(agent_name, "post_comments"):
        log_audit(
            event_type="high_stakes_action",
            agent_name=agent_name,
            action="post_comments",
            status="executing",
            details={"repo": f"{owner}/{repo}", "issue": issue_number},
        )

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
            json={"body": body},
        )
    latency = (time.time() - start) * 1000
    log_api_call(agent_name, "github", "comments.create", response.status_code, latency)

    if response.status_code != 201:
        return {
            "error": f"Comment failed: {response.status_code}",
            "details": response.json(),
        }

    result = response.json()
    log_audit(
        event_type="action_completed",
        agent_name=agent_name,
        action="post_comments",
        status="success",
        details={
            "repo": f"{owner}/{repo}",
            "issue": issue_number,
            "comment_id": result.get("id"),
        },
    )

    return {
        "status": "commented",
        "comment_id": result.get("id"),
        "url": result.get("html_url", ""),
    }
