"""
ctrlAI - Dynamic Evaluation System
====================================
Generates tests dynamically from the live permission state.
Tests validate that the system enforces whatever is currently configured —
not a frozen snapshot.

Run: python -m core.evals
Results are saved to config/eval_results.json and displayed in the dashboard.
"""

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
# Static Routing Tests (these remain hardcoded - they test LLM behavior)
# ============================================================

ROUTING_TESTS = [
    {
        "id": "route_gmail_list",
        "query": "Show me my recent emails",
        "expected_agent": "gmail_agent",
        "expected_action": "list_emails",
    },
    {
        "id": "route_gmail_search",
        "query": "Search my emails for invoices",
        "expected_agent": "gmail_agent",
        "expected_action": "search_emails",
    },
    {
        "id": "route_gmail_send",
        "query": "Send an email to john@example.com saying hello",
        "expected_agent": "gmail_agent",
        "expected_action": "send_email",
    },
    {
        "id": "route_calendar_list",
        "query": "What's on my calendar this week?",
        "expected_agent": "calendar_agent",
        "expected_action": "list_events",
    },
    {
        "id": "route_drive_list",
        "query": "Show me my recent files in Drive",
        "expected_agent": "drive_agent",
        "expected_action": "list_files",
    },
    {
        "id": "route_drive_search",
        "query": "Find the quarterly report in my Drive",
        "expected_agent": "drive_agent",
        "expected_action": "search_files",
    },
    {
        "id": "route_github_repos",
        "query": "Show me my GitHub repositories",
        "expected_agent": "github_agent",
        "expected_action": "list_repos",
    },
    {
        "id": "route_github_issues",
        "query": "List open issues in my ctrlAI repo",
        "expected_agent": "github_agent",
        "expected_action": "list_issues",
    },
    {
        "id": "route_none",
        "query": "What is the meaning of life?",
        "expected_agent": "none",
        "expected_action": "none",
    },
    {
        "id": "route_calendar_create",
        "query": "Create a meeting for tomorrow at 3pm called Team Standup",
        "expected_agent": "calendar_agent",
        "expected_action": "create_event",
    },
]


# ============================================================
# Dynamic Test Generators
# ============================================================


def generate_permission_tests() -> list[dict]:
    """Generate permission tests from the LIVE agent registry state."""
    from core.permissions import get_all_agents, AgentStatus, AVAILABLE_SCOPES

    agents = get_all_agents()
    tests = []

    for agent_name, agent in agents.items():
        # Skip suspended agents - they should deny everything
        if agent.status != AgentStatus.ACTIVE:
            # Test that suspended agent is denied
            available = AVAILABLE_SCOPES.get(agent_name, [])
            if available:
                tests.append(
                    {
                        "id": f"perm_{agent_name}_suspended_deny",
                        "agent": agent_name,
                        "scope": available[0],
                        "expected": False,
                        "description": f"{agent_name.replace('_', ' ').title()} is suspended - should deny {available[0].replace('_', ' ')}",
                    }
                )
            continue

        available = AVAILABLE_SCOPES.get(agent_name, [])

        for scope in available:
            is_permitted = scope in agent.permitted_scopes
            tests.append(
                {
                    "id": f"perm_{agent_name}_{scope}",
                    "agent": agent_name,
                    "scope": scope,
                    "expected": is_permitted,
                    "description": f"{agent_name.replace('_', ' ').title()} {'has' if is_permitted else 'should NOT have'} {scope.replace('_', ' ')} access",
                }
            )

        # Cross-agent test: pick a scope from a DIFFERENT agent that this agent should NOT have
        for other_name, other_scopes in AVAILABLE_SCOPES.items():
            if other_name == agent_name:
                continue
            for other_scope in other_scopes:
                if (
                    other_scope not in available
                    and other_scope not in agent.permitted_scopes
                ):
                    tests.append(
                        {
                            "id": f"perm_{agent_name}_no_{other_scope}",
                            "agent": agent_name,
                            "scope": other_scope,
                            "expected": False,
                            "description": f"{agent_name.replace('_', ' ').title()} should NOT have {other_scope.replace('_', ' ')} (belongs to {other_name.replace('_', ' ').title()})",
                        }
                    )
                    break  # One cross-agent test per pair is enough
            else:
                continue
            break

    return tests


def generate_ciba_tests() -> list[dict]:
    """Generate CIBA tests from the LIVE agent high-stakes configuration."""
    from core.permissions import get_all_agents, AgentStatus, AVAILABLE_HIGH_STAKES

    agents = get_all_agents()
    tests = []

    for agent_name, agent in agents.items():
        if agent.status != AgentStatus.ACTIVE:
            continue

        available_hs = AVAILABLE_HIGH_STAKES.get(agent_name, [])

        for action in available_hs:
            is_high_stakes = action in agent.high_stakes_actions
            tests.append(
                {
                    "id": f"ciba_{agent_name}_{action}",
                    "agent": agent_name,
                    "action": action,
                    "expected_high_stakes": is_high_stakes,
                    "description": f"{action.replace('_', ' ').title()} {'requires' if is_high_stakes else 'does NOT require'} CIBA approval for {agent_name.replace('_', ' ').title()}",
                }
            )

    return tests


def generate_inter_agent_tests() -> list[dict]:
    """Generate inter-agent tests from the LIVE permission matrix."""
    from core.permissions import get_all_agents, get_permission_matrix, AgentStatus

    agents = get_all_agents()
    matrix = get_permission_matrix()
    active_agents = [
        name for name, a in agents.items() if a.status == AgentStatus.ACTIVE
    ]
    tests = []

    # All actions that could be requested
    ALL_IA_ACTIONS = [
        "store_attachment",
        "check_availability",
        "read_email_context",
        "send_alert_email",
        "send_email",
        "delete_file",
        "create_event",
        "read_files",
        "read_events",
        "read_issues",
        "read_repos",
        "post_comments",
        "generate_reports",
    ]

    for requester in active_agents:
        for target in active_agents:
            if requester == target:
                continue

            allowed_actions = matrix.get(requester, {}).get(target, [])

            if allowed_actions:
                # Test that each allowed action is permitted
                for action in allowed_actions:
                    tests.append(
                        {
                            "id": f"ia_{requester}_{target}_{action}_allow",
                            "requesting": requester,
                            "target": target,
                            "action": action,
                            "expected": True,
                            "description": f"{requester.replace('_', ' ').title()} → {target.replace('_', ' ').title()}: {action.replace('_', ' ')} should be allowed",
                        }
                    )

                # Test that an action NOT in the list is denied
                for action in ALL_IA_ACTIONS:
                    if action not in allowed_actions:
                        tests.append(
                            {
                                "id": f"ia_{requester}_{target}_{action}_deny",
                                "requesting": requester,
                                "target": target,
                                "action": action,
                                "expected": False,
                                "description": f"{requester.replace('_', ' ').title()} → {target.replace('_', ' ').title()}: {action.replace('_', ' ')} should be denied",
                            }
                        )
                        break  # One deny test per pair is enough
            else:
                # No access at all - test one action is denied
                tests.append(
                    {
                        "id": f"ia_{requester}_{target}_blocked",
                        "requesting": requester,
                        "target": target,
                        "action": ALL_IA_ACTIONS[0],
                        "expected": False,
                        "description": f"{requester.replace('_', ' ').title()} → {target.replace('_', ' ').title()}: should be fully blocked",
                    }
                )

    return tests


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
                    "category": "routing",
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
                    "category": "routing",
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

    tests = generate_permission_tests()
    results = []
    for test in tests:
        actual = check_scope_permission(test["agent"], test["scope"])
        passed = actual == test["expected"]
        results.append(
            {
                "id": test["id"],
                "category": "permission",
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

    tests = generate_ciba_tests()
    results = []
    for test in tests:
        actual = is_high_stakes(test["agent"], test["action"])
        passed = actual == test["expected_high_stakes"]
        results.append(
            {
                "id": test["id"],
                "category": "ciba",
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

    tests = generate_inter_agent_tests()
    results = []
    for test in tests:
        actual = check_inter_agent_permission(
            test["requesting"], test["target"], test["action"]
        )
        passed = actual == test["expected"]
        results.append(
            {
                "id": test["id"],
                "category": "inter_agent",
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
    """Run all evaluation tests and return a comprehensive report."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": {},
        "summary": {},
    }

    # Permission tests (dynamic, deterministic)
    perm_results = run_permission_tests()
    report["categories"]["permission"] = {
        "tests": perm_results,
        "total": len(perm_results),
        "passed": sum(1 for r in perm_results if r["passed"]),
        "failed": sum(1 for r in perm_results if not r["passed"]),
    }

    # CIBA tests (dynamic, deterministic)
    ciba_results = run_ciba_tests()
    report["categories"]["ciba"] = {
        "tests": ciba_results,
        "total": len(ciba_results),
        "passed": sum(1 for r in ciba_results if r["passed"]),
        "failed": sum(1 for r in ciba_results if not r["passed"]),
    }

    # Inter-agent tests (dynamic, deterministic)
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
    lines.append("ctrlAI Evaluation Report")
    lines.append(f"Run at: {report.get('timestamp', '?')[:19]}")
    lines.append("")
    lines.append(
        f"Overall: {summary.get('total_passed', 0)}/{summary.get('total_tests', 0)} passed ({summary.get('pass_rate', 0)}%)"
    )
    lines.append("")

    for cat_name, cat_data in report.get("categories", {}).items():
        lines.append(
            f"{cat_name.replace('_', ' ').title()}: {cat_data['passed']}/{cat_data['total']} passed"
        )
        for test in cat_data.get("tests", []):
            icon = "✅" if test.get("passed") else "❌"
            desc = test.get("description") or test.get("query", test.get("id", "?"))
            lines.append(f"  {icon} {desc}")
            if not test.get("passed") and "expected_agent" in test:
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
