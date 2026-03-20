# ctrlAI

**Identity and Permission Control Plane for AI Agents**

ctrlAI gives every AI agent a registered identity with explicitly scoped permissions, enforces inter-agent communication boundaries, and requires human approval for high-stakes actions — built on Auth0 Token Vault and CIBA.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/ctrlai.git
cd ctrlai

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your credentials
cp .env.example .env

# Run the backend
uvicorn core.app:app --reload --port 8000

# Run the Streamlit dashboard (separate terminal)
streamlit run dashboard/app.py

# Run the Slack bot (separate terminal)
python -m slack_bot.app
```

## Architecture

- **Slack Bot** — Employee-facing interface (Socket Mode)
- **FastAPI Backend** — Auth0 callbacks, Token Vault, CIBA, audit logging
- **LangGraph Orchestrator** — Multi-agent state machine with permission enforcement
- **Streamlit Dashboard** — Admin control plane for permissions and audit logs
- **Auth0 Token Vault** — Secure OAuth token management for agents
- **CIBA** — Human-in-the-loop approval for high-stakes actions

## Agents

| Agent | Service | High-Stakes Actions |
|-------|---------|-------------------|
| Gmail Agent | Gmail API | Sending email |
| Drive Agent | Google Drive API | Deleting files |
| Calendar Agent | Google Calendar API | Creating events |
| GitHub Agent | GitHub API | Public comments |

## Known Limitations

- Single-user demo (no multi-org support)
- Four agents only
- Permissions managed programmatically, not via natural language

## License

MIT
