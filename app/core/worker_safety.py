"""Small process-local safeguards for the single-worker Render deployment.

The lock prevents a manual identity request from overlapping the live polling
worker in the same process.  The memory helper asks Linux libc to return
unused heap pages after already-committed work; it is safe to no-op elsewhere.
"""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)
_COLLECTION_LOCK = threading.Lock()


def process_resident_memory_bytes() -> int | None:
    """Return Linux RSS when the process exposes /proc/self/statm."""
    try:
        with open("/proc/self/statm", encoding="utf-8") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None


@contextmanager
def collection_slot(kind: str) -> Iterator[bool]:
    """Acquire the single collection slot without waiting.

    `False` means another collection unit is already active in this worker.
    The caller must defer or reject its own work rather than overlap it.
    """
    acquired = _COLLECTION_LOCK.acquire(blocking=False)
    try:
        if not acquired:
            logger.info("collection_slot_unavailable", extra={"collection_kind": kind})
        yield acquired
    finally:
        if acquired:
            _COLLECTION_LOCK.release()


def release_process_memory(*, reason: str) -> int | None:
    """Collect Python garbage and request glibc release free heap pages.

    This is intentionally best-effort. It never changes correctness: on an
    unsupported runtime, it simply logs RSS after normal garbage collection.
    """
    gc.collect()
    trimmed = False
    try:
        libc = ctypes.CDLL("libc.so.6")
        malloc_trim = getattr(libc, "malloc_trim", None)
        if malloc_trim is not None:
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            trimmed = bool(malloc_trim(0))
    except (AttributeError, OSError):
        pass
    resident = process_resident_memory_bytes()
    logger.info(
        "process_memory_release",
        extra={"reason": reason, "malloc_trimmed": trimmed, "resident_memory_bytes": resident},
    )
    return resident
