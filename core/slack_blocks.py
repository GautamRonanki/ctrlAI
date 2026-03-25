"""
ctrlAI — Slack Block Kit Formatter
====================================
Converts plain text responses into rich Slack Block Kit messages.
Makes the Slack interface look professional and polished.
"""


def humanize(text: str) -> str:
    return text.replace("_", " ").title()


def humanize_lower(text: str) -> str:
    return text.replace("_", " ")


def text_block(text: str) -> dict:
    """Simple markdown text block."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block() -> dict:
    return {"type": "divider"}


def header_block(text: str) -> dict:
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": text, "emoji": True},
    }


def context_block(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def fields_block(fields: list[str]) -> dict:
    """Two-column fields layout."""
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f} for f in fields[:10]],
    }


# ============================================================
# Processing Message
# ============================================================


def processing_blocks() -> list[dict]:
    return [
        text_block("🤔 Processing your request..."),
    ]


# ============================================================
# Agent Result Blocks
# ============================================================


def format_orchestrator_result_blocks(
    response: str, agent: str, action: str, ciba_status: str = None
) -> list[dict]:
    """Format an orchestrator result as Slack blocks."""
    blocks = []

    # Header based on agent
    agent_emoji = {
        "gmail_agent": "📧",
        "calendar_agent": "📅",
        "drive_agent": "📁",
        "github_agent": "🐙",
    }
    emoji = agent_emoji.get(agent, "🤖")

    if agent and agent != "none":
        blocks.append(header_block(f"{emoji} {humanize(agent)}"))

    # CIBA notice if applicable
    if ciba_status == "approved":
        blocks.append(
            context_block("✅ Human approval granted via Guardian push notification")
        )
    elif ciba_status and ciba_status not in ("skipped", None):
        blocks.append(
            context_block(f"🚫 Action {ciba_status} — blocked for your safety")
        )

    # Main response
    blocks.append(text_block(response))

    return blocks


# ============================================================
# Session Summary Blocks
# ============================================================


def format_session_summary_blocks(
    steps: list,
    agent: str = "",
    action: str = "",
    ciba_status: str = None,
    result_summary: str = "",
) -> list[dict]:
    """Format a session summary as Slack blocks for threading."""
    blocks = []
    blocks.append(header_block("🔒 Session Summary"))
    blocks.append(context_block("What ctrlAI accessed on your behalf"))
    blocks.append(divider_block())

    # Services accessed
    services = set()
    permissions_allowed = []
    permissions_denied = []

    service_map = {
        "gmail_agent": "Gmail",
        "calendar_agent": "Google Calendar",
        "drive_agent": "Google Drive",
        "github_agent": "GitHub",
    }

    for step in steps:
        if "agent" in step and step["agent"] and step["agent"] != "none":
            service = service_map.get(step["agent"], step["agent"])
            services.add(service)

        node = step.get("node") or step.get("step", "")
        status = step.get("status", "")

        if node == "permission_gate":
            if status == "allowed":
                permissions_allowed.append(humanize(step.get("agent", "?")))
            elif status in ("denied", "agent_suspended", "permission_denied"):
                permissions_denied.append(
                    f"{humanize(step.get('agent', '?'))}: {status.replace('_', ' ')}"
                )

    # Build fields
    field_items = []
    field_items.append(
        f"*Services accessed:*\n{', '.join(sorted(services)) if services else 'None'}"
    )
    if agent:
        field_items.append(f"*Agent:*\n{humanize(agent)}")
    if action:
        field_items.append(f"*Action:*\n{humanize_lower(action)}")

    if result_summary:
        # First sentence only — keep it brief
        brief = result_summary.split(". ")[0].split("\n")[0][:150]
        if not brief.endswith("."):
            brief += "."
        field_items.append(f"*Result:*\n{brief}")

    blocks.append(fields_block(field_items))

    # Permissions
    if permissions_allowed:
        blocks.append(
            text_block(
                "*Permissions granted:*\n"
                + "\n".join(f"  ✅ {p}" for p in permissions_allowed)
            )
        )
    if permissions_denied:
        blocks.append(
            text_block(
                "*Permissions denied:*\n"
                + "\n".join(f"  🚫 {p}" for p in permissions_denied)
            )
        )

    # CIBA
    if ciba_status == "approved":
        blocks.append(
            text_block(
                "*Human-in-the-loop:*\n  ✅ Approved via Guardian push notification"
            )
        )
    elif ciba_status and ciba_status not in ("skipped", None):
        blocks.append(text_block(f"*Human-in-the-loop:*\n  🚫 {ciba_status.title()}"))

    blocks.append(divider_block())
    blocks.append(
        context_block("Full execution trace available in the admin dashboard")
    )

    return blocks


# ============================================================
# Workflow Summary Blocks
# ============================================================


def format_workflow_summary_blocks(result: dict) -> list[dict]:
    """Format a cross-agent workflow summary as Slack blocks."""
    blocks = []
    blocks.append(header_block("🔒 Session Summary"))
    blocks.append(context_block("What ctrlAI accessed on your behalf"))
    blocks.append(divider_block())

    # Services
    steps = result.get("steps", [])
    services = set()
    for step in steps:
        step_name = step.get("step", "")
        if "gmail" in step_name:
            services.add("Gmail")
        elif "calendar" in step_name:
            services.add("Google Calendar")
        elif "drive" in step_name:
            services.add("Google Drive")
        elif "github" in step_name:
            services.add("GitHub")

    fields = [
        f"*Services accessed:*\n{', '.join(sorted(services)) if services else 'None'}",
        f"*Workflow:*\nMeeting Preparation",
        f"*Steps:*\n{len(steps)}",
        f"*Status:*\n{result.get('status', '?').title()}",
    ]
    blocks.append(fields_block(fields))

    # Inter-agent permissions
    ia_results = result.get("inter_agent_results", [])
    if ia_results:
        blocks.append(divider_block())
        ia_lines = ["*Inter-agent permissions enforced:*"]
        for r in ia_results:
            icon = "✅" if r["status"] == "allowed" else "🚫"
            ia_lines.append(
                f"  {icon} {r['requesting']} → {r['target']}: {r['action']}"
            )
        blocks.append(text_block("\n".join(ia_lines)))

    # Execution steps
    blocks.append(divider_block())
    step_lines = ["*Execution steps:*"]
    for step in steps:
        step_name = humanize(step.get("step", "?"))
        status = step.get("status", "?")
        note = step.get("note", "")
        icon = "✅" if status == "success" else "🚫" if "denied" in status else "ℹ️"
        step_lines.append(f"  {icon} {step_name}: {status}")
        if note:
            step_lines.append(f"      _{note}_")
    blocks.append(text_block("\n".join(step_lines)))

    blocks.append(divider_block())
    blocks.append(
        context_block("Full execution trace available in the admin dashboard")
    )

    return blocks


# ============================================================
# Inter-Agent Result Blocks
# ============================================================


def format_inter_agent_blocks(result: dict) -> list[dict]:
    """Format an inter-agent result as Slack blocks."""
    blocks = []
    status = result["status"]
    req = humanize(result["requesting_agent"])
    tgt = humanize(result["target_agent"])
    action = humanize_lower(result["action"])

    if status == "allowed":
        blocks.append(header_block("✅ Inter-Agent Request Allowed"))
        blocks.append(
            fields_block(
                [
                    f"*From:*\n{req}",
                    f"*To:*\n{tgt}",
                    f"*Action:*\n{action}",
                    f"*Status:*\nAllowed",
                ]
            )
        )
        if result.get("description"):
            blocks.append(context_block(result["description"]))
    else:
        blocks.append(header_block("🚫 Inter-Agent Request Denied"))
        blocks.append(
            fields_block(
                [
                    f"*From:*\n{req}",
                    f"*To:*\n{tgt}",
                    f"*Action:*\n{action}",
                    f"*Status:*\nDenied",
                ]
            )
        )
        blocks.append(
            text_block(
                f"*Reason:* {result.get('reason', 'Not permitted by the inter-agent permission matrix')}"
            )
        )

    blocks.append(context_block("Logged to audit trail"))

    return blocks
