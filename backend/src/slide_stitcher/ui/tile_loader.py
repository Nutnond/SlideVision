"""Background tile loader for deep-zoom rendering.

Architecture: a plain Python `threading.Thread` reads tiles from WSI files via
`tile_reader.read_tile` (PNG bytes). Tile bytes are passed back to the UI
thread via a Qt signal (which is safe to emit from any thread); the UI thread
converts to QPixmap, caches in QPixmapCache, and re-emits as `tileReady`.

Why not QThread + worker QObject? Calling methods on a QObject that lives in
another thread is unreliable in PySide6 — direct calls from the UI thread to
the worker sometimes silently fail. Using a Python thread with a thread-safe
`queue.Queue` and a Qt signal for the return path sidesteps the issue.

Stale-request handling: every batch request carries a monotonic id. When a
newer request for the same slide arrives, older results are filtered out by
the worker before emitting.
"""

import queue
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap, QPixmapCache

from slide_stitcher.services.tile_reader import TileRequest, read_tile
from slide_stitcher.services.wsi_cache import WSIHandleCache

if TYPE_CHECKING:
    from typing import Optional


class _TileWorker:
    """Plain Python worker running in a daemon `threading.Thread`.

    Multiple workers share a single queue — OpenSlide handles are cached
    per-thread, so 4 workers each open their own slide handle and read
    tiles in parallel (4× speedup on I/O-bound loads).
    """

    _shared_state: dict = {}  # class-level for sharing across instances (used by pool)

    def __init__(self, cache: WSIHandleCache, on_tile_bytes, name: str, shared_queue: queue.Queue,
                 shared_lock: threading.Lock, latest_request_id: dict, running_flag) -> None:
        self._cache = cache
        self._on_tile_bytes = on_tile_bytes
        self._q = shared_queue
        self._lock = shared_lock
        self._latest_request_id = latest_request_id
        self._running_ref = running_flag  # dict with key 'running'
        self._name = name
        self._processed = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
        self._thread.start()

    def stop(self) -> None:
        # Just wake up the queue; the run loop checks _running_ref.
        pass  # handled by pool

    def _run(self) -> None:
        while self._running_ref.get("running", True):
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            request_id, slide_id, req = item
            with self._lock:
                latest = self._latest_request_id.get(slide_id)
            if latest != request_id:
                continue  # stale — superseded by a newer request
            self._processed += 1
            png = read_tile(req, self._cache)
            if png is not None:
                self._on_tile_bytes(
                    slide_id,
                    req.level,
                    req.region_origin[0],
                    req.region_origin[1],
                    req.region_size[0],
                    req.region_size[1],
                    png,
                )
        self._cache.close_thread()


class _TileWorkerPool:
    """Pool of N Python threads consuming a shared queue."""

    def __init__(self, cache: WSIHandleCache, on_tile_bytes, num_workers: int = 4) -> None:
        self._cache = cache
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._latest_request_id: dict[str, int] = {}
        self._running = {"running": True, "processed_total": 0}
        self._workers = [
            _TileWorker(cache, on_tile_bytes, f"tw{i+1}", self._q, self._lock,
                       self._latest_request_id, self._running)
            for i in range(num_workers)
        ]

    def submit(self, request_id: int, slide_id: str, requests: list[TileRequest]) -> None:
        with self._lock:
            self._latest_request_id[slide_id] = request_id
        for r in requests:
            self._q.put((request_id, slide_id, r))

    def cancel(self, slide_id: str) -> None:
        with self._lock:
            self._latest_request_id.pop(slide_id, None)

    def stop(self) -> None:
        self._running["running"] = False
        # Sentinels to wake all workers.
        for _ in self._workers:
            self._q.put(None)

    def join(self, timeout: float = 2.0) -> None:
        for w in self._workers:
            try:
                w._thread.join(timeout=timeout)
            except Exception:
                pass


class TileLoader(QObject):
    """Public API. Lives in UI thread. Routes batched tile requests to a
    pool of background workers and emits pixmaps back as they arrive."""

    tileReady = Signal(str, int, int, int, int, int, QPixmap)
    # slide_id, level, origin_x, origin_y, size_w, size_h, pixmap

    # Internal: emitted from any worker thread, queued to UI thread.
    _bytesReady = Signal(str, int, int, int, int, int, bytes)

    def __init__(self, cache: WSIHandleCache, parent: "Optional[QObject]" = None,
                 num_workers: int = 4) -> None:
        super().__init__(parent)
        self._cache = cache
        QPixmapCache.setCacheLimit(512 * 1024)  # 512 MB
        self._bytesReady.connect(self._on_tile_bytes)
        self._pool = _TileWorkerPool(cache, self._bytesReady.emit, num_workers=num_workers)
        self._counter = 0

    def request(self, slide_id: str, requests: list[TileRequest]) -> None:
        """Submit a batch of tile requests. Cache hits emit tileReady
        synchronously from this call (in the calling UI thread). Misses are
        processed asynchronously by the worker pool."""
        if not requests:
            return
        self._counter += 1
        request_id = self._counter
        misses: list[TileRequest] = []
        for req in requests:
            key = self._cache_key(slide_id, req)
            cached = QPixmapCache.find(key)
            if cached is not None:
                self.tileReady.emit(
                    slide_id,
                    req.level,
                    req.region_origin[0],
                    req.region_origin[1],
                    req.region_size[0],
                    req.region_size[1],
                    cached,
                )
            else:
                misses.append(req)
        if misses:
            self._pool.submit(request_id, slide_id, misses)

    def cancel(self, slide_id: str) -> None:
        self._pool.cancel(slide_id)

    def shutdown(self) -> None:
        self._pool.stop()
        self._pool.join(timeout=2.0)

    def _on_tile_bytes(
        self,
        slide_id: str,
        level: int,
        ox: int,
        oy: int,
        sw: int,
        sh: int,
        png_bytes: bytes,
    ) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(png_bytes):
            return
        key = f"{slide_id}|L{level}|{ox}_{oy}|{sw}x{sh}"
        QPixmapCache.insert(key, pixmap)
        self.tileReady.emit(slide_id, level, ox, oy, sw, sh, pixmap)

    @staticmethod
    def _cache_key(slide_id: str, req: TileRequest) -> str:
        return (
            f"{slide_id}|L{req.level}|"
            f"{req.region_origin[0]}_{req.region_origin[1]}|"
            f"{req.region_size[0]}x{req.region_size[1]}"
        )

