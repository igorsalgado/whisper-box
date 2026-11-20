import fcntl
import json
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager

from .config import BoxError, Settings
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


def heartbeat(settings: Settings, stop: threading.Event):
    while not stop.is_set():
        temporary = settings.state / "heartbeat.tmp"
        temporary.write_text(json.dumps({"timestamp": time.time(), "pid": os.getpid()}))
        os.replace(temporary, settings.state / "heartbeat.json")
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
        thread = threading.Thread(target=heartbeat, args=(settings, stop), daemon=True)
        thread.start()
        model = None
        try:
            log("worker_ready", model="small", revision=manifest["revision"])
            while not stop.is_set():
                job = store.claim()
                if job is None:
                    if policy[0] == "days" and time.monotonic() - last_sweep >= SWEEP_INTERVAL:
                        sweep(settings, store, policy, since)
                        last_sweep = time.monotonic()
                    stop.wait(1)
                    continue
                log("job_started", job_id=job["id"], attempt=job["attempts"])
                try:
                    config = json.loads(job["config"])
                    if config["model_revision"] != manifest["revision"]:
                        raise BoxError("model_changed", "O modelo instalado não corresponde ao trabalho.")
                    if model is None:
                        from faster_whisper import WhisperModel
                        model = WhisperModel(
                            str(settings.models / "small"), device="cpu", compute_type="int8",
                            cpu_threads=2, num_workers=1, local_files_only=True,
                        )
                        log("model_loaded", revision=manifest["revision"])
                    from .pipeline import transcribe
                    transcribe(settings, job, model, lambda seconds: store.progress(job["id"], seconds))
                    store.finish(job["id"])
                    log("job_succeeded", job_id=job["id"])
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
            stop.set()
            thread.join(timeout=5)
            (settings.state / "heartbeat.json").unlink(missing_ok=True)
            log("worker_stopped")
