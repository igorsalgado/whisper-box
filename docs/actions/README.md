# Actions do Whisper Box — índice e roteiro

Atualizado em 20/11/2026 (HEAD `7eec6ec`). Cada action é um documento autossuficiente para um agente executar sozinho: contexto, objetivo, escopo, fora de escopo, tarefas numeradas, contrato afetado, critérios de aceite numerados, validação com comandos, riscos e dependências. O roteiro é um plano de trabalho, não uma promessa de prazo.

**Plataforma (decisão do Igor, 20/11/2026): o produto é exclusivamente desktop.** A interface é a janela própria aberta por `python whisper-box.py painel` (Edge ou Chrome em modo `--app`). Não há app instalável, PWA, service worker nem versão para celular. Windows com Docker Desktop é a plataforma **validada**; macOS e Linux desktop são **suporte não validado** (o código os trata, mas não há ensaio completo registrado; o áudio do sistema no navegador é limitado no macOS).

## 1. Estado das actions

| Action | Tema | Estado | Prioridade | Tamanho |
| --- | --- | --- | --- | --- |
| [A01](A01-transcricao-offline-docker.md) | Transcrição offline com Docker, fila, CLI e wrapper | **Concluída** e validada em 12/11/2026 (revisões de 19 e 20/11) | — | — |
| [A02](A02-captura-ingestao-analise.md) | Captura, ingestão e análise | **F3 (painel) concluída e validada pelo usuário em 20/11/2026** (captura de áudio do sistema e microfone no Edge; gravar, transcrever e abrir pasta). F0, F1, F2 e F4 redistribuídas (abaixo) | — | — |
| [A03](A03-contrato-do-motor.md) | Contrato do motor (ex-F0): I1 a I6, `list`, robustez do wrapper | **Concluída** em 20/11/2026 (`dda345f`; 118 testes, transcribe real com código 0) | — | — |
| [A04](A04-retencao-e-limpeza-de-disco.md) | Retenção, `purge`, limpeza de `.partial` e staging, espaço livre | **Implementada em 20/11/2026** (142 testes; padrão `delete` por D1; aguarda integração/commit) | 1 | M |
| [A05](A05-skill-de-analise.md) | Skill de análise de transcrições (ex-F1) | **Em execução** (D2: 1 arquivo, padrão recomendado) | 1 | S/M |
| [A06](A06-desempenho-e-robustez-do-motor.md) | Desempenho e robustez: threads/CPU, `exec`, observabilidade, checkpoint condicional | Pronta (medir antes de mudar) | 2 | M/L |
| [A07](A07-endurecimento-e-operacao.md) | Endurecimento, CI, consentimento, fronteiras de bloco, ensaios da F3 | Opcional, em blocos independentes | 3 | M |

### Para onde foi cada fase da A02

| Fase da A02 | Destino |
| --- | --- |
| F0 — Contrato do motor (I1 a I6, `list`, Ctrl+C/timeout) | **A03** (concluída) |
| F0 — Retenção, `purge`, limpeza de `saida/.partial/` | **A04** |
| F1 — Skill de análise | **A05** |
| F2 — Ingestão automática (pasta vigiada) | **Backlog** (decisão na seção 4) |
| F3 — Painel (entregue e validada) | Concluída; pendências: indicador de espaço livre em **A04**; ensaios (critérios 26, 28, 29, 31, 32) e consentimento em **A07** |
| F4 — Checkpoint por bloco | **A06** (tarefa 6, condicional) |
| F4 — App nativo de bandeja, macOS | Backlog |

### Mapa dos critérios de aceite da A02 (seção 9)

| Critérios | Situação |
| --- | --- |
| 1 a 7 e 10, 11 | A03 |
| 8 e 9 | A04 |
| 12 a 16 | A05 |
| 17 a 22 | Backlog (pasta vigiada); o 22 (worker volta após reiniciar o Docker) foi aproveitado na A07, bloco 6 |
| 23 | Invariante de todas as actions (`network_mode: none` e limites do worker, conferidos por `docker inspect`) |
| 24, 25 e 30 | **Validados pelo usuário em 20/11/2026** ([VALIDACAO.md](../VALIDACAO.md)); medição formal de gravação longa em A07, bloco 1 |
| 26, 28, 29, 31, 32 | A07, bloco 1 (ensaios); 27 e 30 mudaram com o desenho entregue (A02, seção 0); o 31 perdeu a parte de PWA (descartada) |

## 2. Ordem recomendada para a próxima sessão

1. **A03 (concluída em 20/11/2026)** primeiro e sozinha: corrige o contrato (I1 a I6), entrega o `list` e mexe em `whisper-box.py`, `store.py`, `jobs.py` e `__main__.py`, os mesmos arquivos de A04 e A06. Fazer o merge antes de abrir as outras evita conflito.
2. **A04 e A05 em paralelo** (agentes distintos) depois do merge da A03. A04 mexe em `pipeline.py`, `worker.py`, `painel.py`, `painel/app.js` e `compose.yaml`; A05 em `.claude/`, `AGENTS.md`, `README.md`, `.gitignore` e testes. Atenção apenas às edições simultâneas de README e `AGENTS.md` (integrar em sequência). A04 já pode começar as tarefas 1 a 3 e 5 durante a A03.
3. **A06** em seguida, **medindo primeiro**: depende de A03 (wrapper) e de A04 (`purge` para repetir benchmarks e a regra de `.partial`). Checkpoint só se o Igor decidir.
4. **A07** por blocos, quando houver tempo. O **bloco 1 (ensaios manuais da F3)** não depende de código e pode ser feito pelo Igor a qualquer momento.

```text
A03 (concluída) ───┬──► A04 ──┐
                    ├──► A05   ├──► A06 ──► A07 (blocos 3, 6 e 7.1 depois de A04/A06)
                    └──────────┘
A07 bloco 1 (ensaios manuais): independente, a qualquer momento
```

| Dependência | Motivo |
| --- | --- |
| A05 depende de A03 | Precisa do comando `list`. |
| A04 recomenda A03 | Reaproveita I5/I6 e os padrões de erro; `purge` e reprocessamento convivem. |
| A06 depende de A03 e A04 | Mesmas funções do wrapper; `purge --job` para benchmarks; regra de `.partial` com o checkpoint. |
| A07.7 antes do checkpoint da A06 | Blocos estáveis antes de persistir; um único bump de `pipeline_version` por release. |
| A07 blocos 3 e 6 após A04/A06 | Tocam `compose.yaml` e `Dockerfile` também alterados por elas. |

## 3. O que fica no backlog (sem action)

| Item | Motivo |
| --- | --- |
| **F2 — pasta vigiada `caixa-de-entrada/`** | Ver decisão da seção 4. |
| App nativo de bandeja (PySide6, WASAPI/Process Tap) | Só se o seletor de compartilhamento a cada gravação incomodar. O uso real de 20/11/2026 não relatou atrito. Continua sendo desktop. |
| macOS e Linux desktop como plataformas de captura | Suporte não validado. Exige ensaio completo; áudio do sistema no navegador é limitado no macOS. |
| Recuperar e finalizar pela interface gravações abandonadas em `entrada/.gravacoes/` | A04 apenas limpa o resíduo. Reavaliar se a perda por queda do navegador se mostrar frequente (A07, bloco 1). |
| Exibir ou abrir análises (`analises/`) no painel | Só depois de a A05 produzir análises. |
| `beam_size` 1, `BatchedInferencePipeline`, GPU, outro modelo | Experimentos futuros; exigem nova action e medição de qualidade. |
| Licença do projeto | Só se o repositório for público (A01 §11; README diz que não há licença própria). |
| Prioridade na fila (curto antes de longo) | A06 apenas registra a limitação. |

### Descartado (não é backlog)

| Item | Decisão |
| --- | --- |
| PWA, app instalável, service worker, manifest | Descartado em 20/11/2026 (D5): o produto é exclusivamente desktop e a janela própria cobre o uso. |
| Interface para celular ou tablet, acesso remoto | Fora do produto (somente desktop; painel só em `127.0.0.1`). |

## 4. Decisão sobre a F2 (pasta vigiada): fica no backlog

**Recomendação: não criar action própria agora.** Justificativa:

1. A F2 foi desenhada para que a gravação chegasse ao worker sem a interface. O painel entregue envia a gravação direto à fila pela API (A02, seção 0), então o caminho principal já tem zero passos manuais depois de **Parar** e **Transcrever**, e foi aprovado pelo Igor.
2. O caso restante é arquivo copiado à mão para uma pasta. Ele já está coberto por `transcribe --input` e `submit --input` (e pelo agente que opera a CLI).
3. Implementar exige mudar o perfil de segurança do worker: montar uma pasta nova em escrita, um laço de varredura com estabilidade de tamanho e `mtime`, política de `processadas/` (pergunta 3 da A02) e título derivado do nome (que exige migração de schema). É a maior superfície nova, para o menor ganho atual.
4. Ainda há débito mais valioso: contrato do motor, disco e análise.

**Gatilho para promover a action própria:** o Igor passar a receber gravações de outras ferramentas (por exemplo, gravação local do Teams ou do Zoom) em volume que torne o `submit` manual incômodo, ou pedir importação em lote. Alternativa mais barata nesse caso: um botão **Importar arquivo** no painel (upload pela mesma API de pedaços), avaliado com o `designer`.

## 5. Decisões do Igor

### Pendentes

| # | Decisão | Recomendação | Afeta |
| --- | --- | --- | --- |
| D2 | Formato da análise (pergunta 7): 1 ou 3 arquivos | 1 arquivo, `analises/<job_id>/analise.md` | A05 |
| D3 | F2 (pasta vigiada) fica no backlog? | Sim, conforme a seção 4 | Escopo |
| D4 | Checkpoint por bloco: agora ou com dados de uso | Esperar dados; instrumentação da A06 primeiro | A06 |
| D6 | Licença do projeto | Decidir só antes de tornar o repositório público | Publicação |

### Resolvidas

| # | Decisão | Resolução (20/11/2026) | Efeito |
| --- | --- | --- | --- |
| D5 | PWA instalável (service worker) | **Descartado**, não adiado. “Sem app, é totalmente desktop esse dev”: o produto é exclusivamente desktop, com janela própria (`python whisper-box.py painel`, Edge/Chrome em modo `--app`). O manifest PWA sai de `painel/`. | A02 (critério 31, fluxo e escopo da F3) e A07 (bloco 5) reescritos |
| D7 | Validação de uso real do painel | “Todas as funcionalidades estão ok”: o Igor validou captura de áudio do sistema e microfone no Edge, gravar, transcrever e abrir pasta. | A02: critérios 24, 25 e 30 validados |
| D8 | Próximo passo | “Corrigir bugs”: a A03 entra em execução. | A03 concluída (`dda345f`) |
| D1 | Retenção padrão da cópia de entrada (pergunta 1 da A02) | **Apagar `entrada/<job_id>/` após sucesso verificado** e manter a transcrição, com `WHISPER_BOX_INPUT_RETENTION` configurável. Para gravações do painel o áudio deixa de existir. | A04 em execução |

Perguntas da A02 já resolvidas: 2 (idioma automático no painel), 4, 5, 6 (captura de áudio do sistema inteiro com “Tela inteira” validada no Edge; áudio por aplicativo não testado), 8 e a de privacidade. A pergunta 3 (`processadas/`) fica sem efeito enquanto não houver pasta vigiada.

## 6. Convenções para os agentes executores

- Seguir [AGENTS.md](../../AGENTS.md): Python 3.8 no wrapper, só biblioteca padrão no host, sem `.ps1`/`.sh`, `network_mode: none` no worker e na CLI, 2 CPUs e 4 GiB como padrão, contrato JSON (um objeto em stdout) e códigos 0 a 4.
- Produto somente desktop: não propor PWA, instalação do painel, service worker nem layout para celular. Windows é a plataforma validada; macOS e Linux desktop são suporte não validado e só passam a “validados” com ensaio registrado em [VALIDACAO.md](../VALIDACAO.md).
- Atualizar README e `AGENTS.md` no mesmo trabalho quando mudar comando ou comportamento; registrar medições e ensaios em [VALIDACAO.md](../VALIDACAO.md) sem conteúdo de reunião.
- Nunca versionar gravações, transcrições, análises, modelos, logs, estado nem o perfil do navegador. Commits em português, Conventional Commits, uma mudança coerente por commit.
- Nas mensagens de commit e no PR, seguir a atribuição configurada pela sessão.
