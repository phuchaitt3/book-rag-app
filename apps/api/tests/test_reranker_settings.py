import pytest
from pydantic import ValidationError

from book_rag.providers import FakeReranker, TeiReranker
from book_rag_api.config import Settings
from book_rag_api.main import _reranker


def test_no_reranker_by_default() -> None:
    assert _reranker(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_reranker_provider_picks_the_implementation() -> None:
    assert isinstance(_reranker(Settings(reranker_provider="fake")), FakeReranker)
    assert isinstance(_reranker(Settings(reranker_provider="tei")), TeiReranker)


def test_unknown_reranker_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(reranker_provider="cohere")  # type: ignore[arg-type]
