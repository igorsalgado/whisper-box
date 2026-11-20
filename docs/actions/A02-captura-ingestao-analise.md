# A02 — Captura, ingestão automática e análise sob demanda

Data: 20/11/2026
Estado: escopo aprovado; **F3 (painel de gravação) entregue e validada pelo usuário em 20/11/2026**; F0, F1, F2 e F4 não implementadas aqui (redistribuídas: ver [índice das actions](README.md)). Revisão de 20/11/2026 registra o que mudou (seção 0).
Projeto: Whisper Box (`whisper-box`)
Depende de: [A01](A01-transcricao-offline-docker.md) (motor, fila, deduplicação e verificação, já validados)

## 0. Estado e decisões (revisão de 20/11/2026)

### Plataforma: somente desktop (decisão do Igor, 20/11/2026)

“Sem app, é totalmente desktop esse dev.” O produto é **exclusivamente desktop**: a interface é a janela própria aberta por `python whisper-box.py painel` (Edge ou Chrome em modo `--app`, perfil `.navegador/`). **PWA, app instalável, service worker, manifest e uso em celular estão descartados** (não adiados). Windows com Docker Desktop é a plataforma validada; macOS e Linux desktop são suporte não validado.

### Estado por fase

| Fase | Estado | Observações |
| --- | --- | --- |
| F0 — Contrato do motor | Não iniciada aqui; **A03 em execução** | Achados I1 a I6, `list` e Ctrl+C/timeout vão para a [A03](A03-contrato-do-motor.md); retenção, `purge` e limpeza de `saida/.partial/` para a [A04](A04-retencao-e-limpeza-de-disco.md). |
| F1 — Skill de análise | Não iniciada | [A05](A05-skill-de-analise.md). Não há skill, nem `list`. Hoje o agente lê `transcricao.txt` a pedido, seguindo a regra 3 reescrita do README. |
| F2 — Ingestão automática | Não iniciada, em geral substituída pela F3 | O painel envia a gravação direto à fila pela API; a pasta vigiada continua útil apenas para arquivos copiados à mão (backlog). |
| F3 — Painel (janela desktop) | **Concluída e validada pelo usuário em 20/11/2026** | Entregues: serviço `painel`, telas Gravar, Transcrições e Logs, janela própria e ajudante de host (ver abaixo). Pendências que não bloqueiam o uso: indicador de espaço livre ([A04](A04-retencao-e-limpeza-de-disco.md)), aviso de consentimento na primeira execução e ensaios de borda ([A07](A07-endurecimento-e-operacao.md)), `analises/` ([A05](A05-skill-de-analise.md)). PWA descartado. |
| F4 — Opcional | Não iniciada | Condicionada a métricas (checkpoint na [A06](A06-desempenho-e-robustez-do-motor.md)). |

### Validação de uso real do painel (Igor, 20/11/2026)

O Igor usou o painel e reportou: “todas as funcionalidades estão ok”. Coberto: captura de **áudio do sistema e do microfone no Edge**, gravar → transcrever → abrir pasta. Registro das medições em [VALIDACAO.md](../VALIDACAO.md).

| Critério (seção 9) | Situação |
| --- | --- |
| 24 (gate de captura) | **Validado pelo usuário em 20/11/2026** no Edge; Chrome fica no ensaio da A07, bloco 1. |
| 25 (áudio do sistema e do microfone na transcrição) | **Validado pelo usuário em 20/11/2026**; a medição formal de gravação longa (10 e 60 min) fica na A07, bloco 1. |
| 30 (lista e acesso ao resultado) | **Validado pelo usuário em 20/11/2026**, já reescrito para “abrir pasta” (ver seção 9). |
| 26, 27, 28, 29, 31, 32 | Seguem abertos (ensaios da A07, bloco 1); o 31 perdeu a parte de PWA. |

### O que foi entregue e difere do desenho original

- **Envio direto pela API em vez da pasta vigiada.** O painel acumula os pedaços em `entrada/.gravacoes/<id>.part` e, em **Transcrever**, fecha o arquivo e chama `jobs.submit` (a mesma rotina da CLI). Não existem `caixa-de-entrada/`, `.part/` separado nem varredura. O worker continua sem rede e sem endpoint. Contrato: [painel-api.md](../painel-api.md).
- **Servidor:** biblioteca padrão (`http.server`), não FastAPI, no mesmo código do motor (`python -m whisper_box painel`). O serviço `painel` tem bridge própria, publica só `127.0.0.1:8765` (ou `WHISPER_BOX_PAINEL_PORT`), roda com `cap_drop: ALL`, `read_only` e `no-new-privileges`, com `saida/` e `modelos/` somente leitura e `state`/`entrada` em escrita (precisa escrever a fila e o staging).
- **Segurança:** sem token de API; usa validação de `Host`, `X-Whisper-Box: 1` e `Origin` nas rotas mutáveis. Não há cookie nem resposta `401` (o critério 28 vale com `421`/`403`).
- **Janela própria e ajudante de host:** `python whisper-box.py painel` abre Edge/Chrome em modo app (perfil `.navegador/`, 380×640) e mantém um ajudante em `127.0.0.1:8766`, com token por execução, que abre `saida/<job_id>` no gerenciador de arquivos. Sem ajudante, o botão vira **Copiar caminho**. **Essa janela é a interface do produto:** não há PWA nem instalação.
- **Sem downloads na interface:** os arquivos já estão no disco; as rotas de download existem na API, mas a interface não as usa (o critério 30 mudou para “abrir pasta”).
- **`start` e `stop`:** `start` sobe worker e painel e devolve `painel_url`; `stop` para os dois.
- **Limite:** 2 GiB por gravação e 16 MiB por pedaço. O limite de 4 horas não é aplicado.

### Perguntas resolvidas

| # | Resolução |
| --- | --- |
| 2 (idioma) | **Automático** no painel (`auto`), sem escolha na interface. A CLI mantém `pt` como padrão. |
| 4 (SQLite ro ou índice) | O painel lê a fila pelo mesmo volume `state` (montado em escrita para permitir o `submit`); a lista vem de `Store.list`. |
| 5 (limites) | 2 GiB por gravação, 16 MiB por pedaço. |
| 6 (áudio de aplicativo no Edge) | Captura de áudio do sistema inteiro com “Tela inteira” validada no Edge pelo uso real de 20/11/2026; áudio por aplicativo não foi testado. |
| 8 (porta) | 8765 (painel) e 8766 (ajudante), configuráveis por variável de ambiente. |
| PWA (decisão D5 do [índice](README.md)) | **Resolvida: descartado.** Produto exclusivamente desktop, com janela própria (`--app`). |
| Privacidade (seção 8) | **Resolvida pelo Igor:** a análise das transcrições por agente é permitida (projeto pessoal); captura e transcrição continuam locais. A regra 3 do README já foi reescrita. |

Seguem abertas: 1 (retenção), 3 (`processadas/`, hoje sem efeito pois não há pasta vigiada) e 7 (formato da análise).

## 1. Problema e resultado esperado

Na A01, o fluxo exige que alguém forneça um arquivo e que um agente opere a CLI (o README é o prompt do agente). Isso resolve a transcrição, mas deixa três lacunas para quem tem várias reuniões por dia:

1. **Captura**: o usuário precisa gravar a reunião com outra ferramenta, localizar o arquivo e entregá-lo ao agente.
2. **Disparo**: a transcrição só começa quando um agente é acionado, embora o motor não precise de raciocínio.
3. **Análise**: ata, decisões e tarefas dependem de o agente achar a transcrição certa e de não contaminar `saida/`.

**Resultado esperado**: o usuário clica em gravar, para ao fim da reunião e, minutos depois, a transcrição existe sem nenhum agente envolvido. Mais tarde, diz ao seu agente "resuma a reunião de ontem" e recebe ata, decisões e tarefas com horários citados, salvas fora da saída verificada.

**Princípio**: três componentes ligados somente por pastas e contratos de arquivo. Nenhum fala diretamente com outro.

## 2. Usuários

| Usuário | Necessidade |
| --- | --- |
| Humano (Igor), no computador desktop | Gravar reunião (áudio do sistema + microfone), acompanhar status, abrir a pasta do resultado, pedir análise. |
| Agente do usuário (Claude Code, Codex etc.) | Localizar transcrição por data/título, ler `transcricao.txt`, gerar análise em `analises/`. Também segue operando a CLI manual para arquivos avulsos. |
| Cliente automático da CLI | Depende do contrato JSON e dos códigos de saída da A01; por isso a F0 vem primeiro. |

## 3. Fluxo ponta a ponta (desenho original)

> Nota de 20/11/2026: o painel entregue envia a gravação direto à fila pela API (seção 0); os passos 3 a 5 e o diagrama abaixo descrevem a pasta vigiada do desenho original. O passo 1 foi reescrito pela decisão “somente desktop”.

1. O usuário abre a **janela desktop própria** do painel (`python whisper-box.py painel`, Edge/Chrome em modo `--app`, servindo `http://127.0.0.1:<porta>`; **sem PWA nem instalação**, decisão D5 resolvida em 20/11/2026) e informa um título opcional.
2. Clica em **Gravar** e escolhe a aba/tela a compartilhar com áudio (`getDisplayMedia`); o navegador também pede o microfone (`getUserMedia`). O vídeo é descartado; WebAudio mixa as duas fontes.
3. `MediaRecorder` emite um pedaço a cada ~5 s; o painel os acrescenta a `caixa-de-entrada/.part/<id>.webm.part`. Queda do navegador ou do painel perde no máximo alguns segundos.
4. Ao parar, o painel finaliza o arquivo e faz **rename atômico** para `caixa-de-entrada/<nome>.webm`.
5. O worker, por varredura periódica, vê o arquivo completo, copia e enfileira (título vem do nome). Se o Docker estiver parado, o arquivo espera na pasta.
6. O painel lista o job, mostra `queued`/`running`/progresso e, em `succeeded`, oferece abrir a pasta do resultado (no desenho original: TXT e SRT para baixar).
7. Depois, o usuário diz ao agente "resuma a reunião de ontem". O agente roda `list`, escolhe o `job_id`, lê `transcricao.txt` e grava `analises/<job_id>/`.

```text
Janela desktop própria (Edge/Chrome em modo --app)
   │ getDisplayMedia + getUserMedia → WebAudio → MediaRecorder (5 s)
   ▼
serviço painel (só 127.0.0.1)
   │  rw: caixa-de-entrada/        ro: saida/, estado
   ▼
caixa-de-entrada/<nome>.webm  ──(varredura)──►  worker (network none, 2 CPU / 4 GiB)
                                                  │  entrada/<job_id>/ → fila SQLite → saida/<job_id>/
                                                  ▼
                                    whisper-box.py list ──► agente/skill ──► analises/<job_id>/
```

## 4. Escopo por fase

Cada fase entrega valor sozinha e só começa quando a anterior estiver aceita (exceto o protótipo da F3, que rodou em paralelo).

### F0 — Contrato do motor (pré-requisito)

Há clientes automáticos dependendo da CLI; os defeitos abaixo vêm da revisão e devem ser corrigidos antes de ampliar o sistema.

| Item | Correção |
| --- | --- |
| I1 | `prepare` com falha imprime dois JSON em stdout; deve imprimir exatamente um. |
| I2 | Erro transitório do Docker na espera derruba `transcribe` sem `job_id` no stdout; anexar `job_id` a todo erro pós-submit e fazer retry curto antes de falhar. |
| I3 | `--input ""` gera traceback com stdout vazio; deve devolver JSON com código de saída 3. |
| I4 | Caminho POSIX com `:` quebra o mount `-v`; usar a sintaxe longa (`--mount type=bind,...`). |
| I5 | `status` expõe `error: interrupted` em job re-enfileirado; erro só aparece em `failed`. |
| I6 | Job `succeeded` com saída apagada fica preso em `output_incomplete` e a deduplicação impede reprocessar; definir caminho de reprocessamento (nova tentativa explícita que ignora o reaproveitamento quando a saída é inválida). |
| Novo | Comando `list` (índice, contrato na seção 6.3). |
| Novo | Retenção: apagar a cópia em `entrada/<job_id>/` após sucesso verificado, e comando `purge` para remover job (entrada, saída, registro) por escolha explícita. |
| Novo | Limpeza de `saida/.partial/` órfão na inicialização do worker. |
| Novo | Ctrl+C e timeout nos subprocessos do wrapper, sem deixar containers ou processos órfãos. |

Fora de escopo: qualquer mudança de inferência; novos formatos de saída.

### F1 — Skill de análise

- `.claude/skills/whisper-box-analise/SKILL.md` e receita equivalente em `AGENTS.md` para outros agentes.
- Fluxo da skill: `list` → seleção por data/título → ler `transcricao.txt` → gerar ata, decisões e tarefas (responsável/prazo, "não informado" quando ausente), cada item com horário citado → gravar em `analises/<job_id>/`.
- Funciona com as transcrições já existentes, sem depender de F2/F3.
- Reescrita da regra 3 do README (seção 8).

Fora de escopo: análise sem agente; identificação de falantes; envio automático da análise a terceiros.

### F2 — Ingestão automática

- Pasta vigiada `caixa-de-entrada/`; worker com `restart: unless-stopped`.
- Varredura periódica (padrão 5 s; inotify não atravessa bind mounts no Windows/macOS).
- Título derivado do nome do arquivo (contrato na seção 6.2).
- Reescrita de README/AGENTS.md/CLAUDE.md junto desta fase (seção 8).

Fora de escopo: subpastas recursivas; monitorar pastas arbitrárias do host; idioma por arquivo (usa `pt`; configurável por variável de ambiente do worker).

### F3 — Painel desktop (entregue e validada; ver seção 0)

- Novo serviço `painel` no Compose, publicado somente em `127.0.0.1`, apresentado numa **janela desktop própria** (Edge/Chrome em modo `--app`, aberta por `python whisper-box.py painel`).
- Captura (seção 3), lista de transcrições, status/progresso e acesso ao resultado (abrir pasta; no desenho original, download de TXT/SRT). **Sem PWA, sem instalação e sem versão para celular** (decisão do Igor, 20/11/2026).
- **Gate de entrada**: o protótipo de captura (hoje incorporado ao painel em `painel/`; o arquivo `prototipos/captura-audio.html` foi removido) deve confirmar (a) captura de áudio do sistema no Chrome e no Edge em Windows e (b) que o worker decodifica o `.webm`/opus gerado. *Resolvido para o Edge pelo uso real de 20/11/2026 (critério 24); Chrome fica na A07, bloco 1.*
- Dependências próprias dentro do container (ex.: FastAPI); `whisper-box.py` segue só stdlib. *Entregue com biblioteca padrão, sem FastAPI.*

Fora de escopo: edição de transcrição, upload de arquivos externos, múltiplos usuários, acesso remoto, autenticação além da validação local de `Host`/`Origin`, PWA/instalação, interface para celular.

### F4 — Opcional

| Item | Condição para fazer |
| --- | --- |
| Checkpoint por bloco para gravações longas (retomar do último bloco concluído) | Só se reinício de gravação longa se mostrar frequente ou caro nas métricas. Exige rever `pipeline_version` e dedup. |
| App nativo de bandeja (PySide6 + WASAPI/Process Tap) | Só se o seletor de compartilhamento a cada gravação incomodar. Continua sendo desktop. |
| macOS e Linux desktop | Suporte não validado; só após ensaio completo registrado (áudio do sistema no navegador é limitado no macOS). |

## 5. Segurança e privacidade do painel (F3)

| Controle | Regra |
| --- | --- |
| Exposição | Publicar apenas em `127.0.0.1` (`127.0.0.1:<porta>:<porta>`); nunca `0.0.0.0`. |
| DNS rebinding | Validar `Host` contra lista fixa (`127.0.0.1`, `localhost` com a porta) e `Origin` em toda requisição mutável; rejeitar o restante com 403. |
| Token | Desenho original: token aleatório gerado na inicialização, em cookie `HttpOnly`/`SameSite=Strict`. **Entregue de outra forma** (seção 0): sem cookie, com `X-Whisper-Box: 1` e `Origin` nas rotas mutáveis. |
| Limites | Tamanho máximo por gravação e por pedaço; contagem de gravações simultâneas; nome de arquivo gerado pelo servidor, nunca vindo do cliente. |
| Montagens | `caixa-de-entrada/` rw; `saida/` e estado ro. O painel não escreve em `saida/`. |
| Isolamento | Worker continua sem rede e não fala com o painel; o painel só lê o índice e os arquivos montados. |
| Consentimento | Gravar reunião exige ciência dos participantes; a decisão e a responsabilidade são do usuário. O painel mostra indicador de gravação visível e aviso na primeira execução (A07, bloco 5). |

## 6. Contratos entre componentes

### 6.1 Pastas

| Pasta | Escritor | Leitor | Conteúdo |
| --- | --- | --- | --- |
| `caixa-de-entrada/` | painel (ou o usuário, copiando arquivo) | worker | Gravações finalizadas. |
| `caixa-de-entrada/.part/` | painel | painel | Gravação em andamento (`*.part`). **Nunca lida pelo worker.** |
| `entrada/<job_id>/` | worker / CLI | worker | Cópia de trabalho; removida após sucesso verificado (F0). |
| `saida/<job_id>/` | worker | painel (ro), agente (leitura) | Artefatos verificados + `manifest.json`. **Imutável por terceiros.** |
| `analises/<job_id>/` | agente/skill | humano | `ata.md`, `decisoes.md`, `tarefas.md` ou arquivo único. |

### 6.2 Rename atômico e nome de arquivo

- O painel grava em `caixa-de-entrada/.part/<id>.webm.part`, faz `fsync` ao parar e executa `os.replace` para `caixa-de-entrada/<nome>.webm` no mesmo volume. Só então o arquivo existe para o worker.
- O worker ignora tudo que começa com `.` ou termina em `.part`, e exige que o tamanho e o `mtime` do arquivo estejam estáveis em duas varreduras consecutivas (proteção para cópia manual).
- Nome: `AAAA-MM-DD_HHMM_<titulo-slug>.<ext>`. Título = parte após o segundo `_`, com `-` e `_` trocados por espaço; sem esse padrão, o título é o nome sem extensão. Início = data/hora do nome, senão `mtime`.
- Após enfileirar (cópia e hash concluídos), o worker move o arquivo da caixa para `caixa-de-entrada/processadas/` para não reprocessar; a deduplicação por hash continua como proteção. O worker precisa de montagem rw da caixa. Ver pergunta em aberto 3.
- Título e início passam a ser persistidos no registro do job (migração de schema compatível com bancos existentes; jobs antigos recebem título do nome original e início de `created_at`).

### 6.3 Schema do `list`

`python whisper-box.py list [--status S] [--since AAAA-MM-DD] [--limit N]` imprime um único JSON em stdout, ordenado do mais recente para o mais antigo, e preserva os códigos de saída da A01.

```json
{
  "jobs": [
    {
      "job_id": "identificador",
      "title": "daily sprint",
      "started_at": "2026-11-20T14:30:00-03:00",
      "duration_seconds": 1380.4,
      "status": "succeeded",
      "language": "pt",
      "analysis_path": "C:\\...\\analises\\identificador",
      "files": {
        "text": "C:\\...\\saida\\identificador\\transcricao.txt",
        "srt": "C:\\...\\saida\\identificador\\transcricao.srt",
        "segments": "C:\\...\\saida\\identificador\\segmentos.jsonl",
        "metadata": "C:\\...\\saida\\identificador\\metadados.json"
      }
    }
  ]
}
```

- `files` só aparece em `succeeded` com saída verificada; `analysis_path` só se a pasta existir.
- `duration_seconds` é `null` até o fim; nunca inclui conteúdo da reunião.
- Cada entrada dos jobs em andamento inclui `progress_seconds`.

### 6.4 Compose (alvo)

| Serviço | Rede | Montagens | Observações |
| --- | --- | --- | --- |
| `worker` | `none` | estado, `entrada` rw, `saida` rw, `modelos` ro, `caixa-de-entrada` rw | 2 CPUs / 4 GiB; `restart: unless-stopped`; sem alterações de inferência. |
| `painel` | bridge, porta só em `127.0.0.1` | `caixa-de-entrada` rw, `saida` ro, estado ro | Limites próprios modestos (ex.: 0,5 CPU / 512 MiB); não carrega o modelo. |
| `cli`, `prepare`, `test` | como na A01 | como na A01 | `test` ganha casos da varredura e do `list`. |

O painel lê o estado via leitura do índice (SQLite ro ou arquivo de índice gerado pelo worker); a escolha é detalhe da F3, desde que o worker permaneça sem rede e sem endpoint.

## 7. Restrições preservadas

- Worker com `network_mode: none`, worker exclusivo (lock) e limites de 2 CPUs / 4 GiB.
- `whisper-box.py` somente com biblioteca padrão; sem `.ps1`/`.sh`.
- Dependências extras só dentro do container do `painel`.
- Produto exclusivamente desktop: sem PWA, service worker, manifest nem interface para celular.
- Qualquer mudança de inferência (modelo, parâmetros, decodificação do áudio) exige novo `pipeline_version` e revisão da deduplicação.
- Contrato JSON e códigos de saída da A01 mantidos; novos comandos seguem o mesmo padrão (um JSON em stdout, diagnóstico em stderr).
- Nunca versionar gravações, transcrições, análises, modelos, logs, estado ou credenciais; `caixa-de-entrada/` e `analises/` entram no `.gitignore` e no `.dockerignore`.
- Resultados em `saida/` nunca são alterados (invalida o manifesto de hashes).

## 8. Documentação e privacidade

| Documento | Mudança (junto de F1/F2, não antes) |
| --- | --- |
| `README.md` | Feito em 20/11/2026: parte humana (instalar, painel, onde ficam os arquivos) e seção “Para agentes” com o prompt operacional da CLI. Falta o pedido de análise (F1). |
| `AGENTS.md` | Feito em parte: regras de desenvolvimento por componente (motor, wrapper, painel, frontend, ajudante). Falta a receita de análise (F1). |
| `CLAUDE.md` | Importa README e `AGENTS.md` e menciona o painel. Falta apontar a skill (F1). |

**Regra 3 reescrita (feita no README em 20/11/2026)**: captura e transcrição permanecem 100% locais, sem API de transcrição em nuvem. A análise pode usar o agente do usuário (inclusive em nuvem), e só com o conteúdo pedido; o agente não envia a gravação em si. Esta é uma decisão de projeto pessoal, registrada no README.

## 9. Critérios de aceite

### F0
1. [ ] `prepare` com falha produz exatamente um JSON em stdout e código 1.
2. [ ] Falha de Docker durante a espera de `transcribe` (simulada) mantém o `job_id` no JSON de erro e tenta ao menos um retry curto antes de falhar.
3. [ ] `--input ""` devolve JSON de erro com código 3, sem traceback.
4. [ ] Um caminho POSIX com `:` é montado e transcrito (teste em `tests/test_wrapper.py`).
5. [ ] `status` de job re-enfileirado não contém `error`.
6. [ ] Apagar `saida/<job_id>/` de um job `succeeded` e reenviar a mesma mídia gera nova tentativa processada, com histórico preservado.
7. [ ] `list` segue o schema da seção 6.3 e passa nos testes com jobs `queued`, `running`, `succeeded` e `failed`.
8. [ ] Após sucesso, `entrada/<job_id>/` não existe; `purge --job` remove entrada, saída e registro apenas daquele job, com confirmação explícita.
9. [ ] Início do worker remove itens órfãos de `saida/.partial/`; resultados completos não são tocados.
10. [ ] Ctrl+C no `transcribe` encerra o wrapper sem containers órfãos e imprime o `job_id` se já houver; subprocesso travado termina por timeout com código 1 e JSON.
11. [ ] Suíte `test` do Docker passa; contrato e códigos da A01 inalterados.

### F1
12. [ ] Com três transcrições existentes, "resuma a reunião de ontem" seleciona o `job_id` correto via `list`, sem ler as demais.
13. [ ] A análise grava em `analises/<job_id>/` e `manifest.json` de `saida/<job_id>/` continua válido (`result` ainda devolve sucesso).
14. [ ] Cada decisão e tarefa cita ao menos um horário `[hh:mm:ss]` existente na transcrição; responsável/prazo ausentes aparecem como "não informado".
15. [ ] Pedido ambíguo (duas reuniões no mesmo dia) leva a uma pergunta ao usuário, sem adivinhar.
16. [ ] `AGENTS.md` traz a receita equivalente e um agente que não é o Claude consegue segui-la.

### F2
17. [ ] Um arquivo colocado em `caixa-de-entrada/` vira job `queued` em até 2 varreduras, sem comando do usuário; título e início seguem a seção 6.2.
18. [ ] Arquivo `.part` ou em `.part/` nunca é enfileirado; arquivo em cópia lenta só é enfileirado após o tamanho estabilizar.
19. [ ] Com o Docker parado, a gravação permanece na pasta e é processada ao iniciar o worker.
20. [ ] O mesmo arquivo copiado duas vezes resulta em `reused: true`, sem segundo processamento.
21. [ ] Arquivo inválido ou sem áudio gera job `failed` com motivo e não bloqueia a fila; reiniciar o worker não repete o loop.
22. [ ] Após reiniciar o Docker Desktop, o worker volta sozinho (`unless-stopped`) e continua a fila.
23. [ ] O worker segue com `network_mode: none` e limites inalterados (`docker inspect`).

### F3
24. [x] **Gate** (validado pelo usuário em 20/11/2026): captura de áudio do sistema no Edge (Windows) e o worker transcreve o `.webm`/opus gerado; resultado registrado em `docs/VALIDACAO.md`. *Chrome: ensaio na A07, bloco 1, tarefa 6.*
25. [x] Gravação com áudio do sistema e do microfone audíveis na transcrição (validado pelo usuário em 20/11/2026, uso real no Edge). *A medição formal de 10 e 60 min e a conferência de que nenhum vídeo é gravado em disco ficam na A07, bloco 1.*
26. [ ] Matar o navegador no meio da gravação preserva todo o conteúdo anterior aos últimos ~10 s (a gravação parcial fica em `.part/` e o painel oferece finalizá-la). *Hoje a interface não oferece finalizar; ver A07, bloco 1.*
27. [ ] Parar a gravação publica o arquivo por rename atômico; o worker nunca vê arquivo incompleto.
28. [ ] O painel só responde em `127.0.0.1`: acesso pelo IP da rede local falha; requisição com `Host` ou `Origin` inesperado retorna 403 (ou 421, ver seção 0). *Sem cookie nem 401 no desenho entregue.*
29. [ ] Gravação acima do limite configurado é interrompida com aviso claro e o conteúdo gravado até então é preservado.
30. [x] A lista mostra status e progresso corretos dos jobs e permite **abrir a pasta** (ou copiar o caminho) apenas de jobs `succeeded` verificados (validado pelo usuário em 20/11/2026; reescrito de “baixar TXT e SRT”).
31. [ ] O painel monta `saida/` e estado como somente leitura (`docker inspect`). *A parte “instalável como PWA no Chrome e no Edge” foi removida: PWA descartado em 20/11/2026 (produto somente desktop, janela própria).*
32. [ ] Gravar durante a transcrição de outro job não afeta o worker além do limite de 2 CPUs / 4 GiB.

## 10. Riscos

| Risco | Impacto | Tratamento |
| --- | --- | --- |
| Áudio do sistema no macOS é limitado no navegador | F3 não cobre macOS | Plataforma validada: Windows. macOS e Linux desktop: suporte não validado, só com ensaio completo (F4). |
| Seletor de compartilhamento a cada gravação | Atrito; esquecer de marcar "compartilhar áudio" gera gravação só com microfone | Aviso na UI antes de gravar e detecção de trilha de áudio do sistema ausente; app nativo de bandeja (desktop) na F4 se incomodar. Uso real de 20/11/2026 não relatou atrito. |
| A janela do painel precisa ficar aberta | Fechar a janela encerra a gravação | Aviso ao fechar; preservar o `.part`; finalização manual. |
| Firefox e Safari não suportam captura de áudio do sistema | Fora de suporte | Documentar Chrome/Edge (janela própria em modo `--app`). |
| Crescimento de disco (gravações, cópias, saídas) | Disco cheio, falha silenciosa | Retenção da F0 (A04); indicador de espaço livre no painel; `purge`. |
| Consentimento dos participantes | Risco legal e ético | Aviso, indicador visível e responsabilidade do usuário. |
| Gravação longa reinicia do zero se o worker cair | Retrabalho (limitação já aceita na A01) | Medir; checkpoint por bloco na F4/A06 se necessário. |
| `.webm`/opus incompatível com o decodificador | Transcrição falha | Gate do protótipo; validado no Edge em 20/11/2026. |
| Varredura em bind mount lenta ou arquivo grande em escrita manual | Leitura de arquivo incompleto | Estabilidade em duas varreduras e regra de `.part` (só se a pasta vigiada for retomada). |
| Análise por agente em nuvem expõe conteúdo | Privacidade | Decisão registrada na seção 8; só o texto pedido é lido. |
| Painel exposto por engano | Superfície de ataque local | Bind em 127.0.0.1, validação de Host/Origin, teste de aceite 28. |

## 11. Métricas de sucesso

| Métrica | Meta inicial | Leitura |
| --- | --- | --- |
| Passos manuais da gravação até a transcrição pronta | 0 após clicar em parar | Ensaio ponta a ponta. |
| Gravações perdidas por queda | 0 gravações; perda máxima ≈ 10 s | Teste 26 e uso real por 2 semanas. |
| Reuniões transcritas automaticamente sobre gravadas | ≥ 95% | Comparar arquivos na caixa com jobs `succeeded`. |
| Tempo entre o fim da gravação e o início da transcrição | ≤ 15 s com worker ativo | `created_at` do job versus rename. |
| Análises corretas na primeira tentativa (reunião certa) | ≥ 90% em 10 pedidos | Revisão manual. |
| Itens de ata sem horário citado | 0 | Amostra de 5 análises. |
| Falhas I1 a I6 reproduzíveis | 0 | Testes da F0 (A03). |

Leitura: revisar após duas semanas de uso real; decidir sobre F4 com base nas métricas de perda e de atrito do seletor.

## 12. Perguntas em aberto

O estado atual das perguntas está na seção 0 (resolvidas: 2, 4, 5, 6, 8, PWA e privacidade). A tabela abaixo é o registro original.

| # | Pergunta | Dono | Necessária antes de |
| --- | --- | --- | --- |
| 1 | Qual a retenção padrão: manter a gravação original após sucesso (hoje o áudio é a cópia do trabalho) ou apagar e manter só a transcrição? | Igor | F0 (`purge`/retenção) |
| 2 | Idioma por gravação no painel (campo) ou fixo `pt` na F2/F3? | Igor | F2/F3 |
| 3 | Mover o arquivo para `processadas/` após enfileirar, ou apenas apagá-lo? Isso muda a regra "não apagar original", que passa a valer só para a CLI manual. | Igor | F2 |
| 4 | O painel lê o estado por SQLite ro ou por índice gerado pelo worker? | Dev backend | F3 |
| 5 | Limites padrão de tamanho/duração por gravação do painel. | Igor + dev | F3 |
| 6 | O protótipo cobre o Edge com áudio de aplicativo (Teams/Meet) além de aba do navegador? | Protótipo | F3 (gate) |
| 7 | Formato de saída da análise: um arquivo ou três? | Igor | F1 |
| 8 | Qual porta fixa do painel? | Dev | F3 |

## 13. Dependências e sequência

`F0` → `F1` e `F2` (podem correr em paralelo após F0) → `F3` (depende de F2 e do gate do protótipo; **entregue**) → `F4` (opcional, por métrica). Handoffs: dev-backend (F0, F2, `list`), dev-frontend + dev-backend (F3), qa-engineer (matriz dos critérios da seção 9), infra (Compose, portas, limites).
