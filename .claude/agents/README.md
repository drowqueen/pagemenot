# Claude Code Agents

**Location:** `.claude/agents/`

---

## Agent Inventory

| Agent | File | Delegate When |
|-------|------|---------------|
| 📚 Documentation | `documentation-agent.md` | Creating/updating/cleaning docs |
| 📜 Script | `script-agent.md` | Create/update scripts (searches first) |

---

## Execution Rules (CRITICAL)

### 1. PARALLEL - Never Sequential
```python
# GOOD: Launch multiple agents simultaneously
Task(agent="documentation", run_in_background=True, prompt="Update runbook")
Task(agent="script", run_in_background=True, prompt="Update simulator")

# BAD: Sequential blocking
result1 = Task(agent="documentation", prompt="Update runbook")  # blocks
result2 = Task(agent="script", prompt="Update simulator")  # waits
```

### 2. DETACHED - Screen Sessions
```bash
screen -dmS job_name bash -c "PYTHONUNBUFFERED=1 python scripts/name.py > logs/name_$(date +%Y%m%d_%H%M%S).log 2>&1"
echo "Started: job_name | Log: logs/name_*.log | Attach: screen -r job_name"
```

### 3. NON-BLOCKING - Return Immediately
- Report screen session name
- Report log file path
- Move on — never wait
