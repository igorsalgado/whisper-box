# A03 — Contrato do motor (ex-F0 da A02)

Data: 20/11/2026
Estado: executada em 20/11/2026 (código e testes entregues; sem commit)
Prioridade: 1 (bloqueia A05 e reduz conflito em A04 e A06)
Tamanho: M (uma sessão de um agente `dev-backend`)
Projeto: Whisper Box (`whisper-box`)
Origem: fase F0 da [A02](A02-captura-ingestao-analise.md); achados I1 a I6 da revisão de código e itens menores.
Depende de: [A01](A01-transcricao-offline-docker.md) (motor, fila e CLI, validados) e do painel entregue (A02/F3).

## 1. Contexto

O motor (faster-whisper `small`, CPU, `int8`) e o contrato da CLI foram validados na A01. A revisão de código posterior encontrou defeitos que quebram o contrato para clientes automáticos (agentes que leem stdout como JSON, regra 7 do README) e que continuam abertos no HEAD `da88101`:

| Id | Defeito | Onde está |
| --- | --- | --- |
| I1 | `prepare` com falha no container imprime **dois** JSON em stdout: o do container herda o stdout (`whisper-box.py:514`) e o wrapper acrescenta `docker_error` (`whisper-box.py:545-546`). | `whisper-box.py:510-515`, `:545-546` |
| I2 | Erro transitório do Docker durante a espera derruba `transcribe` sem `job_id` no stdout: `capture` devolve `docker_error` genérico (`:134-135`) e o loop o imprime e sai (`:246-248`); um `json.loads` inválido (`:230`, `:244`) cai no `except` do entrypoint (`:558-560`), também sem `job_id`. | `whisper-box.py:224-254`, `:550-560` |
| I3 | `transcribe --input ""` ou `--job ""` passa pelo grupo obrigatório do argparse, mas os testes de veracidade `if args.input` (`:215`, `:224`) tratam `""` como ausente; `job_id` fica `None`, a lista de argumentos recebe `None` e estoura `TypeError`, que o entrypoint não captura (`:558` só captura `OSError`, `SubprocessError`, `ValueError`, `KeyError`): traceback e stdout vazio. | `whisper-box.py:202-230`, `:558` |
| I4 | Caminho POSIX com `:` quebra o bind mount curto `origem:destino:ro`. | `whisper-box.py:97` |
| I5 | `status` expõe `error: interrupted` em job re-enfileirado: `recover` grava `error_code='interrupted'` ao recolocar na fila (`store.py:99-107`), `claim` não limpa (`store.py:89-92`) e `status` mostra o erro sempre que há código (`jobs.py:94-95`). O painel repete o padrão (`painel.py:430-431`). | `store.py`, `jobs.py`, `painel.py` |
| I6 | Job `succeeded` com `saida/<job_id>/` apagada fica preso em `output_incomplete` (`jobs.py:96-98`), e a deduplicação reutiliza o job (`store.py:67-71`, índice único parcial em `store.py:34-35`), então reenviar a mesma mídia nunca reprocessa. | `store.py:64-79`, `jobs.py:62-69`, `jobs.py:73-84` |

Itens menores já identificados: Ctrl+C sem tratamento e sem timeout nos subprocessos (`capture` em `:130-136`, `run_to_stderr` em `:119-127`); `doctor` apenas confere a existência de `modelos/manifest.json` (`:182-183`) e não detecta imagem defasada (`:180-181`); `probe` não captura `PermissionError` (`:145-153`); caminhos UNC; ausência do comando `list` embora `Store.list` exista (`store.py:58-62`, usado por `painel.py:436-438`); `result` redundante depois de `wait` bem-sucedido (`:249-254`); lacunas de teste em `tests/test_wrapper.py`.

Esta action não altera inferência: `pipeline_version` (`src/whisper_box/__init__.py:3`) e `effective_config` (`config.py:38-53`) permanecem como estão.

## 2. Objetivo

Um cliente automático da CLI recebe **sempre exatamente um JSON em stdout**, com `job_id` quando já existe, código de saída do conjunto 0–4, sem traceback; jobs com saída perdida podem ser reprocessados; e o agente ganha o comando `list` para localizar transcrições (pré-requisito da [A05](A05-skill-de-analise.md)).

Métrica de leitura: falhas I1 a I6 reproduzíveis = 0 (métrica da A02, seção 11).

## 3. Escopo

Parte A (obrigatória): I1 a I6, comando `list`, testes.
Parte B (menores, entregar se couber, na ordem listada): Ctrl+C e timeouts, `result` redundante, `PermissionError`, UNC, `doctor` mais rigoroso, lacunas de teste, atualização de documentação.

## 4. Fora de escopo

- Qualquer mudança de inferência, de modelo, de `effective_config` ou de `pipeline_version`.
- Retenção, `purge` e limpeza de `saida/.partial/` ([A04](A04-retencao-e-limpeza-de-disco.md)).
- `docker compose exec` para consultas rápidas e checkpoint ([A06](A06-desempenho-e-robustez-do-motor.md)).
- Novos formatos de saída; mudanças de API do painel (exceto I5 em `_summary`).
- Pasta vigiada (backlog; ver [README das actions](README.md)).

## 5. Tarefas

Cada tarefa é um commit coerente, em português, Conventional Commits. `whisper-box.py` continua só com biblioteca padrão e **compatível com Python 3.8** (sem `X | Y` em tipos, sem `match`, sem `list[str]` avaliado em tempo de execução). O código dentro da imagem pode usar 3.12.

### Parte A

1. **I1: um único JSON em `prepare`** (`whisper-box.py:510-515`, `:545-546`).
   - Capturar o stdout do container `prepare` (como `capture`, `:130-136`) em vez de herdá-lo; o stderr dele segue para stderr.
   - Sucesso: imprimir o JSON do container uma vez, código 0. Falha: imprimir **um** JSON de erro (o do container se for JSON válido com `error`; senão `docker_error`) e código 1. O `build` continua enviando sua saída para stderr (`run_to_stderr`).
   - Remover o `print` duplicado em `:545-546` para `prepare` (continua valendo para `start` e `stop`, que não imprimem JSON do container em falha).

2. **I2: `job_id` em todo erro pós-submit e retry curto** (`whisper-box.py:224-261`).
   - Depois que o `job_id` existe (retornado pelo `submit` em `:230` ou recebido em `--job`), todo erro impresso em stdout inclui `{"job_id": "...", "error": {...}}`. Isso cobre: falha do `capture` de `wait`, JSON inválido em `wait` ou `result` e `output_unreachable` (já inclui, `:257`).
   - Retry curto **apenas** para falha transitória de infraestrutura (resposta vazia ou sem JSON, que `capture` converte em `docker_error` em `:134-135`; ou exceção de `subprocess`): até 2 novas tentativas, com espera de 2 s e 5 s, dentro do orçamento `--timeout-seconds`. Erros definitivos devolvidos pelo motor (`job_not_found`, `failed`, `output_incomplete`) **não** sofrem retry.
   - Encapsular `json.loads` do retorno do container em um helper que devolve erro estruturado (`docker_error`) em vez de levantar `ValueError`.

3. **I3: entradas vazias e exceções inesperadas** (`whisper-box.py:202-230`, `:550-560`).
   - Validar com `is not None`: `--input ""` e `--job ""` devolvem `{"error":{"code":"invalid_arguments",...}}` com código 3. Validar também `--job` contra `JOB_ID_PATTERN` (`:33`) antes de qualquer chamada Docker (código 3, `invalid_arguments`; `job_not_found` continua para ids bem formados que não existem).
   - O entrypoint passa a capturar `Exception` (além das atuais) e responde `operational_error` com código 1, **sem traceback em stdout**; o tipo da exceção vai para stderr (sem caminhos nem conteúdo).

4. **I4: bind mount com `:`** (`whisper-box.py:78-99`).
   - Verificar se o Compose instalado aceita `docker compose run --mount type=bind,source=...,target=...,readonly` (o ambiente validado tem Compose v5.5.1). Se aceitar, usar a sintaxe longa para todos os caminhos. Se não aceitar, **rejeitar** na validação, antes do Docker, caminho POSIX contendo `:` com `{"error":{"code":"unsupported_path","message":"..."}}` e código 3, orientando a copiar o arquivo para um caminho sem `:`. Registrar a escolha em `docs/VALIDACAO.md`.
   - Caminhos do Windows (`C:\...`) continuam funcionando; o teste cobre os dois formatos.

5. **I5: `error` só em `failed`** (`store.py:81-107`, `jobs.py:94-95`, `painel.py:430-431`).
   - `Store.claim` zera `error_code` e `error_message` ao assumir o job. Por defesa, `jobs.status` e `painel._summary` só expõem `error` quando `status == 'failed'`. A contagem `interruptions` continua registrada e aparece em `metadados.json` (`pipeline.py:108`).
   - `interrupted_limit` (`store.py:104`) continua visível, pois o job termina `failed`.

6. **I6: reprocessar quando a saída foi perdida** (`store.py:64-79`, `jobs.py:62-69`, `jobs.py:73-84`).
   - Em `submit`, antes de reutilizar um job `succeeded`, verificar `complete_output` (`jobs.py:73-84`). Se a saída estiver ausente ou inválida: marcar o job antigo como `failed` com `error_code='output_lost'` e mensagem curta (liberando o índice único parcial de `store.py:34-35`) **e** criar um novo job na mesma transação, devolvendo `reused: false` e o novo `job_id`. O histórico do antigo é preservado; nada em `saida/` é apagado ou movido.
   - Implementação sugerida: `Store.enqueue(..., is_valid=callable)`, executando a verificação dentro de `BEGIN IMMEDIATE` (`store.py:66`). A verificação só lê arquivos pequenos e calcula SHA-256 de quatro artefatos (custo proporcional ao tamanho do texto, desprezível frente a reprocessar).
   - Jobs `queued` e `running` nunca são invalidados por esta lógica. O `result` do job antigo passa a devolver `failed/output_lost` depois da invalidação.

7. **Comando `list`** (`__main__.py:14-26`, `:28-57`; wrapper `whisper-box.py:28`, `:539-540`).
   - Sintaxe: `python whisper-box.py list [--status S] [--since AAAA-MM-DD] [--until AAAA-MM-DD] [--limit N]`. Padrão `--limit 20`, máximo 200; `--since` e `--until` são **inclusivos** e interpretados no fuso do host.
   - Fuso: o container roda em UTC. O wrapper calcula o deslocamento local (`time.localtime().tm_gmtoff // 60`) e o passa ao container (`--utc-offset-minutes`, argumento interno, validado entre -840 e 840). O container usa esse deslocamento para filtrar por data e para formatar os horários em ISO 8601 com offset.
   - `Store.list` (`store.py:58-62`) ganha filtros opcionais (`status`, `since`, `until` em epoch), mantendo a assinatura atual compatível com o painel (`painel.py:437`).
   - Schema (derivado do §6.3 da A02, ajustado ao que existe hoje: o banco não guarda `title`; use `source_name`; `analysis_path` fica para a A05):

```json
{
  "jobs": [
    {
      "job_id": "32 hex",
      "source_name": "gravacao-2026-11-20_1430.webm",
      "status": "succeeded",
      "language": "auto",
      "created_at": "2026-11-20T14:30:12-03:00",
      "started_at": "2026-11-20T14:30:20-03:00",
      "finished_at": "2026-11-20T14:33:09-03:00",
      "duration_seconds": 1398.08,
      "progress_seconds": 1398.08,
      "files": { "text": "...", "srt": "...", "segments": "...", "metadata": "..." },
      "output_relative": "saida/<job_id>",
      "error": { "code": "...", "message": "..." }
    }
  ]
}
```

   - Do mais recente para o mais antigo (`created_at DESC, id DESC`). `files` e `output_relative` só em `succeeded` **com saída verificada** (mesmo critério de `jobs.status(include_files=True)`, `jobs.py:96-106`; uma saída inválida omite `files` e **não** derruba a listagem). `duration_seconds` vem de `metadados.json` do job verificado (somente esse campo) e é `null` nos demais. `error` só em `failed`. `language` vem do `config` do job. Nunca inclui texto da reunião.
   - Lista vazia é sucesso: `{"jobs": []}`, código 0. `--status` inválido, data inválida ou `--limit` fora de 1–200: código 3 `invalid_arguments`.
   - Registrar `list` em `COMMANDS` (`whisper-box.py:28`), no roteamento de comandos de job (`:29`, `:539-540`, passando o deslocamento de fuso) e no README.

8. **Testes da Parte A.** Casos novos em `tests/test_wrapper.py` (Docker simulado, como os existentes), `tests/test_jobs.py` e, se necessário, um arquivo novo para `list`. Ver critérios 1 a 14.

### Parte B

9. **Ctrl+C e timeouts nos subprocessos** (`whisper-box.py:119-153`).
   - `capture` e `run_to_stderr` recebem `timeout`. Padrões: `wait` = `--timeout` + 60 s; `submit` = 3600 s (cópia de até 2 GiB); demais comandos de job = 120 s; `probe` mantém 30 s.
   - Rodar os containers de CLI com `--name whisper-box-cli-<uuid8>` (`docker compose run --name`). Em timeout ou `KeyboardInterrupt`: encerrar o processo, executar `docker rm -f <nome>` (melhor esforço, com timeout curto) e responder `{"job_id"?: ..., "error": {"code": "docker_timeout" | "interrupted"}}`, código 1. Conferir se o `docker compose run --rm` remove o container ao receber SIGINT antes de acrescentar o `rm -f`.
   - O handler do `painel` (`:451-457`) não muda.

10. **`result` redundante em `transcribe`** (`whisper-box.py:249-254`). Em `wait` com código 0 a resposta já traz `files` e `output_relative`, produzidos pelo mesmo `status(include_files=True)` (`jobs.py:115`). Usar essa resposta, manter a conferência dos arquivos no host (`:255-259`) e remover a chamada `result` e o ramo de código 4 que ficam mortos. Economiza um `docker compose run` (cerca de 5 a 10 s) por transcrição.

11. **`PermissionError` em `probe`** (`whisper-box.py:145-153`): capturar `OSError` (inclui `PermissionError`) e devolver `(None, "sem permissao")`; `doctor` continua devolvendo JSON com `start_docker` e a dica de permissão do Linux (`:49-50`).

12. **Caminhos UNC** (`submit_arguments`, `whisper-box.py:90-97`): testar no Docker Desktop um arquivo em `\\servidor\compartilhamento\x.mp4`. Se montar, suportar e documentar; se não, rejeitar `\\...` (exceto `\\?\`) com `unsupported_path`, código 3 e a orientação de copiar o arquivo para um disco local.

13. **`doctor` mais rigoroso** (`whisper-box.py:156-188`).
    - Modelo: além de existir, `modelos/manifest.json` precisa ser JSON com `revision` e a lista de arquivos, e cada arquivo precisa existir com o tamanho registrado (sem recalcular hash; o worker já valida os hashes ao iniciar, `worker.py:46`). Falha vira o passo `prepare` com a nota de preservar `modelos/` (README, tabela de erros).
    - Imagem defasada: o `prepare`/`build` grava na imagem um rótulo com o SHA-256 de `Dockerfile`, `requirements.lock`, `src/**/*.py` e `whisper-box.py` (`ARG` e `LABEL` no `Dockerfile`, argumento de build repassado pelo wrapper); `doctor` compara o rótulo com o cálculo local. Divergência gera `next_step.code = "rebuild"` (`requires_user_approval: false`, ação: `python whisper-box.py stop` e `docker compose build worker`) e `ready: false`. Atualizar a tabela de `next_step` do README. Se o cálculo do digest no `prepare` tornar o build frágil, entregar apenas a checagem de manifesto e registrar a pendência na seção 9.

14. **Lacunas de teste do wrapper.** Para cada correção das tarefas 1 a 13 há teste novo; além disso, cobrir `painel_arguments`/`start_arguments`, `list` com e sem fuso, e `transcribe` com `--job` malformado.

15. **Documentação no mesmo trabalho** (regra de `AGENTS.md`): README (seção “Para agentes”: tabela de comandos com `list`, tabela de erros com `output_lost`, `unsupported_path`, `docker_timeout`, `interrupted`; linha de `output_incomplete`: “reenvie a mesma gravação para reprocessar”; tabela de `next_step` com `rebuild`); [A01](A01-transcricao-offline-docker.md) §5 (comando `list`); `docs/VALIDACAO.md` (suíte e medições); **corrigir `README.md:93`**, que ainda diz que a captura real aguarda validação (validada pelo usuário em 20/11/2026).

## 6. Contrato e interfaces afetados

| Interface | Mudança |
| --- | --- |
| CLI `whisper-box.py` | Novo comando `list`. Códigos de saída 0 a 4 **inalterados**. Todo erro pós-submit traz `job_id`. Novos códigos de erro: `output_lost` (job antigo), `unsupported_path`, `docker_timeout`, `interrupted`. |
| CLI do container (`python -m whisper_box`) | Subcomando `list` e argumento interno `--utc-offset-minutes`. |
| `jobs.submit` / `Store.enqueue` | `reused: false` e novo `job_id` quando o job `succeeded` equivalente perdeu a saída. Dedup de jobs íntegros inalterada. |
| `status`, painel `GET /api/transcricoes` | Campo `error` só em `failed`. Atualizar [painel-api.md](../painel-api.md) (frase do item `error`). |
| `doctor` | Possível `next_step` novo `rebuild`; validação de manifesto. |
| Banco | Nenhuma migração de schema. |
| `effective_config`, `pipeline_version`, Compose | Sem mudança. |

## 7. Critérios de aceite

Parte A:

1. [x] `prepare` com falha simulada no container produz **exatamente um** JSON em stdout e código 1; com sucesso, exatamente um JSON e código 0 (teste conta linhas de stdout).
2. [x] `transcribe --input` com falha transitória do Docker na primeira espera e sucesso na segunda termina com código 0 (retry funcionou, sem imprimir erro).
3. [x] `transcribe` com falha persistente do Docker após o submit imprime um JSON com `job_id` e `error.code = docker_error`, código 1, depois de 2 retries (testes com relógio simulado, sem esperar de verdade).
4. [x] Resposta não JSON do container em `wait` ou `result` gera erro estruturado com `job_id`, sem traceback.
5. [x] `transcribe --input ""`, `--job ""` e `--job` malformado devolvem `invalid_arguments`, código 3, stdout com um JSON e **nenhum** traceback em stdout ou stderr.
6. [x] Uma exceção inesperada (por exemplo `TypeError` injetada no teste) no entrypoint resulta em `operational_error`, um JSON, código 1.
7. [x] Caminho POSIX contendo `:` é montado corretamente (sintaxe longa) **ou** rejeitado com `unsupported_path` e código 3, conforme a tarefa 4; o teste cobre também um caminho do Windows com letra de unidade.
8. [x] `status` e `GET /api/transcricoes` de um job re-enfileirado após `recover` não contêm `error`; um job `failed` contém.
9. [x] Apagar `saida/<job_id>/` de um job `succeeded` e reenviar a mesma mídia e idioma devolve `reused: false`, **novo** `job_id`, o job antigo em `failed/output_lost` (registro preservado) e o novo chega a `succeeded` com a saída verificada.
10. [x] Reenviar a mesma mídia de um job `succeeded` **íntegro** continua devolvendo `reused: true` (regressão da deduplicação).
11. [x] `list` devolve o schema da seção 5 para jobs `queued`, `running`, `succeeded` e `failed`; ordena do mais recente ao mais antigo; respeita `--status`, `--since`, `--until`, `--limit`; devolve `{"jobs": []}` sem resultados; `files` aparece só em `succeeded` verificado; valores inválidos dão código 3.
12. [x] Com `--utc-offset-minutes -180`, um job criado às 23:30 de 19/11 no horário local (02:30 UTC de 20/11) aparece em `--since 2026-11-19 --until 2026-11-19` e não em `--since 2026-11-20`.
13. [x] `list` não contém texto da reunião; o único dado derivado dos artefatos é `duration_seconds`.

Parte B (cada item só conta se a tarefa correspondente foi entregue):

14. [x] `transcribe` simulado com `KeyboardInterrupt` durante a espera imprime `interrupted` com o `job_id` conhecido, código 1, e chama `docker rm -f` do container nomeado; um subprocesso simulado que não termina é encerrado por timeout com `docker_timeout`, código 1.
15. [x] `transcribe` bem-sucedido executa uma chamada de container a menos (sem `result`) e ainda confere `files` no host.
16. [x] `probe` com `PermissionError` simulado não levanta exceção; `doctor` imprime JSON, código 1, e a dica de permissão no Linux.
17. [x] Caminho UNC é suportado ou rejeitado com `unsupported_path` conforme a tarefa 12, com teste.
18. [x] `doctor` com `manifest.json` inválido ou arquivo do modelo com tamanho diferente devolve `next_step.code = prepare`; com rótulo de imagem divergente devolve `rebuild`.

Gerais:

19. [x] A suíte do Docker passa com testes novos, e o número de testes aprovados é registrado em `docs/VALIDACAO.md` (hoje 76).
20. [x] `effective_config` e `pipeline_version` não mudaram (diff vazio em `config.py` e `__init__.py`); códigos de saída 0 a 4 inalterados.
21. [x] Documentação atualizada conforme a tarefa 15, incluindo a correção de `README.md:93`.

## 8. Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test        # suíte completa, sem rede
python whisper-box.py doctor                                    # ready: true no ambiente real
python whisper-box.py transcribe --input ""                     # JSON invalid_arguments, código 3 (echo $? / $LASTEXITCODE)
python whisper-box.py transcribe --job ""                       # idem
python whisper-box.py list --limit 5                            # JSON com jobs reais; conferir que não há texto
python whisper-box.py list --since 2026-11-19 --until 2026-11-19
python tests/smoke.py --input CAMINHO                           # ensaio real, com modelo preparado
```

Ensaio manual de I6 (no ambiente real, com mídia sintética curta de `tests/make_fixtures.py`): `submit`, aguardar `succeeded`, **renomear** (não apagar) `saida/<job_id>` para outro nome, `submit` da mesma mídia e conferir o novo `job_id`; depois restaurar o nome original. Em todo ensaio, ler stdout e stderr separadamente (nunca `2>&1`).

Registrar resultados e contagem de testes em `docs/VALIDACAO.md`.

## 9. Riscos

| Risco | Tratamento |
| --- | --- |
| I6 muda a semântica de deduplicação e pode gerar duplicatas indevidas se `complete_output` falhar por erro transitório de leitura. | Só invalidar quando a falha for ausência ou hash divergente (`complete_output` hoje devolve `False` também para `OSError`, `jobs.py:83-84`); distinguir erro de E/S transitório de arquivo ausente e não invalidar neste caso. |
| Retry mascara falha real do Docker. | Máximo de 2 retries curtos, só para ausência de JSON; todo erro final inclui `job_id` e o motivo em stderr. |
| `--mount` na sintaxe longa pode não ser aceito por `compose run` em versões antigas. | A tarefa 4 prevê fallback de rejeição explícita. |
| Rótulo de imagem com digest do código torna o build mais frágil. | A checagem de imagem defasada é a última da parte B e pode ser adiada sem afetar o resto. |
| Compatibilidade Python 3.8 do wrapper. | Rodar a verificação na suíte (a imagem usa 3.12; conferir sintaxe manualmente ou com `python3.8 -m py_compile whisper-box.py` quando houver 3.8 disponível). |
| Conflito de merge com A04 e A06 (mesmos arquivos). | A03 vai primeiro; A04 e A06 começam depois do merge. |

## 10. Dependências

- Antes: nenhuma.
- Depois: **A05** depende do `list` (tarefa 7); **A04** se beneficia de I5/I6 (`purge`, reprocessamento); **A06** altera `capture` e o loop de `transcribe`, então espera esta action.
- Handoffs: `dev-backend` (executa), `qa-engineer` (matriz dos critérios 1 a 21), `code-reviewer` (I6 e retry).

## 11. Registro de execução (20/11/2026)

Resultado: tarefas 1 a 15 entregues. Suíte no Docker: **118 testes aprovados** (76 antes). Medições em [VALIDACAO.md](../VALIDACAO.md). Sem commits nesta execução.

Critérios: 1 a 21 atendidos. O critério 7 foi atendido pela alternativa de rejeição; o 17, pela rejeição de UNC.

Desvios e decisões:

- **Tarefa 4 (I4):** `docker compose run` (Compose 5.1.0 no ambiente) não tem `--mount`, só `-v/--volume`. Foi adotada a rejeição: caminho com `:` além da letra da unidade devolve `unsupported_path`, código 3, antes do Docker.
- **Tarefa 12 (UNC):** sem compartilhamento de rede disponível para testar, `\\servidor\...` (exceto `\\?\`) é rejeitado no Windows com `unsupported_path`. **Suporte a UNC não testado.** Um caminho que resolve para UNC (unidade mapeada) também é rejeitado.
- **Tarefa 2:** a normalização de resposta que não é objeto JSON em `docker_error` fica em `capture`, então vale também para `status`, `result`, `list` e `prepare` (um JSON de erro, código 1, em vez de texto cru). O retry só ocorre em `transcribe` (espera `wait`); o `submit` não tem retry (ainda sem `job_id`).
- **Tarefa 6 (I6):** `complete_output` ganhou a variante `output_state` (`ok`, `lost`, `unknown`); só `lost` (ausente, manifesto inválido ou hash divergente) invalida. Erro de E/S que não prova perda (por exemplo `PermissionError`) mantém a reutilização.
- **Tarefa 7:** `Store.list` aceita `status`, `since` (inclusivo) e `until` (exclusivo, epoch) sobre `created_at`; `list_jobs` converte as datas inclusivas no fuso informado.
- **Tarefa 9:** o container de CLI recebe `--name whisper-box-cli-<uuid8>`; em timeout ou Ctrl+C executa `docker rm -f`. O comportamento do `compose run --rm` ao receber SIGINT real não foi conferido (testes simulados apenas).
- **Tarefa 13:** `prepare` passa `--build-arg SOURCE_DIGEST`; o `Dockerfile` grava o rótulo no fim (sem invalidar a camada de dependências). Imagem sem rótulo é aceita pelo `doctor` (limitação: um `docker compose build worker` direto não detecta defasagem futura). A ação do `rebuild` inclui o digest no `--build-arg`.
- **Retry:** só para `docker_error` gerado pelo wrapper (resposta vazia, não JSON ou exceção de subprocesso); `DockerTimeout` não sofre retry.
- **Painel:** `painel.py` (`_summary`) expõe `error` só em `failed`; `painel/app.js` já só lê `error` de jobs `failed`. [painel-api.md](../painel-api.md) atualizado.
- **Observação fora do escopo:** o `submit` do wrapper monta o arquivo como `/source/recording.<ext>`, então `source_name` dos trabalhos da CLI é `recording.<ext>`. Pode interessar à A05 (a skill de análise não verá o nome original).
