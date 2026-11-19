# Whisper Box — prompt do agente

> **Este README é um prompt.** Se você é um agente de código (Claude Code, Codex, Cursor ou similar), o texto abaixo são as suas instruções para operar este projeto. Siga-as do início ao fim.
>
> Humano: entregue este repositório ao seu agente e diga **“Clone https://github.com/igorsalgado/whisper-box, leia o README e transcreva uma gravação minha.”**

## Sua missão

Transcrever gravações de áudio ou vídeo do usuário **localmente**, com Docker, e devolver os caminhos dos arquivos gerados: TXT com horários, legenda SRT, segmentos JSONL e metadados JSON.

O projeto já contém o motor (faster-whisper `small`, CPU, `int8`, português por padrão), a fila, a deduplicação e a recuperação de falhas. Tudo isso roda dentro da imagem Docker, inclusive o FFmpeg, que vem embutido como biblioteca no PyAV e decodifica mp4, mp3, m4a, wav e outros formatos. O host não precisa de FFmpeg nem de bibliotecas Python. Seu trabalho é **preparar o ambiente, pedir o arquivo, executar um comando e reportar o resultado**. Depois da preparação inicial, tudo roda offline, sem API, chave ou custo de tokens durante a transcrição.

## Regras invioláveis

1. Use somente `whisper-box.py`. Não escreva código de transcrição, não instale faster-whisper/FFmpeg no host e não crie scripts `.ps1`/`.sh`.
2. Peça permissão ao usuário antes de instalar software no sistema (Python, Docker) e antes do download inicial (`prepare`).
3. Nunca envie a gravação ou a transcrição para fora da máquina nem use APIs de transcrição em nuvem.
4. Não mova, renomeie ou apague o arquivo original do usuário.
5. Não rode `docker compose down -v` e não apague `entrada/`, `saida/`, `modelos/` ou volumes para “corrigir” falhas.
6. Não rode `prepare` a cada reunião; ele é feito uma única vez.
7. Leia stdout como JSON e stderr como diagnóstico, em canais separados. Nunca use `2>&1` ao interpretar a resposta.
8. Não cole a transcrição na conversa, a menos que o usuário peça resumo, ata ou análise.

## Passo 0 — Obter o projeto

Se o repositório ainda não estiver na máquina, clone-o e trabalhe na raiz:

```bash
git clone https://github.com/igorsalgado/whisper-box.git
cd whisper-box
```

Reutilize sempre o mesmo clone. O modelo, a fila e os resultados ficam nele; um clone novo exige preparar tudo de novo.

## Passo 1 — Garantir Python 3.8+

Teste, nesta ordem, até um responder 3.8 ou superior: `python --version`, `python3 --version` e, no Windows, `py -3 --version`. Nos exemplos abaixo, `python` significa o interpretador encontrado.

Se nenhum existir, peça permissão e instale:

| Sistema | Comando |
| --- | --- |
| Windows | `winget install -e --id Python.Python.3.12` |
| macOS | `brew install python` |
| Linux | `sudo apt install python3` / `sudo dnf install python3` (conforme a distribuição) |

Nenhum `pip install` é necessário: o wrapper usa só a biblioteca padrão.

## Passo 2 — Diagnosticar e corrigir o ambiente

```bash
python whisper-box.py doctor
```

A resposta é um JSON com `ready`, `platform`, `checks` e **um** `next_step`. Execute o passo indicado e rode `doctor` de novo, até `"ready": true`.

| `next_step.code` | O que você faz |
| --- | --- |
| `install_docker` / `install_compose` | Explique ao usuário e peça permissão (`requires_user_approval: true`). Instale com o comando de `next_step.action`. Pode exigir administrador, WSL 2 ou reinício; se você não puder executar, entregue a instrução ao usuário e aguarde. |
| `start_docker` | Inicie o Docker conforme `action`, aguarde até cerca de 2 minutos e rode `doctor` novamente. |
| `prepare` | Avise que será baixado ~500 MB uma única vez, com internet. Com o ok, execute `python whisper-box.py prepare` (pode levar vários minutos). |
| `ask_for_recording` | Ambiente pronto. Vá ao passo 3. |

Recursos: o worker usa até **2 CPUs e 4 GiB de RAM**, sem GPU. Garanta espaço para a imagem, o modelo e as cópias das gravações.

## Passo 3 — Pedir a gravação ao usuário

Se o caminho ainda não estiver na conversa, pergunte:

> Qual gravação devo transcrever? Envie o caminho completo do arquivo — por exemplo `C:\Reunioes\call.mp4` ou `/home/voce/Reunioes/call.mp4`. Aceito vídeo ou áudio (mp4, mp3, wav, m4a…). A gravação precisa estar finalizada. Vou transcrever em português, a menos que você prefira inglês, espanhol ou detecção automática.

- O arquivo precisa estar **no computador que roda o Docker**. Se o usuário anexou o arquivo na conversa e ele já existe localmente, use esse caminho; caso contrário, peça o caminho local.
- Caminhos com espaços e acentos são aceitos.
- Uma gravação por chamada. Para várias, transcreva em sequência.

## Passo 4 — Transcrever

```bash
python whisper-box.py transcribe --input "CAMINHO" --language pt
```

- `--language`: `pt` (padrão), `en`, `es` ou `auto`.
- O comando inicia o worker, copia e enfileira a gravação, aguarda e verifica o resultado. Ele **bloqueia até terminar**, com orçamento de 2 horas (`--timeout-seconds`, de 1 a 86400).
- stderr recebe `{"event": "whisper_waiting", "job_id": "..."}`. **Guarde o `job_id`.**
- Se a sua ferramenta de execução tiver limite de tempo, rode o comando em segundo plano ou com tempo maior. Se a execução cair ou o orçamento acabar, retome com:

```bash
python whisper-box.py transcribe --job JOB_ID
```

- **Nunca** submeta a mesma gravação de novo só porque a espera terminou: a fila continua processando. Mesmo que submeta, os mesmos bytes com o mesmo idioma reutilizam o trabalho existente (`reused: true`).
- Referência medida: 23 minutos de áudio levaram cerca de 3 minutos em CPU. Informe ao usuário que gravações longas podem levar vários minutos.

## Passo 5 — Interpretar e responder

| Código de saída | Significado | O que você faz |
| --- | --- | --- |
| `0` | Concluído e verificado. | Entregue os caminhos de `files`. |
| `1` | Falha da transcrição ou do ambiente. | Relate `error.code` e `error.message`; consulte a tabela de erros. |
| `2` | Orçamento de espera esgotado; o trabalho continua. | Informe o `job_id` e retome com `transcribe --job`. |
| `3` | Argumento, arquivo ou trabalho inválido. | Corrija ou peça outro caminho ao usuário. |

Resposta de sucesso (Windows; em Linux/macOS os caminhos são `/home/.../saida/...`):

```json
{
  "job_id": "identificador",
  "status": "succeeded",
  "files": {
    "text": "C:\\Projetos\\whisper-box\\saida\\identificador\\transcricao.txt",
    "srt": "C:\\Projetos\\whisper-box\\saida\\identificador\\transcricao.srt",
    "segments": "C:\\Projetos\\whisper-box\\saida\\identificador\\segmentos.jsonl",
    "metadata": "C:\\Projetos\\whisper-box\\saida\\identificador\\metadados.json"
  },
  "output_relative": "saida/identificador"
}
```

Responda ao usuário assim:

> Transcrição concluída (job `JOB_ID`).
> - Texto com horários: `files.text`
> - Legendas SRT: `files.srt`
> - Segmentos e metadados: `files.segments`, `files.metadata`

Se o usuário pediu resumo, ata, decisões ou tarefas, leia `files.text` nessa etapa. Avise que a transcrição é automática: nomes próprios, siglas, ruído e falas simultâneas podem exigir revisão.

## Erros e como agir

| Sinal | O que você faz |
| --- | --- |
| `python` não encontrado | Passo 1. No Windows, tente `py -3 whisper-box.py`. |
| `docker_error`, `worker_unavailable` | Rode `doctor`, corrija e repita `transcribe` (com `--job` se já houver identificador). |
| `permission denied` no socket do Docker (Linux) | Peça permissão para `sudo usermod -aG docker $USER`; o usuário precisa abrir nova sessão. |
| `model_not_ready` | Rode `doctor` e, se indicado, `prepare`. Se o modelo estiver corrompido, peça ao usuário para preservar/renomear `modelos/` antes de preparar de novo. |
| `input_not_found` | Confirme o caminho com o usuário. |
| `input_changed` | A gravação ainda está sendo escrita; aguarde terminar e repita. |
| `invalid_media`, `no_audio` | O arquivo não tem áudio legível; peça outro. |
| `failed` com outro motivo | Relate o erro; uma nova submissão cria outro `job_id` e preserva o histórico. |
| `output_incomplete`, `output_unreachable` | Não apague nada; relate ao usuário com o `job_id`. |
| Worker encerrado por memória | Relate; peça ao usuário para reduzir outras cargas. Não altere limites por conta própria. |

## Referência

### Comandos

Todos são `python whisper-box.py COMANDO` e escrevem um único JSON em stdout (exceto `logs`).

| Comando | Uso |
| --- | --- |
| `doctor` | Diagnostica Python, Docker, Compose, engine, imagem e modelo; indica um `next_step`. Código 0 quando pronto. |
| `transcribe --input CAMINHO` | Fluxo completo: start, submit, espera renovada e resultado verificado. Aceita `--language` e `--timeout-seconds`. |
| `transcribe --job ID` | Retoma um trabalho existente, sem submeter de novo. |
| `prepare` | Uma vez, com internet: constrói a imagem e baixa/verifica o modelo. Preserva a revisão já instalada. |
| `start` / `stop` | Inicia ou para o worker; fila, modelo e arquivos são preservados. |
| `submit --input CAMINHO [--language pt]` | Só enfileira e devolve `job_id`. |
| `wait --job ID --timeout 30` | Aguarda de 1 a 60 segundos; código 2 se o tempo acabar. |
| `status --job ID` / `result --job ID` | Estado e progresso / caminhos verificados; `result` devolve código 4 se o trabalho ainda estiver pendente. |
| `logs` | Últimos 50 eventos do worker, para diagnóstico. |

Estados: `queued`, `running`, `succeeded`, `failed`. `progress_seconds` é a posição processada no áudio, não uma previsão de término.

### Onde ficam os dados

| Local | Conteúdo |
| --- | --- |
| `entrada/<job_id>/` | Cópia da mídia submetida. |
| `saida/<job_id>/` | TXT, SRT, JSONL, metadados e manifesto de integridade. |
| `saida/.partial/` | Tentativas incompletas; nunca são anunciadas como resultado. |
| `modelos/` | Modelo, revisão e hashes. |
| Volume Docker `whisper-box_state` | Fila SQLite, lock exclusivo e sinal de saúde. |

Não há limpeza automática. Em Linux, arquivos criados pelo container pertencem ao `root`: são legíveis, mas a remoção pode exigir `sudo`.

### Garantias do sistema

- Fechar o terminal, desconectar o agente ou esgotar a espera **não** interrompe o worker; retome pelo mesmo `job_id`.
- Após uma interrupção, o worker recupera o trabalho e pode reiniciar o arquivo, com até três tentativas automáticas.
- Resultados só aparecem completos e com hashes verificados; alterar arquivos finais invalida a verificação.
- Worker e containers de trabalho rodam com `network_mode: none`; apenas `prepare` usa internet. Sem telemetria, credenciais ou envio de mídia. Logs não contêm o texto da reunião.

### Limitações para informar ao usuário

- Sem captura ao vivo, identificação de falantes ou resumo automático.
- Silêncio gera texto vazio com `no_speech: true`; mídia sem áudio falha.
- Fronteiras de cinco minutos podem dividir palavras.
- Validado em Windows com Docker Linux amd64. Linux e macOS são suportados, mas ainda sem ensaio completo registrado; ARM não foi testado.

## Se pedirem para alterar o projeto

Operar e desenvolver são tarefas diferentes. Para mudar código, testes ou documentação, siga [AGENTS.md](AGENTS.md) (regras de desenvolvimento, testes em Docker e Git). Evidências medidas: [docs/VALIDACAO.md](docs/VALIDACAO.md). Contrato original: [action A01](docs/actions/A01-transcricao-offline-docker.md).

Motor: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [PyAV](https://pyav.org/docs/stable/) e [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small), cada um com sua licença. O projeto ainda não define licença própria.
