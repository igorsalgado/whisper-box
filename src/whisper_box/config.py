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


def effective_config(model_revision: str, language: str = "pt") -> dict:
    if language not in {"pt", "en", "es", "auto"}:
        raise BoxError("invalid_language", "Use pt, en, es ou auto.", 3)
    return {
        "pipeline_version": __version__,
        "model": "small",
        "model_revision": model_revision,
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 2,
        "beam_size": 5,
        "language": language,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "chunk_seconds": 300,
    }
