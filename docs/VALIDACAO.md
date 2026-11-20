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

## Limites desta validação

- Sem GPU, diarização ou adaptador para um sistema de agente específico. A interface web foi adicionada em 20/11/2026 (seção acima), com a captura real ainda por validar.
- Sem ensaio em Linux/macOS como host ou arquitetura ARM.
- Sem teste de queda de energia, corrupção do volume ou restauração de backup.
- Não há garantia de prazo ou precisão para outras gravações; ruído, duração de fala e carga concorrente alteram os resultados.
