# A05 — Skill de análise de transcrições (ex-F1 da A02)

Data: 20/11/2026
Estado: pronta para execução (depende do `list` da A03)
Prioridade: 3 (pode correr em paralelo com a A04 depois do merge da A03)
Tamanho: S/M (uma sessão de um agente, sem alteração do motor)
Projeto: Whisper Box (`whisper-box`)
Origem: fase F1 da [A02](A02-captura-ingestao-analise.md); pergunta 7 da A02.
Depende de: [A03](A03-contrato-do-motor.md) (comando `list`, tarefa 7).

## 1. Contexto

O motor gera `transcricao.txt` com linhas `[hh:mm:ss–hh:mm:ss] texto` (`pipeline.py:91`), SRT, `segmentos.jsonl` e `metadados.json`, e um `manifest.json` com hashes (`pipeline.py:113-116`) que `result` confere (`jobs.py:73-84`). Qualquer arquivo novo dentro de `saida/<job_id>/` não invalida o manifesto (ele só confere os quatro artefatos), mas **alterar** um deles invalida; a regra do projeto é nunca escrever em `saida/` (A02 §6.1). O painel monta `saida/` só leitura (`compose.yaml:49`).

Hoje o fluxo de análise é informal: o README (`README.md:228`) diz para ler `files.text`, citar horários e gravar fora de `saida/`, mas não há skill, nem forma estável de localizar a reunião certa (“a de ontem”). A decisão de privacidade do Igor (A02 §0 e §8) permite que o agente analise o **texto**; o áudio nunca é enviado.

## 2. Objetivo

O Igor diz ao seu agente “resuma a reunião de ontem” e recebe uma análise (resumo, decisões, tarefas com responsável e prazo, pontos em aberto), com cada decisão e tarefa citando horários reais da transcrição, salva em `analises/<job_id>/analise.md`, sem tocar em `saida/`.

Métricas (A02 §11): reunião certa na primeira tentativa em pelo menos 9 de 10 pedidos; **zero** itens de decisão/tarefa sem horário citado em amostra de 5 análises.

## 3. Decisão tomada nesta action — formato (pergunta 7 da A02)

**Um arquivo por análise:** `analises/<job_id>/analise.md`. Justificativa: uma só leitura para o humano, menos arquivos para sincronizar, e o agente consegue extrair tarefas de uma tabela. Três arquivos (`ata.md`, `decisoes.md`, `tarefas.md`) só se o Igor pedir; marcar como decisão pendente confirmável (recomendação: 1 arquivo).

## 4. Escopo e fora de escopo

Escopo: skill do Claude Code; receita equivalente para outros agentes em `AGENTS.md`; passo de análise no README (“Para agentes”) e no `CLAUDE.md` do projeto; `.gitignore`; verificador opcional de citações.

Fora de escopo: análise sem agente; identificação de falantes; envio da análise a terceiros; exibir ou abrir análises no painel (backlog); mudanças no motor, no banco ou na API do painel; análise de áudio.

## 5. Tarefas

1. **`.claude/skills/whisper-box-analise/SKILL.md`**, com frontmatter (`name: whisper-box-analise`, `description` indicando quando usar: pedir resumo, ata, decisões ou tarefas de uma reunião transcrita) e este fluxo:
   1. **Localizar.** Resolver o pedido em um intervalo de datas no fuso local (“ontem”, “segunda”, “a daily de hoje”) e executar `python whisper-box.py list --status succeeded --since AAAA-MM-DD --until AAAA-MM-DD`. Usar `source_name`, `created_at` e `duration_seconds` para escolher. Sem `list` disponível (versão antiga), alternativa: `GET http://127.0.0.1:8765/api/transcricoes` com o painel no ar (traz `pasta` do host).
   2. **Desambiguar.** Se houver mais de um candidato plausível, **perguntar** ao usuário listando data/hora, `source_name` e duração; nunca adivinhar. Se não houver nenhum, dizer isso e sugerir ampliar o intervalo.
   3. **Ler** somente `files.text` do job escolhido (não abrir as demais transcrições). Respeitar a regra 3 do README: só o texto necessário; não colar a transcrição inteira na conversa.
   4. **Gerar** `analise.md` com as seções abaixo (modelo na skill).
   5. **Gravar** em `analises/<job_id>/analise.md` (criar a pasta). Se já existir, perguntar se sobrescreve ou grava `analise-AAAAMMDD-HHMM.md`; nunca sobrescrever em silêncio.
   6. **Conferir** que `saida/<job_id>/` não foi tocada: `python whisper-box.py result --job ID` deve devolver código 0.
   7. **Responder** com o caminho do arquivo, um resumo curto e o aviso de que a transcrição é automática (nomes próprios, siglas, ruído e falas simultâneas podem estar errados).
2. **Modelo do `analise.md`** (dentro da skill e na receita do `AGENTS.md`):
   - Cabeçalho: título, `job_id`, `source_name`, data e hora do início, duração, data da análise, aviso de transcrição automática.
   - **Resumo** (3 a 6 linhas).
   - **Decisões**: lista; cada item termina com horário(s) `[hh:mm:ss]`.
   - **Tarefas**: tabela `Tarefa | Responsável | Prazo | Horário`; responsável ou prazo ausentes na fala aparecem como **“não informado”**; nada inventado.
   - **Pontos em aberto** (dúvidas e pendências), também com horário.
   - **Citações de horário**: usar o instante de **início** de um segmento existente, formato `[hh:mm:ss]`, que precisa aparecer como início de linha em `transcricao.txt`. Quando o assunto abranger um trecho, citar o início de cada segmento relevante.
3. **Receita equivalente em `AGENTS.md`**, nova seção “Analisar transcrições”, escrita de modo que um agente que não é o Claude consiga seguir os mesmos passos sem a skill. Remover a frase de que a análise “ainda não está implementada”.
4. **README.** Em “Para agentes”: novo passo “Analisar uma transcrição” apontando para a receita (e para o `list`); atualizar a linha de limitações (`README.md:88`, “A análise por agente (skill) ainda não está implementada”); mencionar a pasta `analises/` na tabela “Onde ficam os arquivos” (`README.md:67-75`). No `CLAUDE.md` do projeto, uma linha apontando a skill.
5. **`.gitignore`**: acrescentar `/analises/` ao bloco de dados locais (`.gitignore:1-7`). O `.dockerignore` é uma allowlist (`**` na linha 2) e já exclui `analises/` do build; apenas confirmar. Conferir que `.claude/skills/` **não** é ignorado e entra no commit (o resto de `.claude/` não).
6. **Verificador de citações (opcional, recomendado).** `tests/check_analise.py` (somente biblioteca padrão; Python do host) recebe `--analise caminho --transcricao caminho` e verifica: toda linha das seções Decisões, Tarefas e Pontos em aberto contém ao menos um `[hh:mm:ss]` que existe como início de segmento na transcrição; responsáveis e prazos ausentes aparecem como “não informado” (não vazios). Saída em JSON, código 0/1. Testes unitários em `tests/test_analise.py` com **transcrição sintética** (o Docker roda o `unittest discover`, `compose.yaml:112`; o nome `check_analise.py` não é descoberto como teste). A skill instrui o agente a rodar o verificador antes de responder.
7. **`list` com `analysis_path` (opcional).** Acrescentar de forma aditiva ao schema da A03 o campo `analysis_path` quando existir `analises/<job_id>/`, montando `./analises:/analises:ro` no serviço `cli` (`compose.yaml:88-91`; manter `network_mode: none`). Se a montagem criar problemas (pasta inexistente criada por root no Linux), pular e deixar o agente checar a pasta no host.
8. **Validação** (seção 7) e registro em `docs/VALIDACAO.md`: apenas contagens e métricas, **sem conteúdo** de reunião.

## 6. Contrato e interfaces afetados

| Interface | Mudança |
| --- | --- |
| Arquivos novos | `.claude/skills/whisper-box-analise/SKILL.md`, `tests/check_analise.py`, `tests/test_analise.py`, pasta local `analises/<job_id>/analise.md` (fora do Git). |
| CLI | Nenhuma obrigatória (usa `list` e `result` da A03). Opcional: campo `analysis_path` em `list`. |
| Compose | Opcional: mount `ro` de `analises` no `cli`. Worker e painel inalterados. |
| Documentação | README, `AGENTS.md`, `CLAUDE.md`, `.gitignore`. |
| `saida/`, banco, `effective_config` | Sem mudança; `saida/` continua intocada. |

## 7. Critérios de aceite

1. Com três transcrições existentes em dias diferentes, “resuma a reunião de ontem” seleciona o `job_id` correto por `list` e lê somente o `transcricao.txt` desse job (o registro de comandos do agente mostra uma única leitura de transcrição).
2. A análise é gravada em `analises/<job_id>/analise.md`; depois dela, `python whisper-box.py result --job ID` devolve código 0 e os hashes de `saida/<job_id>/` continuam válidos.
3. Cada item de Decisões, Tarefas e Pontos em aberto cita ao menos um `[hh:mm:ss]` que existe como início de segmento na transcrição; `tests/check_analise.py` devolve código 0 sobre a análise.
4. Responsável e prazo ausentes na fala aparecem como “não informado” e nenhum campo fica vazio nem inventado.
5. Pedido ambíguo (duas reuniões no mesmo dia, simulável com `--since/--until` do mesmo dia) leva a uma pergunta ao usuário listando as opções, sem escolher sozinho.
6. Reanálise do mesmo job com `analise.md` já existente pergunta antes de sobrescrever.
7. Nenhum arquivo é criado ou alterado dentro de `saida/`; `git status` não mostra `analises/`; `.claude/skills/whisper-box-analise/SKILL.md` aparece como arquivo a versionar.
8. `AGENTS.md` traz a receita completa e um agente sem a skill consegue segui-la (revisão de leitura por outro agente ou pelo `code-reviewer`).
9. O README e o `CLAUDE.md` não contêm mais a afirmação de que a análise não está implementada.
10. Se a tarefa 7 foi entregue: `list` traz `analysis_path` só quando a pasta existe; `docker inspect` do `cli` mostra o mount `ro` e a rede `none`.
11. Testes do verificador passam na suíte do Docker; nenhuma transcrição real é versionada.

## 8. Validação

```bash
docker compose build worker
docker compose --profile test run --rm --no-deps -T test
python whisper-box.py list --status succeeded --since 2026-11-19 --until 2026-11-19
python tests/check_analise.py --analise analises/JOB_ID/analise.md --transcricao saida/JOB_ID/transcricao.txt
python whisper-box.py result --job JOB_ID        # código 0 depois da análise
git status --short                               # analises/ não aparece
```

Ensaio de uso real: com as transcrições locais do Igor (já existem; se houver menos de três, enviar gravações curtas pela CLI ou pelo painel), pedir ao agente: “resuma a reunião de ontem”, depois um pedido ambíguo e uma reanálise. Medir acertos em 10 pedidos e a amostra de 5 análises (métricas da seção 2). Registrar somente métricas e comandos, nunca trechos.

## 9. Riscos

| Risco | Tratamento |
| --- | --- |
| Agente seleciona a reunião errada. | Regra de perguntar na ambiguidade; `list` por intervalo; critério 5. |
| Horários inventados ou aproximados. | Verificador da tarefa 6 e instrução de citar apenas inícios de segmentos existentes. |
| Vazamento de conteúdo para ferramentas externas além do agente. | Regra 3 do README; a skill não usa serviços externos e não cola a transcrição inteira na conversa. |
| Transcrições longas (1 h gera da ordem de 10 mil tokens) estouram contexto. | Para transcrições muito longas, ler por faixas de linhas ou usar `segmentos.jsonl`; documentar na skill. |
| Fuso horário errado ao interpretar “ontem”. | A skill usa o fuso do host; o `list` aplica o deslocamento local (A03). |
| Qualidade ruim da transcrição propaga erros à ata. | Aviso obrigatório na resposta e no cabeçalho do arquivo. |
| Fixtures reais no repositório. | Só transcrição sintética nos testes; `analises/` ignorada. |

## 10. Dependências

- Antes: **A03** (tarefa 7, `list`). Sem ela, só a rota alternativa do painel, que exige o painel no ar.
- Pode correr em paralelo com a A04 (arquivos diferentes), com cuidado nas edições do README e do `AGENTS.md`.
- Decisão pendente do Igor (confirmação, não bloqueante): 1 arquivo (recomendado) ou 3.
- Handoffs: `dev-backend` ou o agente que escreve a skill, `code-reviewer` (receita e privacidade), `qa-engineer` (métricas da seção 2).
