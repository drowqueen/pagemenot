# Claude Code Instructions for pagemenot

## CRITICAL RULES

### #0: SYSTEMATIC RULE ENFORCEMENT
State which rules apply BEFORE any task. If violated: STOP, fix, add validation.

| Task | Rules |
|------|-------|
| Git | #24, #24.5, #26 |
| New code | #29 |
| Any docs/README | #30 |
| Long jobs | #7, #0.95 |
| Agents | #25 |

### #0.95: NEVER BLOCK THE TERMINAL — ZERO EXCEPTIONS
FORBIDDEN in any shape or form:
- `sleep N`, polling loops, `tail -f`, `watch`, waiting for output
- Blocking Bash calls for anything that takes more than 2 seconds

REQUIRED: Every long-running command (builds, deploys, docker compose, ssh remote commands, test runs) MUST run in a detached screen session:
`screen -dmS <name> bash -c "<command> > /tmp/<name>.log 2>&1"`
Report the screen name + log path, move on immediately. Never use `run_in_background` for long jobs — screen survives terminal crashes.

### #5: CREDENTIALS
`.env` only. Never in code. Never hardcode API keys, tokens, or secrets.

### #7: SCREEN FOR LONG JOBS
`screen -dmS <name> bash -c "PYTHONUNBUFFERED=1 python script.py > logs/... 2>&1"`

### #11: NO FLUFF — EVERYWHERE
Applies to: code, responses, docs, commit messages, PR titles/bodies, CHANGELOG, README.

**Code:** No defensive comments, no explanatory prints unless they carry data. No dead code, no commented-out blocks.
**Responses:** No preamble, no summaries restating what was just done, no sign-offs. Lead with the result.
**Docs / README / CHANGELOG:** Facts only — what changed, what it does, inputs, outputs. No motivation paragraphs, no benefit statements, no closing summaries.
**Commit messages:** `<type>: <what changed>` — one line, imperative, specific. No "This commit...", no "In order to...", no explaining why unless non-obvious.
**PR descriptions:** bullet facts only — what changed and why (if non-obvious). No intro paragraph, no "This PR adds...", no sign-off.

FORBIDDEN everywhere: "robust", "seamless", "leverages", "powerful", "comprehensive", "state-of-the-art", "it's worth noting", "This is designed to", "In order to", "ensure that".

### #24: COMMIT DISCIPLINE
NEVER commit without explicit user command. NEVER commit credentials or secrets.

### #24.5: BRANCH AND PR WORKFLOW
NEVER commit or work directly on local `main` or `develop`. ALWAYS create a local feature branch first.
Branch naming: `feature/<name>`, `fix/<name>`, `chore/<name>`.
Every change must go through a PR. No exceptions.
Violation of this rule is a hard stop — abort, create the branch, move the work there.

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
- Factual only — what it does, inputs, outputs, constraints
- Prefer tables and code blocks over paragraphs
- ASCII diagrams for architecture and data flow
- See #11 for full forbidden word/phrase list.

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
