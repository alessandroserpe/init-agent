"""Connection admission and shared work limits for the optional dashboard."""
from __future__ import annotations

import http.client
import io
from collections import OrderedDict
import socket
import threading
import time
from http.server import ThreadingHTTPServer

MAX_CONNECTIONS = 4
MAX_PREAUTH = 32
MAX_PUBLIC = 2
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
        self.public_slots = threading.BoundedSemaphore(MAX_PUBLIC)
        self.pending = OrderedDict()
        self.workers = {}
        self.worker_lock = threading.Lock()
        self.authorize_headers = lambda headers: False
        self.window = time.monotonic()
        self.accepted = 0
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        # Incomplete connections own no thread and no authenticated work slot.
        # Evict the oldest incomplete connection, never reject a fresh client
        # merely because slow peers filled the bounded pre-auth queue.
        if len(self.pending) >= MAX_PREAUTH:
            oldest, _ = self.pending.popitem(last=False)
            self.shutdown_request(oldest)
        request.setblocking(False)
        self.pending[request] = (client_address, time.monotonic())
        self.service_actions()

    def service_actions(self):
        now = time.monotonic()
        if now - self.window >= 1:
            self.window, self.accepted = now, 0
        for request, (address, started) in list(self.pending.items()):
            if now - started >= REQUEST_SECONDS:
                del self.pending[request]
                self.shutdown_request(request)
                continue
            try:
                data = request.recv(MAX_HEADER_BYTES + 1, socket.MSG_PEEK)
            except BlockingIOError:
                continue
            except OSError:
                data = b''
            if data and len(data) <= MAX_HEADER_BYTES and b'\r\n\r\n' not in data:
                continue
            del self.pending[request]
            authenticated = False
            try:
                if not data or len(data) > MAX_HEADER_BYTES:
                    raise ValueError('header limit')
                first, raw_headers = data.split(b'\r\n', 1)
                if len(first) > 4096 or len(first.split()) != 3:
                    raise ValueError('invalid request line')
                headers = http.client.parse_headers(io.BytesIO(raw_headers.split(b'\r\n\r\n', 1)[0] + b'\r\n\r\n'))
                authenticated = self.authorize_headers(headers)
            except (ValueError, http.client.HTTPException):
                self.shutdown_request(request)
                continue
            slots = self.slots if authenticated else self.public_slots
            # Public traffic cannot spend the authenticated rate/work allowance.
            if (not authenticated and self.accepted >= 20) or not slots.acquire(blocking=False):
                self.shutdown_request(request)
                continue
            if not authenticated:
                self.accepted += 1
            with self.worker_lock:
                self.workers[request] = slots
            try:
                request.settimeout(REQUEST_SECONDS)
                super().process_request(request, address)
            except BaseException:
                with self.worker_lock:
                    self.workers.pop(request, None)
                slots.release()
                self.shutdown_request(request)
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
            with self.worker_lock:
                slots = self.workers.pop(request)
            slots.release()

    def server_close(self):
        for request in list(self.pending):
            self.shutdown_request(request)
        self.pending.clear()
        super().server_close()


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
