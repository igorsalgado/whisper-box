import hashlib
import json
import ntpath
import os
import shutil
import time
import uuid
from pathlib import Path

from .config import BoxError, Settings, effective_config
from .model import read_manifest, sha256_file
from .store import Store

ARTIFACTS = {"text": "transcricao.txt", "srt": "transcricao.srt",
             "segments": "segmentos.jsonl", "metadata": "metadados.json"}


def require_worker(settings: Settings):
    try:
        heartbeat = json.loads((settings.state / "heartbeat.json").read_text())
        if time.time() - heartbeat["timestamp"] > 15:
            raise ValueError("Heartbeat expirado")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BoxError("worker_unavailable", "Worker indisponível. Execute start e consulte os logs.") from exc


def submit(settings: Settings, source: Path, language: str) -> dict:
    settings.initialize()
    manifest = read_manifest(settings.models)
    config = effective_config(manifest["revision"], language)
    require_worker(settings)
    if not source.is_file():
        raise BoxError("input_not_found", "Informe um arquivo de mídia existente.", 3)
    job_id = uuid.uuid4().hex
    directory = settings.inputs / job_id
    directory.mkdir()
    suffix = source.suffix.lower()
    # O nome de arquivo original nunca participa da composição de caminhos internos.
    target = directory / ("source" + (suffix if len(suffix) < 12 else ".media"))
    temporary = directory / "copy.partial"
    try:
        before = source.stat()
        digest = hashlib.sha256()
        with source.open("rb") as original, temporary.open("xb") as copy:
            for block in iter(lambda: original.read(1024 * 1024), b""):
                digest.update(block)
                copy.write(block)
            copy.flush()
            os.fsync(copy.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino):
            raise BoxError("input_changed", "O arquivo mudou durante a cópia. Aguarde o fim da gravação.")
        if temporary.stat().st_size != before.st_size:
            raise BoxError("input_changed", "A cópia da gravação está incompleta.")
        os.replace(temporary, target)
        input_hash = digest.hexdigest()
        fingerprint = hashlib.sha256(
            (input_hash + json.dumps(config, sort_keys=True)).encode()
        ).hexdigest()
        store = Store(settings.state)
        selected, reused = store.enqueue(
            job_id, fingerprint, input_hash, str(target), source.name, config
        )
    except BaseException:
        shutil.rmtree(directory)
        raise
    if reused:
        shutil.rmtree(directory)
    return {"job_id": selected, "status": store.get(selected)["status"], "reused": reused}


def complete_output(settings: Settings, job: dict) -> bool:
    directory = settings.outputs / job["id"]
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["fingerprint"] != job["fingerprint"]:
            return False
        for name in ARTIFACTS.values():
            if sha256_file(directory / name) != manifest["sha256"][name]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def status(settings: Settings, job_id: str, include_files: bool = False) -> dict:
    job = Store(settings.state).get(job_id)
    response = {
        "job_id": job["id"], "status": job["status"], "attempts": job["attempts"],
        "progress_seconds": job["progress"], "created_at": job["created_at"],
        "started_at": job["started_at"], "finished_at": job["finished_at"],
    }
    if job["error_code"]:
        response["error"] = {"code": job["error_code"], "message": job["error_message"]}
    if include_files and job["status"] == "succeeded":
        if not complete_output(settings, job):
            raise BoxError("output_incomplete", "Os arquivos de saída estão ausentes ou foram alterados.")
        relative = f"saida/{job_id}"
        join = ntpath.join if "\\" in settings.host_root else os.path.join
        response["files"] = {
            key: join(settings.host_root, "saida", job_id, name)
            if settings.host_root else str(settings.outputs / job_id / name)
            for key, name in ARTIFACTS.items()
        }
        response["output_relative"] = relative
    return response


def wait(settings: Settings, job_id: str, timeout: int):
    if not 1 <= timeout <= 60:
        raise BoxError("invalid_timeout", "timeout deve estar entre 1 e 60 segundos.", 3)
    deadline = time.monotonic() + timeout
    while True:
        response = status(settings, job_id, include_files=True)
        if response["status"] in {"succeeded", "failed"}:
            return response, 0 if response["status"] == "succeeded" else 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            response["timed_out"] = True
            return response, 2
        time.sleep(min(0.5, remaining))
