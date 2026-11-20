#!/usr/bin/env python3
"""Verifica as citações de horário de um analise.md contra transcricao.txt.

Somente biblioteca padrão. Saída: um JSON em stdout; código 0 (ok) ou 1.
Não é descoberto pelo unittest (o nome não começa com "test").
"""
import argparse
import json
import re
import sys
from pathlib import Path

SECTIONS = ("decisões", "tarefas", "pontos em aberto")
CITATION = re.compile(r"\[(\d{2,}:[0-5]\d:[0-5]\d)\]")
SEGMENT_START = re.compile(r"^\[(\d{2,}:[0-5]\d:[0-5]\d)–\d{2,}:[0-5]\d:[0-5]\d\]")
EMPTY_MARK = re.compile(r"^(?:[-*]\s*)?nenhum[a-z]?\b", re.IGNORECASE)


def segment_starts(path):
    starts = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = SEGMENT_START.match(line)
        if match:
            starts.add(match.group(1))
    return starts


def split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator(line):
    return bool(re.fullmatch(r"\|?[\s:|-]+\|?", line)) and "-" in line


def check(analise_path, transcricao_path):
    starts = segment_starts(transcricao_path)
    problems = []
    if not starts:
        problems.append({"line": 0, "problem": "transcricao_sem_segmentos"})
    section = None
    header = None
    checked = 0
    for number, raw in enumerate(Path(analise_path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            section = title if title in SECTIONS else None
            header = None
            continue
        if section is None or not line:
            continue
        is_table = line.startswith("|")
        if is_table and header is None:
            header = [cell.lower() for cell in split_row(line)]
            continue
        if is_table and is_separator(line):
            continue
        if EMPTY_MARK.match(line):
            continue
        checked += 1
        cites = CITATION.findall(line)
        if not cites:
            problems.append({"line": number, "problem": "sem_horario"})
        for cite in cites:
            if cite not in starts:
                problems.append({"line": number, "problem": "horario_inexistente", "value": cite})
        if is_table and header:
            cells = split_row(line)
            if len(cells) != len(header):
                problems.append({"line": number, "problem": "colunas_divergentes"})
            for name, cell in zip(header, cells):
                if name in ("responsável", "responsavel", "prazo") and not cell:
                    problems.append({"line": number, "problem": "campo_vazio", "value": name})
    return {"ok": not problems, "items_checked": checked, "problems": problems}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analise", required=True)
    parser.add_argument("--transcricao", required=True)
    args = parser.parse_args(argv)
    try:
        result = check(args.analise, args.transcricao)
    except OSError as error:
        result = {"ok": False, "items_checked": 0,
                  "problems": [{"line": 0, "problem": "arquivo_ilegivel", "value": error.__class__.__name__}]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
