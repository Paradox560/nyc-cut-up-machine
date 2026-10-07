"""Local web application with same-origin mutations and server-side credentials."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import unquote, urlparse

from .composer import compose
from .config import ROOT, load_config
from .demo import demo_sources
from .http_client import ProviderError
from .providers import ElasticClient, MistralClient
from .provenance import plain_text, validate_source
from .store import CorpusStore


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, project_root: Path = ROOT, demo: bool = False):
        self.project_root = project_root
        self.force_demo = demo
        self.work_slot = BoundedSemaphore(1)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "CutUp/0.1"

    def log_message(self, fmt, *args):
        # Do not log prompts, source text, query parameters, or credentials.
        pass

    def headers_for(self, status: int, content_type: str, size: int):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https://nycrecords.access.preservica.com data: blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers_for(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def checked_origin(self):
        host = self.headers.get("Host", "")
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in expected:
            raise ProviderError("Use this application on localhost.", status=403, code="invalid_host")
        origin = self.headers.get("Origin")
        if (origin and origin != "http://" + host) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ProviderError("Cross-origin requests are not allowed.", status=403, code="invalid_origin")

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ProviderError("Send an application/json body.", status=415, code="invalid_content_type")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request length.") from None
        if not 1 <= length <= 65536:
            raise ProviderError("Request body must be between 1 byte and 64 KB.", status=413)
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise ValueError("Request body must be valid JSON.") from None
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            self.checked_origin()
            config = load_config(self.server.project_root)
            store = CorpusStore(config.data_dir)
            demo = self.server.force_demo or not config.configured
            path = urlparse(self.path).path
            if method == "GET" and path == "/api/status":
                corpus = store.all()
                return self.json({"mode": "demo" if demo else "live",
                    "configured": {"mistral": bool(config.mistral_api_key),
                                   "elasticsearch": bool(config.elasticsearch_url and config.elasticsearch_api_key)},
                    "corpus_count": len(corpus), "reviewed_count": sum(s["reviewed"] for s in corpus),
                    "models": {"chat": config.chat_model, "ocr": config.ocr_model, "embed": config.embed_model},
                    "voice_enabled": bool(config.voice_id and config.mistral_api_key and not demo)})
            if method == "GET" and path == "/api/sources":
                return self.json({"sources": demo_sources() if demo else store.all()})
            if method == "POST":
                payload = self.read_json()
                if path not in {"/api/compose", "/api/sources/review", "/api/speech", "/api/check"}:
                    return self.json({"error": "Endpoint not found.", "code": "not_found"}, 404)
                if not self.server.work_slot.acquire(blocking=False):
                    return self.json({"error": "Another request is running. Please wait for it to finish.", "code": "busy"}, 409)
                try:
                    if path == "/api/compose":
                        if not isinstance(payload.get("include_unreviewed", False), bool):
                            raise ValueError("include_unreviewed must be a boolean.")
                        return self.json(compose(config, payload.get("prompt"), payload.get("form", "poem"),
                            demo=demo, include_unreviewed=payload.get("include_unreviewed", False)))
                    if path == "/api/check":
                        return self.json({"mistral": MistralClient(config).check(), "elasticsearch": ElasticClient(config).check()})
                    if path == "/api/sources/review":
                        if not isinstance(payload.get("id"), str) or not payload["id"]:
                            raise ValueError("A source id is required.")
                        source = store.get(payload.get("id"))
                        if source is None:
                            raise ProviderError("Archive source not found.", status=404, code="not_found")
                        if not isinstance(payload.get("reviewed"), bool):
                            raise ValueError("reviewed must be true or false.")
                        source.setdefault("ocr_original", source["ocr_text"])
                        if "ocr_text" in payload:
                            source["ocr_text"] = payload["ocr_text"]
                        source["reviewed"] = payload["reviewed"]
                        source["reviewed_at"] = datetime.now(timezone.utc).isoformat() if source["reviewed"] else None
                        source = validate_source(source)
                        if config.configured:
                            ElasticClient(config).index_source(source)
                        store.upsert(source)
                        return self.json({"source": source})
                    if path == "/api/speech":
                        identifier = payload.get("composition_id")
                        if not isinstance(identifier, str):
                            raise ValueError("A composition_id is required.")
                        result = store.get_composition(identifier)
                        if result is None:
                            raise ProviderError("Composition not found.", status=404, code="not_found")
                        if result.get("mode") != "live":
                            raise ProviderError("Speech is available for live archival compositions.", status=409)
                        audio = MistralClient(config).speech(plain_text(result["lines"]))
                        self.headers_for(200, "audio/mpeg", len(audio))
                        return self.wfile.write(audio)
                finally:
                    self.server.work_slot.release()
            if method == "GET" and not path.startswith("/api/"):
                if path.startswith("/archive/"):
                    root = (config.data_dir / "archive").resolve()
                    file = (root / unquote(path.removeprefix("/archive/"))).resolve()
                    extensions = {".jpg", ".jpeg", ".png"}
                else:
                    root = (config.project_root / "web").resolve()
                    file = (root / unquote(path.lstrip("/") or "index.html")).resolve()
                    extensions = {".html", ".css", ".js", ".svg"}
                if file.is_relative_to(root) and file.is_file() and file.suffix.lower() in extensions:
                    data = file.read_bytes()
                    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    self.headers_for(200, mime, len(data))
                    return self.wfile.write(data)
            self.json({"error": "Not found.", "code": "not_found"}, 404)
        except ProviderError as exc:
            self.json({"error": str(exc), "code": exc.code}, exc.status)
        except ValueError as exc:
            self.json({"error": str(exc), "code": "invalid_request"}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json({"error": "The request could not be completed. Check local data and retry.", "code": "internal_error"}, 500)


def serve(port: int = 8765, *, demo: bool = False):
    server = AppServer(("127.0.0.1", port), demo=demo)
    print(f"NYC Cut-Up Machine: http://127.0.0.1:{server.server_port}", flush=True)
    print("Mode: explicit synthetic demo" if demo else "Mode: live when credentials are configured", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
