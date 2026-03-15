"""Tests for cloud provider filtering in RAG retrieval."""

import pathlib
import tempfile
from pathlib import Path

from pagemenot.rag import _detect_cloud_provider, _ingest_directory


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


class TestDetectCloudProvider:
    def test_gcp_tag(self):
        assert _detect_cloud_provider("gcp, gce, nginx", "") == "gcp"

    def test_aws_ecs_tag(self):
        assert _detect_cloud_provider("ecs, container, aws", "") == "aws"

    def test_aws_ec2_tag(self):
        assert _detect_cloud_provider("ec2, nginx", "") == "aws"

    def test_aws_lambda_tag(self):
        assert _detect_cloud_provider("lambda, errors", "") == "aws"

    def test_k8s_content_fallback(self):
        assert _detect_cloud_provider("", "kubectl get pods") == "k8s"

    def test_generic_no_signals(self):
        assert _detect_cloud_provider("", "check connection pool") == "generic"


def test_provider_detection():
    """Alias used by automated command in plan."""
    assert _detect_cloud_provider("gcp, gce, nginx", "") == "gcp"
    assert _detect_cloud_provider("ecs, container, aws", "") == "aws"
    assert _detect_cloud_provider("ec2, nginx", "") == "aws"
    assert _detect_cloud_provider("lambda, errors", "") == "aws"
    assert _detect_cloud_provider("", "kubectl get pods") == "k8s"
    assert _detect_cloud_provider("", "check connection pool") == "generic"


# ---------------------------------------------------------------------------
# Ingest stores cloud_provider in metadata
# ---------------------------------------------------------------------------


def _make_runbook(tmp: Path, name: str, tags: str) -> None:
    content = (
        f"# {name}\n\nservice: general\ntags: {tags}\ndate: 2026-01-01\n\n## Steps\nDo the thing.\n"
    )
    (tmp / f"{name}.md").write_text(content)


def test_runbook_ingest_tags(chroma_client):
    collection = chroma_client.get_or_create_collection(
        "test_ingest", metadata={"hnsw:space": "cosine"}
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _make_runbook(tmp, "gce-test", "gcp, gce")
        _make_runbook(tmp, "ec2-test", "ec2, aws")
        _make_runbook(tmp, "generic-test", "database, connections")
        _ingest_directory(chroma_client, tmp, "test_ingest", "runbook")
        results = collection.get(include=["metadatas"])
        providers = {m.get("cloud_provider") for m in results["metadatas"]}
        assert "gcp" in providers
        assert "aws" in providers
        assert "generic" in providers


# ---------------------------------------------------------------------------
# Query-time filtering
# ---------------------------------------------------------------------------


def _ingest_two(chroma_client, collection_name: str, gcp_tags: str, aws_tags: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _make_runbook(tmp, "gcp-runbook", gcp_tags)
        _make_runbook(tmp, "aws-runbook", aws_tags)
        _ingest_directory(chroma_client, tmp, collection_name, "runbook")


def test_search_filters_by_provider(chroma_client):
    _ingest_two(chroma_client, "test_filter", "gcp, gce", "ec2, aws")
    collection = chroma_client.get_collection("test_filter")
    results = collection.query(
        query_texts=["nginx stopped"],
        n_results=10,
        where={"cloud_provider": {"$in": ["gcp", "generic"]}},
    )
    filenames = [m.get("filename", "") for m in results["metadatas"][0]]
    assert any("gcp-runbook" in f for f in filenames)
    assert not any("aws-runbook" in f for f in filenames)


def test_generic_runbooks_match_any(chroma_client):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _make_runbook(tmp, "generic-rb", "database, connections")
        _make_runbook(tmp, "aws-rb", "ec2, aws")
        _ingest_directory(chroma_client, tmp, "test_generic", "runbook")
    collection = chroma_client.get_collection("test_generic")
    results = collection.query(
        query_texts=["database error"],
        n_results=10,
        where={"cloud_provider": {"$in": ["gcp", "generic"]}},
    )
    filenames = [m.get("filename", "") for m in results["metadatas"][0]]
    assert any("generic-rb" in f for f in filenames)
    assert not any("aws-rb" in f for f in filenames)


def test_aws_no_regression(chroma_client):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _make_runbook(tmp, "aws-rb", "ec2, aws")
        _make_runbook(tmp, "gcp-rb", "gcp, gce")
        _make_runbook(tmp, "gen-rb", "database, connections")
        _ingest_directory(chroma_client, tmp, "test_regression", "runbook")
    collection = chroma_client.get_collection("test_regression")
    results = collection.query(
        query_texts=["service down"],
        n_results=10,
        where={"cloud_provider": {"$in": ["aws", "generic"]}},
    )
    filenames = [m.get("filename", "") for m in results["metadatas"][0]]
    assert any("aws-rb" in f for f in filenames)
    assert any("gen-rb" in f for f in filenames)
    assert not any("gcp-rb" in f for f in filenames)


# ---------------------------------------------------------------------------
# AZ-07: Azure runbooks parseable by RAG
# ---------------------------------------------------------------------------


class TestAzureRunbooks:
    """AZ-07: Azure runbook files parseable by RAG with azure tag detection."""

    RUNBOOK_DIR = pathlib.Path("knowledge/runbooks/azure")

    def test_runbook_dir_exists(self):
        assert self.RUNBOOK_DIR.is_dir(), "knowledge/runbooks/azure/ directory must exist"

    def test_app_service_runbook_has_azure_tag(self):
        rb = self.RUNBOOK_DIR / "azure-app-service-down.md"
        assert rb.exists(), "azure-app-service-down.md must exist"
        content = rb.read_text()
        assert "azure" in content.lower()

    def test_runbooks_have_exec_steps(self):
        for rb in self.RUNBOOK_DIR.glob("*.md"):
            content = rb.read_text()
            assert "<!-- exec:" in content, f"{rb.name} must have at least one <!-- exec: --> step"

    def test_runbooks_have_cloud_provider_frontmatter(self):
        import re

        for rb in self.RUNBOOK_DIR.glob("*.md"):
            content = rb.read_text()
            assert re.search(r"cloud_provider:\s*azure", content), (
                f"{rb.name} must have 'cloud_provider: azure' in frontmatter"
            )
