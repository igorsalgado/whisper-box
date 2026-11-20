# A06 — Desempenho e robustez do motor (medir antes de mudar)

Data: 20/11/2026
Estado: **entregue em 20/11/2026** (tarefas 1, 3, 4, 5, 7 e 8; medições em [VALIDACAO.md](../VALIDACAO.md)). Tarefa 2 entregue **sem** retirar `cpu_threads` do fingerprint (a medição mostrou que as threads alteram o texto; sem bump de `pipeline_version`). Tarefa 6 (checkpoint) **adiada** por decisão D4; reabrir com dados de uso
Prioridade: 4
Tamanho: M/L (uma sessão com medições longas; o agente `dev-backend` trabalha com apoio do `infra`)
Projeto: Whisper Box (`whisper-box`)
Origem: recomendações da análise de infraestrutura; item F4 da [A02](A02-captura-ingestao-analise.md) (checkpoint).
Depende de: [A03](A03-contrato-do-motor.md) (mesmas funções do wrapper) e, para repetir benchmarks, do `purge` da [A04](A04-retencao-e-limpeza-de-disco.md) (ou do contorno descrito na tarefa 1).

## 1. Contexto e linha de base

Linha de base medida em 12/11/2026 ([VALIDACAO.md](../VALIDACAO.md)): gravação real de **23 min 18 s (1.398,08 s)** processada em **166,4 s (RTF 0,12×)** com `small`, CPU, `int8`, 2 threads, `beam_size=5`, VAD; pico de memória do container **1,12 GiB** (limite 4 GiB); 286 segmentos. Duas horas de silêncio sintético: 14,8 s e 0,62 GiB (não representa fala contínua).

O que existe hoje e motiva esta action:

| Ponto | Situação atual |
| --- | --- |
| Threads e CPU | `cpu_threads: 2` faz parte de `effective_config` (`config.py:47`) e, portanto, do fingerprint de deduplicação (`jobs.py:58-60`); o worker as fixa no código (`worker.py:81`), o `Dockerfile` fixa `OMP_NUM_THREADS=2` (`Dockerfile:3-4`) e o Compose fixa `cpus: 2` (`compose.yaml:76`). Mudar a CPU exige editar quatro lugares e invalida a deduplicação. |
| Latência dos comandos de consulta | `wait`, `status` e `result` rodam por `docker compose run --rm ... cli` (`whisper-box.py:102-103`), com 5 a 10 s de início de container cada; a análise de infra mediu **0,8 s** com `docker compose exec` no worker em execução. O `transcribe` chama `wait` repetidamente (`:241-248`). |
| Recuperação | Queda do worker reinicia o arquivo do zero, até 3 tentativas (`store.py:99-107`, `worker.py:48-52`). Cada tentativa é um diretório novo (`pipeline.py:62-63`). Sem checkpoint, uma queda aos 55 min de uma gravação de 1 h perde 55 min. |
| Observabilidade | O healthcheck só confere o heartbeat (`compose.yaml:81-86`, `worker.py:35-40`), que roda em thread própria: uma inferência travada continua “saudável”. O log `job_succeeded` (`worker.py:87`) não traz duração, tempo de processamento nem RTF. |
| Fila | FIFO por `created_at` (`store.py:84-86`): um job curto espera atrás de um longo. |

## 2. Objetivo

Tornar o ajuste de CPU barato e seguro, reduzir a latência dos comandos de consulta, dar visibilidade de desempenho e de travamento e, se os dados justificarem, reduzir o custo de uma queda em gravação longa. Tudo **medido antes e depois**, sem alterar a qualidade da transcrição.

Métricas: tempo por consulta (`wait`/`status`/`result`) abaixo de 2 s com o worker no ar; RTF e memória registrados por job; dedup preservada entre configurações de CPU equivalentes.

## 3. Escopo e fora de escopo

Escopo: tarefas da seção 5.

Fora de escopo (experimentos futuros, só com nova action): `beam_size` 1, `BatchedInferencePipeline`, outro modelo, GPU, mais de um worker, prioridade na fila (apenas registrar a limitação).

## 4. Decisão pendente do Igor — checkpoint (tarefa 6)

O checkpoint é a tarefa mais complexa e só compensa se quedas em gravações longas ocorrerem. **Recomendação: não implementar agora.** Implementar as tarefas 1 a 5 (instrumentação inclusive) e decidir com os dados de uso (campo `interruptions` em `metadados.json`, `pipeline.py:108`; eventos `job_started` repetidos para o mesmo `job_id` nos logs). Se o Igor preferir antecipar, a tarefa 6 traz o desenho completo.

## 5. Tarefas

1. **Medição de referência (spike, antes de mudar).** Reproduzir a linha de base com a gravação de 23 min (`Gravando 2026-11-12 125248.mp4`, se ainda existir; senão outra gravação longa de fala contínua, de preferência acima de 20 min): 3 execuções, registrando `processing_seconds` e `duration_seconds` de `metadados.json` e o pico de memória (`docker compose exec worker cat /sys/fs/cgroup/memory.peak`). Em seguida medir `cpus=2/threads=2` (atual), `cpus=3/threads=3` e `cpus=4/threads=4`. Como a deduplicação bloqueia reenviar a mesma mídia com a mesma configuração, repetir exige `purge --job ID --yes` (A04) ou um contorno: copiar a mídia e acrescentar 1 byte nulo ao final da **cópia** (nunca ao original). Resultado: tabela em `docs/VALIDACAO.md` (RTF e pico de memória por configuração). Comparar os `segmentos.jsonl` entre execuções de threads diferentes (campo `texto`, linha a linha) para saber se o número de threads altera o texto.

2. **Threads fora do fingerprint e CPU configurável.**
   - Só avançar se a comparação da tarefa 1 mostrar texto **idêntico** entre 2, 3 e 4 threads. Se houver diferença, manter `cpu_threads` no fingerprint, registrar o achado e implementar apenas a configuração de CPU (itens abaixo sem a retirada do fingerprint).
   - `config.py:38-53`: remover `cpu_threads` de `effective_config`. O valor passa a ser **configuração de execução** (`runtime`), registrado em `metadados.json` (`pipeline.py:102-109`) para auditoria, mas fora do fingerprint.
   - `worker.py:81`: ler `WHISPER_BOX_CPU_THREADS` (inteiro 1 a 16; padrão 2) em vez do literal.
   - `compose.yaml:76`: `cpus: ${WHISPER_BOX_CPUS:-2}`. No `worker` (`compose.yaml:72-86`), `OMP_NUM_THREADS` e `WHISPER_BOX_CPU_THREADS` derivam de `WHISPER_BOX_CPUS` (padrão 2); o `ENV OMP_NUM_THREADS=2` do `Dockerfile:4` passa a ser apenas o valor padrão da imagem. Os limites de memória (4 GiB) e `pids_limit` não mudam.
   - **Bump de `pipeline_version`** (`__init__.py:3`, `0.1.0` para `0.2.0`): a composição do fingerprint muda, então a deduplicação de jobs antigos deixa de casar (reenviar a mesma mídia reprocessa uma vez). Documentar isso em `docs/VALIDACAO.md`; é regra do `AGENTS.md` revisar versão e deduplicação em mudança desse tipo. Coordenar com o bump previsto para as fronteiras de bloco (A07): **um único bump por release**.
   - O `doctor` informa o valor efetivo de CPU (campo em `checks`) quando `WHISPER_BOX_CPUS` não for o padrão. O padrão 2 CPUs permanece (A01, §2).

3. **`docker compose exec` para `wait`, `status`, `result` e `list`** (`whisper-box.py:102-103`, `:139-142`).
   - `job_arguments` tenta primeiro `exec -T worker python -m whisper_box <comando>` quando o worker está em execução; o `submit` continua em `run` (precisa do `--volume` da gravação, `:97-99`).
   - **Fallback** para o `run --rm ... cli` atual quando o `exec` não devolve JSON válido (container ausente, parado ou comando indisponível); erros devolvidos pelo motor (códigos 1, 2, 3, 4 com JSON) **não** disparam fallback. O contrato (um JSON em stdout, códigos 0 a 4) não muda.
   - Reavaliar o timeout de `wait` (A03, tarefa 9) e o nome do container (`--name`) que só se aplica ao `run`.
   - Atenção: o processo do `exec` roda no cgroup do worker (2 CPUs e 4 GiB); as consultas são leves, mas conferir que não elevam o pico de memória medido.

4. **Observabilidade do job.**
   - `pipeline.transcribe` (`pipeline.py:60`) passa a devolver o dicionário de metadados (hoje devolve `None`).
   - `worker.py:87`: o log `job_succeeded` inclui `duration_seconds`, `processing_seconds`, `rtf` (processing/duration, 3 casas), `attempts` e `peak_memory_bytes` (lido de `/sys/fs/cgroup/memory.peak` com fallback `null`). `job_started` (`worker.py:72`) inclui `queue_wait_seconds` (agora menos `created_at`). **Nenhum** texto, nome de arquivo ou caminho entra nos logs.
   - Mostrar RTF e duração na lista do `list` da A03 é opcional; não alterar a API do painel nesta action.

5. **Healthcheck de progresso.**
   - Schema: nova coluna `progress_at REAL` em `jobs` com migração segura em `Store.__init__` (`store.py:14-36`: `ALTER TABLE ... ADD COLUMN` se ausente, compatível com bancos existentes); `Store.progress` (`store.py:109-111`) grava o instante.
   - `heartbeat` (`worker.py:35-40`) inclui `job_id` e `progress_at` do job em execução. Novo comando `health` (hoje `require_worker`, `__main__.py:41-44`) devolve código não zero também quando há job `running` sem progresso há mais de `WHISPER_BOX_STALL_SECONDS` (padrão 1200 s). **`require_worker` usado por `submit` e pelo painel (`jobs.py:18-24`) não muda**: separar uma função de saúde só para o healthcheck do Compose (`compose.yaml:81-86`).
   - `progress_seconds` é atualizado ao fim de cada bloco de 300 s (`pipeline.py:96`) e a cada 5 s com segmentos (`:93-95`); com RTF em torno de 1 ou menor, 1200 s é folgado. Validar com um bloco de silêncio longo (só atualiza no fim do bloco).
   - Ação ao detectar travamento: apenas registrar `job_stalled` em log e refletir no healthcheck. **Não** reiniciar o worker automaticamente nesta action.

6. **Checkpoint por bloco de 300 s (condicional, seção 4).**
   - Diretório de trabalho estável por job (`saida/.partial/<job_id>/work/`, não por tentativa) com `checkpoint.json` gravado de forma atômica após cada bloco: `{"fingerprint", "input_sha256", "next_chunk", "segment_count", "text_bytes", "srt_bytes", "segments_bytes"}`.
   - Na nova tentativa, validar `fingerprint` e `input_sha256`; truncar os três arquivos aos tamanhos registrados; decodificar e **descartar** os blocos já concluídos (`audio_chunks`, `pipeline.py:14-47`, é sequencial) e retomar em `next_chunk`. Medir o custo da redecodificação antes de decidir por seek.
   - A regra de limpeza da A04 passa a preservar `.partial/<job_id>/` de jobs `queued`/`running`.
   - Como cada bloco é transcrito de forma independente (`condition_on_previous_text=False`, `pipeline.py:74-79`), o resultado retomado deve ser **idêntico** ao ininterrupto; se o teste provar isso, **não** é necessário bump de `pipeline_version` nem muda o fingerprint. Se houver diferença, tratar como mudança de inferência (bump e revisão da deduplicação).
   - Manter o limite de 3 tentativas.

7. **FIFO: só registrar.** Documentar a limitação (README, “Limitações”: um job curto espera os longos à frente) e usar `queue_wait_seconds` (tarefa 4) para quantificar. Nenhuma mudança em `Store.claim` (`store.py:81-93`).

8. **Documentação e validação** no mesmo trabalho: README (variáveis `WHISPER_BOX_CPUS`, `WHISPER_BOX_CPU_THREADS`, `WHISPER_BOX_STALL_SECONDS`; limitação da fila), `AGENTS.md` (regra de limites 2 CPUs/4 GiB agora “padrão configurável”), A01 §7 (perfil) e `docs/VALIDACAO.md`.

## 6. Contrato e interfaces afetados

| Interface | Mudança |
| --- | --- |
| `effective_config` e fingerprint | Sem `cpu_threads` (se a tarefa 2 avançar); `pipeline_version` sobe para 0.2.0. Efeito: deduplicação de jobs anteriores deixa de casar uma única vez. |
| `metadados.json` | Campo aditivo `runtime` (threads, CPUs). |
| Logs do worker | `job_started` e `job_succeeded` com campos aditivos; sem conteúdo da reunião. |
| CLI | Contrato (JSON único e códigos 0 a 4) inalterado; `wait`, `status`, `result`, `list` passam a usar `exec` com fallback. |
| Compose | `cpus: ${WHISPER_BOX_CPUS:-2}`; novas variáveis no `worker`; healthcheck com progresso. Padrões idênticos aos atuais. |
| Banco | Coluna `progress_at` com migração aditiva. |
| Segurança | `network_mode: none` e limite de memória do worker inalterados. |

## 7. Critérios de aceite

1. `docs/VALIDACAO.md` traz a tabela de medição (3 execuções do caso base e as configurações 2/3/4), com RTF, `processing_seconds` e pico de memória, e a conclusão sobre equivalência de texto entre contagens de threads.
2. O RTF do caso base na configuração padrão fica dentro de ±15% de 0,12× ou a diferença é explicada (carga da máquina) no registro.
3. Com `WHISPER_BOX_CPUS=4`, `docker inspect` mostra `NanoCpus: 4000000000`, o worker usa 4 threads (`metadados.json` registra `runtime`) e, **se a tarefa 2 avançou**, reenviar a mesma mídia com 2 e depois 4 CPUs devolve `reused: true` na segunda vez.
4. Sem as variáveis, o comportamento é o atual: 2 CPUs, 2 threads, 4 GiB, `network_mode: none` (`docker inspect`).
5. Com o worker em execução, `wait`, `status` e `result` respondem em menos de 2 s (medido 5 vezes, mediana); com o worker parado, o fallback devolve o mesmo JSON e os mesmos códigos.
6. Nenhum teste do contrato (códigos 0 a 4, um JSON em stdout) regride; `exec` com resposta inválida aciona o fallback e erro do motor não aciona (testes com Docker simulado).
7. O log `job_succeeded` contém `rtf`, `duration_seconds`, `processing_seconds`, `attempts` e `peak_memory_bytes`; um grep de logs em um job real não encontra texto da reunião nem nomes de arquivo.
8. `health` falha (código não zero) quando um job `running` fica sem progresso por mais de `WHISPER_BOX_STALL_SECONDS` (teste com valor baixo e job simulado) e continua saudável com o worker ocioso e com job progredindo; `submit` não é bloqueado por esse estado.
9. Banco existente (cópia de um `jobs.sqlite` anterior) abre sem erro e ganha `progress_at`; jobs antigos permanecem legíveis.
10. A limitação FIFO está documentada e `queue_wait_seconds` aparece no log de início.
11. **Se a tarefa 6 foi entregue:** interromper o worker (`docker kill`) no meio do 3º bloco de um áudio sintético longo e reiniciar retoma do bloco concluído mais recente (`job_started` seguido de processamento só dos blocos restantes) e produz `transcricao.txt`, `.srt` e `segmentos.jsonl` **byte a byte iguais** aos de uma execução sem interrupção (ignorando `metadados.json`).
12. Suíte do Docker passa; `pip check` do build passa; `pipeline_version` e dedup documentados conforme a tarefa 2.

## 8. Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
python whisper-box.py start
python whisper-box.py transcribe --input "GRAVACAO_23MIN.mp4" --language pt        # base: lê metadados.json depois
docker compose exec worker cat /sys/fs/cgroup/memory.peak                          # pico de memória
docker inspect whisper-box-worker-1 --format "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}} {{.HostConfig.NetworkMode}}"
WHISPER_BOX_CPUS=4 python whisper-box.py start                                     # PowerShell: $env:WHISPER_BOX_CPUS=4
python whisper-box.py wait --job JOB_ID --timeout 1                                # medir tempo com e sem worker no ar
python whisper-box.py logs                                                         # job_succeeded com rtf
```

Medir tempo de consulta com `Measure-Command { python whisper-box.py status --job ID }` (PowerShell) ou `time` (Linux/macOS), 5 vezes. Para a tarefa 6, gerar o áudio longo sintético com `tests/make_fixtures.py` (silêncio mais tons) e matar o worker com `docker kill`. Não usar gravações reais em testes versionados.

## 9. Riscos

| Risco | Tratamento |
| --- | --- |
| Número de threads alterar o texto (int8 e paralelismo podem divergir em casos limite). | Comparação da tarefa 1 como portão; sem equivalência, `cpu_threads` permanece no fingerprint. |
| Mais CPU no worker concorre com o resto da máquina (histórico de travamento com carga pesada, A01 §2). | Padrão permanece em 2; aviso em README; `doctor` informa o valor ativo. |
| `exec` depende de o container do worker estar saudável; processos de consulta compartilham o cgroup. | Fallback para `run`; medir memória. |
| Bump de `pipeline_version` invalida a deduplicação anterior. | Documentado; custo é reprocessar uma vez; coordenar com A07 para um bump único. |
| Migração de schema em banco com dados reais. | Aditiva (`ALTER TABLE ADD COLUMN`); testar com cópia do banco real antes. |
| Checkpoint com corrupção parcial (queda durante gravação do checkpoint). | Escrita atômica e truncamento pelos tamanhos registrados; validar `fingerprint` e hash da entrada. |
| Healthcheck gerar falso positivo em bloco longo de silêncio. | Limite generoso (1200 s) e validação com bloco de silêncio. |

## 10. Dependências

- Antes: **A03** (conflito nas funções `capture` e `job_arguments`); **A04** (regra de `.partial`; `purge` para benchmarks) é recomendada.
- Depois: A07 (fronteiras de bloco compartilham o bump de versão e devem preceder o checkpoint, para que os blocos sejam estáveis antes de serem persistidos).
- Decisão pendente do Igor: seção 4 (checkpoint agora ou com dados).
- Handoffs: `dev-backend` (tarefas 2 a 7), `infra` (Compose, limites, healthcheck, medição), `qa-engineer` (critérios 1 a 12).
