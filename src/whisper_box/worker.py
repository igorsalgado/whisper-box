import fcntl
import json
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import BoxError, Settings, cpu_threads, runtime_config, stall_seconds
from .jobs import complete_output
from .model import read_manifest
from .retention import (apply_input_retention, clean_partial, parse_policy, retention_start,
                        sweep_inputs)
from .store import Store


def log(event: str, **fields):
    print(json.dumps({"event": event, "timestamp": time.time(), **fields}, ensure_ascii=False),
          file=sys.stderr, flush=True)


@contextmanager
def worker_lock(settings: Settings):
    settings.state.mkdir(parents=True, exist_ok=True)
    with (settings.state / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BoxError("worker_already_running", "Já existe um worker usando este estado.") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def peak_memory_bytes():
    """Pico de memória do cgroup do container desde o início dele (não é por job); None se indisponível."""
    try:
        return int(Path("/sys/fs/cgroup/memory.peak").read_text().strip())
    except (OSError, ValueError):
        return None


def performance_fields(job: dict, metadata: dict) -> dict:
    """Métricas do job para o log; só números (nunca texto, nome de arquivo ou caminho)."""
    processing, duration = metadata["processing_seconds"], metadata["duration_seconds"]
    return {"duration_seconds": duration, "processing_seconds": processing,
            "rtf": round(processing / duration, 3) if duration else None,
            "attempts": job["attempts"], "peak_memory_bytes": peak_memory_bytes()}


def heartbeat(settings: Settings, stop: threading.Event, current: dict = None, limit: float = None):
    """Sinal de vida a cada 3 s; inclui o job em execução e o instante do último progresso.

    Se o job fica mais de `limit` s sem progresso, registra `job_stalled` uma vez (sem reiniciar nada).
    """
    current = {} if current is None else current
    limit = stall_seconds() if limit is None else limit
    while not stop.is_set():
        job_id, progress_at = current.get("job_id"), current.get("progress_at")
        temporary = settings.state / "heartbeat.tmp"
        temporary.write_text(json.dumps({"timestamp": time.time(), "pid": os.getpid(),
                                         "job_id": job_id, "progress_at": progress_at}))
        os.replace(temporary, settings.state / "heartbeat.json")
        if job_id and progress_at and time.time() - progress_at > limit and current.get("stalled") != job_id:
            current["stalled"] = job_id
            log("job_stalled", job_id=job_id, seconds_without_progress=round(time.time() - progress_at))
        stop.wait(3)


SWEEP_INTERVAL = 3600


def input_policy() -> tuple:
    """Política de WHISPER_BOX_INPUT_RETENTION; valor inválido cai em `keep` (nunca apaga por engano)."""
    try:
        return parse_policy(os.getenv("WHISPER_BOX_INPUT_RETENTION"))
    except BoxError:
        log("retention_invalid", fallback="keep")
        return "keep", None


def sweep(settings: Settings, store: Store, policy: tuple, since: float):
    try:
        result = sweep_inputs(settings, store, policy, since=since)
        if result["removed"]:
            log("inputs_swept", removed=result["removed"], bytes_freed=result["bytes"])
    except Exception as exc:  # a limpeza nunca derruba o worker
        log("sweep_failed", exception_type=type(exc).__name__)


def run(settings: Settings):
    settings.initialize()
    with worker_lock(settings):
        manifest = read_manifest(settings.models, verify=True)
        store = Store(settings.state)
        # Worker exclusivo: nada em saida/.partial está em uso (a recuperação decide pelo diretório final).
        cleaned = clean_partial(settings)
        log("partial_cleaned", items=cleaned["items"], bytes_freed=cleaned["bytes"])
        policy = input_policy()
        since = retention_start(settings)
        for job in store.running():
            if complete_output(settings, job):
                store.finish(job["id"])
            else:
                store.recover(job["id"])
        sweep(settings, store, policy, since)
        last_sweep = time.monotonic()
        stop = threading.Event()

        def interrupted(_signal, _frame):
            stop.set()
            # Mantém running para recuperação na próxima inicialização.
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        current = {}
        thread = threading.Thread(target=heartbeat, args=(settings, stop, current), daemon=True)
        thread.start()
        model = None
        threads, threads_valid = cpu_threads()
        if not threads_valid:
            log("cpu_threads_invalid", fallback=threads)
        loaded_threads = None
        try:
            log("worker_ready", model="small", revision=manifest["revision"], **runtime_config(threads))
            while not stop.is_set():
                job = store.claim()
                if job is None:
                    if policy[0] == "days" and time.monotonic() - last_sweep >= SWEEP_INTERVAL:
                        sweep(settings, store, policy, since)
                        last_sweep = time.monotonic()
                    stop.wait(1)
                    continue
                log("job_started", job_id=job["id"], attempt=job["attempts"],
                    queue_wait_seconds=round(max(0.0, (job["started_at"] or time.time()) - job["created_at"]), 3))
                current.clear()
                current.update(job_id=job["id"], progress_at=job["started_at"] or time.time())

                def report(seconds, job_id=job["id"]):
                    current["progress_at"] = store.progress(job_id, seconds)

                try:
                    config = json.loads(job["config"])
                    if config["model_revision"] != manifest["revision"]:
                        raise BoxError("model_changed", "O modelo instalado não corresponde ao trabalho.")
                    # As threads fazem parte do fingerprint: o job roda com as threads com que foi enfileirado.
                    job_threads = config.get("cpu_threads", threads)
                    if model is None or loaded_threads != job_threads:
                        from faster_whisper import WhisperModel
                        model = None  # libera o modelo anterior antes de carregar o novo
                        model = WhisperModel(
                            str(settings.models / "small"), device="cpu", compute_type="int8",
                            cpu_threads=job_threads, num_workers=1, local_files_only=True,
                        )
                        loaded_threads = job_threads
                        log("model_loaded", revision=manifest["revision"], cpu_threads=job_threads)
                    from .pipeline import transcribe
                    metadata = transcribe(settings, job, model, report, runtime_config(job_threads))
                    store.finish(job["id"])
                    log("job_succeeded", job_id=job["id"], **performance_fields(job, metadata))
                    try:
                        freed = apply_input_retention(settings, store, job, policy, since=since)
                        if freed is not None:
                            log("input_removed", job_id=job["id"], bytes_freed=freed)
                    except Exception as exc:  # falha de limpeza não altera o resultado do job
                        log("input_removal_failed", job_id=job["id"], exception_type=type(exc).__name__)
                except Exception as exc:
                    error = exc if isinstance(exc, BoxError) else BoxError(
                        "transcription_failed", f"Falha no processamento ({type(exc).__name__})."
                    )
                    store.finish(job["id"], error)
                    # Evita registrar falas ou nomes/caminhos da gravação nos logs.
                    log("job_failed", job_id=job["id"], code=error.code,
                        exception_type=type(exc).__name__)
                finally:
                    current.clear()
        finally:
            stop.set()
            thread.join(timeout=5)
            (settings.state / "heartbeat.json").unlink(missing_ok=True)
            log("worker_stopped")
