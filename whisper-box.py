#!/usr/bin/env python3
"""Wrapper multiplataforma do Whisper Box.

Usa somente a biblioteca padrão (Python 3.8+) e delega todo o trabalho ao
Docker Compose. stdout recebe exatamente um objeto JSON nos comandos de
contrato; diagnósticos do Docker seguem para stderr.

Agentes: comece por `doctor` e transcreva com `transcribe --input CAMINHO`.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = "doctor, prepare, start, stop, transcribe, submit, status, wait, result ou logs"
JOB_COMMANDS = ("status", "wait", "result")
LIFECYCLE_COMMANDS = ("prepare", "start", "stop")
ARTIFACTS = ("text", "srt", "segments", "metadata")
IMAGE = "whisper-box:local"

DOCKER_INSTALL = {
    "windows": "Instale o Docker Desktop (requer administrador e WSL 2): winget install -e --id Docker.DockerDesktop "
               "— ou https://docs.docker.com/desktop/setup/install/windows-install/. Pode exigir reiniciar o Windows.",
    "macos": "Instale o Docker Desktop: brew install --cask docker — ou "
             "https://docs.docker.com/desktop/setup/install/mac-install/. Depois abra o aplicativo Docker.",
    "linux": "Instale o Docker Engine e o plugin Compose pelo gerenciador de pacotes da distribuição "
             "(https://docs.docker.com/engine/install/). Depois: sudo usermod -aG docker $USER e nova sessão.",
}
DOCKER_START = {
    "windows": "Abra o Docker Desktop e aguarde o engine Linux ficar pronto.",
    "macos": "Abra o Docker Desktop (open -a Docker) e aguarde o engine ficar pronto.",
    "linux": "Inicie o serviço (sudo systemctl start docker). Se o erro for de permissão no socket, "
             "adicione o usuário ao grupo docker e abra nova sessão.",
}


class ArgumentError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def error_json(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False)


def platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def compose_base(root: Path = ROOT) -> list:
    return ["docker", "compose", "--project-directory", str(root),
            "-f", str(root / "compose.yaml")]


def submit_arguments(rest: list) -> tuple:
    """Monta a chamada de submit e o bind mount somente leitura da gravação.

    Devolve (argumentos, None) ou (None, (código_erro, mensagem)).
    """
    rest = list(rest)
    try:
        index = rest.index("--input")
    except ValueError:
        index = -1
    if index < 0 or index + 1 >= len(rest):
        return None, ("invalid_arguments", "Informe --input com o caminho da gravacao.")
    source = Path(rest[index + 1])
    if not source.is_file():
        return None, ("input_not_found", "Informe um arquivo de midia existente.")
    source = source.resolve()
    # O caminho é dado, nunca shell: subprocess recebe uma lista de argumentos.
    container_path = "/source/recording" + source.suffix
    rest[index + 1] = container_path
    mount = str(source) + ":" + container_path + ":ro"
    return ["--profile", "tools", "run", "--rm", "--no-deps", "-T",
            "--volume", mount, "cli", "submit"] + rest, None


def job_arguments(command: str, rest: list) -> list:
    return ["--profile", "tools", "run", "--rm", "--no-deps", "-T", "cli", command] + list(rest)


def start_arguments() -> list:
    return ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "90", "worker"]


def run_to_stderr(arguments: list, env: dict) -> int:
    """Executa Docker enviando a saída dele para stderr, preservando stdout para JSON."""
    sys.stderr.flush()
    try:
        return subprocess.run(arguments, stdout=sys.stderr.fileno(), env=env).returncode
    except (AttributeError, OSError, ValueError):
        completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env)
        sys.stderr.write(completed.stdout.decode("utf-8", "replace"))
        return completed.returncode


def capture(arguments: list, env: dict) -> tuple:
    """Executa a CLI do container e devolve (json_texto, código); ausência de resposta vira erro."""
    completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env)
    text = completed.stdout.decode("utf-8", "replace").strip()
    if not text:
        return error_json("docker_error", "Sem resposta do container. Execute doctor."), completed.returncode or 1
    return text, completed.returncode


def run_cli(arguments: list, env: dict, out) -> int:
    text, code = capture(arguments, env)
    print(text, file=out)
    return code


def probe(arguments: list, timeout: int = 30) -> tuple:
    """Executa uma verificação curta; devolve (código, stdout) ou (None, motivo)."""
    try:
        completed = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        return None, "nao encontrado"
    except subprocess.TimeoutExpired:
        return None, "sem resposta"
    return completed.returncode, completed.stdout.decode("utf-8", "replace").strip()


def doctor(out) -> int:
    """Diagnostica o host e indica um único próximo passo para o agente."""
    platform = platform_name()
    checks = {"python": {"ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0]}}
    steps = []

    def check(name, ok, detail, step=None):
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok and step:
            steps.append(step)
        return ok

    if not check("docker_cli", shutil.which("docker"), shutil.which("docker") or "nao encontrado",
                 {"code": "install_docker", "requires_user_approval": True, "action": DOCKER_INSTALL[platform]}):
        return finish_doctor(out, platform, checks, steps)
    code, detail = probe(["docker", "compose", "version", "--short"])
    if not check("compose_v2", code == 0, detail if code == 0 else "indisponivel",
                 {"code": "install_compose", "requires_user_approval": True, "action": DOCKER_INSTALL[platform]}):
        return finish_doctor(out, platform, checks, steps)
    code, detail = probe(["docker", "info", "--format", "{{.OSType}}"])
    if not check("docker_engine", code == 0 and detail == "linux",
                 detail if code == 0 else "engine parado ou sem permissao",
                 {"code": "start_docker", "requires_user_approval": False, "action": DOCKER_START[platform]}):
        return finish_doctor(out, platform, checks, steps)
    code, _ = probe(["docker", "image", "inspect", IMAGE])
    image_ready = check("image", code == 0, IMAGE if code == 0 else "ausente")
    model_ready = check("model", (ROOT / "modelos" / "manifest.json").is_file(),
                        "modelos/manifest.json" if (ROOT / "modelos" / "manifest.json").is_file() else "ausente")
    if not (image_ready and model_ready):
        steps.append({"code": "prepare", "requires_user_approval": True,
                      "action": "Execute: python whisper-box.py prepare (uma vez, com internet; baixa imagem e "
                                "modelo de aproximadamente 500 MB)."})
    return finish_doctor(out, platform, checks, steps)


def finish_doctor(out, platform, checks, steps) -> int:
    ready = not steps
    step = steps[0] if steps else {
        "code": "ask_for_recording", "requires_user_approval": False,
        "action": "Peça ao usuário o caminho da gravação finalizada e execute: "
                  "python whisper-box.py transcribe --input CAMINHO"}
    print(json.dumps({"ready": ready, "platform": platform, "project_root": str(ROOT),
                      "checks": checks, "next_step": step}, ensure_ascii=False), file=out)
    return 0 if ready else 1


def transcribe(rest: list, env: dict, out) -> int:
    """Fluxo completo para agentes: start, submit, espera renovada e resultado verificado."""
    parser = Parser(prog="whisper-box.py transcribe")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--input")
    target.add_argument("--job")
    parser.add_argument("--language", choices=("pt", "en", "es", "auto"), default=None)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args(rest)
    if args.job and args.language:
        raise ArgumentError("--language so se aplica a --input.")
    if not 1 <= args.timeout_seconds <= 86400:
        raise ArgumentError("--timeout-seconds deve estar entre 1 e 86400.")
    if args.input and not Path(args.input).is_file():
        print(error_json("input_not_found", "Informe um arquivo de midia existente."), file=out)
        return 3

    compose = compose_base()
    if run_to_stderr(compose + start_arguments(), env) != 0:
        print(error_json("docker_error", "O worker nao iniciou. Execute doctor."), file=out)
        return 1
    job_id = args.job
    if args.input:
        arguments, _ = submit_arguments(["--input", args.input, "--language", args.language or "pt"])
        text, code = capture(compose + arguments, env)
        if code != 0:
            print(text, file=out)
            return code
        job_id = json.loads(text)["job_id"]
    print(json.dumps({"event": "whisper_waiting", "job_id": job_id}), file=sys.stderr, flush=True)

    deadline = time.monotonic() + args.timeout_seconds
    observed = {}
    while True:
        remaining = math.ceil(deadline - time.monotonic())
        if remaining <= 0:
            print(json.dumps({"job_id": job_id, "status": observed.get("status"), "timed_out": True,
                              "wait_budget_exhausted": True}), file=out)
            return 2
        text, code = capture(compose + job_arguments("wait", ["--job", job_id, "--timeout",
                                                              str(min(30, remaining))]), env)
        if code == 2:
            observed = json.loads(text)
            continue
        if code != 0:
            print(text, file=out)
            return code
        text, code = capture(compose + job_arguments("result", ["--job", job_id]), env)
        if code == 4:
            continue
        if code != 0:
            print(text, file=out)
            return code
        files = json.loads(text).get("files") or {}
        if not all(files.get(key) and Path(files[key]).is_file() for key in ARTIFACTS):
            print(json.dumps({"job_id": job_id, "error": {"code": "output_unreachable",
                              "message": "Artefatos ausentes ou inacessiveis pelo host."}}), file=out)
            return 1
        print(text, file=out)
        return 0


def main(argv: list, out=None) -> int:
    out = out or sys.stdout
    if not argv:
        print(error_json("invalid_arguments", "Use " + COMMANDS + "."), file=out)
        return 3
    command, rest = argv[0], list(argv[1:])
    env = dict(os.environ, WHISPER_BOX_HOST_ROOT=str(ROOT))
    compose = compose_base()

    if command == "doctor":
        return doctor(out)
    if command == "transcribe":
        try:
            return transcribe(rest, env, out)
        except ArgumentError as error:
            print(error_json("invalid_arguments", str(error)), file=out)
            return 3
    if command == "prepare":
        code = run_to_stderr(compose + ["build", "worker"], env)
        if code == 0:
            out.flush()
            code = subprocess.run(compose + ["--profile", "setup", "run", "--rm", "--no-deps", "-T", "prepare"],
                                  env=env).returncode
    elif command == "start":
        code = run_to_stderr(compose + start_arguments(), env)
        if code == 0:
            print('{"status":"ready"}', file=out)
    elif command == "stop":
        code = run_to_stderr(compose + ["stop", "worker"], env)
        if code == 0:
            print('{"status":"stopped"}', file=out)
    elif command == "logs":
        out.flush()
        code = subprocess.run(compose + ["logs", "--tail", "50", "worker"], env=env).returncode
    elif command == "submit":
        arguments, failure = submit_arguments(rest)
        if failure:
            print(error_json(*failure), file=out)
            return 3
        code = run_cli(compose + arguments, env, out)
    elif command in JOB_COMMANDS:
        code = run_cli(compose + job_arguments(command, rest), env, out)
    else:
        print(error_json("invalid_arguments", "Comando desconhecido. Use " + COMMANDS + "."), file=out)
        return 3

    if code != 0 and command in LIFECYCLE_COMMANDS:
        print(error_json("docker_error", "Falha no Docker. Consulte stderr e execute doctor."), file=out)
    return code


def entrypoint() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        return main(sys.argv[1:])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        print(error_json("operational_error", "Nao foi possivel executar o comando. Execute doctor."))
        return 1


if __name__ == "__main__":
    sys.exit(entrypoint())
