# Guia do agente — Whisper Box

## Operar (transcrever gravações)

A seção “Para agentes” do [README.md](README.md) é o prompt operacional completo: missão, regras, passos (`doctor` → corrigir ambiente → pedir a gravação → `transcribe`), erros e referência de comandos. Siga-a quando o usuário pedir uma transcrição. A parte “Para quem usa” do mesmo arquivo é o guia humano (instalação, painel).

## Analisar transcrições

Receita para qualquer agente (o Claude Code tem a skill `.claude/skills/whisper-box-analise/SKILL.md`, equivalente). Só sob pedido do usuário. A análise é do **texto**: o áudio nunca é enviado, nenhum serviço externo é usado, só a transcrição pedida é lida e ela não é colada inteira na conversa. Nunca escreva em `saida/`.

1. **Localizar:** converta o pedido em intervalo de datas no fuso local e rode `python whisper-box.py list --status succeeded --since AAAA-MM-DD --until AAAA-MM-DD` (stdout é JSON). Escolha por `created_at`/`started_at` e `duration_seconds`. Trabalhos enviados pela CLI têm `source_name` `recording.<ext>`, que não identifica a reunião.
2. **Desambiguar:** com mais de um candidato plausível, pergunte ao usuário (data/hora, `source_name`, duração). Nunca adivinhe; sem candidatos, diga e sugira ampliar o intervalo.
3. **Ler** só `files.text` do job escolhido (transcrições longas: por faixas de linhas ou `segmentos.jsonl`).
4. **Gerar** `analise.md`: cabeçalho (título, `job_id`, `source_name`, início, duração, data da análise, aviso de transcrição automática); **Resumo** (3 a 6 linhas); **Decisões** (cada item termina com `[hh:mm:ss]`); **Tarefas** (tabela `Tarefa | Responsável | Prazo | Horário`; o que não foi dito é “não informado”, nada inventado); **Pontos em aberto** (com horário). Horário citado é o **início** de um segmento existente em `transcricao.txt`.
5. **Gravar** em `analises/<job_id>/analise.md` (pasta ignorada pelo Git). Se já existir, pergunte se sobrescreve ou grava `analise-AAAAMMDD-HHMM.md`.
6. **Verificar:** `python tests/check_analise.py --analise analises/JOB_ID/analise.md --transcricao saida/JOB_ID/transcricao.txt` (código 0) e `python whisper-box.py result --job JOB_ID` (código 0, `saida/` intacta).
7. **Responder** com o caminho, um resumo curto e o aviso de que a transcrição é automática.

## Desenvolver (alterar o projeto)

### Princípios gerais

- Todo runtime e toda a suíte rodam em Docker. O host exige apenas Python 3.8+ para o wrapper.
- Não crie scripts específicos de shell (`.ps1`, `.sh`); a interface de host é somente Python.
- Uma alteração de inferência (modelo, parâmetros, decodificação) exige novo `pipeline_version` e revisão da deduplicação.
- Mantenha o contrato JSON (um objeto em stdout, diagnóstico em stderr) e os códigos de saída (0 a 4). Ao mudar comandos, atualize o README (seção “Para agentes”) no mesmo trabalho.
- Mudou o comportamento do painel? Atualize [docs/painel-api.md](docs/painel-api.md) junto.

### Por componente

| Componente | Onde | Regras |
| --- | --- | --- |
| Motor, fila e CLI do container | `src/whisper_box/` (`pipeline.py`, `worker.py`, `jobs.py`, `store.py`, `model.py`, `__main__.py`) | Dependências somente em `requirements.lock` (instaladas na imagem; `pip check` no build). Worker exclusivo (lock), 2 CPUs e 4 GiB, `network_mode: none` no worker e na CLI. Erros como `BoxError` com código e exit code. Nunca registrar áudio ou texto da reunião em logs. |
| Wrapper de host | `whisper-box.py` | Somente biblioteca padrão e Python 3.8+ (sem sintaxe nem módulos mais novos). Nunca usar shell: argumentos em lista. stdout recebe um único JSON nos comandos de contrato. |
| Painel (servidor) | `src/whisper_box/painel.py`, serviço `painel` no `compose.yaml` | Também só biblioteca padrão (`http.server`). Único serviço com rede: bridge própria e porta publicada **somente em `127.0.0.1`**. Mantém `cap_drop: [ALL]`, `read_only`, `no-new-privileges`, `saida/` e `modelos/` somente leitura, validação de `Host` e `Origin` e cabeçalho `X-Whisper-Box`. Nunca expõe caminhos do host além de `pasta` na lista. Envia ao worker pela fila (`jobs.submit`), sem falar com ele por rede. |
| Frontend do painel | `painel/` (HTML, CSS e JS puros) | Vanilla, sem build, sem dependências e sem CDN: é montado em `/srv/painel` somente leitura. Alterar arquivos aqui não exige reconstruir a imagem. Segue o contrato da API; qualquer mudança de rota é feita primeiro em `painel.py` e no documento da API. |
| Ajudante de host | `helper_handler`/`start_helper` em `whisper-box.py` | Escuta só em `127.0.0.1`, uma rota (`POST /abrir-pasta`), token aleatório por execução comparado em tempo constante, `Host` e `Origin` restritos, `job_id` validado (32 hex) e pasta existente em `saida/`. Nunca abrir caminho vindo do cliente. |

### Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test   # suíte completa, sem rede (inclui tests/test_wrapper.py e tests/test_painel.py)
python tests/smoke.py --input CAMINHO                       # ensaio real, com modelo preparado
```

- Para o painel, valide também de ponta a ponta: `python whisper-box.py painel`, gravar, transcrever e abrir a pasta; confirme `NetworkMode: none` no worker e a porta apenas em `127.0.0.1`.
- `prepare` constrói a imagem com `--build-arg SOURCE_DIGEST` (digest de `Dockerfile`, `requirements.lock`, `src/**/*.py` e `whisper-box.py`, gravado no rótulo `whisper-box.source-digest`); o `doctor` compara com o código local e indica `rebuild` se divergir. Imagem sem rótulo (`docker compose build worker` direto) não é comparável e é aceita.
- Todo erro de comando de job posterior ao envio inclui `job_id`; stdout recebe sempre um único JSON e exceções inesperadas viram `operational_error` (código 1) sem traceback. `error` só existe em trabalhos `failed`.
- Para atualizar código ou dependências: `python whisper-box.py stop`, reconstrua a imagem (`docker compose build worker`) e execute `start`. Os dados ficam fora da imagem. Não há migração automática de schemas de versões futuras. Arquivos em `painel/` não exigem rebuild.
- Registre medições e ensaios em [docs/VALIDACAO.md](docs/VALIDACAO.md). Contratos: [A01](docs/actions/A01-transcricao-offline-docker.md) (motor e CLI) e [A02](docs/actions/A02-captura-ingestao-analise.md) (captura, painel, análise).

### Privacidade

Captura e transcrição permanecem locais. Analisar o texto de uma transcrição com um agente é permitido (decisão do projeto pessoal), mas nunca envie a gravação nem use APIs de transcrição em nuvem.

## Dados e Git

- Nunca versionar gravações, transcrições reais, modelos, logs, estado, perfil do navegador (`.navegador/`) ou credenciais.
- Inspecionar os arquivos selecionados antes de cada commit; usar pathspecs explícitos.
- Não apagar o original nem remover volumes de estado para corrigir uma falha.
- Commits em português, com Conventional Commits e uma mudança coerente por commit.
