"""Zero-retention ephemeral buffer.

Uploads are held in a RAM-backed temp file under /dev/shm (tmpfs) — never on SSD or object storage — and the
bytes are overwritten with zeros and unlinked when the request finishes, success or failure.
"""
from __future__ import annotations

import os
import tempfile

from .config import settings


class EphemeralBuffer:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._tmp = None

    def __enter__(self) -> "EphemeralBuffer":
        settings.EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.NamedTemporaryFile(dir=settings.EPHEMERAL_DIR, prefix="nf_", delete=False)
        self._tmp.write(self._data)
        self._tmp.flush()
        return self

    def read(self) -> bytes:
        self._tmp.seek(0)
        return self._tmp.read()

    @property
    def path(self) -> str:
        return self._tmp.name

    def __exit__(self, *exc) -> None:
        try:
            size = self._tmp.tell() or len(self._data)
            self._tmp.seek(0)
            self._tmp.write(b"\0" * size)  # overwrite before unlink
            self._tmp.flush()
            os.fsync(self._tmp.fileno())
        except Exception:
            pass
        finally:
            try:
                self._tmp.close()
                os.unlink(self._tmp.name)
            except Exception:
                pass
            self._data = b""

    @staticmethod
    def backing_store() -> str:
        return str(settings.EPHEMERAL_DIR)
