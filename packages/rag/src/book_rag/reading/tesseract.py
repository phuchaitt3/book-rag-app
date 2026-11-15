"""Tesseract OCR through the `tesseract` binary (no Python dependency)."""

from __future__ import annotations

import subprocess

from book_rag.reading.base import RENDER_DPI, PageReadError


class TesseractReader:
    """Runs `tesseract stdin stdout -l <languages>` on a page image. CPU only, deterministic.

    A missing binary raises `FileNotFoundError` (a setup error that fails the job); a failed or
    timed-out call on one page raises `PageReadError`.
    """

    name = "tesseract"

    def __init__(
        self, languages: str = "vie+eng", command: str = "tesseract", timeout: float = 120.0
    ) -> None:
        self.languages = languages
        self.command = command
        self.timeout = timeout
        self.version = f"{languages}@{RENDER_DPI}dpi"

    def read(self, image: bytes) -> str:
        try:
            done = subprocess.run(
                [self.command, "stdin", "stdout", "-l", self.languages],
                input=image,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PageReadError(f"tesseract timed out after {self.timeout:g}s") from exc
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", "replace").strip()[:300]
            raise PageReadError(f"tesseract exited with {done.returncode}: {detail}")
        return done.stdout.decode("utf-8", "replace").strip()
