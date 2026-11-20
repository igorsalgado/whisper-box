/* Whisper Box — minipainel (SPA com rotas por hash).
   A captura vive no escopo do módulo; trocar de rota apenas mostra/oculta seções.

   MODO DEMONSTRAÇÃO (para os prints da documentação)
   Abra o painel com ?demo=<estado>, onde estado é: gravar | gravando | pausado | parado | transcricoes | logs.
   O painel renderiza o visual daquele estado sem pedir captura, sem chamar POST/PUT/DELETE e sem alterar dados:
   cronômetro fixo (12:34), níveis simulados estáticos, lista de transcrições fictícia (embutida) e saúde "normal".
   Tudo fica isolado no objeto Demo abaixo; sem ?demo= o fluxo normal não é afetado. */
(function () {
'use strict';

const $ = id => document.getElementById(id);
const pad = n => String(n).padStart(2, '0');
const fmtClock = sec => pad(Math.floor(sec / 60)) + ':' + pad(Math.floor(sec % 60));
const hhmmss = d => pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
const mk = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };

/* ---------- ícones SVG inline (conjunto único, constantes do próprio código) ---------- */
const ICONS = {
  rec: '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="9"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
  spin: '<path d="M12 3a9 9 0 1 0 9 9"/>'
};
function icon(name, size, cls) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', size); s.setAttribute('height', size);
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '2');
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.setAttribute('aria-hidden', 'true');
  if (cls) s.setAttribute('class', cls);
  s.innerHTML = ICONS[name];
  return s;
}
function setBtn(btn, name, text) {
  btn.textContent = '';
  if (name) btn.appendChild(icon(name, 16, name === 'spin' ? 'spin' : ''));
  btn.appendChild(mk('span', '', text));
}

/* ---------- modo demonstração (isolado) ---------- */
const Demo = (function () {
  const ESTADOS = ['gravar', 'gravando', 'pausado', 'parado', 'transcricoes', 'logs'];
  let q = null;
  try { q = new URLSearchParams(location.search).get('demo'); } catch (_) { /* sem demo */ }
  const ativo = ESTADOS.includes(q);
  const SEG = 754; // 12:34
  function lista() {
    const h = (dias, hh, mm, ss) => { const d = new Date(); d.setDate(d.getDate() - dias); d.setHours(hh, mm, ss || 0, 0); return d.toISOString(); };
    return [
      { job_id: 'demo-1', source_name: 'gravacao-2026-11-20_1523.webm', status: 'running', progress_seconds: 200, created_at: h(0, 15, 23), started_at: h(0, 15, 23, 5) },
      { job_id: 'demo-2', source_name: 'reuniao-planejamento.webm', status: 'succeeded', created_at: h(0, 14, 5), started_at: h(0, 14, 5, 0), finished_at: h(0, 14, 5, 7), pasta: 'C:\\whisper-box\\saida\\demo-2' },
      { job_id: 'demo-3', source_name: 'gravacao-2026-11-19_0910.webm', status: 'succeeded', created_at: h(1, 9, 10), started_at: h(1, 9, 10, 0), finished_at: h(1, 9, 13, 12), pasta: 'C:\\whisper-box\\saida\\demo-3' },
      { job_id: 'demo-4', source_name: 'entrevista-cliente.webm', status: 'failed', created_at: h(2, 18, 40), error: 'Falha ao decodificar o áudio: o arquivo não contém uma faixa de áudio legível (no_audio).' }
    ];
  }
  function aplicar() {
    if (!ativo) return;
    log('Modo demonstração (' + q + '): dados fictícios, nenhuma alteração é feita.');
    diagData.mime = 'audio/webm;codecs=opus'; diagData.sr = '48000 Hz';
    diagData.sysTracks = 'Áudio do sistema (demonstração)'; diagData.micTracks = 'Microfone (demonstração)';
    if (!location.hash || location.hash === '#') {
      const alvo = q === 'transcricoes' ? '#/transcricoes' : q === 'logs' ? '#/logs' : '#/gravar';
      history.replaceState(null, '', location.pathname + location.search + alvo);
    }
    const setMeters = (a, b) => {
      [['vuSys', a], ['vuMic', b]].forEach(([id, p]) => { const f = $(id).firstElementChild; f.style.width = p + '%'; f.classList.toggle('hot', false); });
    };
    if (q === 'gravando') { state = 'gravando'; statusMsg = 'Gravando. Mantenha a janela aberta.'; setMeters(62, 38); }
    else if (q === 'pausado') { state = 'pausado'; statusMsg = 'Em pausa.'; }
    else if (q === 'parado') { state = 'parado'; statusMsg = 'Parada. Pronta para transcrever.'; }
  }
  return { ativo, estado: q, seg: SEG, lista, aplicar };
})();

/* ---------- preferências (só microfone; idioma é sempre automático) ---------- */
const settings = { mic: true };
function loadSettings() {
  try {
    const raw = localStorage.getItem('whisperbox.ajustes');
    if (raw) {
      const o = JSON.parse(raw);
      if (typeof o.mic === 'boolean') settings.mic = o.mic;
      if ('lang' in o) localStorage.setItem('whisperbox.ajustes', JSON.stringify({ mic: settings.mic }));
    }
    for (const k of ['whisperbox.idioma', 'whisperbox.lang', 'whisperbox.language']) localStorage.removeItem(k);
  } catch (_) { /* armazenamento indisponível: usa padrões */ }
}
function saveSettings() {
  try { localStorage.setItem('whisperbox.ajustes', JSON.stringify({ mic: settings.mic })); return true; }
  catch (_) { return false; }
}
let forcarDica = false;
function mostrarDica() {
  if (forcarDica) return true;
  try { return !localStorage.getItem('whisperbox.dica'); } catch (_) { return true; }
}
function marcarDicaVista() { try { localStorage.setItem('whisperbox.dica', '1'); } catch (_) { /* segue */ } }

/* ---------- ajudante no host (Abrir pasta) ---------- */
const helper = { porta: '', token: '' };
const PORTA_RE = /^\d{2,5}$/;
function initHelper() {
  try {
    const q = new URLSearchParams(location.search);
    const porta = q.get('ajudante'), token = q.get('token');
    if (porta || token) {
      try {
        if (porta && PORTA_RE.test(porta)) sessionStorage.setItem('whisperbox.ajudante', porta);
        if (token) sessionStorage.setItem('whisperbox.token', token);
      } catch (_) { /* sem sessionStorage */ }
      history.replaceState(null, '', location.pathname + location.hash);
      if (porta && PORTA_RE.test(porta)) helper.porta = porta;
      if (token) helper.token = token;
    }
  } catch (_) { /* segue sem ajudante */ }
  try {
    helper.porta = helper.porta || sessionStorage.getItem('whisperbox.ajudante') || '';
    helper.token = helper.token || sessionStorage.getItem('whisperbox.token') || '';
  } catch (_) { /* segue */ }
  if (!PORTA_RE.test(helper.porta) || !helper.token) { helper.porta = ''; helper.token = ''; }
}

/* ---------- log da sessão ---------- */
const logs = [];
function log(evento, erro) {
  const e = { t: new Date(), evento: String(evento), erro: erro ? String(erro) : '' };
  logs.push(e);
  if (logs.length > 500) logs.shift();
  if (currentRoute === 'logs') renderLogs();
}
function logLine(e) { return '[' + hhmmss(e.t) + '] ' + e.evento + (e.erro ? ' — ERRO: ' + e.erro : ''); }
function renderLogs(force) {
  const pre = $('logPre');
  const noFim = force || pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
  pre.textContent = '';
  for (const e of logs) {
    const d = document.createElement('div');
    if (e.erro) d.className = 'e';
    d.textContent = logLine(e);
    pre.appendChild(d);
  }
  if (noFim) pre.scrollTop = pre.scrollHeight;
}

/* ---------- API ---------- */
class ApiError extends Error {
  constructor(code, message, status, extra) { super(message); this.code = code; this.status = status; this.extra = extra || {}; }
}
async function api(method, path, body, raw) {
  if (Demo.ativo) {
    if (method !== 'GET') throw new ApiError('demo', 'Modo demonstração: nenhuma alteração é feita.', 0);
    if (path === '/api/saude') return { painel: true, worker: true, modelo: true };
    if (path === '/api/transcricoes') return { transcricoes: Demo.lista() };
    throw new ApiError('demo', 'Modo demonstração.', 0);
  }
  const opts = { method, headers: {} };
  if (method !== 'GET') opts.headers['X-Whisper-Box'] = '1';
  if (raw !== undefined) { opts.body = raw; opts.headers['Content-Type'] = 'application/octet-stream'; }
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  let res;
  try { res = await fetch(path, opts); }
  catch (e) { throw new ApiError('rede', 'Sem conexão com o painel local.', 0); }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (_) { /* sem corpo JSON */ }
  if (!res.ok) {
    const er = (data && data.error) || {};
    throw new ApiError(er.code || 'http_' + res.status, er.message || 'Falha HTTP ' + res.status, res.status, data || {});
  }
  return data;
}

/* ---------- copiar texto ---------- */
async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch (_) { /* tenta o fallback */ }
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  ta.remove();
  return ok;
}

/* ---------- saúde / faixa de aviso ---------- */
let saude = null;
let avisoKey = '';
function cmdButton(cmd) {
  const b = mk('button', 'cmd', cmd); b.type = 'button'; b.title = 'Tocar para copiar';
  b.addEventListener('click', async () => {
    const ok = await copyText(cmd);
    b.textContent = ok ? 'Copiado ✓' : 'Não foi possível copiar';
    setTimeout(() => { b.textContent = cmd; }, 2000);
  });
  return b;
}
function renderAviso() {
  const aviso = $('aviso');
  let key = 'ok';
  if (saude && saude.erro) key = 'painel';
  else if (saude && saude.worker === false) key = 'motor';
  else if (saude && saude.modelo === false) key = 'modelo';
  if (key === avisoKey) return;
  avisoKey = key;
  aviso.textContent = '';
  aviso.classList.toggle('err', key === 'painel');
  if (key === 'ok') { aviso.hidden = true; return; }
  const t = mk('div', 'txt');
  if (key === 'painel') t.append('Sem resposta do painel. Verifique se o contêiner está no ar.');
  else if (key === 'motor') t.append('Motor parado. Clique para copiar o comando: ', cmdButton('python whisper-box.py start'));
  else t.append('Modelo não preparado. Rode: ', cmdButton('python whisper-box.py prepare'));
  aviso.append(icon('alert', 16), t);
  aviso.hidden = false;
}
async function checkSaude() {
  if (Demo.ativo) { saude = { painel: true, worker: true, modelo: true }; renderAviso(); if (currentRoute === 'logs') renderDiag(); return; }
  try {
    saude = await api('GET', '/api/saude');
    log('Saúde: ' + JSON.stringify(saude));
  } catch (e) {
    saude = { erro: e.message };
    log('Falha ao consultar /api/saude', e.message);
  }
  renderAviso();
  if (currentRoute === 'logs') renderDiag();
}

/* ---------- estado da gravação ---------- */
// ocioso | iniciando | gravando | pausado | parando | parado | enviando
let state = 'ocioso';
let sess = null;      // captura + id da gravação + fila
let lastError = '';
let statusMsg = 'Pronto para gravar.';
const diagData = {};

const el = {
  timer: $('timer'), status: $('status'), erro: $('erro'), erroTxt: $('erroTxt'),
  rec: $('btnRec'), pause: $('btnPause'), stop: $('btnStop'), trans: $('btnTrans'), cancel: $('btnCancel'),
  confirm: $('confirm'), yes: $('btnConfirmYes'), no: $('btnConfirmNo'),
  micBtn: $('btnMic'), prog: $('prog')
};
let confirming = false;
let noDisplay = false;

function elapsedSec() {
  if (Demo.ativo) return state === 'gravando' || state === 'pausado' || state === 'parado' ? Demo.seg : 0;
  if (!sess) return 0;
  const ms = sess.accMs + (state === 'gravando' ? Date.now() - sess.t0 : 0);
  return Math.floor(ms / 1000);
}
function setState(s, msg) {
  state = s;
  if (msg !== undefined) statusMsg = msg;
  if (s !== 'gravando' && s !== 'pausado' && s !== 'parado') confirming = false;
  renderRec();
}
function setError(t) { lastError = t || ''; if (t) log('Erro na gravação', t); renderRec(); }

function focusPrimary() {
  const alvo = { ocioso: el.rec, gravando: el.pause, pausado: el.pause, parado: el.trans }[state];
  if (alvo && !alvo.hidden && !alvo.disabled) alvo.focus();
}
function renderRec() {
  const prev = document.activeElement;
  const wasIn = !!prev && prev !== document.body && $('v-gravar').contains(prev);
  const active = state === 'gravando' || state === 'pausado';
  const canCancel = active || state === 'parado';
  const showConfirm = confirming && canCancel;
  const micOn = state === 'ocioso' ? settings.mic : (sess ? sess.mic : settings.mic);

  $('zona').classList.toggle('alta', active || state === 'parado' || state === 'enviando' || state === 'parando');
  $('acoes').hidden = showConfirm;
  $('sub').hidden = showConfirm;
  el.confirm.hidden = !showConfirm;

  el.rec.hidden = state !== 'ocioso' && state !== 'iniciando';
  el.rec.disabled = noDisplay;
  el.rec.setAttribute('aria-disabled', String(state === 'iniciando'));
  setBtn(el.rec, state === 'iniciando' ? 'spin' : 'rec', 'Gravar');
  el.pause.hidden = !active;
  el.pause.classList.toggle('primary', state === 'pausado');
  setBtn(el.pause, state === 'pausado' ? 'play' : 'pause', state === 'pausado' ? 'Retomar' : 'Pausar');
  el.pause.title = (state === 'pausado' ? 'Retomar' : 'Pausar') + ' (Espaço)';
  el.stop.hidden = !active;
  setBtn(el.stop, 'stop', 'Parar');
  el.trans.hidden = !(state === 'parado' || state === 'enviando');
  el.trans.setAttribute('aria-disabled', String(state === 'enviando'));
  if (state === 'enviando') el.trans.setAttribute('aria-busy', 'true'); else el.trans.removeAttribute('aria-busy');
  setBtn(el.trans, state === 'enviando' ? 'spin' : '', state === 'enviando' ? 'Enviando…' : 'Transcrever');
  el.prog.hidden = state !== 'enviando';
  el.cancel.hidden = !canCancel || confirming;

  el.status.textContent = statusMsg;
  el.erro.hidden = !lastError;
  el.erroTxt.textContent = lastError;
  el.micBtn.setAttribute('aria-checked', String(micOn));
  el.micBtn.classList.toggle('off', !micOn);
  $('micOff').hidden = micOn;
  $('vuMic').hidden = !micOn;
  el.micBtn.disabled = state !== 'ocioso';
  el.micBtn.title = state === 'ocioso' ? 'Incluir o microfone na gravação' : 'Só dá para mudar antes de gravar';
  el.timer.textContent = fmtClock(elapsedSec());
  el.timer.classList.toggle('pausa', state === 'pausado');
  $('dica').hidden = !(state === 'ocioso' && mostrarDica());
  updateNav();
  updateTitle();

  // foco: nunca deixar o foco cair no body quando o botão focado some
  if (wasIn && !showConfirm && (prev.hidden || prev.disabled || prev.closest('[hidden]'))) focusPrimary();
}

/* aba Gravar mostra o estado da gravação em todas as rotas; document.title acompanha */
let navKey = '';
function updateNav() {
  const a = document.querySelector('[data-nav="gravar"]'), lbl = $('navGravarTxt');
  let key = '', txt = 'Gravar';
  if (state === 'gravando' || state === 'parando') { key = 'gravando'; txt = fmtClock(elapsedSec()); }
  else if (state === 'pausado') { key = 'pausa'; txt = 'Pausa ' + fmtClock(elapsedSec()); }
  else if (state === 'enviando') { key = 'enviando'; txt = 'Enviando'; }
  a.classList.toggle('rec', key === 'gravando' || key === 'pausa');
  a.classList.toggle('pausa', key === 'pausa');
  lbl.textContent = txt;
  if (key) lbl.setAttribute('aria-hidden', 'true'); else lbl.removeAttribute('aria-hidden');
  if (key !== navKey) {
    navKey = key;
    const nomes = { gravando: 'Gravar, gravando', pausa: 'Gravar, em pausa', enviando: 'Gravar, enviando' };
    if (key) a.setAttribute('aria-label', nomes[key]); else a.removeAttribute('aria-label');
  }
}
function updateTitle() {
  let t = 'Whisper Box';
  if (state === 'gravando' || state === 'parando') t = '● ' + fmtClock(elapsedSec()) + ' · Whisper Box';
  else if (state === 'pausado') t = '❚❚ ' + fmtClock(elapsedSec()) + ' · Whisper Box';
  else if (state === 'enviando') t = 'Enviando… · Whisper Box';
  if (document.title !== t) document.title = t;
}
function updateProgress() {
  if (state !== 'enviando' || !sess) return;
  const total = sess.q.nextSeq;
  const pct = total ? Math.max(0, Math.min(100, Math.floor((total - pending(sess.q)) / total * 100))) : 0;
  el.prog.firstElementChild.style.width = pct + '%';
  statusMsg = 'Enviando… ' + pct + '%';
  el.status.textContent = statusMsg;
}
let tick = 0;
setInterval(() => {
  tick++;
  if (state === 'gravando' || state === 'pausado') { el.timer.textContent = fmtClock(elapsedSec()); updateNav(); updateTitle(); }
  if (state === 'enviando' && tick % 2 === 0) updateProgress();
}, 500);

/* ---------- erros de captura (texto humano na tela; detalhe técnico só no log) ---------- */
function errMsg(e, ctx) {
  const n = (e && e.name) || 'Erro';
  log('Detalhe técnico (' + ctx + ')', n + (e && e.message ? ': ' + e.message : ''));
  const map = {
    NotAllowedError: ctx === 'mic' ? 'Microfone bloqueado. Libere o acesso nas configurações do site.' : 'Compartilhamento cancelado. Clique em Gravar e escolha Tela inteira com áudio do sistema.',
    NotFoundError: ctx === 'mic' ? 'Nenhum microfone encontrado.' : 'Nenhuma fonte de captura encontrada.',
    NotReadableError: 'Dispositivo em uso por outro aplicativo.',
    AbortError: 'A captura foi interrompida antes de iniciar.',
    NotSupportedError: 'Este navegador não captura áudio do sistema. Use Chrome ou Edge.',
    SecurityError: 'Abra o painel em http://127.0.0.1.',
    TypeError: 'Este navegador não captura áudio do sistema. Use Chrome ou Edge.',
    OverconstrainedError: 'O dispositivo não aceita as configurações de áudio pedidas.'
  };
  return map[n] || 'Falha inesperada.';
}
function pickMime() {
  if (typeof MediaRecorder === 'undefined') return null;
  for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

/* ---------- medidores (decorativos: aria-hidden; o status é anunciado à parte) ---------- */
function makeMeter(ctx, source, barId) {
  const an = ctx.createAnalyser(); an.fftSize = 1024;
  source.connect(an);
  const buf = new Float32Array(an.fftSize);
  const fill = $(barId).firstElementChild;
  return { update() {
    an.getFloatTimeDomainData(buf);
    let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const db = rms > 0 ? 20 * Math.log10(rms) : -100;
    const pct = Math.max(0, Math.min(100, (db + 60) / 60 * 100));
    fill.style.width = pct + '%'; fill.classList.toggle('hot', db > -6);
  } };
}
function resetMeters() {
  for (const id of ['vuSys', 'vuMic']) { const f = $(id).firstElementChild; f.style.width = '0'; f.classList.remove('hot'); }
}

/* ---------- fila de envio (sequencial, com retry) ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
function newQueue() { return { items: [], nextSeq: 0, running: false, failed: '', inflight: 0, waiters: [], lastSent: null }; }
function pending(q) { return q.items.length + q.inflight; }
function notifyQueue(q) {
  if (pending(q) === 0 || q.failed) { const w = q.waiters.splice(0); w.forEach(f => f()); }
}
function enqueue(s, blob) {
  const q = s.q;
  q.items.push({ seq: q.nextSeq++, blob });
  log('Pedaço #' + (q.nextSeq - 1) + ' (' + Math.round(blob.size / 1024) + ' KB) na fila');
  q.failed = '';
  pump(s);
}
async function pump(s) {
  const q = s.q;
  if (q.running) return;
  q.running = true;
  try {
    while (q.items.length && !s.dead) {
      const it = q.items[0];
      q.inflight = 1;
      const ok = await sendChunk(s, it);
      q.inflight = 0;
      if (!ok) break;
      q.items.shift();
    }
  } finally {
    q.inflight = 0; q.running = false; notifyQueue(q);
  }
}
async function sendChunk(s, it) {
  const q = s.q;
  const delays = [400, 800, 1600, 3200];
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    if (s.dead) return false;
    try {
      await api('PUT', '/api/gravacoes/' + s.id + '/pedacos/' + it.seq, undefined, it.blob);
      return true;
    } catch (e) {
      if (e.status === 409 && e.extra && typeof e.extra.esperado === 'number') {
        if (e.extra.esperado > it.seq) { log('Pedaço #' + it.seq + ' já estava gravado (esperado ' + e.extra.esperado + ')'); return true; }
        q.failed = 'Sequência inválida: servidor espera #' + e.extra.esperado + ' e o painel está em #' + it.seq + '.';
        log('Falha de sequência', q.failed); return false;
      }
      const transient = e.code === 'rede' || e.status >= 500 || e.status === 408 || e.status === 429;
      if (!transient) { q.failed = e.message; log('Pedaço #' + it.seq + ' recusado (' + e.code + ')', e.message); return false; }
      if (attempt === delays.length) { q.failed = e.message; log('Pedaço #' + it.seq + ' falhou após novas tentativas', e.message); return false; }
      log('Pedaço #' + it.seq + ' falhou (' + e.code + '); nova tentativa em ' + delays[attempt] + ' ms');
      await sleep(delays[attempt]);
    }
  }
  return false;
}
function drain(s) {
  const q = s.q;
  return new Promise(resolve => {
    if (pending(q) === 0 || q.failed) return resolve();
    q.waiters.push(resolve);
  });
}

/* ---------- captura ---------- */
async function startRecording() {
  if (state !== 'ocioso') return;
  forcarDica = false;
  setError('');
  if (!window.isSecureContext) { setError('Abra o painel em http://127.0.0.1.'); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { setError('Este navegador não captura áudio do sistema. Use Chrome ou Edge.'); return; }
  const mime = pickMime();
  if (mime === null) { setError('Este navegador não captura áudio do sistema. Use Chrome ou Edge.'); return; }
  setState('iniciando', 'Escolha o que compartilhar…');
  log('Solicitando captura (tela com áudio do sistema)');

  let disp = null, micStream = null;
  const releaseAll = () => {
    if (disp) disp.getTracks().forEach(t => t.stop());
    if (micStream) micStream.getTracks().forEach(t => t.stop());
  };
  try {
    disp = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      systemAudio: 'include', selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude', monitorTypeSurfaces: 'include'
    });
  } catch (e) { setState('ocioso', 'Não foi possível iniciar.'); setError(errMsg(e, 'display')); return; }
  disp.getVideoTracks().forEach(t => { t.stop(); disp.removeTrack(t); });
  const sysAudio = disp.getAudioTracks();
  if (!sysAudio.length) {
    releaseAll();
    forcarDica = true;
    setState('ocioso', 'Nenhum áudio do sistema recebido.');
    setError('Nenhum áudio do sistema foi compartilhado. Escolha Tela inteira e marque Compartilhar áudio do sistema.');
    return;
  }
  diagData.sysTracks = sysAudio.map(t => t.label || '(sem rótulo)').join('; ');
  log('Áudio do sistema: ' + diagData.sysTracks);

  if (settings.mic) {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      diagData.micTracks = micStream.getAudioTracks().map(t => t.label || '(sem rótulo)').join('; ');
      log('Microfone: ' + diagData.micTracks);
    } catch (e) {
      releaseAll(); setState('ocioso', 'Não foi possível iniciar.'); setError(errMsg(e, 'mic')); return;
    }
  } else { diagData.micTracks = '(desativado)'; }

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (_) { /* segue */ } }
  diagData.sr = ctx.sampleRate + ' Hz';
  const dest = ctx.createMediaStreamDestination();
  const sysSrc = ctx.createMediaStreamSource(disp); sysSrc.connect(dest);
  const meters = [makeMeter(ctx, sysSrc, 'vuSys')];
  if (micStream) { const ms = ctx.createMediaStreamSource(micStream); ms.connect(dest); meters.push(makeMeter(ctx, ms, 'vuMic')); }

  const opts = { audioBitsPerSecond: 48000 };
  if (mime) opts.mimeType = mime;
  let rec;
  try { rec = new MediaRecorder(dest.stream, opts); }
  catch (e) { releaseAll(); ctx.close().catch(() => {}); setState('ocioso', 'Não foi possível iniciar.'); log('Falha ao criar o gravador', e && e.message); setError('Não foi possível criar o gravador.'); return; }
  diagData.mime = rec.mimeType || mime || '(padrão do navegador)';
  log('MediaRecorder: ' + diagData.mime + ', 48 kbps, pedaços de 5 s, AudioContext ' + diagData.sr);

  // cria a gravação no servidor antes de iniciar
  let id;
  try {
    const r = await api('POST', '/api/gravacoes', { mime: diagData.mime });
    id = r.id;
    log('Gravação criada: ' + id);
  } catch (e) {
    releaseAll(); ctx.close().catch(() => {});
    log('Falha ao criar a gravação no painel', e.message);
    setState('ocioso', 'Não foi possível iniciar.');
    setError('Não foi possível iniciar a gravação no painel.');
    return;
  }

  const cur = { id, rec, ctx, disp, micStream, mic: !!micStream, meters, q: newQueue(), t0: Date.now(), accMs: 0, raf: 0, dead: false, reason: '', stopped: false };
  sess = cur;
  rec.ondataavailable = ev => { if (ev.data && ev.data.size > 0 && !cur.dead) enqueue(cur, ev.data); };
  rec.onerror = ev => { log('Erro no gravador', ev.error ? ev.error.name + ' ' + ev.error.message : 'desconhecido'); stopRecording('erro no gravador'); };
  rec.onstop = () => onRecorderStopped(cur);
  sysAudio[0].addEventListener('ended', () => {
    if (cur.stopped || cur.dead) return;
    log('Compartilhamento encerrado pelo navegador');
    stopRecording('compartilhamento encerrado');
  });

  rec.start(5000);
  cur.t0 = Date.now();
  log('Gravação iniciada');
  setState('gravando', 'Gravando. Mantenha a janela aberta.');
  const loop = () => { if (cur.dead || cur.stopped) return; meters.forEach(m => m.update()); cur.raf = requestAnimationFrame(loop); };
  loop();
}

function pauseResume() {
  if (!sess) return;
  if (state === 'gravando') {
    try { sess.rec.pause(); } catch (e) { log('Falha ao pausar', e.message); setError('Não foi possível pausar.'); return; }
    sess.accMs += Date.now() - sess.t0;
    log('Pausado');
    setState('pausado', 'Em pausa.');
  } else if (state === 'pausado') {
    try { sess.rec.resume(); } catch (e) { log('Falha ao retomar', e.message); setError('Não foi possível retomar.'); return; }
    sess.t0 = Date.now();
    log('Retomado');
    setState('gravando', 'Gravando. Mantenha a janela aberta.');
  }
}

function releaseCapture(s) {
  s.stopped = true;
  cancelAnimationFrame(s.raf);
  s.disp.getTracks().forEach(t => t.stop());
  if (s.micStream) s.micStream.getTracks().forEach(t => t.stop());
  s.ctx.close().catch(() => {});
  resetMeters();
}

function stopRecording(reason) {
  if (!sess || sess.stopped || (state !== 'gravando' && state !== 'pausado')) return;
  const s = sess;
  s.reason = reason || 'solicitado pelo usuário';
  if (state === 'gravando') s.accMs += Date.now() - s.t0;
  log('Parando (' + s.reason + ')');
  setState('parando', 'Finalizando…');
  if (s.rec.state !== 'inactive') {
    try { s.rec.stop(); } catch (e) { log('Falha ao parar o gravador', e.message); onRecorderStopped(s); }
  } else onRecorderStopped(s);
}

function msgParada(s) {
  return s && s.reason && s.reason !== 'solicitado pelo usuário' ? 'Parada: ' + s.reason + '.' : 'Parada. Pronta para transcrever.';
}
function onRecorderStopped(s) {
  if (s.finalized) return;
  s.finalized = true;
  releaseCapture(s);
  if (s.dead || sess !== s) return;
  const total = s.q.nextSeq;
  if (total === 0) {
    log('Gravação terminou sem dados');
    discardLocal();
    api('DELETE', '/api/gravacoes/' + s.id).catch(() => {});
    setState('ocioso', 'Gravação vazia.');
    setError('A gravação terminou sem dados.');
    return;
  }
  marcarDicaVista();
  setState('parado', msgParada(s));
}

function discardLocal() {
  if (sess) { sess.dead = true; sess.q.items.length = 0; sess.q.waiters.splice(0).forEach(f => f()); }
  sess = null;
  el.timer.textContent = '00:00';
}

async function cancelRecording() {
  confirming = false;
  const s = sess;
  if (!s) { setState('ocioso', 'Pronto para gravar.'); return; }
  log('Descartando gravação');
  s.dead = true;
  if (!s.stopped) {
    try { if (s.rec.state !== 'inactive') s.rec.stop(); } catch (_) { /* segue */ }
    releaseCapture(s);
  }
  s.finalized = true;
  s.q.items.length = 0;
  s.q.waiters.splice(0).forEach(f => f());
  sess = null;
  let msg = 'Gravação descartada.';
  try { await api('DELETE', '/api/gravacoes/' + s.id); }
  catch (e) { log('Falha ao apagar a gravação no servidor', e.message); msg = 'Descartada. O painel não confirmou a limpeza.'; }
  setError('');
  setState('ocioso', msg);
}

async function transcribe() {
  const s = sess;
  if (!s || state !== 'parado') return;
  setError('');
  setState('enviando', 'Enviando… 0%');
  s.q.failed = '';
  pump(s);
  updateProgress();
  await drain(s);
  if (s.q.failed) {
    log('Envio incompleto', s.q.failed);
    setState('parado', msgParada(s));
    setError('Falha ao enviar. Clique em Transcrever para tentar de novo.');
    return;
  }
  try {
    const r = await api('POST', '/api/gravacoes/' + s.id + '/transcrever', { language: 'auto' });
    log('Transcrição enfileirada: job ' + r.job_id + (r.reused ? ' (reaproveitado)' : ''));
    highlightJob = r.job_id; focarNovo = true;
    sess = null; s.dead = true;
    el.timer.textContent = '00:00';
    setState('ocioso', 'Pronto para gravar.');
    location.hash = '#/transcricoes';
  } catch (e) {
    log('Falha ao transcrever (' + e.code + ')', e.message);
    setState('parado', msgParada(s));
    setError(e.code === 'worker_unavailable' ? 'Motor parado. Inicie-o e clique em Transcrever.' : 'Não foi possível transcrever. Tente de novo.');
    checkSaude();
  }
}

/* ---------- transcrições ---------- */
let highlightJob = '';
let focarNovo = false;
let trTimer = 0;
let trLoaded = false;
let lastLista = [];
const fb = {};          // job_id -> { txt, err } (feedback curto)
const copiaModo = {};   // job_id -> true quando o ajudante falhou
const STATUS_PT = { queued: 'Na fila', running: 'Processando', succeeded: 'Concluída', failed: 'Falhou' };

function toDate(v) {
  if (v === null || v === undefined || v === '') return null;
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return isNaN(d.getTime()) ? null : d;
}
function fmtDate(v) {
  const d = toDate(v);
  if (!d) return '';
  return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}
function relDate(v) {
  const d = toDate(v);
  if (!d) return '';
  const now = new Date();
  const dia = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((dia(now) - dia(d)) / 86400000);
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  if (diff === 0) return 'hoje ' + hm;
  if (diff === 1) return 'ontem ' + hm;
  if (d.getFullYear() === now.getFullYear()) return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + ' ' + hm;
  return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear();
}
function fmtErr(er) { if (!er) return ''; if (typeof er === 'string') return er; return er.message || er.code || JSON.stringify(er); }

function showSkeleton() {
  const ul = $('trLista');
  ul.textContent = '';
  for (let i = 0; i < 3; i++) { const li = mk('li', 'sk'); li.append(mk('i'), mk('i')); ul.appendChild(li); }
  ul.setAttribute('aria-busy', 'true');
  $('trLive').textContent = 'Carregando transcrições';
}
async function loadTranscricoes() {
  clearTimeout(trTimer);
  if (currentRoute !== 'transcricoes') return;
  if (!trLoaded && !lastLista.length && !$('trLista').children.length) showSkeleton();
  let lista;
  try {
    const r = await api('GET', '/api/transcricoes');
    lista = r.transcricoes || [];
  } catch (e) {
    log('Falha ao listar transcrições', e.message);
    if (currentRoute !== 'transcricoes') return;
    $('trErro').hidden = false;
    $('trLista').classList.toggle('velha', trLoaded);
    if (!trLoaded) { $('trLista').textContent = ''; $('trLista').setAttribute('aria-busy', 'false'); $('trLive').textContent = ''; }
    trTimer = setTimeout(loadTranscricoes, 5000);
    return;
  }
  if (currentRoute !== 'transcricoes') return;
  trLoaded = true;
  $('trErro').hidden = true;
  $('trLista').classList.remove('velha');
  $('trLive').textContent = '';
  lastLista = lista;
  renderTranscricoes(lista);
  if (!Demo.ativo && lista.some(j => j.status === 'queued' || j.status === 'running')) trTimer = setTimeout(loadTranscricoes, 3000);
}
function showFb(jobId, txt, err) {
  fb[jobId] = { txt, err: !!err };
  $('trLive').textContent = txt;
  renderTranscricoes(lastLista);
  setTimeout(() => { if (fb[jobId] && fb[jobId].txt === txt) { delete fb[jobId]; if (currentRoute === 'transcricoes') renderTranscricoes(lastLista); } }, 3000);
}
const pastaBusy = {};
async function pastaAction(j) {
  if (pastaBusy[j.job_id]) return;
  pastaBusy[j.job_id] = true;
  try {
    if (helper.porta && !copiaModo[j.job_id]) {
      try {
        const res = await fetch('http://127.0.0.1:' + helper.porta + '/abrir-pasta', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Whisper-Box-Token': helper.token },
          body: JSON.stringify({ job_id: j.job_id })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        showFb(j.job_id, 'Pasta aberta');
        log('Pasta aberta: ' + j.job_id);
        return;
      } catch (e) {
        log('Ajudante falhou ao abrir a pasta de ' + j.job_id, e.message);
        copiaModo[j.job_id] = true;
        if (!j.pasta) { showFb(j.job_id, 'Não foi possível abrir a pasta', true); return; }
      }
    }
    if (j.pasta) {
      const ok = await copyText(j.pasta);
      showFb(j.job_id, ok ? 'Caminho copiado' : 'Não foi possível copiar', !ok);
    }
  } finally { pastaBusy[j.job_id] = false; }
}
function renderTranscricoes(lista) {
  const ul = $('trLista');
  // preserva o foco no botão de ação do mesmo job
  const ativo = document.activeElement;
  const focoJob = ativo && ativo.classList && ativo.classList.contains('acao') ? ativo.dataset.job : '';
  ul.textContent = '';
  ul.setAttribute('aria-busy', 'false');
  $('trVazio').hidden = lista.length > 0;
  for (const j of lista) {
    const nomeCompleto = j.source_name || j.job_id;
    const feedback = fb[j.job_id];
    const copiar = !helper.porta || copiaModo[j.job_id];
    const temAcao = j.status === 'succeeded' && (!!helper.porta || !!j.pasta);
    const li = mk('li', 'item' + (j.job_id === highlightJob ? ' novo' : '') + (temAcao ? ' tem-acao' : '') + (j.status === 'failed' ? ' falhou' : ''));
    li.dataset.job = j.job_id; li.tabIndex = -1;
    const nome = mk('div', 'nome', nomeCompleto.replace(/\.[^.]+$/, '') || nomeCompleto); nome.title = nomeCompleto;
    const pill = mk('span', 'pill ' + j.status);
    if (j.status === 'succeeded') pill.append(icon('check', 12));
    pill.append(STATUS_PT[j.status] || j.status);
    li.append(nome, pill);

    let infoTxt = '', infoCls = 'info', infoTitle = '';
    if (j.status === 'succeeded') {
      const a = toDate(j.started_at), b = toDate(j.finished_at);
      if (a && b && b >= a) { infoTxt = 'Transcrita em ' + fmtClock((b - a) / 1000); infoTitle = infoTxt; }
    } else if (j.status === 'running') infoTxt = (typeof j.progress_seconds === 'number' ? fmtClock(j.progress_seconds) : '00:00') + ' processados';
    else if (j.status === 'queued') infoTxt = 'Aguardando a vez';
    if (feedback) { infoTxt = feedback.txt; infoCls += feedback.err ? ' bad' : ' ok'; infoTitle = ''; }
    const info = mk('div', infoCls, infoTxt); if (infoTitle) info.title = infoTitle;
    li.appendChild(info);

    const d = toDate(j.created_at);
    if (d) { const t = mk('time', 'data', relDate(j.created_at)); t.dateTime = d.toISOString(); t.title = fmtDate(j.created_at); li.appendChild(t); }
    if (temAcao) {
      const rot = (copiar ? 'Copiar caminho de ' : 'Abrir pasta de ') + nomeCompleto.replace(/\.[^.]+$/, '');
      const btn = mk('button', 'btn icon acao'); btn.type = 'button'; btn.dataset.job = j.job_id;
      btn.setAttribute('aria-label', rot); btn.title = rot;
      btn.appendChild(icon(feedback && !feedback.err ? 'check' : (copiar ? 'copy' : 'folder'), 22));
      btn.addEventListener('click', () => { pastaAction(j); });
      li.appendChild(btn);
    }
    if (j.status === 'failed') { const m = mk('div', 'msg', fmtErr(j.error) || 'Falha na transcrição.'); m.title = m.textContent; li.appendChild(m); }
    if (j.status === 'running') li.appendChild(mk('div', 'ind'));
    ul.appendChild(li);
  }
  if (focoJob) { const b = ul.querySelector('button.acao[data-job="' + (window.CSS && CSS.escape ? CSS.escape(focoJob) : focoJob) + '"]'); if (b) b.focus(); }
  if (highlightJob && lista.some(j => j.job_id === highlightJob)) {
    const n = ul.querySelector('.novo');
    if (n) {
      if (n.scrollIntoView) n.scrollIntoView({ block: 'nearest' });
      if (focarNovo) { focarNovo = false; n.focus(); setTimeout(() => { if (highlightJob) { highlightJob = ''; const x = document.querySelector('.item.novo'); if (x) x.classList.remove('novo'); } }, 6000); }
    }
  }
}

/* ---------- logs / diagnóstico ---------- */
function navegadorResumo() {
  const ua = navigator.userAgent;
  let nav = 'Navegador';
  let m;
  if ((m = /Edg\/(\d+)/.exec(ua))) nav = 'Edge ' + m[1];
  else if ((m = /Chrome\/(\d+)/.exec(ua))) nav = 'Chrome ' + m[1];
  else if ((m = /Firefox\/(\d+)/.exec(ua))) nav = 'Firefox ' + m[1];
  else if ((m = /Version\/(\d+).*Safari/.exec(ua))) nav = 'Safari ' + m[1];
  const so = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return nav + (so ? ' · ' + so : '');
}
const tick2 = b => b ? '✓' : '✗';
function diagRows() {
  const gdm = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
  return [
    ['Navegador', navegadorResumo(), navigator.userAgent],
    ['Janela', window.innerWidth + ' × ' + window.innerHeight],
    ['Captura', 'Seguro ' + tick2(window.isSecureContext) + ' · getDisplayMedia ' + tick2(gdm) + ' · MediaRecorder ' + tick2(typeof MediaRecorder !== 'undefined')],
    ['Gravador', diagData.mime ? diagData.mime + (diagData.sr ? ' · ' + diagData.sr : '') : '—'],
    ['Faixas', 'sistema: ' + (diagData.sysTracks || '—') + '; microfone: ' + (diagData.micTracks || '—')],
    ['Ajudante', helper.porta ? 'configurado (porta ' + helper.porta + ')' : 'não configurado']
  ];
}
function renderSaude() {
  const p = $('saudeLinha'); p.textContent = '';
  const ponto = (ok, txtOk, txtBad) => {
    const s = mk('span', 'pt' + (ok === null ? '' : ok ? ' ok' : ' bad'), ok === null ? '—' : ok ? txtOk : txtBad);
    return s;
  };
  const semResp = !saude || saude.erro;
  p.append(
    ponto(saude ? !saude.erro : null, 'Painel ativo', 'Painel sem resposta'),
    ponto(semResp ? null : saude.worker !== false, 'Motor ativo', 'Motor parado'),
    ponto(semResp ? null : saude.modelo !== false, 'Modelo pronto', 'Modelo ausente')
  );
}
function renderDiag() {
  renderSaude();
  const dl = $('diag'); dl.textContent = '';
  for (const [k, v, title] of diagRows()) {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v; if (title) dd.title = title;
    dl.append(dt, dd);
  }
}
async function copyLog() {
  const rows = diagRows().map(r => r[0] + ': ' + (r[2] || r[1]));
  rows.push('/api/saude: ' + (saude ? JSON.stringify(saude) : '—'));
  const text = rows.join('\n') + '\n\n' + logs.map(logLine).join('\n');
  const btn = $('btnCopiar');
  let ok = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); ok = true; }
  } catch (_) { ok = false; }
  if (ok) { btn.textContent = 'Copiado ✓'; }
  else {
    const pre = $('logPre'); const r = document.createRange(); r.selectNodeContents(pre);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    btn.textContent = 'Selecionado: Ctrl+C';
  }
  setTimeout(() => { btn.textContent = 'Copiar log'; }, 2000);
}

/* ---------- microfone (interruptor na tela Gravar) ---------- */
function initMicToggle() {
  el.micBtn.addEventListener('click', () => {
    if (el.micBtn.disabled) return;
    settings.mic = !settings.mic;
    const ok = saveSettings();
    log('Microfone ' + (settings.mic ? 'incluído' : 'desligado') + (ok ? '' : ' (não foi possível salvar a preferência)'));
    renderRec();
  });
}

/* ---------- roteador ---------- */
const ROUTES = ['gravar', 'transcricoes', 'logs'];
const H1 = { gravar: 'h-gravar', transcricoes: 'h-tr', logs: 'h-logs' };
let currentRoute = '';
function route(fromUser) {
  const m = /^#\/([a-z]+)/.exec(location.hash);
  const r = m && ROUTES.includes(m[1]) ? m[1] : 'gravar';
  if (!m || r !== m[1]) { history.replaceState(null, '', location.pathname + location.search + '#/' + r); }
  clearTimeout(trTimer);
  currentRoute = r;
  document.querySelectorAll('.view').forEach(v => { v.hidden = v.dataset.rota !== r; });
  document.querySelectorAll('[data-nav]').forEach(a => {
    if (a.dataset.nav === r) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  if (r === 'transcricoes') loadTranscricoes();
  if (r === 'logs') { renderDiag(); renderLogs(true); }
  if (r === 'gravar') renderRec();
  checkSaude();
  if (r !== 'transcricoes') highlightJob = '';
  if (fromUser) { const h = $(H1[r]); if (h) h.focus(); }
}

/* ---------- eventos ---------- */
el.rec.addEventListener('click', () => {
  if (Demo.ativo || el.rec.getAttribute('aria-disabled') === 'true') return;
  startRecording().catch(e => { log('Falha inesperada ao iniciar', e && e.message); setState('ocioso', 'Não foi possível iniciar.'); setError(errMsg(e, 'display')); });
});
el.pause.addEventListener('click', () => { if (!Demo.ativo) pauseResume(); });
el.stop.addEventListener('click', () => { if (!Demo.ativo) stopRecording('solicitado pelo usuário'); });
el.trans.addEventListener('click', () => {
  if (Demo.ativo || el.trans.getAttribute('aria-disabled') === 'true') return;
  transcribe().catch(e => { log('Falha inesperada ao transcrever', e && e.message); setState('parado', msgParada(sess)); setError('Não foi possível transcrever. Tente de novo.'); });
});
el.cancel.addEventListener('click', () => { confirming = true; renderRec(); el.no.focus(); });
el.no.addEventListener('click', () => { confirming = false; renderRec(); el.cancel.focus(); });
el.yes.addEventListener('click', () => { if (!Demo.ativo) cancelRecording(); });
$('btnCopiar').addEventListener('click', copyLog);
window.addEventListener('hashchange', () => route(true));
window.addEventListener('resize', () => { if (currentRoute === 'logs') renderDiag(); });
window.addEventListener('beforeunload', e => {
  const ativo = sess && !sess.dead && (state === 'gravando' || state === 'pausado' || state === 'parando' || state === 'enviando' || (state === 'parado' && sess.q.nextSeq > 0) || pending(sess.q) > 0);
  if (ativo) { e.preventDefault(); e.returnValue = ''; }
});
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.defaultPrevented) return;
  if (e.altKey && !e.shiftKey && ['Digit1', 'Digit2', 'Digit3'].includes(e.code)) {
    e.preventDefault(); location.hash = '#/' + ROUTES[Number(e.code.slice(5)) - 1]; return;
  }
  if (e.key === 'Escape' && confirming) { e.preventDefault(); confirming = false; renderRec(); el.cancel.focus(); return; }
  if (e.code === 'Space' && !e.altKey && !e.shiftKey && !e.repeat && currentRoute === 'gravar' && !confirming) {
    const t = e.target;
    if (t && t.closest && t.closest('button,a,input,textarea,select,[role=switch],[contenteditable],summary')) return;
    if (state === 'ocioso') { e.preventDefault(); if (!el.rec.disabled) el.rec.click(); }
    else if (state === 'gravando' || state === 'pausado') { e.preventDefault(); el.pause.click(); }
  }
});

/* ---------- início ---------- */
loadSettings();
initHelper();
initMicToggle();
log('Painel carregado. Contexto seguro: ' + window.isSecureContext);
if (!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia)) {
  noDisplay = true;
  lastError = 'Este navegador não captura áudio do sistema. Use Chrome ou Edge.';
}
Demo.aplicar();
route(false);
setInterval(() => { if (state === 'ocioso' || state === 'parado') checkSaude(); }, 20000);
})();
