"""
Knowledge ingestion — auto-loads postmortems and runbooks into ChromaDB.

Teams just drop markdown files into provider subdirectories:
  ./knowledge/runbooks/gcp/
  ./knowledge/runbooks/aws/
  ./knowledge/runbooks/k8s/
  ./knowledge/runbooks/onprem/
  ./knowledge/runbooks/hetzner/
  ./knowledge/runbooks/azure/
  ./knowledge/runbooks/generic/
  ./knowledge/postmortems/

Pagemenot ingests them on startup. No commands, no config.
"""

import datetime
import logging
import os
import re
import subprocess
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

# Known providers — controls boolean flag metadata keys stored in ChromaDB
_KNOWN_PROVIDERS = {"gcp", "aws", "k8s", "azure", "onprem", "hetzner", "generic"}

# Tag sets for auto-detection from runbook frontmatter
_GCP_TAGS = {
    "gcp",
    "gce",
    "cloud-run",
    "cloud_run",
    "cloud-sql",
    "cloud_sql",
    "google",
    "google-cloud",
}
_AWS_TAGS = {"aws", "ec2", "ecs", "lambda", "rds", "s3", "cloudwatch", "amazon"}
_K8S_TAGS = {"kubernetes", "k8s", "kubectl", "gke", "eks", "aks"}
_AZURE_TAGS = {"azure", "az", "aks", "blob", "cosmosdb", "app-service", "azure-vm"}
_HETZNER_TAGS = {"hetzner", "hetzner-cloud", "htz"}
_ONPREM_TAGS = {"onprem", "on-prem", "on_prem", "bare-metal", "baremetal"}


def sync_from_bucket() -> None:
    """Sync runbooks from PAGEMENOT_RUNBOOK_BUCKET to RUNBOOKS_DIR before ingest.

    Supports:
      gs://bucket/path        — gsutil rsync
      s3://bucket/path        — aws s3 sync
      az://account/container  — azcopy sync (requires azcopy in PATH or AZCOPY_AUTO_LOGIN=true)
    """
    bucket = settings.pagemenot_runbook_bucket
    if not bucket:
        return

    RUNBOOKS_DIR.mkdir(parents=True, exist_ok=True)

    if bucket.startswith("gs://"):
        cmd = ["gsutil", "-m", "rsync", "-r", "-d", bucket, str(RUNBOOKS_DIR)]
    elif bucket.startswith("s3://"):
        cmd = ["aws", "s3", "sync", "--delete", bucket, str(RUNBOOKS_DIR)]
    elif bucket.startswith("az://"):
        parts = bucket[5:].split("/", 1)
        account = parts[0]
        container = parts[1] if len(parts) > 1 else ""
        az_url = f"https://{account}.blob.core.windows.net/{container}"
        cmd = ["azcopy", "sync", az_url, str(RUNBOOKS_DIR), "--delete-destination=true"]
    else:
        logger.warning("PAGEMENOT_RUNBOOK_BUCKET: unsupported scheme %r — skipped", bucket)
        return

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning("Runbook bucket sync failed: %s", (result.stderr or result.stdout)[:300])
        else:
            logger.info("Runbooks synced from %s", bucket)
    except FileNotFoundError as e:
        logger.warning("Runbook bucket sync failed — CLI not found: %s", e)
    except subprocess.TimeoutExpired:
        logger.warning("Runbook bucket sync timed out after 120s")


def ingest_all():
    """Auto-ingest all knowledge on startup. Called from main.py."""
    try:
        sync_from_bucket()
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
    """Ingest all markdown files from directory tree into a ChromaDB collection."""
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

        title = f.stem.replace("-", " ").replace("_", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        tags_str = _extract_field(content, "tags") or ""
        # Directory name provides authoritative provider hint (e.g. runbooks/gcp/)
        dir_hint = f.parent.name if f.parent != directory else ""
        providers = _detect_cloud_providers(tags_str, content, dir_hint)
        provider_flags = _provider_flags(providers)

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
            # Human-readable list (comma-separated) — for display/debug
            "cloud_providers": ",".join(providers),
            # Legacy field — primary provider, for backward compat
            "cloud_provider": providers[0] if providers else "generic",
            **provider_flags,
        }

        chunks = _chunk_document(content, max_chars=1500)
        for i, chunk in enumerate(chunks):
            docs.append(chunk)
            ids.append(f"{doc_id}_chunk{i}")
            metadatas.append(meta)

    if docs:
        collection.upsert(documents=docs, ids=ids, metadatas=metadatas)
        logger.info(
            f"Ingested {len(md_files)} {doc_type}s ({len(docs)} chunks) into '{collection_name}'"
        )


def index_incident(
    content: str, filename: str, service: str, cloud_providers: list[str] | None = None
) -> None:
    """Index a single postmortem into ChromaDB incidents collection."""
    try:
        providers = cloud_providers or ["generic"]
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
            "cloud_providers": ",".join(providers),
            "cloud_provider": providers[0],
            **_provider_flags(providers),
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
    """Write a postmortem for any resolved incident and index into ChromaDB."""
    service = result.service or "unknown"
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{service}_{ts}-{uuid.uuid4().hex[:6]}.md"

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
        providers = getattr(result, "cloud_provider", ["generic"])
        if isinstance(providers, str):
            providers = [providers] if providers else ["generic"]
        index_incident(content, filename, service, cloud_providers=providers)
    except Exception as e:
        logger.warning(f"Postmortem write/index failed: {e}")


def _detect_cloud_providers(tags_str: str, content: str, dir_hint: str = "") -> list[str]:
    """Return all detected cloud providers for a document. Always includes at least ['generic']."""
    detected: set[str] = set()

    # Directory name is authoritative — runbooks/gcp/ → gcp
    if dir_hint in _KNOWN_PROVIDERS and dir_hint != "generic":
        detected.add(dir_hint)

    tags = {t.strip().lower() for t in tags_str.split(",") if t.strip()}
    if tags & _GCP_TAGS:
        detected.add("gcp")
    if tags & _AWS_TAGS:
        detected.add("aws")
    if tags & _K8S_TAGS:
        detected.add("k8s")
    if tags & _AZURE_TAGS:
        detected.add("azure")
    if tags & _HETZNER_TAGS:
        detected.add("hetzner")
    if tags & _ONPREM_TAGS:
        detected.add("onprem")

    # User-configured aliases
    aliases = settings.pagemenot_cloud_provider_aliases
    for tag in tags:
        if tag in aliases:
            detected.add(aliases[tag])

    # Content scan — always runs (not gated on empty tags)
    if "gcloud " in content:
        detected.add("gcp")
    if re.search(r"\baws ", content):
        detected.add("aws")
    if "kubectl " in content:
        detected.add("k8s")
    if re.search(r"\baz ", content):
        detected.add("azure")

    return sorted(detected) if detected else ["generic"]


def _detect_cloud_provider(tags_str: str, content: str) -> str:
    """Single-value wrapper around _detect_cloud_providers for backward-compat tests."""
    return _detect_cloud_providers(tags_str, content)[0]


def _provider_flags(providers: list[str]) -> dict[str, int]:
    """Return boolean int flags for each known provider, for ChromaDB $or queries."""
    flags: dict[str, int] = {f"is_{p}": 0 for p in _KNOWN_PROVIDERS}
    for p in providers:
        key = f"is_{p}"
        if key in flags:
            flags[key] = 1
    # Generic runbooks match all queries
    if not providers or providers == ["generic"]:
        flags["is_generic"] = 1
    return flags


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
