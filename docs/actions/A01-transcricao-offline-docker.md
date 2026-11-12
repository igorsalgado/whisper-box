# A01 — Transcrição offline com Docker e integração com agentes

Data: 12/11/2026  
Estado: implementação autorizada em 12/11/2026; validação em andamento  
Projeto: Whisper Box (`whisper-box`)  
Destino pretendido: `igorsalgado/whisper-box` no GitHub

## 1. Problema e resultado esperado

Igor transcreve várias reuniões durante o dia. Hoje solicita a execução ao Codex, que utiliza faster-whisper localmente, mas precisa preparar ou adaptar scripts, executar comandos e acompanhar o processamento a cada demanda.

Criar um projeto independente, reutilizável e executável em Docker. A transcrição deve ocorrer inteiramente no sistema local, sem depender de raciocínio do agente, chamadas a APIs ou conexão com a internet durante o processamento.

O agente associado a outro sistema terá somente estas responsabilidades:

1. Solicitar a transcrição de um arquivo e receber o identificador do trabalho.
2. Aguardar o resultado usando um comando próprio do projeto.
3. Obter o estado final e os caminhos dos arquivos de saída.
4. Encaminhar ou ler esses arquivos apenas conforme a tarefa posterior do usuário.

O agente não instala dependências a cada reunião, não escreve scripts de transcrição, não carrega o modelo e não gerencia os segmentos produzidos. A espera não depende de manter uma conversa ativa nem de consultar repetidamente os logs.

## 2. Evidências e premissas

### Evidências locais

- Referência: `C:\Users\Igor\Desktop\Dev\lockfire\docs\reunioes\2026-11-12-call-processamento\transcrever.py`.
- O script usa faster-whisper, modelo `small`, CPU, `compute_type='int8'`, duas threads, um worker, idioma `pt` e filtro de atividade de voz.
- Há um Dockerfile baseado em `python:3.12-slim` com `faster-whisper==1.2.1`.
- O script gera texto com horários e segmentos JSONL, prevê metadados finais e também extrai imagens do vídeo. Os caminhos de entrada e saída são fixos.
- O script decodifica o áudio completo para memória. Isso precisa ser considerado no teste de gravações longas.
- O guia local do Lock Fire registra máquina com 16 GB de RAM, histórico de travamento com carga pesada e necessidade de limites nos containers.

Essas evidências orientam o projeto; não constituem validação de uma implementação nova. Os arquivos e as regras de entrega do Lock Fire não serão incorporados a este projeto independente.

### Premissas para o primeiro incremento

- Ambiente inicial: Windows com PowerShell e Docker Desktop em modo de containers Linux.
- Projeto utilizável por qualquer reunião, independentemente do repositório ou sistema do agente.
- Perfil inicial: CPU, modelo `small`, `int8`, português e um trabalho de transcrição por vez.
- Limites iniciais do worker: 2 CPUs e 4 GiB de memória; adequação depende de medição.
- Preparação inicial online; operação posterior offline com modelo completo persistido.
- Publicação futura na conta `igorsalgado`. Publicação privada inicial, conforme a premissa desta action.

## 3. Escopo da A01

- Imagem Docker reutilizável, dependências fixadas e Docker Compose próprio.
- Preparação explícita do modelo, separada da execução offline.
- Interface PowerShell fina, sem necessidade de Python instalado no Windows.
- Submissão explícita de arquivo, fila persistente, consulta de estado, espera e consulta de resultado.
- Worker independente do agente, com modelo carregado uma vez durante sua execução e reutilizado entre trabalhos.
- Processamento sequencial com proteção contra execução simultânea por mais de um worker sobre o mesmo estado.
- Resultados em texto com horários, SRT, segmentos JSONL e metadados JSON.
- Registros curtos de progresso e diagnóstico local de falhas.
- Documentação de uso humano e contrato para integração com agentes.
- Exclusão de gravações, resultados, modelos e estado do versionamento e do contexto de build.

### Fora do primeiro incremento

- Interface web, API HTTP, MCP e integração específica com um agente ou sistema externo.
- Monitoramento automático de pastas; na A01 a entrada ocorre por submissão explícita.
- Captura de reuniões ao vivo, identificação de falantes e extração de imagens do vídeo.
- Resumos, atas, decisões e tarefas produzidos por modelos de linguagem.
- GPU, múltiplos workers de transcrição, nuvem e acesso remoto.
- Retomada da inferência a partir de um segmento intermediário; a recuperação poderá reiniciar o arquivo completo.

## 4. Arquitetura e persistência

```text
Sistema/agente ou usuário
          │
          │ whisper-box.ps1: submit / status / wait / result
          ▼
CLI executada em container auxiliar sem rede
          │
          ├── entrada/<job_id>/arquivo.ext
          └── estado/jobs.sqlite
                       │
                       ▼
              Worker Docker sem rede
                       │
                       ├── modelos/ (somente leitura)
                       └── saida/<job_id>/
```

Estrutura planejada:

```text
whisper-box/
├── README.md
├── Dockerfile
├── compose.yaml
├── requirements.lock
├── .dockerignore
├── whisper-box.ps1
├── src/
├── tests/
├── docs/actions/
├── entrada/      # ignorada no Git
├── saida/        # ignorada no Git
├── estado/      # ignorada no Git
└── modelos/     # ignorada no Git
```

- A CLI e o worker compartilham o contrato de armazenamento, sem precisar de servidor HTTP.
- SQLite fica em volume Docker local, não em pasta de rede nem em bind mount do Windows. A CLI acessa o banco pelo container auxiliar; o host não precisa abri-lo.
- Entrada, saída e modelos usam armazenamento persistente. As saídas devem ser acessíveis pelo Windows.
- O host fornece arquivos por bind mount com caminho tratado como dado, nunca como comando de shell. Montar somente o arquivo ou a pasta necessários.
- A submissão copia o arquivo para uma entrada própria. O trabalho só entra na fila após a cópia completa e a publicação atômica do arquivo. O chamador deve fornecer uma gravação cuja escrita já terminou; detectar alteração durante a cópia e rejeitar a submissão.
- CLI e worker usam transações curtas, espera limitada para bloqueios do SQLite e atualização atômica de estados. `wait` não mantém uma transação aberta durante a espera.
- Os limites do worker são aplicados no Compose e conferidos no ambiente real. Containers auxiliares também terão limites explícitos e não carregarão o modelo de transcrição.

## 5. Contrato com o agente

Os comandos abaixo definem a interface de implementação. Serão executados a partir da raiz do projeto.

```powershell
# Preparação inicial com internet: imagem, dependências e modelo
.\whisper-box.ps1 prepare

# Inicia o worker em segundo plano; pode ser repetido com segurança
.\whisper-box.ps1 start

# Submete uma gravação e retorna um identificador
.\whisper-box.ps1 submit --input "C:\Reunioes\call.mp4"

# Espera por até 30 segundos; pode ser repetido pelo mesmo trabalho
.\whisper-box.ps1 wait --job "<job_id>" --timeout 30

# Consulta curta, sem abrir os arquivos da transcrição
.\whisper-box.ps1 status --job "<job_id>"

# Obtém o manifesto de saída de um trabalho concluído
.\whisper-box.ps1 result --job "<job_id>"
```

### Regras da interface

- `submit`, `status`, `wait` e `result` escrevem somente um objeto JSON em stdout. Diagnósticos de execução ficam em stderr e nos registros locais.
- O wrapper deve preservar os códigos de saída do projeto e funcionar sem instalações ou políticas globais adicionais no host, além dos pré-requisitos documentados.
- `submit` devolve `job_id`, estado e `reused`. `status` devolve estado e progresso disponível, sem conteúdo da reunião.
- `wait` bloqueia dentro do comando, sem usar um modelo de linguagem. Emite um único JSON ao terminar ou atingir o tempo limite; não transmite segmentos nem logs continuamente.
- `wait` admite de 1 a 60 segundos, com padrão de 30. O sistema associado pode renovar a espera conforme sua própria política.
- Tempo limite de espera não cancela nem reinicia o trabalho. Uma nova chamada usa o mesmo `job_id`.
- Em sucesso, a resposta informa os caminhos absolutos dos arquivos no Windows, relativos à configuração local do projeto, e os caminhos relativos portáveis.
- O agente pode entregar esses caminhos ao sistema sem carregar a transcrição na conversa. Ler a transcrição para outra finalidade é uma etapa explícita posterior.
- Antes da preparação ou com Docker/worker indisponível, devolver erro estruturado e orientação curta. Não instalar, baixar ou trocar o modelo silenciosamente.

### Códigos de saída

| Código | Significado |
| --- | --- |
| `0` | Comando atendido; em `wait` e `result`, trabalho concluído com sucesso. |
| `1` | Falha de transcrição ou erro operacional. |
| `2` | `wait` atingiu o tempo limite; trabalho pode continuar na fila ou em execução. |
| `3` | Argumento inválido ou trabalho inexistente. |
| `4` | `result` solicitado para trabalho ainda pendente ou em execução. |

Exemplo ilustrativo de resposta final, com identificador e caminho substituídos pelo ambiente real:

```json
{
  "job_id": "exemplo-id",
  "status": "succeeded",
  "files": {
    "text": "C:\\Users\\Igor\\Desktop\\Dev\\whisper-box\\saida\\exemplo-id\\transcricao.txt",
    "srt": "C:\\Users\\Igor\\Desktop\\Dev\\whisper-box\\saida\\exemplo-id\\transcricao.srt",
    "segments": "C:\\Users\\Igor\\Desktop\\Dev\\whisper-box\\saida\\exemplo-id\\segmentos.jsonl",
    "metadata": "C:\\Users\\Igor\\Desktop\\Dev\\whisper-box\\saida\\exemplo-id\\metadados.json"
  },
  "output_relative": "saida/exemplo-id"
}
```

## 6. Ciclo de vida e recuperação

- Estados públicos: `queued`, `running`, `succeeded` e `failed`.
- Persistir identificador, hash da entrada, configuração efetiva, versão do pipeline, versão/revisão do modelo, horários, tentativa, progresso e erro, quando houver.
- A chave de deduplicação combina conteúdo, configuração efetiva e versões do pipeline/modelo. Nova submissão equivalente reutiliza um trabalho pendente, em execução ou concluído e informa `reused: true`.
- Trabalho que falhou exige nova submissão explícita, que cria uma tentativa identificável sem apagar o histórico anterior.
- Entradas originais do usuário nunca são movidas nem apagadas pelo sistema.
- Desconexão do agente ou encerramento de `wait` não afetam o worker.
- Em reinício após interrupção, o worker exclusivo recupera trabalhos que ficaram em `running`, registra a interrupção e os recoloca na fila, com até três tentativas automáticas no total. Após esse limite, marca `failed` com motivo.
- Erros de arquivo, ausência de áudio e falhas normais de inferência geram `failed`; não entram em repetição automática indefinida.
- Cada tentativa escreve em diretório temporário próprio. Resultados parciais nunca são apresentados como completos nem misturados com a tentativa seguinte.
- `succeeded` só é persistido depois de todos os artefatos serem finalizados e publicados. Se houver interrupção entre publicação dos arquivos e atualização do estado, a recuperação deve reconhecer o manifesto completo ou refazer a tentativa com segurança.
- Progresso pode incluir último instante de áudio processado e tempo decorrido. Estimativa de conclusão não é compromisso de prazo.

## 7. Offline, desempenho e dados locais

- `prepare` verifica a integridade/completude do modelo e registra sua revisão. O runtime carrega por caminho local e falha claramente se o modelo estiver ausente.
- Worker e comandos de trabalho operam com `network_mode: none`. Somente a etapa explícita de preparação tem rede.
- A imagem pronta não instala pacotes ao iniciar nem exige chaves de APIs.
- Modelo carregado uma vez por execução do worker. Reiniciar o worker pode recarregá-lo do disco, sem download.
- Primeiro perfil: `small`, CPU, `int8`, duas threads, um worker, português, `beam_size=5`, VAD e `condition_on_previous_text=False`, preservando a configuração de referência até medir qualidade.
- Medir o consumo do áudio decodificado além do modelo. Se gravações de duas horas excederem o orçamento, ajustar a leitura/processamento antes de considerar o perfil aprovado.
- Sem garantias antecipadas de velocidade ou precisão. Nomes próprios, siglas e falas sobrepostas precisam de revisão humana quando relevantes.
- Texto e legendas mantêm os horários da gravação, inclusive após filtragem de silêncio.
- Arquivos locais permanecem até exclusão manual; não há retenção automática na A01.
- `.gitignore` e `.dockerignore` excluem dados reais, modelos, estados, logs e credenciais. Fixtures de teste serão sintéticas ou devidamente autorizadas.
- A transcrição local não usa a OpenAI. Interações com o agente e análise posterior podem consumir tokens; aguardar em código elimina a necessidade de acompanhamento contínuo por conversa.

## 8. Incrementos de implementação

| Ordem | Entrega | Resultado verificável |
| --- | --- | --- |
| 1 | Imagem, Compose e preparação | Modelo persistido, limites aplicados e execução sem rede. |
| 2 | Pipeline de arquivo único | Áudio/vídeo com áudio geram quatro artefatos consistentes. |
| 3 | Fila e recuperação | Submissões sequenciais, deduplicação, falhas e reinício preservam estados. |
| 4 | Contrato do agente | Wrapper oferece submit/status/wait/result com JSON e códigos definidos. |
| 5 | Validação e documentação | Fluxo completo reproduzível no Windows, medições e guia de integração. |

Cada incremento terá validação correspondente. A integração com um sistema externo poderá ser feita depois sobre esse contrato, sem alterar o motor de transcrição.

## 9. Critérios de aceite

1. [ ] Após `prepare`, uma gravação real autorizada é transcrita com worker e CLI sem rede, sem downloads e sem credenciais externas.
2. [ ] `submit` aceita caminho com espaços e caracteres acentuados, devolve identificador e não depende de Python no host.
3. [ ] Arquivo inexistente, cópia alterada durante submissão, mídia inválida ou sem áudio produzem erro identificável, sem falso sucesso.
4. [ ] MP3, WAV, M4A e MP4 com áudio produzem TXT, SRT, JSONL e metadados, validados por fixtures apropriadas.
5. [ ] Uma entrada sem fala termina com sucesso e metadados indicando ausência de segmentos; uma mídia sem stream de áudio falha com motivo próprio.
6. [ ] Duas gravações submetidas em sequência são processadas uma por vez, sem mistura de arquivos ou caminhos.
7. [ ] Submissão duplicada com a mesma configuração e versões reutiliza o trabalho; outra configuração não reutiliza resultados incompatíveis.
8. [ ] `wait` retorna um único JSON, usa os códigos previstos e respeita o tempo limite com tolerância operacional documentada. O tempo limite não cancela o trabalho.
9. [ ] Encerrar o cliente de espera e consultar depois permite recuperar o resultado do mesmo trabalho.
10. [ ] Interromper e reiniciar o worker recupera o trabalho conforme o limite de tentativas, sem publicar arquivos parciais como resultado final.
11. [ ] Tentativa de iniciar um segundo worker sobre o mesmo estado é rejeitada claramente.
12. [ ] `result` fornece caminhos acessíveis pelo Windows e recusa anunciar conclusão antes de todos os artefatos estarem disponíveis.
13. [ ] Os limites de 2 CPUs/4 GiB são confirmados no Docker e uma gravação representativa de até duas horas é processada nesse perfil sem OOM. Se falhar, ajustar e documentar o perfil antes de concluir a A01.
14. [ ] Um segundo trabalho na mesma execução reutiliza o modelo já carregado. Os metadados registram configurações, versões, duração da mídia e tempo de processamento.
15. [ ] Um ensaio de integração inicia, submete, aguarda e recebe somente estado/caminhos, sem imprimir a transcrição no retorno dos comandos.
16. [ ] A inspeção dos arquivos destinados ao Git e do contexto de build não encontra gravações reais, transcrições, modelos, estados, logs ou segredos.

## 10. Plano de validação e métricas

- Testes automatizados para transições de estado, deduplicação, concorrência da fila, códigos de saída e publicação completa dos artefatos.
- Testes de integração em Docker para um áudio curto, um vídeo com áudio, silêncio, mídia inválida e ausência do modelo local.
- Ensaio manual no Windows com caminho acentuado, espera expirada, cliente desconectado, worker reiniciado e segundo worker rejeitado.
- Medição com gravação autorizada de até duas horas: duração, tempo de processamento, pico de memória observado e ocorrência de erros/OOM. Registrar a fonte e as limitações da medição.
- Amostragem manual de trechos do começo, meio e fim para avaliar qualidade e correspondência dos horários; não exigir igualdade literal entre execuções do modelo.
- Comparar o esforço operacional com o fluxo atual: nenhuma adaptação de script por reunião e nenhuma consulta de logs necessária ao agente no caminho de sucesso.
- Resultado desta etapa documental: implementação, transcrição, consumo de recursos e integração externa ainda não testados.

## 11. Publicação no GitHub

- Repositório pretendido: `igorsalgado/whisper-box`; confirmar disponibilidade do nome e conta autenticada no momento da criação.
- Antes do primeiro envio, revisar os arquivos selecionados e executar as validações aplicáveis.
- O usuário autorizou implementar, testar a gravação indicada, iniciar Git, criar o repositório remoto e publicar em commits por entrega. A criação remota e o push ocorrerão após os testes.
- Não presumir licença de distribuição; defini-la antes de publicação pública e preservar os avisos das dependências utilizadas.

## 12. Riscos e decisões para etapas futuras

| Ponto | Tratamento na A01 |
| --- | --- |
| Memória de gravações longas | Medir o pipeline completo e ajustar antes do aceite. |
| Reinícios e arquivos incompletos | Estado persistente, tentativas isoladas e publicação atômica. |
| Muitos tokens ao aguardar | Espera feita em código, retorno curto e sem leitura automática da transcrição. |
| Integração com agente ainda não identificado | Contrato CLI independente; adaptador específico fica para etapa posterior. |
| Precisão de nomes e falas simultâneas | Preservar texto bruto e horários; revisão quando necessária. |
| Acesso a reuniões no GitHub | Dados reais excluídos do Git e do contexto de build. |
| Uso simultâneo com outros projetos | Worker sequencial e limites explícitos; validar com a carga real da máquina. |

## 13. Referências

- [faster-whisper — documentação e carregamento de modelos locais](https://github.com/SYSTRAN/faster-whisper).
- Script e Dockerfile locais citados na seção 2, usados somente como referência técnica.

O projeto Lock Fire permanece apenas como referência. Os resultados da implementação e dos testes serão registrados em docs/VALIDACAO.md.
