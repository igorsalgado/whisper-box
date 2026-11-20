# A07 — Endurecimento e operação (opcional)

Data: 20/11/2026
Estado: opcional; menor prioridade. Os blocos são independentes e podem ser entregues em commits e sessões separados
Prioridade: 5 (exceto o bloco 1, ensaios pendentes, que pode ser feito a qualquer momento)
Tamanho: M (somando os blocos); cada bloco é S/M
Projeto: Whisper Box (`whisper-box`)
Origem: pendências da F3 da [A02](A02-captura-ingestao-analise.md) (critérios 26, 28, 29, 31, 32 e consentimento), revisão de infraestrutura e achados menores.
Plataforma: produto **exclusivamente desktop** (decisão do Igor, 20/11/2026): janela própria via `python whisper-box.py painel`. PWA, service worker e manifest foram **descartados** (decisão D5 resolvida no [índice](README.md)) e o bloco que os tratava foi removido desta action. Windows é a plataforma validada; macOS e Linux desktop são suporte não validado.
Depende de: nenhuma action como pré-requisito; os blocos 5 e 6 mexem em arquivos das [A03](A03-contrato-do-motor.md) e [A06](A06-desempenho-e-robustez-do-motor.md) e devem esperar o merge delas (o bloco 5 só toca `painel/`, então depende apenas do estado do frontend após a [A04](A04-retencao-e-limpeza-de-disco.md)).

## 1. Contexto

O painel foi validado pelo usuário em 20/11/2026 (captura real de áudio do sistema e microfone no Edge e fluxo gravar, transcrever, abrir pasta; [VALIDACAO.md](../VALIDACAO.md)), mas ficaram sem ensaio: gravação longa, queda do navegador, limite de 2 GiB, Chrome, Linux/macOS e as demais verificações de segurança do painel. O serviço `painel` já tem `cap_drop: [ALL]`, `read_only` e `no-new-privileges` (`compose.yaml:52-55`), mas o `worker` não (`compose.yaml:72-86`) e a imagem roda como root (`Dockerfile` sem `USER`). A suíte vai dentro da imagem de produção (`Dockerfile:9`, `COPY tests ./tests`) e não existe CI (`.github/` ausente). As fronteiras de bloco de 300 s cortam palavras (`pipeline.py:14-47`, corte seco em `size`; cada bloco é transcrito isoladamente, `pipeline.py:72-79`).

## 2. Objetivo

Fechar as lacunas de validação e de endurecimento que não bloqueiam o uso diário, deixando o projeto mais seguro, com CI e com qualidade de transcrição melhor nas fronteiras de bloco. Cada bloco é entregue só se o Igor julgar que vale o custo.

## 3. Escopo e fora de escopo

Escopo: blocos 1 a 7 da seção 4.

Fora de escopo: pasta vigiada, app nativo de bandeja, validação oficial de macOS e Linux desktop (backlog, ver [README das actions](README.md)); **PWA, app instalável, service worker, manifest e interface para celular (descartados)**; redistribuição de privilégios do painel; qualquer mudança de modelo ou de parâmetros de decodificação além do corte em silêncio do bloco 7.

## 4. Tarefas (por bloco)

### Bloco 1 — Ensaios pendentes da F3 (prioridade alta dentro desta action; manual, sem código)

Executar com o Igor, registrar em `docs/VALIDACAO.md` (somente métricas, nunca conteúdo):

1. **Gravação longa (10 min e 60 min)** pelo painel: áudio do sistema e microfone presentes na transcrição; nenhum vídeo em disco (critério 25 da A02, parte formal e longa; o critério já foi validado pelo uso real de 20/11/2026); contar pedaços enviados (cerca de 720 por hora) e medir o tempo do `Transcrever` até `queued`.
2. **Queda do navegador no meio da gravação** (critério 26): matar o processo do Edge aos ~3 min; conferir em `entrada/.gravacoes/` o `.part` com tudo, exceto, no máximo, os últimos ~10 s. Registrar que **não há caminho de interface para finalizar** gravações abandonadas (A04 só as limpa; recuperação é backlog).
3. **Limite de 2 GiB** (critério 29): forçar o limite por teste do servidor (`RECORDING_LIMIT` em `painel.py`) ou por gravação sintética e confirmar o aviso claro e a preservação do que foi enviado (`413 gravacao_grande_demais`).
4. **Gravar durante a transcrição de outro job** (critério 32): `docker stats` mostra o worker dentro de 2 CPUs e 4 GiB e a gravação sem falhas.
5. **Segurança do painel (critérios 28 e 31):** acesso por IP da rede local falha (`docker port` mostra `127.0.0.1:8765`); `Host` ou `Origin` inesperados devolvem `421`/`403` (a API não usa cookie nem `401`, A02 §0); `docker inspect` mostra `saida` e `modelos` `ro` no painel e `NetworkMode` do worker `none`.
6. **Chrome:** repetir o fluxo gravar, transcrever, abrir pasta no Chrome (o Edge já foi validado; completa o critério 24 da A02).
7. **Linux e macOS desktop como host** (suporte não validado; só se houver máquina): `doctor`, `prepare`, `transcribe`, o painel em janela própria e o ajudante (`xdg-open`/`open`, hoje cobertos só por testes). Registrar o resultado como ensaio de suporte, sem declarar a plataforma validada sem um ensaio completo.

### Bloco 2 — Endurecimento do container do worker

1. `compose.yaml:72-86`: acrescentar ao `worker` `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `read_only: true` e `tmpfs: [/tmp]` (o painel já usa o mesmo conjunto, `compose.yaml:52-55`; `PYTHONDONTWRITEBYTECODE=1` já evita escrita de bytecode, `Dockerfile:3`). Os únicos caminhos graváveis são os volumes (`state`, `entrada`, `saida`). Validar um job real completo.
2. **Usuário não root (somente com host Linux disponível para teste):** `user: "${WHISPER_BOX_UID:-0}:${WHISPER_BOX_GID:-0}"` com o wrapper definindo UID/GID em POSIX; resolver a propriedade do volume `state` (criado pelo Docker como root). Resolve também o aviso de arquivos `root` em Linux (`README.md:77`). **Sem Linux para testar, não entregar este item.**
3. Painel em Linux desktop: com `cap_drop: [ALL]` e root sem `CAP_DAC_OVERRIDE`, escrever em `./entrada` criado pelo usuário do host pode falhar. Testar em Linux; se falhar, `cap_add: [DAC_OVERRIDE]` apenas no `painel` ou execução com UID do host. No Windows não há efeito.

### Bloco 3 — Imagem de teste separada

`Dockerfile` em dois estágios: `runtime` (sem `tests/`) e `test` (herda de `runtime` e copia `tests/`). O serviço `test` (`compose.yaml:106-112`) passa a usar `build: {context: ., target: test}` e imagem própria (`whisper-box:test`), mantendo `network_mode: none` e `pull_policy: never`. O `.dockerignore` continua permitindo `tests/` (allowlist, linhas 7-8) para o estágio de teste. Atualizar os comandos de validação do `AGENTS.md` e do README (`docker compose build worker test`). **Critério:** a imagem `whisper-box:local` não contém `/app/tests`.

### Bloco 4 — CI no GitHub Actions

`.github/workflows/ci.yml` (gatilho `push` e `pull_request`): checkout, `docker compose build worker test`, `docker compose --profile test run --rm --no-deps -T test`. Fixar as ações por SHA, permissões mínimas (`contents: read`), sem segredos. Passo extra de sintaxe do wrapper com `python3.8 -m py_compile whisper-box.py` (verificar a disponibilidade do Python 3.8 no runner escolhido). Sem `prepare` nem modelo no CI (o modelo tem cerca de 500 MB e a suíte usa dados sintéticos); o ensaio real (`tests/smoke.py`) continua local. Depende do bloco 3 só para tempo de build, não para funcionar.

### Bloco 5 — Aviso de consentimento (frontend, `painel/`)

1. **Consentimento na primeira gravação:** antes da primeira gravação o painel mostra um aviso curto (texto proposto: “Gravar uma reunião exige a ciência dos participantes. A responsabilidade é de quem grava.”) com confirmação explícita; a confirmação é guardada em `localStorage` (`consentimento_v1`) e o aviso não reaparece. Alinhar microcopy e foco com `docs/design/painel-revisao.md` (seções 8, 9 e 11) e consultar o agente `designer` se o fluxo mudar. O README já traz a nota (`README.md:63`).
2. Verificar que `app.js` continua sem dependências e sem CDN (AGENTS.md).

Nota: o bloco antes incluía a avaliação de PWA instalável (service worker, `painel/sw.js`, manifest). Foi **descartado** em 20/11/2026: o produto é exclusivamente desktop e a janela própria (`python whisper-box.py painel`, modo `--app`) cobre o uso.

### Bloco 6 — Resiliência após reiniciar o Docker (critério 22 da A02, reaproveitado)

1. `compose.yaml:80`: o worker usa `restart: "on-failure:3"`, enquanto o painel usa `unless-stopped` (`compose.yaml:59`). Avaliar e, se confirmado por ensaio, mudar o worker para `unless-stopped` para que ele volte após reiniciar o Docker Desktop. O encerramento manual (`stop`, SIGTERM, `exit 0` em `worker.py:58`) não deve reiniciá-lo. Ensaio: com um job `running`, reiniciar o Docker Desktop e conferir que o worker retorna sozinho e a recuperação (`worker.py:48-52`) recoloca o job na fila.
2. Registrar o resultado em `docs/VALIDACAO.md`.

### Bloco 7 — Qualidade nas fronteiras de bloco e correção de documentação

1. **Fronteiras de 300 s cortando palavras** (`pipeline.py:14-47`). Recomendação: em vez de corte seco, fechar o bloco no ponto de **menor energia** de uma janela de busca (por exemplo, o trecho de 1 s de menor energia RMS entre 270 s e 300 s do bloco), mantendo o limite de memória (o buffer atual é `300 s` de `float32`; acrescentar um pequeno retalho de busca). Alternativa descartada por complexidade: sobreposição com remoção de segmentos duplicados. Mudança de inferência: **bump de `pipeline_version`** (compartilhar o bump com a A06, um por release) e `chunk_seconds` passa a ser “alvo máximo” (`config.py:52`; incluir um campo de configuração, por exemplo `boundary: "silence"`, no fingerprint). Deve preceder o checkpoint da A06 (blocos estáveis antes de persistir).
   Teste: áudio sintético com tons e uma pausa próxima do limite, verificando que o corte cai na pausa; teste de memória; comparação manual das fronteiras (300, 600, 900 s) da gravação real de 23 min antes e depois.
2. **Corrigir a A01** ([A01](A01-transcricao-offline-docker.md), linhas 78-79, 85 e 104): o diagrama e a árvore ainda citam `estado/jobs.sqlite` e a pasta `estado/`; o estado vive no volume Docker `whisper-box_state` (já dito no §4 da própria A01). Ajustar o diagrama e a árvore e manter a nota de revisão. (Esta é a única tarefa desta action que edita a A01; fazê-la só depois de a sessão que revisa a A01 terminar.)

## 5. Contrato e interfaces afetados

| Bloco | Interface |
| --- | --- |
| 1 | Somente `docs/VALIDACAO.md`. |
| 2 | `compose.yaml` (worker e painel); possível `user` e variáveis `WHISPER_BOX_UID`/`GID` no wrapper. Contrato da CLI inalterado. |
| 3 | `Dockerfile`, `compose.yaml` (serviço `test`), comandos de validação do README e do `AGENTS.md`. |
| 4 | Novo `.github/workflows/ci.yml`. |
| 5 | `painel/app.js`, `painel/index.html`, `painel/app.css`. API inalterada. |
| 6 | `compose.yaml:80` (política de reinício). |
| 7 | `pipeline.py`, `config.py` (`effective_config`), `__init__.py` (`pipeline_version`), fingerprint e deduplicação; A01 (texto). |

## 6. Critérios de aceite

Bloco 1:
1. `docs/VALIDACAO.md` registra: gravação de 10 min e de 60 min com áudio do sistema e do microfone presentes; nenhum vídeo gravado em disco; contagem de pedaços; resultado da queda do navegador (perda máxima de cerca de 10 s) e a constatação sobre finalização de gravações abandonadas; comportamento no limite de 2 GiB; consumo do worker durante uma gravação concorrente; Chrome; e, se houver máquina, Linux/macOS desktop (como suporte não validado até haver ensaio completo).
2. `docker port` do painel mostra apenas `127.0.0.1`, acesso por IP da LAN falha, `Host`/`Origin` inválidos dão 421/403, e `docker inspect` confirma `saida` e `modelos` `ro` no painel e `NetworkMode: none` no worker.

Bloco 2:
3. O worker roda com `cap_drop: [ALL]`, `no-new-privileges` e `read_only` (`docker inspect`), e um job real conclui com `result` código 0.
4. (Linux) Com o usuário não root, `entrada/` e `saida/` ficam com o dono do host e o painel grava gravações com `cap_drop` aplicado; senão o item é documentado como não entregue.

Bloco 3:
5. `docker run --rm --entrypoint ls whisper-box:local /app` não lista `tests`; `docker compose --profile test run --rm --no-deps -T test` passa e `NetworkMode` continua `none`.

Bloco 4:
6. O workflow passa em um PR de teste, com a mesma suíte do Docker, ações fixadas por SHA e permissão `contents: read`.

Bloco 5:
7. O aviso de consentimento aparece na primeira gravação, bloqueia o início até a confirmação, não reaparece depois (limpar `localStorage` o reativa) e é acessível por teclado.

Bloco 6:
8. Depois de reiniciar o Docker Desktop com um job `running`, o worker volta sem comando do usuário e o job termina `succeeded`; `python whisper-box.py stop` mantém o worker parado.

Bloco 7:
9. Teste com áudio sintético: o corte de bloco cai na pausa mais próxima do limite; o pico de memória do pipeline não aumenta além de 10% do valor de referência.
10. `pipeline_version` foi incrementado (compartilhado com a A06), o fingerprint inclui o novo campo e a mudança de deduplicação está documentada.
11. Na gravação real, as fronteiras de 300, 600 e 900 s não dividem palavras em inspeção manual (anotar quantas dividiam antes).
12. A01 não cita mais `estado/jobs.sqlite` como pasta do repositório.

## 7. Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
docker inspect whisper-box-worker-1 --format "{{.HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.NetworkMode}}"
docker port whisper-box-painel-1
docker run --rm --entrypoint ls whisper-box:local /app           # bloco 3: sem tests
python tests/smoke.py --input CAMINHO                             # ensaio real depois de qualquer mudança no worker/pipeline
```

Testes manuais dos blocos 1, 5 e 6 seguem os roteiros das tarefas e são registrados em `docs/VALIDACAO.md`.

## 8. Riscos

| Risco | Tratamento |
| --- | --- |
| `read_only` ou `cap_drop` quebrar o worker (escrita inesperada, `/tmp`, HF cache). | `tmpfs` para `/tmp`, teste com job real e `smoke.py`; reverter o item se necessário. |
| Usuário não root sem Linux para teste. | Não entregar; registrar como pendente. |
| CI sem modelo cobre menos que o ensaio real. | Declarar o limite no workflow e no README; `smoke.py` continua manual. |
| Corte em silêncio muda a transcrição e invalida a deduplicação. | Bump único coordenado com a A06; documentação. |
| Reinício automático do worker consumir CPU no login com fila cheia. | Aceito (trabalho já enfileirado pelo usuário); registrar. |
| Ensaios manuais dependem do Igor. | Bloco 1 agendado separadamente, sem bloquear código. |
| Linux/macOS desktop declarados “suportados” sem ensaio. | Manter o rótulo “suporte não validado” até haver ensaio completo registrado. |

## 9. Dependências

- Nenhuma action é pré-requisito dos blocos 1 a 5. O bloco 7.1 deve vir **antes** do checkpoint da A06 e compartilhar seu bump de versão; os blocos 3 e 6 tocam `compose.yaml`, também alterado em A04 e A06, então devem esperar esses merges.
- Sem decisões pendentes do Igor nesta action: a D5 (PWA) foi resolvida em 20/11/2026 (descartado).
- Handoffs: `qa-engineer` (bloco 1), `infra` (blocos 2, 3, 4 e 6), `dev-frontend` e `designer` (bloco 5), `dev-backend` (bloco 7), `code-reviewer` (blocos 2, 4 e 5).
