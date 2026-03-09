"""
Knowledge ingestion — auto-loads postmortems and runbooks into ChromaDB.

Teams just drop markdown files into:
  ./knowledge/postmortems/
  ./knowledge/runbooks/

Pagemenot ingests them on startup. No commands, no config.
"""

import datetime
import logging
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import chromadb

from pagemenot.config import settings

if TYPE_CHECKING:
    from pagemenot.triage import TriageResult

logger = logging.getLogger("pagemenot.rag")

_REPO_ROOT = Path(__file__).parent.parent
_KNOWLEDGE_BASE = Path(os.environ.get("KNOWLEDGE_DIR", str(_REPO_ROOT / "knowledge")))
POSTMORTEMS_DIR = _KNOWLEDGE_BASE / "postmortems"
RUNBOOKS_DIR = _KNOWLEDGE_BASE / "runbooks"


def ingest_all():
    """Auto-ingest all knowledge on startup. Called from main.py."""
    try:
        os.makedirs(settings.chroma_path, exist_ok=True)
        client = chromadb.PersistentClient(path=settings.chroma_path)

        _ingest_directory(
            client, POSTMORTEMS_DIR, settings.chroma_incidents_collection, "postmortem"
        )
        _ingest_directory(client, RUNBOOKS_DIR, settings.chroma_runbooks_collection, "runbook")

    except Exception as e:
        logger.warning(f"Knowledge ingestion failed (non-fatal): {e}")
        logger.info("Pagemenot works without knowledge — it learns as you use it.")


def _ingest_directory(
    client: chromadb.PersistentClient,
    directory: Path,
    collection_name: str,
    doc_type: str,
):
    """Ingest all markdown files from a directory into a ChromaDB collection."""
    if not directory.exists():
        logger.info(f"No {doc_type}s directory at {directory}. Skipping.")
        return

    md_files = list(directory.glob("**/*.md"))
    if not md_files:
        logger.info(f"No {doc_type}s found in {directory}.")
        return

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    docs = []
    ids = []
    metadatas = []

    for f in md_files:
        content = f.read_text(encoding="utf-8")
        doc_id = f"{doc_type}_{f.stem}"

        # Extract title from first heading or filename
        title = f.stem.replace("-", " ").replace("_", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        # Extract metadata from frontmatter-style headers
        tags_str = _extract_field(content, "tags") or ""
        meta = {
            "type": doc_type,
            "title": title,
            "filename": f.name,
            "service": _extract_field(content, "service") or "general",
            "root_cause": _extract_field(content, "root_cause")
            or _extract_field(content, "root cause")
            or "",
            "resolution": _extract_field(content, "resolution") or "",
            "date": _extract_field(content, "date") or "",
            "cloud_provider": _detect_cloud_provider(tags_str, content),
        }

        # Chunk long documents (ChromaDB has limits)
        chunks = _chunk_document(content, max_chars=1500)
        for i, chunk in enumerate(chunks):
            docs.append(chunk)
            ids.append(f"{doc_id}_chunk{i}")
            metadatas.append(meta)

    if docs:
        # Upsert (idempotent — safe to re-run)
        collection.upsert(documents=docs, ids=ids, metadatas=metadatas)
        logger.info(
            f"Ingested {len(md_files)} {doc_type}s ({len(docs)} chunks) into '{collection_name}'"
        )


def index_incident(
    content: str, filename: str, service: str, cloud_provider: str = "generic"
) -> None:
    """Index a single postmortem into ChromaDB incidents collection. Called after human-approved resolution."""
    try:
        client = chromadb.PersistentClient(path=settings.chroma_path)
        collection = client.get_or_create_collection(
            name=settings.chroma_incidents_collection,
            metadata={"hnsw:space": "cosine"},
        )
        stem = Path(filename).stem
        title = stem.replace("-", " ").replace("_", " ").title()
        meta = {
            "type": "postmortem",
            "title": title,
            "filename": filename,
            "service": service,
            "root_cause": _extract_field(content, "root_cause") or "",
            "resolution": _extract_field(content, "resolution") or "",
            "date": _extract_field(content, "date") or "",
            "cloud_provider": cloud_provider,
        }
        chunks = _chunk_document(content)
        doc_id = f"postmortem_{stem}"
        collection.upsert(
            documents=chunks,
            ids=[f"{doc_id}_chunk{i}" for i in range(len(chunks))],
            metadatas=[meta] * len(chunks),
        )
        logger.info(f"Indexed postmortem: {filename} ({len(chunks)} chunks)")
    except Exception as e:
        logger.warning(f"Postmortem indexing failed: {e}")


def write_and_index_postmortem(
    result: "TriageResult",
    resolved_by: str = "agent",
    jira_url: str = "",
) -> None:
    """Write a postmortem for any resolved incident (auto or human-approved) and index into ChromaDB."""
    service = result.service or "unknown"
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{service}_{ts}-{uuid.uuid4().hex[:6]}.md"

    # Resolve template vars in execution log before persisting
    resolved_log = [
        re.sub(
            r"\{\{\s*service\s*\}\}",
            service,
            re.sub(r"\{\{\s*namespace\s*\}\}", settings.pagemenot_exec_namespace, entry),
        )
        for entry in (result.execution_log or [])
    ]
    log_md = "\n\n".join(resolved_log) or "No steps logged."

    root_cause = (result.root_cause or "").strip()
    if not root_cause or root_cause == "See detailed analysis below.":
        root_cause = "Not determined."

    resolution = (
        "Human-approved runbook execution"
        if resolved_by != "agent"
        else "Auto-resolved by runbook execution"
    )

    content = (
        f"# Postmortem: {result.alert_title}\n\n"
        f"service: {service}\n"
        f"date: {datetime.date.today()}\n"
        f"root_cause: {root_cause}\n"
        f"resolution: {resolution}\n\n"
        f"## Alert\n{result.alert_title}\n\n"
        f"## Root Cause\n{root_cause}\n\n"
        f"## Execution Log\n{log_md}\n\n"
        f"## Resolved By\n{resolved_by}\n" + (f"\n## Jira\n{jira_url}\n" if jira_url else "")
    )

    path = POSTMORTEMS_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
        logger.info(f"Postmortem written: {filename}")
        index_incident(
            content,
            filename,
            service,
            cloud_provider=getattr(result, "cloud_provider", "generic"),
        )
    except Exception as e:
        logger.warning(f"Postmortem write/index failed: {e}")


_GCP_TAGS = {"gcp", "gce", "cloud-run", "cloud_run", "cloud-sql", "cloud_sql"}
_AWS_TAGS = {"aws", "ec2", "ecs", "lambda", "rds", "s3", "cloudwatch"}
_K8S_TAGS = {"kubernetes", "k8s", "kubectl"}
_HETZNER_TAGS = {"hetzner", "htz"}
_ONPREM_TAGS = {"onprem", "on-prem", "on_prem", "bare-metal", "baremetal"}


def _detect_cloud_provider(tags_str: str, content: str) -> str:
    tags = {t.strip().lower() for t in tags_str.split(",") if t.strip()}
    if tags & _GCP_TAGS:
        return "gcp"
    if tags & _AWS_TAGS:
        return "aws"
    if tags & _K8S_TAGS:
        return "k8s"
    if tags & _HETZNER_TAGS:
        return "hetzner"
    if tags & _ONPREM_TAGS:
        return "onprem"
    # User-configured aliases — keeps ingest in sync with alert normalization
    aliases = settings.pagemenot_cloud_provider_aliases
    for tag in tags:
        if tag in aliases:
            return aliases[tag]
    # Content fallback only for untagged docs (tags field absent or empty)
    if not tags:
        if "gcloud " in content:
            return "gcp"
        if re.search(r"\baws ", content):
            return "aws"
        if "kubectl " in content:
            return "k8s"
    return "generic"


def _extract_field(content: str, field: str) -> str | None:
    """Extract a field value from markdown-ish content."""
    for line in content.split("\n")[:20]:
        lower = line.lower().strip()
        if lower.startswith(f"{field}:") or lower.startswith(f"**{field}**:"):
            return line.split(":", 1)[1].strip().strip("*")
    return None


def _chunk_document(text: str, max_chars: int = 1500) -> list[str]:
    """Split a document into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""
    for para in text.split("\n\n"):
        if len(current) + len(para) > max_chars:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current += "\n\n" + para

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text[:max_chars]]
