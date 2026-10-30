from pathlib import Path


class LocalStorage:
    """Reads uploaded files from a directory; a key may not leave it."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def read(self, key: str) -> bytes:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"storage key {key!r} is outside the storage directory")
        return path.read_bytes()
