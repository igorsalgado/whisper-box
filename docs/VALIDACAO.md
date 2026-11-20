# Validação — Whisper Box 0.1.0

Data: 12/11/2026. Ambiente: Windows, Windows PowerShell 5.1 e Docker Desktop com engine Linux 29.2.1, em amd64.

## Resultado

Implementação validada com a gravação indicada pelo usuário, suíte automatizada e ensaios pelo wrapper PowerShell. A mídia e o texto da reunião permanecem apenas no ambiente local.

| Verificação | Resultado |
| --- | --- |
| Build da imagem e `pip check` | Aprovados; dependências fixadas e imagem base por digest. |
| Testes automatizados sem rede | **18 testes aprovados** em 1,673 s. |
| Ensaio completo pelo wrapper | **7 casos aprovados**. |
| Recuperação com interrupção real do worker | Concluiu na tentativa 2, com uma interrupção registrada. |
| Worker duplicado | Rejeitado com `worker_already_running` e código 1. |
| Caminho com espaços e acentos | Submissão aprovada e deduplicação preservada. |
| Espera expirada | Código 2; processamento continuou. |
| Resultado pendente | Código 4, sem anunciar artefatos. |
| Erro de transcrição pelo wrapper | Código 1 e JSON válido com caracteres UTF-8. |
| Retorno de sucesso | Caminhos de todos os artefatos acessíveis pelo Windows. |

## Gravação real

Arquivo autorizado para o ensaio: `Gravando 2026-11-12 125248.mp4`.

| Métrica | Medida |
| --- | --- |
| Duração do áudio | **1.398,080 s — 23 min 18,080 s** |
| Processamento do pipeline | **166,409 s — 2 min 46,409 s** |
| Da tomada do trabalho até a conclusão | **169,424 s — 2 min 49,424 s**, incluindo carga inicial do modelo |
| Segmentos produzidos | **286** |
| Idioma | Português (`pt`) |
| Modelo | `small`, CPU, `int8`, duas threads |
| Revisão do modelo | `536b0662742c02347bc0e980a01041f333bce120` |
| Pico de memória do container | **1.199.644.672 bytes**, aproximadamente **1,12 GiB** |
| Encerramento por falta de memória | Não observado; `OOMKilled=false` |

O pico foi lido de `/sys/fs/cgroup/memory.peak` no worker que realizou a transcrição. Inclui a memória contabilizada pelo cgroup, não todo o Docker Desktop ou o Windows. O tempo total foi calculado pelos eventos persistidos de início e fim; o tempo de pipeline está nos metadados e começa após o carregamento do modelo.

Os horários e três amostras do texto, no começo, meio e fim, foram inspecionados. Isso verifica plausibilidade e presença de conteúdo, mas **não mede precisão/WER**, pois não há transcrição humana de referência. Os quatro artefatos tiveram seus hashes conferidos pelo comando de resultado.

## Formatos e duração longa

Casos do ensaio automatizado (executado em 12/11/2026 com `tests/smoke.ps1`, hoje substituído por `tests/smoke.py`):

| Caso | Duração decodificada | Processamento | Resultado |
| --- | --- | --- | --- |
| Gravação real MP4 com áudio e vídeo | 1.398,080 s | 166,409 s | 286 segmentos; resultado reutilizado no ensaio seguinte. |
| Arquivo MP4 inválido | — | — | Falha esperada com `invalid_media`. |
| WAV de duas horas de silêncio sintético | 7.200,000 s | 14,818 s | Sucesso, zero segmentos. |
| M4A de silêncio sintético | 2,064 s | 0,039 s | Sucesso, zero segmentos. |
| MP3 de silêncio sintético | 2,000 s | 0,027 s | Sucesso, zero segmentos. |
| MP4 de silêncio sintético | 2,064 s | 0,034 s | Sucesso, zero segmentos. |
| WAV de silêncio sintético | 2,000 s | 0,039 s | Sucesso, zero segmentos. |

O worker desse ensaio atingiu pico de **661.458.944 bytes**, aproximadamente **0,62 GiB**. O log registrou um carregamento do modelo, seguido de vários trabalhos. O caso de duas horas valida a decodificação em blocos e o caminho de silêncio; **não representa duas horas de fala contínua** nem permite prever seu tempo de inferência. A gravação real de 23 minutos exercitou o caminho de fala.

## Rede, recursos e persistência

A inspeção do worker confirmou:

```text
NetworkMode: none
Memory: 4294967296 bytes
NanoCpus: 2000000000
```

Os containers auxiliares usam a mesma configuração de rede `none` no Compose. Somente o serviço de preparação usa rede. O worker foi parado e iniciado com um trabalho sintético ainda em execução: a fila persistiu, o processamento foi reiniciado e os resultados completos foram publicados na segunda tentativa.

`wait --timeout 1` retornou código 2 sem cancelar o trabalho. A tolerância da espera inclui até um ciclo de consulta interno e, na chamada pelo host, o tempo adicional de criação/encerramento do container auxiliar.

## Comandos para reproduzir

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
python whisper-box.py prepare
python tests/smoke.py --input "C:\Reunioes\gravacao.mp4"
```

Para repetir o ensaio de recuperação, submeta uma mídia ainda não processada, consulte `result` enquanto estiver em execução, execute `wait --timeout 1`, pare e inicie o worker e aguarde o mesmo identificador. Os metadados devem registrar a tentativa 2 e uma interrupção. A política de três tentativas também é coberta pela suíte automatizada.

Relatórios brutos, fixtures e resultados permanecem em `logs/`, `entrada/` e `saida/`, ignorados pelo Git. Nenhuma fala, gravação ou transcrição real está incluída neste relatório.

## Revisão de 19/11/2026 — wrapper Python multiplataforma

O wrapper de host passou de PowerShell para `whisper-box.py` (Python 3.8+, somente biblioteca padrão). Primeiro, `whisper-box.ps1` virou um shim que repassava tudo ao Python. Depois que o helper do agents-framework também foi migrado (`whisper/scripts/transcribe.py`), o shim foi removido; não há mais scripts PowerShell. `tests/smoke.ps1` foi substituído por `tests/smoke.py`. Pipeline, modelo, Compose e limites não mudaram; a versão do pipeline foi mantida.

Ambiente: Windows 11, Python 3.12.6, Docker 29.8.1 e Compose v5.5.1.

| Verificação | Resultado |
| --- | --- |
| Suíte no Docker sem rede | **27 testes aprovados**: 18 anteriores, 1 de caminhos POSIX e 8 do wrapper. |
| `start`, `submit`, `wait`, `result` por `whisper-box.py` | Aprovados com mídia sintética em caminho com espaços e acentos. |
| Espera expirada | `wait --timeout 1` retornou código 2; o trabalho concluiu em seguida. |
| Trabalho inexistente e comando desconhecido | Código 3 com JSON de erro. |
| Shim `whisper-box.ps1` (antes da remoção) | Uma linha JSON em stdout, Docker em stderr, códigos e UTF-8 preservados. |
| Contrato do `transcribe.py` do agents-framework | 11 casos aprovados com backend simulado. |
| `transcribe.py` com o Whisper Box real | Retomada por `--job` e submissão por `--input` concluídas com código 0 e os quatro artefatos. |

Na mesma data, foram adicionados os comandos para agentes `doctor` (diagnóstico com um `next_step`) e `transcribe` (fluxo completo em um comando), além do roteiro do agente, hoje no `README.md` como prompt operacional:

| Verificação | Resultado |
| --- | --- |
| Testes do wrapper | **17 aprovados**, incluindo 4 de `doctor` e 5 de `transcribe` com Docker simulado. |
| `doctor` no ambiente real | `ready: true`, `platform: windows`, `next_step: ask_for_recording`, código 0. |
| `transcribe --input` com mídia sintética e caminho acentuado | `succeeded` com os quatro artefatos, código 0 e evento `whisper_waiting` em stderr. |
| `transcribe --job` inexistente / arquivo ausente | Código 3 com `job_not_found` / `input_not_found`. |

Os caminhos `install_docker`, `start_docker` e `prepare` do `doctor` foram validados somente com testes simulados. O ensaio completo com gravação real (`tests/smoke.py`) e a execução em host Linux/macOS não foram repetidos nesta revisão. O comportamento POSIX está coberto por testes unitários do wrapper e do mapeamento de caminhos.

## Revisão de 20/11/2026 — painel web local e ajudante de host (A02/F3, adiantada)

Escopo: serviço `painel` no Compose (`python -m whisper_box painel`), interface em `painel/`, API em [painel-api.md](painel-api.md) (revisões 1 e 2) e comando `python whisper-box.py painel` com ajudante de host. `start` passou a subir worker e painel e `stop` a parar os dois. Ambiente: Windows 11, Docker Desktop (engine Linux), Edge.

| Verificação | Resultado |
| --- | --- |
| Suíte no Docker sem rede | **76 testes aprovados** (15 de jobs, 4 de pipeline, 39 do wrapper e 18 do painel). |
| Fumaça do painel: WebM/Opus sintético de 3 s enviado em 4 pedaços, `transcrever`, espera | Trabalho chegou a `succeeded`; download do TXT pela API retornou `200`. |
| Fumaça com o worker parado | `transcrever` devolveu `503` (`worker_unavailable`) e a gravação em `entrada/.gravacoes/` foi preservada para nova tentativa. |
| `python whisper-box.py painel` real | Abriu o Edge em `--app`, com perfil próprio (`.navegador/`) e janela de 380×640; imprimiu `status: open` com `painel_url` e `ajudante_port`. |
| Ajudante de host, preflight `OPTIONS` com origem do painel | `204` com `Access-Control-Allow-Origin` restrito à origem do painel. |
| Ajudante com token errado | `403` (`token_invalido`). |
| Ajudante com `Origin` estranha | `403` (`origem_invalida`). |
| Worker após o `start` com painel | `NetworkMode: none` mantido; somente o painel usa a bridge própria. |
| Validação visual da interface pelo usuário | O Igor usou o painel na janela do aplicativo e relatou que “ficou perfeito”. Registro de observação visual; não é medição. |

**Bug encontrado e corrigido:** o `painel` retornava `browser_not_found` no Windows mesmo com o Edge instalado. A causa era procurar `ProgramFiles`, `ProgramFiles(x86)` e `LocalAppData` em uma cópia de `os.environ` (dicionário comum), cujas chaves ficam em maiúsculas no Windows. A busca agora ignora a caixa das chaves, e há teste cobrindo o caso.

**Não validado nesta revisão:**

- **Captura real de áudio do sistema e do microfone** (Chrome e Edge) seguida de transcrição. O teste da fumaça usou áudio sintético enviado pela API, não uma captura feita no navegador; a observação visual do usuário não substitui o critério 24 e 25 da A02. O ensaio manual de gravação real segue pendente.
- Gravações longas (acima de alguns minutos) pelo painel, queda do navegador no meio da gravação e o limite de 2 GiB.
- Linux e macOS como host (o ajudante usa `xdg-open` e `open`, cobertos somente por testes).
- Fluxo de ponta a ponta com o Chrome.

## Revisão de 20/11/2026 — contrato do motor (A03)

Escopo: [A03](actions/A03-contrato-do-motor.md), achados I1 a I6, comando `list` e itens menores. Sem mudança de inferência (`pipeline_version` e `effective_config` intactos). Ambiente: Windows 11, Python 3.14.3 no host, Docker Desktop (engine Linux) e Compose 5.1.0.

| Verificação | Resultado |
| --- | --- |
| Suíte no Docker sem rede | **118 testes aprovados** (76 antes): 26 de jobs, 4 de pipeline, 69 do wrapper e 19 do painel. |
| Sintaxe do wrapper | `ast.parse(..., feature_version=(3, 8))` aprovado; não havia Python 3.8 instalado para executar. |
| `doctor` real | `ready: true`, `next_step: ask_for_recording`; com a imagem construída com o rótulo `whisper-box.source-digest`, `image_current` ok. |
| `transcribe --input ""`, `--job ""`, `--job abc` | Código 3, um JSON `invalid_arguments`, stderr vazio no primeiro caso (sem traceback). |
| `list --limit 3`, `list --since/--until 2026-11-19`, `list --limit 0` | JSON com trabalhos reais (sem texto da reunião), `{"jobs": []}` e código 3. |
| `transcribe --input` real: WAV sintético de 4 s em `C:\tmp`, nome com espaços e acento, gerado na imagem com `--network none` | Código 0 em cerca de 17 s, um JSON com `files` e `output_relative`, sem chamada `result` (uma execução de container a menos). |
| I6 no ambiente real: `saida/<job_id>` renomeada (não apagada), mesma mídia reenviada | `reused: false`, novo `job_id`; o antigo ficou `failed/output_lost` com registro preservado; o novo chegou a `succeeded`. A pasta original foi restaurada. |
| Worker após `start` | `NetworkMode: none`, 2 CPUs e 4 GiB mantidos; worker e painel `healthy`. |

Decisões e desvios:

- **I4 (bind mount com `:`):** `docker compose run` (Compose 5.1.0) só aceita `-v/--volume`; não tem `--mount`. Caminho com `:` além da letra da unidade é **rejeitado** antes do Docker (`unsupported_path`, código 3). Caminhos do Windows com letra de unidade continuam funcionando.
- **Caminhos UNC (`\\servidor\pasta`):** não havia compartilhamento de rede para testar no Docker Desktop. Foram **rejeitados** com `unsupported_path` (código 3) no Windows, exceto o prefixo `\\?\`. O suporte, se existir, não foi testado.
- **Imagem defasada:** `prepare` constrói com `--build-arg SOURCE_DIGEST`; o `Dockerfile` grava o rótulo `whisper-box.source-digest`. Uma imagem construída sem o argumento (por exemplo, `docker compose build worker` direto) fica sem rótulo comparável e é aceita pelo `doctor`.
- **Timeouts e Ctrl+C:** cobertos por testes simulados (remoção do container nomeado com `docker rm -f`). O Ctrl+C real contra um `docker compose run` não foi ensaiado.
- **Observação (fora do escopo):** `submit` pelo wrapper monta o arquivo como `/source/recording.<ext>`; por isso `source_name` dos trabalhos enviados pela CLI é `recording.<ext>` e não o nome original.
- A captura real de áudio pelo painel (Chrome/Edge, sistema e microfone) foi validada pelo usuário em 20/11/2026 (“todas as funcionalidades estão ok”); isso é registro de aceite do usuário, não medição.

## Revisão de 20/11/2026 — retenção e limpeza de disco (A04)

Escopo: [A04](actions/A04-retencao-e-limpeza-de-disco.md). Sem mudança de inferência (`pipeline_version` e `effective_config` intactos). Decisão D1 do usuário: o padrão é **apagar `entrada/<job_id>/` após sucesso verificado** (`WHISPER_BOX_INPUT_RETENTION=delete`; `keep` e `<N>d` disponíveis).

| Verificação | Resultado |
| --- | --- |
| Suíte no Docker sem rede | **142 testes aprovados** (118 antes): 22 novos de retenção, `purge`, `.partial`, staging e saúde do disco, mais 2 do wrapper. |
| Ensaio real, `transcribe` de WAV sintético de 4 s (em `C:\tmp`) | Código 0; `entrada/<job_id>` removida após o sucesso (log `input_removed`); `saida/.partial/` vazio; as 3 pastas de entrada do histórico real permaneceram. |
| Reenvio da mesma mídia depois da remoção | `reused: true`, mesmo `job_id`, sem nova pasta em `entrada/`. |
| `purge --job` sem `--yes` / com `--yes` (só no job sintético) | Dry-run sem alterar nada; com `--yes` removeu saída e registro do job; `status` devolveu `job_not_found` (3). `job_id` malformado: `invalid_arguments` (3). |
| `purge --older-than 0` (dry-run no histórico real) | Lista os jobs reais sem apagar nada. Nenhum `purge --yes` foi executado no histórico do usuário. |
| Limpeza de `.partial` na inicialização | Log `partial_cleaned` com 3 itens (diretórios vazios residuais) ao reiniciar o worker. |
| Retenção e histórico | O marcador `state/retention.json` registra quando a retenção foi ativada; jobs concluídos antes dele não são apagados automaticamente (só por `purge`). |
| Worker e painel após `start` | Worker `NetworkMode: none`, 2 CPUs e 4 GiB; painel `CapDrop: [ALL]`, sistema de arquivos somente leitura e porta apenas em `127.0.0.1`. |

**Spike do espaço livre (container vs host):** `shutil.disk_usage('/input')` no container do painel devolveu `total=510939623424` e `free=119575244800`, idênticos (diferença 0%) ao `Get-PSDrive C` do Windows no mesmo instante. Com Docker Desktop e bind mount de um drive, o container enxerga o disco do host; o painel usa o valor do container e o ajudante de host não ganhou rota nova. Em Linux/macOS não foi medido.

Pendências e observações:

- O aviso na aba Gravar e a linha “Disco” na aba Logs foram validados por teste da API (`disco`, `aviso_livre_bytes`) e revisão de código; o ensaio visual no navegador (por exemplo com `WHISPER_BOX_DISK_WARN_GIB=100000`) fica para o usuário.
- A limpeza `<N>d` e a de staging foram cobertas por testes com datas simuladas, não por espera real.
- Para voltar ao comportamento anterior (manter tudo): `WHISPER_BOX_INPUT_RETENTION=keep` no ambiente antes de `start`, ou trocar o padrão em `compose.yaml`.

## Revisão de 20/11/2026 — skill de análise (A05)

Escopo: [A05](actions/A05-skill-de-analise.md), decisão D2 (1 arquivo, `analises/<job_id>/analise.md`). Sem mudança no motor, no banco, no compose nem na imagem. Nenhum conteúdo de reunião foi lido ou registrado.

| Verificação | Resultado |
| --- | --- |
| Testes do verificador de citações (`tests/test_analise.py`, transcrição sintética) | 8 testes aprovados, em contêiner `--network none` com a imagem existente e `tests/` montada somente leitura. |
| Suíte completa nessa mesma execução | 126 testes aprovados (118 + 8). |
| `list --status succeeded --limit 3` real | JSON com 3 trabalhos (somente metadados); o `list` atende à localização da skill. |
| `git check-ignore` | `analises/` ignorada; `.claude/skills/whisper-box-analise/SKILL.md` não é ignorado. |

Não ensaiado: uso real da skill por um agente (critérios 1, 5, 6 e as métricas de 9/10 pedidos e 5 análises), pois exige o Igor com transcrições reais e um agente interativo. Tarefa 7 (`analysis_path` em `list` e mount `ro` no `cli`) não foi entregue: era opcional e evita conflito de `compose.yaml` com a A04; o agente checa a pasta no host.

## Revisão de 20/11/2026 — desempenho e robustez do motor (A06)

Escopo: [A06](actions/A06-desempenho-e-robustez-do-motor.md). Regra aplicada: **medir antes de mudar**. Decisão D4: o checkpoint por bloco (tarefa 6) **não foi implementado**; só a instrumentação que permite decidir depois. Ambiente: Windows 11, i5-12450H (12 threads lógicas), Docker Desktop com 12 CPUs e cerca de 5,8 GiB para a VM, Python 3.14.3 no host.

### Linha de base (código anterior à A06)

A gravação real de 23 min de 12/11 não existe mais em `entrada/` (retenção `delete`) e nenhuma gravação do usuário foi usada. O caso de benchmark é **fala sintética** gerada localmente com a voz pt-BR do Windows (SAPI, "Maria"), a partir de texto gerado por script (sem conteúdo real), em WAV 16 kHz mono cortado em **1.398,08 s** (mesma duração da linha de base de 12/11). É fala contínua e limpa, sem pausas; **não é equivalente** à gravação de reunião (por isso o RTF absoluto não se compara 1 a 1 com o de 12/11). Cada repetição usa uma cópia da mídia com 1 a N bytes nulos ao final (a original não muda) para contornar a deduplicação; os jobs de benchmark foram removidos depois com `purge --job ID --yes` (só os criados aqui).

| Execução (imagem antiga, 2 CPUs / 2 threads) | processing_seconds | RTF | Segmentos | Hash do texto |
| --- | --- | --- | --- | --- |
| 1 | 194,204 | 0,1389 | 250 | `67219972…` |
| 2 | 180,581 | 0,1292 | 250 | `67219972…` |
| 3 | 184,702 | 0,1321 | 250 | `67219972…` |
| **Média** | **186,5** | **0,1334** | | idêntico nas 3 |

Referência de 12/11 (fala real): RTF 0,12. A média sintética fica 11% acima, dentro dos ±15% do critério 2; as diferenças de conteúdo e a máquina em uso (as edições de código e os `docker compose` do próprio trabalho rodaram durante as execuções 1 e 2) explicam a variação. O pico de memória do container nas execuções 2 e 3 (o container foi recriado entre a 1 e a 2): **942.809.088 bytes (0,88 GiB)**, abaixo dos 1,12 GiB de 12/11.

### Matriz de CPUs/threads (imagem nova, 2 execuções por configuração)

`WHISPER_BOX_CPUS` define `cpus` do container e as threads. `docker inspect` confirmou `NanoCpus` 2, 3 e 4 bilhões, `Memory` 4 GiB e `NetworkMode: none` em todas.

| CPUs / threads | processing_seconds | RTF | Ganho vs 2/2 | Segmentos | Hash do texto | Pico de memória do container |
| --- | --- | --- | --- | --- | --- | --- |
| 2 / 2 (padrão) | 192,128 e 193,164 | 0,1374 e 0,1382 | — | 250 | `67219972…` | 992.342.016 (0,92 GiB) |
| 3 / 3 | 147,946 e 146,796 | 0,1058 e 0,1050 | 1,31× | 248 | `92603a20…` | 965.292.032 (0,90 GiB) |
| 4 / 4 | 135,580 e 136,614 | 0,0970 e 0,0977 | 1,41× | 262 | `7a40fa9a…` | 919.142.400 (0,86 GiB) |

- **Instrumentação neutra:** o padrão com o código novo (RTF 0,1374 e 0,1382; 0,138 num terceiro job) ficou na faixa da linha de base (0,129 a 0,139).
- **Equivalência de texto entre contagens de threads: NÃO.** Cada configuração é determinística (as duas repetições geram `segmentos.jsonl` byte a byte iguais), mas 2, 3 e 4 threads produzem textos e segmentações **diferentes** (250, 248 e 262 segmentos; só 191 de 250 segmentos de texto idênticos entre 2 e 3, e 129 entre 2 e 4). Num clipe de 60 s o texto coincidiu, mas o arquivo de segmentos não (tempos diferentes). Portanto, pela regra da tarefa 2, **`cpu_threads` permanece no fingerprint**, **não há bump de `pipeline_version`** (continua 0.1.0) e a deduplicação anterior com o padrão 2 é preservada. O achado vale para fala sintética contínua; não foi medida a qualidade (WER) de nenhuma configuração.
- Mais CPU rende ganho decrescente (1,31× com 3, 1,41× com 4), sem custo de memória. O padrão continua em 2 (A01 §2: histórico de travamento da máquina com carga pesada); 3 ou 4 ficam como opção documentada.

### Mudanças e verificação

| Item | Resultado |
| --- | --- |
| Suíte no Docker sem rede | **178 testes aprovados** (150 antes): 28 novos (`tests/test_performance.py` com 18; `ExecTest` e `DoctorCpuTest` em `tests/test_wrapper.py`). |
| `WHISPER_BOX_CPUS` | `cpus: ${WHISPER_BOX_CPUS:-2}`; `OMP_NUM_THREADS` e `WHISPER_BOX_CPU_THREADS` derivam dele. Sem variáveis: `NanoCpus 2000000000`, 4 GiB, `none`. `doctor` informa `cpus` só quando diferente de 2. `metadados.json` traz `runtime` (threads e CPUs reais do job). |
| Threads por job | Com o worker em 4 CPUs, um job enfileirado com `WHISPER_BOX_CPU_THREADS=2` rodou com 2 threads (modelo recarregado em cerca de 4 s; `runtime` no metadado), e o mesmo áudio com 4 threads recebeu outro `job_id` (`reused: false`), como esperado. |
| `exec` nas consultas (5 execuções cada, mediana, worker ocioso) | `status` 0,42 s, `result` 0,42 s, `wait --timeout 1` 0,44 s, `list` 0,46 s. Via `run --rm cli`: `status` 1,17 s, `wait` 1,47 s. |
| Mesmo, com um job de 23 min em execução | `exec status` 0,64 s e `wait --timeout 1` 1,56 s (1 s é a própria espera); via `run`: 1,46 s e 2,39 s. Pico de memória do worker durante as consultas: 908 MB, igual ao de um job sem consultas. |
| Fallback com worker parado | `status` devolve o mesmo JSON e código 0; job inexistente devolve `job_not_found` com código 3, igual ao caminho `exec`. Erros JSON do motor (códigos 1 a 4) nunca acionam o fallback (testes). |
| Log do worker | `job_succeeded`: `duration_seconds 1398.08`, `processing_seconds 193.626`, `rtf 0.138`, `attempts 1`, `peak_memory_bytes 909090816`; `job_started` com `queue_wait_seconds 0.243`. Grep dos logs por nome de arquivo e palavras do texto sintético: 0 ocorrências. |
| Healthcheck de progresso | `health` com `WHISPER_BOX_STALL_SECONDS=1` durante um job real: falhou em 5 de 6 tentativas (progresso a cada poucos segundos); com o padrão (1200 s) ficou saudável e o container `healthy`. Testes cobrem ocioso, progredindo, parado (job simulado), `submit` não bloqueado e heartbeat morto. `job_stalled` é só log. |
| Banco real | O `jobs.sqlite` do usuário abriu e ganhou `progress_at` (12 registros legíveis, todos com `progress_at` nulo); teste com banco legado criado à mão também aprovado. |
| Rede e limites | Worker `NetworkMode: none`, 2 CPUs padrão e 4 GiB; painel e worker `healthy` ao final, no padrão. |

Limitações da medição: um único tipo de áudio (TTS, sem ruído, sem pausas), 2 repetições por configuração, máquina de uso normal durante as execuções; `memory.peak` é do container desde que subiu (não por job) e não pode ser zerado dentro do container. O RTF e o ganho por CPU em fala real de reunião podem diferir. Linux e macOS não foram medidos.

### Dados para decidir o checkpoint (tarefa 6, adiada)

Sem uso real suficiente para decidir. O que passa a existir para decidir depois: `interruptions` e `attempt` em `metadados.json`, eventos `job_started` repetidos por `job_id` nos logs, `job_stalled`, `rtf` e `peak_memory_bytes` por job. Custo de referência: a 0,14 de RTF, perder 55 min de uma gravação de 1 h custa cerca de 8 min de reprocessamento por tentativa; o limite continua em 3 tentativas. Critério sugerido para reabrir: duas ou mais interrupções em gravações acima de 30 min.

## Limites desta validação

- Sem GPU, diarização ou adaptador para um sistema de agente específico. A interface web foi adicionada em 20/11/2026 (seção acima) e a captura real foi aprovada pelo usuário na mesma data.
- Sem ensaio em Linux/macOS como host ou arquitetura ARM.
- Sem teste de queda de energia, corrupção do volume ou restauração de backup.
- Não há garantia de prazo ou precisão para outras gravações; ruído, duração de fala e carga concorrente alteram os resultados.
