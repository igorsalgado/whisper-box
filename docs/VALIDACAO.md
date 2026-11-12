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

Casos do ensaio automatizado `tests/smoke.ps1`:

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

```powershell
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 prepare
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\smoke.ps1 --input "C:\Reunioes\gravacao.mp4"
```

Para repetir o ensaio de recuperação, submeta uma mídia ainda não processada, consulte `result` enquanto estiver em execução, execute `wait --timeout 1`, pare e inicie o worker e aguarde o mesmo identificador. Os metadados devem registrar a tentativa 2 e uma interrupção. A política de três tentativas também é coberta pela suíte automatizada.

Relatórios brutos, fixtures e resultados permanecem em `logs/`, `entrada/` e `saida/`, ignorados pelo Git. Nenhuma fala, gravação ou transcrição real está incluída neste relatório.

## Limites desta validação

- Sem GPU, interface web, diarização ou adaptador para um sistema de agente específico.
- Sem ensaio em Linux/macOS como host ou arquitetura ARM.
- Sem teste de queda de energia, corrupção do volume ou restauração de backup.
- Não há garantia de prazo ou precisão para outras gravações; ruído, duração de fala e carga concorrente alteram os resultados.
