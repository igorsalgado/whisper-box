import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_analise  # noqa: E402

TRANSCRICAO = (
    "[00:00:00–00:00:04] Texto sintético um.\n"
    "[00:01:05–00:01:09] Texto sintético dois.\n"
    "[01:02:03–01:02:10] Texto sintético três.\n"
)

BOA = """# Análise
Aviso de transcrição automática.

## Resumo
Resumo sintético sem citações.

## Decisões
- Decisão A. [00:00:00]
- Decisão B. [00:01:05] [01:02:03]

## Tarefas
| Tarefa | Responsável | Prazo | Horário |
| --- | --- | --- | --- |
| Fazer X | não informado | não informado | [00:01:05] |

## Pontos em aberto
Nenhum ponto em aberto.
"""


class CheckAnaliseTests(unittest.TestCase):
    def run_check(self, analise, transcricao=TRANSCRICAO):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "analise.md"
            t = Path(folder) / "transcricao.txt"
            a.write_text(analise, encoding="utf-8")
            t.write_text(transcricao, encoding="utf-8")
            return check_analise.check(a, t)

    def problems(self, analise):
        return [item["problem"] for item in self.run_check(analise)["problems"]]

    def test_analise_valida(self):
        result = self.run_check(BOA)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["items_checked"], 3)

    def test_item_sem_horario(self):
        self.assertEqual(self.problems(BOA.replace("Decisão A. [00:00:00]", "Decisão A.")), ["sem_horario"])

    def test_horario_inexistente(self):
        self.assertEqual(self.problems(BOA.replace("[00:01:05] [01:02:03]", "[00:01:06]")),
                         ["horario_inexistente"])

    def test_horario_de_fim_nao_conta(self):
        self.assertEqual(self.problems(BOA.replace("Decisão A. [00:00:00]", "Decisão A. [00:00:04]")),
                         ["horario_inexistente"])

    def test_campo_vazio_na_tabela(self):
        analise = BOA.replace("| não informado | não informado |", "| João |  |")
        self.assertEqual(self.problems(analise), ["campo_vazio"])

    def test_secao_fora_do_escopo_nao_exige_horario(self):
        self.assertTrue(self.run_check(BOA.replace("Resumo sintético sem citações.", "Outro texto."))["ok"])

    def test_transcricao_sem_segmentos(self):
        problems = [p["problem"] for p in self.run_check(BOA, "")["problems"]]
        self.assertIn("transcricao_sem_segmentos", problems)

    def test_arquivo_inexistente_retorna_1(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = check_analise.main(["--analise", "nao-existe.md", "--transcricao", "nao-existe.txt"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
