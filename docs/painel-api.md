# Painel — contrato da API local (A02, F3 adiantada)

Servidor: `python -m whisper_box painel` (biblioteca padrão, `ThreadingHTTPServer`, escuta em `0.0.0.0:8765` dentro do container) no serviço `painel` do Compose, publicado só em `127.0.0.1:${WHISPER_BOX_PAINEL_PORT:-8765}`. Serve os arquivos estáticos de `/srv/painel` (pasta `painel/` do repositório, montada somente leitura) e a API abaixo. O worker continua com `network_mode: none`; o painel o alcança apenas pela fila no volume `state`. Visão geral e decisões: [A02](actions/A02-captura-ingestao-analise.md).

## Segurança (todas as rotas)

- O cabeçalho `Host` precisa ser `127.0.0.1:<porta>` ou `localhost:<porta>` (porta pública); caso contrário a resposta é `421` `host_invalido` (bloqueia DNS rebinding).
- `POST`, `PUT` e `DELETE` exigem o cabeçalho `X-Whisper-Box: 1` (`403` `cabecalho_ausente`) e, se houver `Origin`, ele deve ser `http://127.0.0.1:<porta>` ou `http://localhost:<porta>` (`403` `origem_invalida`). Não há cabeçalhos CORS: a API só atende a própria página.
- Identificadores: `^[0-9a-f]{32}$` (outros caminhos caem em `404` `rota_inexistente`). Pedaço de até **16 MiB** (`413` `corpo_grande_demais`) e gravação de até **2 GiB** no total (`413` `gravacao_grande_demais`). Não há limite de duração: o limite de 4 horas não é aplicado.
- Corpos JSON de até 4096 bytes. `Content-Length` é obrigatório nos pedaços (`411` `length_required`; `Transfer-Encoding` não é aceito).
- Respostas trazem `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e `Referrer-Policy: no-referrer`; a API responde com `Cache-Control: no-store`.
- Erros: `{"error": {"code": "...", "message": "..."}}` com status HTTP 4xx/5xx; os códigos de `BoxError` do motor são preservados. Mapeamento: `worker_unavailable` e `model_not_ready` → `503`; `job_not_found` e `input_not_found` → `404`; `input_changed` → `409`; `invalid_language` → `400`; demais erros de argumento (saída 3) → `400`; o restante → `500`.
- O painel registra em stderr apenas método, rota (com `:id`), status e duração. Nunca registra áudio, texto de transcrições nem caminhos.

## Rotas

| Método e caminho | Corpo | Resposta |
| --- | --- | --- |
| `GET /` e arquivos estáticos | — | `index.html` e demais arquivos de `painel/` (`Cache-Control: no-cache`). Caminhos com segmentos iniciados por `.` ou fora da raiz: `404`. |
| `GET /api/saude` | — | `200 {"painel": "ok", "worker": true/false, "modelo": true/false}` |
| `POST /api/gravacoes` | `{"mime": "audio/webm;codecs=opus"}` | `201 {"id": "<32 hex>"}`; cria `entrada/.gravacoes/<id>.part` e `<id>.meta`. `400` `mime_invalido` se `mime` faltar; `415` `mime_invalido` se o tipo não for aceito. Tipos aceitos (parâmetros como `codecs` são ignorados): `audio/webm`, `video/webm` (`.webm`), `audio/ogg`, `video/ogg` (`.ogg`), `audio/mp4`, `video/mp4` (`.m4a`), `audio/wav`, `audio/x-wav` (`.wav`), `audio/mpeg` (`.mp3`). |
| `PUT /api/gravacoes/<id>/pedacos/<seq>` | bytes do pedaço (`application/octet-stream`) | `204`. `seq` começa em 0 e precisa ser o próximo esperado (`409` `sequencia_invalida`, com `"esperado": N` ao lado de `error`); reenviar o último `seq` já gravado é idempotente (`204`, o corpo é descartado). Pedaço vazio: `400` `pedaco_vazio`. Corpo curto: `400` `corpo_incompleto`. Gravação desconhecida: `404` `gravacao_inexistente`. Já enviada para transcrição: `409` `gravacao_fechada`. |
| `POST /api/gravacoes/<id>/transcrever` | opcional: `{"language": "auto"}` (`pt`, `en`, `es`, `auto`; padrão `auto`) | `202 {"job_id": "...", "status": "queued", "reused": false}`. Fecha o arquivo (`gravacao-AAAA-MM-DD_HHMM.<ext>`, que vira o `source_name`), chama `jobs.submit` e apaga o staging após o envio; se o envio falhar, o staging permanece e a chamada pode ser repetida. `400` `gravacao_vazia` sem dados; `400` `invalid_language`; `404` `gravacao_inexistente`; `503` `worker_unavailable` ou `model_not_ready`. Com os mesmos bytes e idioma, `reused` é `true` e o `job_id` é o existente. |
| `DELETE /api/gravacoes/<id>` | — | `204`; cancela e apaga o staging. `404` `gravacao_inexistente` se não existir. |
| `GET /api/transcricoes` | — | `200 {"transcricoes": [{"job_id", "status", "progress_seconds", "created_at", "started_at", "finished_at", "source_name", "error"?, "pasta"?}]}`, mais recentes primeiro, até 50. `error` (`code`, `message`) só em trabalhos com erro. `pasta` só em `succeeded` (ver revisão 2). **Não traz `downloads`.** |
| `GET /api/transcricoes/<job_id>` | — | `200` igual ao `status` da CLI (`job_id`, `status`, `attempts`, `progress_seconds`, `created_at`, `started_at`, `finished_at`, `error`?) mais `source_name`; sem caminhos de host e sem `pasta`. Com `"downloads": {"text": "/api/transcricoes/<id>/arquivos/text", "srt": "/api/transcricoes/<id>/arquivos/srt"}` quando `succeeded` e com saída verificada. `404` `job_not_found`. |
| `GET /api/transcricoes/<job_id>/arquivos/<text\|srt>` | — | O arquivo (`text/plain; charset=utf-8` ou `application/x-subrip`), com `Content-Disposition: attachment` e nome derivado do `source_name`. `409` `arquivo_indisponivel` se o trabalho não estiver `succeeded` e verificado. |

Outros métodos em rotas existentes retornam `405` `metodo_invalido`; rotas inexistentes, `404` `rota_inexistente`.

## Revisão 2 (pedido do Igor, 2026-11-20)

- **Idioma:** sempre detecção automática. O corpo de `transcrever` é opcional; sem `language`, o padrão é `auto`. A interface não oferece escolha e envia `auto`. (A CLI mantém `pt` como padrão.)
- **Sem downloads na interface:** os arquivos já estão no disco local. `GET /api/transcricoes` traz `pasta` em cada item `succeeded`: o caminho da pasta `saida/<job_id>` **no host** (derivado de `WHISPER_BOX_HOST_ROOT`, que o wrapper define), ou `null` se a raiz do host não for conhecida. As rotas de download continuam existindo, mas a interface não as usa e a lista não traz `downloads`.
- **Janela própria + ajudante no host:** `python whisper-box.py painel` (biblioteca padrão) garante worker e painel no ar, abre o Edge ou o Chrome em modo app (`--app`, perfil próprio em `.navegador/`, janela de 380×640) e, enquanto essa janela estiver aberta, mantém um **ajudante** HTTP no host:
  - Escuta em `127.0.0.1:<porta_ajudante>` (padrão 8766; se ocupada, tenta as 10 portas seguintes; `WHISPER_BOX_AJUDANTE_PORT` muda a inicial), com um token aleatório gerado a cada execução.
  - A janela abre em `http://127.0.0.1:<porta_painel>/?ajudante=<porta_ajudante>&token=<token>`. A página guarda os dois valores em `sessionStorage` e remove a query com `history.replaceState`.
  - Única rota: `POST http://127.0.0.1:<porta_ajudante>/abrir-pasta` com corpo `{"job_id": "<32 hex>"}` (até 1024 bytes) e cabeçalho `X-Whisper-Box-Token: <token>` → `204`. Abre `saida/<job_id>` no gerenciador de arquivos (Explorer, Finder ou `xdg-open`). Erros: `404` `rota_inexistente` (outro caminho ou método) ou `pasta_inexistente`; `400` `corpo_invalido` ou `job_id_invalido`; `403` `token_invalido` ou `origem_invalida`; `421` `host_invalido`; `500` `abrir_falhou`.
  - CORS: só `Access-Control-Allow-Origin` com a origem do painel (`http://127.0.0.1:<porta_painel>` ou `localhost`). O preflight `OPTIONS` (exige `Origin` válida) responde `204` liberando `POST, OPTIONS` e os cabeçalhos `Content-Type` e `X-Whisper-Box-Token`. O `Host` é validado como no painel.
  - Sem ajudante (painel aberto num navegador comum) ou se o ajudante falhar, o botão vira **Copiar caminho** e copia `pasta`.

## Fluxo da interface

`Gravar` → `POST /api/gravacoes` → a cada 5 s `PUT .../pedacos/<seq>` → `Pausar`/`Retomar` (só no cliente) → `Parar` →
`Transcrever` (`POST .../transcrever` com `{"language": "auto"}`; aguarda os pedaços pendentes antes) ou `Cancelar` (`DELETE`).
A tela de transcrições consulta `GET /api/transcricoes` a cada 3 s enquanto houver trabalho `queued` ou `running` (e tenta de novo a cada 5 s após uma falha de rede). A tela de logs consulta `GET /api/saude` para o diagnóstico (motor e modelo) e mostra os eventos da sessão, que ficam só no navegador.
