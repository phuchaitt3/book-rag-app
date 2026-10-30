from book_rag_api.db import to_asyncpg_url


def test_plain_neon_url_becomes_asyncpg() -> None:
    url = to_asyncpg_url(
        "postgresql://u:p@ep-x-pooler.example.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert dict(url.query) == {"ssl": "require"}
    assert url.host == "ep-x-pooler.example.neon.tech"


def test_asyncpg_url_is_unchanged() -> None:
    raw = "postgresql+asyncpg://bookrag:bookrag@localhost:5432/bookrag"
    url = to_asyncpg_url(raw)
    assert url.render_as_string(hide_password=False) == raw
