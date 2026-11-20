# A04 — Retenção e limpeza de disco

Data: 20/11/2026
Estado: **implementada em 20/11/2026** (D1 resolvida: padrão `delete`; evidências em [VALIDACAO.md](../VALIDACAO.md)). Desvios: `--inputs-only` no `purge`; retenção só vale para jobs concluídos após a ativação (`state/retention.json`), preservando o histórico anterior
Prioridade: 2
Tamanho: M (uma sessão de um agente `dev-backend`, com um ajuste pequeno de `dev-frontend`)
Projeto: Whisper Box (`whisper-box`)
Origem: fase F0 da [A02](A02-captura-ingestao-analise.md) (retenção, `purge`, limpeza de `.partial`) e pendência da F3 (indicador de espaço livre); pergunta 1 da A02.
Depende de: [A03](A03-contrato-do-motor.md) (recomendado: I5/I6 e padrões de erro; não bloqueia as tarefas 1 a 3).

## 1. Contexto

Não existe nenhuma limpeza automática (README, “Onde ficam os arquivos”; `README.md:77`). O uso real de 20/11/2026 já acumulou **733 MB em `entrada/`**. O que cresce:

| Local | Por que cresce | Onde nasce |
| --- | --- | --- |
| `saida/.partial/<job_id>/<tentativa>/` | `pipeline.transcribe` cria o diretório da tentativa (`pipeline.py:62-63`) e **não tem `try/finally`** (`pipeline.py:60-121`): uma falha ou `SystemExit` do SIGTERM (`worker.py:55-58`) deixa a tentativa. Mesmo no sucesso, `temporary.rename(final)` (`pipeline.py:121`) deixa `.partial/<job_id>/` vazio. A recuperação na inicialização (`worker.py:48-52`) só olha o estado, não limpa disco. | `pipeline.py`, `worker.py` |
| `entrada/<job_id>/source.<ext>` | `jobs.submit` copia toda mídia (`jobs.py:35-56`) e nada a remove depois do sucesso. Para gravações do painel, esta cópia é a **única cópia do áudio**: o staging em `entrada/.gravacoes/<id>/` é apagado após o envio (`painel.py:200`). | `jobs.py` |
| `entrada/.gravacoes/*` | `.part`, `.meta`, `.meta.tmp` e o diretório `<id>/` de gravações cuja janela fechou ou cujo `transcrever` falhou (`painel.py:75-204`). Não há rota para listar nem finalizar gravações abandonadas, então são inalcançáveis pela interface. | `painel.py` |
| `saida/<job_id>/` | Intencional (é o produto). Sem política de remoção por escolha do usuário. | — |

Regras que esta action **não pode** violar: nunca apagar o arquivo original do usuário (regra 4 do README: o original é o arquivo no disco do usuário, que a CLI só lê em `ro`, `whisper-box.py:97`); nunca apagar dados para “corrigir” falhas (regra 5). Retenção é **política explícita e documentada**, nunca efeito colateral de um erro.

## 2. Objetivo

O disco deixa de crescer sem controle e sem surpresa: resíduos técnicos (parciais, staging abandonado) somem sozinhos; dados do usuário (cópias de entrada, transcrições) só somem por política escolhida ou por `purge` explícito; e o painel avisa quando o espaço está acabando.

Métricas: `saida/.partial/` vazio com o worker ocioso; zero arquivos em `entrada/.gravacoes/` mais antigos que o limite; painel mostra espaço livre.

## 3. Escopo e fora de escopo

Escopo: limpeza de `.partial`; política de retenção da cópia de entrada; limpeza de staging abandonado; comando `purge`; indicador de espaço livre; documentação.

Fora de escopo: remoção automática de `saida/` (transcrições são o produto); recuperação/finalização pela interface de gravações abandonadas (backlog); checkpoint por bloco (A06, que depende da regra de limpeza de `.partial` definida aqui); compactação de áudio; qualquer mudança de inferência ou de `effective_config`.

## 4. Decisão pendente (Igor) — retenção padrão (pergunta 1 da A02)

| Opção | Efeito | Observação |
| --- | --- | --- |
| **A (recomendada): apagar `entrada/<job_id>/` após sucesso verificado; manter a transcrição** | Para de crescer o maior consumidor. Reprocessar com outro modelo exigiria a gravação de novo. | **Consequência a aceitar:** para gravações feitas no painel, o áudio deixa de existir em qualquer lugar. Para arquivos enviados pela CLI, o original do usuário segue intacto no lugar de origem. |
| B: manter por N dias e apagar depois (ex.: 7 dias) | Meio-termo: janela para reprocessar ou conferir a transcrição. | Exige varredura periódica no worker (mesmo código da inicialização). |
| C: manter sempre (comportamento atual) | Nada muda. | O disco cresce; `purge` manual. |

**Recomendação:** A, com a variável `WHISPER_BOX_INPUT_RETENTION` já suportando os três modos (`delete`, `<N>d`, `keep`), de modo que mudar de ideia seja trocar o valor.

**Se a decisão não vier antes da execução:** implementar o mecanismo completo e entregar com padrão `keep` (comportamento atual; nenhuma perda irreversível sem decisão), e registrar em `docs/VALIDACAO.md` que a troca do padrão é uma linha no `compose.yaml` (e no README). Não escolher A por conta própria.

## 5. Tarefas

1. **Limpeza de `saida/.partial/`.**
   - `pipeline.transcribe` (`pipeline.py:60-121`): envolver a produção da tentativa em `try/except BaseException` que remove `temporary` com `shutil.rmtree(..., ignore_errors=True)` e relança. Depois do `rename` (`:121`) e também no erro, remover `settings.outputs / ".partial" / job["id"]` se estiver vazio. `BaseException` cobre o `SystemExit` do SIGTERM.
   - `worker.run` (`worker.py:45-52`): logo após obter o lock e **antes** da recuperação, remover todo o conteúdo de `saida/.partial/` (com o worker exclusivo, nada ali está em uso; a recuperação decide pelo diretório final, `complete_output`, e nunca por `.partial`). Registrar `partial_cleaned` com a contagem de itens e bytes (`log` em `worker.py:16-18`). Resultados completos em `saida/<job_id>/` nunca são tocados.
   - **Nota para a A06:** se o checkpoint por bloco for implementado, esta varredura precisa passar a preservar `.partial/<job_id>/` de jobs ainda `queued` ou `running`.

2. **Retenção da cópia de entrada** (`worker.py:86-87`, `config.py`).
   - Novo módulo pequeno (por exemplo `retention.py`) com `apply_input_retention(settings, store, job, policy)`. Variável `WHISPER_BOX_INPUT_RETENTION` no serviço `worker` (`compose.yaml:72-86`) com `${WHISPER_BOX_INPUT_RETENTION:-keep}` até a decisão da seção 4 (ver lá).
   - Chamada logo depois de `store.finish(job["id"])` (`worker.py:86`) **somente** se o job está `succeeded` **e** `complete_output(settings, job)` (`jobs.py:73-84`) é verdadeiro. Remove `entrada/<job_id>/` (apenas esse diretório, validando que o caminho resolvido está dentro de `settings.inputs`). Jobs `failed` mantêm a entrada (diagnóstico e nova tentativa); são tratados por `purge`.
   - Modo `<N>d`: varredura na inicialização e a cada hora, removendo entradas de jobs `succeeded` verificados com `finished_at` mais antigo que N dias.
   - Varredura de resíduo na inicialização: job `succeeded` verificado cuja pasta de entrada ainda existe (queda entre `finish` e remoção) é tratado conforme a política.
   - Efeito colateral aceito e testado: depois de apagada a entrada, reenviar a mesma mídia continua devolvendo `reused: true` (`jobs.py:62-69`); se a saída tiver sido perdida, o reprocessamento da A03/I6 usa a **nova** cópia enviada.
   - Logar `input_removed` com `job_id` e bytes liberados, nunca nomes ou caminhos de gravação.

3. **Staging abandonado do painel** (`painel.py:75-204`, `serve`, `painel.py:496`).
   - Na inicialização do painel e a cada hora: em `entrada/.gravacoes/`, remover `<id>.part`, `<id>.meta`, `<id>.meta.tmp` e diretório `<id>/` cujo **mtime mais recente** seja mais antigo que `WHISPER_BOX_STAGING_DAYS` (padrão 7). Nunca tocar em gravação com atividade recente nem em `entrada/<job_id>/`. Usar o lock por gravação já existente (`Gravacoes._lock`, `painel.py:87-89`).
   - Logar `staging_cleaned` (contagem e bytes). O painel já tem `entrada` em escrita (`compose.yaml:48`).

4. **Comando `purge`** (container: `__main__.py`; wrapper: `whisper-box.py`; roda no serviço `cli`, que monta `entrada` e `saida` em escrita, `compose.yaml:18-22`, `:88-91`; isso também remove arquivos de dono `root` no Linux sem `sudo`).
   - Sintaxe: `python whisper-box.py purge --job ID [--yes]` e `python whisper-box.py purge --older-than DIAS [--status failed|succeeded] [--yes]`.
   - **Sem `--yes`, não apaga nada**: devolve `{"dry_run": true, "would_purge": [{"job_id", "status", "input_bytes", "output_bytes"}], "freed_bytes": N}`. Com `--yes`, apaga e devolve `{"dry_run": false, "purged": [...], "freed_bytes": N}`.
   - Por job: remove `entrada/<job_id>/`, `saida/<job_id>/`, parciais `saida/.partial/<job_id>/` e o registro no banco (esta é a escolha explícita do usuário; o registro some junto, e a deduplicação deixa de ver o job). Ordem: validar e marcar sob `BEGIN IMMEDIATE`, apagar o registro, depois os diretórios.
   - Recusa `queued` e `running` (`job_active`, código 3). `job_id` precisa casar `[0-9a-f]{32}`; caminhos sempre derivados de `settings`, nunca de argumento; resolver e conferir que ficam dentro de `entrada/` e `saida/`. Job inexistente: `job_not_found`, código 3. `--older-than` e `--job` são mutuamente exclusivos; sem nenhum dos dois: `invalid_arguments`, 3.
   - Código de saída 0 em dry-run e em sucesso; mesma convenção de um JSON em stdout.
   - README (“Para agentes”): **nova regra inviolável**: só execute `purge --yes` se o usuário pediu explicitamente; em qualquer outro caso use apenas o dry-run. Atualizar as regras 5 e a tabela de comandos.

5. **Indicador de espaço livre no painel** (`painel.py:380-392`, `painel/app.js:225` e `:878`).
   - **Spike primeiro (30 min):** comparar `shutil.disk_usage` dentro do container (`/input`) com o espaço livre real do disco do host (no Windows, Docker Desktop pode reportar o disco da VM, não o do drive). Registrar o resultado. Se coincidirem, o painel usa o valor do container. Se não, o espaço livre deve vir do host: o wrapper já tem o ajudante; avaliar com `code-reviewer` uma segunda rota somente leitura (`GET /espaco`, mesmo token e as mesmas validações de `Host` e `Origin`) em vez de ampliar privilégio do container, ou mostrar o espaço apenas quando medível.
   - `GET /api/saude` ganha `disco: {"livre_bytes": N, "total_bytes": N, "entrada_bytes": N, "saida_bytes": N}` (tamanhos de pasta calculados com cache de 60 s; erro de leitura omite o campo em vez de falhar a saúde). Atualizar [painel-api.md](../painel-api.md).
   - Interface: linha “Disco” na aba **Logs** (formato `42,1 GB livres`) e **aviso** na aba **Gravar**, antes de gravar, quando `livre_bytes` < `WHISPER_BOX_DISK_WARN_GIB` (padrão 5), com a microcopy no estilo de `docs/design/painel-revisao.md` (seção 9). Não bloqueia a gravação. O arquivo `painel/app.js` é vanilla e montado `ro`, sem rebuild.

6. **Documentação.** README (tabela “Onde ficam os arquivos”, parágrafo sobre limpeza `README.md:77`, comandos, regras para agentes, variáveis de ambiente `WHISPER_BOX_INPUT_RETENTION`, `WHISPER_BOX_STAGING_DAYS`, `WHISPER_BOX_DISK_WARN_GIB`), `AGENTS.md` (regras do motor e do painel), `docs/VALIDACAO.md` e [A02](A02-captura-ingestao-analise.md) (seção 0).

## 6. Contrato e interfaces afetados

| Interface | Mudança |
| --- | --- |
| CLI | Novo comando `purge` (com dry-run por padrão). Códigos 0–4 inalterados. Novo erro `job_active`. |
| Variáveis de ambiente | `WHISPER_BOX_INPUT_RETENTION` (`keep` provisório, `delete` ou `<N>d`), `WHISPER_BOX_STAGING_DAYS`, `WHISPER_BOX_DISK_WARN_GIB`. |
| `GET /api/saude` | Campo `disco` (aditivo). |
| Sistema de arquivos | `.partial` limpo na inicialização e no erro; `entrada/<job_id>/` removida conforme política; staging abandonado removido. |
| Banco | Nenhuma migração (apenas `DELETE` pelo `purge`). |
| Compose | Variáveis no `worker` e no `painel`; mounts inalterados (mantém `saida` `ro` no painel). |
| `effective_config`, `pipeline_version` | Sem mudança. |

## 7. Critérios de aceite

1. Depois de um job `failed` por mídia inválida, `saida/.partial/` não contém o diretório da tentativa nem `<job_id>/` vazio.
2. Depois de um job `succeeded`, `saida/.partial/<job_id>/` não existe e `saida/<job_id>/` está completo (`result` com código 0).
3. Com um diretório órfão criado à mão em `saida/.partial/x/y`, reiniciar o worker o remove e registra `partial_cleaned`; um `saida/<job_id>/` completo permanece intacto.
4. Com `WHISPER_BOX_INPUT_RETENTION=delete`, após `succeeded` verificado `entrada/<job_id>/` não existe, e reenviar a mesma mídia devolve `reused: true`; com `keep` ela permanece; com `7d`, uma entrada de job concluído há 8 dias (simulado) é removida e a de 1 dia permanece.
5. A entrada de um job `failed`, `queued` ou `running` **nunca** é removida pela retenção.
6. Nenhum arquivo original do usuário é alterado (os testes confirmam que o caminho de origem do `submit` é só lido).
7. Staging com mtime acima de `WHISPER_BOX_STAGING_DAYS` (simulado) é removido na inicialização do painel; staging recente e gravação em andamento permanecem.
8. `purge --job ID` sem `--yes` não altera disco nem banco e lista tamanhos; com `--yes` remove entrada, saída, parciais e registro **apenas** daquele job (outros jobs intactos) e `status --job ID` passa a devolver `job_not_found` (código 3).
9. `purge` recusa job `queued` ou `running` (`job_active`), `job_id` malformado e qualquer tentativa de caminho fora de `entrada/`/`saida/`.
10. `purge --older-than 30 --status failed` sem `--yes` lista apenas jobs `failed` com mais de 30 dias.
11. `GET /api/saude` traz `disco` com `livre_bytes` coerente com o disco (diferença menor que 5% do valor medido no host, conforme o spike); a aba Logs mostra a linha de disco e a aba Gravar mostra o aviso abaixo do limite (simulável com `WHISPER_BOX_DISK_WARN_GIB` alto).
12. O resultado do spike (container vs host) está registrado em `docs/VALIDACAO.md`.
13. README e `AGENTS.md` descrevem `purge`, a política de retenção, o padrão adotado e a regra “só `purge --yes` a pedido do usuário”.
14. Suíte do Docker passa com os testes novos; códigos 0–4 e `effective_config` inalterados.

## 8. Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
python whisper-box.py start
python whisper-box.py transcribe --input "MIDIA_SINTETICA.wav" --language pt   # gerar job de teste
python whisper-box.py purge --job JOB_ID                                        # dry-run
python whisper-box.py purge --job JOB_ID --yes                                  # remove só esse job
python whisper-box.py purge --older-than 30 --status failed                     # dry-run em lote
```

Conferir manualmente: `saida/.partial/` vazio com o worker ocioso; `docker compose exec worker env` mostra a variável de retenção; `curl http://127.0.0.1:8765/api/saude` traz `disco`; aviso na aba Gravar com `WHISPER_BOX_DISK_WARN_GIB=100000`. Comparar `disco.livre_bytes` com o espaço livre do drive no Explorer. Usar só mídia sintética nos ensaios de remoção (nunca as gravações reais do Igor).

## 9. Riscos

| Risco | Tratamento |
| --- | --- |
| Perda irreversível do áudio de gravações do painel (opção A). | Decisão explícita do Igor; padrão provisório `keep`; documentação clara; opção B como meio-termo. |
| `purge` apagar dados errados (caminho, job em uso). | Dry-run por padrão, validação de `job_id`, caminhos derivados de `settings`, recusa de jobs ativos, testes de borda. |
| Agente executar `purge --yes` sem pedido. | Regra no README e dry-run como padrão. |
| Limpeza de `.partial` conflitar com o checkpoint da A06. | Nota na tarefa 1; a A06 ajusta a regra. |
| `disk_usage` do container refletir a VM do Docker e não o host. | Spike da tarefa 5 antes de implementar; fallback pelo ajudante com revisão de segurança. |
| Condição de corrida entre `purge` e `claim`. | Marcar e remover o registro sob `BEGIN IMMEDIATE`; só então apagar diretórios. |

## 10. Dependências

- Antes: A03 (recomendado; as tarefas 1 a 3 e 5 não dependem dela).
- Depois: A06 (regra de `.partial`; `purge --job` serve para repetir benchmarks que a deduplicação bloquearia); A05 não depende.
- Decisão pendente do Igor: seção 4.
- Handoffs: `dev-backend` (tarefas 1 a 4 e 6), `dev-frontend` (parte da tarefa 5), `infra` (variáveis de ambiente e Compose), `qa-engineer`.
