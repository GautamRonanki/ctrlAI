"""
ctrlAI Admin Dashboard - Streamlit
Identity and Permission Control Plane for AI Agents.
Multi-page layout with sidebar navigation.
"""

import json
import asyncio
import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logger import log_audit
from datetime import datetime

# Page config
st.set_page_config(
    page_title="ctrlAI - Admin Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Password Gate ──
_dashboard_password = os.environ.get("DASHBOARD_PASSWORD")
if _dashboard_password and not st.session_state.get("dashboard_authenticated"):
    st.markdown(
        """
        <div style="display:flex; justify-content:center; align-items:center; min-height:60vh;">
        <div style="width:360px; text-align:center;">
            <div style="font-size:2em; margin-bottom:8px;">🛡️</div>
            <div style="font-size:1.4em; font-weight:700; margin-bottom:4px;">ctrlAI Admin</div>
            <div style="font-size:0.9em; color:#888; margin-bottom:24px;">Enter the dashboard password to continue.</div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_l, col_m, col_r = st.columns([1, 1, 1])
    with col_m:
        pwd = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        if st.button("Login", use_container_width=True):
            if pwd == _dashboard_password:
                st.session_state["dashboard_authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()

# ── Imports from core ──
from core.permissions import (
    get_all_agents,
    AgentStatus,
    get_available_scopes,
    get_available_high_stakes,
    update_scopes,
    update_high_stakes,
    suspend_agent,
    activate_agent,
    get_permission_matrix,
    update_inter_agent_permission,
    get_all_inter_agent_actions,
    check_scope_permission,
    check_inter_agent_permission,
    AVAILABLE_SCOPES,
    grant_temporary_scope,
    get_active_temp_grants,
    get_all_active_temp_grants,
    revoke_temp_grant,
)

# ── Paths ──
AUDIT_LOG_PATH = Path(__file__).parent.parent / "logs" / "audit.jsonl"
USAGE_STATS_PATH = Path(__file__).parent.parent / "logs" / "llm_usage.json"


# ── Shared Helpers ──
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
    return text.replace("_", " ").title()


def humanize_lower(text: str) -> str:
    return text.replace("_", " ")


# ── Label Maps ──
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

IA_ACTION_LABELS = {
    "store_attachment": "Store attachment",
    "check_availability": "Check availability",
    "read_email_context": "Read email context",
    "send_alert_email": "Send alert email",
    "send_email": "Send email",
    "delete_file": "Delete file",
    "create_event": "Create event",
    "read_files": "Read files",
    "read_events": "Read events",
    "read_issues": "Read issues",
    "read_repos": "Read repositories",
    "post_comments": "Post comments",
    "generate_reports": "Generate reports",
}

IA_ACTIONS_BY_TARGET = {
    "gmail_agent": ["read_email_context", "send_email", "send_alert_email"],
    "drive_agent": ["store_attachment", "delete_file", "read_files"],
    "calendar_agent": ["check_availability", "create_event", "read_events"],
    "github_agent": ["read_issues", "post_comments", "read_repos"],
    "security_report_agent": ["generate_reports"],
    "stale_issue_monitor": ["read_issues"],
}

IA_ACTION_TO_SCOPE = {
    "read_email_context": "read_emails",
    "send_email": "send_emails",
    "send_alert_email": "send_emails",
    "store_attachment": "create_files",
    "delete_file": "delete_files",
    "read_files": "read_files",
    "check_availability": "list_events",
    "create_event": "create_events",
    "read_events": "read_events",
    "read_issues": "read_issues",
    "post_comments": "post_comments",
    "read_repos": "read_repos",
    "generate_reports": "generate_reports",
}


# ── Custom CSS ──
st.markdown(
    """
<style>
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
    }
    [data-testid="stSidebar"] .stRadio label {
        color: #c9d1d9 !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,0.05);
        border-radius: 6px;
    }
    [data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.1);
    }

    .agent-card {
        border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px;
        margin-bottom: 10px; background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06); box-sizing: border-box;
    }
    .agent-card-suspended {
        border: 1px solid #ffcdd2; border-radius: 12px; padding: 20px;
        margin-bottom: 10px; background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06); box-sizing: border-box;
    }
    .agent-name { font-size: 1.1em; font-weight: 700; margin-bottom: 6px; }
    .agent-detail { font-size: 0.88em; color: #555; margin-bottom: 3px; }
    .status-active { color: #2e7d32; font-weight: 600; }
    .status-suspended { color: #c62828; font-weight: 600; }
    .scope-badge {
        display: inline-block; background: #e3f2fd; color: #1565c0;
        padding: 2px 8px; border-radius: 12px; font-size: 0.82em; margin: 2px 2px;
    }
    .highstakes-badge {
        display: inline-block; background: #fff3e0; color: #e65100;
        padding: 2px 8px; border-radius: 12px; font-size: 0.82em; margin: 2px 2px;
    }
    .gear-icon-btn {
        position: absolute; top: 10px; right: 10px; background: none;
        border: 1px solid #ddd; border-radius: 6px; cursor: pointer;
        font-size: 1.1em; padding: 5px 5px; line-height: 1; color: #666; z-index: 1;
    }
    .gear-icon-btn:hover { background: #f0f0f0; border-color: #bbb; }
    [data-testid="stSidebar"] button {
        background: transparent !important;
        border: none !important;
        color: #c9d1d9 !important;
        text-align: left !important;
        padding: 10px 16px !important;
        font-size: 0.95em !important;
        border-radius: 8px !important;
        margin-bottom: 2px !important;
    }
    [data-testid="stSidebar"] button:hover {
        background: rgba(255,255,255,0.08) !important;
    }
    [data-testid="stSidebar"] button[kind="primary"] {
        background: rgba(255,255,255,0.12) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    /* Keep collapse button always visible */
    [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
        opacity: 1 !important;
        visibility: visible !important;
    }
    
    /* Compact sidebar buttons */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0px !important;
    }
    [data-testid="stSidebar"] button {
        padding: 8px 12px !important;
        font-size: 0.9em !important;
        margin-bottom: 0px !important;
    }
    [data-testid="stSidebar"] .stElementContainer {
        margin-bottom: 2px !important;
    }
    /* Hide collapse button */
    button[data-testid="stBaseButton-headerNoPadding"] {
        display: none !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# Sidebar Navigation
# ============================================================
with st.sidebar:
    st.markdown(
        """
    <div style="padding: 16px 0 8px 0;">
        <div style="font-size: 1.6em; font-weight: 800; color: #ffffff;">🛡️ ctrlAI</div>
        <div style="font-size: 0.85em; color: #8b949e; margin-top: 2px;">Admin Control Plane</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.divider()

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "📊 Dashboard"

    pages = [
        "📊 Dashboard",
        "🤖 Agent Registry",
        "🔗 Inter-Agent",
        "🔒 Security & Audit",
        "🤖 Autonomous Agents",
        "🧪 Testing",
        "💰 LLM Usage",
    ]

    for p in pages:
        is_active = st.session_state["current_page"] == p
        if st.button(
            p,
            key=f"nav_{p}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["current_page"] = p
            st.rerun()

    page = st.session_state["current_page"]

    st.divider()

    # Quick stats in sidebar
    entries = load_audit_log()
    agents = get_all_agents()
    active_count = sum(1 for a in agents.values() if a.status == AgentStatus.ACTIVE)

    st.markdown(
        f"""
    <div style="color: #8b949e; font-size: 0.82em; padding: 0 4px;">
        <div style="margin-bottom: 6px;">🤖 <b style="color:#c9d1d9;">{active_count}/{len(agents)}</b> agents active</div>
        <div style="margin-bottom: 6px;">📊 <b style="color:#c9d1d9;">{len(entries)}</b> audit events</div>
        <div>🚫 <b style="color:#c9d1d9;">{len([e for e in entries if e["status"] == "denied"])}</b> denials</div>
    </div>
    """,
        unsafe_allow_html=True,
    )


# ============================================================
# Shared metric card helper
# ============================================================
def metric_card(label, value, icon, color):
    return f"""
    <div style="background: white; border: 1px solid #e0e0e0; border-radius: 10px;
                padding: 16px 18px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.04);
                height: 90px; display: flex; flex-direction: column; justify-content: center;">
        <div style="font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 0.5px;">{icon} {label}</div>
        <div style="font-size: 1.8em; font-weight: 700; color: {color}; margin-top: 4px;">{value}</div>
    </div>
    """


# ============================================================
# PAGE: Dashboard
# ============================================================
if page == "📊 Dashboard":
    st.markdown(
        """
    <div style="background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #1a1e2e 100%);
                padding: 18px 24px; border-radius: 12px; margin-bottom: 20px;">
        <div style="font-size: 1.8em; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">
            🛡️ ctrlAI
        </div>
        <div style="font-size: 1.05em; color: #8b949e; margin-top: 4px;">
            Identity and Permission Control Plane for AI Agents
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("")

    tour_col1, tour_col2, tour_col3 = st.columns(3)
    with tour_col1:
        st.markdown("""
        <div style="border:1px solid #e0e0e0; border-radius:10px; padding:16px; text-align:center; background:#f8fffe; height:160px; display:flex; flex-direction:column; justify-content:center; margin-bottom:16px;">
            <div style="font-size:1.5em;">1️⃣</div>
            <div style="font-weight:700; margin-top:4px;">Ask</div>
            <div style="font-size:0.82em; color:#666; margin-top:4px;">Employees message the Slack bot in natural language. The orchestrator routes to the right agent.</div>
        </div>
        """, unsafe_allow_html=True)
    with tour_col2:
        st.markdown("""
        <div style="border:1px solid #e0e0e0; border-radius:10px; padding:16px; text-align:center; background:#fff8f8; height:160px; display:flex; flex-direction:column; justify-content:center; margin-bottom:16px;">
            <div style="font-size:1.5em;">2️⃣</div>
            <div style="font-weight:700; margin-top:4px;">Govern</div>
            <div style="font-size:0.82em; color:#666; margin-top:4px;">Every request passes through permission gates. Denied actions are blocked. High-stakes actions require approval.</div>
        </div>
        """, unsafe_allow_html=True)
    with tour_col3:
        st.markdown("""
        <div style="border:1px solid #e0e0e0; border-radius:10px; padding:16px; text-align:center; background:#f8f8ff; height:160px; display:flex; flex-direction:column; justify-content:center; margin-bottom:16px;">
            <div style="font-size:1.5em;">3️⃣</div>
            <div style="font-weight:700; margin-top:4px;">Audit</div>
            <div style="font-size:0.82em; color:#666; margin-top:4px;">Every action is logged. Admins see what happened, who did it, and whether it was allowed or denied.</div>
        </div>
        """, unsafe_allow_html=True)

    # Metric cards
    denied = len([e for e in entries if e["status"] == "denied"])
    ciba_count = len([e for e in entries if e["event_type"] == "ciba"])
    inter_agent = len(
        [
            e
            for e in entries
            if e["event_type"]
            in ("inter_agent", "inter_agent_execution", "inter_agent_request")
        ]
    )

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.markdown(
            metric_card(
                "Active Agents", f"{active_count}/{len(agents)}", "🤖", "#2e7d32"
            ),
            unsafe_allow_html=True,
        )
    with s2:
        st.markdown(
            metric_card("Total Events", len(entries), "📊", "#1565c0"),
            unsafe_allow_html=True,
        )
    with s3:
        st.markdown(
            metric_card("Denials", denied, "🚫", "#c62828" if denied > 0 else "#888"),
            unsafe_allow_html=True,
        )
    with s4:
        st.markdown(
            metric_card("CIBA Events", ciba_count, "🔐", "#e65100"),
            unsafe_allow_html=True,
        )
    with s5:
        st.markdown(
            metric_card("Inter-Agent", inter_agent, "🔗", "#6a1b9a"),
            unsafe_allow_html=True,
        )

    st.divider()

    # Agent overview cards (compact)
    st.subheader("Agent Overview")
    try:
        _token_store = json.loads((Path(__file__).parent.parent / "config" / "token_store.json").read_text())
        _google_email = _token_store.get("user_email", _token_store.get("email", "Not connected"))
        _github_username = _token_store.get("github_username", "Not connected")
    except Exception:
        _google_email = "Not connected"
        _github_username = "Not connected"
    _all_temp_grants = get_all_active_temp_grants()
    agent_list = list(agents.items())
    for row_start in range(0, len(agent_list), 3):
        row_agents = agent_list[row_start : row_start + 3]
        cols = st.columns(3)
        for j, (name, agent) in enumerate(row_agents):
            with cols[j]:
                is_active = agent.status == AgentStatus.ACTIVE
                status_emoji = "🟢" if is_active else "🔴"
                status_label = "Active" if is_active else "Suspended"
                provider = PROVIDER_LABELS.get(
                    agent.oauth_provider, agent.oauth_provider
                )
                scope_count = len(agent.permitted_scopes)
                hs_count = len(agent.high_stakes_actions)

                if agent.oauth_provider == "google":
                    _connected_as = f"Connected as: {_google_email}"
                elif agent.oauth_provider == "github":
                    _connected_as = f"Connected as: {_github_username}"
                else:
                    _connected_as = "No external connection"

                _agent_temp_grants = [g for g in _all_temp_grants if g["agent_name"] == name]
                _temp_html = ""
                if _agent_temp_grants:
                    _temp_lines = []
                    for _tg in _agent_temp_grants:
                        _tg_label = SCOPE_LABELS.get(_tg["scope"], _tg["scope"])
                        _tg_exp = pd.to_datetime(_tg["expires_at"]).strftime("%H:%M")
                        _temp_lines.append(f"⏳ {_tg_label} (until {_tg_exp})")
                    _temp_html = f'<div style="font-size:0.8em; color:#b8860b; margin-top:3px;">{"  ·  ".join(_temp_lines)}</div>'

                st.markdown(
                    f"""
                <div style="border:1px solid #e0e0e0; border-radius:10px; padding:16px;
                            margin-bottom:12px; background:{"#fff" if is_active else "#fff5f5"}; box-shadow:0 1px 4px rgba(0,0,0,0.04);">
                    <div style="font-weight:700; font-size:1em;">{status_emoji} {humanize(name)}</div>
                    <div style="font-size:0.82em; color:#888; margin-top:4px;">{provider} · {scope_count} scopes · {hs_count} CIBA</div>
                    <div style="font-size:0.8em; color:#666; margin-top:3px;">{_connected_as}</div>
                    {_temp_html}
                </div>
                """,
                    unsafe_allow_html=True,
                )

    # Recent audit activity
    st.divider()
    st.subheader("Recent Activity")
    recent = entries[-5:][::-1] if entries else []
    if recent:
        for entry in recent:
            ts = pd.to_datetime(entry["timestamp"]).strftime("%H:%M:%S")
            agent_name = humanize(entry["agent_name"])
            action = humanize_lower(entry["action"])
            status = entry["status"]
            icon = (
                "✅"
                if status in ("allowed", "success")
                else "🚫"
                if status == "denied"
                else "⚠️"
            )
            st.markdown(f"{icon} **{ts}** — {agent_name} · {action} · {status}")
    else:
        st.info("No activity yet.")

    # ── Security Enforcement Demo ──
    st.divider()
    st.subheader("🛡️ Security Enforcement Demo")
    st.caption("Click any scenario to see how ctrlAI handles permission violations in real time.")
    st.caption("Slack-triggered high-stakes actions use real Auth0 CIBA with Guardian push notifications. Dashboard-triggered autonomous actions use admin approval buttons.")

    demo_col1, demo_col2, demo_col3 = st.columns(3)

    with demo_col1:
        if st.button("🚫 Scope Violation", use_container_width=True):
            # Find an active agent and a scope it does NOT have
            demo_agent = None
            demo_scope = None
            for name, agent in agents.items():
                if agent.status == AgentStatus.ACTIVE:
                    available = AVAILABLE_SCOPES.get(name, [])
                    denied_scopes = [s for s in available if s not in agent.permitted_scopes]
                    if denied_scopes:
                        demo_agent = name
                        demo_scope = denied_scopes[0]
                        break
            if demo_agent:
                result = check_scope_permission(demo_agent, demo_scope, _system_bypass_rate_limit=True)
                if not result:
                    st.error(f"**{humanize(demo_agent)}** attempted `{humanize_lower(demo_scope)}` — **DENIED** by permission gate")
                    st.caption("Audit log entry created.")
                else:
                    st.warning("Scope was unexpectedly allowed.")
            else:
                st.info("No active agent with a revoked scope found. Revoke a scope first.")

    with demo_col2:
        if st.button("🔗 Inter-Agent Violation", use_container_width=True):
            # Find a pair of active agents with no inter-agent access
            matrix = get_permission_matrix()
            active_names = [n for n, a in agents.items() if a.status == AgentStatus.ACTIVE]
            demo_req = None
            demo_tgt = None
            demo_action = None
            for req in active_names:
                for tgt in active_names:
                    if req == tgt:
                        continue
                    allowed = matrix.get(req, {}).get(tgt, [])
                    if not allowed:
                        demo_req = req
                        demo_tgt = tgt
                        demo_action = "send_email"
                        break
                if demo_req:
                    break
            if demo_req:
                result = check_inter_agent_permission(demo_req, demo_tgt, demo_action)
                if not result:
                    action_label = IA_ACTION_LABELS.get(demo_action, demo_action)
                    st.error(f"**{humanize(demo_req)}** attempted to request `{action_label}` from **{humanize(demo_tgt)}** — **BLOCKED** by inter-agent policy")
                    st.caption("Audit log entry created.")
                else:
                    st.warning("Request was unexpectedly allowed.")
            else:
                st.info("No blocked agent pair found in current configuration.")

    with demo_col3:
        if st.button("⏸️ Suspended Agent", use_container_width=True):
            # Pick an active agent, suspend, test, reactivate
            demo_agent = None
            demo_scope = None
            for name, agent in agents.items():
                if agent.status == AgentStatus.ACTIVE and agent.permitted_scopes:
                    demo_agent = name
                    demo_scope = agent.permitted_scopes[0]
                    break
            if demo_agent:
                try:
                    suspend_agent(demo_agent)
                    result = check_scope_permission(demo_agent, demo_scope, _system_bypass_rate_limit=True)
                    if not result:
                        st.warning(f"**{humanize(demo_agent)}** was suspended — all access denied")
                    else:
                        st.error("Suspended agent was unexpectedly allowed access.")
                finally:
                    activate_agent(demo_agent)
                st.success(f"**{humanize(demo_agent)}** reactivated — access restored")
            else:
                st.info("No active agent with scopes found.")


# ============================================================
# PAGE: Agent Registry
# ============================================================
elif page == "🤖 Agent Registry":
    # Check if all agents are currently suspended
    all_suspended = all(a.status != AgentStatus.ACTIVE for a in agents.values())

    reg_header_col, reg_btn_col = st.columns([8, 2])
    with reg_header_col:
        st.header("🤖 Agent Registry")
    with reg_btn_col:
        st.markdown("<br>", unsafe_allow_html=True)
        if all_suspended:
            activate_all_clicked = st.button(
                "🟢 Activate All Agents",
                key="activate_all_agents",
                use_container_width=True,
            )
            suspend_all_clicked = False
        else:
            suspend_all_clicked = st.button(
                "🛑 Suspend All Agents",
                key="suspend_all_agents",
                use_container_width=True,
            )
            activate_all_clicked = False

    @st.dialog("⚠️ Suspend All Agents")
    def confirm_suspend_all():
        st.warning(
            "This will suspend **all agents immediately**. No agent will be able to access any service or execute any action until reactivated by an administrator."
        )
        st.markdown("")
        col_cancel, col_suspend = st.columns(2)
        with col_cancel:
            if st.button("Cancel", key="cancel_suspend_all", use_container_width=True):
                st.rerun()
        with col_suspend:
            if st.button(
                "🛑 Suspend All",
                key="confirm_suspend_all_btn",
                use_container_width=True,
            ):
                for agent_name in agents:
                    suspend_agent(agent_name)
                log_audit(
                    "admin_action",
                    "admin",
                    "suspend_all_agents",
                    "success",
                    {"agents_suspended": len(agents)},
                )
                st.rerun()

    @st.dialog("▶️ Activate All Agents")
    def confirm_activate_all():
        st.info(
            "This will reactivate **all agents immediately**. Every agent will regain access to its permitted services and scopes."
        )
        st.markdown("")
        col_cancel, col_activate = st.columns(2)
        with col_cancel:
            if st.button("Cancel", key="cancel_activate_all", use_container_width=True):
                st.rerun()
        with col_activate:
            if st.button(
                "▶️ Activate All",
                key="confirm_activate_all_btn",
                use_container_width=True,
                type="primary",
            ):
                for agent_name in agents:
                    activate_agent(agent_name)
                log_audit(
                    "admin_action",
                    "admin",
                    "activate_all_agents",
                    "success",
                    {"agents_activated": len(agents)},
                )
                st.rerun()

    if suspend_all_clicked:
        confirm_suspend_all()
    if activate_all_clicked:
        confirm_activate_all()

    # Permission dialog
    @st.dialog("Agent Settings", width="large")
    def show_permission_dialog(agent_name: str):
        agent = get_all_agents()[agent_name]
        is_active = agent.status == AgentStatus.ACTIVE
        status_emoji = "🟢" if is_active else "🔴"

        st.subheader(f"{status_emoji} {humanize(agent_name)}")
        st.caption(agent.description)

        # ── Effective Access Summary ──
        provider_label = PROVIDER_LABELS.get(agent.oauth_provider, agent.oauth_provider)
        status_label = "Active" if is_active else "Suspended"
        num_scopes = len(agent.permitted_scopes)
        num_hs = len(agent.high_stakes_actions)
        st.caption("**Effective Access Summary**")
        st.markdown(
            f"`{provider_label}` · `{status_label}` · **{num_scopes}** permitted scopes · **{num_hs}** CIBA-gated actions"
        )

        matrix = get_permission_matrix()

        # Outgoing: what this agent can request from others
        outgoing = matrix.get(agent_name, {})
        st.caption("**Inter-Agent Access**")
        if outgoing:
            out_parts = []
            for target, actions in outgoing.items():
                labels = ", ".join(IA_ACTION_LABELS.get(a, a) for a in actions)
                out_parts.append(f"**{humanize(target)}**: {labels}")
            st.markdown("Can request from: " + " · ".join(out_parts))
        else:
            st.markdown("Can request from: None")

        # Incoming: which agents can request from this agent
        incoming = {}
        for requester, targets in matrix.items():
            if agent_name in targets and targets[agent_name]:
                incoming[requester] = targets[agent_name]
        if incoming:
            in_parts = []
            for requester, actions in incoming.items():
                labels = ", ".join(IA_ACTION_LABELS.get(a, a) for a in actions)
                in_parts.append(f"**{humanize(requester)}**: {labels}")
            st.markdown("Accepts requests from: " + " · ".join(in_parts))
        else:
            st.markdown("Accepts requests from: None")

        st.divider()

        st.markdown("**Agent Status**")
        if is_active:
            if st.button(
                "⏸️ Suspend Agent",
                key=f"dlg_suspend_{agent_name}",
                use_container_width=True,
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

        available = get_available_scopes(agent_name)
        available_hs = get_available_high_stakes(agent_name)
        current_scopes = list(agent.permitted_scopes)
        current_hs = list(agent.high_stakes_actions)

        all_keys = list(dict.fromkeys(available + available_hs))
        label_map = {**ACTION_LABELS, **SCOPE_LABELS}

        rows = [
            {
                "Scope": label_map.get(k, k),
                "Permissions": k in current_scopes,
                "Requires Approval (CIBA)": k in current_hs,
            }
            for k in all_keys
        ]

        st.caption("**Permissions** - what this agent is allowed to do.")
        st.caption(
            "**Requires Approval (CIBA)** - actions that need your confirmation before executing."
        )

        edited = st.data_editor(
            pd.DataFrame(rows),
            column_config={
                "Scope": st.column_config.TextColumn("Scope", disabled=True),
                "Permissions": st.column_config.CheckboxColumn("Permissions"),
                "Requires Approval (CIBA)": st.column_config.CheckboxColumn(
                    "Requires Approval (CIBA)"
                ),
            },
            hide_index=True,
            use_container_width=True,
            key=f"dlg_table_{agent_name}",
        )

        new_scopes = [
            all_keys[i]
            for i, row in edited.iterrows()
            if row["Permissions"] and all_keys[i] in available
        ]
        new_hs = [
            all_keys[i]
            for i, row in edited.iterrows()
            if row["Requires Approval (CIBA)"] and all_keys[i] in available_hs
        ]

        st.divider()
        st.markdown("**Temporary Access Grants**")
        st.caption("Grant temporary scope access that auto-expires. Use for time-limited tasks.")

        active_grants = get_active_temp_grants(agent_name)
        if active_grants:
            for grant in active_grants:
                exp = pd.to_datetime(grant["expires_at"]).strftime("%H:%M:%S UTC")
                scope_label = SCOPE_LABELS.get(grant["scope"], grant["scope"])
                gcol, rcol = st.columns([5, 1])
                with gcol:
                    st.markdown(f"⏳ **{scope_label}** — expires at {exp}")
                with rcol:
                    if st.button("Revoke", key=f"dlg_revoke_{agent_name}_{grant['scope']}"):
                        revoke_temp_grant(agent_name, grant["scope"])
                        st.rerun()
        else:
            st.caption("No active temporary grants.")

        available_for_grant = [s for s in get_available_scopes(agent_name) if s not in current_scopes]
        if available_for_grant:
            grant_cols = st.columns([3, 2, 2])
            with grant_cols[0]:
                selected_scope = st.selectbox(
                    "Scope",
                    available_for_grant,
                    format_func=lambda s: SCOPE_LABELS.get(s, s),
                    key=f"temp_scope_{agent_name}",
                )
            with grant_cols[1]:
                duration = st.number_input(
                    "Minutes",
                    min_value=5,
                    max_value=480,
                    value=30,
                    key=f"temp_duration_{agent_name}",
                )
            with grant_cols[2]:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button(
                    "⏱️ Grant Temporary Access",
                    key=f"temp_grant_{agent_name}",
                    use_container_width=True,
                ):
                    grant_temporary_scope(agent_name, selected_scope, duration)
                    st.rerun()
        else:
            st.caption("All available scopes are already permanently granted.")

        st.divider()
        if st.button(
            "💾 Save Changes", key=f"dlg_save_{agent_name}", use_container_width=True
        ):
            if new_scopes != current_scopes:
                update_scopes(agent_name, new_scopes)
            if new_hs != current_hs:
                update_high_stakes(agent_name, new_hs)
            st.rerun()

    # Render agent cards
    agent_list = list(agents.items())
    for row_start in range(0, len(agent_list), 3):
        row_agents = agent_list[row_start : row_start + 3]
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
                <div class="{card_class}" style="position:relative;">
                    <button class="gear-icon-btn">⚙️</button>
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

                if st.button("⚙️", key=f"settings_{name}", use_container_width=False):
                    show_permission_dialog(name)

    # JS for gear buttons and card height equalization
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
                cards.forEach(c => { c.style.height = 'auto'; });
                const maxH = Math.max(...Array.from(cards).map(c => c.getBoundingClientRect().height));
                cards.forEach(c => { c.style.height = maxH + 'px'; });
            });
        }
        run(); setTimeout(run, 200); setTimeout(run, 800);
    })();

    (function wireGearButtons() {
        const doc = window.parent.document;
        let debounce;
        function wire() {
            const gears = Array.from(doc.querySelectorAll('.gear-icon-btn'));
            if (gears.length === 0) return;
            const stBtns = Array.from(doc.querySelectorAll('button')).filter(b =>
                b.textContent.trim().startsWith('\u2699') &&
                !b.closest('.agent-card') && !b.closest('.agent-card-suspended')
            );
            if (stBtns.length !== gears.length) return;
            stBtns.forEach(btn => {
                const container = btn.closest('[data-testid="stElementContainer"]') ||
                                  btn.closest('[data-testid="stButton"]')?.parentElement || btn.parentElement?.parentElement;
                if (container) { container.style.height = '0'; container.style.overflow = 'hidden'; container.style.padding = '0'; container.style.margin = '0'; }
            });
            gears.forEach((gear, i) => { gear.onclick = (e) => { e.stopPropagation(); stBtns[i].click(); }; });
        }
        const observer = new MutationObserver(() => { clearTimeout(debounce); debounce = setTimeout(wire, 80); });
        observer.observe(doc.body, { childList: true, subtree: true });
        wire();
    })();
    </script>
    """,
        height=0,
    )


# ============================================================
# PAGE: Inter-Agent
# ============================================================
elif page == "🔗 Inter-Agent":
    st.header("🔗 Inter-Agent Permission Matrix")
    st.caption(
        "Click any cell to manage the relationship between two agents. Enforced at runtime on every inter-agent communication."
    )
    st.caption("Rows = requesting agent · Columns = target agent · ✅ = communication allowed · ❌ = blocked by policy")

    matrix = get_permission_matrix()
    agent_name_list = list(agents.keys())
    all_ia_actions = get_all_inter_agent_actions()

    @st.dialog("Inter-Agent Relationship", width="large")
    def show_inter_agent_dialog(requester: str, target: str):
        current_actions = matrix.get(requester, {}).get(target, [])
        has_access = len(current_actions) > 0

        st.markdown(f"### {humanize(requester)}  ➡️  {humanize(target)}")
        req_agent = agents.get(requester)
        tgt_agent = agents.get(target)
        if req_agent and tgt_agent:
            st.caption(f"**{humanize(requester)}:** {req_agent.description}")
            st.caption(f"**{humanize(target)}:** {tgt_agent.description}")

        st.divider()

        if has_access:
            st.success(f"✅ {humanize(requester)} has access to {humanize(target)}")
        else:
            st.error(f"❌ {humanize(requester)} is blocked from {humanize(target)}")

        st.markdown("**Permitted Actions**")
        st.caption("Toggle which actions this agent can request from the target agent.")

        new_actions = []
        target_actions = IA_ACTIONS_BY_TARGET.get(target, all_ia_actions)
        tgt_agent_obj = get_all_agents().get(target)
        tgt_scopes = tgt_agent_obj.permitted_scopes if tgt_agent_obj else []

        for action in target_actions:
            label = IA_ACTION_LABELS.get(action, action)
            checked = action in current_actions
            if st.checkbox(
                label, value=checked, key=f"ia_{requester}_{target}_{action}"
            ):
                new_actions.append(action)
            required_scope = IA_ACTION_TO_SCOPE.get(action)
            if checked and required_scope and required_scope not in tgt_scopes:
                scope_label = SCOPE_LABELS.get(required_scope, required_scope)
                st.caption(
                    f"⚠️ {humanize(target)} currently has '{scope_label}' disabled - this action may fail at runtime."
                )

        st.divider()

        col_test, col_save = st.columns(2)
        with col_test:
            if current_actions:
                if st.button(
                    f"🧪 Test All ({len(current_actions)} actions)",
                    key=f"ia_test_{requester}_{target}",
                    use_container_width=True,
                ):
                    from core.inter_agent import execute_inter_agent_request

                    for test_action in current_actions:
                        test_result = run_async(
                            execute_inter_agent_request(
                                requesting_agent=requester,
                                target_agent=target,
                                action=test_action,
                            )
                        )
                        action_label = IA_ACTION_LABELS.get(test_action, test_action)
                        if test_result["status"] == "allowed":
                            st.success(f"✅ {action_label} - Allowed")
                        else:
                            st.error(f"🚫 {action_label} - Denied")
            else:
                st.info("No actions permitted - grant access to enable testing")
        with col_save:
            if st.button(
                "💾 Save Changes",
                key=f"ia_save_{requester}_{target}",
                use_container_width=True,
            ):
                update_inter_agent_permission(requester, target, new_actions)
                st.rerun()

    # Build matrix HTML table
    matrix_html_rows = []
    header_cells = '<th style="padding:10px 8px; text-align:left; background:#f0f2f6; border:1px solid #ddd; font-size:0.85em;">Agent</th>'
    for name in agent_name_list:
        header_cells += f'<th style="padding:10px 6px; text-align:center; background:#f0f2f6; border:1px solid #ddd; font-size:0.8em; min-width:80px;">{humanize(name)}</th>'
    matrix_html_rows.append(f"<tr>{header_cells}</tr>")

    for requester in agent_name_list:
        cells = f'<td style="padding:10px 8px; font-weight:600; background:#fafafa; border:1px solid #ddd; font-size:0.85em;">{humanize(requester)}</td>'
        for target in agent_name_list:
            if requester == target:
                cells += '<td style="padding:8px; text-align:center; border:1px solid #ddd; color:#999;">-</td>'
            else:
                has_access = (
                    requester in matrix
                    and target in matrix[requester]
                    and len(matrix[requester][target]) > 0
                )
                if has_access:
                    action_count = len(matrix[requester][target])
                    cells += f'<td style="padding:8px; text-align:center; border:1px solid #ddd; background:#e8f5e9; cursor:pointer;" title="Click to manage">✅ <span style="font-size:0.75em; color:#555;">{action_count} action{"s" if action_count > 1 else ""}</span></td>'
                else:
                    cells += '<td style="padding:8px; text-align:center; border:1px solid #ddd; background:#ffebee; cursor:pointer;" title="Click to manage">❌ <span style="font-size:0.75em; color:#999;">blocked</span></td>'
        matrix_html_rows.append(f"<tr>{cells}</tr>")

    st.markdown(
        f"""<div style="overflow-x: auto;"><table style="width:100%; border-collapse:collapse; border-radius:3px; overflow:hidden;">
        {"".join(matrix_html_rows)}
    </table></div>""",
        unsafe_allow_html=True,
    )

    # Hidden buttons for matrix cell clicks
    btn_cols_per_row = len(agent_name_list)
    for requester in agent_name_list:
        row_cols = st.columns(btn_cols_per_row + 1)
        with row_cols[0]:
            st.empty()
        for j, target in enumerate(agent_name_list):
            with row_cols[j + 1]:
                if requester != target:
                    if st.button(
                        "•",
                        key=f"matrix_{requester}_{target}",
                        use_container_width=True,
                    ):
                        show_inter_agent_dialog(requester, target)

    # JS to wire matrix clicks
    components.html(
        """
    <script>
    (function wireMatrixClicks() {
        const doc = window.parent.document;
        let debounce;
        let observer;
        function wire() {
            const table = doc.querySelector('table');
            if (!table) { if (observer) { observer.disconnect(); observer = null; } return; }
            const allBtns = Array.from(doc.querySelectorAll('button'));
            const gearBtns = allBtns.filter(b => b.textContent.trim() === '•');
            gearBtns.forEach(btn => {
                if (btn.textContent.trim() !== '•') return;
                const wrapper = btn.closest('[data-testid="stButton"]');
                if (wrapper) { wrapper.style.display = 'none'; }
            });
            const rows = table.querySelectorAll('tr');
            let btnIndex = 0;
            for (let i = 1; i < rows.length; i++) {
                const cells = rows[i].querySelectorAll('td');
                for (let j = 1; j < cells.length; j++) {
                    if (cells[j].textContent.trim() === '-') continue;
                    const btn = gearBtns[btnIndex];
                    if (btn) {
                        cells[j].style.cursor = 'pointer';
                        cells[j].onclick = () => btn.click();
                        cells[j].onmouseover = () => { cells[j].style.opacity = '0.7'; };
                        cells[j].onmouseout = () => { cells[j].style.opacity = '1'; };
                    }
                    btnIndex++;
                }
            }
        }
        observer = new MutationObserver(() => { clearTimeout(debounce); debounce = setTimeout(wire, 150); });
        observer.observe(doc.body, { childList: true, subtree: true });
        wire(); setTimeout(wire, 300); setTimeout(wire, 800);
    })();
    </script>
    """,
        height=0,
    )


# ============================================================
# PAGE: Security & Audit
# ============================================================
elif page == "🔒 Security & Audit":
    # Security Report Agent
    st.subheader("🔒 Security Report Agent")
    st.caption(
        "Autonomous agent — monitors the audit trail and alerts on security violations. Dashboard-triggered with admin approval."
    )

    try:
        from agents.security_report_agent import generate_security_report, send_alert_email
    except ImportError as e:
        st.error(f"Failed to load Security Report Agent: {e}")
        generate_security_report = None
        send_alert_email = None

    @st.dialog("🔒 Security Report", width="large")
    def show_security_report_dialog(send_alert_flag: bool):
        try:
            with st.spinner("Security Report Agent running through permission pipeline..."):
                report_result = run_async(generate_security_report())
        except Exception as e:
            st.error(f"Security Report Agent failed: {e}")
            return

        if report_result["status"] == "blocked":
            st.error(f"🚫 Blocked: {report_result['reason']}")
        elif report_result["status"] == "success":
            st.success("✅ Report generated successfully")

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

            st.divider()
            st.markdown(report_result["report"])

            if send_alert_flag and report_result.get("has_critical"):
                st.divider()
                st.warning(
                    "⚠️ Critical issues detected - sending alert email via Gmail Agent..."
                )
                try:
                    from core.token_service import get_google_token, get_stored_refresh_token

                    refresh_token = get_stored_refresh_token()
                    if refresh_token:
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
                        st.error("❌ No refresh token available.")
                except Exception:
                    st.warning(
                        "Alert email requires an active OAuth session. Use the Slack bot for live agent actions."
                    )
            elif send_alert_flag and not report_result.get("has_critical"):
                st.info("✅ No critical issues found - no alert email needed.")
        else:
            st.error(f"❌ Error: {report_result.get('reason', 'Unknown error')}")

    if generate_security_report is not None:
        report_col1, report_col2, report_col3 = st.columns([2, 2, 6])
        with report_col1:
            run_report_clicked = st.button("▶️ Run Now", key="run_security_report", use_container_width=True)
        with report_col2:
            run_alert_clicked = st.button(
                "▶️ Run & Alert",
                key="run_and_alert",
                use_container_width=True,
                help="Generate report and send email alert if critical issues found",
            )

        if run_report_clicked:
            show_security_report_dialog(send_alert_flag=False)
        if run_alert_clicked:
            show_security_report_dialog(send_alert_flag=True)

    st.divider()

    # Audit Log
    st.header("📋 Audit Log")

    if not entries:
        st.info("No audit entries yet. Use the Slack bot or API to generate activity.")
    else:

        def clear_filters():
            st.session_state["filter_event_type"] = []
            st.session_state["filter_agent"] = []
            st.session_state["filter_status"] = []

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
            status_labels_map = {s: humanize(s) for s in statuses}
            selected_statuses = st.multiselect(
                "Filter by status",
                options=statuses,
                format_func=lambda x: status_labels_map.get(x, x),
                key="filter_status",
            )
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("🧹 Clear Filters", on_click=clear_filters)

        filtered = entries
        if selected_types:
            filtered = [e for e in filtered if e["event_type"] in selected_types]
        if selected_agents:
            filtered = [e for e in filtered if e["agent_name"] in selected_agents]
        if selected_statuses:
            filtered = [e for e in filtered if e["status"] in selected_statuses]

        m1, m2, m3, m4 = st.columns(4)
        allowed_count = len([e for e in filtered if e["status"] == "allowed"])
        denied_count = len([e for e in filtered if e["status"] == "denied"])
        success_count = len([e for e in filtered if e["status"] == "success"])
        error_count = len([e for e in filtered if e["status"] == "error"])
        with m1:
            st.markdown(metric_card("Allowed", allowed_count, "✅", "#2e7d32"), unsafe_allow_html=True)
        with m2:
            st.markdown(metric_card("Denied", denied_count, "🚫", "#c62828" if denied_count > 0 else "#888"), unsafe_allow_html=True)
        with m3:
            st.markdown(metric_card("Success", success_count, "✅", "#2e7d32"), unsafe_allow_html=True)
        with m4:
            st.markdown(metric_card("Errors", error_count, "⚠️", "#e65100" if error_count > 0 else "#888"), unsafe_allow_html=True)

        if filtered:

            def status_html(raw_status):
                s = raw_status.replace("_", " ").title()
                styles = {
                    "Allowed": ("✅", "#2e7d32", "#e8f5e9"),
                    "Success": ("✅", "#2e7d32", "#e8f5e9"),
                    "Denied": ("🚫", "#c62828", "#ffebee"),
                    "Error": ("⚠️", "#e65100", "#fff3e0"),
                    "Executing": ("🔄", "#1565c0", "#e3f2fd"),
                    "Blocked": ("🚫", "#c62828", "#ffebee"),
                }
                icon, fg, bg = styles.get(s, ("", "#555", "#f5f5f5"))
                return f'<span style="background:{bg}; color:{fg}; padding:3px 10px; border-radius:12px; font-size:0.82em; font-weight:600;">{icon} {s}</span>'

            rows_html = ""
            for i, entry in enumerate(filtered[::-1][:100]):
                bg = "#fafafa" if i % 2 == 0 else "#ffffff"
                dt = pd.to_datetime(entry["timestamp"])
                date_str = dt.strftime("%b %d")
                ts = dt.strftime("%H:%M:%S")
                evt = humanize(entry["event_type"])
                agent_nm = humanize(entry["agent_name"])
                action = humanize_lower(entry["action"])
                status = status_html(entry["status"])
                details = (
                    json.dumps(entry.get("details", ""))[:60]
                    if entry.get("details")
                    else ""
                )

                rows_html += f"""
                <tr style="background:{bg};">
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.85em; color:#666;">{date_str}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.85em; color:#666;">{ts}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.85em;">{evt}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.85em; font-weight:600;">{agent_nm}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.85em;">{action}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee;">{status}</td>
                    <td style="padding:10px 12px; border-bottom:1px solid #eee; font-size:0.78em; color:#888; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{details}</td>
                </tr>
                """

            table_html = f"""
            <div style="max-height:420px; overflow-y:auto; border:1px solid #e0e0e0; border-radius:10px;">
                <table style="width:100%; border-collapse:collapse;">
                    <thead>
                        <tr style="background:#f0f2f6; position:sticky; top:0; z-index:1;">
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Date</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Time</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Event Type</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Agent</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Action</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Status</th>
                            <th style="padding:12px; text-align:left; font-size:0.82em; color:#555; border-bottom:2px solid #ddd;">Details</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """

            table_with_sort = f"""
            <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@400;600;700&display=swap" rel="stylesheet">
            <style>
                * {{ font-family: 'Source Sans Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .audit-table th {{ cursor: pointer; user-select: none; }}
                .audit-table th:hover {{ background: #e0e4ea !important; }}
                .sort-arrow {{ font-size: 0.7em; margin-left: 4px; color: #999; }}
            </style>
            {table_html}
            <script>
            (function() {{
                const table = document.querySelector('table');
                if (!table) return;
                const headers = table.querySelectorAll('th');
                let sortCol = -1, sortAsc = true;
                headers.forEach((th, i) => {{
                    th.addEventListener('click', () => {{
                        if (sortCol === i) {{ sortAsc = !sortAsc; }} else {{ sortCol = i; sortAsc = true; }}
                        headers.forEach(h => {{ let ex = h.querySelector('.sort-arrow'); if (ex) ex.remove(); }});
                        const arrow = document.createElement('span');
                        arrow.className = 'sort-arrow';
                        arrow.textContent = sortAsc ? ' ▲' : ' ▼';
                        th.appendChild(arrow);
                        const tbody = table.querySelector('tbody');
                        const rows = Array.from(tbody.querySelectorAll('tr'));
                        rows.sort((a, b) => {{
                            const aText = a.children[i]?.textContent.trim() || '';
                            const bText = b.children[i]?.textContent.trim() || '';
                            return sortAsc ? aText.localeCompare(bText) : bText.localeCompare(aText);
                        }});
                        rows.forEach(r => tbody.appendChild(r));
                    }});
                }});
            }})();
            </script>
            """
            components.html(table_with_sort, height=440, scrolling=True)

    # Footer buttons
    st.divider()
    col_refresh, col_clear = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 Refresh"):
            st.rerun()
    with col_clear:
        if st.button("🗑️ Clear Audit Log"):
            if AUDIT_LOG_PATH.exists():
                AUDIT_LOG_PATH.write_text("")
                st.rerun()


# ============================================================
# PAGE: Autonomous Agents
# ============================================================
elif page == "🤖 Autonomous Agents":
    st.header("🤖 Autonomous Agents")
    st.caption("Agents that operate independently, retrieving their own OAuth tokens from Token Vault and executing on schedule or manual trigger.")

    # Stale Issue Monitor
    st.subheader("🔍 Stale Issue Monitor")
    st.caption(
        "Autonomous OAuth agent — retrieves its own GitHub token from Token Vault, monitors repos for stale issues. High-stakes actions (commenting, labeling) require admin approval via dashboard before execution."
    )

    try:
        from agents.stale_issue_monitor import run_stale_issue_monitor
    except ImportError as e:
        st.error(f"Failed to load Stale Issue Monitor agent: {e}")
        run_stale_issue_monitor = None

    @st.dialog("🔍 Stale Issue Monitor", width="large")
    def show_stale_issue_dialog(owner: str, repo: str, execute: bool, test: bool):
        try:
            print('DEBUG: ABOUT TO CALL MONITOR')
            with st.spinner(
                "Stale Issue Monitor running through permission pipeline → Token Vault → GitHub API..."
            ):
                result = run_async(
                    run_stale_issue_monitor(
                        owner=owner,
                        repo=repo,
                        execute_actions=execute,
                        ciba_approved=False,
                        stale_threshold_override=0 if test else None,
                    )
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            st.error(f"Stale Issue Monitor failed: {e}")
            return

        if result["status"] == "blocked":
            st.error(f"🚫 Blocked: {result['reason']}")
        elif result["status"] == "error":
            st.error(f"❌ Error: {result['reason']}")
        elif result["status"] == "awaiting_ciba":
            st.warning(f"🔐 {result['reason']}")
            st.markdown(result.get("report", ""))
            if st.button(
                "✅ Approve & Execute",
                key="sim_ciba_approve_dlg",
                use_container_width=True,
            ):
                with st.spinner("Executing high-stakes actions with CIBA approval..."):
                    approved_result = run_async(
                        run_stale_issue_monitor(
                            owner=owner,
                            repo=repo,
                            execute_actions=True,
                            ciba_approved=True,
                            stale_threshold_override=0 if test else None,
                        )
                    )
                if approved_result["status"] == "success":
                    st.success("✅ Actions executed successfully")
                    if approved_result.get("actions_taken"):
                        for action in approved_result["actions_taken"]:
                            st.markdown(
                                f"  ✅ Issue #{action['issue']} - {action['action']}"
                            )
        elif result["status"] == "success":
            st.success("✅ Scan complete")
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
            st.divider()
            categories = result.get("categories", {})
            if categories.get("two_plus_weeks"):
                st.markdown("**🔴 2+ Weeks Inactive**")
                for issue in categories["two_plus_weeks"]:
                    st.markdown(
                        f"  • **#{issue['number']}** - {issue['title']} ({issue['days_inactive']} days)"
                    )
            if categories.get("two_weeks"):
                st.markdown("**🟠 2 Weeks Inactive**")
                for issue in categories["two_weeks"]:
                    st.markdown(
                        f"  • **#{issue['number']}** - {issue['title']} ({issue['days_inactive']} days)"
                    )
            if categories.get("one_to_two_weeks"):
                st.markdown("**🟡 1-2 Weeks Inactive**")
                for issue in categories["one_to_two_weeks"]:
                    st.markdown(
                        f"  • **#{issue['number']}** - {issue['title']} ({issue['days_inactive']} days)"
                    )

    if run_stale_issue_monitor is not None:
        sim_col1, sim_col2, sim_col3 = st.columns([2, 2, 6])
        with sim_col1:
            sim_owner = st.text_input("Owner", value="GautamRonanki", key="sim_owner")
        with sim_col2:
            sim_repo = st.text_input("Repo", value="ctrlAI", key="sim_repo")

        if "sim_test_mode" not in st.session_state:
            st.session_state["sim_test_mode"] = False

        sim_btn_col1, sim_btn_col2, sim_btn_col3, sim_btn_col4 = st.columns([2, 2, 2, 4])
        with sim_btn_col1:
            run_scan_clicked = st.button(
                "▶️ Run Scan", key="run_stale_scan", use_container_width=True
            )
        with sim_btn_col2:
            run_act_clicked = st.button(
                "▶️ Run & Act", key="run_stale_act", use_container_width=True
            )
        with sim_btn_col3:
            test_mode = st.checkbox(
                "🧪 Test Mode",
                key="sim_test_mode",
                help="Sets threshold to 0 days so all issues appear stale",
            )

        if run_scan_clicked:
            show_stale_issue_dialog(sim_owner, sim_repo, execute=False, test=test_mode)
        if run_act_clicked:
            show_stale_issue_dialog(sim_owner, sim_repo, execute=True, test=test_mode)


# ============================================================
# PAGE: Testing
# ============================================================
elif page == "🧪 Testing":
    st.header("🧪 Dynamic Evaluation Suite")
    st.caption(
        "Tests are generated dynamically from the live permission state. Change permissions, run evals — tests adapt automatically."
    )

    from core.evals import load_eval_results, run_all_evals

    eval_results = load_eval_results()

    col_run, col_info = st.columns([1, 3])
    with col_run:
        run_evals_clicked = st.button("▶️ Run Evals", use_container_width=True)
    with col_info:
        if eval_results:
            st.caption(f"Last run: {eval_results.get('timestamp', '?')[:19]}")
        else:
            st.caption("No eval results yet. Click Run Evals to test the system.")

    if run_evals_clicked:
        with st.spinner("Running dynamic evaluation suite..."):
            eval_results = run_async(run_all_evals(include_routing=True))

    if eval_results:
        summary = eval_results.get("summary", {})
        total = summary.get("total_tests", 0)
        passed = summary.get("total_passed", 0)
        failed = summary.get("total_failed", 0)
        rate = summary.get("pass_rate", 0)

        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.markdown(
                metric_card("Total Tests", total, "🧪", "#1565c0"),
                unsafe_allow_html=True,
            )
        with e2:
            st.markdown(
                metric_card("Passed", passed, "✅", "#2e7d32"), unsafe_allow_html=True
            )
        with e3:
            st.markdown(
                metric_card(
                    "Failed", failed, "❌", "#c62828" if failed > 0 else "#888"
                ),
                unsafe_allow_html=True,
            )
        with e4:
            st.markdown(
                metric_card(
                    "Pass Rate",
                    f"{rate}%",
                    "📊",
                    "#2e7d32" if rate == 100 else "#e65100",
                ),
                unsafe_allow_html=True,
            )

        st.divider()

        categories = eval_results.get("categories", {})
        st.caption("Each category validates a different layer of the ctrlAI governance pipeline. Green = enforcement working correctly.")
        cat_tabs = st.tabs(
            [
                f"{humanize(cat)} ({cat_data['passed']}/{cat_data['total']})"
                for cat, cat_data in categories.items()
            ]
        )

        for tab, (cat_name, cat_data) in zip(cat_tabs, categories.items()):
            with tab:
                failed_tests = [
                    t for t in cat_data.get("tests", []) if not t.get("passed")
                ]
                passed_tests = [t for t in cat_data.get("tests", []) if t.get("passed")]

                if failed_tests:
                    st.markdown("**❌ Failed**")
                    for test in failed_tests:
                        desc = test.get("description") or test.get(
                            "query", test.get("id", "?")
                        )
                        st.markdown(f"🚫 {desc}")
                        if "expected_agent" in test:
                            st.caption(
                                f"Expected: `{test['expected_agent']}/{test['expected_action']}` → Got: `{test.get('actual_agent', '?')}/{test.get('actual_action', '?')}`"
                            )
                    st.divider()

                st.markdown(f"**✅ Passed ({len(passed_tests)})**")
                for test in passed_tests:
                    desc = test.get("description") or test.get(
                        "query", test.get("id", "?")
                    )
                    st.markdown(f"✅ {desc}")


# ============================================================
# PAGE: LLM Usage
# ============================================================
elif page == "💰 LLM Usage":
    st.header("💰 LLM Usage Stats")

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
        st.markdown(
            metric_card("Total LLM Calls", stats["total_calls"], "🤖", "#1565c0"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            metric_card(
                "Prompt Tokens", f"{stats['total_prompt_tokens']:,}", "📝", "#6a1b9a"
            ),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            metric_card(
                "Completion Tokens",
                f"{stats['total_completion_tokens']:,}",
                "💬",
                "#e65100",
            ),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            metric_card(
                "Estimated Cost", f"${stats['estimated_cost_usd']:.4f}", "💵", "#2e7d32"
            ),
            unsafe_allow_html=True,
        )

    st.caption(
        "Token usage tracked across all orchestrator routing calls. Cost estimated at GPT-4o-mini rates."
    )

    st.divider()

    total_tokens = stats["total_prompt_tokens"] + stats["total_completion_tokens"]
    if total_tokens > 0:
        st.progress(
            stats["total_prompt_tokens"] / total_tokens,
            text=f"Prompt: {stats['total_prompt_tokens']:,} / Completion: {stats['total_completion_tokens']:,}",
        )

    st.divider()

    reset_col, _ = st.columns([1, 3])
    with reset_col:
        if st.button("🗑️ Reset Stats", use_container_width=True):
            USAGE_STATS_PATH.write_text(
                json.dumps({"total_calls": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0})
            )
            st.rerun()


# ============================================================
# Footer (all pages)
# ============================================================
st.markdown(
    """
<div style="text-align: center; padding: 20px 0 10px 0; color: #999; font-size: 0.82em;">
    🛡️ <b>ctrlAI</b> · Identity and Permission Control Plane for AI Agents<br>
    <span style="color: #bbb;">Authorized to Act Hackathon · Auth0 Token Vault · CIBA</span>
</div>
""",
    unsafe_allow_html=True,
)
