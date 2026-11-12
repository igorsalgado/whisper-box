import hashlib
import json
import os
from pathlib import Path

from .config import BoxError

REPO = "Systran/faster-whisper-small"
REQUIRED = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(models: Path, verify: bool = False) -> dict:
    try:
        manifest = json.loads((models / "manifest.json").read_text(encoding="utf-8"))
        if manifest["repo"] != REPO or not manifest["revision"]:
            raise ValueError("Modelo incompatível")
        for filename in REQUIRED:
            entry = manifest["files"][filename]
            path = models / "small" / filename
            if path.stat().st_size != entry["size"]:
                raise ValueError("Tamanho inválido")
            if verify and sha256_file(path) != entry["sha256"]:
                raise ValueError("Hash inválido")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BoxError(
            "model_not_ready",
            "Modelo local ausente ou inválido. Execute prepare com internet antes de start.",
        ) from exc


def prepare(models: Path) -> dict:
    # Uma preparação já completa não muda silenciosamente a revisão instalada.
    if (models / "manifest.json").exists():
        manifest = read_manifest(models, verify=True)
        return {"status": "ready", "model": "small", "revision": manifest["revision"], "reused": True}
    from huggingface_hub import HfApi, snapshot_download

    models.mkdir(parents=True, exist_ok=True)
    revision = HfApi().model_info(REPO).sha
    snapshot_download(
        repo_id=REPO,
        revision=revision,
        local_dir=str(models / "small"),
        allow_patterns=list(REQUIRED),
    )
    manifest = {
        "repo": REPO,
        "revision": revision,
        "files": {
            name: {"size": (models / "small" / name).stat().st_size,
                   "sha256": sha256_file(models / "small" / name)}
            for name in REQUIRED
        },
    }
    temporary = models / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(temporary, models / "manifest.json")
    return {"status": "ready", "model": "small", "revision": revision, "reused": False}
