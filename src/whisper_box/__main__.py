import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .config import BoxError, Settings


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BoxError("invalid_arguments", message, 3)


def date_argument(value: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("use datas no formato AAAA-MM-DD.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("data inexistente: " + value) from None


def main():
    parser = Parser(description="Whisper Box: transcrição local, sem API.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "worker", "health", "painel"):
        commands.add_parser(name)
    submit_parser = commands.add_parser("submit")
    submit_parser.add_argument("--input", required=True, type=Path)
    submit_parser.add_argument("--language", default="pt")
    for name in ("status", "wait", "result"):
        command = commands.add_parser(name)
        command.add_argument("--job", required=True)
        if name == "wait":
            command.add_argument("--timeout", default=30, type=int)
    list_parser = commands.add_parser("list")
    list_parser.add_argument("--status", choices=("queued", "running", "succeeded", "failed"))
    list_parser.add_argument("--since", type=date_argument)
    list_parser.add_argument("--until", type=date_argument)
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--utc-offset-minutes", type=int, default=0)
    args = parser.parse_args()
    settings = Settings.from_env()
    code = 0
    if args.command == "prepare":
        from .model import prepare
        response = prepare(settings.models)
    elif args.command == "worker":
        from .worker import run
        run(settings)
        return 0
    elif args.command == "painel":
        from .painel import serve
        serve(settings)
        return 0
    elif args.command == "health":
        from .jobs import require_worker
        require_worker(settings)
        return 0
    elif args.command == "submit":
        from .jobs import submit
        response = submit(settings, args.input, args.language)
    elif args.command == "list":
        from .jobs import list_jobs
        response = list_jobs(settings, args.status, args.since, args.until, args.limit,
                             args.utc_offset_minutes)
    elif args.command == "wait":
        from .jobs import wait
        response, code = wait(settings, args.job, args.timeout)
    else:
        from .jobs import status
        response = status(settings, args.job, include_files=args.command == "result")
        if args.command == "result":
            code = {"succeeded": 0, "failed": 1}.get(response["status"], 4)
    print(json.dumps(response, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BoxError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}, ensure_ascii=False))
        raise SystemExit(error.exit_code)
    except Exception as error:
        print(json.dumps({"error": {"code": "operational_error",
                                   "message": f"Falha operacional ({type(error).__name__}). Consulte o ambiente local."}}))
        raise SystemExit(1)
