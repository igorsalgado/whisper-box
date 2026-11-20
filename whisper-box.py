#!/usr/bin/env python3
"""Wrapper multiplataforma do Whisper Box.

Usa somente a biblioteca padrão (Python 3.8+) e delega todo o trabalho ao
Docker Compose. stdout recebe exatamente um objeto JSON nos comandos de
contrato; diagnósticos do Docker seguem para stderr.

Agentes: comece por `doctor` e transcreva com `transcribe --input CAMINHO`.
"""
import argparse
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = "doctor, prepare, start, stop, painel, transcribe, submit, status, wait, result ou logs"
JOB_COMMANDS = ("status", "wait", "result")
LIFECYCLE_COMMANDS = ("prepare", "start", "stop")
ARTIFACTS = ("text", "srt", "segments", "metadata")
IMAGE = "whisper-box:local"
JOB_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
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


def painel_arguments() -> list:
    return ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "30", "painel"]


def painel_url(env: dict = None) -> str:
    port = (env if env is not None else os.environ).get("WHISPER_BOX_PAINEL_PORT") or "8765"
    return "http://127.0.0.1:" + port + "/"


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
        code = run_to_stderr(compose + ["build", "worker"], env)
        if code == 0:
            out.flush()
            code = subprocess.run(compose + ["--profile", "setup", "run", "--rm", "--no-deps", "-T", "prepare"],
                                  env=env).returncode
    elif command == "start":
        code = run_to_stderr(compose + start_arguments(), env)
        if code == 0:
            body = {"status": "ready"}
            # O painel e opcional: sua falha nunca altera o codigo de saida.
            if run_to_stderr(compose + painel_arguments(), env) == 0:
                body["painel_url"] = painel_url(env)
            else:
                body["painel_error"] = "O painel nao iniciou. O worker segue disponivel; consulte stderr."
            print(json.dumps(body, ensure_ascii=False, separators=(",", ":")), file=out)
    elif command == "stop":
        code = run_to_stderr(compose + ["stop", "worker", "painel"], env)
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
