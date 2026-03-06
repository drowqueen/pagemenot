"""
Pagemenot Crew — auto-configures agents with real OR mock tools.

The crew module imports tools from mock_tools.get_available_tools()
which auto-detects: real integration configured? Use it. Not configured?
Use the mock. Teams never see the difference in the agent config.
"""

from crewai import Agent, Task, Crew, Process, LLM
from pagemenot.config import settings
from pagemenot.mock_tools import get_available_tools

import logging

logger = logging.getLogger("pagemenot.crew")


def _build_llm() -> LLM:
    if settings.llm_provider == "ollama":
        return LLM(model=f"ollama/{settings.llm_model}", base_url=settings.ollama_url)
    elif settings.llm_provider == "anthropic":
        return LLM(model=f"anthropic/{settings.llm_model}", api_key=settings.anthropic_api_key)
    elif settings.llm_provider == "gemini":
        return LLM(model=f"gemini/{settings.llm_model}", api_key=settings.gemini_api_key)
    else:
        return LLM(model=f"openai/{settings.llm_model}", api_key=settings.openai_api_key)


def build_triage_crew(alert_summary: str) -> Crew:
    """Build a complete triage crew for a specific incident and return it ready to kickoff."""
    llm = _build_llm()
    available = get_available_tools()
    _verbose = logger.isEnabledFor(logging.DEBUG)

    monitor = Agent(
        role="Senior SRE Monitoring Specialist",
        goal=(
            "Rapidly gather all observability data for the reported incident. "
            "Pull metrics, logs, alert details. Focus on the time window around the incident. "
            "Summarize findings clearly with specific numbers."
        ),
        backstory=(
            "You are a veteran SRE with 15 years of experience. You know exactly which "
            "metrics, logs, and signals matter. You work fast because every minute of "
            "downtime costs money. Use ALL your available tools to build a complete picture."
        ),
        tools=available["monitor"],
        llm=llm,
        verbose=_verbose,
        max_iter=10,
        allow_delegation=False,
    )

    diagnoser = Agent(
        role="Principal Incident Analyst",
        goal=(
            "Correlate monitoring data with recent changes to identify root cause. "
            "Check deploys, code changes, past incidents. Provide a specific root cause "
            "with confidence level and supporting evidence."
        ),
        backstory=(
            "You are a staff-level SRE known for finding root causes others miss. "
            "You think in correlations: what changed right before symptoms appeared? "
            "Always check deploy history and search for similar past incidents. "
            "Your diagnoses are specific, never vague."
        ),
        tools=available["diagnoser"],
        llm=llm,
        verbose=_verbose,
        max_iter=10,
        allow_delegation=False,
    )

    remediator = Agent(
        role="SRE Remediation Specialist",
        goal=(
            "Propose safe, prioritized remediation steps based on the diagnosis. "
            "Search runbooks for established procedures. For destructive actions "
            "(rollbacks, restarts), ALWAYS flag as NEEDS HUMAN APPROVAL. "
            "Draft a brief postmortem summary."
        ),
        backstory=(
            "You are a cautious, methodical SRE. You never execute destructive actions "
            "without human approval. You prioritize the fastest safe fix first and always "
            "check for existing runbooks. You think about blast radius."
        ),
        tools=available["remediator"],
        llm=llm,
        verbose=_verbose,
        max_iter=8,
        allow_delegation=False,
    )

    FORMAT_RULES = (
        "OUTPUT RULES — MUST FOLLOW:\n"
        "- No prose, no paragraphs, no explanations, no summaries.\n"
        "- Use `inline code` for commands. NEVER use ``` code fences.\n"
        "- Bullet points and labeled fields only.\n"
        "- No phrases like 'By following these steps', 'In order to', 'It is worth noting'.\n"
    )

    monitor_task = Task(
        description=(
            f"Incident:\n\n{alert_summary}\n\n"
            f"Gather using all available tools:\n"
            f"- Current metrics (error rate, latency, CPU, memory, pod restarts)\n"
            f"- Recent logs (errors, stack traces, warnings)\n"
            f"- Any anomalies in the 30-min window before the alert\n"
            f"Skip failed tools, note which couldn't be checked.\n\n"
            f"{FORMAT_RULES}"
        ),
        expected_output=(
            "Metrics: error_rate=X%, latency_p99=Xms, cpu=X%, memory=XMB, restarts=N\n"
            "Logs: [timestamp] LEVEL message (top 3 relevant lines)\n"
            "Anomalies: [what changed just before the incident, or 'none detected']\n"
            "Unavailable: [tools that failed, or 'all tools available']"
        ),
        agent=monitor,
    )

    diagnose_task = Task(
        description=(
            "Using monitoring data, identify root cause:\n"
            "- Search past incidents FIRST — if a matching postmortem exists, cite it and set confidence: high\n"
            "- Check recent deploys and code changes for correlation\n"
            "- Be SPECIFIC: name the deploy, PR, config change, or code path\n"
            "- Confidence rules: high = past incident match OR clear single cause; "
            "medium = probable cause with some ambiguity; low = multiple possible causes\n"
            "- Output confidence as exactly one word on its own line: 'Confidence: high' OR "
            "'Confidence: medium' OR 'Confidence: low'\n\n"
            f"{FORMAT_RULES}"
        ),
        expected_output=(
            "Root cause: [one specific sentence — name the deploy/change/code path]\n"
            "Confidence: high\n"
            "Evidence:\n"
            "- [data point 1]\n"
            "- [data point 2]\n"
            "Similar incidents: [postmortem filename or 'none found']\n"
            "What changed: [deploy/config/traffic spike, with timestamp]"
        ),
        agent=diagnoser,
        context=[monitor_task],
    )

    remediate_task = Task(
        description=(
            "Propose remediation based on the diagnosis:\n"
            "- Search runbooks for existing procedures\n"
            "- List steps in order, safest first\n"
            "- Tag every step [AUTO-SAFE] or [NEEDS APPROVAL]\n"
            "- [NEEDS APPROVAL] = destructive/irreversible (rollback, restart, delete, scale-down)\n"
            "- Draft 3-sentence postmortem\n\n"
            f"{FORMAT_RULES}"
        ),
        expected_output=(
            "Remediation:\n"
            "1. [AUTO-SAFE] `command` — what it checks/fixes\n"
            "2. [NEEDS APPROVAL] `command` — why approval needed\n"
            "3. [AUTO-SAFE] `command` — verification step\n\n"
            "Postmortem: [sentence 1: what happened]. [sentence 2: root cause]. [sentence 3: fix applied]."
        ),
        agent=remediator,
        context=[monitor_task, diagnose_task],
    )

    # Configure memory embedder per provider.
    # Grok/Ollama have no embedding API — memory disabled for those.
    embedder_config = None
    if settings.llm_provider == "openai" and settings.openai_api_key:
        embedder_config = {
            "provider": "openai",
            "config": {"model": "text-embedding-3-small", "api_key": settings.openai_api_key},
        }
    elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        # Anthropic has no embedding API — fall back to OpenAI if key available, else skip
        if settings.openai_api_key:
            embedder_config = {
                "provider": "openai",
                "config": {"model": "text-embedding-3-small", "api_key": settings.openai_api_key},
            }
    # gemini/ollama: no ChromaDB-compatible embedding API — memory stays disabled

    memory_enabled = embedder_config is not None

    crew_kwargs: dict = {
        "agents": [monitor, diagnoser, remediator],
        "tasks": [monitor_task, diagnose_task, remediate_task],
        "process": Process.sequential,
        "verbose": _verbose,
        "memory": memory_enabled,
    }
    if embedder_config:
        crew_kwargs["embedder"] = embedder_config

    return Crew(**crew_kwargs)
