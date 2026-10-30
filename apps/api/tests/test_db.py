from book_rag_api.db import to_asyncpg_url
from book_rag_api.jobs import to_libpq_dsn


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


def test_queue_dsn_is_a_libpq_url() -> None:
    dsn = to_libpq_dsn("postgresql+asyncpg://u:p@host/db?ssl=require")
    assert dsn == "postgresql://u:p@host/db?sslmode=require"


def test_queue_dsn_drops_libpq_only_options_it_cannot_pass_through() -> None:
    dsn = to_libpq_dsn("postgresql://u:p@host/db?sslmode=require&channel_binding=require")
    assert dsn == "postgresql://u:p@host/db?sslmode=require"
