"""
Knowledge ingestion — auto-loads postmortems and runbooks into ChromaDB.

Teams just drop markdown files into:
  ./knowledge/postmortems/
  ./knowledge/runbooks/

Pagemenot ingests them on startup. No commands, no config.
"""

import logging
import os
from pathlib import Path

import chromadb

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.knowledge")

_REPO_ROOT = Path(__file__).parent.parent.parent
_KNOWLEDGE_BASE = Path(os.environ.get("KNOWLEDGE_DIR", str(_REPO_ROOT / "knowledge")))
POSTMORTEMS_DIR = _KNOWLEDGE_BASE / "postmortems"
RUNBOOKS_DIR = _KNOWLEDGE_BASE / "runbooks"


def _chroma_client():
    """Return a ChromaDB client — HTTP (remote) if CHROMA_HOST is set, PersistentClient otherwise."""
    if settings.chroma_host:
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    os.makedirs(settings.chroma_path, exist_ok=True)
    return chromadb.PersistentClient(path=settings.chroma_path)


def ingest_all():
    """Auto-ingest all knowledge on startup. Called from main.py."""
    try:
        client = _chroma_client()

        _ingest_directory(client, POSTMORTEMS_DIR, "incidents", "postmortem")
        _ingest_directory(client, RUNBOOKS_DIR, "runbooks", "runbook")

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
        meta = {
            "type": doc_type,
            "title": title,
            "filename": f.name,
            "service": _extract_field(content, "service") or "general",
            "root_cause": _extract_field(content, "root_cause") or _extract_field(content, "root cause") or "",
            "resolution": _extract_field(content, "resolution") or "",
            "date": _extract_field(content, "date") or "",
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
        logger.info(f"Ingested {len(md_files)} {doc_type}s ({len(docs)} chunks) into '{collection_name}'")


def add_postmortem(filepath: Path) -> None:
    """Incrementally index a single postmortem file into ChromaDB. Non-blocking on error."""
    try:
        client = _chroma_client()
        collection = client.get_or_create_collection(
            name="incidents",
            metadata={"hnsw:space": "cosine"},
        )
        content = filepath.read_text(encoding="utf-8")
        doc_id = f"postmortem_{filepath.stem}"

        title = filepath.stem.replace("-", " ").replace("_", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        meta = {
            "type": "postmortem",
            "title": title,
            "filename": filepath.name,
            "service": _extract_field(content, "service") or "general",
            "root_cause": _extract_field(content, "root_cause") or _extract_field(content, "root cause") or "",
            "resolution": _extract_field(content, "resolution") or "",
            "date": _extract_field(content, "date") or "",
        }

        chunks = _chunk_document(content, max_chars=1500)
        collection.upsert(
            documents=chunks,
            ids=[f"{doc_id}_chunk{i}" for i in range(len(chunks))],
            metadatas=[meta] * len(chunks),
        )
        logger.info(f"Indexed postmortem: {filepath.name} ({len(chunks)} chunks)")
    except Exception as e:
        logger.warning(f"Failed to index postmortem {filepath.name}: {e}")


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
