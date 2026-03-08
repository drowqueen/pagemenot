import os

import chromadb
import pytest

# Minimal env so Settings loads without real secrets
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("LLM_MODEL", "gpt-4o")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture
def chroma_client():
    return chromadb.EphemeralClient()
