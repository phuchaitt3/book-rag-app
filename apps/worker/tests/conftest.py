import asyncio
import io
import sys
from collections.abc import Iterator
from pathlib import Path

import font_roboto
import pytest
from alembic import command
from alembic.config import Config
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    # psycopg's async mode cannot run on Windows' default ProactorEventLoop.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


ALEMBIC_INI = Path(__file__).parents[2] / "api" / "alembic.ini"
FONT = "Roboto"  # has Vietnamese glyphs; the base-14 fonts do not
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(font_roboto.__file__).parent / "files" / "Roboto-Regular.ttf"))
)

CHAPTERS = [
    ("Chương 1", 1, "Việt Nam là một đất nước nằm ở Đông Nam Á. " * 40),
    ("1.1 Mở đầu", 2, "Người nông dân gieo hạt vào mùa xuân. " * 40),
    ("Chương 2", 1, "Sông Mê Kông chảy qua nhiều tỉnh phía nam. " * 40),
]


def make_pdf() -> bytes:
    """One chapter per page, with an outline."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for number, (title, level, body) in enumerate(CHAPTERS, start=1):
        canvas.bookmarkPage(f"b{number}")
        canvas.addOutlineEntry(title, f"b{number}", level=level - 1)
        canvas.setFont(FONT, 16)
        canvas.drawString(40, 800, title)
        canvas.setFont(FONT, 11)
        y = 770.0
        for line in simpleSplit(body, FONT, 11, 515):
            canvas.drawString(40, y, line)
            y -= 15
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    (tmp_path / "book.pdf").write_bytes(make_pdf())
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    return tmp_path
