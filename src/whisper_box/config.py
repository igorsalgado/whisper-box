import os
from dataclasses import dataclass
from pathlib import Path

from . import __version__


class BoxError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


@dataclass(frozen=True)
class Settings:
    state: Path
    inputs: Path
    outputs: Path
    models: Path
    host_root: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.getenv("WHISPER_BOX_STATE", "/state")),
            Path(os.getenv("WHISPER_BOX_INPUT", "/input")),
            Path(os.getenv("WHISPER_BOX_OUTPUT", "/output")),
            Path(os.getenv("WHISPER_BOX_MODELS", "/models")),
            os.getenv("WHISPER_BOX_HOST_ROOT", ""),
        )

    def initialize(self):
        for path in (self.state, self.inputs, self.outputs):
            path.mkdir(parents=True, exist_ok=True)


DEFAULT_CPU_THREADS = 2
DEFAULT_STALL_SECONDS = 1200


def cpu_threads(value=None) -> tuple:
    """Threads de inferência (WHISPER_BOX_CPU_THREADS, inteiro de 1 a 16). Devolve (valor, valido)."""
    raw = os.getenv("WHISPER_BOX_CPU_THREADS") if value is None else value
    if raw in (None, ""):
        return DEFAULT_CPU_THREADS, True
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CPU_THREADS, False
    return (number, True) if 1 <= number <= 16 else (DEFAULT_CPU_THREADS, False)


def stall_seconds(value=None) -> float:
    """Limite de job sem progresso (WHISPER_BOX_STALL_SECONDS); inválido cai no padrão."""
    raw = os.getenv("WHISPER_BOX_STALL_SECONDS") if value is None else value
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALL_SECONDS
    return number if number > 0 else DEFAULT_STALL_SECONDS


def runtime_config(threads=None) -> dict:
    """Configuração de execução registrada em `runtime` nos metadados (auditoria).

    As threads também entram no fingerprint (`effective_config`): a medição da A06 mostrou que
    2, 3 e 4 threads produzem textos diferentes."""
    value = cpu_threads()[0] if threads is None else threads
    cpus = os.getenv("WHISPER_BOX_CPUS")
    return {"cpu_threads": value, "cpus": cpus if cpus else None}


def effective_config(model_revision: str, language: str = "pt") -> dict:
    if language not in {"pt", "en", "es", "auto"}:
        raise BoxError("invalid_language", "Use pt, en, es ou auto.", 3)
    return {
        "pipeline_version": __version__,
        "model": "small",
        "model_revision": model_revision,
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": cpu_threads()[0],  # medido em A06: o numero de threads altera o texto
        "beam_size": 5,
        "language": language,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "chunk_seconds": 300,
    }
