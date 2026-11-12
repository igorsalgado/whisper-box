# Guia do agente — Whisper Box

## Uso operacional

- A transcrição pertence ao programa. Use `whisper-box.ps1`; não gere um script por reunião.
- Após a preparação inicial, execute `start`, `submit --input CAMINHO`, `wait --job ID --timeout 30` e `result --job ID`.
- Coloque a renovação de `wait` em um loop de código do sistema associado. Código de saída `2` significa que a espera expirou e o trabalho continua.
- Capture stdout como JSON e stderr como diagnóstico. Não misture os canais.
- Retorne os caminhos de `files` ao solicitante. Leia ou resuma a transcrição somente quando isso fizer parte da tarefa.
- Não execute `prepare` por reunião. Ausência de modelo exige preparação online explícita.
- Encerrar a espera não cancela a fila. Consulte o mesmo identificador após reconectar.

## Desenvolvimento

- Todo runtime e teste Python roda em Docker; não exigir instalação no Windows.
- Preserve `network_mode: none` no worker e na CLI, o worker exclusivo e os limites de recursos.
- Uma alteração de inferência exige rever a versão do pipeline e a deduplicação.
- Valide a suíte e o contrato PowerShell quando alterar os comandos.
- Leia [README.md](README.md), a [action A01](docs/actions/A01-transcricao-offline-docker.md) e o [relatório de validação](docs/VALIDACAO.md).

## Dados e Git

- Nunca versionar gravações, transcrições reais, modelos, logs, estado ou credenciais.
- Inspecionar os arquivos selecionados antes de cada commit; usar pathspecs explícitos.
- Não apagar o original nem remover volumes de estado para corrigir uma falha.
- Commits em português, com Conventional Commits e uma mudança coerente por commit.
