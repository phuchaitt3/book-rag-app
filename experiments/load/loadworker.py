"""The ingestion worker with a fake embedder that has latency (#227). Not part of the product."""

import asyncio
import os

from book_rag.providers import FakeEmbedder
from book_rag_api.models import EMBEDDING_DIM
from book_rag_worker.__main__ import run
from book_rag_worker.config import get_worker_settings
from book_rag_worker.worker import build_worker

settings = get_worker_settings()
worker = build_worker(
    settings,
    embedder=FakeEmbedder(EMBEDDING_DIM, batch_delay=float(os.environ["FAKE_BATCH_DELAY"])),
)
asyncio.run(run(worker))
