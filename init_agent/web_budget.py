"""Connection admission and shared work limits for the optional dashboard."""
from __future__ import annotations

import http.client
import socket
import threading
import time
from http.server import ThreadingHTTPServer

MAX_CONNECTIONS = 4
REQUEST_SECONDS = 5.0
MAX_HEADER_BYTES = 16_384
MAX_RESPONSE_BYTES = 2_097_152
SNAPSHOT_SECONDS = 2.0
SNAPSHOT_STEPS = 500_000
SNAPSHOT_ROWS = 1000


class LimitedHeaders:
    def __init__(self, stream):
        self.stream = stream
        self.remaining = MAX_HEADER_BYTES

    def readline(self, size=-1):
        value = self.stream.readline(min(size if size >= 0 else self.remaining + 1, self.remaining + 1))
        self.remaining -= len(value)
        if self.remaining < 0:
            raise http.client.HTTPException("header byte budget exceeded")
        return value

    def __getattr__(self, name):
        return getattr(self.stream, name)


class BoundedHTTPServer(ThreadingHTTPServer):
    request_queue_size = 8
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.window = time.monotonic()
        self.accepted = 0
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        now = time.monotonic()
        if now - self.window >= 1:
            self.window, self.accepted = now, 0
        if self.accepted >= 20 or not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        self.accepted += 1
        try:
            request.settimeout(REQUEST_SECONDS)
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        def expire():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(REQUEST_SECONDS, expire)
        timer.daemon = True
        timer.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            self.slots.release()


class SnapshotCache:
    """Single-flight, short-lived cache; failures also get a cooling period."""
    def __init__(self, builder):
        self.builder = builder
        self.lock = threading.Lock()
        self.expires = 0.0
        self.value = None
        self.error = None

    def get(self):
        with self.lock:
            if time.monotonic() >= self.expires:
                self.value = self.error = None
                try:
                    self.value = self.builder()
                except Exception as exc:
                    self.error = exc
                self.expires = time.monotonic() + 2.0
            if self.error:
                raise self.error
            return self.value
