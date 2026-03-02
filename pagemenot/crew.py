"""
Pagemenot Crew — auto-configures agents with real OR mock tools.

The crew module imports tools from mock_tools.get_available_tools()
which auto-detects: real integration configured? Use it. Not configured?
Use the mock. Teams never see the difference in the agent config.
"""

from typing import Literal

from crewai import Agent, Task, Crew, Process, LLM
from pydantic import BaseModel, Field
from pagemenot.config import settings
from pagemenot.mock_tools import get_available_tools

import logging

logger = logging.getLogger("pagemenot.crew")


class TriageOutput(BaseModel):
    root_cause: str = Field(description="Specific root cause of the incident.")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence in the root cause.")
    evidence: list[str] = Field(default=[], description="Key evidence supporting the root cause.")
    remediation_steps: list[str] = Field(default=[], description="Ordered fix steps, each prefixed [AUTO-SAFE] or [NEEDS APPROVAL].")
    postmortem_summary: str = Field(default="", description="3-sentence postmortem summary.")


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

    monitor_task = Task(
        description=(
            f"An incident has been reported:\n\n{alert_summary}\n\n"
            f"Use ALL your monitoring tools to gather:\n"
            f"1. Current metrics (error rates, latency, CPU, memory)\n"
            f"2. Recent log entries with errors/warnings\n"
            f"3. Alert details and severity\n"
            f"4. Anomalies in the 30-minute window before the incident\n\n"
            f"If a tool fails, skip it and note what you couldn't check."
        ),
        expected_output=(
            "A structured monitoring report with:\n"
            "- Metrics summary (what's normal vs anomalous, with numbers)\n"
            "- Key log entries (errors, stack traces)\n"
            "- Alert context\n"
            "- Pre-incident anomalies"
        ),
        agent=monitor,
    )

    diagnose_task = Task(
        description=(
            "Using the monitoring data above, identify the root cause:\n"
            "1. Check for recent deployments or code changes that correlate\n"
            "2. Search past incidents for similar patterns\n"
            "3. Correlate metrics with changes\n"
            "4. Form a specific root cause hypothesis\n\n"
            "Be SPECIFIC. Not 'something is wrong' but 'Deploy #4521 introduced "
            "a KeyError in the Stripe webhook handler'."
        ),
        expected_output=(
            "Root cause analysis with:\n"
            "- Root cause (specific and actionable)\n"
            "- Confidence level: high / medium / low\n"
            "- Evidence (what data supports this)\n"
            "- Similar past incidents (if found)\n"
            "- What changed (deploy, config, traffic)"
        ),
        agent=diagnoser,
        context=[monitor_task],
    )

    remediate_task = Task(
        description=(
            "Based on the diagnosis, produce a structured remediation plan:\n"
            "1. Extract the root_cause and confidence level (high/medium/low) from the diagnoser's output\n"
            "2. Search runbooks for established procedures\n"
            "3. List ordered fix steps (safest/fastest first), each prefixed [AUTO-SAFE] or [NEEDS APPROVAL]\n"
            "4. Summarize key evidence from the monitoring and diagnosis\n"
            "5. Draft a 3-sentence postmortem summary\n\n"
            "NEVER recommend destructive actions without [NEEDS APPROVAL] prefix.\n"
            "If root cause cannot be determined, set confidence to 'low'."
        ),
        expected_output="JSON object matching the TriageOutput schema.",
        output_json=TriageOutput,
        agent=remediator,
        context=[monitor_task, diagnose_task],
    )

    # Configure memory embedder per provider.
    embedder_config = None
    if settings.llm_provider == "ollama" and settings.ollama_embedding_model:
        embedder_config = {
            "provider": "ollama",
            "config": {
                "model_name": settings.ollama_embedding_model,
                "url": f"{settings.ollama_url}/api/embeddings",
            },
        }
    elif settings.llm_provider == "openai" and settings.openai_api_key:
        embedder_config = {
            "provider": "openai",
            "config": {"model": "text-embedding-3-small", "api_key": settings.openai_api_key},
        }
    elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        # Anthropic has no embedding API — use OpenAI embeddings if key available
        if settings.openai_api_key:
            embedder_config = {
                "provider": "openai",
                "config": {"model": "text-embedding-3-small", "api_key": settings.openai_api_key},
            }
    # gemini: no ChromaDB-compatible embedding API — memory stays disabled

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
