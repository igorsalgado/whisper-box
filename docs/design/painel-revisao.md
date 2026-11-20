# Revisão de design: minipainel do Whisper Box

Escopo: `painel/index.html`, `app.js`, `app.css`, `manifest.webmanifest`, `icone.svg`, mais os seis prints em `C:\tmp\telas\` (janela 380×640) e o contrato `docs/painel-api.md`. Nenhum código foi alterado. Restrições respeitadas: HTML/CSS/JS vanilla, sem dependências, CDN ou fontes externas, e sem mudança na API.

## Design Critique: Minipainel Whisper Box

### Overall Impression

O painel já cumpre bem a promessa: uma tela, um botão principal, estados claros e quase nenhuma configuração. A estrutura de rotas, os estados da gravação, a confirmação de descarte e a fila de envio estão sólidos.

O maior problema hoje é o corte à direita nos prints (diagnóstico abaixo). Fora isso, há três oportunidades:

1. Ganhar altura útil removendo o que é redundante: o título `h1` repetido, o botão de microfone separado, a pílula REC no topo e a dica fixa.
2. Corrigir contrastes que falham no tema escuro: texto branco sobre o verde e o vermelho claros dos badges e do botão Descartar.
3. Tornar o card de transcrição mais baixo e mais legível.

#### Diagnóstico do overflow (a causa não está onde parece)

Os prints mostram o conteúdo cortado à direita, mas as medidas indicam que o CSS do conteúdo não está estourando. A **largura de layout da página é maior que os 380 px do recorte**:

| Evidência no print | Leitura |
| --- | --- |
| Nav: as colunas começam em x≈0, 164 e 328 | `grid-template-columns: repeat(3,1fr)` com 164 px por coluna dá **≈492 px** de largura de layout. O 3º item (Logs) começa em x=328 e some no recorte. |
| Timer e texto centralizados em x≈245 | O centro de uma página de 492 px é 246. |
| Barras do medidor terminam em x≈376 | `.meters` tem 260 px e fica centralizado em 246, então vai de ≈116 a ≈376. Isso só é coerente com um layout de ≈492 px. |
| Tela Logs: o UA aparece cortado e o log vai além do recorte | Mesma causa. |
| UA nos Logs: `HeadlessChrome/157` | Os prints foram feitos em Chromium **headless**, que impõe largura mínima de janela (~500 px). A captura de 380 px é um recorte de uma página de ~492 px. |

Causas, em ordem de probabilidade:

1. **Artefato de captura (mais provável).** O Chromium impõe largura mínima à janela, e o layout viewport (`window.innerWidth`) fica em ≈492 px. O CSS está correto para essa largura, e o recorte esconde 112 px.
2. **Risco real na janela do Igor.** Em `--app --window-size=380,640`, a largura inclui a moldura da janela (bordas de ~8 px por lado no Windows). O viewport útil tende a ficar em ≈364 px, ou o Edge pode impor um mínimo maior. Em qualquer dos casos, o layout não pode depender de 380 exatos. O alvo de projeto passa a ser **de 320 a 500 px sem corte e sem rolagem horizontal**.

Não há elemento com largura fixa que force estouro. Os pontos frágeis latentes no CSS atual são:

- `repeat(3,1fr)` sem `minmax(0,…)` no `.nav`, que deixa as colunas crescerem com o conteúdo.
- `.item` com coluna `auto` à direita, onde badge, data e botão disputam espaço com um nome `nowrap`.
- `.diag` com `max-content` na coluna da chave ("Ajudante (Abrir pasta)" consome ~140 px).
- Texto longo sem `overflow-wrap` (UA, caminhos, comandos).

**Como confirmar (1 minuto, no dev-frontend):**

1. Adicionar temporariamente em Logs a linha `Janela: innerWidth × innerHeight` (esta linha passa a ser definitiva, ver Logs) e abrir pelo atalho real do Igor. Se aparecer ~492 ou mais, o corte era só do recorte.
2. Para refazer os prints com largura de verdade, usar o CDP `Emulation.setDeviceMetricsOverride({width:380,height:640,deviceScaleFactor:1,mobile:false})`, ou o Playwright com `viewport:{width:380,height:640}`. Não usar `--window-size` headless.
3. Detector de estouro (colar no console, em cada rota): `[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+0.5)`. A lista deve vir vazia.

A correção está na seção **Correção do overflow** da especificação.

### Usability

| Finding | Severity | Recommendation |
| --- | --- | --- |
| A página tem ≈492 px de layout, mas o painel é pensado para 380; o corte esconde o 3º item da nav, a dica, o badge e o botão dos cards. Sem a nav completa, o Logs fica inacessível. | 🔴 | Aplicar a correção do overflow (`minmax(0,1fr)`, `min-width:0`, `overflow-wrap`) e validar de 320 a 500 px. Mostrar `innerWidth` em Logs. |
| Contraste: no escuro, texto branco sobre `--ok` (#5ccf86) dá 1,96:1 (badge Concluída) e sobre `--danger` (#ef6b6b) dá 3,0:1 (badge Falhou, REC, botão Descartar). | 🔴 | Novos tokens `--on-ok` e `--on-danger` (ver tokens). Badge "Concluída" passa a texto colorido sem fundo cheio. |
| A pílula REC ocupa 46 px de altura no topo de Transcrições e Logs (e é redundante na tela Gravar, que já tem o timer). Cada pixel conta em 640 px. | 🟡 | Remover a pílula. Indicar a gravação na própria aba "Gravar" da nav (ponto pulsante + tempo) e no `document.title` (aparece na barra de título da janela --app). |
| O botão "Microfone" é um segundo botão com peso visual parecido ao do Gravar, e o estado ligado/desligado se confunde com ação. | 🟡 | Transformá-lo em interruptor (`role="switch"`) dentro da própria linha do medidor "Microfone". Sai um botão e 56 px. |
| A dica "Chrome ou Edge: escolha Tela inteira…" fica fixa na Gravar (cortada) e se repete em Logs. | 🟡 | Mostrar só no estado ocioso, em até 2 linhas, e apenas até a primeira gravação concluída (ou após o erro de áudio ausente). Remover de Logs. |
| Cada card tem ~110 px de altura (nome, badge, data, info e botão em 3 faixas). Cabem ~4 cards. | 🟡 | Card em 2 linhas (~66 px) com o botão como ícone à direita. Cabem ~7 cards. |
| "Cancelar" abre um painel de confirmação abaixo, que empurra o layout. | 🟡 | Trocar a linha de ações pela confirmação no mesmo lugar (sem salto). Esc volta. |
| Mensagens de erro misturam texto humano e técnico: "(NotAllowedError: Permission denied)". | 🟡 | Mostrar só a frase humana; manter o detalhe técnico no log (já é gravado). |
| Estado "enviando" mostra só "Enviando…", sem noção de progresso (gravações de 1 h geram ~720 pedaços). | 🟡 | Mostrar "Enviando… 62%", calculado no cliente por `(nextSeq − pendentes) / nextSeq`. Sem mudar a API. |
| Aviso "Motor parado — rode python whisper-box.py start" exige digitar o comando. | 🟢 | Tornar o comando tocável: toque copia e mostra "Copiado". |
| A lista de transcrições não tem estado de carregamento (fica em branco até a resposta) nem distingue "sem conexão" de "vazia". | 🟢 | Esqueleto de 3 cards, estado vazio ilustrado com texto e estado de erro que mantém a última lista. |
| Foco: ao trocar de estado (Gravar → Pausar/Parar), o botão focado some e o foco cai no `body`. A troca de rota não move o foco. | 🟢 | Regras de foco da especificação (mover para o novo botão primário; foco no título oculto da rota). |

### Visual Hierarchy

**O que chama o olho primeiro.** Na tela Gravar, o timer em 48 px negrito e depois o botão Gravar azul, o que está certo. Logo abaixo, o botão Microfone (contorno azul) compete com o Gravar. Nos cards, o que salta primeiro é o badge sólido (azul, verde ou vermelho), não o nome. Como a maioria dos cards é "Concluída", a lista vira uma coluna de blocos verdes que escondem o que importa: o que falhou ou está em andamento.

**Fluxo de leitura.**
- Gravar: timer → níveis → status → ação. A ordem é boa. O status repete informação do timer ("Gravação parada (00:12)") e a dica fica em último, sem hierarquia.
- Transcrições: o título "Transcrições" repete a aba ativa e consome 40 px. Dentro do card, o olho vai ao nome, desvia para o canto direito (badge e data empilhados), volta ao rodapé (info) e vai ao botão: um percurso em "Z" para ler uma linha de informação.
- Logs: o primeiro conteúdo é uma dica, não o diagnóstico. O UA de 150 caracteres domina a seção.

**Ênfase recomendada.**
1. Uma ação primária por estado, a única com fundo cheio: Gravar, Parar (gravando), Retomar (pausado), Transcrever (parado).
2. Cor semântica só onde há exceção: vermelho para erro e gravação em curso; azul para "em processamento"; verde discreto (texto) para concluída.
3. Texto secundário (data, duração, rótulos) sempre em `--muted` 12,5 px, nunca abaixo de 12 px.
4. Tela Gravar centrada com leve deslocamento para cima (centro óptico), sem título de página.

### Consistency

| Element | Issue | Recommendation |
| --- | --- | --- |
| Ícones da nav e dos botões | Misturam glifos de texto: `⏺`, `≡`, `▤`, `⏸`, `⏹`, `▶`, `✕`. Renderizam com tamanhos e pesos diferentes (o `⏺` aparece como círculo azul gordo, parecido com REC). | Ícones SVG inline (24×24, traço 2, `currentColor`), conjunto único (caminhos na especificação). |
| Botões | Seis variantes (`primary`, `stop`, `danger`, `link`, `small`, `mic`) com alturas 40/44 e raios 10/22/12. | Três variantes: `primary` (cheio), `secondary` (contorno), `ghost` (texto). Altura 44 px, exceto o ícone do card (44×44). Raio 10 px. |
| Badges | `.pill` com 4 fundos cheios. Concluída (a mais comum) é a mais gritante. | Concluída: texto verde com ✓, sem fundo. Fila: fundo âmbar suave. Processando: azul cheio. Falhou: vermelho cheio. |
| Tamanhos de fonte | 15, 17, 14, 13, 12,3, 11,7, 11,1, 10,8 px. Nav e datas ficam abaixo de 12 px. | Escala de 5 passos (12, 12,5/13, 14, 15, 48) e mínimo de 12 px. |
| Mensagens de estado | `.status` (centralizado), `.erro` (caixa), `.aviso` (faixa no topo), `.muted` (parágrafo) e `copiaStatus` (parágrafo extra). | Três componentes: linha de status (Gravar), caixa de mensagem (erro/aviso, com ícone) e feedback inline no próprio botão. |
| Cabeçalhos | `h1` em Transcrições e Logs, nenhum em Gravar. | Nenhum `h1` visível. Cada rota tem um `h1` `sr-only` (leitores de tela). |
| Microcopy | "aba" (é janela); "Enviando…" em duas variações; "Cancelar" vs "Cancelar gravação" vs "Descartar". | Ver microcopy: "janela", "Descartar" para a ação destrutiva, mesmos verbos em todo o app. |
| Tokens | Cores, raios e espaços em valores soltos (6, 8, 10, 12, 14 px). | Escala de espaço 4/8/12/16/24 e raios 10 e 999. |

### Accessibility

Contraste calculado a partir dos tokens de `app.css` (fórmula WCAG 2.x, luminância relativa sRGB):

| Par (primeiro plano / fundo) | Claro | Escuro | Critério | Veredito |
| --- | --- | --- | --- | --- |
| `--fg` / `--bg` | 15,1:1 | 15,0:1 | 4,5 | OK |
| `--fg` / `--card` | 16,2:1 | 13,5:1 | 4,5 | OK |
| `--muted` / `--card` | 5,9:1 | 6,5:1 | 4,5 | OK |
| `--muted` / `--bg` | 5,5:1 | 7,2:1 | 4,5 | OK |
| `--acc` / `--card` (nav ativa, links) | 5,2:1 | 5,0:1 | 4,5 | OK |
| `--acc` / `--bg` | 4,8:1 | 5,6:1 | 4,5 | OK (folga pequena no claro) |
| `--acc-fg` / `--acc` (Gravar, badge Processando) | 5,2:1 | 5,8:1 | 4,5 | OK |
| `--danger` texto / `--bg` | 5,2:1 | 6,0:1 | 4,5 | OK |
| `--danger` texto / `--err-bg` | 4,8:1 | ≈5,5:1 | 4,5 | OK |
| `#fff` / `--danger` (REC, badge Falhou, Descartar) | 5,6:1 | **3,0:1** | 4,5 | **Falha no escuro** |
| `#fff` / `--ok` (badge Concluída) | 5,1:1 | **1,96:1** | 4,5 | **Falha grave no escuro** |
| `--ok` texto / `--card` (feedback "Pasta aberta") | 5,1:1 | 8,3:1 | 4,5 | OK |
| `--bd` / `--card` (contorno de botão e card) | 1,4:1 | 1,4:1 | 3,0 (1.4.11, quando o contorno é a única pista) | Fraco. Aceitável nos cards (o texto identifica), mas reforçar nos botões secundários. |
| Trilho do medidor `--vu` / `--card` | 1,2:1 | n/c | 3,0 | Fraco. O preenchimento sobre o trilho dá 4,2:1; escurecer o trilho. |

Correções: tokens `--on-danger` e `--on-ok` (valores na especificação), com contraste mínimo de 6,3:1 e 9,6:1 no escuro. O trilho do medidor passa a usar um tom mais escuro.

**Alvos de toque.** Botões de 44 px, nav de 48 px e interruptor de microfone de 44 px estão dentro do recomendado. O `.btn.small` (40 px) e a pílula REC (40 px) ficam abaixo de 44, mas acima do mínimo de 24 px do WCAG 2.2 (2.5.8). Padronizar em 44 px. O botão de ícone do card terá 44×44.

**Legibilidade.** Textos de 10,8 a 12,3 px (nav, data, dica, diagnóstico) estão pequenos para uma janela compacta lida à distância de braço. Mínimo de 12 px, e 12,5 px para metadados do card.

**Outros critérios.**

- `prefers-reduced-motion` já é respeitado no ponto REC. Estender para esqueleto, indicador de progresso e transições.
- Medidores têm `role="meter"` com `aria-valuenow` atualizado a cada quadro. Leitores de tela podem ficar verbosos: tornar o `aria-valuenow` atualizado só a cada 500 ms, ou marcar os medidores `aria-hidden="true"` (são decorativos, o status já é anunciado).
- O timer tem `aria-hidden` e o status é `aria-live="polite"`. Bom. Não anunciar o tempo a cada segundo.
- A nav tem `aria-current="page"` e rótulo. Bom. O estado de gravação precisa estar no nome acessível da aba.
- `:focus-visible` com contorno de 3 px e offset de 2 px: bom. Manter.
- Cor nunca é a única pista: badges têm texto; o REC terá ponto e texto.
- Zoom de 200% e reflow (1.4.10): com 380 px a 200% o viewport equivale a 190 px. Não é requisito pleno aqui, mas a regra "sem rolagem horizontal até 320 px" cobre o essencial.

### What Works Well

- Hierarquia simples da tela Gravar: timer, níveis, uma ação. É exatamente o "poucos botões" que o Igor aprova.
- O ciclo ocioso → gravando → pausado → parado → enviando está bem definido, com botões ocultos em vez de desabilitados.
- A captura sobrevive à troca de rota (tudo no escopo do módulo) e o `beforeunload` protege contra fechar por engano.
- Fila de envio com retentativa e idempotência, sem custo para a interface.
- Confirmação explícita antes de descartar uma gravação, com foco movido para o botão de confirmação.
- Alvos de 44 px, `aria-pressed`, `role="status"/"alert"`, `lang="pt-BR"` e tema escuro automático.
- O destaque do job recém-enviado (`.novo`) fecha o ciclo: o usuário vê onde a transcrição foi parar.
- Feedback de "Abrir pasta"/"Copiar caminho" e o fallback sem ajudante.
- Detalhes honestos: `progress_seconds` apresentado como "processados", sem inventar previsão.

### Priority Recommendations (top 5)

1. **Garantir layout sem corte de 320 a 500 px e validar com viewport real** (CDP/Playwright, `innerWidth` em Logs, detector de estouro). Aplicar as correções de CSS defensivas. 🔴
2. **Corrigir contrastes do tema escuro** com `--on-danger` e `--on-ok`, e trocar o badge "Concluída" por texto verde sem fundo. 🔴
3. **Recuperar altura:** remover a pílula REC (usar aba Gravar + `document.title`), o `h1` visível, o botão de microfone separado (vira interruptor no medidor) e a dica fixa. 🟡
4. **Card de transcrição em 2 linhas** com ação em ícone 44×44, data relativa e badge discreto. 🟡
5. **Estados completos e microcopy:** esqueleto de carregamento, estado vazio, erro sem texto técnico, progresso de envio, confirmação inline, foco gerenciado e atalho Espaço. 🟡

---

## Especificação para o frontend

Público: dev-frontend. Tudo em HTML/CSS/JS vanilla, sem dependências nem fontes externas, sem alterar a API (`docs/painel-api.md`). Onde houver "novo", o dado já existe no cliente.

Alvo de largura: **320 a 560 px** (a janela --app deve ficar em ≈364 a 380 px úteis). Alvo de altura: **560 a 800 px**.

### 1. Tokens

Manter os nomes existentes (`--bg`, `--fg`, `--muted`, `--card`, `--bd`, `--acc`, `--acc-fg`, `--danger`, `--ok`, `--warn-*`, `--err-*`, `--vu`, `--r`) e acrescentar os novos.

#### Cores

| Token | Claro | Escuro | Uso |
| --- | --- | --- | --- |
| `--bg` | `#f6f7f9` | `#14171b` | fundo |
| `--fg` | `#1c2127` | `#e8ebef` | texto |
| `--muted` | `#5b6672` | `#9aa5b1` | texto secundário |
| `--card` | `#ffffff` | `#1d2127` | cards, nav |
| `--bd` | `#c3cad2` (era `#d6dbe1`) | `#434b56` (era `#343b44`) | contornos (≈2,0:1 / ≈2,0:1) |
| `--acc` | `#2563eb` | `#5b8def` | ação, aba ativa |
| `--acc-fg` | `#ffffff` | `#0b1220` | texto sobre `--acc` |
| `--danger` | `#c62828` | `#ef6b6b` | erro, REC |
| **`--on-danger`** (novo) | `#ffffff` (5,6:1) | `#1a0b0b` (6,3:1) | texto sobre `--danger` |
| `--ok` | `#1b7f3b` | `#5ccf86` | decorativo (pontos) |
| **`--ok-text`** (novo) | `#176c33` (6,5:1 no card) | `#5ccf86` (8,3:1) | texto verde "Concluída" |
| **`--on-ok`** (novo) | `#ffffff` | `#0b1220` | só se houver fundo `--ok` (9,6:1 no escuro) |
| `--warn-bg` / `--warn-bd` | `#fff6dd` / `#e5c36a` | `#2d2815` / `#7a6726` | aviso, "Na fila" |
| `--err-bg` / `--err-bd` | `#fde8e8` / `#e49a9a` | `#331b1b` / `#7a3333` | caixa de erro |
| `--vu` (trilho) | `#d5dae0` | `#2a3037` | trilho do medidor (mais escuro no claro) |
| `--ring` (novo) | `var(--acc)` | `var(--acc)` | foco: `outline:3px solid var(--ring); outline-offset:2px` |

Regras: nunca usar `#fff` direto sobre `--danger`/`--ok`; usar `--on-danger`/`--on-ok`. O `theme-color` do HTML (`#2563eb`) pode ficar como está. Opcionalmente, duplicar com `<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#14171b">`.

#### Espaçamento (`--s1` a `--s5`)

`4 · 8 · 12 · 16 · 24 px`. Padding horizontal das telas: **12 px** (`--s3`). Entre cards: 8 px. Padding interno do card: 10 px 12 px.

#### Raios

`--r: 10px` (botões, cards, caixas), `--r-pill: 999px` (badges, interruptor), medidor: 3 px.

#### Tipografia

Pilha: `system-ui, -apple-system, "Segoe UI", sans-serif` (sem fonte externa). Mono: `ui-monospace, Consolas, monospace`. `html{font-size:15px}` só como base; use px nos tokens abaixo para evitar variação.

| Papel | Tamanho / altura de linha | Peso | Observação |
| --- | --- | --- | --- |
| Timer | 48 px / 1,1 | 700 | `font-variant-numeric:tabular-nums`; em `max-height:560px` usar 40 px |
| Botão e nome do card | 15 px / 1,3 | 600 | |
| Corpo, status | 14 px / 1,4 | 400 (status 600) | |
| Metadados, dica, badge | 12,5 px / 1,35 | 400 (badge 600) | mínimo permitido: 12 px |
| Rótulo da nav | 12 px / 1,2 | 500 (ativa 700) | |
| Log e comandos | 12 px / 1,4 mono | 400 | |

### 2. Correção do overflow

Aplicar no `app.css` (não há conteúdo com largura fixa; a ideia é blindar e permitir quebra):

```css
html { width: 100%; }
body { margin: 0 auto; width: 100%; max-width: 560px; min-width: 0; overflow-x: hidden; }
main, .view, .view > * { min-width: 0; }
.view { padding: 8px 12px; }
.nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }   /* era repeat(3,1fr) */
.nav a { min-width: 0; }
.nav a span + * , .nav .lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
.item { min-width: 0; }
.diag dd, .aviso, .erro, .dica, .log, .meta { overflow-wrap: anywhere; }
.meters { width: min(280px, 100%); }
```

Conferência:

- Nenhum filho pode exceder `innerWidth` (detector no console da seção de diagnóstico).
- Testar em 320, 364, 380, 420 e 492 px, nos temas claro e escuro, nas três rotas e em todos os estados da Gravar.
- Em 320 px, a nav continua com 3 itens (cada ~106 px; rótulos de até 12 px cabem).
- Capturas devem ser feitas com viewport real (CDP `Emulation.setDeviceMetricsOverride` 380×640), não com `--window-size` headless.
- Em Logs, a linha "Janela" mostra `innerWidth × innerHeight` (ver Logs).
- Opcional, no host (fora do painel): se o Edge impuser mínimo maior que o desejado, registrar a largura observada. Não é necessário mudar a API.

### 3. Estrutura global

```
<body>
  <aviso>   (faixa, só quando há motor/modelo/painel com problema; 1 a 2 linhas)
  <main>    (rota ativa; rola internamente; sem cabeçalho visível)
  <nav>     (56 px, fixa no rodapé)
```

- **Remover** o `<header class="top">` e a `.rec-pill`. O `<div id="aviso">` passa a ser o primeiro filho de `<body>`, acima de `<main>`.
- `h1` de cada rota: `<h1 class="sr-only">Gravar</h1>` etc.
- `.sr-only{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}`.
- `document.title`: ocioso `Whisper Box`; gravando `● 12:34 · Whisper Box`; pausado `❚❚ 12:34 · Whisper Box`; enviando `Enviando… · Whisper Box`. Atualizar a cada segundo só durante a gravação.

### 4. Navegação inferior

Altura 56 px (`min-height:56px`), fundo `--card`, borda superior `1px solid var(--bd)`, 3 colunas `minmax(0,1fr)`. Cada aba: ícone SVG 22 px acima, rótulo 12 px abaixo, `gap:2px`. Aba ativa: cor `--acc`, rótulo 700 e barra superior de 3 px (`box-shadow: inset 0 3px 0 var(--acc)`, como hoje).

Ícones (SVG inline, `viewBox="0 0 24 24"`, `fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`, `aria-hidden="true"`):

| Aba | Ícone |
| --- | --- |
| Gravar | `<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="9"/>` |
| Transcrições | `<path d="M5 7h14M5 12h14M5 17h9"/>` |
| Logs | `<path d="M4 6l5 5-5 5M12 18h8"/>` |

**Indicador de gravação em todas as rotas (substitui a pílula REC):**

- Durante `gravando`, `pausado` e `parando`, a aba "Gravar" muda: rótulo vira o tempo (`12:34`, `tabular-nums`), cor `--danger`, o ícone vira um ponto cheio pulsante (`--danger`). Em pausa: rótulo `Pausa 12:34`, ponto estático.
- Em `enviando`, o rótulo vira `Enviando`.
- Se a aba ativa for Gravar, a aba continua com a barra superior `--acc`; nas demais rotas, a aba Gravar mantém texto em `--danger` sem barra.
- Acessibilidade: `aria-label` da aba é atualizado **só quando o estado muda** (não a cada segundo): `"Gravar, gravando"`, `"Gravar, em pausa"`, `"Gravar, enviando"`, `"Gravar"`. O rótulo visual do tempo recebe `aria-hidden="true"`.
- Pulsação: animação de opacidade 1 s (ver Animações). Contraste do texto `--danger` sobre `--card`: 5,2:1 (claro) e 5,4:1 (escuro). OK.
- Rationale: libera os 46 px do topo nas rotas Transcrições e Logs, e a barra de título da janela --app já mostra o tempo via `document.title`.

### 5. Tela Gravar

Container `#v-gravar`: coluna centralizada horizontal e verticalmente, `padding: 8px 12px 24px` (o `24px` embaixo desloca o conjunto levemente para cima, centro óptico), `gap: 12px`, `text-align:center`. Os botões de ação ocupam a largura útil até 320 px.

Componentes na ordem: **Timer → Medidores → Status → (Erro) → Ações → Dica (só ocioso)**.

#### Medidores (substituem o botão Microfone)

Duas linhas de 44 px, largura `min(280px,100%)`:

- Linha "Sistema": rótulo (72 px, 13 px, `--muted`) + barra de 8 px de altura. Não interativa.
- Linha "Microfone": `<button class="meter mic" role="switch" aria-checked="true|false">` com rótulo + barra + interruptor visual à direita (36×20 px, `--r-pill`, bolinha de 16 px; ligado `--acc`, desligado `--bd`). A linha inteira é o alvo de toque (44 px).
  - Habilitado só em `ocioso`. Nos demais estados, `disabled` e `title="Só dá para mudar antes de gravar"`, mantendo o estado atual visível. Não esmaecer abaixo de 0,6 de opacidade.
  - Desligado: barra vazia e rótulo "Microfone desligado". Durante a gravação, mostrar o mesmo texto em `--muted`.
  - Persistência atual (`whisperbox.ajustes`) permanece.
- Barra: trilho `--vu`, preenchimento `--ok`, vira `--danger` acima de −6 dB (comportamento atual). Remover `aria-valuenow` por quadro: marcar `.meters` com `aria-hidden="true"` para o leitor de tela, mantendo `role="meter"` só se atualizado no máximo a cada 500 ms. O botão do interruptor continua acessível.

#### Linha de status

Uma linha de 14 px/600, altura mínima 20 px (evita salto de layout). `role="status"` e `aria-live="polite"`. Textos na seção Microcopy.

#### Ações

Largura total, `gap:8px`. Botões de 44 px, `flex:1 1 0`, `min-width:0` (remover `min-width:130px`). Ícone SVG de 16 px à esquerda do rótulo.

#### Mockups ASCII (largura de 380 px, ≈ 48 colunas)

**Ocioso**

```
+------------------------------------------------+
|                                                |
|                                                |
|                     00:00                      |
|                                                |
|  Sistema      [=================           ]    |
|  Microfone    [=========            ]   (o-)   |
|                                                |
|               Pronto para gravar.              |
|                                                |
|   [            (●)  Gravar                   ] |
|                                                |
|   Na janela que abrir, escolha Tela inteira    |
|   e marque Compartilhar áudio do sistema.      |
|                                                |
+------------------------------------------------+
|  (●) Gravar |  ≡ Transcrições |  >_ Logs      |
+------------------------------------------------+
```

**Gravando**

```
+------------------------------------------------+
|                                                |
|                     12:34                      |
|                                                |
|  Sistema      [==========|=============   ]    |
|  Microfone    [======                 ]  (o-)  |
|                                                |
|        Gravando. Mantenha a janela aberta.     |
|                                                |
|   [   ❚❚ Pausar   ]    [   ■ Parar   ]         |
|                                                |
|               Descartar gravação               |
|                                                |
+------------------------------------------------+
|   (o) 12:34   |  ≡ Transcrições |  >_ Logs    |   <- aba Gravar em vermelho, ponto pulsa
+------------------------------------------------+
```

- Pausar: `secondary`. Parar: `secondary` com texto e contorno `--danger` (6,3:1 no escuro sobre `--card`; manter contorno de 2 px).
- "Descartar gravação" é `ghost` (texto `--muted` sublinhado), com `margin-top:16px` e **separado dos botões principais por ≥16 px** para evitar toque acidental. Mantém 44 px de altura.

**Pausado**

```
|                     12:34                      |   timer em --muted
|  Sistema      [                          ]     |   barras zeradas
|  Microfone    [                      ]  (o-)   |
|                Em pausa.                       |
|   [   ▶ Retomar   ]    [   ■ Parar   ]         |   Retomar vira primary
|               Descartar gravação               |
```

- Ao pausar, Retomar passa a `primary` e Pausar deixa de existir (mesmo botão, `aria-label` e ícone trocados, comportamento atual).
- O texto do timer pisca? **Não.** Só `--muted`; o ponto da aba fica estático.

**Confirmação de descarte** (substitui a linha de ações, sem salto):

```
|                     12:34                      |
|  Sistema      [                          ]     |
|  Microfone    [                      ]  (o-)   |
|                                                |
|     Descartar esta gravação? Não dá para       |
|     desfazer.                                  |
|   [   Descartar   ]    [   Voltar   ]          |   Descartar: --danger/--on-danger; Voltar: secondary
```

- Substituir o conteúdo de `.actions` e `.sub` por esta linha, mantendo a mesma altura (≈ 100 px). Foco inicial em **Voltar** (opção segura; hoje o foco vai para Descartar). `Esc` volta e devolve o foco ao botão "Descartar gravação".
- Texto em `role="alertdialog"`? Usar `role="group"` com `aria-labelledby` como hoje.

**Parado (pronto para transcrever)**

```
|                     12:34                      |   timer congelado, --fg
|  Sistema      [                          ]     |
|  Microfone    [                      ]  (o-)   |
|          Parada. Pronta para transcrever.      |
|                                                |
|   [            Transcrever                   ] |   primary, largura total
|                                                |
|               Descartar gravação               |
```

- Se `saude.worker === false`, acima de Transcrever aparecer a caixa de aviso "Motor parado. Inicie-o antes de transcrever." (não bloquear o botão).
- Se a parada foi automática (compartilhamento encerrado, erro do gravador): status "Parada: compartilhamento encerrado." (motivo curto, sem parênteses).

**Enviando**

```
|                     12:34                      |
|          Enviando… 62%                         |
|   [ ⟳  Enviando…                             ] |   primary, desabilitado, aria-busy
|   ============------------                     |   barra de progresso 4 px (--acc)
```

- Barra de progresso de 4 px logo abaixo do botão, preenchida por `(nextSeq − pendentes) / nextSeq`. `aria-valuenow` não é atualizado por quadro; só texto "Enviando… 62%" no status a cada 1 s.
- Sem "Descartar" durante o envio (comportamento atual).
- Em erro de envio: volta a `parado` com a caixa de erro (ver Erros).

**Iniciando** (diálogo de compartilhamento aberto)

```
|          Escolha o que compartilhar…           |
|   [ ⟳  Gravar ]  desabilitado                  |
```

#### Dica (só no ocioso)

12,5 px, `--muted`, máx. 2 linhas, centralizada, `max-width: 300px`. Exibir quando `localStorage['whisperbox.dica']` não existir; gravar a chave `1` ao concluir a primeira gravação com sucesso (estado `parado` com áudio do sistema). Também exibir sempre após o erro "Nenhum áudio do sistema…". Texto em Microcopy. Remover a dica da tela Logs.

### 6. Tela Transcrições

Container rolável (`overflow:auto`, `padding:8px 12px 16px`), sem título visível. Lista com `gap:8px`. Rolagem apenas dentro da lista.

#### Anatomia do card

```
+--------------------------------------------+------+
| gravacao-2026-11-20_1523              ...   |  [📁]|   linha 1: nome (600, ellipsis)
| ✓ Concluída · hoje 15:23 · 00:07            |      |   linha 2: badge + metadados (12,5, --muted)
+--------------------------------------------+------+
```

- Grade: `grid-template-columns:minmax(0,1fr) 44px; grid-template-areas:"nome acao" "meta acao"; gap:2px 8px; padding:10px 8px 10px 12px; align-items:center`.
- `nome`: sem extensão do arquivo (`replace(/\.[^.]+$/,'')`), `white-space:nowrap; overflow:hidden; text-overflow:ellipsis; title` com o nome completo.
- `meta`: `display:flex; flex-wrap:wrap; gap:4px 8px; font-size:12.5px; color:var(--muted)`. Itens, nesta ordem: badge de status, data, duração/andamento. Separador `·` só por CSS (`::before`), não lido por leitor de tela.
- `acao`: botão 44×44, `ghost`, só nos cards `succeeded` com `helper.porta` ou `j.pasta`. Ícone pasta (com ajudante) ou copiar (sem ajudante/falha do ajudante). `aria-label` "Abrir pasta de {nome}" / "Copiar caminho de {nome}"; `title` igual.
- Feedback ("Pasta aberta", "Caminho copiado", "Não foi possível abrir a pasta"): substitui, por 3 s, o texto de `meta` (em `--ok-text`, ou `--danger` no erro), com `role="status"`. O ícone do botão troca para ✓ durante o feedback. Nada de nova linha.
- Fundo `--card`, borda `1px solid var(--bd)`, `--r`.
- Estado "novo" (recém-enviado): borda `--acc` + anel de 2 px por **6 s**, depois transição de 300 ms para o normal. `scrollIntoView({block:'nearest'})` como hoje.

**Deslocamento em relação ao layout atual (aprovado pelo Igor):** a data deixa o canto superior direito e passa à segunda linha, ao lado do badge. Motivo: era a coluna direita (badge e data empilhados) que somava largura e altura e causava o corte. Se o Igor preferir a data no topo direito, manter `nome | data` na linha 1 e `badge · info` na linha 2, mantendo a ação à direita em 44×44. As duas variantes cabem em 320 px.

#### Badges (`.pill`)

Altura 20 px, padding `0 8px`, `--r-pill`, 12,5 px/600.

| Estado | Rótulo | Estilo |
| --- | --- | --- |
| `queued` | Na fila | fundo `--warn-bg`, borda `--warn-bd`, texto `--fg` |
| `running` | Processando | fundo `--acc`, texto `--acc-fg` |
| `succeeded` | ✓ Concluída | **sem fundo**, sem borda, texto `--ok-text` (ícone ✓ SVG 12 px) |
| `failed` | Falhou | fundo `--danger`, texto `--on-danger` |

#### Linha de metadados por estado

| Estado | Linha 2 (`meta`) |
| --- | --- |
| `queued` | `Na fila · hoje 15:23 · aguardando a vez` |
| `running` | `Processando · hoje 15:23 · 03:20 processados` + barra indeterminada de 2 px no rodapé do card |
| `succeeded` | `✓ Concluída · hoje 15:23 · 00:07` (duração da transcrição; título "Transcrita em 00:07" via `title`) |
| `failed` | Linha 2 com badge e data; **linha 3** (largura total, `grid-column:1/-1`): mensagem de erro, `color:var(--danger)`, 12,5 px, até 3 linhas (`-webkit-line-clamp:3`), `overflow-wrap:anywhere`. Sem botão de ação. |

**Data relativa:** `hoje HH:MM`, `ontem HH:MM`, `dd/mm HH:MM` (mesmo ano), `dd/mm/aaaa` (outro ano). Atributo `<time datetime>` e `title` com data completa (`dd/mm/aaaa HH:MM`).

#### Estados da lista

| Estado | Regra |
| --- | --- |
| **Carregando (1ª carga)** | 3 cards esqueleto (altura 62 px; duas barras cinza de 60% e 35% da largura; `--vu` com pulsar de opacidade 1,2 s; estático em reduced-motion). `aria-busy="true"` no `<ul>` e `role="status"` com texto oculto "Carregando transcrições". |
| **Vazio (sem transcrições)** | Centralizado verticalmente: ícone de lista (32 px, `--muted`), `Nenhuma transcrição ainda.` (14 px/600) e `Grave uma reunião e toque em Transcrever.` (12,5 px, `--muted`). Sem botão (a nav já leva a Gravar). |
| **Erro de carga** | Faixa de erro no topo da lista: `Sem conexão com o painel. Tentando de novo…`; manter a última lista visível (esmaecida a 0,6 se for velha); tentar novamente a cada 5 s (comportamento atual). Na 1ª carga sem dados: só a faixa, sem esqueleto. |
| **Em andamento** | Atualização a cada 3 s (atual). Atualizar o DOM sem recriar toda a lista, se possível (evita piscar e perda de foco). Se recriar, restaurar o foco no mesmo `job_id`. |
| **Lista cheia** | Até 50 itens (API). Sem paginação. Rolagem interna, nav sempre visível. |

### 7. Tela Logs

Container rolável, padding `8px 12px 16px`, sem título visível (`h1` `sr-only`). Largura útil integral.

```
+------------------------------------------------+
|  Diagnóstico                      [ Copiar log ]|   título de seção 14/600 + botão 44 px (secondary)
|  ● Painel   ● Motor   ● Modelo                  |   linha de saúde com pontos coloridos
|  Navegador   Edge 157 · Windows                 |
|  Janela      364 × 640                          |
|  Captura     HTTPS local · getDisplayMedia ok   |
|  Gravador    audio/webm;codecs=opus · 48 kHz    |
|  Ajudante    configurado (porta 8766)           |
|                                                |
|  Eventos                                        |
|  +--------------------------------------------+ |
|  |[13:00:49] Painel carregado. ...            | |   <pre> ocupa o resto da altura
|  +--------------------------------------------+ |
+------------------------------------------------+
```

- Remover a dica e o parágrafo `#copiaStatus`. O feedback do "Copiar log" vai **no próprio botão**: `Copiado ✓` por 2 s; em falha, `Selecionado: Ctrl+C` e o log selecionado.
- `dl.diag`: grade `96px minmax(0,1fr)` (largura fixa da chave, valor com `overflow-wrap:anywhere`). Chaves curtas (tabela abaixo). 12,5 px. Em largura <340 px, empilhar (chave acima do valor).
- **Navegador:** resumir o UA em `Navegador + versão + SO` por regex (`Edg/…`, `Chrome/…`; `Windows`, `Mac`, `Linux`). O UA completo aparece em `title` e sempre no texto copiado pelo "Copiar log". Evitar o UA bruto na tela.
- **Saúde:** substituir o JSON bruto de `/api/saude` por três pontos: `Painel`, `Motor`, `Modelo`, cada um com `●` (`--ok`/`--danger`) mais o texto (não depender só da cor). O JSON bruto continua no log copiado.
- `<pre>`: `flex:1; min-height:120px; max-height:none` (hoje 40vh), 12 px mono, `overflow:auto`, `tabindex="0"`, rolando ao fim a cada evento novo, **a menos que** o usuário tenha rolado para cima.
- Evento com erro em `--danger` (já existe). Prefixo "ERRO:" mantém a pista além da cor.

Mapa das linhas do diagnóstico:

| Rótulo novo | Fonte atual | Observação |
| --- | --- | --- |
| Saúde | `/api/saude` | pontos Painel/Motor/Modelo |
| Navegador | `navigator.userAgent` | resumido |
| Janela | `innerWidth × innerHeight` | **novo**, definitivo (diagnóstico de overflow) |
| Captura | `isSecureContext`, `getDisplayMedia`, `MediaRecorder` | uma linha: "Seguro · getDisplayMedia · MediaRecorder" com `✓/✗` |
| Gravador | `mimeType`, `sampleRate` | uma linha |
| Faixas | `sysTracks`, `micTracks` | uma linha (pode quebrar) |
| Ajudante | `helper.porta` | `configurado (porta N)` ou `não configurado` |

### 8. Estados de sistema (todas as rotas)

#### Motor parado / modelo não preparado / painel sem resposta

Faixa no topo (`#aviso`), 1 a 2 linhas, `role="status"`, ícone ⚠ SVG de 16 px, fundo `--warn-bg`, borda inferior `--warn-bd`, padding 8 px 12 px, 12,5 px:

```
+------------------------------------------------+
| ⚠  Motor parado. Toque para copiar o comando:  |
|    [python whisper-box.py start]               |
+------------------------------------------------+
```

- O comando é um `<button class="cmd">` (mono 12 px, `--card`, borda `--bd`, altura 44 px na área de toque via padding vertical) que copia o texto; feedback `Copiado ✓` por 2 s no próprio botão.
- Modelo: `Modelo não preparado. Rode: [python whisper-box.py prepare]` (mesmo comando-botão).
- Painel sem resposta: `Sem resposta do painel. Verifique se o contêiner está no ar.` Em cor de erro (`--err-bg`/`--err-bd`), sem comando.
- A faixa **não bloqueia** a gravação (o áudio é salvo mesmo com o motor parado). Aparece em todas as rotas, e `checkSaude()` roda também ao entrar em Transcrições e Logs (hoje só em Gravar).
- Ao voltar a normal, a faixa some sem animação (ou com fade de 150 ms, off em reduced-motion).

#### Erros da gravação (caixa `.erro`, abaixo do status)

Caixa `--err-bg`, borda `--err-bd`, ícone ✕ vermelho de 16 px, 13 px, texto `--fg` (não vermelho sobre vermelho: melhor leitura), `role="alert"`, `overflow-wrap:anywhere`. Sem botão. A ação de recuperação é o botão principal já visível. Limpar ao iniciar nova ação. Os textos técnicos (`NotAllowedError…`) vão só para o log.

### 9. Microcopy (PT-BR, curto)

Ajustes de tom: verbo no infinitivo para ações, ponto final em frases, "janela" em vez de "aba".

**Status da gravação**

| Estado | Hoje | Novo |
| --- | --- | --- |
| ocioso | Pronto para gravar. | Pronto para gravar. |
| iniciando | Escolha o que compartilhar… | Escolha o que compartilhar… |
| gravando | Gravando… mantenha esta aba aberta. | Gravando. Mantenha a janela aberta. |
| pausado | Pausado. | Em pausa. |
| parando | Finalizando… | Finalizando… |
| parado | Gravação parada (00:12). Pronta para transcrever. | Parada. Pronta para transcrever. |
| parado (motivo) | `(compartilhamento encerrado) …` | Parada: compartilhamento encerrado. |
| enviando | Enviando… | Enviando… 62% |
| vazia | Gravação vazia. | Gravação vazia. |
| cancelada | Gravação cancelada. | Gravação descartada. |
| cancelada sem limpeza | Gravação cancelada (o painel não confirmou a limpeza). | Descartada. O painel não confirmou a limpeza. |
| falha geral | Não foi possível iniciar. | Não foi possível iniciar. |

**Botões e controles**

| Hoje | Novo |
| --- | --- |
| ⏺ Gravar | Gravar |
| ⏸ Pausar / ▶ Retomar | Pausar / Retomar |
| ⏹ Parar | Parar |
| Transcrever / Enviando… | Transcrever / Enviando… |
| ✕ Cancelar / Cancelar gravação | Descartar gravação |
| Descartar esta gravação? | Descartar esta gravação? Não dá para desfazer. |
| Descartar / Voltar | Descartar / Voltar |
| Microfone | Microfone (interruptor); desligado: Microfone desligado |
| Abrir pasta / Copiar caminho | ícone com `aria-label` "Abrir pasta" / "Copiar caminho" |
| Copiar log | Copiar log |

**Dica (ocioso)**

> Na janela que abrir, escolha **Tela inteira** e marque **Compartilhar áudio do sistema**.

**Erros (frase humana; detalhe vai ao log)**

| Código | Texto |
| --- | --- |
| NotAllowedError (tela) | Compartilhamento cancelado. Toque em Gravar e escolha Tela inteira com áudio do sistema. |
| NotAllowedError (mic) | Microfone bloqueado. Libere o acesso nas configurações do site. |
| NotFoundError (mic) | Nenhum microfone encontrado. |
| NotFoundError (tela) | Nenhuma fonte de captura encontrada. |
| NotReadableError | Dispositivo em uso por outro aplicativo. |
| sem áudio do sistema | Nenhum áudio do sistema foi compartilhado. Escolha Tela inteira e marque Compartilhar áudio do sistema. |
| navegador sem suporte | Este navegador não captura áudio do sistema. Use Chrome ou Edge. |
| contexto inseguro | Abra o painel em http://127.0.0.1. |
| criar gravação falhou | Não foi possível iniciar a gravação no painel. |
| envio incompleto | Falha ao enviar. Toque em Transcrever para tentar de novo. |
| transcrição falhou | Não foi possível transcrever. Tente de novo. |
| worker_unavailable | Motor parado. Inicie-o e toque em Transcrever. |
| lista de transcrições | Sem conexão com o painel. Tentando de novo… |

**Lista de transcrições**

| Estado | Texto |
| --- | --- |
| Vazio | **Nenhuma transcrição ainda.** Grave uma reunião e toque em Transcrever. |
| Fila | Na fila · aguardando a vez |
| Processando | Processando · 03:20 processados |
| Concluída | Concluída · 00:07 |
| Falha sem mensagem | Falha na transcrição. |
| Feedback | Pasta aberta · Caminho copiado · Não foi possível abrir a pasta · Não foi possível copiar |

**Avisos de sistema**

| Situação | Texto |
| --- | --- |
| Motor parado | Motor parado. Toque para copiar o comando: `python whisper-box.py start` |
| Modelo | Modelo não preparado. Rode: `python whisper-box.py prepare` |
| Painel | Sem resposta do painel. Verifique se o contêiner está no ar. |

### 10. Animações (discretas)

| Elemento | Animação | Duração | Reduced motion |
| --- | --- | --- | --- |
| Ponto REC (aba Gravar) | opacidade 1 ↔ 0,25 | 1 s, infinita | estático, opacidade 1 |
| Medidores | largura (`transition: width .08s`) | 80 ms | manter (é dado, não decoração) |
| Troca de estado dos botões | nenhuma (trocar `hidden`) | — | — |
| Aba ativa | cor e barra superior | 120 ms | sem transição |
| Card novo | anel `--acc` some | 300 ms após 6 s | remover sem transição |
| Esqueleto de carregamento | opacidade 0,6 ↔ 1 | 1,2 s | estático (`--vu` fixo) |
| Barra de progresso / indeterminada | `translateX` de 40% de largura em loop | 1,4 s | barra estática a 30% |
| Faixa de aviso | fade 150 ms | 150 ms | sem fade |
| Botão pressionado | `transform:scale(.98)` | 80 ms | sem transform |

Bloco único para desligar tudo:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

### 11. Foco e teclado

**Ordem de Tab (Gravar):** faixa de aviso (botão do comando, se houver) → interruptor do Microfone → botões de ação (na ordem visual) → Descartar gravação → nav (Gravar, Transcrições, Logs). Em Transcrições: botões de ação dos cards na ordem da lista → nav. Em Logs: Copiar log → log (`tabindex=0`) → nav.

**Atalhos** (todos opcionais, anunciados em `title` e `aria-keyshortcuts`):

| Tecla | Ação | Condição |
| --- | --- | --- |
| Espaço | Gravar (ocioso) · Pausar/Retomar (gravando/pausado) | Só quando o foco **não** está em botão, link, interruptor ou campo. Com foco em botão, o Espaço mantém o comportamento nativo (aciona o botão). Chamar `preventDefault()` no atalho para a página não rolar. Na tela Gravar, apenas. |
| Esc | Cancela a confirmação de descarte e devolve o foco | Só com a confirmação aberta |
| Alt+1 / Alt+2 / Alt+3 | Gravar / Transcrições / Logs | Em qualquer rota |

Não usar Espaço para Parar ou Descartar (ações com consequência). Parar e Descartar exigem Tab + Enter, ou toque.

**Gestão de foco:**

- Ao trocar de estado, se o elemento focado ficar oculto, focar o primeiro botão visível da linha de ações (Gravando → Pausar; Pausado → Retomar; Parado → Transcrever; Ocioso → Gravar).
- Ao abrir a confirmação, foco em **Voltar** (segura); ao fechar, foco em "Descartar gravação".
- Em trocas de rota por clique/teclado, focar o `h1.sr-only` da nova rota (`tabindex="-1"`), sem contorno visível; leitor de tela anuncia o nome da tela.
- Após Transcrever com sucesso (que leva a Transcrições), o foco vai ao card destacado.
- O botão com `disabled` durante `enviando` mantém `aria-busy` e não perde o foco do usuário (se perder, ver regra acima).
- Foco visível: `outline:3px solid var(--ring); outline-offset:2px` em tudo; nos cards com botão, foco só no botão.

### 12. O que remover (para ficar mais compacto)

| Remover | Economia / motivo |
| --- | --- |
| `<header class="top">` e `.rec-pill` | 46 px no topo nas rotas Transcrições e Logs; indicador migra para a aba Gravar e `document.title`. |
| `h1` visível em Transcrições e Logs | 36 a 40 px; vira `sr-only`. |
| Botão separado de Microfone | 56 px e 1 botão; vira interruptor na linha do medidor. |
| Dica fixa na Gravar e em Logs | 30 a 40 px; só aparece no ocioso e até a 1ª gravação. |
| `#copiaStatus` e `#trStatus` (parágrafos de feedback) | Salto de layout; feedback vai no botão / estado vazio. |
| Painel de confirmação abaixo das ações | Salto de layout; troca no lugar. |
| Glifos `⏺ ⏸ ▶ ⏹ ✕ ≡ ▤` | Inconsistência de render; usar SVG. |
| UA completo, JSON de `/api/saude` e `sampleRate` solto em Logs | Ruído; resumos de uma linha. |
| `max-height:40vh` do log | Desperdício; o log ocupa o restante. |
| Texto técnico `(NotAllowedError: …)` nos erros da interface | Só no log. |
| `min-width:130px` dos botões grandes | Origem de quebra em larguras pequenas; usar `flex:1`. |
| Coluna direita empilhada (badge + data) dos cards | ~34 px por card e fonte do corte. |
| `.mic` com `min-width:44px`/raio 22 px, `.btn.link`/`.small` em variantes soltas | Unificar em `primary`, `secondary`, `ghost`. |

### 13. Critérios de aceite (QA)

1. **Sem corte:** em 320, 364, 380, 420 e 492 px, nos dois temas, em todas as rotas e estados, o detector de estouro retorna lista vazia e não há barra horizontal. A nav mostra os 3 itens.
2. **Contraste:** todo texto ≥ 4,5:1 nos dois temas (inclui Falhou, REC/aba Gravar, Descartar e Concluída no escuro). Contornos de botões secundários ≥ 3:1 (usar o `--bd` novo) ou com rótulo visível.
3. **Gravação visível em todas as rotas:** durante `gravando`/`pausado`, a aba Gravar mostra o tempo; o título da janela muda; ao parar, volta ao normal.
4. **Mic:** interruptor só muda no ocioso; estado anunciado (`aria-checked`); persistência preservada.
5. **Descartar:** confirmação sem salto de layout; foco inicial em Voltar; Esc cancela.
6. **Card:** nome com reticências, ícone de ação com alvo 44×44 e `aria-label` com o nome; 6+ cards visíveis em 640 px de altura (nav incluída).
7. **Estados:** esqueleto, vazio, erro de carga, em andamento, falhou (3 linhas) e novo-destacado testados; motor parado/modelo/painel indisponível mostram a faixa correta.
8. **Reduced motion:** com `prefers-reduced-motion: reduce`, nenhum elemento anima; ponto REC e esqueleto estáticos.
9. **Teclado:** Espaço comporta-se como descrito sem duplicar ação; Alt+1/2/3 navegam; foco nunca cai no `body` ao trocar de estado.
10. **Sem regressão:** API, fila de envio, retentativas, `beforeunload`, persistência do mic e comportamento do ajudante permanecem iguais.
