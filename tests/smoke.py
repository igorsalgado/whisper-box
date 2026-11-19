#!/usr/bin/env python3
"""Ensaio de integração pelo wrapper. Dados e relatório ficam em logs/, fora do Git.

Executa no host (Windows, Linux ou macOS) com Python 3.8+ e Docker:
    python tests/smoke.py --input CAMINHO_DA_GRAVACAO
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT / "whisper-box.py"
LOGS = PROJECT / "logs"
FIXTURES = LOGS / "fixtures"


class SmokeError(Exception):
    pass


def box(arguments, allowed=(0,)):
    completed = subprocess.run([sys.executable, str(RUNNER)] + list(arguments),
                               stdout=subprocess.PIPE, cwd=str(PROJECT))
    lines = [line for line in completed.stdout.decode("utf-8").splitlines() if line.strip()]
    if completed.returncode not in allowed:
        raise SmokeError(f"Comando falhou: {arguments[0]}, codigo={completed.returncode}, resposta={''.join(lines)}")
    if len(lines) != 1:
        raise SmokeError("stdout deve conter exatamente uma linha JSON.")
    return completed.returncode, json.loads(lines[0])


def await_job(job_id, total_seconds=1800):
    deadline = time.monotonic() + total_seconds
    while True:
        code, body = box(["wait", "--job", job_id, "--timeout", "30"], allowed=(0, 1, 2))
        if code != 2:
            return code, body
        if time.monotonic() > deadline:
            raise SmokeError("Prazo total do ensaio excedido; o trabalho continua no worker.")


def read_metadata(body):
    return json.loads(Path(body["files"]["metadata"]).read_text(encoding="utf-8"))


def generate_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    # Sem inferência: apenas gera fixtures, com os limites do container auxiliar.
    command = ["docker", "compose", "--project-directory", str(PROJECT), "-f", str(PROJECT / "compose.yaml"),
               "--profile", "tools", "run", "--rm", "--no-deps", "-T", "--volume", f"{FIXTURES}:/fixtures",
               "--entrypoint", "python", "cli", "/app/tests/make_fixtures.py", "/fixtures"]
    if subprocess.run(command, stdout=sys.stderr.fileno()).returncode != 0:
        raise SmokeError("Falha na geracao de fixtures.")


def main(recording: str):
    results = []
    box(["start"])
    _, real = box(["submit", "--input", recording])
    _, duplicate = box(["submit", "--input", recording])
    if not duplicate.get("reused") or duplicate["job_id"] != real["job_id"]:
        raise SmokeError("Deduplicacao incorreta.")
    code, completed = await_job(real["job_id"])
    if code != 0:
        raise SmokeError("A gravacao real falhou.")
    for path in completed["files"].values():
        if not Path(path).is_file():
            raise SmokeError("Caminho de saida inacessivel pelo host.")
    metadata = read_metadata(completed)
    if metadata["segments"] <= 0:
        raise SmokeError("A gravacao real nao produziu segmentos.")
    results.append({"case": "real-recording", "job_id": real["job_id"], "metadata": metadata})

    generate_fixtures()
    for fixture in sorted(path for path in FIXTURES.iterdir() if path.is_file()):
        _, submission = box(["submit", "--input", str(fixture)])
        code, result = await_job(submission["job_id"])
        if fixture.name == "invalido.mp4":
            if code != 1 or result.get("error", {}).get("code") != "invalid_media":
                raise SmokeError("Midia invalida deveria falhar.")
            results.append({"case": fixture.name, "job_id": submission["job_id"], "status": "expected_failure"})
            continue
        if code != 0:
            raise SmokeError(f"Falha no formato {fixture.suffix}")
        metadata = read_metadata(result)
        if not metadata["no_speech"]:
            raise SmokeError("Silencio deveria gerar zero segmentos.")
        results.append({"case": fixture.name, "job_id": submission["job_id"], "metadata": metadata})

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "results": results}
    (LOGS / "smoke-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ensaio aprovado: {len(results)} casos; relatorio local em logs/smoke-result.json.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ensaio de integracao do Whisper Box.")
    parser.add_argument("--input", required=True, help="Gravacao finalizada usada no ensaio.")
    try:
        main(parser.parse_args().input)
    except SmokeError as error:
        print(f"Ensaio reprovado: {error}", file=sys.stderr)
        sys.exit(1)
