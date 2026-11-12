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

## Pré-requisitos

- Windows com PowerShell 5.1 ou superior.
- Docker Desktop com containers Linux e Compose v2 com suporte a `up --wait`.
- Internet na preparação inicial para imagem, dependências e modelo.
- Espaço para a imagem, aproximadamente 500 MB de modelo e cópias das gravações.

Não precisa instalar Python ou FFmpeg no Windows, nem ter GPU. O áudio é decodificado com PyAV no container. Os limites do worker não incluem o consumo dos outros serviços do Docker Desktop.

## Instalação e uso

```powershell
git clone https://github.com/igorsalgado/whisper-box.git
cd whisper-box

# Uma vez, com internet: constrói a imagem e baixa/verifica o modelo.
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 prepare

# Inicia o worker em segundo plano e aguarda sua prontidão.
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 start

# Devolve um job_id; aguarde o arquivo terminar de gravar antes de submeter.
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 submit --input "C:\Reunioes\gravacao.mp4"

# Substitua pelo identificador recebido.
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 wait --job "SEU_JOB_ID" --timeout 30
powershell -NoProfile -ExecutionPolicy Bypass -File .\whisper-box.ps1 result --job "SEU_JOB_ID"
```

`-ExecutionPolicy Bypass` vale somente para o processo iniciado, sem alterar a política global. Se sua política permite scripts locais, pode executar `./whisper-box.ps1` diretamente. Sistemas gerenciados podem impor restrições adicionais.

`prepare` preserva a revisão do modelo já instalada e verifica os hashes. Não precisa executá-lo por reunião. Para reconstruir somente o código, use `docker compose build worker` e depois `start`.

O projeto copia a gravação, detecta alterações durante a cópia e mantém o original intacto. Caminhos com espaços e acentos são aceitos.

## Comandos

Use `./whisper-box.ps1` ou o prefixo completo do PowerShell acima.

| Comando | Uso |
| --- | --- |
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
| `0` | Comando atendido; em `wait`/`result`, trabalho concluído com sucesso. |
| `1` | Falha no trabalho ou na operação. |
| `2` | A espera atingiu o tempo limite; o trabalho continua. |
| `3` | Argumento inválido ou trabalho inexistente. |
| `4` | `result` solicitado enquanto o trabalho ainda está pendente/em execução. |

`status` pode retornar `0` com estado `failed`: a consulta foi atendida. `wait` e `result` retornam `1` nesse estado.

## Integração com agentes

O agente executa o projeto e recebe o resultado. Não precisa escrever Python ou acompanhar segmentos. O loop abaixo deve rodar em código no sistema associado ao agente:

```powershell
$runner = Join-Path (Get-Location).Path 'whisper-box.ps1'
$submission = & powershell -NoProfile -ExecutionPolicy Bypass -File $runner submit --input 'C:\Reunioes\gravacao.mp4'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao submeter a gravacao.' }
$job = $submission | ConvertFrom-Json

do {
    $response = & powershell -NoProfile -ExecutionPolicy Bypass -File $runner wait --job $job.job_id --timeout 30
    $waitCode = $LASTEXITCODE
    if ($waitCode -notin 0, 2) { throw $response }
} while ($waitCode -eq 2)

$result = $response | ConvertFrom-Json
$result.files
```

Cada `wait` admite de 1 a 60 segundos. O sistema define o prazo total. Fechar o terminal, desconectar o agente ou encerrar a espera não interrompe o worker. Uma consulta posterior usa o mesmo `job_id`.

`submit`, `status`, `wait` e `result` escrevem um objeto JSON em stdout. Mensagens operacionais do Docker ficam em stderr: capture os canais separadamente, sem `2>&1` ao interpretar o JSON.

Exemplo abreviado de conclusão:

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

```powershell
docker compose build worker
docker compose --profile test run --rm --no-deps -T test

# Ensaio pelo wrapper com modelo preparado e mídia fornecida explicitamente.
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\smoke.ps1 --input "C:\Reunioes\gravacao.mp4"
```

A suíte automatizada roda sem rede e sem carregar o modelo. O ensaio completo valida também a gravação fornecida, formatos de mídia e silêncio sintético de duas horas. Fixtures e relatório ficam em `logs/`, fora do Git.

Resultados medidos: [docs/VALIDACAO.md](docs/VALIDACAO.md). Contrato: [action A01](docs/actions/A01-transcricao-offline-docker.md).

Para atualizar código/dependências, pare o worker, reconstrua a imagem e execute `start`. Os dados ficam fora da imagem. Mudanças na inferência devem atualizar a versão do pipeline para evitar reutilização incompatível. Não há migração automática de schemas de versões futuras nesta versão.

## Diagnóstico

| Sintoma | Ação |
| --- | --- |
| Docker indisponível | Abra Docker Desktop e aguarde o engine Linux. |
| `model_not_ready` | Execute `prepare`. Se o modelo estiver corrompido, pare o worker e preserve/renomeie `modelos` antes de preparar novamente. |
| `worker_unavailable` | Execute `start` e consulte `logs`. |
| `wait` com código `2` | Repita com o mesmo identificador. |
| `failed` | Consulte `status`, corrija o arquivo/ambiente e submeta novamente. |
| `output_incomplete` | Artefatos foram alterados/removidos; restaure um backup consistente. |
| Worker encerrado por memória | Consulte `docker inspect`, reduza outras cargas e registre a ocorrência antes de ajustar limites. |

## Limitações

- Ambiente inicial: Windows/PowerShell com Docker Linux amd64. Outros hosts precisam de validação do wrapper e do mapeamento de caminhos.
- Sem captura ao vivo, identificação de falantes, interface web ou resumo automático.
- Fronteiras de cinco minutos podem dividir palavras; revise esses trechos quando necessário.
- Silêncio gera texto/legenda vazios e `no_speech: true`; mídia sem stream de áudio falha.
- Nomes próprios, siglas, ruído e falas simultâneas afetam a precisão. A transcrição automática pode exigir revisão.

## Dependências

Motor: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [PyAV](https://pyav.org/docs/stable/) e [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small). Dependências e modelo mantêm suas próprias licenças. O projeto ainda não define licença de distribuição própria.
