"""
ctrlAI Admin Dashboard — Streamlit
Displays agent registry, permission matrix, audit log, and agent controls.
"""

import json
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pathlib import Path
from datetime import datetime

# Page config
st.set_page_config(
    page_title="ctrlAI — Admin Dashboard",
    page_icon="🛡️",
    layout="wide",
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
                entries.append(json.loads(line))
    return entries


# ============================================================
# Header
# ============================================================
st.title("🛡️ ctrlAI")
st.caption("Identity and Permission Control Plane for AI Agents")
st.divider()

# ============================================================
# Agent Registry
# ============================================================
st.header("Agent Registry")

from core.permissions import get_all_agents, AGENT_REGISTRY, AgentStatus

agents = get_all_agents()

cols = st.columns(4)
for i, (name, agent) in enumerate(agents.items()):
    with cols[i % 4]:
        status_emoji = "🟢" if agent.status == AgentStatus.ACTIVE else "🔴"
        st.markdown(f"### {status_emoji} {name}")
        st.markdown(f"**{agent.description}**")
        st.markdown(f"Provider: `{agent.oauth_provider}`")
        st.markdown(f"Scopes: `{'`, `'.join(agent.permitted_scopes)}`")
        st.markdown(f"High-stakes: `{'`, `'.join(agent.high_stakes_actions)}`")

        # Suspend/Activate button
        if agent.status == AgentStatus.ACTIVE:
            if st.button(f"Suspend {name}", key=f"suspend_{name}"):
                from core.permissions import suspend_agent

                suspend_agent(name)
                st.rerun()
        else:
            if st.button(f"Activate {name}", key=f"activate_{name}"):
                from core.permissions import activate_agent

                activate_agent(name)
                st.rerun()

st.divider()

# ============================================================
# Inter-Agent Permission Matrix
# ============================================================
st.header("Inter-Agent Permission Matrix")

from core.permissions import get_permission_matrix

matrix = get_permission_matrix()
agent_names = list(agents.keys())

# Build matrix display
matrix_data = []
for requester in agent_names:
    row = {"Agent": requester}
    for target in agent_names:
        if requester == target:
            row[target] = "—"
        elif requester in matrix and target in matrix[requester]:
            row[target] = ", ".join(matrix[requester][target])
        else:
            row[target] = "❌ BLOCKED"
    matrix_data.append(row)

df_matrix = pd.DataFrame(matrix_data).set_index("Agent")
st.dataframe(df_matrix, use_container_width=True)

st.caption(
    "Each cell shows what the row agent can request from the column agent. ❌ = all requests blocked."
)

st.divider()

# ============================================================
# Audit Log
# ============================================================
st.header("Audit Log")

entries = load_audit_log()

if not entries:
    st.info("No audit entries yet. Use the Slack bot or API to generate activity.")
else:
    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        event_types = sorted(set(e["event_type"] for e in entries))
        selected_type = st.selectbox("Filter by event type", ["All"] + event_types)
    with col2:
        agent_names_in_log = sorted(set(e["agent_name"] for e in entries))
        selected_agent = st.selectbox("Filter by agent", ["All"] + agent_names_in_log)
    with col3:
        statuses = sorted(set(e["status"] for e in entries))
        selected_status = st.selectbox("Filter by status", ["All"] + statuses)

    # Apply filters
    filtered = entries
    if selected_type != "All":
        filtered = [e for e in filtered if e["event_type"] == selected_type]
    if selected_agent != "All":
        filtered = [e for e in filtered if e["agent_name"] == selected_agent]
    if selected_status != "All":
        filtered = [e for e in filtered if e["status"] == selected_status]

    # Display
    st.metric("Total Events", len(filtered))

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        allowed = len([e for e in entries if e["status"] == "allowed"])
        st.metric("Permissions Allowed", allowed)
    with m2:
        denied = len([e for e in entries if e["status"] == "denied"])
        st.metric(
            "Permissions Denied",
            denied,
            delta=f"-{denied}" if denied > 0 else "0",
            delta_color="inverse",
        )
    with m3:
        ciba_count = len([e for e in entries if e["event_type"] == "ciba"])
        st.metric("CIBA Events", ciba_count)
    with m4:
        api_calls = len([e for e in entries if e["event_type"] == "api_call"])
        st.metric("API Calls", api_calls)

    # Table
    if filtered:
        df = pd.DataFrame(filtered[::-1])  # Reverse for newest first
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%H:%M:%S")
        df["details"] = df["details"].apply(lambda d: json.dumps(d)[:80] if d else "")

        # Color code status
        display_cols = [
            "timestamp",
            "event_type",
            "agent_name",
            "action",
            "status",
            "details",
        ]
        st.dataframe(
            df[display_cols],
            use_container_width=True,
            height=400,
        )

    st.divider()

    # CIBA Events Detail
    ciba_events = [e for e in entries if e["event_type"] == "ciba"]
    if ciba_events:
        st.subheader("CIBA Approval History")
        for event in reversed(ciba_events):
            status = event["status"]
            icon = {
                "requested": "🔔",
                "pending": "⏳",
                "approved": "✅",
                "denied": "❌",
                "expired": "⏰",
                "timeout": "⏰",
            }.get(status, "❓")
            st.markdown(
                f"{icon} **{event['agent_name']}** — {event['action']} — **{status}** at {event['timestamp'][:19]}"
            )

# ============================================================
# Refresh
# ============================================================
st.divider()
if st.button("🔄 Refresh Dashboard"):
    st.rerun()

st.caption("ctrlAI Admin Dashboard • Authorized to Act Hackathon • Auth0 Token Vault")
