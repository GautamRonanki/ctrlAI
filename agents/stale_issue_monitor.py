"""
Stale Issue Monitor - Autonomous OAuth Agent for ctrlAI.
Autonomous GitHub monitor - identifies inactive issues and keeps your project board healthy.

This agent retrieves its own GitHub OAuth token from Token Vault directly.
It is not triggered by employees - it runs on schedule or manual trigger.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from loguru import logger

from core.permissions import check_scope_permission, is_agent_active, is_high_stakes
from core.logger import log_audit, log_api_call
from core.llm import get_llm, call_llm
from core.token_service import get_github_token

GITHUB_BASE = "https://api.github.com"
AGENT_NAME = "stale_issue_monitor"

# Default repo to monitor - can be overridden
DEFAULT_OWNER = "GautamRonanki"
DEFAULT_REPO = "ctrlAI"


async def _fetch_open_issues(
    github_token: str, owner: str, repo: str
) -> list[dict] | None:
    """Fetch all open issues from a repo."""
    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_BASE}/repos/{owner}/{repo}/issues",
            params={"state": "open", "per_page": 100},
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
    latency = (time.time() - start) * 1000
    log_api_call(AGENT_NAME, "github", "issues.list", response.status_code, latency)

    if response.status_code != 200:
        logger.error(f"GitHub API error: {response.status_code} {response.text}")
        return None

    issues = [i for i in response.json() if "pull_request" not in i]
    return issues


def _categorize_issues(issues: list[dict], threshold_days: int = 7) -> dict:
    """Categorize issues by staleness relative to threshold."""
    now = datetime.now(timezone.utc)
    categories = {
        "one_to_two_weeks": [],
        "two_weeks": [],
        "two_plus_weeks": [],
        "active": [],
    }

    two_week_threshold = threshold_days * 2

    for issue in issues:
        updated_str = issue.get("updated_at", issue.get("created_at", ""))
        if not updated_str:
            continue

        updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
        days_inactive = (now - updated_at).days

        entry = {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "author": issue.get("user", {}).get("login", ""),
            "url": issue.get("html_url", ""),
            "days_inactive": days_inactive,
            "updated_at": updated_str,
            "labels": [l.get("name") for l in issue.get("labels", [])],
        }

        if days_inactive > two_week_threshold:
            categories["two_plus_weeks"].append(entry)
        elif days_inactive == two_week_threshold:
            categories["two_weeks"].append(entry)
        elif days_inactive >= threshold_days:
            categories["one_to_two_weeks"].append(entry)
        else:
            categories["active"].append(entry)

    return categories


async def _post_stale_comment(
    github_token: str, owner: str, repo: str, issue_number: int, days_inactive: int
) -> dict:
    """Post a comment on a stale issue. HIGH-STAKES - caller must verify CIBA."""
    if not check_scope_permission(AGENT_NAME, "post_comments"):
        return {
            "error": f"Permission denied: {AGENT_NAME} does not have post_comments scope"
        }

    body = (
        f"🤖 **ctrlAI Stale Issue Monitor**\n\n"
        f"This issue has had no activity for **{days_inactive} days**. "
        f"Is this still relevant? If so, please provide an update. "
        f"If not, consider closing it.\n\n"
        f"*This comment was posted by an autonomous agent governed by ctrlAI.*"
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
    log_api_call(AGENT_NAME, "github", "comments.create", response.status_code, latency)

    if response.status_code != 201:
        return {"error": f"Comment failed: {response.status_code}"}

    result = response.json()
    log_audit(
        "action_completed",
        AGENT_NAME,
        "post_comments",
        "success",
        {
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


async def _add_stale_label(
    github_token: str, owner: str, repo: str, issue_number: int
) -> dict:
    """Add a 'stale' label to an issue. HIGH-STAKES - caller must verify CIBA."""
    if not check_scope_permission(AGENT_NAME, "add_labels"):
        return {
            "error": f"Permission denied: {AGENT_NAME} does not have add_labels scope"
        }

    start = time.time()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_BASE}/repos/{owner}/{repo}/issues/{issue_number}/labels",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
            json={"labels": ["stale"]},
        )
    latency = (time.time() - start) * 1000
    log_api_call(AGENT_NAME, "github", "labels.add", response.status_code, latency)

    if response.status_code not in (200, 201):
        return {"error": f"Label failed: {response.status_code}"}

    log_audit(
        "action_completed",
        AGENT_NAME,
        "add_labels",
        "success",
        {
            "repo": f"{owner}/{repo}",
            "issue": issue_number,
        },
    )
    return {"status": "labeled", "label": "stale"}


async def run_stale_issue_monitor(
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    execute_actions: bool = False,
    ciba_approved: bool = False,
    stale_threshold_override: int | None = None,
) -> dict:
    """
    Main entry point. Runs the full stale issue analysis.
    """
    if not is_agent_active(AGENT_NAME):
        log_audit(
            "agent_execution",
            AGENT_NAME,
            "run_monitor",
            "denied",
            {"reason": "agent suspended"},
        )
        return {
            "status": "blocked",
            "reason": "Stale Issue Monitor is currently suspended by the administrator.",
        }

    if not check_scope_permission(AGENT_NAME, "read_repos"):
        return {
            "status": "blocked",
            "reason": "Stale Issue Monitor does not have the 'read_repos' scope.",
        }

    if not check_scope_permission(AGENT_NAME, "read_issues"):
        return {
            "status": "blocked",
            "reason": "Stale Issue Monitor does not have the 'read_issues' scope.",
        }

    # ── Token Vault retrieval ──
    token_store_path = Path(__file__).parent.parent / "config" / "token_store.json"
    refresh_token = None
    if token_store_path.exists():
        try:
            token_data = json.loads(token_store_path.read_text())
            refresh_token = token_data.get("refresh_token", "")
        except (json.JSONDecodeError, Exception):
            pass

    if not refresh_token:
        return {
            "status": "error",
            "reason": "No refresh token available. Log in via the web dashboard first.",
        }

    log_audit("token_vault", AGENT_NAME, "retrieve_github_token", "requesting", {})

    github_token = await get_github_token(refresh_token)
    if not github_token:
        log_audit("token_vault", AGENT_NAME, "retrieve_github_token", "failed", {})
        return {
            "status": "error",
            "reason": "Failed to retrieve GitHub token from Token Vault.",
        }

    log_audit("token_vault", AGENT_NAME, "retrieve_github_token", "success", {})

    # ── Fetch and categorize issues ──
    issues = await _fetch_open_issues(github_token, owner, repo)
    if issues is None:
        return {"status": "error", "reason": "Failed to fetch issues from GitHub API."}

    threshold = stale_threshold_override if stale_threshold_override is not None else 7
    categories = _categorize_issues(issues, threshold_days=threshold)

    # ── Generate LLM summary ──
    summary_prompt = f"""You are a GitHub project health analyst. Analyze these stale issue categories for the repo {owner}/{repo}:

Active issues (less than 1 week): {len(categories["active"])}
1-2 weeks inactive: {len(categories["one_to_two_weeks"])} issues
2 weeks inactive: {len(categories["two_weeks"])} issues
2+ weeks inactive: {len(categories["two_plus_weeks"])} issues

Issues inactive 1-2 weeks:
{json.dumps(categories["one_to_two_weeks"], indent=2) if categories["one_to_two_weeks"] else "None"}

Issues inactive 2 weeks:
{json.dumps(categories["two_weeks"], indent=2) if categories["two_weeks"] else "None"}

Issues inactive 2+ weeks:
{json.dumps(categories["two_plus_weeks"], indent=2) if categories["two_plus_weeks"] else "None"}

Provide a brief summary with:
1. Overall health assessment (one sentence)
2. Key findings for each staleness category
3. Recommended actions
Keep it concise and actionable."""

    llm = get_llm()
    response = await call_llm(
        llm, [{"role": "user", "content": summary_prompt}], label="stale_issue_monitor"
    )
    report = response.content

    # ── Execute high-stakes actions on 2+ week stale issues ──
    actions_taken = []
    actions_blocked = []

    if execute_actions and categories["two_plus_weeks"]:
        if not ciba_approved:
            needs_ciba = is_high_stakes(AGENT_NAME, "post_comments") or is_high_stakes(
                AGENT_NAME, "add_labels"
            )
            if needs_ciba:
                log_audit(
                    "ciba",
                    AGENT_NAME,
                    "post_comments",
                    "requesting_approval",
                    {
                        "issues_count": len(categories["two_plus_weeks"]),
                    },
                )
                return {
                    "status": "awaiting_ciba",
                    "reason": f"CIBA approval required to comment on and label {len(categories['two_plus_weeks'])} stale issues.",
                    "report": report,
                    "categories": categories,
                    "stale_count": len(categories["two_plus_weeks"]),
                }
        else:
            for issue in categories["two_plus_weeks"]:
                if check_scope_permission(AGENT_NAME, "post_comments"):
                    comment_result = await _post_stale_comment(
                        github_token,
                        owner,
                        repo,
                        issue["number"],
                        issue["days_inactive"],
                    )
                    if "error" in comment_result:
                        actions_blocked.append(
                            {
                                "issue": issue["number"],
                                "action": "comment",
                                "error": comment_result["error"],
                            }
                        )
                    else:
                        actions_taken.append(
                            {
                                "issue": issue["number"],
                                "action": "comment",
                                "url": comment_result.get("url", ""),
                            }
                        )

                if check_scope_permission(AGENT_NAME, "add_labels"):
                    label_result = await _add_stale_label(
                        github_token, owner, repo, issue["number"]
                    )
                    if "error" in label_result:
                        actions_blocked.append(
                            {
                                "issue": issue["number"],
                                "action": "label",
                                "error": label_result["error"],
                            }
                        )
                    else:
                        actions_taken.append(
                            {"issue": issue["number"], "action": "label"}
                        )

    log_audit(
        "agent_execution",
        AGENT_NAME,
        "run_monitor",
        "success",
        {
            "repo": f"{owner}/{repo}",
            "total_issues": len(issues),
            "stale_1_2_weeks": len(categories["one_to_two_weeks"]),
            "stale_2_weeks": len(categories["two_weeks"]),
            "stale_2_plus_weeks": len(categories["two_plus_weeks"]),
            "actions_taken": len(actions_taken),
            "actions_blocked": len(actions_blocked),
        },
    )

    return {
        "status": "success",
        "report": report,
        "categories": categories,
        "summary": {
            "total_issues": len(issues),
            "active": len(categories["active"]),
            "one_to_two_weeks": len(categories["one_to_two_weeks"]),
            "two_weeks": len(categories["two_weeks"]),
            "two_plus_weeks": len(categories["two_plus_weeks"]),
        },
        "actions_taken": actions_taken,
        "actions_blocked": actions_blocked,
    }
