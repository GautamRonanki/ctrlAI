"""
ctrlAI Admin Dashboard — Streamlit
Identity and Permission Control Plane for AI Agents.
"""

import json
import asyncio
import streamlit as st
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
    }
    .agent-card-suspended {
        border: 1px solid #ffcdd2;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 10px;
        background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
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
    from core.permissions import get_all_agents, AgentStatus

    for a in get_all_agents().values():
        if a.status == AgentStatus.ACTIVE:
            active_count += 1
    st.metric("Active Agents", f"{active_count} / 4")
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
# Agent Registry
# ============================================================
st.header("🤖 Agent Registry")

agents = get_all_agents()

cols = st.columns(4)
for i, (name, agent) in enumerate(agents.items()):
    with cols[i % 4]:
        is_active = agent.status == AgentStatus.ACTIVE
        card_class = "agent-card" if is_active else "agent-card-suspended"
        status_class = "status-active" if is_active else "status-suspended"
        status_label = "Active" if is_active else "Suspended"
        status_emoji = "🟢" if is_active else "🔴"

        scope_badges = "".join(
            f'<span class="scope-badge">{humanize_lower(s)}</span>'
            for s in agent.permitted_scopes
        )
        highstakes_badges = "".join(
            f'<span class="highstakes-badge">{humanize_lower(s)}</span>'
            for s in agent.high_stakes_actions
        )

        st.markdown(
            f"""
        <div class="{card_class}">
            <div class="agent-name">{status_emoji} {humanize(name)}</div>
            <div class="agent-detail">{agent.description}</div>
            <div class="agent-detail" style="margin-top:8px;"><b>Provider:</b> {humanize(agent.oauth_provider)}</div>
            <div class="agent-detail"><b>Scopes:</b> {scope_badges}</div>
            <div class="agent-detail"><b>High-Stakes:</b> {highstakes_badges}</div>
            <div class="agent-detail" style="margin-top:6px;"><b>Status:</b> <span class="{status_class}">{status_label}</span></div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if is_active:
            if st.button(f"⏸️ Suspend", key=f"suspend_{name}"):
                from core.permissions import suspend_agent

                suspend_agent(name)
                st.rerun()
        else:
            if st.button(f"▶️ Activate", key=f"activate_{name}"):
                from core.permissions import activate_agent

                activate_agent(name)
                st.rerun()

st.divider()

# ============================================================
# Agent Permission Management
# ============================================================
st.header("⚙️ Agent Permission Management")
st.caption(
    "Toggle scopes and high-stakes actions per agent. Changes take effect immediately on the next request."
)

from core.permissions import (
    get_available_scopes,
    get_available_high_stakes,
    update_scopes,
    update_high_stakes,
)

mgmt_tabs = st.tabs([humanize(name) for name in agents.keys()])

for tab, (name, agent) in zip(mgmt_tabs, agents.items()):
    with tab:
        col_scopes, col_highstakes = st.columns(2)

        with col_scopes:
            st.markdown("**Permitted Scopes**")
            st.caption("Toggle which scopes this agent is allowed to use.")
            available = get_available_scopes(name)
            current_scopes = list(agent.permitted_scopes)

            new_scopes = []
            for scope in available:
                checked = st.checkbox(
                    humanize_lower(scope),
                    value=scope in current_scopes,
                    key=f"scope_{name}_{scope}",
                )
                if checked:
                    new_scopes.append(scope)

            if new_scopes != current_scopes:
                update_scopes(name, new_scopes)
                st.rerun()

        with col_highstakes:
            st.markdown("**High-Stakes Actions (require CIBA approval)**")
            st.caption("Toggle which actions require human approval before executing.")
            available_hs = get_available_high_stakes(name)
            current_hs = list(agent.high_stakes_actions)

            new_hs = []
            for action in available_hs:
                checked = st.checkbox(
                    humanize_lower(action),
                    value=action in current_hs,
                    key=f"hs_{name}_{action}",
                )
                if checked:
                    new_hs.append(action)

            if new_hs != current_hs:
                update_high_stakes(name, new_hs)
                st.rerun()

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
