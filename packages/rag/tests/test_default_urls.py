"""Default service URLs must use 127.0.0.1, not `localhost` (#235).

On Windows `localhost` resolves to ::1 first; Ollama listens on IPv4 only, so each new
connection waited about 2 s for the IPv6 attempt to fail (#185).
"""

import inspect
from pathlib import Path

from book_rag.providers import OllamaEmbedder, OllamaLLM
from book_rag.providers.tei import TeiReranker

ROOT = Path(__file__).resolve().parents[3]


def _default_base_url(cls: type) -> str:
    return str(inspect.signature(cls.__init__).parameters["base_url"].default)


def test_provider_default_base_urls_use_loopback_ip() -> None:
    for cls in (OllamaEmbedder, OllamaLLM, TeiReranker):
        url = _default_base_url(cls)
        assert "localhost" not in url, f"{cls.__name__} default {url}"
        assert "127.0.0.1" in url


def test_settings_defaults_use_loopback_ip() -> None:
    for rel in ("apps/api/src/book_rag_api/config.py", "apps/worker/src/book_rag_worker/config.py"):
        for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith(("ollama_url", "reranker_url")):
                assert "localhost" not in line, f"{rel}: {line.strip()}"


def test_env_example_uses_loopback_ip_for_ollama_and_reranker() -> None:
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "OLLAMA_URL" in line or "RERANKER_URL" in line:
            assert "localhost" not in line, line
