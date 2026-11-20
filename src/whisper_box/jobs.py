import hashlib
import json
import ntpath
import os
import shutil
import time
import uuid
from datetime import datetime, time as day_time, timedelta, timezone
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
            job_id, fingerprint, input_hash, str(target), source.name, config,
            is_valid=lambda job: output_state(settings, job) != "lost",
        )
    except BaseException:
        shutil.rmtree(directory)
        raise
    if reused:
        shutil.rmtree(directory)
    return {"job_id": selected, "status": store.get(selected)["status"], "reused": reused}


def output_state(settings: Settings, job: dict) -> str:
    """'ok', 'lost' (ausente, inválida ou alterada) ou 'unknown' (erro de E/S que não prova perda)."""
    directory = settings.outputs / job["id"]
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["fingerprint"] != job["fingerprint"]:
            return "lost"
        for name in ARTIFACTS.values():
            if sha256_file(directory / name) != manifest["sha256"][name]:
                return "lost"
        return "ok"
    except (FileNotFoundError, NotADirectoryError, ValueError, KeyError, TypeError):
        return "lost"
    except OSError:
        return "unknown"


def complete_output(settings: Settings, job: dict) -> bool:
    return output_state(settings, job) == "ok"


def host_files(settings: Settings, job_id: str) -> dict:
    join = ntpath.join if "\\" in settings.host_root else os.path.join
    return {
        key: join(settings.host_root, "saida", job_id, name)
        if settings.host_root else str(settings.outputs / job_id / name)
        for key, name in ARTIFACTS.items()
    }


def status(settings: Settings, job_id: str, include_files: bool = False) -> dict:
    job = Store(settings.state).get(job_id)
    response = {
        "job_id": job["id"], "status": job["status"], "attempts": job["attempts"],
        "progress_seconds": job["progress"], "created_at": job["created_at"],
        "started_at": job["started_at"], "finished_at": job["finished_at"],
    }
    # Erro anterior (por exemplo, interrupção recuperada) não aparece em job que segue ativo.
    if job["status"] == "failed" and job["error_code"]:
        response["error"] = {"code": job["error_code"], "message": job["error_message"]}
    if include_files and job["status"] == "succeeded":
        if not complete_output(settings, job):
            raise BoxError("output_incomplete", "Os arquivos de saída estão ausentes ou foram alterados. "
                                                "Reenvie a mesma gravação para reprocessar.")
        response["files"] = host_files(settings, job_id)
        response["output_relative"] = f"saida/{job_id}"
    return response


def _iso(epoch, offset_minutes: int):
    if epoch is None:
        return None
    zone = timezone(timedelta(minutes=offset_minutes))
    return datetime.fromtimestamp(epoch, zone).isoformat(timespec="seconds")


def _duration(settings: Settings, job_id: str):
    try:
        value = json.loads((settings.outputs / job_id / ARTIFACTS["metadata"]).read_text(encoding="utf-8"))
        value = value["duration_seconds"]
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def list_jobs(settings: Settings, status: str | None = None, since=None, until=None,
              limit: int = 20, utc_offset_minutes: int = 0) -> dict:
    """Lista trabalhos (mais recentes primeiro). `since` e `until` são datas inclusivas no fuso informado."""
    if not 1 <= limit <= 200:
        raise BoxError("invalid_arguments", "--limit deve estar entre 1 e 200.", 3)
    if not -840 <= utc_offset_minutes <= 840:
        raise BoxError("invalid_arguments", "--utc-offset-minutes deve estar entre -840 e 840.", 3)
    zone = timezone(timedelta(minutes=utc_offset_minutes))

    def midnight(day):
        return datetime.combine(day, day_time(), tzinfo=zone).timestamp()

    rows = Store(settings.state).list(
        limit=limit, status=status,
        since=midnight(since) if since else None,
        until=midnight(until + timedelta(days=1)) if until else None)
    items = []
    for job in rows:
        item = {
            "job_id": job["id"], "source_name": job["source_name"], "status": job["status"],
            "language": json.loads(job["config"]).get("language"),
            "created_at": _iso(job["created_at"], utc_offset_minutes),
            "started_at": _iso(job["started_at"], utc_offset_minutes),
            "finished_at": _iso(job["finished_at"], utc_offset_minutes),
            "duration_seconds": None, "progress_seconds": job["progress"],
        }
        if job["status"] == "succeeded" and complete_output(settings, job):
            item["duration_seconds"] = _duration(settings, job["id"])
            item["files"] = host_files(settings, job["id"])
            item["output_relative"] = f"saida/{job['id']}"
        if job["status"] == "failed" and job["error_code"]:
            item["error"] = {"code": job["error_code"], "message": job["error_message"]}
        items.append(item)
    return {"jobs": items}


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
