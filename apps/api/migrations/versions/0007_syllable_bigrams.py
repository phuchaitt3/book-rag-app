"""chunks.tsv_bi: unigram and syllable-bigram lexemes for the BM25 leg (#95)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Adjacent word pairs of a text as tsvector lexemes 'a b' with their positions (the position of
# the first word). Words are the same `\w+` runs the query side uses, lower-cased.
BIGRAM_FUNCTION = r"""
CREATE FUNCTION bigram_tsvector(t text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT coalesce(string_agg('''' || b || ''':' || p, ' ' ORDER BY b), '')::tsvector
  FROM (
    SELECT a.w || ' ' || c.w AS b,
           string_agg(least(a.n, 16383)::text, ',' ORDER BY a.n) AS p
    FROM (SELECT lower(m[1]) AS w, n FROM regexp_matches(t, '(\w+)', 'g')
          WITH ORDINALITY AS r(m, n)) a
    JOIN (SELECT lower(m[1]) AS w, n FROM regexp_matches(t, '(\w+)', 'g')
          WITH ORDINALITY AS r(m, n)) c ON c.n = a.n + 1
    GROUP BY 1
  ) g
$$
"""


def upgrade() -> None:
    op.execute(BIGRAM_FUNCTION)
    op.add_column(
        "chunks",
        sa.Column(
            "tsv_bi",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text) || bigram_tsvector(text)", persisted=True),
        ),
    )
    op.create_index("ix_chunks_tsv_bi", "chunks", ["tsv_bi"], postgresql_using="gin")
    # Statistics now count unigrams and bigrams: rebuild them for the books that exist (the
    # same statements as `refresh_book_stats`, all books).
    op.execute(
        "UPDATE chunks SET token_count = "
        "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv_bi))"
    )
    op.execute("DELETE FROM book_terms")
    op.execute(
        "INSERT INTO book_terms (book_id, term, df) "
        "SELECT c.book_id, u.lexeme, count(*) FROM chunks c, unnest(c.tsv_bi) u GROUP BY 1, 2"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_tsv_bi", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "tsv_bi")
    op.execute("DROP FUNCTION bigram_tsvector(text)")
    op.execute(
        "UPDATE chunks SET token_count = "
        "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv))"
    )
    op.execute("DELETE FROM book_terms")
    op.execute(
        "INSERT INTO book_terms (book_id, term, df) "
        "SELECT c.book_id, u.lexeme, count(*) FROM chunks c, unnest(c.tsv) u GROUP BY 1, 2"
    )
