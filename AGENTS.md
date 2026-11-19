# Guia do agente — Whisper Box

Este projeto transcreve gravações de áudio/vídeo **localmente**, com Docker. Se o usuário pediu uma transcrição, siga o roteiro abaixo do início ao fim. Você não escreve código de transcrição, não instala bibliotecas Python e não cria scripts: o programa `whisper-box.py` faz tudo e responde em JSON.

## Roteiro do agente

### 0. Obter o projeto

Se o repositório ainda não estiver na máquina, clone-o e trabalhe na raiz dele:

```bash
git clone https://github.com/igorsalgado/whisper-box.git
cd whisper-box
```

Reutilize sempre o mesmo clone. Modelo, fila e resultados ficam nele; um clone novo exigiria preparar tudo de novo.

### 1. Garantir Python 3.8+

Teste `python --version`, `python3 --version` ou (Windows) `py -3 --version`. Use o primeiro que responder 3.8 ou superior; nos exemplos ele aparece como `python`.

Se nenhum existir, **peça permissão ao usuário** e instale:

| Sistema | Comando |
| --- | --- |
| Windows | `winget install -e --id Python.Python.3.12` |
| macOS | `brew install python` |
| Linux | pacote `python3` da distribuição (`sudo apt install python3`, `sudo dnf install python3`…) |

Nenhum `pip install` é necessário.

### 2. Diagnosticar e corrigir o ambiente

```bash
python whisper-box.py doctor
```

Devolve um JSON com `ready`, `platform`, `checks` e **um** `next_step`. Execute o passo indicado e rode `doctor` de novo, até `ready: true`.

| `next_step.code` | O que fazer |
| --- | --- |
| `install_docker` / `install_compose` | `requires_user_approval: true`. Explique ao usuário e peça permissão antes de instalar com o comando de `next_step.action`. Pode exigir administrador ou reiniciar; se você não puder executar, entregue a instrução ao usuário e aguarde. |
| `start_docker` | Inicie o Docker conforme `action`, aguarde até cerca de 2 minutos e rode `doctor` novamente. |
| `prepare` | Avise que é necessário baixar a imagem e o modelo (~500 MB, uma única vez, com internet). Com o ok do usuário, execute `python whisper-box.py prepare`; pode levar vários minutos. |
| `ask_for_recording` | Ambiente pronto. Siga para o passo 3. |

### 3. Pedir a gravação ao usuário

Se o caminho ainda não estiver na conversa, pergunte:

> Qual gravação devo transcrever? Envie o caminho completo do arquivo — por exemplo `C:\Reunioes\call.mp4` ou `/home/voce/Reunioes/call.mp4`. Aceito vídeo ou áudio (mp4, mp3, wav, m4a…). A gravação precisa estar finalizada. Vou transcrever em português, a menos que você prefira inglês, espanhol ou detecção automática.

- O arquivo precisa estar **no computador que roda o Docker**. Se o usuário anexou o arquivo na conversa e ele já existe localmente, use esse caminho; caso contrário, peça o caminho local.
- Não mova, renomeie nem copie o original; o projeto faz a própria cópia.
- Uma gravação por chamada. Para várias, transcreva em sequência.

### 4. Transcrever

```bash
python whisper-box.py transcribe --input "CAMINHO" --language pt
```

`--language` aceita `pt` (padrão), `en`, `es` ou `auto`. O comando inicia o worker, submete, aguarda e verifica o resultado. Ele **bloqueia até terminar**, com orçamento padrão de 2 horas (`--timeout-seconds` de 1 a 86400).

- **stdout** recebe um único JSON final. **stderr** recebe o diagnóstico do Docker e o evento `{"event": "whisper_waiting", "job_id": "..."}`. Capture os canais separadamente; não use `2>&1`.
- Guarde o `job_id`. Se a sua ferramenta de execução tiver limite de tempo, rode o comando em segundo plano ou com tempo maior. Se a execução cair, retome com `python whisper-box.py transcribe --job JOB_ID`.
- **Nunca** submeta a mesma gravação de novo só porque a espera terminou; a fila continua processando.
- Referência medida: 23 minutos de áudio foram transcritos em cerca de 3 minutos, em CPU ([VALIDACAO.md](docs/VALIDACAO.md)).

### 5. Interpretar e responder

| Código de saída | Significado | Ação |
| --- | --- | --- |
| `0` | Concluído e verificado. | Entregue os caminhos de `files`. |
| `1` | Falha da transcrição ou do ambiente. | Relate `error.code`/`error.message`; consulte a tabela de erros. |
| `2` | Orçamento de espera esgotado; o trabalho continua. | Informe o `job_id` e retome com `transcribe --job`. |
| `3` | Argumento, arquivo ou trabalho inválido. | Corrija ou peça outro caminho ao usuário. |

Resposta sugerida ao usuário:

> Transcrição concluída (job `JOB_ID`).
> - Texto com horários: `files.text`
> - Legendas SRT: `files.srt`
> - Segmentos e metadados: `files.segments`, `files.metadata`

Não leia nem cole a transcrição na conversa, a menos que o usuário peça resumo, ata ou análise; nesse caso, leia `files.text`.

### Erros comuns

| `error.code` | Ação |
| --- | --- |
| `model_not_ready` | Rode `doctor` e, se indicado, `prepare`. |
| `docker_error`, `worker_unavailable` | Rode `doctor`; depois repita `transcribe` (com `--job` se já houver identificador). |
| `input_not_found` | Confirme o caminho com o usuário. |
| `input_changed` | A gravação ainda está sendo escrita; aguarde terminar e repita. |
| `invalid_media`, `no_audio` | O arquivo não tem áudio legível; peça outro arquivo. |
| `output_incomplete`, `output_unreachable` | Não apague nada; relate ao usuário com o `job_id`. |

### Não faça

- Rodar `prepare` a cada reunião, `docker compose down -v` ou apagar `entrada/`, `saida/`, `modelos/` ou volumes para "corrigir" falhas.
- Instalar faster-whisper/FFmpeg no host, escrever outro script de transcrição ou usar APIs de transcrição em nuvem.
- Enviar a gravação ou a transcrição para fora da máquina sem pedido explícito do usuário.

### Comandos de baixo nível

`start`, `submit`, `wait`, `result`, `status`, `stop` e `logs` continuam disponíveis para integrações próprias; veja o [README](README.md). Para o fluxo comum, prefira `doctor` + `transcribe`.

## Desenvolvimento

- Todo runtime de transcrição e a suíte rodam em Docker. O host exige apenas Python 3.8+ para o wrapper.
- `whisper-box.py` usa somente a biblioteca padrão; não adicione dependências instaladas no host.
- Não crie scripts específicos de shell (`.ps1`, `.sh`); a interface de host é somente Python.
- Preserve `network_mode: none` no worker e na CLI, o worker exclusivo e os limites de recursos.
- Uma alteração de inferência exige rever a versão do pipeline e a deduplicação.
- Valide com `docker compose build worker` e `docker compose --profile test run --rm --no-deps -T test` (inclui `tests/test_wrapper.py`) quando alterar os comandos.
- Leia [README.md](README.md), a [action A01](docs/actions/A01-transcricao-offline-docker.md) e o [relatório de validação](docs/VALIDACAO.md).

## Dados e Git

- Nunca versionar gravações, transcrições reais, modelos, logs, estado ou credenciais.
- Inspecionar os arquivos selecionados antes de cada commit; usar pathspecs explícitos.
- Não apagar o original nem remover volumes de estado para corrigir uma falha.
- Commits em português, com Conventional Commits e uma mudança coerente por commit.
