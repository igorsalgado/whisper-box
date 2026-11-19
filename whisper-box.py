#!/usr/bin/env python3
"""Wrapper multiplataforma do Whisper Box.

Usa somente a biblioteca padrão (Python 3.8+) e delega todo o trabalho ao
Docker Compose. stdout recebe exatamente um objeto JSON nos comandos de
contrato; diagnósticos do Docker seguem para stderr.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = "prepare, start, stop, submit, status, wait, result ou logs"
JOB_COMMANDS = ("status", "wait", "result")
LIFECYCLE_COMMANDS = ("prepare", "start", "stop")


def error_json(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False)


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


def run_to_stderr(arguments: list, env: dict) -> int:
    """Executa Docker enviando a saída dele para stderr, preservando stdout para JSON."""
    sys.stderr.flush()
    try:
        return subprocess.run(arguments, stdout=sys.stderr.fileno(), env=env).returncode
    except (AttributeError, OSError, ValueError):
        completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env)
        sys.stderr.write(completed.stdout.decode("utf-8", "replace"))
        return completed.returncode


def run_cli(arguments: list, env: dict, out) -> int:
    """Executa a CLI do container e repassa seu JSON; ausência de resposta vira erro."""
    completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env)
    text = completed.stdout.decode("utf-8", "replace").strip()
    code = completed.returncode
    if not text:
        print(error_json("docker_error", "Sem resposta do container. Verifique o Docker e execute prepare."),
              file=out)
        return code or 1
    print(text, file=out)
    return code


def main(argv: list, out=None) -> int:
    out = out or sys.stdout
    if not argv:
        print(error_json("invalid_arguments", "Use " + COMMANDS + "."), file=out)
        return 3
    command, rest = argv[0], list(argv[1:])
    env = dict(os.environ, WHISPER_BOX_HOST_ROOT=str(ROOT))
    compose = compose_base()

    if command == "prepare":
        code = run_to_stderr(compose + ["build", "worker"], env)
        if code == 0:
            out.flush()
            code = subprocess.run(compose + ["--profile", "setup", "run", "--rm", "--no-deps", "-T", "prepare"],
                                  env=env).returncode
    elif command == "start":
        code = run_to_stderr(compose + ["up", "-d", "--no-build", "--pull", "never", "--wait",
                                        "--wait-timeout", "90", "worker"], env)
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
        print(error_json("docker_error", "Falha no Docker. Consulte stderr, verifique o engine Docker "
                                         "e execute prepare antes de start."), file=out)
    return code


def entrypoint() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        return main(sys.argv[1:])
    except (OSError, subprocess.SubprocessError):
        print(error_json("operational_error", "Nao foi possivel executar o comando. Verifique o caminho, "
                                              "o Docker e a preparacao inicial."))
        return 1


if __name__ == "__main__":
    sys.exit(entrypoint())
