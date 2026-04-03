# 🛡️ ctrlAI

**Identity and Permission Control Plane for AI Agents**

Organizations are deploying dozens of AI agents. One manages email, another handles documents, another monitors code repositories. These agents need to interact with each other to complete complex workflows. But without governance, no one knows what these agents can access, what they're doing, or who authorized them.

ctrlAI solves this by treating every AI agent as a first-class identity, each with explicitly scoped permissions, governed inter-agent communication rules, and a complete audit trail. Think of it as IAM (Identity and Access Management), but for AI agents instead of humans.

Built on **Auth0 Token Vault** and **CIBA** for the [Authorized to Act](https://authorizedtoact.devpost.com/) hackathon.

---

## What ctrlAI Demonstrates

- Every agent has a registered identity in Auth0 with explicitly scoped permissions
- Agents cannot access services outside their scopes, enforced at runtime, not just policy
- Inter-agent communication is governed by a permission matrix. Agents can only talk to other agents they are authorized to reach
- High-stakes actions require human approval via CIBA before execution
- Permissions can be changed in real time. Revoke access and it takes effect on the next request
- Every action is audited with a full trace visible in the admin dashboard
- Dynamic evaluation suite generates 100+ tests from the live permission state

---

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────────────┐
│   Slack Bot      │────▶│              FastAPI Backend                 │
│ (Employee-facing)│     │  Auth0 callbacks · Token Vault · CIBA        │
└──────────────────┘     └────────────────┬─────────────────────────────┘
                                          │
                                          ▼
                        ┌───────────────────────────────────┐
                        │      LangGraph Orchestrator       │
                        │  Router → Permission Gate →       │
                        │  Token Retrieval → CIBA Check →   │
                        │  Agent Executor → Formatter       │
                        └──────┬───────────────────┬────────┘
                               │                   │
                    ┌──────────▼───────┐   ┌───────▼─────────┐
                    │ Employee Agents  │   │Autonomous Agents│
                    │ Gmail · Drive    │   │ Security Report │
                    │ Calendar · GitHub│   │ Stale Issue Mon.│
                    └──────────┬───────┘   └───────┬─────────┘
                               │                   │
                        ┌──────▼───────────────────▼────────┐
                        │       Auth0 Token Vault           │
                        │  Google OAuth · GitHub OAuth      │
                        │  Token exchange · Auto-refresh    │
                        └───────────────────────────────────┘

       ┌──────────────────────────────────────────────────────────────┐
       │              Streamlit Admin Dashboard                       │
       │  Agent Registry · Intra-Agent Matrix · Audit Log             │
       │  Security Reports · Dynamic Evals · LLM Usage                │
       └──────────────────────────────────────────────────────────────┘
```

---

## Agents

| Agent | OAuth Provider | Permissions | High-Stakes (CIBA) |
|-------|---------------|-------------|-------------------|
| Gmail Agent | Google OAuth | Read, send, list, search emails | Sending email |
| Drive Agent | Google OAuth | List, read, create, delete, search files | Deleting files |
| Calendar Agent | Google OAuth | List, read, create, modify events | Creating events |
| GitHub Agent | GitHub OAuth | List repos/issues, read, post comments | Posting comments |
| Security Report Agent | Internal | Read audit trail, generate reports | None |
| Stale Issue Monitor | GitHub OAuth | Read repos/issues, post comments, add labels | Comments, labels |

---

## Key Features

### Token Vault Integration
Three agents share a single Google OAuth connection, one uses GitHub OAuth, but each agent has independently scoped permissions. The governance layer operates at the agent identity level, not the provider level. Sharing a connection does not mean sharing access.

### Inter-Agent Permission Matrix
A runtime-enforced matrix defines which agent can communicate with which other agent, and what actions it can request. Any request not explicitly permitted is blocked and logged. Both the requesting agent and the receiving agent enforce the boundary independently.

### CIBA (Client-Initiated Backchannel Authentication)
Every high-stakes action (sending email, deleting files, posting public comments, creating events) triggers an async authorization request via Auth0. The agent pauses, the admin receives an approval request, and only proceeds after explicit confirmation.

### Dynamic Evaluation Suite
Tests are generated dynamically from the live permission state, not hardcoded. Change a permission on the dashboard, run evals, and the test suite adapts automatically. Covers permission enforcement, CIBA configuration, inter-agent matrix, and LLM routing accuracy.

### Rate Limiting
Each agent is rate-limited to 20 requests per 60-second window. Exceeding the limit triggers automatic blocking, audit logging, and an email alert to the admin via the inter-agent communication pipeline.

### Real-Time Permission Changes
Revoke an agent's scope on the admin dashboard and it takes effect immediately on the next Slack request. No restart, no redeployment. The same applies to suspending agents and modifying the inter-agent matrix.

---

## Two Interfaces

**Slack Bot (Employee-facing):** Employees message the ctrlAI Slack bot in natural language. The orchestrator routes to the correct agent, enforces permissions, retrieves tokens from Token Vault, and returns results, all within the Slack thread.

**Streamlit Dashboard (Admin-facing):** Administrators manage the entire agent ecosystem. The dashboard includes the agent registry with permission management, an interactive inter-agent permission matrix, a real-time audit log, autonomous agent controls, a dynamic evaluation suite, and LLM usage tracking.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Agent Framework | LangGraph |
| LLM | Claude 3.5 Sonnet |
| Backend | FastAPI |
| Admin Dashboard | Streamlit |
| User Interface | Slack (Socket Mode) |
| Identity and Auth | Auth0 Token Vault + CIBA |
| Logging | Python logging + JSONL audit trail |

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/GautamRonanki/ctrlAI.git
cd ctrlAI

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your credentials
cp .env.example .env

# Run the FastAPI backend
python app.py

# Run the Streamlit dashboard (separate terminal)
streamlit run dashboard/app.py

# Run the Slack bot (separate terminal)
python -m slack_bot.app
```

### Environment Variables

See `.env.example` for all required variables:
- `AUTH0_DOMAIN` - Your Auth0 tenant domain
- `AUTH0_CLIENT_ID` / `AUTH0_CLIENT_SECRET` - Auth0 application credentials
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` - Slack bot credentials
- `ANTHROPIC_API_KEY` - For Claude LLM calls
- `ADMIN_ALERT_EMAIL` - Email for security alerts

---

## Project Structure

```
ctrlAI/
├── agents/              # Agent implementations (Gmail, Drive, Calendar, GitHub, Security, Stale Issue)
├── core/
│   ├── orchestrator.py  # LangGraph multi-agent state machine
│   ├── permissions.py   # Permission enforcement, rate limiting, inter-agent matrix
│   ├── evals.py         # Dynamic evaluation suite
│   ├── token_service.py # Auth0 Token Vault integration
│   ├── ciba_service.py  # CIBA async authorization
│   ├── inter_agent.py   # Inter-agent communication layer
│   ├── llm.py           # LLM wrapper with token tracking
│   └── logger.py        # Audit logging
├── dashboard/
│   └── app.py           # Streamlit admin dashboard
├── slack_bot/
│   └── app.py           # Slack bot (Socket Mode)
├── config/              # Runtime state (permissions, token store, eval results)
├── logs/                # Audit logs, LLM usage stats
├── app.py               # FastAPI backend
└── requirements.txt
```

---

## Known Limitations

- Single-user demo (no multi-organization support)
- Six agents (production would support dynamic agent registration)
- Single-user demo (no multi-organization support)
- Six agents (production would support dynamic agent registration)
- Permissions managed via dashboard UI (production would add natural language management)
- Permissions managed via dashboard UI (production would add natural language management)

---

## The Vision

ctrlAI is a governance layer for agent-driven organizations. Today it governs six agents across two OAuth providers. The architecture is designed to scale to hundreds of agents across any number of providers, each with a registered identity, scoped permissions, governed communication boundaries, and a complete audit trail.

As AI agents proliferate in organizations, the attack surface created by ungoverned agent identities becomes a critical security risk. ctrlAI is the missing piece that makes agent-driven organizations trustworthy.

---

## License

MIT
