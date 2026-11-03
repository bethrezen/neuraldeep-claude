"""Portable, independent MCP stdio adapters for NeuralDeep service APIs.

Only the Python standard library is needed. All requests bypass environment
proxies. No automatic billing fallback or retry of chargeable requests is made.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request
import uuid


GROUPS = ("search", "ocr", "images", "music", "tts", "transcription",
          "diarization", "embeddings", "rerank", "pii", "decisions", "drift",
          "book", "speechcore")
SERVICE_GROUPS = (*GROUPS, "browser")
API = "https://api.neuraldeep.ru"
S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
O = {"type": "object", "additionalProperties": True}
A = {"type": "array", "items": S}


@dataclass(frozen=True)
class Tool:
    group: str
    name: str
    description: str
    method: str
    path: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    files: dict[str, str] = field(default_factory=dict)
    base: str = API
    multipart: bool = False
    binary: bool = False
    timeout: int = 300

    def public(self) -> dict[str, Any]:
        props = dict(self.properties)
        if self.group != "drift":
            props["billing"] = {"type": "string", "enum": ["subscription", "wallet"],
                                "default": "subscription", "description": "Explicit key selection. Wallet charges money; no automatic fallback."}
        props["parameters"] = {**O, "description": "Additional documented API fields; merged with the explicit fields. For GET they are query parameters."}
        if self.multipart or self.files:
            props["idempotency_key"] = {**S, "description": "Optional Idempotency-Key (documented for OCR). Reuse to avoid duplicate OCR charges."}
        return {"name": self.name, "description": self.description,
                "annotations": {"readOnlyHint": self.method == "GET",
                                "destructiveHint": self.method in ("DELETE", "PUT"),
                                "idempotentHint": self.method == "GET", "openWorldHint": True},
                "inputSchema": {"type": "object", "properties": props,
                                "required": list(self.required), "additionalProperties": False}}


def _tools() -> tuple[Tool, ...]:
    tools: list[Tool] = []

    def add(group, name, description, method, path, properties=None, required=(), **kw):
        tools.append(Tool(group, name, description, method, path, properties or {}, tuple(required), **kw))

    add("search", "web_search", "Search the web through NeuralDeep. Returns sources and remaining search quota.", "POST", "/v1/search/web", {"query": S, "limit": I}, ("query",))
    add("search", "read_page", "Read one URL as clean markdown (or return_format=text).", "POST", "/v1/search/read", {"url": S, "return_format": S}, ("url",))
    add("search", "crawl_site", "Crawl multiple pages of a website. Uses the separate crawling quota.", "POST", "/v1/search/crawl", {"url": S, "limit": I}, ("url",))
    add("search", "telegram_search", "Search NeuralDeep's Telegram channel database with hybrid full-text/vector search.", "GET", "/v1/search/tg", {"q": S, "limit": I}, ("q",))

    add("ocr", "ocr_extract", "Upload a local PDF or image for asynchronous OCR (<=50 MB, <=500 pages). Returns job id. Poll ocr_status no faster than once/second, then ocr_result. page_ranges='1-5,8'.", "POST", "/v1/ocr/extract", {"file_path": S, "page_ranges": S}, ("file_path",), files={"file_path": "file"}, multipart=True)
    add("ocr", "ocr_status", "Get OCR job status; polling and result do not spend quota.", "GET", "/v1/ocr/jobs/{job_id}", {"job_id": S}, ("job_id",))
    add("ocr", "ocr_result", "Get completed OCR job as markdown/json/text. Coordinates, if returned, use the page image coordinate system.", "GET", "/v1/ocr/jobs/{job_id}/result", {"job_id": S, "format": {"type": "string", "enum": ["markdown", "json", "text"]}}, ("job_id",))
    add("ocr", "ocr_balance", "Read remaining OCR page balance without creating an OCR job.", "GET", "/v1/ocr/balance")

    add("images", "image_generate", "Create an asynchronous Qwen-Image task: prompt <=4000 chars; options supports width/height or aspect_ratio, negative_prompt, steps(1..50), true_cfg_scale(1..10), seed, num_images(1..4), transparent. Max 1.5 MP. Poll image_status, then image_result.", "POST", "/v1/images/generate", {"prompt": S, "options": O}, ("prompt",))
    # Public docs show images[], but the live FastAPI endpoint requires images
    # (422 missing body.images with images[]; verified 2026-11-02).
    add("images", "image_edit", "Edit 1..10 local images with an instruction. <=25 MB total. options may contain documented image generation settings except size. Poll image_status then image_result.", "POST", "/v1/images/edit", {"image_paths": A, "prompt": S, "options": O}, ("image_paths", "prompt"), files={"image_paths": "images"}, multipart=True)
    for name, path, description in (("image_upscale", "upscale", "Upscale a local image 4x with RealESRGAN."), ("image_remove_background", "background/remove", "Remove the background from a local image."), ("image_enhance", "enhance", "Enhance a local image with FLUX.")):
        add("images", name, description + " Async task; poll image_status then image_result. <=25 MB and 4 MP input.", "POST", "/v1/images/" + path, {"file_path": S}, ("file_path",), files={"file_path": "image"}, multipart=True)
    add("images", "image_avatar", "Create avatar from local photo with gender/style. Async task; poll image_status then image_result.", "POST", "/v1/images/avatar", {"file_path": S, "gender": S, "style": S}, ("file_path", "gender", "style"), files={"file_path": "photo"}, multipart=True)
    add("images", "image_status", "Get task status: queued/processing/finished/failed. Fetch result after finished.", "GET", "/v1/images/tasks/{task_id}", {"task_id": S}, ("task_id",))
    add("images", "image_result", "Download finished image to a local artifact. If HTTP 202 the image is still pending; no file is saved.", "GET", "/v1/images/tasks/{task_id}/result", {"task_id": S}, ("task_id",), binary=True)
    add("images", "image_queue", "Read current image generation queue.", "GET", "/v1/images/queue")

    add("music", "music_generate", "Generate one asynchronous Lyria 3 Pro song. Wallet price per track. prompt describes style; lyrics may contain [verse]/[chorus] or [instrumental]; duration 10..300 seconds is a hint. Poll music_status then music_result. No covers, stems, or batches.", "POST", "/v1/music/generate", {"prompt": S, "lyrics": S, "vocal_language": S, "audio_duration": I, "bpm": N, "key_scale": S, "time_signature": S, "seed": I})
    add("music", "music_status", "Get music task status: queued/running/succeeded/failed.", "GET", "/v1/music/tasks/{task_id}", {"task_id": S}, ("task_id",))
    add("music", "music_result", "Download succeeded music track to local artifact. HTTP 409 means not ready. audio_format supports mp3/wav/wav32/flac/opus/aac.", "GET", "/v1/music/tasks/{task_id}/result", {"task_id": S, "index": I, "audio_format": S}, ("task_id",), binary=True)
    add("music", "music_models", "List available music generation models.", "GET", "/v1/music/models")

    add("tts", "speak", "Synthesize <=5000 characters to local WAV (24kHz mono). Voices: vivian/serena/ono_anna/sohee/dylan/ryan/aiden/uncle_fu. language=Russian uses ESpeech stress correction; '+' before vowel overrides stress. Other languages use Qwen3-TTS. instructions selects emotion/style. Voice cloning unavailable.", "POST", "/v1/audio/speech", {"input": S, "voice": S, "language": S, "instructions": S, "model": S, "response_format": S}, ("input",), binary=True)
    add("tts", "voices", "List available NeuralDeep voices.", "GET", "/v1/audio/voices")
    add("transcription", "transcribe", "Transcribe local audio/video <=25 MB synchronously. model: whisper-1/whisper-podlodka-turbo/gigaam-v3. response_format=json/verbose_json/text/srt/vtt (only whisper-1 supports subtitles). timestamp_granularities[] via parameters needs verbose_json. Server may charge wallet when free subscription quota is exhausted; check limits first.", "POST", "/v1/audio/transcriptions", {"file_path": S, "model": S, "language": S, "prompt": S, "response_format": S, "temperature": N}, ("file_path", "model"), files={"file_path": "file"}, multipart=True)
    add("diarization", "diarize", "Identify speaker turns (not transcript) in local audio <=500 MB/4 hours, <=8 speakers. response_format=json/rttm; min_duration removes short fragments. Charges by rounded-up audio minutes.", "POST", "/v1/audio/diarize", {"file_path": S, "response_format": S, "min_duration": N}, ("file_path",), files={"file_path": "file"}, multipart=True)
    add("embeddings", "embed", "Embed text/string array. Required client prefixes: e5-large query:/passage:, frida search_query:/search_document:, Qwen query='Instruct: <task>\\nQuery: ...'. Server does not add prefixes. Total <=105600 chars; respect each model's context. See /docs/vector.md.", "POST", "/v1/embeddings", {"model": S, "input": {"oneOf": [S, A]}, "dimensions": I, "encoding_format": S}, ("model", "input"))
    add("rerank", "rerank", "Rerank candidate documents against query with bge-reranker or qwen3-reranker-8b. query+documents <=105600 chars, each pair within context. Prefer top 20..100 candidates. Returns relevance scores and indices.", "POST", "/v1/rerank", {"model": S, "query": S, "documents": A, "top_n": I, "return_documents": B}, ("model", "query", "documents"))
    texts = {"text": S, "texts": A}
    add("pii", "anonymize", "Anonymize Russian personal data. Provide text OR texts (<=512 strings). entities optionally selects PII types. Keep returned mapping locally for deanonymize; detection is probabilistic.", "POST", "/v1/pii/anonymize", {**texts, "entities": A})
    add("pii", "deanonymize", "Restore PII placeholders using the exact mapping returned by anonymize. Russian names/locations are inflected in context. Provide text OR texts.", "POST", "/v1/pii/deanonymize", {**texts, "mapping": O}, ("mapping",))
    add("decisions", "decide", "Classify, score or rank without text generation. state is text/JSON. questions maps names to {type,instructions,criteria}. FRIDA types: choice/score/noul/ranking, state<=512 tokens; clef-flash supports choice/score/noul, total<=8192 tokens. <=32 questions/512 options/256KB. Use descriptive criteria.", "POST", "/v1/decisions", {"model": S, "state": {}, "questions": O}, ("state", "questions"))

    for group, path in (("search", "/v1/search/quota"), ("ocr", "/v1/ocr/quota"), ("images", "/v1/images/quota"), ("music", "/v1/music/quota"), ("diarization", "/v1/audio/diarize/quota"), ("pii", "/v1/pii/quota"), ("decisions", "/v1/decisions/quota")):
        add(group, group + "_quota", "Read current " + group + " quota; does not start a task.", "GET", path)
    for group in ("embeddings", "rerank", "transcription", "tts"):
        add(group, group + "_limits", "Read key/model/vector quotas, wallet mode and request limits. Does not consume generation quota.", "GET", "/v1/limits")

    book = "https://neuraldeep.ru"
    add("book", "book_list", "List books available in NeuralDeep's agent/coding knowledge library.", "GET", "/api/v1/books", base=book)
    slug = {"slug": {**S, "default": "agenty-vajbkoding"}}
    add("book", "book_toc", "Read book table of contents. Default slug agenty-vajbkoding.", "GET", "/api/v1/books/{slug}/toc", slug, base=book)
    add("book", "book_chapter", "Read full book chapter by id (e.g. ch12).", "GET", "/api/v1/books/{slug}/chapter/{chapter_id}", {**slug, "chapter_id": S}, ("chapter_id",), base=book)
    add("book", "book_search", "Hybrid search over NeuralDeep agent/coding book. Modes hybrid/fts/vector, limit 1..20. Default slug agenty-vajbkoding.", "GET", "/api/v1/books/{slug}/search", {**slug, "q": S, "mode": {"type": "string", "enum": ["hybrid", "fts", "vector"]}, "limit": I}, ("q",), base=book)

    speech = "https://speechcore.neuraldeep.ru"
    add("speechcore", "speechcore_upload", "Upload local audio/video <=2GB for asynchronous long transcription. Options are URL query parameters. diarize enables speaker separation; exact diarize_speakers_num OR upper bound diarize_max_speakers (1..20), language, hotwords<=500 chars, initial_prompt<=2000 chars. Server can charge wallet beyond subscription quota; check usage first. Poll status then result.", "POST", "/api/upload", {"file_path": S, "diarize": B, "diarize_speakers_num": I, "diarize_max_speakers": I, "language": S, "hotwords": S, "initial_prompt": S}, ("file_path",), base=speech, multipart=True, files={"file_path": "file"}, query=("diarize", "diarize_speakers_num", "diarize_max_speakers", "language", "hotwords", "initial_prompt"), timeout=1800)
    for name, suffix, description in (("status", "/status", "Read transcription status; wait until completed or failed."), ("result", "", "Read completed transcription segments, timestamps, speaker IDs, detected language and duration."), ("markdown", "/markdown", "Read completed transcription as markdown with timestamps."), ("speakers", "/speakers", "Read speaker counts and speaking times; min_seconds defaults to 10.")):
        props = {"task_id": S}
        if name == "speakers": props["min_seconds"] = N
        add("speechcore", "speechcore_" + name, description, "GET", "/api/transcriptions/{task_id}" + suffix, props, ("task_id",), base=speech)
    add("speechcore", "speechcore_list", "List own SpeechCore transcriptions.", "GET", "/api/transcriptions", {"limit": I}, base=speech)
    add("speechcore", "speechcore_usage", "Read daily transcription quota and remaining allowance. Polling and results do not consume upload quota.", "GET", "/api/usage", base=speech)
    add("speechcore", "speechcore_export", "Export a completed SpeechCore transcription or original uploaded file. These authenticated paths are published in the completed transcription's links object. Formats: original/json/txt/srt/vtt/tsv/docx/pdf. Binary/text exports are saved as local artifacts; JSON is returned directly.", "GET", "/api/files/{format}/{task_id}", {"task_id": S, "format": {"type": "string", "enum": ["original", "json", "txt", "srt", "vtt", "tsv", "docx", "pdf"]}}, ("task_id", "format"), base=speech, binary=True)

    drift = "https://drift.neuraldeep.ru"
    add("drift", "drift_ask", "Ask the paid Drift agent (separate NEURALDEEP_DRIFT_TOKEN=dft_* required). Send only the latest prompt; Drift maintains history itself. May use remote tools. Additional caller tools/skills/mcp_servers and return-to-caller payloads through parameters.", "POST", "/v1/chat/completions", {"prompt": S, "model": S, "conversation_id": I}, ("prompt",), base=drift, timeout=1800)
    add("drift", "drift_conversations", "List own Drift conversations.", "GET", "/v1/conversations", base=drift)
    add("drift", "drift_create_conversation", "Create a separate Drift conversation.", "POST", "/v1/conversations", {"title": S}, ("title",), base=drift)
    add("drift", "drift_delete_conversation", "Permanently delete a Drift conversation. Use only on explicit user request.", "DELETE", "/v1/conversations/{conversation_id}", {"conversation_id": I}, ("conversation_id",), base=drift)
    add("drift", "drift_history", "Read conversation history with source labels.", "GET", "/v1/history", {"conversation_id": I, "limit": I}, base=drift)
    add("drift", "drift_upload", "Upload local file to Drift workspace (<=20MB/file, <=8 files). Drift previews PDF/XLSX/CSV/TXT/JSON/MD/DOCX.", "POST", "/v1/files/upload", {"file_paths": A}, ("file_paths",), base=drift, multipart=True, files={"file_paths": "file"})
    add("drift", "drift_tasks", "List scheduled Drift tasks.", "GET", "/v1/tasks", base=drift)
    add("drift", "drift_create_task", "Create paid Drift cron/once task. Only when user explicitly requests scheduling. schedule is 5-field cron.", "POST", "/v1/tasks", {"title": S, "schedule": S, "prompt": S, "active": B}, ("title", "schedule", "prompt"), base=drift)
    add("drift", "drift_run_task", "Run an existing Drift task now; invokes paid agent.", "POST", "/v1/tasks/{task_id}/run", {"task_id": S}, ("task_id",), base=drift)
    add("drift", "drift_delete_task", "Delete a scheduled Drift task when requested by user.", "DELETE", "/v1/tasks/{task_id}", {"task_id": S}, ("task_id",), base=drift)
    add("drift", "drift_memory", "Read Drift persistent memory.", "GET", "/v1/memory", base=drift)
    add("drift", "drift_replace_memory", "Replace the ENTIRE Drift memory file. Read current memory first and preserve wanted contents; only write memory on user instruction.", "PUT", "/v1/memory", {"content": S}, ("content",), base=drift)
    return tuple(tools)


TOOLS = _tools()
TOOL_BY_NAME = {t.name: t for t in TOOLS}


def load_env(root: Path) -> dict[str, str]:
    """Use the same literal dotenv parser as model routing, also as a script."""
    if not __package__:
        parent = str(Path(__file__).resolve().parent.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
    from neuraldeep_claude.config import load_env as read_dotenv
    return read_dotenv(root)


def service_state(root: Path) -> dict[str, bool]:
    path = root / ".local/services.json"
    state = {group: True for group in SERVICE_GROUPS}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and "enabled" in saved:
            saved = saved["enabled"]
        if isinstance(saved, list):
            state = {group: group in saved for group in SERVICE_GROUPS}
        elif isinstance(saved, dict):
            state.update({key: bool(value) for key, value in saved.items() if key in SERVICE_GROUPS})
    return state


def set_services(root: Path, names: Iterable[str], enabled: bool) -> dict[str, bool]:
    state = service_state(root)
    for name in names:
        if name not in SERVICE_GROUPS:
            raise ValueError("Unknown service: " + name)
        state[name] = enabled
    directory = root / ".local"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "services.json"
    temp = directory / ("services-" + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps({"enabled": state}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    return state


def tool_state(root: Path) -> dict[str, bool]:
    """Per-operation switches; portable defaults plus explicit local choices."""
    state = {name: True for name in TOOL_BY_NAME}
    policy = root / "config/service-policy.json"
    if policy.exists():
        data = json.loads(policy.read_text(encoding="utf-8"))
        for name in data.get("disabled_tools", {}):
            if name in state:
                state[name] = False
    local = root / ".local/service-tools.json"
    if local.exists():
        data = json.loads(local.read_text(encoding="utf-8"))
        state.update({name: bool(enabled) for name, enabled in data.get("enabled", {}).items() if name in state})
    return state


def set_tools(root: Path, names: Iterable[str], enabled: bool) -> dict[str, bool]:
    path = root / ".local/service-tools.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"enabled": {}}
    for name in names:
        if name not in TOOL_BY_NAME:
            raise ValueError("Unknown tool: " + name)
        data.setdefault("enabled", {})[name] = enabled
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("service-tools-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return tool_state(root)


class ServiceError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ServiceError("Unexpected API redirect rejected; credentials were not forwarded.")


def _form_value(value: Any) -> str:
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False)
    return str(value)


def multipart_body(fields: dict[str, Any], files: list[tuple[str, Path]], boundary: str):
    """Return (iterable, exact length), streaming large files in bounded chunks."""
    parts: list[bytes | Path] = []
    for key, value in fields.items():
        values = value if isinstance(value, list) and key.endswith("[]") else [value]
        for v in values:
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n' + _form_value(v) + "\r\n").encode("utf-8"))
    for key, path in files:
        if not path.is_file():
            raise ServiceError("Local upload file does not exist: " + str(path))
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.extend([(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n').encode("utf-8"), path, b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    size = sum(p.stat().st_size if isinstance(p, Path) else len(p) for p in parts)

    def chunks():
        for part in parts:
            if isinstance(part, Path):
                with part.open("rb") as f:
                    while chunk := f.read(1024 * 1024):
                        yield chunk
            else:
                yield part
    return chunks(), size


def _redact(text: str, env: dict[str, str]) -> str:
    for key, value in env.items():
        if value and ("KEY" in key.upper() or "TOKEN" in key.upper()) and len(value) >= 8:
            text = text.replace(value, "[REDACTED]")
    return text


def call_tool(root: Path, group: str, name: str, arguments: dict[str, Any]) -> Any:
    if group not in GROUPS or not service_state(root).get(group):
        raise ServiceError("Service is disabled: " + group)
    tool = TOOL_BY_NAME.get(name)
    if tool is None or tool.group != group:
        raise ServiceError("Unknown tool in service " + group + ": " + name)
    if not tool_state(root).get(name, False):
        raise ServiceError("Tool is disabled: " + name)
    args = dict(arguments)
    for required in tool.required:
        if required not in args:
            raise ServiceError("Missing required argument: " + required)
    parameters = args.pop("parameters", {})
    if not isinstance(parameters, dict):
        raise ServiceError("parameters must be a JSON object")
    billing = args.pop("billing", "subscription")
    if billing not in ("subscription", "wallet"):
        raise ServiceError("billing must be subscription or wallet")
    env = load_env(root)
    secret_name = "NEURALDEEP_DRIFT_TOKEN" if group == "drift" else "NEURALDEEP_API_KEY_" + billing.upper()
    key = env.get(secret_name, "")
    if not key:
        raise ServiceError("Missing " + secret_name + " in " + str(root / ".env"))
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json, */*", "User-Agent": "neuraldeep-claude-services/1"}
    idem = args.pop("idempotency_key", None)
    if idem:
        if "\r" in idem or "\n" in idem: raise ServiceError("Invalid idempotency key")
        headers["Idempotency-Key"] = idem
    path = tool.path
    for placeholder in re.findall(r"\{(\w+)\}", path):
        value = args.pop(placeholder, "agenty-vajbkoding" if placeholder == "slug" else None)
        if value is None: raise ServiceError("Missing path parameter: " + placeholder)
        path = path.replace("{" + placeholder + "}", urllib.parse.quote(str(value), safe=""))
    files = []
    for arg_name, form_name in tool.files.items():
        values = args.pop(arg_name, [])
        if not isinstance(values, list): values = [values]
        for value in values:
            p = Path(value).expanduser()
            if not p.is_absolute(): p = root / p
            files.append((form_name, p))
    body = {**parameters, **args}
    query = {}
    if tool.method == "GET": query, body = body, {}
    else:
        for field_name in tool.query:
            if field_name in body: query[field_name] = body.pop(field_name)
    if name == "speechcore_upload":
        # Every upload option goes in the URL, including future documented options.
        query.update(body)
        body = {}
    if name == "drift_ask":
        prompt = body.pop("prompt")
        body["messages"] = [{"role": "user", "content": prompt}]
        body["stream"] = False
    query_string = urllib.parse.urlencode({k: _form_value(v) for k, v in query.items()}, doseq=False)
    url = tool.base + path + (("?" + query_string) if query_string else "")
    data = None
    if tool.multipart:
        boundary = "neuraldeep-" + uuid.uuid4().hex
        data, length = multipart_body(body, files, boundary)
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        headers["Content-Length"] = str(length)
    elif tool.method in ("POST", "PUT", "PATCH"):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=tool.method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=tool.timeout) as response:
            status = response.status
            mime = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].lower()
            if status == 202:
                return {"status": "pending", "http_status": status, "message": "Result is not ready; poll status before requesting again."}
            if mime == "application/json" or mime.endswith("+json"):
                raw = response.read()
                return json.loads(raw) if raw else {"http_status": status}
            if not tool.binary and (mime.startswith("text/") or mime in ("application/xml", "application/javascript")):
                return {"text": response.read().decode("utf-8", errors="replace"), "mime_type": mime}
            directory = root / ".local/artifacts"
            directory.mkdir(parents=True, exist_ok=True)
            extension = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, mimetypes.guess_extension(mime) or ".bin")
            if name == "speechcore_export" and arguments.get("format") in ("txt", "srt", "vtt", "tsv", "docx", "pdf"):
                extension = "." + arguments["format"]
            target = directory / (name + "-" + uuid.uuid4().hex + extension)
            partial = target.with_suffix(target.suffix + ".partial")
            total = 0
            try:
                with partial.open("wb") as f:
                    while chunk := response.read(1024 * 1024):
                        f.write(chunk)
                        total += len(chunk)
                partial.replace(target)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            return {"path": str(target.resolve()), "mime_type": mime, "bytes": total, "http_status": status,
                    "engine": response.headers.get("X-TTS-Engine"), "voice": response.headers.get("X-TTS-Voice")}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:12000]
        raise ServiceError(_redact(f"NeuralDeep HTTP {exc.code}: {detail}; Retry-After={exc.headers.get('Retry-After', '')}", env)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ServiceError(_redact("Direct NeuralDeep request failed: " + str(exc), env)) from None


class MCPServer:
    """Line-delimited MCP JSON-RPC. Concurrent calls use independent requests."""
    def __init__(self, root: Path, group: str):
        self.root, self.group = root, group

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if "id" not in request:
            return None
        result = None
        error = None
        params = request.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                      "serverInfo": {"name": "neuraldeep-" + self.group, "version": "1.0.0"},
                      "instructions": "Tools access NeuralDeep directly, without environment proxies. Billing defaults to subscription; wallet must be explicit. Async tools return ids: poll status, then fetch result with the same billing key. No automatic retries of paid operations. Read tool descriptions for model-specific constraints."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            enabled = service_state(self.root).get(self.group, False)
            switches = tool_state(self.root)
            result = {"tools": [tool.public() for tool in TOOLS if tool.group == self.group and switches[tool.name]] if enabled else []}
        elif method == "tools/call":
            try:
                value = call_tool(self.root, self.group, params["name"], params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
            except Exception as exc:
                result = {"isError": True, "content": [{"type": "text", "text": _redact(str(exc), load_env(self.root))}]}
        else:
            error = {"code": -32601, "message": "Method not found: " + str(method)}
        return {"jsonrpc": "2.0", "id": request_id, **({"error": error} if error else {"result": result})}

    def run(self, stdin=None, stdout=None):
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        lock = threading.Lock()

        def respond(request):
            response = self.handle(request)
            if response is not None:
                with lock:
                    stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    stdout.flush()

        with ThreadPoolExecutor(max_workers=64, thread_name_prefix="neuraldeep-mcp") as pool:
            for line in stdin:
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict): raise ValueError("JSON-RPC object required")
                    # Initialization/list stay ordered; calls can proceed concurrently.
                    if request.get("method") == "tools/call": pool.submit(respond, request)
                    else: respond(request)
                except (ValueError, TypeError) as exc:
                    with lock:
                        stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
                        stdout.flush()


def mcp_config(root: Path, python: str | None = None) -> dict[str, Any]:
    """Config fragment: absolute entrypoint makes MCP independent of caller cwd."""
    script = str(Path(__file__).resolve())
    state = service_state(root)
    servers = {"neuraldeep-" + group: {"command": python or sys.executable,
            "args": [script, "--root", str(root.resolve()), "mcp", group]}
            for group, enabled in state.items() if enabled and group in GROUPS}
    if state.get("browser"):
        from neuraldeep_claude.local_browser import mcp_command
        servers["local-browser"] = mcp_command(root, python=python)
    return {"mcpServers": servers}


READ_ONLY_PROBES = (("search", "search_quota"), ("ocr", "ocr_quota"),
    ("images", "images_quota"), ("music", "music_quota"), ("tts", "voices"),
    ("transcription", "transcription_limits"), ("diarization", "diarization_quota"),
    ("embeddings", "embeddings_limits"), ("rerank", "rerank_limits"),
    ("pii", "pii_quota"), ("decisions", "decisions_quota"),
    ("book", "book_list"), ("speechcore", "speechcore_usage"))


def probe_services(root: Path, billing="subscription") -> dict[str, Any]:
    """Read-only live metadata checks, never an inference/creation endpoint."""
    report: dict[str, Any] = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "billing": billing, "scope": "read-only metadata/quota; does not prove charged operations",
        "direct_no_proxy": True, "probes": []}
    for group, name in READ_ONLY_PROBES:
        entry: dict[str, Any] = {"group": group, "tool": name}
        if not service_state(root)[group]:
            entry["status"] = "disabled"
        else:
            try:
                result = call_tool(root, group, name, {"billing": billing})
                entry.update(status="pass", response_keys=list(result) if isinstance(result, dict) else None)
            except Exception as exc:
                entry.update(status="fail", error=_redact(str(exc), load_env(root)))
        report["probes"].append(entry)
    drift_state = "not_configured" if not load_env(root).get("NEURALDEEP_DRIFT_TOKEN") else "not_probed"
    report["probes"].append({"group": "drift", "status": drift_state,
        "reason": "Separate dft_* token and paid Drift subscription required; no agent action invoked"})
    directory = root / ".local"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "service-probes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _smoke_pdf(path: Path):
    """A one-page ASCII PDF fixture, without third-party document libraries."""
    content = b"BT /F1 24 Tf 50 740 Td (NEURALDEEP SERVICE TEST) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)


def smoke_services(root: Path, billing="subscription", groups=None, execute=False,
                   audio_path=None, wait_seconds=600) -> dict[str, Any]:
    """Opt-in functional smoke. No live call at all without execute=True.

    The report states transport/basic response checks, not universal model
    quality or service completeness. Submitting a job is never retried.
    """
    selected = list(GROUPS if not groups or "all" in groups else groups)
    if any(group not in GROUPS for group in selected): raise ServiceError("Unknown smoke group")
    plan = {"billing": billing, "groups": selected, "chargeable": True,
            "server_wallet_overage_possible": ["transcription", "speechcore"],
            "audio_prerequisite": "For audio groups without --audio-path, one TTS call creates a fixture.",
            "execute": execute}
    if not execute:
        return {"plan": plan, "message": "Plan only: no requests made. Add --execute to authorize quota-consuming/paid operations."}
    artifacts = root / ".local/artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "plan": plan, "scope": "functional smoke with basic response/shape checks; no blanket quality guarantee", "checks": []}
    report_path = root / ".local/service-smoke.json"

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def invoke(group, name, args=None):
        args = dict(args or {})
        if group != "drift": args["billing"] = billing
        result = call_tool(root, group, name, args)
        report["checks"].append({"group": group, "tool": name, "status": "response_received", "response": result})
        save()
        return result

    def poll(group, tool, id_name, ident, terminal):
        deadline = time.monotonic() + wait_seconds
        while True:
            status = invoke(group, tool, {id_name: ident})
            value = status.get("status") if isinstance(status, dict) else None
            if value in terminal:
                if value == "failed": raise ServiceError("Async job failed: " + json.dumps(status, ensure_ascii=False))
                return status
            if time.monotonic() >= deadline:
                raise ServiceError("Async wait timed out; job was preserved. Resume polling id=" + str(ident))
            time.sleep(2)

    wav = Path(audio_path).expanduser().resolve() if audio_path else None
    if wav is None and any(group in selected for group in ("transcription", "diarization", "speechcore")):
        try:
            audio = invoke("tts", "speak", {"input": "Проверка сервиса Нейрал Дип. Это короткая тестовая запись для распознавания речи и определения спикеров.", "language": "Russian", "voice": "serena"})
            wav = Path(audio["path"])
        except Exception as exc:
            report["checks"].append({"group": "tts", "status": "fail", "phase": "audio_prerequisite", "error": _redact(str(exc), load_env(root))})
            save()
    for group in selected:
        if not service_state(root).get(group):
            report["checks"].append({"group": group, "status": "disabled"})
            save()
            continue
        try:
            if group == "search":
                result = invoke(group, "web_search", {"query": "NeuralDeep API документация", "limit": 1})
                if not isinstance(result, dict): raise ServiceError("Expected JSON search response")
            elif group == "ocr":
                pdf = artifacts / "service-smoke.pdf"
                _smoke_pdf(pdf)
                created = invoke(group, "ocr_extract", {"file_path": str(pdf), "idempotency_key": "smoke-" + uuid.uuid4().hex})
                ident = created["id"]
                poll(group, "ocr_status", "job_id", ident, ("completed", "failed"))
                result = invoke(group, "ocr_result", {"job_id": ident, "format": "markdown"})
                if "NEURALDEEP" not in json.dumps(result, ensure_ascii=False).upper(): raise ServiceError("OCR result did not contain the known fixture text")
            elif group == "images":
                created = invoke(group, "image_generate", {"prompt": "Один синий круг на белом фоне", "options": {"width": 512, "height": 512}})
                ident = created["task_uid"]
                poll(group, "image_status", "task_id", ident, ("finished", "failed"))
                result = invoke(group, "image_result", {"task_id": ident})
                if not result.get("bytes"): raise ServiceError("Empty image artifact")
            elif group == "music":
                created = invoke(group, "music_generate", {"prompt": "Short calm instrumental piano service test", "lyrics": "[instrumental]", "audio_duration": 10})
                ident = created["task_id"]
                poll(group, "music_status", "task_id", ident, ("succeeded", "failed"))
                result = invoke(group, "music_result", {"task_id": ident, "index": 0})
                if not result.get("bytes"): raise ServiceError("Empty music artifact")
            elif group == "tts":
                result = invoke(group, "speak", {"input": "Проверка сервиса Нейрал Дип.", "language": "Russian", "voice": "serena"})
                if not result.get("bytes"): raise ServiceError("Empty speech artifact")
            elif group in ("transcription", "diarization", "speechcore"):
                if wav is None: raise ServiceError("Audio fixture unavailable; provide --audio-path or enable working TTS")
                if group == "transcription":
                    result = invoke(group, "transcribe", {"file_path": str(wav), "model": "whisper-1", "language": "ru"})
                    if not result.get("text"): raise ServiceError("Empty transcript for known speech fixture")
                elif group == "diarization":
                    result = invoke(group, "diarize", {"file_path": str(wav)})
                    if "segments" not in result: raise ServiceError("Missing diarization segments field")
                else:
                    created = invoke(group, "speechcore_upload", {"file_path": str(wav), "diarize": True, "language": "ru"})
                    ident = created["task_id"]
                    poll(group, "speechcore_status", "task_id", ident, ("completed", "failed"))
                    result = invoke(group, "speechcore_result", {"task_id": ident})
                    if not isinstance(result, dict): raise ServiceError("Expected JSON SpeechCore transcript")
            elif group == "embeddings":
                result = invoke(group, "embed", {"model": "bge-m3", "input": "NeuralDeep service test"})
                if not result.get("data", [{}])[0].get("embedding"): raise ServiceError("Missing embedding vector")
            elif group == "rerank":
                result = invoke(group, "rerank", {"model": "bge-reranker", "query": "модель языка", "documents": ["Большая языковая модель", "Рецепт блинов"]})
                if not result.get("results"): raise ServiceError("Missing rerank scores")
            elif group == "pii":
                masked = invoke(group, "anonymize", {"text": "Иван Петров, +79161234567"})
                if "mapping" not in masked: raise ServiceError("Missing PII mapping")
                result = invoke(group, "deanonymize", {"text": masked["anonymized"], "mapping": masked["mapping"]})
                if "deanonymized" not in result: raise ServiceError("Missing deanonymized text")
            elif group == "decisions":
                result = invoke(group, "decide", {"model": "frida-decisions", "state": "Не приходит код входа", "questions": {"topic": {"type": "choice", "instructions": "Выбери тему обращения", "criteria": {"login": "вход, коды, пароль", "delivery": "доставка заказа"}}}})
                if not result.get("answers"): raise ServiceError("Missing decision answers")
            elif group == "book":
                result = invoke(group, "book_toc")
                if not result: raise ServiceError("Empty book table of contents")
            elif group == "drift":
                if not load_env(root).get("NEURALDEEP_DRIFT_TOKEN"):
                    report["checks"].append({"group": group, "status": "not_configured", "reason": "NEURALDEEP_DRIFT_TOKEN required"})
                    save()
                    continue
                result = invoke(group, "drift_ask", {"prompt": "Ответь только NEURALDEEP_DRIFT_OK. Не используй инструменты и не совершай никаких других действий."})
                if not result.get("choices"): raise ServiceError("Missing Drift agent completion")
            report["checks"].append({"group": group, "status": "pass", "check": "transport_and_basic_response_shape"})
        except Exception as exc:
            report["checks"].append({"group": group, "status": "fail", "error": _redact(str(exc), load_env(root))})
        save()
    return report


def main(argv=None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept --root in either position, including the parent's documented form.
    root_default = Path(__file__).resolve().parents[1]
    if "--root" in argv:
        pos = argv.index("--root")
        if pos + 1 >= len(argv): raise SystemExit("--root needs a directory")
        root_default = Path(argv[pos + 1]).expanduser().resolve()
        del argv[pos:pos + 2]
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for action in ("enable", "disable"):
        sub.add_parser(action).add_argument("names", choices=(*SERVICE_GROUPS, "all"), nargs="+")
    sub.add_parser("mcp").add_argument("name", choices=GROUPS)
    sub.add_parser("config")
    tools = sub.add_parser("tools", help="List or toggle individual service operations")
    tools.add_argument("operation", choices=("list", "enable", "disable"))
    tools.add_argument("names", choices=tuple(TOOL_BY_NAME), nargs="*")
    probe = sub.add_parser("probe", help="Read-only live quota/metadata checks")
    probe.add_argument("--billing", choices=("subscription", "wallet"), default="subscription")
    smoke = sub.add_parser("smoke", help="Plan or explicitly execute quota-consuming service smoke tests")
    smoke.add_argument("--billing", choices=("subscription", "wallet"), default="subscription")
    smoke.add_argument("--groups", choices=(*GROUPS, "all"), nargs="+", default=["all"])
    smoke.add_argument("--execute", action="store_true")
    smoke.add_argument("--audio-path")
    smoke.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    if args.action == "mcp":
        MCPServer(root_default, args.name).run()
    elif args.action == "config":
        print(json.dumps(mcp_config(root_default), ensure_ascii=False, indent=2))
    elif args.action == "tools":
        if args.operation != "list":
            if not args.names:
                parser.error("tools enable/disable requires at least one operation name")
            set_tools(root_default, args.names, args.operation == "enable")
        for name, enabled in tool_state(root_default).items():
            print(f"{name}: {'enabled' if enabled else 'disabled'}")
    elif args.action == "probe":
        print(json.dumps(probe_services(root_default, args.billing), ensure_ascii=False, indent=2))
    elif args.action == "smoke":
        print(json.dumps(smoke_services(root_default, args.billing, args.groups, args.execute,
                                       args.audio_path, args.wait_seconds), ensure_ascii=False, indent=2))
    else:
        if args.action in ("enable", "disable"):
            names = SERVICE_GROUPS if "all" in args.names else args.names
            set_services(root_default, names, args.action == "enable")
        env = load_env(root_default)
        for group, enabled in service_state(root_default).items():
            suffix = " (requires NEURALDEEP_DRIFT_TOKEN)" if group == "drift" and not env.get("NEURALDEEP_DRIFT_TOKEN") else ""
            if group == "browser":
                suffix = " (local Playwright MCP; independent of NeuralDeep billing)"
            print(f"{group}: {'enabled' if enabled else 'disabled'}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
