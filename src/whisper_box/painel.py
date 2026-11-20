"""Painel local de gravação: API HTTP mínima e arquivos estáticos (somente biblioteca padrão).

O contrato está em docs/painel-api.md. Este módulo nunca registra áudio nem texto de
transcrições e nunca expõe caminhos do host nas respostas.
"""
import json
import mimetypes
import ntpath
import os
import posixpath
import re
import shutil
import signal
import sys
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import jobs
from .config import BoxError, Settings
from .model import read_manifest
from .store import Store

INTERNAL_PORT = 8765
CHUNK_LIMIT = 16 * 1024 * 1024
RECORDING_LIMIT = 2 * 1024 ** 3
JSON_LIMIT = 4096
DRAIN_LIMIT = 1024 * 1024
ID_PATTERN = r"[0-9a-f]{32}"
LANGUAGES = {"pt", "en", "es", "auto"}
EXTENSIONS = {
    "audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "video/ogg": ".ogg",
    "audio/mp4": ".m4a", "video/mp4": ".m4a", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
}
MIME_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".png": "image/png", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}
DOWNLOADS = {"text": ("transcricao.txt", "text/plain; charset=utf-8", ".txt"),
             "srt": ("transcricao.srt", "application/x-subrip", ".srt")}
STATUS_BY_CODE = {
    "worker_unavailable": 503, "model_not_ready": 503, "invalid_language": 400,
    "job_not_found": 404, "input_not_found": 404, "input_changed": 409,
}


def log(event: str, **fields):
    print(json.dumps({"event": event, "timestamp": time.time(), **fields}, ensure_ascii=False),
          file=sys.stderr, flush=True)


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.extra = status, code, extra


def http_status(error: BoxError) -> int:
    return STATUS_BY_CODE.get(error.code, 400 if error.exit_code == 3 else 500)


def extension_for(mime: str):
    return EXTENSIONS.get(str(mime).split(";")[0].strip().lower())


class Gravacoes:
    """Staging das gravações em <inputs>/.gravacoes: <id>.part (+ <id>.meta) até transcrever."""

    def __init__(self, settings: Settings, submit=None):
        self.settings = settings
        self.root = settings.inputs / ".gravacoes"
        self.root.mkdir(parents=True, exist_ok=True)
        self.submit = submit or jobs.submit
        self._locks = {}
        self._guard = threading.Lock()

    # -- caminhos e estado -------------------------------------------------
    def _lock(self, recording_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(recording_id, threading.Lock())

    def _part(self, recording_id): return self.root / (recording_id + ".part")
    def _meta(self, recording_id): return self.root / (recording_id + ".meta")
    def _closed(self, recording_id): return self.root / recording_id

    def _load(self, recording_id: str) -> dict:
        try:
            meta = json.loads(self._meta(recording_id).read_text(encoding="utf-8"))
            return {"mime": str(meta["mime"]), "next": int(meta["next"]), "size": int(meta["size"]),
                    "name": meta.get("name")}
        except (OSError, ValueError, KeyError, TypeError):
            raise HttpError(404, "gravacao_inexistente", "Gravação inexistente.") from None

    def _save(self, recording_id: str, state: dict):
        temporary = self.root / (recording_id + ".meta.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._meta(recording_id))

    # -- operações -----------------------------------------------------------
    def create(self, mime: str) -> str:
        if extension_for(mime) is None:
            raise HttpError(415, "mime_invalido", "Tipo de mídia não suportado.")
        recording_id = uuid.uuid4().hex
        with self._lock(recording_id):
            self._part(recording_id).open("xb").close()
            self._save(recording_id, {"mime": str(mime)[:100], "next": 0, "size": 0, "name": None})
        return recording_id

    def append(self, recording_id: str, seq: int, length: int, stream) -> None:
        with self._lock(recording_id):
            state = self._load(recording_id)
            if self._closed(recording_id).exists():
                raise HttpError(409, "gravacao_fechada", "A gravação já foi enviada para transcrição.")
            if state["next"] > 0 and seq == state["next"] - 1:
                self._drain(stream, length)  # reenvio idempotente do último pedaço
                return
            if seq != state["next"]:
                raise HttpError(409, "sequencia_invalida", "Pedaço fora de ordem.", esperado=state["next"])
            if state["size"] + length > RECORDING_LIMIT:
                raise HttpError(413, "gravacao_grande_demais", "A gravação excede 2 GiB.")
            part = self._part(recording_id)
            try:
                with part.open("r+b") as target:
                    target.truncate(state["size"])  # descarta resto de escrita interrompida
                    target.seek(state["size"])
                    remaining = length
                    while remaining:
                        block = stream.read(min(64 * 1024, remaining))
                        if not block:
                            raise HttpError(400, "corpo_incompleto", "O pedaço chegou incompleto.")
                        target.write(block)
                        remaining -= len(block)
                    target.flush()
                    os.fsync(target.fileno())
            except FileNotFoundError:
                raise HttpError(404, "gravacao_inexistente", "Gravação inexistente.") from None
            except OSError as exc:
                if isinstance(exc, (ConnectionError, TimeoutError)):
                    raise
                raise HttpError(500, "erro_gravacao", "Não foi possível gravar o pedaço.") from exc
            state["next"], state["size"] = seq + 1, state["size"] + length
            self._save(recording_id, state)

    @staticmethod
    def _drain(stream, length):
        while length:
            block = stream.read(min(64 * 1024, length))
            if not block:
                break
            length -= len(block)

    def cancel(self, recording_id: str) -> None:
        with self._lock(recording_id):
            if not (self._part(recording_id).exists() or self._closed(recording_id).exists()
                    or self._meta(recording_id).exists()):
                raise HttpError(404, "gravacao_inexistente", "Gravação inexistente.")
            self._part(recording_id).unlink(missing_ok=True)
            self._meta(recording_id).unlink(missing_ok=True)
            shutil.rmtree(self._closed(recording_id), ignore_errors=True)
        with self._guard:
            self._locks.pop(recording_id, None)

    def transcribe(self, recording_id: str, language: str) -> dict:
        if language not in LANGUAGES:
            raise BoxError("invalid_language", "Use pt, en, es ou auto.", 3)
        with self._lock(recording_id):
            state = self._load(recording_id)
            directory = self._closed(recording_id)
            if state["size"] == 0:
                raise HttpError(400, "gravacao_vazia", "A gravação não tem dados.")
            if state["name"] is None:
                state["name"] = "gravacao-" + datetime.now().strftime("%Y-%m-%d_%H%M") \
                    + extension_for(state["mime"])
                self._save(recording_id, state)
            final = directory / state["name"]
            part = self._part(recording_id)
            if part.exists():
                directory.mkdir(exist_ok=True)
                with part.open("r+b") as stream:
                    stream.truncate(state["size"])
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(part, final)
            elif not final.is_file():
                raise HttpError(404, "gravacao_inexistente", "Gravação inexistente.")
            # Em erro de submit o staging permanece e transcrever pode ser repetido.
            result = self.submit(self.settings, final, language)
            shutil.rmtree(directory, ignore_errors=True)
            self._meta(recording_id).unlink(missing_ok=True)
        with self._guard:
            self._locks.pop(recording_id, None)
        return result


class PainelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, settings: Settings, static_root: Path, public_port: int, submit=None):
        self.settings = settings
        self.static_root = Path(static_root)
        self.public_port = public_port
        self.hosts = {f"127.0.0.1:{public_port}", f"localhost:{public_port}"}
        self.origins = {"http://" + host for host in self.hosts}
        self.gravacoes = Gravacoes(settings, submit)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WhisperBoxPainel"
    sys_version = ""
    timeout = 30

    # -- infraestrutura ------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 - substituído por log JSON próprio
        pass

    def setup(self):
        super().setup()
        self._body_pending = False

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _finish(self, status: int, headers=(), body: bytes = b""):
        self._status = status
        if self._body_pending:
            self.close_connection = True
        self.send_response(status)
        self._security_headers()
        for name, value in headers:
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        if status != 204:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _discard_body(self):
        """Consome corpos pequenos não lidos para a resposta de erro não ser perdida por um reset."""
        if not self._body_pending:
            return
        raw = self.headers.get("Content-Length", "")
        if "Transfer-Encoding" not in self.headers and raw.isdigit() and int(raw) <= DRAIN_LIMIT:
            try:
                Gravacoes._drain(self.rfile, int(raw))
                self._body_pending = False
            except OSError:
                pass

    def _json(self, status: int, payload=None):
        if payload is None:
            return self._finish(status, [("Cache-Control", "no-store")])
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._finish(status, [("Content-Type", "application/json; charset=utf-8"),
                              ("Cache-Control", "no-store")], body)

    def _error(self, status: int, code: str, message: str, **extra):
        self._json(status, {"error": {"code": code, "message": message}, **extra})

    def _length(self, limit: int, required: bool = True):
        if "Transfer-Encoding" in self.headers:
            raise HttpError(411, "length_required", "Use Content-Length.")
        raw = self.headers.get("Content-Length")
        if raw is None:
            if required:
                raise HttpError(411, "length_required", "Content-Length é obrigatório.")
            return 0
        if not raw.isdigit():
            raise HttpError(400, "content_length_invalido", "Content-Length inválido.")
        length = int(raw)
        if length > limit:
            raise HttpError(413, "corpo_grande_demais", "Corpo acima do limite permitido.")
        return length

    def _read_json(self) -> dict:
        length = self._length(JSON_LIMIT, required=False)
        raw = self.rfile.read(length) if length else b""
        self._body_pending = False
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            raise HttpError(400, "json_invalido", "Corpo JSON inválido.") from None
        if not isinstance(data, dict):
            raise HttpError(400, "json_invalido", "O corpo deve ser um objeto JSON.")
        return data

    # -- despacho ------------------------------------------------------------
    def do_GET(self): self._dispatch()
    def do_HEAD(self): self._dispatch()
    def do_POST(self): self._dispatch()
    def do_PUT(self): self._dispatch()
    def do_DELETE(self): self._dispatch()

    def _dispatch(self):
        started = time.monotonic()
        self._status = 0
        route = "-"
        mutating = self.command in {"POST", "PUT", "DELETE"}
        # Requisições com corpo não lido não podem reutilizar a conexão.
        self._body_pending = mutating and (self.headers.get("Content-Length", "0") != "0"
                                           or "Transfer-Encoding" in self.headers)
        try:
            if (self.headers.get("Host") or "").lower() not in self.server.hosts:
                raise HttpError(421, "host_invalido", "Host não permitido.")
            if mutating:
                if self.headers.get("X-Whisper-Box") != "1":
                    raise HttpError(403, "cabecalho_ausente", "Cabeçalho X-Whisper-Box ausente.")
                origin = self.headers.get("Origin")
                if origin is not None and origin not in self.server.origins:
                    raise HttpError(403, "origem_invalida", "Origem não permitida.")
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            if path.startswith("/api/") or path == "/api":
                route = self._api(path)
            elif self.command in {"GET", "HEAD"}:
                route = "estatico"
                self._static(path)
            else:
                raise HttpError(405, "metodo_invalido", "Método não permitido.")
        except HttpError as error:
            self._error(error.status, error.code, str(error), **error.extra)
        except BoxError as error:
            self._error(http_status(error), error.code, str(error))
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception as exc:
            log("painel_erro", route=route, exception_type=type(exc).__name__)
            try:
                self._error(500, "erro_interno", "Erro interno do painel.")
            except OSError:
                self.close_connection = True
        if not (route == "GET /api/saude" and self._status == 200):
            log("painel_requisicao", method=self.command, route=route, status=self._status,
                ms=round((time.monotonic() - started) * 1000))

    def _api(self, path: str) -> str:
        routes = [
            ("GET", r"/api/saude", self._saude),
            ("POST", r"/api/gravacoes", self._criar),
            ("PUT", rf"/api/gravacoes/({ID_PATTERN})/pedacos/(\d{{1,9}})", self._pedaco),
            ("POST", rf"/api/gravacoes/({ID_PATTERN})/transcrever", self._transcrever),
            ("DELETE", rf"/api/gravacoes/({ID_PATTERN})", self._cancelar),
            ("GET", r"/api/transcricoes", self._listar),
            ("GET", rf"/api/transcricoes/({ID_PATTERN})", self._detalhe),
            ("GET", rf"/api/transcricoes/({ID_PATTERN})/arquivos/(text|srt)", self._arquivo),
        ]
        allowed = False
        for method, pattern, handler in routes:
            match = re.fullmatch(pattern, path)
            if not match:
                continue
            if method == self.command or (method == "GET" and self.command == "HEAD"):
                handler(*match.groups())
                return method + " " + re.sub(ID_PATTERN, ":id", path)
            allowed = True
        if allowed:
            raise HttpError(405, "metodo_invalido", "Método não permitido.")
        raise HttpError(404, "rota_inexistente", "Rota inexistente.")

    # -- rotas da API --------------------------------------------------------
    def _saude(self):
        settings = self.server.settings
        try:
            jobs.require_worker(settings)
            worker = True
        except BoxError:
            worker = False
        try:
            read_manifest(settings.models)
            model = True
        except BoxError:
            model = False
        self._json(200, {"painel": "ok", "worker": worker, "modelo": model})

    def _criar(self):
        mime = self._read_json().get("mime")
        if not isinstance(mime, str) or not mime:
            raise HttpError(400, "mime_invalido", "Informe o campo mime.")
        self._json(201, {"id": self.server.gravacoes.create(mime)})

    def _pedaco(self, recording_id: str, seq: str):
        length = self._length(CHUNK_LIMIT)
        if length == 0:
            raise HttpError(400, "pedaco_vazio", "O pedaço está vazio.")
        self.server.gravacoes.append(recording_id, int(seq), length, self.rfile)
        self._body_pending = False
        self._json(204)

    def _transcrever(self, recording_id: str):
        language = self._read_json().get("language") or "auto"
        result = self.server.gravacoes.transcribe(recording_id, language)
        self._json(202, {"job_id": result["job_id"], "status": result["status"],
                         "reused": result["reused"]})

    def _cancelar(self, recording_id: str):
        self.server.gravacoes.cancel(recording_id)
        self._json(204)

    def _pasta(self, job_id: str):
        """Caminho de saida/<job_id> no host (None quando a raiz do host é desconhecida)."""
        root = self.server.settings.host_root
        if not root:
            return None
        join = ntpath.join if "\\" in root or re.match(r"[A-Za-z]:", root) else posixpath.join
        return join(root, "saida", job_id)

    def _summary(self, job: dict) -> dict:
        item = {"job_id": job["id"], "status": job["status"], "progress_seconds": job["progress"],
                "created_at": job["created_at"], "started_at": job["started_at"],
                "finished_at": job["finished_at"], "source_name": job["source_name"]}
        if job["error_code"]:
            item["error"] = {"code": job["error_code"], "message": job["error_message"]}
        if job["status"] == "succeeded":
            item["pasta"] = self._pasta(job["id"])
        return item

    def _listar(self):
        items = Store(self.server.settings.state).list(limit=50)
        self._json(200, {"transcricoes": [self._summary(job) for job in items]})

    def _detalhe(self, job_id: str):
        settings = self.server.settings
        job = Store(settings.state).get(job_id)
        body = jobs.status(settings, job_id)
        body["source_name"] = job["source_name"]
        if job["status"] == "succeeded" and jobs.complete_output(settings, job):
            body["downloads"] = {key: f"/api/transcricoes/{job_id}/arquivos/{key}" for key in DOWNLOADS}
        self._json(200, body)

    def _arquivo(self, job_id: str, kind: str):
        settings = self.server.settings
        job = Store(settings.state).get(job_id)
        if job["status"] != "succeeded" or not jobs.complete_output(settings, job):
            raise HttpError(409, "arquivo_indisponivel", "A transcrição ainda não foi concluída e verificada.")
        filename, content_type, suffix = DOWNLOADS[kind]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(job["source_name"]).stem).strip("._") or job_id
        headers = [("Content-Type", content_type), ("Cache-Control", "no-store"),
                   ("Content-Disposition", f'attachment; filename="{stem[:80]}{suffix}"')]
        self._send_file(settings.outputs / job_id / filename, headers)

    # -- estáticos -----------------------------------------------------------
    def _send_file(self, target: Path, headers):
        try:
            stream = target.open("rb")
        except OSError:
            raise HttpError(404, "nao_encontrado", "Arquivo não encontrado.") from None
        with stream:
            size = os.fstat(stream.fileno()).st_size
            self._status = 200
            if self._body_pending:
                self.close_connection = True
            self.send_response(200)
            self._security_headers()
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(stream, self.wfile, 64 * 1024)

    def _static(self, raw_path: str):
        relative = unquote(raw_path)
        parts = [part for part in relative.split("/") if part]
        if "\x00" in relative or "\\" in relative or any(part.startswith(".") for part in parts):
            raise HttpError(404, "nao_encontrado", "Arquivo não encontrado.")
        root = self.server.static_root.resolve()
        target = (root.joinpath(*parts) if parts else root).resolve()
        if target.is_dir():
            target = target / "index.html"
        if root != target and root not in target.parents:
            raise HttpError(404, "nao_encontrado", "Arquivo não encontrado.")
        content_type = MIME_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        self._send_file(target, [("Content-Type", content_type), ("Cache-Control", "no-cache")])


def serve(settings: Settings):
    settings.initialize()
    static_root = Path(os.getenv("WHISPER_BOX_PAINEL_STATIC", "/srv/painel"))
    public_port = int(os.getenv("WHISPER_BOX_PAINEL_PORT") or INTERNAL_PORT)
    server = PainelServer(("0.0.0.0", INTERNAL_PORT), settings, static_root, public_port)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    thread.start()
    log("painel_ready", port=INTERNAL_PORT, public_port=public_port)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        log("painel_stopped")
