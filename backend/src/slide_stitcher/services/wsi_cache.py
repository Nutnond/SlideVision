"""Per-thread LRU cache for OpenSlide handles.

OpenSlide handles are NOT thread-safe per-handle, but separate handles on
separate threads can be used in parallel without locking. So we key the cache
by (path, thread_id) — each worker thread gets its own handle pool, and we
never need to lock around the actual `read_region` call.

This module is Qt-free and lives under services/ so it can be used from any
thread including non-Qt worker threads.
"""

import threading
from collections import OrderedDict
from pathlib import Path

import openslide


def _try_open(path: Path) -> openslide.OpenSlide | None:
    try:
        return openslide.open_slide(str(path))
    except openslide.OpenSlideError:
        return None
    except OSError:
        return None
    except Exception:
        return None


class WSIHandleCache:
    def __init__(self, max_open_per_thread: int = 8) -> None:
        self._max = max_open_per_thread
        # outer dict: thread_id -> (path -> OpenSlide), insertion-ordered for LRU
        self._per_thread: dict[int, OrderedDict[Path, openslide.OpenSlide]] = {}
        self._lock = threading.Lock()

    def get(self, path: Path) -> openslide.OpenSlide | None:
        """Return a cached OpenSlide handle for `path` on the current thread,
        opening a new one if necessary. Returns None if the file cannot be
        opened as a WSI."""
        tid = threading.get_ident()
        with self._lock:
            per_thread = self._per_thread.get(tid)
            if per_thread is None:
                per_thread = OrderedDict()
                self._per_thread[tid] = per_thread

            existing = per_thread.get(path)
            if existing is not None:
                per_thread.move_to_end(path)
                return existing

        # Opening a slide does disk I/O — do it OUTSIDE the lock so multiple
        # threads can open different files in parallel.
        slide = _try_open(path)
        if slide is None:
            return None

        with self._lock:
            per_thread = self._per_thread.setdefault(tid, OrderedDict())
            existing = per_thread.get(path)
            if existing is not None:
                # Another thread beat us to it on this same thread — use that one.
                slide.close()
                per_thread.move_to_end(path)
                return existing
            per_thread[path] = slide
            while len(per_thread) > self._max:
                _, old = per_thread.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass
            return slide

    def close_all(self) -> None:
        """Close every cached handle. Safe to call from any thread; intended
        for case-close and app-shutdown."""
        with self._lock:
            for per_thread in self._per_thread.values():
                for slide in per_thread.values():
                    try:
                        slide.close()
                    except Exception:
                        pass
            self._per_thread.clear()

    def close_thread(self) -> None:
        """Close all handles owned by the current thread. Call from a worker
        thread just before it exits."""
        tid = threading.get_ident()
        with self._lock:
            per_thread = self._per_thread.pop(tid, None)
        if per_thread is not None:
            for slide in per_thread.values():
                try:
                    slide.close()
                except Exception:
                    pass
