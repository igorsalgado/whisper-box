"""Retenção e limpeza de disco (A04): .partial, cópia de entrada e remoção explícita (purge).

Regras: nunca toca no arquivo original do usuário (a CLI só o lê), nunca apaga `saida/<job_id>/`
fora do `purge --yes`, e só remove caminhos derivados de `Settings` e de um job_id validado.
"""
import json
import os
import re
import shutil
import time
from pathlib import Path

from .config import BoxError, Settings
from .jobs import complete_output
from .store import Store

JOB_ID = re.compile(r"[0-9a-f]{32}")
DAY = 86400
DEFAULT_POLICY = "delete"
MARKER = "retention.json"


def parse_policy(value) -> tuple:
    """'keep' | 'delete' | '<N>d' -> (modo, dias). Vazio usa o padrão; valor inválido levanta BoxError."""
    text = (value or DEFAULT_POLICY).strip().lower()
    if text in ("keep", "delete"):
        return text, None
    match = re.fullmatch(r"([1-9]\d{0,3})d", text)
    if match:
        return "days", int(match.group(1))
    raise BoxError("invalid_retention", "WHISPER_BOX_INPUT_RETENTION deve ser keep, delete ou <N>d.", 3)


def tree_bytes(path: Path) -> int:
    """Soma dos tamanhos de arquivos (sem seguir links simbólicos); 0 se não existir."""
    total = 0
    if path is None:
        return 0
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def child(base: Path, name: str):
    """base/name se for um diretório real (não link) cujo pai resolvido é `base`; senão None."""
    if not JOB_ID.fullmatch(name):
        return None
    candidate = base / name
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    if candidate.resolve().parent != base.resolve():
        return None
    return candidate


def remove_tree(path: Path) -> int:
    """Remove o diretório e devolve os bytes liberados. Levanta OSError se algo restar."""
    size = tree_bytes(path)
    failures = []
    shutil.rmtree(path, onerror=lambda _f, p, _e: failures.append(p))
    if failures or path.exists():
        raise OSError("remoção incompleta")
    return size


def clean_partial(settings: Settings) -> dict:
    """Esvazia saida/.partial/ (chamar só com o worker exclusivo). Nunca toca em saida/<job_id>/."""
    root = settings.outputs / ".partial"
    items = freed = 0
    if root.is_dir() and not root.is_symlink():
        for entry in list(root.iterdir()):
            size = tree_bytes(entry)
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                continue
            items += 1
            freed += size
    return {"items": items, "bytes": freed}


def retention_start(settings: Settings, now: float = None) -> float:
    """Instante em que a retenção passou a valer neste estado.

    Jobs concluídos antes dele (histórico anterior à A04) não são apagados automaticamente; a
    limpeza do histórico é explícita (`purge`).
    """
    path = settings.state / MARKER
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["since"])
    except (OSError, ValueError, KeyError, TypeError):
        since = time.time() if now is None else now
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"since": since}), encoding="utf-8")
        os.replace(temporary, path)
        return since


def apply_input_retention(settings: Settings, store: Store, job: dict, policy: tuple,
                          now: float = None, since: float = 0.0):
    """Remove entrada/<job_id>/ conforme a política. Devolve bytes liberados ou None se nada foi removido.

    Só age em job `succeeded` com saída verificada (manifest ok). `failed`, `queued` e `running`
    mantêm a entrada.
    """
    mode, days = policy
    if mode == "keep":
        return None
    current = store.get(job["id"])  # estado atual, não o instantâneo recebido
    if current["status"] != "succeeded" or not complete_output(settings, current):
        return None
    finished = current["finished_at"] or 0
    if finished < since:
        return None
    if mode == "days" and (time.time() if now is None else now) - finished < days * DAY:
        return None
    directory = child(settings.inputs, current["id"])
    if directory is None:
        return None
    return remove_tree(directory)


def sweep_inputs(settings: Settings, store: Store, policy: tuple, now: float = None,
                 since: float = 0.0) -> dict:
    """Aplica a retenção às pastas em entrada/ (resíduos pós-queda e política <N>d)."""
    removed = freed = 0
    if policy[0] == "keep" or not settings.inputs.is_dir():
        return {"removed": 0, "bytes": 0}
    for entry in sorted(settings.inputs.iterdir()):
        if not JOB_ID.fullmatch(entry.name):
            continue  # .gravacoes e qualquer outra coisa
        try:
            job = store.get(entry.name)  # pasta sem job (submit em andamento) nunca é tocada
        except BoxError:
            continue
        try:
            size = apply_input_retention(settings, store, job, policy, now, since)
        except OSError:
            continue
        if size is not None:
            removed += 1
            freed += size
    return {"removed": removed, "bytes": freed}


def purge(settings: Settings, job_id: str = None, older_than: int = None, status: str = None,
          yes: bool = False, inputs_only: bool = False, now: float = None) -> tuple:
    """Remove jobs (entrada, saída, parciais e registro). Sem `yes`, só lista. Devolve (resposta, código).

    Com `inputs_only` remove apenas entrada/<job_id>/ e mantém saída e registro.
    """
    if (job_id is None) == (older_than is None):
        raise BoxError("invalid_arguments", "Use --job ID ou --older-than DIAS (exatamente um).", 3)
    if job_id is not None and (status is not None or not JOB_ID.fullmatch(job_id)):
        raise BoxError("invalid_arguments",
                       "Informe --job com 32 hexadecimais; --status só vale com --older-than.", 3)
    if older_than is not None and not 0 <= older_than <= 36500:
        raise BoxError("invalid_arguments", "--older-than deve estar entre 0 e 36500.", 3)
    if status not in (None, "failed", "succeeded"):
        raise BoxError("invalid_arguments", "--status deve ser failed ou succeeded.", 3)
    store = Store(settings.state)
    if job_id is not None:
        job = store.get(job_id)  # job_not_found (3)
        if job["status"] in ("queued", "running"):
            raise BoxError("job_active", "O trabalho está na fila ou em processamento; aguarde terminar.", 3)
        selected = [job]
    else:
        cutoff = (time.time() if now is None else now) - older_than * DAY
        selected = [job for job in store.list(limit=1_000_000, status=status)
                    if job["status"] in ("succeeded", "failed")
                    and (job["finished_at"] or job["created_at"]) < cutoff]
    items = []
    for job in selected:
        entry = child(settings.inputs, job["id"])
        output = None if inputs_only else child(settings.outputs, job["id"])
        partial = None if inputs_only else child(settings.outputs / ".partial", job["id"])
        items.append((job, entry, output, partial, {
            "job_id": job["id"], "status": job["status"],
            "input_bytes": tree_bytes(entry) if entry else 0,
            "output_bytes": (tree_bytes(output) + tree_bytes(partial)) if output or partial else 0,
        }))
    base = {"inputs_only": True} if inputs_only else {}
    if not yes:
        total = sum(i[4]["input_bytes"] + i[4]["output_bytes"] for i in items)
        return {"dry_run": True, **base, "would_purge": [i[4] for i in items], "freed_bytes": total}, 0
    purged, errors, total = [], [], 0
    for job, entry, output, partial, summary in items:
        try:
            if inputs_only:
                if store.get(job["id"])["status"] in ("queued", "running"):
                    continue
            elif not store.delete(job["id"]):
                continue
        except BoxError:
            if job_id is not None:
                raise
            continue  # virou ativo entre a listagem e a remoção
        failed = False
        for directory in (entry, output, partial):
            if directory is None:
                continue
            try:
                remove_tree(directory)
            except OSError:
                failed = True
        if failed:
            errors.append({"job_id": job["id"], "code": "remove_failed"})
        else:
            purged.append(summary)
            total += summary["input_bytes"] + summary["output_bytes"]
    response = {"dry_run": False, **base, "purged": purged, "freed_bytes": total}
    if errors:
        response["errors"] = errors
    return response, 1 if errors else 0
