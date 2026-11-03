"""Authenticated loopback Anthropic Messages to NeuralDeep gateway."""
from __future__ import annotations
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from . import catalog, protocol, title_helpers
from .config import atomic_json, key_for, local_token, source_revision
from .transport import RequestCancellation, UpstreamError, open_request, sse_chunks

PING_INTERVAL_SECONDS = 15
CLAUDE_PROMPT_LIMIT_MESSAGE = "Claude 5.5 does not support prompts over ~90k tokens through this API."

def error_body(message, kind="invalid_request_error"):
    return {"type": "error", "error": {"type": kind, "message": message}}

def serve(root: Path, port: int = 8787):
    token = local_token(root)
    revision = source_revision()
    requests_lock = threading.Lock()
    active_requests = 0
    draining = False
    metrics_lock = threading.Lock()
    def metric(data):
        data["time"] = time.time()
        with metrics_lock:
            with (root / ".local/gateway-events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(data) + "\n")
    if hasattr(protocol, "configure"):
        protocol.configure(root)
    semaphores = {}
    limits_lock = threading.Lock()
    def semaphore(mode, limit):
        # Honor the provider's advertised limit, no arbitrary percentage reduction.
        with limits_lock:
            return semaphores.setdefault((mode, limit), threading.BoundedSemaphore(limit))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, fmt, *args):
            # No bodies, keys, prompts, or model-generated text in logs.
            return

        def send_json(self, status, data, headers=None):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("request-id", "nd_" + uuid.uuid4().hex)
            for key, value in (headers or {}).items():
                if key.lower() in ("retry-after", "retry-after-ms", "x-window", "x-wallet", "x-quota-reset", "x-neuraldeep-token-count"):
                    self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            return self.headers.get("x-api-key") == token or self.headers.get("Authorization") == "Bearer " + token

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                return self.send_json(200, {"status": "ok", "service": "neuraldeep-claude", "direct_network": True, "revision": revision, "active_requests": active_requests})
            if not self.authorized():
                return self.send_json(401, error_body("Invalid local gateway credential", "authentication_error"))
            if path == "/v1/models":
                cat = catalog.load(root)
                return self.send_json(200, catalog.discovery_data(cat))
            return self.send_json(404, error_body("Unknown endpoint", "not_found_error"))

        def do_POST(self):
            nonlocal active_requests, draining
            request_id = None
            streaming_started = False
            stop_ping = threading.Event()
            write_lock = threading.Lock()
            ping_thread = None
            cancellation = None
            headers_received = False
            def client_disconnected():
                stop_ping.set()
                if cancellation is not None and cancellation.cancel():
                    metric({"event": "cancelled", "id": request_id, "reason": "client_disconnect", "phase": "body" if headers_received else "connect_or_headers", "elapsed": time.monotonic() - started})
            def write_event(event):
                payload = json.dumps(event, ensure_ascii=False)
                try:
                    with write_lock:
                        self.wfile.write(("event: " + event["type"] + "\ndata: " + payload + "\n\n").encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    client_disconnected()
                    raise
            def keepalive():
                while not stop_ping.wait(PING_INTERVAL_SECONDS):
                    try:
                        write_event({"type": "ping"})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
            if not self.authorized():
                return self.send_json(401, error_body("Invalid local gateway credential", "authentication_error"))
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 256 * 1024 * 1024:
                    return self.send_json(413, error_body("Invalid request size", "request_too_large"))
                body = json.loads(self.rfile.read(length))
                if urlparse(self.path).path == "/_neuraldeep/shutdown":
                    with requests_lock:
                        if active_requests:
                            return self.send_json(409, error_body("Gateway has active requests; wait before restart"))
                        draining = True
                        self.send_json(200, {"status": "stopping"})
                        threading.Thread(target=server.shutdown, daemon=True).start()
                        return
                # Debug only protocol structure; never persist prompts or tool data.
                atomic_json(root / ".local/request-shape.json", {"keys": list(body), "roles": [m.get("role") for m in body.get("messages", [])], "context_management": body.get("context_management"), "tools": [{"name": t.get("name"), "type": t.get("type")} for t in body.get("tools", [])]}, private=True)
                path = urlparse(self.path).path
                cat = catalog.load(root)
                model = catalog.resolve(cat, body.get("model", ""))
                if path == "/v1/messages/count_tokens":
                    # NeuralDeep has no documented tokenizer endpoint. Mark this estimate.
                    # Actual input/output/cache usage in Messages responses is never replaced.
                    translated = protocol.to_openai(body | {"max_tokens": 1}, model, model["upstream_id"])
                    raw = json.dumps({k: translated[k] for k in ("messages", "tools") if k in translated}, ensure_ascii=False)
                    estimate = max(1, (len(raw.encode("utf-8")) + 2) // 3)
                    return self.send_json(200, {"input_tokens": estimate}, {"x-neuraldeep-token-count": "estimate"})
                if path != "/v1/messages":
                    return self.send_json(404, error_body("Unknown endpoint", "not_found_error"))
                helper_routing = {}
                title_kind = title_helpers.match_native_title_request(body)
                if title_kind is not None:
                    helper_id = title_helpers.title_model(root)
                    if helper_id is not None:
                        helper_routing = {"requested_model": body["model"],
                                          "helper_rule": "desktop_title:" + title_kind}
                        model = catalog.resolve(cat, helper_id)
                        # The native title parser reads text, not response.model.
                        # Return the actual helper identity and keep the original
                        # route only in structural metrics, without prompt text.
                        body = body | {"model": model["id"]}
                upstream = protocol.to_openai(body, model, model["upstream_id"])
                request_id = uuid.uuid4().hex
                started = time.monotonic()
                metric({"event": "request", "id": request_id, "model": model["id"], "billing": model["billing"], "messages": len(upstream.get("messages", [])), "tools": len(upstream.get("tools", [])), "max_tokens": upstream.get("max_tokens"), "stream": bool(upstream.get("stream")), "effort_requested": (body.get("output_config") or {}).get("effort"), "effort_applied": upstream.get("reasoning_effort"), **helper_routing})
                mode = model["billing"]
                limit = max(1, int(cat.get("limits", {}).get(mode, {}).get("parallel_limit") or 1))
                sem = semaphore(mode, limit)
                if not sem.acquire(blocking=False):
                    return self.send_json(429, error_body("NeuralDeep advertised parallel limit reached", "rate_limit_error"), {"Retry-After": "1"})
                with requests_lock:
                    if draining:
                        sem.release()
                        return self.send_json(503, error_body("Gateway is restarting", "overloaded_error"), {"Retry-After": "1"})
                    active_requests += 1
                cancellation = RequestCancellation()
                try:
                    if body.get("stream"):
                        # A provider can queue/prefill before returning headers.
                        # Keep the Claude connection alive during that wait too.
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        streaming_started = True
                        ping_thread = threading.Thread(target=keepalive, daemon=True)
                        ping_thread.start()
                    with open_request("POST", "/v1/chat/completions", key_for(root, mode), upstream, cancellation=cancellation) as response:
                        headers_received = True
                        metric({"event": "upstream_headers", "id": request_id, "elapsed": time.monotonic() - started, "content_type": response.headers.get("Content-Type")})
                        if body.get("stream"):
                            if "text/event-stream" in response.headers.get("Content-Type", ""):
                                chunks = sse_chunks(response)
                            else:
                                full = json.load(response)
                                for choice in full.get("choices", []):
                                    choice["delta"] = choice.pop("message", {})
                                    for index, call in enumerate(choice["delta"].get("tool_calls", [])):
                                        call["index"] = index
                                chunks = iter([full])
                            for event in protocol.stream_openai(chunks, body["model"]):
                                write_event(event)
                                if event["type"] in ("message_delta", "message_stop"):
                                    metric({"event": event["type"], "id": request_id, "elapsed": time.monotonic() - started, "usage": event.get("usage"), "stop_reason": event.get("delta", {}).get("stop_reason")})
                        else:
                            self.send_json(200, protocol.from_openai(json.load(response), body["model"]))
                finally:
                    stop_ping.set()
                    cancellation.complete()
                    sem.release()
                    with requests_lock:
                        active_requests -= 1
                    metric({"event": "finished", "id": request_id, "elapsed": time.monotonic() - started, "cancelled": cancellation.cancelled})
            except (BrokenPipeError, ConnectionResetError):
                client_disconnected()
                return
            except Exception as exc:
                if cancellation is not None and cancellation.cancelled:
                    return
                if isinstance(exc, UpstreamError):
                    try:
                        data = json.loads(exc.data)
                        detail = data.get("error", data.get("detail", data))
                        message = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
                    except (ValueError, UnicodeError):
                        message = str(exc)
                    # Never forward authorization headers or credential echoes.
                    for mode in ("subscription", "wallet"):
                        try:
                            message = message.replace(key_for(root, mode), "[redacted]")
                        except ValueError:
                            pass
                    status = exc.status
                    kind = {401: "authentication_error", 403: "permission_error", 404: "not_found_error", 429: "rate_limit_error", 503: "overloaded_error"}.get(status, "invalid_request_error" if status < 500 else "api_error")
                    if status == 400 and message.strip() == CLAUDE_PROMPT_LIMIT_MESSAGE:
                        # Claude Code detects this phrase to trigger reactive compaction.
                        message = "Prompt is too long. " + CLAUDE_PROMPT_LIMIT_MESSAGE
                    if request_id is not None:
                        metric({"event": "upstream_error", "id": request_id, "status": status, "kind": kind})
                    data = error_body(message, kind)
                    headers = exc.headers
                else:
                    status = 400 if isinstance(exc, (ValueError, KeyError, TypeError)) else 502
                    data = error_body(str(exc) if status == 400 or isinstance(exc, protocol.EmptyResponseError) else "Gateway upstream connection failed", "invalid_request_error" if status == 400 else "api_error")
                    headers = {}
                if streaming_started:
                    write_event(data)
                else:
                    self.send_json(status, data, headers)
            finally:
                stop_ping.set()
                if ping_thread:
                    ping_thread.join(timeout=1)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"NeuralDeep gateway: http://127.0.0.1:{port} (direct upstream)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
