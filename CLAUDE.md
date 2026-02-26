# Claude Code Instructions for pagemenot

## CRITICAL RULES

### #0: SYSTEMATIC RULE ENFORCEMENT
State which rules apply BEFORE any task. If violated: STOP, fix, add validation.

| Task | Rules |
|------|-------|
| Git | #24, #26 |
| New code | #29 |
| Any docs/README | #30 |
| Long jobs | #7, #0.95 |
| Agents | #25 |

### #0.95: NO SLEEP LOOPS
FORBIDDEN: `sleep N && tail`, polling loops. Launch in detached screen, report name + log path, move on.

### #5: CREDENTIALS
`.env` only. Never in code. Never hardcode API keys, tokens, or secrets.

### #7: SCREEN FOR LONG JOBS
`screen -dmS <name> bash -c "PYTHONUNBUFFERED=1 python script.py > logs/... 2>&1"`

### #11: NO FLUFF — CODE AND PROSE
**Code:** No defensive comments, no "# This is designed to...", no explanatory prints unless they carry data. Variable names are self-documenting. No dead code, no commented-out blocks.
**Responses:** No preamble ("Great question!"), no summaries restating what was just done, no sign-offs. Lead with the result.
**Docs:** No motivation paragraphs, no benefit statements. Facts only: what it does, inputs, outputs.
FORBIDDEN everywhere: "robust", "seamless", "leverages", "powerful", "comprehensive", "state-of-the-art", "it's worth noting".

### #24: COMMIT DISCIPLINE
NEVER commit without explicit user command. NEVER commit credentials or secrets.

### #25: DELEGATE — AGENTS USE SCREEN, NEVER BLOCK
Task agents MUST use `screen -dmS` for any work >2 min. FORBIDDEN: blocking terminal waiting for agent results. Launch screen, report name + log path, move on. Agent inventory: `.claude/agents/README.md`.

### #26: GIT SAFETY
NEVER force push or amend without explicit request.

### #28: NO DUMPS
NEVER dump diffs, edit outputs, or large code blocks. Summarize in 1-2 lines.

### #29: NO NEW SCRIPTS — EXTEND EXISTING ONES
FORBIDDEN: Creating new scripts when an existing script covers the same domain/function.
REQUIRED: Search first, add parameters or functions to existing scripts.

### #30: DOCUMENTATION STANDARDS
All docs must be:
- **Factual only** — what it does, inputs, outputs, constraints
- **No filler** — forbidden: "This script is designed to...", "In order to...", "It is worth noting..."
- **Minimal prose** — prefer tables and code blocks over paragraphs
- **Diagrams over words** — ASCII diagrams for architecture and data flow

FORBIDDEN in any doc: introductory paragraphs, closing summaries, benefit statements, "robust", "seamless", "comprehensive", "leverages", "state-of-the-art".

### #31: NO NEW DOC FILES
Do not create new `.md` files. Add content to the nearest existing doc. If no existing doc fits, ask the user which file to update.

## STYLE
Brief, technical, terse. No fluff, no pleasantries. Prioritize correctness.

## PROJECT STRUCTURE

```
pagemenot/
├── pagemenot/          # Core package
│   ├── config.py       # Settings (Pydantic)
│   ├── crew.py         # CrewAI crew definition
│   ├── main.py         # Entrypoint
│   ├── mock_tools.py   # Mock tools for testing
│   ├── slack_bot.py    # Slack Bolt integration
│   ├── tools.py        # CrewAI tools
│   ├── triage.py       # Incident triage logic
│   └── knowledge/
│       └── rag.py      # RAG over runbooks/postmortems
├── knowledge/
│   ├── runbooks/       # Operational runbooks
│   └── postmortems/    # Incident postmortems
├── scripts/
│   └── simulate_incident.py
├── docs/
│   └── deployment.md
├── deploy/             # Terraform + userdata
├── Dockerfile
└── docker-compose.yml
```

## KEY FILES

| File | Purpose |
|------|---------|
| `pagemenot/config.py` | All config via Pydantic Settings / .env |
| `pagemenot/crew.py` | CrewAI crew and agent definitions |
| `pagemenot/triage.py` | Incident triage and routing logic |
| `pagemenot/slack_bot.py` | Slack Bolt app and event handlers |
| `pagemenot/tools.py` | Tools available to CrewAI agents |
| `pagemenot/knowledge/rag.py` | RAG retrieval over knowledge base |
| `knowledge/runbooks/` | Runbooks indexed by RAG |
| `knowledge/postmortems/` | Postmortems indexed by RAG |

---
**Last Updated**: 2026-02-26
