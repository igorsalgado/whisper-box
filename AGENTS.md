# Guia do agente — Whisper Box

## Operar (transcrever gravações)

O [README.md](README.md) é o prompt operacional completo: missão, regras, passos (`doctor` → corrigir ambiente → pedir a gravação → `transcribe`), erros e referência. Siga-o quando o usuário pedir uma transcrição.

## Desenvolver (alterar o projeto)

- Todo runtime de transcrição e a suíte rodam em Docker. O host exige apenas Python 3.8+ para o wrapper.
- `whisper-box.py` usa somente a biblioteca padrão; não adicione dependências instaladas no host.
- Não crie scripts específicos de shell (`.ps1`, `.sh`); a interface de host é somente Python.
- Preserve `network_mode: none` no worker e na CLI, o worker exclusivo e os limites de recursos (2 CPUs, 4 GiB).
- Uma alteração de inferência exige rever a versão do pipeline e a deduplicação.
- Mantenha o contrato JSON e os códigos de saída; ao mudar comandos, atualize o README (prompt do agente) no mesmo trabalho.
- Valide com:

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test   # inclui tests/test_wrapper.py
python tests/smoke.py --input CAMINHO                       # ensaio real, com modelo preparado
```

- Para atualizar código/dependências: pare o worker, reconstrua a imagem e execute `start`. Os dados ficam fora da imagem. Não há migração automática de schemas de versões futuras.
- Registre medições em [docs/VALIDACAO.md](docs/VALIDACAO.md); o contrato original está na [action A01](docs/actions/A01-transcricao-offline-docker.md).

## Dados e Git

- Nunca versionar gravações, transcrições reais, modelos, logs, estado ou credenciais.
- Inspecionar os arquivos selecionados antes de cada commit; usar pathspecs explícitos.
- Não apagar o original nem remover volumes de estado para corrigir uma falha.
- Commits em português, com Conventional Commits e uma mudança coerente por commit.
