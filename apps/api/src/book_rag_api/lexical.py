"""BM25 over Postgres full-text data, from stored per-book statistics (ADR 0011).

`refresh_book_stats` writes the statistics when a book's chunks are written; `BM25_SEARCH`
ranks with them. Terms are the lexemes of the `simple` text search configuration, the same as
`chunks.tsv`, so query and chunks tokenise alike.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# BM25 parameters (the usual defaults) and the share of a book's chunks above which a query
# word is too common to select candidates with; it still counts in the score.
K1 = 1.2
B = 0.75
RARE_SHARE = 0.2

_REFRESH = (
    "UPDATE chunks SET token_count = "
    "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv)) WHERE book_id = :book_id",
    "DELETE FROM book_terms WHERE book_id = :book_id",
    "INSERT INTO book_terms (book_id, term, df) "
    "SELECT c.book_id, u.lexeme, count(*) FROM chunks c, unnest(c.tsv) u "
    "WHERE c.book_id = :book_id GROUP BY 1, 2",
)


async def refresh_book_stats(session: AsyncSession, book_id: UUID) -> None:
    """Recompute chunk lengths and term document frequencies for one book.

    Call it in the transaction that writes the book's chunks, after a flush.
    """
    for statement in _REFRESH:
        await session.execute(text(statement), {"book_id": book_id})


async def has_stats(session: AsyncSession, book_id: UUID) -> bool:
    """Whether the book's statistics exist (a book ingested before they were written has none)."""
    found = await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM book_terms WHERE book_id = :book_id)"),
        {"book_id": book_id},
    )
    return bool(found)


# Candidates are the chunks the GIN index finds for the query's rare words (all words when none
# is rare); each is scored over every query word that the book contains. A term is quoted for
# `to_tsquery`, so punctuation inside a lexeme (a URL, an e-mail) cannot be read as syntax.
BM25_SEARCH = text(
    r"""
WITH q AS (
  SELECT lexeme AS term, cardinality(positions) AS qtf
  FROM unnest(to_tsvector('simple', :query))
), s AS (
  SELECT count(*)::float AS n, nullif(avg(token_count), 0)::float AS avgdl
  FROM chunks WHERE book_id = :book_id
), qt AS (
  SELECT q.term, q.qtf, t.df::float AS df,
         '''' || replace(replace(q.term, '\', '\\'), '''', '''''') || '''' AS quoted
  FROM q JOIN book_terms t ON t.term = q.term AND t.book_id = :book_id
), cands AS (
  SELECT c.id, c.text, c.page, c.section_path, c.tsv, c.token_count
  FROM chunks c
  WHERE c.book_id = :book_id
    AND c.tsv @@ to_tsquery('simple', coalesce(
      (SELECT string_agg(quoted, ' | ') FROM qt WHERE df <= :share * (SELECT n FROM s)),
      (SELECT string_agg(quoted, ' | ') FROM qt)))
)
SELECT d.id, d.text, d.page, d.section_path
FROM cands d, unnest(d.tsv) u JOIN qt ON qt.term = u.lexeme, s
GROUP BY d.id, d.text, d.page, d.section_path, d.token_count, s.avgdl, s.n
ORDER BY sum(qt.qtf * ln(1 + (s.n - qt.df + 0.5) / (qt.df + 0.5))
             * cardinality(u.positions) * (:k1 + 1)
             / (cardinality(u.positions)
                + :k1 * (1 - :b + :b * d.token_count / coalesce(s.avgdl, 1)))) DESC
LIMIT :limit
"""
)
