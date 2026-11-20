---
name: whisper-box-analise
description: Use quando o usuário pedir resumo, ata, decisões ou tarefas de uma reunião já transcrita pelo Whisper Box (por exemplo "resuma a reunião de ontem", "quais as tarefas da daily de hoje"). Localiza a transcrição pelo comando list, lê só o transcricao.txt escolhido e grava analises/<job_id>/analise.md com horários citados.
---

# Análise de transcrição (Whisper Box)

Regras fixas (README, "Para agentes", regras 3 e 8): a análise é do **texto**; o áudio nunca é enviado a lugar nenhum; leia apenas a transcrição pedida; não use serviços externos; não cole a transcrição inteira na conversa; **nunca escreva em `saida/`** (alterar arquivos ali invalida a verificação). Não suba o painel. Todos os comandos rodam na raiz do projeto, com `python whisper-box.py`.

## Fluxo

1. **Localizar.** Converta o pedido em um intervalo de datas no fuso local ("ontem", "segunda", "hoje") e rode:
   `python whisper-box.py list --status succeeded --since AAAA-MM-DD --until AAAA-MM-DD`
   (stdout é JSON; não use `2>&1`). Cada item traz `job_id`, `source_name`, `created_at`, `started_at`, `finished_at`, `duration_seconds` e `files`. Sem `list` (versão antiga), use `GET http://127.0.0.1:8765/api/transcricoes` só se o painel já estiver no ar.
   - Trabalhos enviados pela CLI têm `source_name` `recording.<ext>`: o nome não identifica a reunião. Nesse caso escolha por data/hora (`started_at`/`created_at`) e `duration_seconds`; se isso não bastar, pergunte.
2. **Desambiguar.** Mais de um candidato plausível: **pergunte** ao usuário, listando data/hora, `source_name` e duração. Nunca adivinhe. Nenhum candidato: diga isso e sugira ampliar o intervalo. Não leia transcrições para "descobrir" qual é a certa.
3. **Ler** somente `files.text` do job escolhido, uma única vez. Transcrição muito longa (da ordem de 10 mil tokens por hora): leia por faixas de linhas, ou use `segmentos.jsonl` do mesmo job.
4. **Gerar** o `analise.md` pelo modelo abaixo.
5. **Gravar** em `analises/<job_id>/analise.md` (crie a pasta; ela é ignorada pelo Git). Se o arquivo já existir, **pergunte** se sobrescreve ou grava `analise-AAAAMMDD-HHMM.md`; nunca sobrescreva em silêncio.
6. **Verificar as citações:**
   `python tests/check_analise.py --analise analises/JOB_ID/analise.md --transcricao saida/JOB_ID/transcricao.txt`
   Código 0 é obrigatório; corrija os itens apontados e repita. (Se `tests/check_analise.py` não existir, confira à mão que cada horário citado é o início de uma linha da transcrição.)
7. **Conferir `saida/`:** `python whisper-box.py result --job JOB_ID` deve devolver código 0.
8. **Responder** com o caminho do arquivo, um resumo curto e o aviso: a transcrição é automática; nomes próprios, siglas, ruído e falas simultâneas podem estar errados.

## Citações de horário

Cite o instante de **início** de um segmento existente, no formato `[hh:mm:ss]`, que aparece como começo de linha em `transcricao.txt` (`[hh:mm:ss–hh:mm:ss] texto`). Nunca arredonde nem invente. Se o assunto abranger um trecho, cite o início de cada segmento relevante. Responsável ou prazo que não foram ditos: escreva **não informado**; nada inventado, nenhum campo vazio.

## Modelo do analise.md

```markdown
# Análise: <título curto da reunião>

- job_id: <job_id>
- Arquivo de origem: <source_name>
- Início: <AAAA-MM-DD hh:mm> (fuso local)
- Duração: <hh:mm:ss>
- Análise gerada em: <AAAA-MM-DD>
- Aviso: transcrição automática; nomes, siglas e falas simultâneas podem estar incorretos.

## Resumo
<3 a 6 linhas>

## Decisões
- <decisão> [hh:mm:ss]

## Tarefas
| Tarefa | Responsável | Prazo | Horário |
| --- | --- | --- | --- |
| <tarefa> | <nome ou não informado> | <prazo ou não informado> | [hh:mm:ss] |

## Pontos em aberto
- <dúvida ou pendência> [hh:mm:ss]
```

Seção sem itens: uma linha "Nenhuma decisão registrada." (ou equivalente começando com "Nenhum/Nenhuma").
