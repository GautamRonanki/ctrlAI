"""
ctrlAI Admin Dashboard — Streamlit
Identity and Permission Control Plane for AI Agents.
"""

import json
import asyncio
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from datetime import datetime

# Page config
st.set_page_config(
    page_title="ctrlAI — Admin Dashboard",
    page_icon="🛡️",
    layout="wide",
)

# ── Custom CSS for cards and styling ──
st.markdown(
    """
<style>
    .agent-card {
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 10px;
        background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        box-sizing: border-box;
    }
    .agent-card-suspended {
        border: 1px solid #ffcdd2;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 10px;
        background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        box-sizing: border-box;
    }
    .agent-name {
        font-size: 1.1em;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .agent-detail {
        font-size: 0.88em;
        color: #555;
        margin-bottom: 3px;
    }
    .status-active {
        color: #2e7d32;
        font-weight: 600;
    }
    .status-suspended {
        color: #c62828;
        font-weight: 600;
    }
    .scope-badge {
        display: inline-block;
        background: #e3f2fd;
        color: #1565c0;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.82em;
        margin: 2px 2px;
    }
    .highstakes-badge {
        display: inline-block;
        background: #fff3e0;
        color: #e65100;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.82em;
        margin: 2px 2px;
    }
    .flow-container {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-wrap: wrap;
        gap: 8px;
        padding: 20px 0;
    }
    .flow-node {
        border: 2px solid #1565c0;
        border-radius: 10px;
        padding: 12px 16px;
        text-align: center;
        background: #e3f2fd;
        min-width: 120px;
    }
    .flow-node-label {
        font-weight: 700;
        font-size: 0.9em;
        color: #0d47a1;
    }
    .flow-node-desc {
        font-size: 0.75em;
        color: #555;
        margin-top: 4px;
    }
    .flow-arrow {
        font-size: 1.4em;
        color: #1565c0;
        font-weight: bold;
    }
    .flow-deny {
        font-size: 0.78em;
        color: #c62828;
        text-align: center;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Paths
AUDIT_LOG_PATH = Path(__file__).parent.parent / "logs" / "audit.jsonl"


def load_audit_log() -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    entries = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def humanize(text: str) -> str:
    """Convert underscore_text to human readable text."""
    return text.replace("_", " ").title()


def humanize_lower(text: str) -> str:
    """Convert underscore_text to human readable lowercase."""
    return text.replace("_", " ")


# ============================================================
# Header
# ============================================================
st.title("🛡️ ctrlAI")
st.caption("Identity and Permission Control Plane for AI Agents")

# Quick stats bar
entries = load_audit_log()
s1, s2, s3, s4, s5 = st.columns(5)
with s1:
    active_count = 0
    from core.permissions import (
        get_all_agents,
        AgentStatus,
        get_available_scopes,
        get_available_high_stakes,
        update_scopes,
        update_high_stakes,
        suspend_agent,
        activate_agent,
    )

    for a in get_all_agents().values():
        if a.status == AgentStatus.ACTIVE:
            active_count += 1
    st.metric("Active Agents", f"{active_count} / {len(get_all_agents())}")
with s2:
    st.metric("Total Events", len(entries))
with s3:
    denied = len([e for e in entries if e["status"] == "denied"])
    st.metric("Denials", denied)
with s4:
    ciba_count = len([e for e in entries if e["event_type"] == "ciba"])
    st.metric("CIBA Events", ciba_count)
with s5:
    inter_agent = len(
        [
            e
            for e in entries
            if e["event_type"]
            in ("inter_agent", "inter_agent_execution", "inter_agent_request")
        ]
    )
    st.metric("Inter-Agent Events", inter_agent)

st.divider()

# ============================================================
# Agent Registry (with inline permission management)
# ============================================================
st.header("🤖 Agent Registry")

agents = get_all_agents()

# Plain language scope descriptions
SCOPE_LABELS = {
    "read_emails": "Read emails",
    "send_emails": "Send emails",
    "list_emails": "List emails",
    "search_emails": "Search emails",
    "list_files": "List files",
    "read_files": "Read files",
    "create_files": "Create files",
    "delete_files": "Delete files",
    "search_files": "Search files",
    "list_events": "List events",
    "read_events": "Read events",
    "create_events": "Create events",
    "modify_events": "Modify events",
    "list_repos": "List repositories",
    "read_repos": "Read repositories",
    "list_issues": "List issues",
    "read_issues": "Read issues",
    "post_comments": "Post comments",
    "add_labels": "Add labels",
    "read_audit_trail": "Read audit trail",
    "generate_reports": "Generate reports",
}

ACTION_LABELS = {
    "send_emails": "Send emails",
    "list_emails": "List emails",
    "search_emails": "Search emails",
    "read_emails": "Read emails",
    "delete_files": "Delete files",
    "list_files": "List files",
    "search_files": "Search files",
    "read_files": "Read files",
    "create_files": "Create files",
    "create_events": "Create events",
    "modify_events": "Modify events",
    "list_events": "List events",
    "read_events": "Read events",
    "post_comments": "Post comments",
    "list_repos": "List repositories",
    "list_issues": "List issues",
    "read_repos": "Read repositories",
    "read_issues": "Read issues",
    "add_labels": "Add labels",
    "send_alert_emails": "Send alert emails",
    "generate_reports": "Generate reports",
}

PROVIDER_LABELS = {
    "google": "Google OAuth",
    "github": "GitHub OAuth",
    "internal": "Internal (No OAuth)",
}


# Dialog for managing agent settings
@st.dialog("Agent Settings", width="large")
def show_permission_dialog(agent_name: str):
    agent = get_all_agents()[agent_name]
    is_active = agent.status == AgentStatus.ACTIVE
    status_emoji = "🟢" if is_active else "🔴"
    status_label = "Active" if is_active else "Suspended"

    st.subheader(f"{status_emoji} {humanize(agent_name)}")
    st.caption(agent.description)
    st.divider()

    # Status toggle
    st.markdown("**Agent Status**")
    if is_active:
        if st.button(
            "⏸️ Suspend Agent", key=f"dlg_suspend_{agent_name}", use_container_width=True
        ):
            suspend_agent(agent_name)
            st.rerun()
    else:
        if st.button(
            "▶️ Activate Agent",
            key=f"dlg_activate_{agent_name}",
            use_container_width=True,
        ):
            activate_agent(agent_name)
            st.rerun()

    st.divider()

    col_scopes, col_highstakes = st.columns(2)

    with col_scopes:
        st.markdown("**Permissions**")
        st.caption("What this agent is allowed to do.")
        available = get_available_scopes(agent_name)
        current_scopes = list(agent.permitted_scopes)

        new_scopes = []
        for scope in available:
            label = SCOPE_LABELS.get(scope, scope)
            checked = st.checkbox(
                label,
                value=scope in current_scopes,
                key=f"dlg_scope_{agent_name}_{scope}",
            )
            if checked:
                new_scopes.append(scope)

    with col_highstakes:
        st.markdown("**Requires Approval (CIBA)**")
        st.caption("Actions that need your confirmation before executing.")
        available_hs = get_available_high_stakes(agent_name)
        current_hs = list(agent.high_stakes_actions)

        new_hs = []
        for action in available_hs:
            label = ACTION_LABELS.get(action, action)
            checked = st.checkbox(
                label,
                value=action in current_hs,
                key=f"dlg_hs_{agent_name}_{action}",
            )
            if checked:
                new_hs.append(action)

    st.divider()
    if st.button(
        "💾 Save Changes", key=f"dlg_save_{agent_name}", use_container_width=True
    ):
        if new_scopes != current_scopes:
            update_scopes(agent_name, new_scopes)
        if new_hs != current_hs:
            update_high_stakes(agent_name, new_hs)
        st.rerun()


# Render agent cards row by row so cards in the same row share equal height
agent_list = list(agents.items())
for row_start in range(0, len(agent_list), 3):
    row_agents = agent_list[row_start:row_start + 3]
    cols = st.columns(3)
    for j, (name, agent) in enumerate(row_agents):
        with cols[j]:
            is_active = agent.status == AgentStatus.ACTIVE
            card_class = "agent-card" if is_active else "agent-card-suspended"
            status_class = "status-active" if is_active else "status-suspended"
            status_label = "Active" if is_active else "Suspended"
            status_emoji = "🟢" if is_active else "🔴"

            scope_badges = "".join(
                f'<span class="scope-badge">{SCOPE_LABELS.get(s, s)}</span>'
                for s in agent.permitted_scopes
            )
            highstakes_badges = "".join(
                f'<span class="highstakes-badge">{ACTION_LABELS.get(s, s)}</span>'
                for s in agent.high_stakes_actions
            )

            st.markdown(
                f"""
            <div class="{card_class}">
                <div class="agent-name">{status_emoji} {humanize(name)}</div>
                <div class="agent-detail">{agent.description}</div>
                <div class="agent-detail" style="margin-top:8px;"><b>Provider:</b> {PROVIDER_LABELS.get(agent.oauth_provider, agent.oauth_provider)}</div>
                <div class="agent-detail"><b>Permissions:</b> {scope_badges}</div>
                <div class="agent-detail"><b>Requires Approval:</b> {highstakes_badges if highstakes_badges else '<span style="color:#888;">None</span>'}</div>
                <div class="agent-detail" style="margin-top:6px;"><b>Status:</b> <span class="{status_class}">{status_label}</span></div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            if st.button("⚙️ Manage", key=f"settings_{name}", use_container_width=True):
                show_permission_dialog(name)

# Equalize card heights across columns in each row via JS
components.html(
    """
    <script>
    (function equalizeCards() {
        const doc = window.parent.document;
        function run() {
            const rows = doc.querySelectorAll('[data-testid="stHorizontalBlock"]');
            rows.forEach(row => {
                const cards = row.querySelectorAll('.agent-card, .agent-card-suspended');
                if (cards.length < 2) return;
                // Reset so we measure natural height
                cards.forEach(c => { c.style.height = 'auto'; });
                const maxH = Math.max(...Array.from(cards).map(c => c.getBoundingClientRect().height));
                cards.forEach(c => { c.style.height = maxH + 'px'; });
            });
        }
        // Run immediately and after Streamlit finishes painting
        run();
        setTimeout(run, 200);
        setTimeout(run, 800);
    })();
    </script>
    """,
    height=0,
)

st.divider()
# ============================================================
# Inter-Agent Permission Matrix
# ============================================================
st.header("🔗 Inter-Agent Permission Matrix")

from core.permissions import get_permission_matrix

matrix = get_permission_matrix()
agent_names = list(agents.keys())

matrix_data = []
for requester in agent_names:
    row = {"Agent": humanize(requester)}
    for target in agent_names:
        if requester == target:
            row[humanize(target)] = "—"
        elif requester in matrix and target in matrix[requester]:
            actions = ", ".join(humanize_lower(a) for a in matrix[requester][target])
            row[humanize(target)] = f"✅ {actions}"
        else:
            row[humanize(target)] = "❌ Blocked"
    matrix_data.append(row)

df_matrix = pd.DataFrame(matrix_data).set_index("Agent")
st.dataframe(df_matrix, use_container_width=True)

st.caption(
    "Each cell shows what the row agent can request from the column agent. "
    "❌ Blocked = all requests denied. Enforced at runtime on every inter-agent communication."
)

st.divider()

# ============================================================
# Inter-Agent Demo Panel
# ============================================================
st.header("🧪 Inter-Agent Demo Panel")
st.caption(
    "Click any scenario to execute it live. Results are logged to the audit trail in real time."
)

from core.inter_agent import (
    get_demo_scenarios,
    execute_inter_agent_request,
    format_inter_agent_result,
)

scenarios = get_demo_scenarios()

allowed_scenarios = [s for s in scenarios if s["expected"] == "allowed"]
denied_scenarios = [s for s in scenarios if s["expected"] == "denied"]

col_allowed, col_denied = st.columns(2)

with col_allowed:
    st.subheader("✅ Allowed Requests")
    for scenario in allowed_scenarios:
        label = f"✅ {humanize(scenario['requesting_agent'])} → {humanize(scenario['target_agent'])}: {humanize_lower(scenario['action'])}"
        if st.button(
            label,
            key=f"demo_{scenario['requesting_agent']}_{scenario['target_agent']}_{scenario['action']}",
        ):
            with st.spinner("Executing..."):
                result = run_async(
                    execute_inter_agent_request(
                        requesting_agent=scenario["requesting_agent"],
                        target_agent=scenario["target_agent"],
                        action=scenario["action"],
                    )
                )
                formatted = format_inter_agent_result(result)
                st.success(formatted)

with col_denied:
    st.subheader("🚫 Denied Requests")
    for scenario in denied_scenarios:
        label = f"🚫 {humanize(scenario['requesting_agent'])} → {humanize(scenario['target_agent'])}: {humanize_lower(scenario['action'])}"
        if st.button(
            label,
            key=f"demo_{scenario['requesting_agent']}_{scenario['target_agent']}_{scenario['action']}",
        ):
            with st.spinner("Executing..."):
                result = run_async(
                    execute_inter_agent_request(
                        requesting_agent=scenario["requesting_agent"],
                        target_agent=scenario["target_agent"],
                        action=scenario["action"],
                    )
                )
                formatted = format_inter_agent_result(result)
                st.error(formatted)

st.divider()

# ============================================================
# Orchestrator Execution Flow
# ============================================================
st.header("🔄 Orchestrator Execution Flow")
st.caption(
    "Every request flows through this LangGraph state machine. Each node enforces a governance check."
)

st.markdown(
    """
<div class="flow-container">
    <div class="flow-node">
        <div class="flow-node-label">Router</div>
        <div class="flow-node-desc">LLM picks the<br>right agent</div>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-node">
        <div class="flow-node-label">Permission Gate</div>
        <div class="flow-node-desc">Scope & status<br>check</div>
        <div class="flow-deny">↓ denied → blocked</div>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-node">
        <div class="flow-node-label">Token Retrieval</div>
        <div class="flow-node-desc">Token Vault<br>exchange</div>
        <div class="flow-deny">↓ failed → error</div>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-node">
        <div class="flow-node-label">CIBA Checkpoint</div>
        <div class="flow-node-desc">Guardian push<br>approval</div>
        <div class="flow-deny">↓ denied → blocked</div>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-node">
        <div class="flow-node-label">Agent Executor</div>
        <div class="flow-node-desc">Calls the<br>service API</div>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-node">
        <div class="flow-node-label">Response</div>
        <div class="flow-node-desc">Formatted result<br>to user</div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# Recent orchestrator traces
orchestrator_entries = [
    e for e in entries if e["event_type"] == "orchestrator_complete"
]
if orchestrator_entries:
    st.subheader("Recent Executions")
    for entry in reversed(orchestrator_entries[-5:]):
        details = entry.get("details", {})
        steps_count = details.get("steps_count", 0)
        status_icon = "✅" if entry["status"] == "success" else "❌"
        agent_display = humanize(entry["agent_name"])
        action_display = humanize_lower(entry["action"])
        st.markdown(
            f"{status_icon} **{agent_display}** — {action_display} — "
            f"{steps_count} steps — {entry['timestamp'][:19]}"
        )

st.divider()

# ============================================================
# Autonomous Security Report Agent
# ============================================================
st.header("🔒 Security Report Agent")
st.caption(
    "Autonomous agent — monitors the audit trail and alerts on security violations. Not triggered by employees."
)

from agents.security_report_agent import generate_security_report, send_alert_email

report_col1, report_col2, report_col3 = st.columns([2, 2, 6])

with report_col1:
    run_report = st.button(
        "▶️ Run Now", key="run_security_report", use_container_width=True
    )
with report_col2:
    run_and_alert = st.button(
        "▶️ Run & Alert",
        key="run_and_alert",
        use_container_width=True,
        help="Generate report and send email alert if critical issues found",
    )

if run_report or run_and_alert:
    with st.spinner("Security Report Agent running through permission pipeline..."):
        report_result = run_async(generate_security_report())

    if report_result["status"] == "blocked":
        st.error(f"🚫 Blocked: {report_result['reason']}")
    elif report_result["status"] == "success":
        st.success("✅ Report generated successfully")
        st.markdown(report_result["report"])

        # Show analysis metrics
        if (
            report_result.get("analysis")
            and report_result["analysis"].get("total_events", 0) > 0
        ):
            analysis = report_result["analysis"]
            a1, a2, a3, a4, a5 = st.columns(5)
            with a1:
                st.metric("Total Events", analysis["total_events"])
            with a2:
                st.metric("Denials", analysis["denied_count"])
            with a3:
                st.metric("CIBA Events", analysis["ciba_count"])
            with a4:
                st.metric(
                    "Inter-Agent Violations", analysis["inter_agent_denied_count"]
                )
            with a5:
                st.metric("Errors", analysis["error_count"])

        # Send alert email if critical and user clicked Run & Alert
        if run_and_alert and report_result.get("has_critical"):
            st.warning(
                "⚠️ Critical issues detected — sending alert email via Gmail Agent..."
            )
            refresh_token = None
            token_store_path = (
                Path(__file__).parent.parent / "config" / "token_store.json"
            )
            if token_store_path.exists():
                try:
                    token_data = json.loads(token_store_path.read_text())
                    refresh_token = token_data.get("refresh_token", "")
                except (json.JSONDecodeError, Exception):
                    pass

            if refresh_token:
                from core.token_service import get_google_token

                gmail_token = run_async(get_google_token(refresh_token))
                if gmail_token:
                    email_result = run_async(
                        send_alert_email(report_result["report"], gmail_token)
                    )
                    if email_result.get("status") == "blocked":
                        st.error(
                            f"🚫 Inter-agent request blocked: {email_result['reason']}"
                        )
                    elif "error" in email_result:
                        st.error(
                            f"❌ Failed to send alert: {email_result.get('error', 'Unknown error')}"
                        )
                    else:
                        st.success(
                            "✅ Alert email sent to admin via Gmail Agent (inter-agent communication)"
                        )
                else:
                    st.error("❌ Could not retrieve Gmail token from Token Vault")
            else:
                st.error(
                    "❌ No refresh token available. Log in via the web dashboard first."
                )
        elif run_and_alert and not report_result.get("has_critical"):
            st.info("✅ No critical issues found — no alert email needed.")
    else:
        st.error(f"❌ Error: {report_result.get('reason', 'Unknown error')}")

st.divider()

# ============================================================
# Stale Issue Monitor — Autonomous OAuth Agent
# ============================================================
st.header("🔍 Stale Issue Monitor")
st.caption(
    "Autonomous OAuth agent — retrieves its own GitHub token from Token Vault, "
    "monitors repos for stale issues, and comments/labels with CIBA approval."
)

from agents.stale_issue_monitor import run_stale_issue_monitor

# Repo configuration
sim_col1, sim_col2, sim_col3 = st.columns([2, 2, 6])
with sim_col1:
    sim_owner = st.text_input("Owner", value="GautamRonanki", key="sim_owner")
with sim_col2:
    sim_repo = st.text_input("Repo", value="ctrlAI", key="sim_repo")

sim_btn_col1, sim_btn_col2, sim_btn_col3, sim_btn_col4 = st.columns([2, 2, 2, 4])

with sim_btn_col1:
    run_scan = st.button("▶️ Run Scan", key="run_stale_scan", use_container_width=True)
with sim_btn_col2:
    run_and_act = st.button(
        "▶️ Run & Act",
        key="run_stale_act",
        use_container_width=True,
        help="Scan for stale issues and comment/label 2+ week stale issues (requires CIBA)",
    )
with sim_btn_col3:
    test_mode = st.checkbox(
        "🧪 Test Mode",
        key="sim_test_mode",
        help="Sets threshold to 0 days so all issues appear stale",
    )

if run_scan or run_and_act:
    with st.spinner(
        "Stale Issue Monitor running through permission pipeline → Token Vault → GitHub API..."
    ):
        result = run_async(
            run_stale_issue_monitor(
                owner=sim_owner,
                repo=sim_repo,
                execute_actions=run_and_act,
                ciba_approved=False,
                stale_threshold_override=0 if test_mode else None,
            )
        )
    st.session_state["sim_result"] = result
    st.session_state["sim_owner_val"] = sim_owner
    st.session_state["sim_repo_val"] = sim_repo
    st.session_state["sim_test_val"] = test_mode

# Display result from session state
if "sim_result" in st.session_state:
    result = st.session_state["sim_result"]

    if result["status"] == "blocked":
        st.error(f"🚫 Blocked: {result['reason']}")

    elif result["status"] == "error":
        st.error(f"❌ Error: {result['reason']}")

    elif result["status"] == "awaiting_ciba":
        st.warning(f"🔐 {result['reason']}")
        st.markdown(result.get("report", ""))

        if st.button(
            "✅ Approve & Execute", key="sim_ciba_approve", use_container_width=True
        ):
            with st.spinner("Executing high-stakes actions with CIBA approval..."):
                approved_result = run_async(
                    run_stale_issue_monitor(
                        owner=st.session_state.get("sim_owner_val", "GautamRonanki"),
                        repo=st.session_state.get("sim_repo_val", "ctrlAI"),
                        execute_actions=True,
                        ciba_approved=True,
                        stale_threshold_override=0
                        if st.session_state.get("sim_test_val")
                        else None,
                    )
                )
            st.session_state["sim_result"] = approved_result
            st.rerun()

    elif result["status"] == "success":
        st.success("✅ Scan complete")
        st.markdown(result.get("report", ""))

        summary = result.get("summary", {})
        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        with sm1:
            st.metric("Total Issues", summary.get("total_issues", 0))
        with sm2:
            st.metric("Active", summary.get("active", 0))
        with sm3:
            st.metric("1-2 Weeks", summary.get("one_to_two_weeks", 0))
        with sm4:
            st.metric("2 Weeks", summary.get("two_weeks", 0))
        with sm5:
            st.metric("2+ Weeks", summary.get("two_plus_weeks", 0))

        categories = result.get("categories", {})

        if categories.get("two_plus_weeks"):
            st.subheader("🔴 2+ Weeks Inactive")
            for issue in categories["two_plus_weeks"]:
                st.markdown(
                    f"  • **#{issue['number']}** — {issue['title']} "
                    f"({issue['days_inactive']} days) — [{issue['author']}]({issue['url']})"
                )

        if categories.get("two_weeks"):
            st.subheader("🟠 2 Weeks Inactive")
            for issue in categories["two_weeks"]:
                st.markdown(
                    f"  • **#{issue['number']}** — {issue['title']} "
                    f"({issue['days_inactive']} days) — [{issue['author']}]({issue['url']})"
                )

        if categories.get("one_to_two_weeks"):
            st.subheader("🟡 1-2 Weeks Inactive")
            for issue in categories["one_to_two_weeks"]:
                st.markdown(
                    f"  • **#{issue['number']}** — {issue['title']} "
                    f"({issue['days_inactive']} days) — [{issue['author']}]({issue['url']})"
                )

        if result.get("actions_taken"):
            st.subheader("✅ Actions Taken")
            for action in result["actions_taken"]:
                st.markdown(f"  ✅ Issue #{action['issue']} — {action['action']}")

        if result.get("actions_blocked"):
            st.subheader("❌ Actions Blocked")
            for action in result["actions_blocked"]:
                st.markdown(
                    f"  ❌ Issue #{action['issue']} — {action['action']}: {action['error']}"
                )
st.divider()

# ============================================================
# Audit Log
# ============================================================
st.header("📋 Audit Log")

if not entries:
    st.info("No audit entries yet. Use the Slack bot or API to generate activity.")
else:
    # Clear filters callback
    def clear_filters():
        st.session_state["filter_event_type"] = []
        st.session_state["filter_agent"] = []
        st.session_state["filter_status"] = []

    # Filters
    col1, col2, col3, col4 = st.columns([3, 3, 3, 1])
    with col1:
        event_types = sorted(set(e["event_type"] for e in entries))
        event_type_labels = {et: humanize(et) for et in event_types}
        selected_types = st.multiselect(
            "Filter by event type",
            options=event_types,
            format_func=lambda x: event_type_labels.get(x, x),
            key="filter_event_type",
        )
    with col2:
        agent_names_in_log = sorted(set(e["agent_name"] for e in entries))
        agent_labels = {a: humanize(a) for a in agent_names_in_log}
        selected_agents = st.multiselect(
            "Filter by agent",
            options=agent_names_in_log,
            format_func=lambda x: agent_labels.get(x, x),
            key="filter_agent",
        )
    with col3:
        statuses = sorted(set(e["status"] for e in entries))
        status_labels = {s: humanize(s) for s in statuses}
        selected_statuses = st.multiselect(
            "Filter by status",
            options=statuses,
            format_func=lambda x: status_labels.get(x, x),
            key="filter_status",
        )
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        st.button("🧹 Clear", on_click=clear_filters)

    # Apply filters — show all if no filters selected
    filtered = entries
    if selected_types:
        filtered = [e for e in filtered if e["event_type"] in selected_types]
    if selected_agents:
        filtered = [e for e in filtered if e["agent_name"] in selected_agents]
    if selected_statuses:
        filtered = [e for e in filtered if e["status"] in selected_statuses]

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        allowed = len([e for e in filtered if e["status"] == "allowed"])
        st.metric("Allowed", allowed)
    with m2:
        denied_f = len([e for e in filtered if e["status"] == "denied"])
        st.metric("Denied", denied_f)
    with m3:
        success_f = len([e for e in filtered if e["status"] == "success"])
        st.metric("Success", success_f)
    with m4:
        error_f = len([e for e in filtered if e["status"] == "error"])
        st.metric("Errors", error_f)

    # Table
    if filtered:
        df = pd.DataFrame(filtered[::-1])
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%H:%M:%S")
        df["event_type"] = df["event_type"].apply(humanize)
        df["agent_name"] = df["agent_name"].apply(humanize)
        df["action"] = df["action"].apply(humanize_lower)
        df["status"] = df["status"].apply(humanize)
        df["details"] = df["details"].apply(lambda d: json.dumps(d)[:80] if d else "")

        display_cols = [
            "timestamp",
            "event_type",
            "agent_name",
            "action",
            "status",
            "details",
        ]
        col_config = {
            "timestamp": st.column_config.TextColumn("Time"),
            "event_type": st.column_config.TextColumn("Event Type"),
            "agent_name": st.column_config.TextColumn("Agent"),
            "action": st.column_config.TextColumn("Action"),
            "status": st.column_config.TextColumn("Status"),
            "details": st.column_config.TextColumn("Details"),
        }
        st.dataframe(
            df[display_cols],
            column_config=col_config,
            use_container_width=True,
            height=400,
        )

    st.divider()

    # CIBA Events Detail
    ciba_events = [e for e in entries if e["event_type"] == "ciba"]
    if ciba_events:
        st.subheader("🔐 CIBA Approval History")
        for event in reversed(ciba_events[-10:]):
            status = event["status"]
            icon = {
                "requested": "🔔",
                "pending": "⏳",
                "approved": "✅",
                "denied": "❌",
                "expired": "⏰",
                "timeout": "⏰",
                "requesting_approval": "🔔",
            }.get(status, "❓")
            agent_display = humanize(event["agent_name"])
            action_display = humanize_lower(event["action"])
            st.markdown(
                f"{icon} **{agent_display}** — {action_display} — "
                f"**{humanize(status)}** at {event['timestamp'][:19]}"
            )

st.divider()

# ============================================================
# Evaluation Results
# ============================================================
st.header("🧪 Evaluation Results")

from core.evals import load_eval_results, run_all_evals

eval_results = load_eval_results()

col_run, col_info = st.columns([1, 3])
with col_run:
    if st.button("▶️ Run Evals"):
        with st.spinner("Running 28 tests..."):
            eval_results = run_async(run_all_evals(include_routing=True))
            st.rerun()
with col_info:
    if eval_results:
        st.caption(f"Last run: {eval_results.get('timestamp', '?')[:19]}")
    else:
        st.caption("No eval results yet. Click Run Evals to test the system.")

if eval_results:
    summary = eval_results.get("summary", {})

    # Overall score
    total = summary.get("total_tests", 0)
    passed = summary.get("total_passed", 0)
    rate = summary.get("pass_rate", 0)

    e1, e2, e3, e4 = st.columns(4)
    with e1:
        st.metric("Total Tests", total)
    with e2:
        st.metric("Passed", passed)
    with e3:
        st.metric("Failed", summary.get("total_failed", 0))
    with e4:
        st.metric("Pass Rate", f"{rate}%")

    # Per-category results
    categories = eval_results.get("categories", {})
    cat_tabs = st.tabs([humanize(cat) for cat in categories.keys()])

    for tab, (cat_name, cat_data) in zip(cat_tabs, categories.items()):
        with tab:
            cat_passed = cat_data.get("passed", 0)
            cat_total = cat_data.get("total", 0)
            st.markdown(f"**{cat_passed}/{cat_total} passed**")

            for test in cat_data.get("tests", []):
                icon = "✅" if test.get("passed") else "❌"
                desc = test.get("description") or test.get("query", test.get("id", "?"))

                if test.get("passed"):
                    st.markdown(f"{icon} {desc}")
                else:
                    st.markdown(f"{icon} {desc}")
                    if "expected_agent" in test:
                        st.markdown(
                            f"&nbsp;&nbsp;&nbsp;&nbsp;Expected: `{test['expected_agent']}/{test['expected_action']}` | "
                            f"Got: `{test.get('actual_agent', '?')}/{test.get('actual_action', '?')}`"
                        )

st.divider()

# ============================================================
# LLM Usage Stats
# ============================================================
st.header("💰 LLM Usage Stats")

USAGE_STATS_PATH = Path(__file__).parent.parent / "logs" / "llm_usage.json"


def _read_llm_stats():
    try:
        if USAGE_STATS_PATH.exists():
            data = json.loads(USAGE_STATS_PATH.read_text())
            cost = round(
                (data.get("total_prompt_tokens", 0) * 0.15 / 1_000_000)
                + (data.get("total_completion_tokens", 0) * 0.6 / 1_000_000),
                4,
            )
            data["estimated_cost_usd"] = cost
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "estimated_cost_usd": 0,
    }


stats = _read_llm_stats()
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total LLM Calls", stats["total_calls"])
with c2:
    st.metric("Prompt Tokens", f"{stats['total_prompt_tokens']:,}")
with c3:
    st.metric("Completion Tokens", f"{stats['total_completion_tokens']:,}")
with c4:
    st.metric("Estimated Cost", f"${stats['estimated_cost_usd']:.4f}")

st.caption(
    "Token usage tracked across all orchestrator routing calls. Cost estimated at GPT-4o-mini rates."
)

# ============================================================
# Footer
# ============================================================
st.divider()

col_refresh, col_clear = st.columns([1, 1])
with col_refresh:
    if st.button("🔄 Refresh Dashboard"):
        st.rerun()
with col_clear:
    if st.button("🗑️ Clear Audit Log"):
        if AUDIT_LOG_PATH.exists():
            AUDIT_LOG_PATH.write_text("")
            st.rerun()

st.caption(
    "ctrlAI — Identity and Permission Control Plane for AI Agents • Authorized to Act Hackathon • Auth0 Token Vault"
)
