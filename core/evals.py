"""
ctrlAI - Evaluation System
============================
Lightweight eval infrastructure that validates the orchestrator, permissions,
CIBA, and inter-agent matrix are working correctly.

Run: python -m core.evals
Results are saved to config/eval_results.json and displayed in the dashboard.

This addresses the "evals everywhere" theme the hackathon organizers highlighted.
"""

import os
import json
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

RESULTS_FILE = Path(__file__).parent.parent / "config" / "eval_results.json"


# ============================================================
# Test Definitions
# ============================================================

ROUTING_TESTS = [
    {
        "id": "route_gmail_list",
        "query": "Show me my recent emails",
        "expected_agent": "gmail_agent",
        "expected_action": "list_emails",
        "category": "routing",
    },
    {
        "id": "route_gmail_search",
        "query": "Search my emails for invoices",
        "expected_agent": "gmail_agent",
        "expected_action": "search_emails",
        "category": "routing",
    },
    {
        "id": "route_gmail_send",
        "query": "Send an email to john@example.com saying hello",
        "expected_agent": "gmail_agent",
        "expected_action": "send_email",
        "category": "routing",
    },
    {
        "id": "route_calendar_list",
        "query": "What's on my calendar this week?",
        "expected_agent": "calendar_agent",
        "expected_action": "list_events",
        "category": "routing",
    },
    {
        "id": "route_drive_list",
        "query": "Show me my recent files in Drive",
        "expected_agent": "drive_agent",
        "expected_action": "list_files",
        "category": "routing",
    },
    {
        "id": "route_drive_search",
        "query": "Find the quarterly report in my Drive",
        "expected_agent": "drive_agent",
        "expected_action": "search_files",
        "category": "routing",
    },
    {
        "id": "route_github_repos",
        "query": "Show me my GitHub repositories",
        "expected_agent": "github_agent",
        "expected_action": "list_repos",
        "category": "routing",
    },
    {
        "id": "route_github_issues",
        "query": "List open issues in my ctrlAI repo",
        "expected_agent": "github_agent",
        "expected_action": "list_issues",
        "category": "routing",
    },
    {
        "id": "route_none",
        "query": "What is the meaning of life?",
        "expected_agent": "none",
        "expected_action": "none",
        "category": "routing",
    },
    {
        "id": "route_calendar_create",
        "query": "Create a meeting for tomorrow at 3pm called Team Standup",
        "expected_agent": "calendar_agent",
        "expected_action": "create_event",
        "category": "routing",
    },
]

PERMISSION_TESTS = [
    {
        "id": "perm_gmail_read_allowed",
        "agent": "gmail_agent",
        "scope": "read_emails",
        "expected": True,
        "category": "permission",
        "description": "Gmail Agent should have read access",
    },
    {
        "id": "perm_gmail_send_allowed",
        "agent": "gmail_agent",
        "scope": "send_emails",
        "expected": True,
        "category": "permission",
        "description": "Gmail Agent should have send access",
    },
    {
        "id": "perm_drive_cross_agent",
        "agent": "gmail_agent",
        "scope": "list_files",
        "expected": False,
        "category": "permission",
        "description": "Gmail Agent should NOT have Drive access",
    },
    {
        "id": "perm_github_cross_agent",
        "agent": "calendar_agent",
        "scope": "list_repos",
        "expected": False,
        "category": "permission",
        "description": "Calendar Agent should NOT have GitHub access",
    },
    {
        "id": "perm_drive_read_allowed",
        "agent": "drive_agent",
        "scope": "list_files",
        "expected": True,
        "category": "permission",
        "description": "Drive Agent should have read access",
    },
    {
        "id": "perm_github_repo_allowed",
        "agent": "github_agent",
        "scope": "list_repos",
        "expected": True,
        "category": "permission",
        "description": "GitHub Agent should have repo access",
    },
]

CIBA_TESTS = [
    {
        "id": "ciba_gmail_send",
        "agent": "gmail_agent",
        "action": "send_emails",
        "expected_high_stakes": True,
        "category": "ciba",
        "description": "Sending email should require CIBA approval",
    },
    {
        "id": "ciba_gmail_list",
        "agent": "gmail_agent",
        "action": "list_emails",
        "expected_high_stakes": False,
        "category": "ciba",
        "description": "Listing emails should NOT require CIBA",
    },
    {
        "id": "ciba_drive_delete",
        "agent": "drive_agent",
        "action": "delete_files",
        "expected_high_stakes": True,
        "category": "ciba",
        "description": "Deleting a file should require CIBA approval",
    },
    {
        "id": "ciba_calendar_create",
        "agent": "calendar_agent",
        "action": "create_events",
        "expected_high_stakes": True,
        "category": "ciba",
        "description": "Creating an event should require CIBA approval",
    },
    {
        "id": "ciba_github_comment",
        "agent": "github_agent",
        "action": "post_comments",
        "expected_high_stakes": True,
        "category": "ciba",
        "description": "Posting a GitHub comment should require CIBA",
    },
    {
        "id": "ciba_drive_list",
        "agent": "drive_agent",
        "action": "list_files",
        "expected_high_stakes": False,
        "category": "ciba",
        "description": "Listing files should NOT require CIBA",
    },
]

INTER_AGENT_TESTS = [
    {
        "id": "ia_gmail_drive_store",
        "requesting": "gmail_agent",
        "target": "drive_agent",
        "action": "store_attachment",
        "expected": True,
        "category": "inter_agent",
        "description": "Gmail Agent should be allowed to store attachments in Drive",
    },
    {
        "id": "ia_gmail_drive_delete",
        "requesting": "gmail_agent",
        "target": "drive_agent",
        "action": "delete_file",
        "expected": False,
        "category": "inter_agent",
        "description": "Gmail Agent should NOT be allowed to delete Drive files",
    },
    {
        "id": "ia_calendar_gmail_read",
        "requesting": "calendar_agent",
        "target": "gmail_agent",
        "action": "read_email_context",
        "expected": True,
        "category": "inter_agent",
        "description": "Calendar Agent should be allowed to read email context",
    },
    {
        "id": "ia_drive_gmail_send",
        "requesting": "drive_agent",
        "target": "gmail_agent",
        "action": "send_email",
        "expected": False,
        "category": "inter_agent",
        "description": "Drive Agent should NOT be allowed to send emails",
    },
    {
        "id": "ia_github_calendar_create",
        "requesting": "github_agent",
        "target": "calendar_agent",
        "action": "create_event",
        "expected": False,
        "category": "inter_agent",
        "description": "GitHub Agent should NOT be allowed to create calendar events",
    },
    {
        "id": "ia_github_gmail_read",
        "requesting": "github_agent",
        "target": "gmail_agent",
        "action": "read_email_context",
        "expected": True,
        "category": "inter_agent",
        "description": "GitHub Agent should be allowed to read email context",
    },
]


# ============================================================
# Test Runners
# ============================================================


async def run_routing_tests() -> list[dict]:
    """Test that the LLM router picks the correct agent and action."""
    from core.orchestrator import router_node

    results = []
    for test in ROUTING_TESTS:
        start = time.time()
        try:
            state = {
                "user_message": test["query"],
                "refresh_token": "",
                "ciba_user_id": "",
                "agent": "",
                "action": "",
                "params": {},
                "token": None,
                "agent_result": None,
                "ciba_status": None,
                "response": "",
                "error": None,
                "steps": [],
            }
            result = await router_node(state)
            latency = (time.time() - start) * 1000

            agent_correct = result.get("agent") == test["expected_agent"]
            action_correct = result.get("action") == test["expected_action"]
            passed = agent_correct and action_correct

            results.append(
                {
                    "id": test["id"],
                    "category": test["category"],
                    "query": test["query"],
                    "expected_agent": test["expected_agent"],
                    "expected_action": test["expected_action"],
                    "actual_agent": result.get("agent"),
                    "actual_action": result.get("action"),
                    "agent_correct": agent_correct,
                    "action_correct": action_correct,
                    "passed": passed,
                    "latency_ms": round(latency, 1),
                }
            )
        except Exception as e:
            results.append(
                {
                    "id": test["id"],
                    "category": test["category"],
                    "query": test["query"],
                    "passed": False,
                    "error": str(e),
                    "latency_ms": round((time.time() - start) * 1000, 1),
                }
            )

    return results


def run_permission_tests() -> list[dict]:
    """Test that scope permissions are enforced correctly."""
    from core.permissions import check_scope_permission

    results = []
    for test in PERMISSION_TESTS:
        # We call check_scope_permission but we don't want it to log during evals
        actual = check_scope_permission(test["agent"], test["scope"])
        passed = actual == test["expected"]

        results.append(
            {
                "id": test["id"],
                "category": test["category"],
                "description": test["description"],
                "agent": test["agent"],
                "scope": test["scope"],
                "expected": test["expected"],
                "actual": actual,
                "passed": passed,
            }
        )

    return results


def run_ciba_tests() -> list[dict]:
    """Test that high-stakes actions are correctly identified."""
    from core.permissions import is_high_stakes

    results = []
    for test in CIBA_TESTS:
        actual = is_high_stakes(test["agent"], test["action"])
        passed = actual == test["expected_high_stakes"]

        results.append(
            {
                "id": test["id"],
                "category": test["category"],
                "description": test["description"],
                "agent": test["agent"],
                "action": test["action"],
                "expected_high_stakes": test["expected_high_stakes"],
                "actual_high_stakes": actual,
                "passed": passed,
            }
        )

    return results


def run_inter_agent_tests() -> list[dict]:
    """Test that the inter-agent permission matrix is enforced."""
    from core.permissions import check_inter_agent_permission

    results = []
    for test in INTER_AGENT_TESTS:
        actual = check_inter_agent_permission(
            test["requesting"], test["target"], test["action"]
        )
        passed = actual == test["expected"]

        results.append(
            {
                "id": test["id"],
                "category": test["category"],
                "description": test["description"],
                "requesting": test["requesting"],
                "target": test["target"],
                "action": test["action"],
                "expected": test["expected"],
                "actual": actual,
                "passed": passed,
            }
        )

    return results


# ============================================================
# Main Eval Runner
# ============================================================


async def run_all_evals(include_routing: bool = True) -> dict:
    """
    Run all evaluation tests and return a comprehensive report.
    Set include_routing=False to skip LLM-dependent routing tests (faster).
    """
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": {},
        "summary": {},
    }

    # Permission tests (fast, deterministic)
    perm_results = run_permission_tests()
    report["categories"]["permission"] = {
        "tests": perm_results,
        "total": len(perm_results),
        "passed": sum(1 for r in perm_results if r["passed"]),
        "failed": sum(1 for r in perm_results if not r["passed"]),
    }

    # CIBA tests (fast, deterministic)
    ciba_results = run_ciba_tests()
    report["categories"]["ciba"] = {
        "tests": ciba_results,
        "total": len(ciba_results),
        "passed": sum(1 for r in ciba_results if r["passed"]),
        "failed": sum(1 for r in ciba_results if not r["passed"]),
    }

    # Inter-agent tests (fast, deterministic)
    ia_results = run_inter_agent_tests()
    report["categories"]["inter_agent"] = {
        "tests": ia_results,
        "total": len(ia_results),
        "passed": sum(1 for r in ia_results if r["passed"]),
        "failed": sum(1 for r in ia_results if not r["passed"]),
    }

    # Routing tests (requires LLM calls, slower)
    if include_routing:
        routing_results = await run_routing_tests()
        report["categories"]["routing"] = {
            "tests": routing_results,
            "total": len(routing_results),
            "passed": sum(1 for r in routing_results if r["passed"]),
            "failed": sum(1 for r in routing_results if not r["passed"]),
        }

    # Summary
    total_tests = 0
    total_passed = 0
    for cat in report["categories"].values():
        total_tests += cat["total"]
        total_passed += cat["passed"]

    report["summary"] = {
        "total_tests": total_tests,
        "total_passed": total_passed,
        "total_failed": total_tests - total_passed,
        "pass_rate": round(total_passed / total_tests * 100, 1)
        if total_tests > 0
        else 0,
    }

    # Save to file
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(report, indent=2))
    logger.info(f"Eval results saved: {report['summary']}")

    return report


def load_eval_results() -> dict | None:
    """Load the most recent eval results."""
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return None


def format_eval_report(report: dict) -> str:
    """Format eval results for display."""
    lines = []
    summary = report.get("summary", {})
    lines.append(f"ctrlAI Evaluation Report")
    lines.append(f"Run at: {report.get('timestamp', '?')[:19]}")
    lines.append(f"")
    lines.append(
        f"Overall: {summary.get('total_passed', 0)}/{summary.get('total_tests', 0)} passed ({summary.get('pass_rate', 0)}%)"
    )
    lines.append(f"")

    for cat_name, cat_data in report.get("categories", {}).items():
        lines.append(
            f"{cat_name.replace('_', ' ').title()}: {cat_data['passed']}/{cat_data['total']} passed"
        )
        for test in cat_data.get("tests", []):
            icon = "✅" if test.get("passed") else "❌"
            desc = test.get("description") or test.get("query", test.get("id", "?"))
            lines.append(f"  {icon} {desc}")
            if not test.get("passed"):
                if "expected_agent" in test:
                    lines.append(
                        f"      Expected: {test['expected_agent']}/{test['expected_action']}"
                    )
                    lines.append(
                        f"      Got: {test.get('actual_agent', '?')}/{test.get('actual_action', '?')}"
                    )
        lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    print("Running ctrlAI evaluation suite...\n")
    report = asyncio.run(run_all_evals(include_routing=True))
    print(format_eval_report(report))
