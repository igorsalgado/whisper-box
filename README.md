# Whisper Box

**Transforme gravações de reuniões em texto, localmente, com Docker.**

Você ou um agente submete o arquivo, aguarda a conclusão e recebe os caminhos dos resultados. O próprio projeto gerencia a fila, o modelo e a transcrição.

- Offline depois da preparação inicial; sem API ou chave da OpenAI.
- faster-whisper `small`, CPU, `int8`, português por padrão.
- Um trabalho por vez, com limite de **2 CPUs e 4 GiB de RAM**.
- TXT com horários, SRT, segmentos JSONL e metadados JSON.
- Fila persistente, deduplicação e recuperação de trabalhos interrompidos.
- Retorno JSON curto para agentes, sem imprimir a transcrição na conversa.

```text
Usuário/agente → submit → fila SQLite → worker Docker → saida/<job_id>/
              ← job_id
Usuário/agente → wait/result → estado e caminhos dos arquivos
```

## Usar com um agente

Peça ao seu agente de código (Claude Code, Codex ou similar):

> Clone https://github.com/igorsalgado/whisper-box, siga o AGENTS.md e transcreva uma gravação minha.

O agente lê o [AGENTS.md](AGENTS.md) (o Claude Code o carrega via `CLAUDE.md`), roda `python whisper-box.py doctor`, instala ou prepara o que faltar pedindo sua permissão, pergunta qual arquivo transcrever e executa `python whisper-box.py transcribe --input CAMINHO`. Você recebe os caminhos do TXT, SRT, JSONL e metadados.

## Pré-requisitos

- Windows, Linux ou macOS com **Python 3.8+** no host (somente biblioteca padrão, sem `pip install`).
- Docker com engine Linux (Docker Desktop ou Docker Engine) e Compose v2 com suporte a `up --wait`.
- Internet na preparação inicial para imagem, dependências e modelo.
- Espaço para a imagem, aproximadamente 500 MB de modelo e cópias das gravações.

O Python do host executa apenas o wrapper `whisper-box.py`, que monta as chamadas ao Docker Compose. Bibliotecas de transcrição, FFmpeg/PyAV e o modelo ficam no container; não há GPU nem dependências extras no host. Os limites do worker não incluem o consumo dos outros serviços do Docker.

No Windows, use `py -3` ou `python`; em Linux/macOS, `python3`. Os exemplos abaixo usam `python`.

## Instalação do zero

### 1. Pré-requisitos por sistema

| Sistema | Python 3.8+ | Docker |
| --- | --- | --- |
| Windows 10/11 | Instalador de [python.org](https://www.python.org/downloads/) ou `winget install Python.Python.3.12`. Use `py -3` ou `python`. | Docker Desktop com WSL 2 e containers Linux. |
| Linux | Já incluso na maioria das distribuições (`python3`). | Docker Engine com o plugin Compose v2. Adicione o usuário ao grupo `docker` ou use `sudo`. |
| macOS | `brew install python` ou instalador de python.org (`python3`). | Docker Desktop. |

Confira antes de continuar (depois de clonar, `python whisper-box.py doctor` faz essa verificação e indica o próximo passo em JSON):

```bash
python --version          # 3.8 ou superior (python3 em Linux/macOS)
docker compose version    # Compose v2
docker info               # engine em execução
```

### 2. Clonar e preparar (uma vez, com internet)

```bash
git clone https://github.com/igorsalgado/whisper-box.git
cd whisper-box
python whisper-box.py prepare
```

`prepare` constrói a imagem e baixa/verifica o modelo (aproximadamente 500 MB). A partir daí, tudo roda offline.

### 3. Uso diário

```bash
# Um comando: inicia o worker, submete, aguarda e devolve os caminhos.
python whisper-box.py transcribe --input "/home/voce/Reunioes/gravacao.mp4"   # Linux/macOS
python whisper-box.py transcribe --input "C:\Reunioes\gravacao.mp4"           # Windows

# Se a execução for interrompida, retome pelo job_id (impresso em stderr).
python whisper-box.py transcribe --job "SEU_JOB_ID"
```

Aguarde o arquivo terminar de gravar antes de transcrever. Os passos individuais (`start`, `submit`, `wait`, `result`) continuam disponíveis; veja [Comandos](#comandos).

Em Linux/macOS, o arquivo também pode ser executado diretamente: `./whisper-box.py start`. O mesmo comando funciona em PowerShell, cmd, bash ou zsh; não há scripts específicos de shell.

`prepare` preserva a revisão do modelo já instalada e verifica os hashes. Não precisa executá-lo por reunião. Para reconstruir somente o código, use `docker compose build worker` e depois `start`.

O projeto copia a gravação, detecta alterações durante a cópia e mantém o original intacto. Caminhos com espaços e acentos são aceitos.

## Comandos

Use `python whisper-box.py COMANDO`.

| Comando | Uso |
| --- | --- |
| `doctor` | Verifica Python, Docker, Compose, engine, imagem e modelo; indica um `next_step` em JSON. |
| `transcribe --input CAMINHO` | Fluxo completo: start, submit, espera renovada e resultado verificado. Aceita `--language` e `--timeout-seconds` (padrão 7200). |
| `transcribe --job ID` | Retoma o acompanhamento de um trabalho existente, sem submeter de novo. |
| `prepare` | Constrói a imagem e prepara/verifica o modelo, com internet. |
| `start` | Inicia o worker offline; pode ser repetido. |
| `stop` | Para o worker, preservando fila, modelo e arquivos. |
| `submit --input CAMINHO` | Copia e enfileira uma gravação; padrão `--language pt`. |
| `submit --input CAMINHO --language en` | Usa inglês; também aceita `es` e `auto`. |
| `status --job ID` | Consulta estado, tentativa e último segundo processado. |
| `wait --job ID --timeout 30` | Aguarda até 30 segundos, devolvendo um único JSON. |
| `result --job ID` | Retorna os caminhos dos artefatos completos. |
| `logs` | Mostra os últimos 50 eventos do worker. |

Estados: `queued`, `running`, `succeeded` e `failed`. Os horários de eventos são Unix timestamps em segundos. `progress_seconds` é a posição processada no áudio; não representa previsão de término.

### Códigos de saída

| Código | Significado |
| --- | --- |
| `0` | Comando atendido; em `wait`/`result`/`transcribe`, trabalho concluído com sucesso; em `doctor`, ambiente pronto. |
| `1` | Falha no trabalho ou na operação; em `doctor`, há um `next_step` pendente. |
| `2` | A espera (ou o orçamento de `transcribe`) atingiu o tempo limite; o trabalho continua. |
| `3` | Argumento inválido ou trabalho inexistente. |
| `4` | `result` solicitado enquanto o trabalho ainda está pendente/em execução. |

`status` pode retornar `0` com estado `failed`: a consulta foi atendida. `wait` e `result` retornam `1` nesse estado.

## Integração com agentes

O roteiro completo para agentes (instalação, diagnóstico, pergunta ao usuário, erros e resposta) está no [AGENTS.md](AGENTS.md). Em resumo:

```bash
python whisper-box.py doctor                      # repetir até "ready": true
python whisper-box.py transcribe --input CAMINHO  # um JSON final em stdout
```

`transcribe` renova `wait` internamente em janelas de até 30 segundos, dentro de `--timeout-seconds`. Sistemas que preferem controlar a espera podem usar `submit` e repetir `wait --job ID --timeout 30` enquanto o código de saída for `2`. Cada `wait` admite de 1 a 60 segundos. Fechar o terminal, desconectar o agente ou encerrar a espera não interrompe o worker. Uma consulta posterior usa o mesmo `job_id`.

`doctor`, `transcribe`, `submit`, `status`, `wait` e `result` escrevem um objeto JSON em stdout. Mensagens operacionais do Docker ficam em stderr: capture os canais separadamente, sem `2>&1` ao interpretar o JSON.

Exemplo abreviado de conclusão no Windows. Os caminhos em `files` seguem o formato do host que executou o wrapper; em Linux/macOS aparecem como `/home/.../saida/...`.

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

A transcrição local não usa tokens da OpenAI. Conversar com um agente ou pedir que ele leia e resuma a saída pode consumir tokens. Deixar a espera em código evita novas mensagens ao modelo durante o processamento.

## Persistência e recuperação

| Local | Conteúdo |
| --- | --- |
| `entrada/<job_id>/` | Cópia da mídia submetida. |
| `saida/<job_id>/` | TXT, SRT, JSONL, metadados e manifesto de integridade. |
| `saida/.partial/` | Tentativas incompletas, não anunciadas como resultados. |
| `modelos/` | Modelo, revisão e hashes dos arquivos. |
| Volume Docker `whisper-box_state` | SQLite, lock exclusivo e sinal de saúde. |

O modelo é carregado no primeiro trabalho e reutilizado até encerrar o worker. O áudio é decodificado em blocos de cinco minutos, limitando memória conforme a duração aumenta.

Os resultados só aparecem na pasta final quando todos os artefatos estão completos. `result` verifica os hashes. Alterar ou apagar arquivos finais invalida essa verificação.

Submeter os mesmos bytes com o mesmo idioma, versão do pipeline e revisão do modelo reutiliza o trabalho (`reused: true`). Após falha, nova submissão cria outro identificador e preserva o histórico.

Depois de uma interrupção, o worker recupera trabalhos em execução e pode reiniciar o arquivo desde o começo. Há no máximo três tentativas automáticas por trabalho. Erros normais de mídia não são repetidos automaticamente.

Não há limpeza automática: arquivos permanecem até remoção manual. Pare o worker antes de copiar o volume de estado e as pastas para um backup consistente. **Não use `docker compose down -v` se quiser preservar a fila.**

## Privacidade e offline

- Worker e containers de trabalho usam `network_mode: none`, sem portas abertas.
- `prepare` é a exceção, com internet para baixar o modelo da Hugging Face.
- O runtime lê o modelo local e não envia mídia a serviços de transcrição.
- Não há telemetria de aplicação ou credenciais de APIs.
- Gravações, saídas, modelos, logs e estado ficam fora do Git e do contexto de build.
- Logs da aplicação registram identificadores/eventos, sem o texto da reunião.

Os dados seguem as permissões locais do computador e do Docker. O projeto não implementa criptografia adicional.

## Testes e desenvolvimento

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test

# Ensaio pelo wrapper com modelo preparado e mídia fornecida explicitamente.
python tests/smoke.py --input "/home/voce/Reunioes/gravacao.mp4"
```

A suíte automatizada roda sem rede e sem carregar o modelo, incluindo os testes do wrapper (`tests/test_wrapper.py`), que simulam o Docker. Eles também rodam no host com `python -m unittest tests.test_wrapper`. O ensaio completo valida também a gravação fornecida, formatos de mídia e silêncio sintético de duas horas. Fixtures e relatório ficam em `logs/`, fora do Git.

Resultados medidos: [docs/VALIDACAO.md](docs/VALIDACAO.md). Contrato: [action A01](docs/actions/A01-transcricao-offline-docker.md).

Para atualizar código/dependências, pare o worker, reconstrua a imagem e execute `start`. Os dados ficam fora da imagem. Mudanças na inferência devem atualizar a versão do pipeline para evitar reutilização incompatível. Não há migração automática de schemas de versões futuras nesta versão.

## Diagnóstico

| Sintoma | Ação |
| --- | --- |
| Docker indisponível | Abra o Docker Desktop ou inicie o serviço Docker e aguarde o engine Linux. |
| `python` não encontrado | Instale Python 3.8+; no Windows, tente `py -3 whisper-box.py`. |
| `permission denied` no socket do Docker (Linux) | Adicione o usuário ao grupo `docker` e abra nova sessão, ou use `sudo`. |
| `model_not_ready` | Execute `prepare`. Se o modelo estiver corrompido, pare o worker e preserve/renomeie `modelos` antes de preparar novamente. |
| `worker_unavailable` | Execute `start` e consulte `logs`. |
| `wait` com código `2` | Repita com o mesmo identificador. |
| `failed` | Consulte `status`, corrija o arquivo/ambiente e submeta novamente. |
| `output_incomplete` | Artefatos foram alterados/removidos; restaure um backup consistente. |
| Worker encerrado por memória | Consulte `docker inspect`, reduza outras cargas e registre a ocorrência antes de ajustar limites. |

## Limitações

- Validado em Windows com Docker Linux amd64. Linux e macOS são suportados pelo wrapper Python e por testes de caminhos POSIX, mas ainda não têm ensaio completo registrado; ARM não foi testado.
- Em Linux, arquivos criados pelo container em `entrada/` e `saida/` pertencem ao `root`: são legíveis pelo usuário, mas a remoção manual pode exigir `sudo`.
- Sem captura ao vivo, identificação de falantes, interface web ou resumo automático.
- Fronteiras de cinco minutos podem dividir palavras; revise esses trechos quando necessário.
- Silêncio gera texto/legenda vazios e `no_speech: true`; mídia sem stream de áudio falha.
- Nomes próprios, siglas, ruído e falas simultâneas afetam a precisão. A transcrição automática pode exigir revisão.

## Dependências

Motor: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [PyAV](https://pyav.org/docs/stable/) e [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small). Dependências e modelo mantêm suas próprias licenças. O projeto ainda não define licença de distribuição própria.
