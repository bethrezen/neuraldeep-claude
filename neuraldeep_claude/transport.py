"""All NeuralDeep networking bypasses ambient HTTP/SOCKS proxy settings."""
from __future__ import annotations
import json
import socket
import threading
import urllib.error
import urllib.request

BASE = "https://api.neuraldeep.ru"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not copy a NeuralDeep credential to a redirect target.
        return None

class UpstreamError(Exception):
    def __init__(self, status: int, data: bytes, headers=None):
        super().__init__("NeuralDeep HTTP " + str(status))
        self.status, self.data, self.headers = status, data, headers or {}

class RequestCancelled(Exception):
    """The local client disconnected; do not continue its provider request."""


class RequestCancellation:
    """Wake urllib's blocked header/body read by shutting down its real socket.

    The request-owning thread closes the response normally. Calling close() on
    a buffered response from the ping thread can itself wait for the blocked
    reader's lock, so cancellation uses socket.shutdown() instead.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._socket = None
        self._cancelled = threading.Event()
        self._completed = False

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def check(self):
        if self.cancelled:
            raise RequestCancelled("Local client disconnected")

    @staticmethod
    def _shutdown(connection):
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                # The owner may have just completed and closed this socket.
                pass

    def bind_socket(self, connection):
        with self._lock:
            self._socket = connection
            cancelled = self.cancelled
        if cancelled:
            self._shutdown(connection)
            self.check()

    def cancel(self):
        with self._lock:
            if self._completed or self.cancelled:
                return False
            self._cancelled.set()
            connection = self._socket
        self._shutdown(connection)
        return True

    def complete(self):
        with self._lock:
            self._completed = True
            self._socket = None


class _CancellableHandler:
    def __init__(self, cancellation):
        super().__init__()
        self._cancellation = cancellation

    def do_open(self, connection_class, request, **kwargs):
        cancellation = self._cancellation

        class Connection(connection_class):
            def connect(self):
                cancellation.check()
                super().connect()
                # HTTP and HTTPS both reach here before sending the request or
                # waiting for headers. DNS/TCP/TLS setup inside super.connect()
                # still follows urllib's existing connect timeout.
                cancellation.bind_socket(self.sock)

        return super().do_open(Connection, request, **kwargs)


class _CancellableHTTPHandler(_CancellableHandler, urllib.request.HTTPHandler):
    pass


class _CancellableHTTPSHandler(_CancellableHandler, urllib.request.HTTPSHandler):
    pass


def open_request(method, path, key=None, body=None, base=BASE, timeout=900, cancellation=None):
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json", "User-Agent": "neuraldeep-claude/0.1"}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode()
    handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
    if cancellation is not None:
        cancellation.check()
        handlers += [_CancellableHTTPHandler(cancellation), _CancellableHTTPSHandler(cancellation)]
    opener = urllib.request.build_opener(*handlers)
    try:
        response = opener.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=timeout)
        if cancellation is not None and cancellation.cancelled:
            response.close()
            cancellation.check()
        return response
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read()
        finally:
            exc.close()
        if cancellation is not None:
            cancellation.check()
        raise UpstreamError(exc.code, data, dict(exc.headers)) from None
    except Exception:
        if cancellation is not None:
            cancellation.check()
        raise

def request(method, path, key=None, body=None, base=BASE, timeout=900):
    with open_request(method, path, key, body, base, timeout) as response:
        return json.load(response)

def sse_chunks(response):
    """Parse complete SSE data frames, including multiline frames."""
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                if payload == "[DONE]":
                    return
                item = json.loads(payload)
                if "error" in item:
                    raise UpstreamError(502, payload.encode())
                yield item
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))
