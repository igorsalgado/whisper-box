#!/usr/bin/env python3
"""Wrapper multiplataforma do Whisper Box.

Usa somente a biblioteca padrão (Python 3.8+) e delega todo o trabalho ao
Docker Compose. stdout recebe exatamente um objeto JSON nos comandos de
contrato; diagnósticos do Docker seguem para stderr.

Agentes: comece por `doctor` e transcreva com `transcribe --input CAMINHO`.
"""
import argparse
import hashlib
import hmac
import json
import math
import ntpath
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = "doctor, prepare, start, stop, painel, transcribe, submit, status, wait, result, list, purge ou logs"
JOB_COMMANDS = ("status", "wait", "result", "list", "purge")
# Consultas leves: tentam `docker compose exec` no worker em execução (~1 s) antes do `run` (5 a 10 s).
EXEC_COMMANDS = ("status", "wait", "result", "list")
USE_EXEC = True
LIFECYCLE_COMMANDS = ("start", "stop")
ARTIFACTS = ("text", "srt", "segments", "metadata")
IMAGE = "whisper-box:local"
JOB_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
RETRY_DELAYS = (2, 5)  # esperas (s) das novas tentativas após falha transitória do Docker
JOB_TIMEOUT = 120  # status, result, list
PURGE_TIMEOUT = 900  # purge pode apagar muitos arquivos
SUBMIT_TIMEOUT = 3600  # cópia de até 2 GiB
START_TIMEOUT = 300
PREPARE_TIMEOUT = 3600
DIGEST_LABEL = "whisper-box.source-digest"
HELPER_PORT = 8766
HELPER_PORT_TRIES = 10
BROWSER_SETTLE_SECONDS = 3.0

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


class DockerTimeout(Exception):
    """Subprocesso do Docker excedeu o tempo; o container nomeado já foi removido."""


def error_json(code: str, message: str, job_id: str = None) -> str:
    body = {"error": {"code": code, "message": message}}
    if job_id:
        body = dict([("job_id", job_id)] + list(body.items()))
    return json.dumps(body, ensure_ascii=False)


def parse_json(text: str):
    """Devolve o objeto JSON de uma resposta ou None se não for um objeto JSON válido."""
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def add_job_id(text: str, job_id: str) -> str:
    """Garante o job_id em respostas de erro de um trabalho já existente."""
    body = parse_json(text)
    if job_id and body is not None and "error" in body and "job_id" not in body:
        return json.dumps(dict([("job_id", job_id)] + list(body.items())), ensure_ascii=False)
    return text


def cli_name() -> str:
    return "whisper-box-cli-" + uuid.uuid4().hex[:8]


def platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def compose_base(root: Path = ROOT) -> list:
    return ["docker", "compose", "--project-directory", str(root),
            "-f", str(root / "compose.yaml")]


def path_problem(text: str, platform: str = None):
    """Motivo (código, mensagem) de um caminho que o bind mount não suporta, ou None."""
    platform = platform or platform_name()
    extended = text.startswith("\\\\?\\")
    plain = text[4:] if extended else text
    if platform == "windows" and not extended and text[:2] in ("\\\\", "//"):
        return ("unsupported_path", "Caminhos de rede (UNC, como \\\\servidor\\pasta) nao sao suportados "
                                    "(nao testados). Copie o arquivo para um disco local e informe esse caminho.")
    if ":" in re.sub(r"^[A-Za-z]:", "", plain):
        return ("unsupported_path", "O caminho contem ':' alem da letra da unidade, o que o bind mount nao "
                                    "aceita. Copie o arquivo para um caminho sem ':' e informe esse caminho.")
    return None


def submit_arguments(rest: list, name: str = None, platform: str = None) -> tuple:
    """Monta a chamada de submit e o bind mount somente leitura da gravação.

    Devolve (argumentos, None) ou (None, (código_erro, mensagem)).
    """
    rest = list(rest)
    try:
        index = rest.index("--input")
    except ValueError:
        index = -1
    if index < 0 or index + 1 >= len(rest) or not rest[index + 1].strip():
        return None, ("invalid_arguments", "Informe --input com o caminho da gravacao.")
    problem = path_problem(rest[index + 1], platform)
    if problem:
        return None, problem
    source = Path(rest[index + 1])
    if not source.is_file():
        return None, ("input_not_found", "Informe um arquivo de midia existente.")
    source = source.resolve()
    problem = path_problem(str(source), platform)
    if problem:
        return None, problem
    # O caminho é dado, nunca shell: subprocess recebe uma lista de argumentos.
    # `docker compose run` não tem --mount; o formato curto exige que o caminho não tenha ':'.
    container_path = "/source/recording" + source.suffix
    rest[index + 1] = container_path
    mount = str(source) + ":" + container_path + ":ro"
    return ["--profile", "tools", "run", "--rm"] + (["--name", name] if name else []) +         ["--no-deps", "-T", "--volume", mount, "cli", "submit"] + rest, None


def job_arguments(command: str, rest: list, name: str = None) -> list:
    return ["--profile", "tools", "run", "--rm"] + (["--name", name] if name else []) +         ["--no-deps", "-T", "cli", command] + list(rest)


def exec_arguments(command: str, rest: list) -> list:
    """Executa a CLI dentro do worker já em execução (sem criar container)."""
    return ["exec", "-T", "worker", "python", "-m", "whisper_box", command] + list(rest)


def start_arguments() -> list:
    return ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "90", "worker"]


def painel_arguments() -> list:
    return ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "30", "painel"]


def painel_url(env: dict = None) -> str:
    port = (env if env is not None else os.environ).get("WHISPER_BOX_PAINEL_PORT") or "8765"
    return "http://127.0.0.1:" + port + "/"


def run_to_stderr(arguments: list, env: dict, timeout: int = None) -> int:
    """Executa Docker enviando a saída dele para stderr, preservando stdout para JSON.

    Estouro de `timeout` encerra o processo e devolve 1 (diagnóstico em stderr).
    """
    sys.stderr.flush()
    try:
        try:
            return subprocess.run(arguments, stdout=sys.stderr.fileno(), env=env, timeout=timeout).returncode
        except (AttributeError, OSError, ValueError):
            completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env, timeout=timeout)
            sys.stderr.write(completed.stdout.decode("utf-8", "replace"))
            return completed.returncode
    except subprocess.TimeoutExpired:
        print("Tempo esgotado ao executar o Docker (%ss)." % timeout, file=sys.stderr, flush=True)
        return 1


def remove_container(name: str) -> None:
    """Remove, em melhor esforço, o container nomeado de uma chamada interrompida."""
    if not name:
        return
    try:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def capture(arguments: list, env: dict, timeout: int = JOB_TIMEOUT, name: str = None) -> tuple:
    """Executa a CLI do container e devolve (json_texto, código).

    Resposta ausente ou que não seja um objeto JSON vira `docker_error` (código 1). Estouro de
    `timeout` levanta DockerTimeout e Ctrl+C levanta KeyboardInterrupt, ambos após remover o container.
    """
    try:
        completed = subprocess.run(arguments, stdout=subprocess.PIPE, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        remove_container(name)
        raise DockerTimeout()
    except KeyboardInterrupt:
        remove_container(name)
        raise
    text = completed.stdout.decode("utf-8", "replace").strip()
    if parse_json(text) is None:
        reason = "Sem resposta do container." if not text else "Resposta do container nao e JSON."
        return error_json("docker_error", reason + " Execute doctor."), 1
    return text, completed.returncode


def capture_job(compose: list, command: str, rest: list, env: dict, timeout: int = JOB_TIMEOUT,
                name: str = None) -> tuple:
    """Como `capture`, mas consultas leves tentam `exec` no worker antes do `run --rm cli`.

    O fallback para `run` só ocorre quando o `exec` não devolve um objeto JSON (container ausente ou
    parado, comando indisponível). Resposta JSON do motor, inclusive de erro (códigos 1 a 4), é final.
    """
    if USE_EXEC and command in EXEC_COMMANDS:
        try:
            completed = subprocess.run(compose + exec_arguments(command, rest), stdout=subprocess.PIPE,
                                       env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise DockerTimeout()
        except OSError:
            completed = None
        if completed is not None:
            text = completed.stdout.decode("utf-8", "replace").strip()
            if parse_json(text) is not None:
                return text, completed.returncode
    return capture(compose + job_arguments(command, rest, name), env, timeout, name)


def interruption(error: BaseException, job_id: str = None) -> str:
    if isinstance(error, DockerTimeout):
        return error_json("docker_timeout", "O Docker nao respondeu no tempo esperado. Execute doctor.", job_id)
    return error_json("interrupted", "Execucao interrompida pelo usuario.", job_id)


def run_cli(arguments: list, env: dict, out, timeout: int = JOB_TIMEOUT, name: str = None,
            job_id: str = None, job: tuple = None) -> int:
    """`job` = (compose, comando, argumentos) usa `capture_job` (exec com fallback) no lugar de `arguments`."""
    try:
        if job is not None:
            text, code = capture_job(job[0], job[1], job[2], env, timeout, name)
        else:
            text, code = capture(arguments, env, timeout, name)
    except (DockerTimeout, KeyboardInterrupt) as error:
        print(interruption(error, job_id), file=out)
        return 1
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
    except OSError:  # inclui PermissionError
        return None, "sem permissao"
    return completed.returncode, completed.stdout.decode("utf-8", "replace").strip()


def source_digest(root: Path = None) -> str:
    """SHA-256 do código que vai para a imagem (Dockerfile, requirements.lock, src/**/*.py, whisper-box.py)."""
    root = ROOT if root is None else root
    files = [root / "Dockerfile", root / "requirements.lock", root / "whisper-box.py"]
    files += sorted((root / "src").rglob("*.py"), key=lambda item: item.relative_to(root).as_posix())
    digest = hashlib.sha256()
    for path in files:
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def model_problem(root: Path = None):
    """None se modelos/manifest.json é íntegro (JSON, revisão, arquivos com o tamanho registrado)."""
    root = ROOT if root is None else root
    manifest_path = root / "modelos" / "manifest.json"
    if not manifest_path.is_file():
        return "ausente"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(manifest["revision"], str) or not manifest["revision"] \
                or not isinstance(files, dict) or not files:
            return "manifest.json incompleto"
        for name, entry in files.items():
            size = entry["size"]
            path = root / "modelos" / "small" / name
            if isinstance(size, bool) or not isinstance(size, int) or not path.is_file() \
                    or path.stat().st_size != size:
                return "arquivo do modelo ausente ou com tamanho diferente: " + str(name)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "manifest.json invalido"
    return None


def doctor(out) -> int:
    """Diagnostica o host e indica um único próximo passo para o agente."""
    platform = platform_name()
    checks = {"python": {"ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0]}}
    steps = []
    cpus = os.environ.get("WHISPER_BOX_CPUS", "").strip()
    if cpus and cpus != "2":  # informativo: o padrao (2 CPUs) nao aparece
        threads = os.environ.get("WHISPER_BOX_CPU_THREADS", "").strip() or cpus
        checks["cpus"] = {"ok": True, "detail": "WHISPER_BOX_CPUS=%s, threads=%s (padrao 2)" % (cpus, threads)}

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
    code, label = probe(["docker", "image", "inspect", "--format",
                         '{{ index .Config.Labels "' + DIGEST_LABEL + '" }}', IMAGE])
    image_ready = check("image", code == 0, IMAGE if code == 0 else "ausente")
    problem = model_problem()
    model_ready = check("model", problem is None, "modelos/manifest.json" if problem is None else problem)
    if not (image_ready and model_ready):
        action = ("Execute: python whisper-box.py prepare (uma vez, com internet; baixa imagem e "
                  "modelo de aproximadamente 500 MB).")
        if problem not in (None, "ausente"):
            action += " O modelo existente parece corrompido: peca ao usuario para preservar ou renomear modelos/ antes."
        steps.append({"code": "prepare", "requires_user_approval": True, "action": action})
    elif label and label not in ("<no value>", "unknown"):
        # Imagem construída sem o rótulo (docker compose build direto) não é comparável e é aceita.
        current = source_digest()
        check("image_current", label == current,
              "atual" if label == current else "codigo local difere da imagem",
              {"code": "rebuild", "requires_user_approval": False,
               "action": "Execute: python whisper-box.py stop e depois docker compose build --build-arg "
                         "SOURCE_DIGEST=" + current + " worker; em seguida rode doctor de novo."})
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
    if args.job is not None and args.language:
        raise ArgumentError("--language so se aplica a --input.")
    if not 1 <= args.timeout_seconds <= 86400:
        raise ArgumentError("--timeout-seconds deve estar entre 1 e 86400.")
    if args.input is not None and not args.input.strip():
        raise ArgumentError("--input nao pode ser vazio.")
    if args.job is not None and not JOB_ID_PATTERN.fullmatch(args.job):
        raise ArgumentError("--job deve ser um identificador de 32 caracteres hexadecimais.")

    compose = compose_base()
    submit_call = None
    submit_name = None
    if args.input is not None:
        submit_name = cli_name()
        submit_call, failure = submit_arguments(["--input", args.input, "--language", args.language or "pt"],
                                                submit_name)
        if failure:
            print(error_json(*failure), file=out)
            return 3
    deadline = time.monotonic() + args.timeout_seconds
    job_id = args.job

    def job_call(command, extra, timeout):
        """Chama o container e repete (até 2 vezes) só em falha transitória do Docker."""
        attempt = 0
        while True:
            name = cli_name()
            try:
                text, code = capture_job(compose, command, extra, env, timeout, name)
            except (OSError, subprocess.SubprocessError) as error:
                print(json.dumps({"event": "whisper_docker_failure", "type": type(error).__name__}),
                      file=sys.stderr, flush=True)
                text, code = error_json("docker_error", "Falha ao executar o Docker. Execute doctor."), 1
            body = parse_json(text) or {}
            transient = (body.get("error") or {}).get("code") == "docker_error"
            if not transient or attempt >= len(RETRY_DELAYS):
                return text, code
            delay = RETRY_DELAYS[attempt]
            if time.monotonic() + delay >= deadline:
                return text, code
            print(json.dumps({"event": "whisper_retry", "job_id": job_id, "in_seconds": delay}),
                  file=sys.stderr, flush=True)
            time.sleep(delay)
            attempt += 1

    try:
        if run_to_stderr(compose + start_arguments(), env, START_TIMEOUT) != 0:
            print(error_json("docker_error", "O worker nao iniciou. Execute doctor."), file=out)
            return 1
        if submit_call is not None:
            text, code = capture(compose + submit_call, env, SUBMIT_TIMEOUT, submit_name)
            job_id = (parse_json(text) or {}).get("job_id")
            if code != 0 or not job_id:
                print(text if code != 0 else error_json("docker_error", "O submit nao devolveu job_id."), file=out)
                return code or 1
        print(json.dumps({"event": "whisper_waiting", "job_id": job_id}), file=sys.stderr, flush=True)

        observed = {}
        while True:
            remaining = math.ceil(deadline - time.monotonic())
            if remaining <= 0:
                print(json.dumps({"job_id": job_id, "status": observed.get("status"), "timed_out": True,
                                  "wait_budget_exhausted": True}), file=out)
                return 2
            wait_seconds = min(30, remaining)
            text, code = job_call("wait", ["--job", job_id, "--timeout", str(wait_seconds)], wait_seconds + 60)
            if code == 2:
                observed = parse_json(text) or {}
                continue
            if code != 0:
                print(add_job_id(text, job_id), file=out)
                return code
            # `wait` bem-sucedido já traz files e output_relative (mesmo status(include_files=True)).
            files = (parse_json(text) or {}).get("files") or {}
            if not all(isinstance(files.get(key), str) and Path(files[key]).is_file() for key in ARTIFACTS):
                print(error_json("output_unreachable", "Artefatos ausentes ou inacessiveis pelo host.", job_id),
                      file=out)
                return 1
            print(text, file=out)
            return 0
    except (DockerTimeout, KeyboardInterrupt) as error:
        print(interruption(error, job_id), file=out)
        return 1


# -- Janela própria do painel e ajudante de host ---------------------------------

def find_browser(env: dict = None, platform: str = None, exists=os.path.isfile, which=shutil.which):
    """Localiza Edge ou Chrome; WHISPER_BOX_NAVEGADOR tem prioridade. Devolve o caminho ou None."""
    env = os.environ if env is None else env
    platform = platform or platform_name()
    explicit = env.get("WHISPER_BOX_NAVEGADOR")
    if explicit:
        return explicit if exists(explicit) else None
    candidates = []
    if platform == "windows":
        # Cópias de os.environ (dict comum) têm chaves em maiúsculas no Windows: busca sem caixa.
        upper = {str(key).upper(): value for key, value in env.items()}
        bases = [upper.get(key) for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for relative in (("Microsoft", "Edge", "Application", "msedge.exe"),
                         ("Google", "Chrome", "Application", "chrome.exe")):
            candidates += [ntpath.join(base, *relative) for base in bases if base]
    elif platform == "macos":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for candidate in candidates:
        if exists(candidate):
            return candidate
    if platform in ("windows", "linux"):
        names = ("msedge",) if platform == "windows" else \
            ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")
        for name in names:
            found = which(name)
            if found:
                return found
    return None


def browser_arguments(browser: str, url: str, root: Path = None) -> list:
    root = ROOT if root is None else root
    return [browser, "--app=" + url, "--user-data-dir=" + str(root / ".navegador"),
            "--window-size=380,640", "--no-first-run", "--no-default-browser-check"]


def open_folder(path: Path) -> None:
    """Abre a pasta no gerenciador de arquivos do sistema (lista de argumentos, sem shell)."""
    platform = platform_name()
    if platform == "windows":
        os.startfile(str(path))  # noqa: S606 - caminho validado pelo ajudante
    else:
        subprocess.Popen(["open" if platform == "macos" else "xdg-open", str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def helper_handler(token: str, helper_port: int, panel_port: int, root: Path, opener):
    """Cria o manipulador do ajudante: uma única rota, POST /abrir-pasta."""
    hosts = {"127.0.0.1:%d" % helper_port, "localhost:%d" % helper_port}
    origins = {"http://127.0.0.1:%d" % panel_port, "http://localhost:%d" % panel_port}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "WhisperBoxAjudante"
        sys_version = ""
        timeout = 10

        def log_message(self, format, *args):  # noqa: A002 - sem log de requisições
            pass

        def _reply(self, status: int, code: str = None, message: str = None):
            body = b""
            if code:
                body = json.dumps({"error": {"code": code, "message": message}},
                                  ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if body:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            if status != 204:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if body:
                self.wfile.write(body)

        def _checked(self) -> bool:
            if self.path.split("?", 1)[0] != "/abrir-pasta":
                self._reply(404, "rota_inexistente", "Rota inexistente.")
                return False
            if (self.headers.get("Host") or "").lower() not in hosts:
                self._reply(421, "host_invalido", "Host não permitido.")
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in origins:
                self._reply(403, "origem_invalida", "Origem não permitida.")
                return False
            return True

        def do_OPTIONS(self):
            if not self._checked():
                return
            if self.headers.get("Origin") is None:
                return self._reply(403, "origem_invalida", "Origem ausente.")
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Whisper-Box-Token")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_POST(self):
            if not self._checked():
                return
            supplied = self.headers.get("X-Whisper-Box-Token") or ""
            if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                return self._reply(403, "token_invalido", "Token inválido.")
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isdigit() or not 0 < int(raw_length) <= 1024:
                return self._reply(400, "corpo_invalido", "Corpo JSON ausente ou grande demais.")
            try:
                data = json.loads(self.rfile.read(int(raw_length)))
                job_id = data.get("job_id") if isinstance(data, dict) else None
            except ValueError:
                job_id = None
            if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
                return self._reply(400, "job_id_invalido", "job_id inválido.")
            folder = root / "saida" / job_id
            if not folder.is_dir():
                return self._reply(404, "pasta_inexistente", "A pasta do resultado não existe.")
            try:
                opener(folder)
            except (OSError, subprocess.SubprocessError):
                return self._reply(500, "abrir_falhou", "Não foi possível abrir a pasta.")
            self._reply(204)

        def do_GET(self):
            self._reply(404, "rota_inexistente", "Rota inexistente.")

        do_HEAD = do_PUT = do_DELETE = do_PATCH = do_GET

    return Handler


def start_helper(token: str, panel_port: int, root: Path = None, opener=open_folder, base_port: int = None):
    """Sobe o ajudante em loopback; tenta as próximas portas se a primeira estiver ocupada."""
    root = ROOT if root is None else root
    if base_port is None:
        base_port = int(os.environ.get("WHISPER_BOX_AJUDANTE_PORT") or HELPER_PORT)
    tries = 1 if base_port == 0 else HELPER_PORT_TRIES + 1
    last_error = None
    for offset in range(tries):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", base_port + offset), BaseHTTPRequestHandler)
        except OSError as error:
            last_error = error
            continue
        port = server.server_address[1]
        server.RequestHandlerClass = helper_handler(token, port, panel_port, root, opener)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        thread.start()
        return server, port
    raise last_error


def panel(env: dict, out, stop: threading.Event = None) -> int:
    """Abre o painel em janela própria (Edge/Chrome em modo app) com o ajudante de host ativo."""
    compose = compose_base()
    if run_to_stderr(compose + start_arguments(), env) != 0:
        print(error_json("docker_error", "O worker nao iniciou. Execute doctor."), file=out)
        return 1
    if run_to_stderr(compose + painel_arguments(), env) != 0:
        print(error_json("docker_error", "O painel nao iniciou. Consulte stderr e execute doctor."), file=out)
        return 1
    url = painel_url(env)
    browser = find_browser(env)
    if not browser:
        print(error_json("browser_not_found", "Edge ou Chrome nao encontrado (ou defina WHISPER_BOX_NAVEGADOR). "
                                              "Abra manualmente: " + url), file=out)
        return 1
    panel_port = int(url.rsplit(":", 1)[1].strip("/"))
    token = secrets.token_urlsafe(24)
    server, helper_port = start_helper(token, panel_port)
    stop = stop or threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM"):
            try:
                previous[name] = signal.signal(getattr(signal, name), lambda *_: stop.set())
            except (AttributeError, ValueError, OSError):
                pass
    open_url = "%s?ajudante=%d&token=%s" % (url, helper_port, token)
    try:
        process = subprocess.Popen(browser_arguments(browser, open_url))
    except OSError:
        server.shutdown()
        server.server_close()
        print(error_json("browser_not_found", "Nao foi possivel iniciar o navegador. Abra manualmente: " + url),
              file=out)
        return 1
    print(json.dumps({"status": "open", "painel_url": url, "ajudante_port": helper_port},
                     ensure_ascii=False, separators=(",", ":")), file=out, flush=True)
    print("Ajudante em 127.0.0.1:%d. Feche a janela do painel ou use Ctrl+C para encerrar." % helper_port,
          file=sys.stderr, flush=True)
    try:
        # Se o navegador sair logo (instância já aberta com este perfil), o ajudante segue até Ctrl+C.
        detached = not stop.wait(BROWSER_SETTLE_SECONDS) and process.poll() is not None
        if detached:
            print("O navegador ja estava aberto com este perfil; o ajudante segue ate Ctrl+C.",
                  file=sys.stderr, flush=True)
        while not stop.is_set() and (detached or process.poll() is None):
            stop.wait(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if process.poll() is None:
            process.terminate()
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)
    return 0


def local_offset_minutes(now: float = None) -> int:
    """Deslocamento do fuso local do host em relação a UTC, em minutos (inclui horário de verão)."""
    offset = getattr(time.localtime(now), "tm_gmtoff", None)
    return int(offset // 60) if offset is not None else 0


def job_from(rest: list):
    """Valor de --job em uma lista de argumentos, se for um job_id bem formado."""
    for index, item in enumerate(rest[:-1]):
        if item == "--job" and JOB_ID_PATTERN.fullmatch(rest[index + 1]):
            return rest[index + 1]
    return None


def wait_timeout(rest: list) -> int:
    for index, item in enumerate(rest[:-1]):
        if item == "--timeout" and rest[index + 1].isdigit():
            return min(int(rest[index + 1]), 3600)
    return 30


def prepare(compose: list, env: dict, out) -> int:
    """Build da imagem (saída para stderr) e preparo do modelo; stdout recebe um único JSON."""
    build = compose + ["build", "--build-arg", "SOURCE_DIGEST=" + source_digest(), "worker"]
    if run_to_stderr(build, env, None) != 0:
        print(error_json("docker_error", "Falha no Docker. Consulte stderr e execute doctor."), file=out)
        return 1
    name = cli_name()
    try:
        text, code = capture(compose + ["--profile", "setup", "run", "--rm", "--name", name, "--no-deps", "-T",
                                        "prepare"], env, PREPARE_TIMEOUT, name)
    except (DockerTimeout, KeyboardInterrupt) as error:
        print(interruption(error), file=out)
        return 1
    if code == 0:
        print(text, file=out)
        return 0
    body = parse_json(text) or {}
    if "error" in body:
        print(text, file=out)
    else:
        print(error_json("docker_error", "Falha no Docker. Consulte stderr e execute doctor."), file=out)
    return 1


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
    if command == "painel":
        return panel(env, out)
    if command == "transcribe":
        try:
            return transcribe(rest, env, out)
        except ArgumentError as error:
            print(error_json("invalid_arguments", str(error)), file=out)
            return 3
    if command == "prepare":
        return prepare(compose, env, out)
    elif command == "start":
        code = run_to_stderr(compose + start_arguments(), env, START_TIMEOUT)
        if code == 0:
            body = {"status": "ready"}
            # O painel e opcional: sua falha nunca altera o codigo de saida.
            if run_to_stderr(compose + painel_arguments(), env) == 0:
                body["painel_url"] = painel_url(env)
            else:
                body["painel_error"] = "O painel nao iniciou. O worker segue disponivel; consulte stderr."
            print(json.dumps(body, ensure_ascii=False, separators=(",", ":")), file=out)
    elif command == "stop":
        code = run_to_stderr(compose + ["stop", "worker", "painel"], env, JOB_TIMEOUT)
        if code == 0:
            print('{"status":"stopped"}', file=out)
    elif command == "logs":
        out.flush()
        code = subprocess.run(compose + ["logs", "--tail", "50", "worker"], env=env).returncode
    elif command == "submit":
        name = cli_name()
        arguments, failure = submit_arguments(rest, name)
        if failure:
            print(error_json(*failure), file=out)
            return 3
        code = run_cli(compose + arguments, env, out, SUBMIT_TIMEOUT, name)
    elif command in JOB_COMMANDS:
        name = cli_name()
        timeout = JOB_TIMEOUT
        if command == "list":
            # O container roda em UTC; o deslocamento do host faz --since/--until e os horários usarem o fuso local.
            rest = rest + ["--utc-offset-minutes", str(local_offset_minutes())]
        elif command == "wait":
            timeout = wait_timeout(rest) + 60
        elif command == "purge":
            timeout = PURGE_TIMEOUT
        code = run_cli(None, env, out, timeout, name, job_from(rest), (compose, command, rest))
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
    except KeyboardInterrupt:
        print(error_json("interrupted", "Execucao interrompida pelo usuario."))
        return 1
    except Exception as error:  # nenhum traceback em stdout; só o tipo vai para stderr
        print("Falha inesperada (%s)." % type(error).__name__, file=sys.stderr, flush=True)
        print(error_json("operational_error", "Nao foi possivel executar o comando. Execute doctor."))
        return 1


if __name__ == "__main__":
    sys.exit(entrypoint())
