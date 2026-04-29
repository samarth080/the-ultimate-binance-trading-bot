// ── Config ────────────────────────────────────────────────────────────────────
const BASE   = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// ── Utility ───────────────────────────────────────────────────────────────────
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => n >= 1000 ? n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : n.toFixed(4);
const id  = x => document.getElementById(x);

// ── State ─────────────────────────────────────────────────────────────────────
const S = {
  orderType: 'market',
  sides: { m:'BUY', l:'BUY', o:'BUY', s:'BUY', t:'BUY' },
  logFilter: 'ALL',
  logs: [],
  currentView: 'overview',
  lastSignal: null,
};

// ── API ───────────────────────────────────────────────────────────────────────
const api = {
  async get(p) {
    const r = await fetch(BASE + p);
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  async post(p, body) {
    const r = await fetch(BASE + p, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
};

// ── Status polling ────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const d = await api.get('/api/status');
    id('net-dot').className = 'dot on';
    id('net-lbl').textContent = 'ONLINE';
    id('sb-api').textContent  = d.api_key_set ? 'API: OK' : 'API: NO KEY';
    let modeText = d.testnet ? 'TESTNET' : 'MAINNET';
    if (d.mode === 'paper') modeText += ' [PAPER TRADING]';
    id('sb-mode').textContent = 'MODE: ' + modeText;
    id('sb-ts').textContent   = new Date().toLocaleTimeString();
  } catch {
    id('net-dot').className = 'dot';
    id('net-lbl').textContent = 'OFFLINE';
  }
}

async function pollRisk() {
  try {
    const d = await api.get('/api/risk/status');
    const pnl = d.daily_pnl || 0;
    const pos  = d.open_positions || 0;
    const halt = d.halted ? ' ⚠ HALTED' : '';
    id('sb-risk').textContent = `PnL:${pnl>=0?'+':''}${pnl.toFixed(2)} POS:${pos}${halt}`;
    id('sb-risk').style.color = halt ? 'var(--sell)' : (pnl >= 0 ? 'var(--buy)' : 'var(--sell)');
  } catch {
    id('sb-risk').textContent = 'RISK: —';
  }
}

pollStatus(); setInterval(pollStatus, 15000);
pollRisk();   setInterval(pollRisk, 30000);

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws = null;
function connectWS() {
  if (ws && ws.readyState < 2) return;
  ws = new WebSocket(WS_URL);
  ws.onopen = () => { setWS(true); setAction('WebSocket connected'); };
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.type === 'init') m.data.forEach(addLog);
    else if (m.type === 'log') addLog(m.data);
    if (typeof m.upnl === "number") {
      var upnlEl = document.getElementById("upnl-val");
      upnlEl.textContent = (m.upnl >= 0 ? "+" : "") + "$" + m.upnl.toFixed(2);
      upnlEl.style.color = m.upnl >= 0 ? "#0f0" : "#f44";
    }
  };
  ws.onclose = () => { setWS(false); setTimeout(connectWS, 3000); };
  ws.onerror = () => ws.close();
}
function setWS(on) {
  id('ws-dot').className = 'dot' + (on ? ' on' : '');
  id('ws-lbl').textContent = on ? 'WS:ON' : 'WS:OFF';
}
connectWS();

// ── Logs ──────────────────────────────────────────────────────────────────────
function addLog(e) {
  S.logs.push(e);
  if (S.logs.length > 500) S.logs.shift();
  id('log-count').textContent = S.logs.length + ' ENTRIES';
  if (S.logFilter !== 'ALL' && e.level !== S.logFilter) return;
  appendLogDOM(e);
}
function appendLogDOM(e) {
  const body = id('logbody');
  const load = body.querySelector('.loading-msg');
  if (load) load.remove();
  const d = document.createElement('div');
  d.className = 'lentry ' + e.level;
  d.innerHTML = `<span class="lts">${esc(e.ts)}</span><span class="llvl ${e.level}">${e.level.slice(0,4)}</span><span class="lmsg">${esc(e.msg)}</span>`;
  body.appendChild(d);
  while (body.children.length > 200) body.removeChild(body.firstChild);
  body.scrollTop = body.scrollHeight;
}
function rebuildLogs() {
  const body = id('logbody');
  body.innerHTML = '';
  const list = S.logFilter === 'ALL' ? S.logs : S.logs.filter(l => l.level === S.logFilter);
  list.slice(-120).forEach(appendLogDOM);
  if (!list.length) body.innerHTML = `<div class="loading-msg">NO ${S.logFilter} ENTRIES</div>`;
}
document.querySelectorAll('.lfbtn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.lfbtn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  S.logFilter = b.dataset.lv;
  rebuildLogs();
}));

// ── Centre panel tabs ─────────────────────────────────────────────────────────
document.querySelectorAll('.ctab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.ctab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.cview').forEach(x => { x.classList.remove('active'); x.style.display = ''; });
  t.classList.add('active');
  S.currentView = t.dataset.view;
  const _activeView = id('view-' + S.currentView);
  _activeView.classList.add('active');
  if (S.currentView === 'overview') _activeView.style.display = 'grid';
  // Toggle controls
  ['analytics','signal','stats','scanner'].forEach(v => {
    const ctrl = id('ctrl-' + v);
    if (ctrl) ctrl.style.display = (v === S.currentView) ? 'flex' : 'none';
  });
  // News view needs flex layout
  const newsView = id('view-news');
  if (newsView) newsView.style.display = (S.currentView === 'news') ? 'flex' : 'none';
  // Auto-load data when switching tabs
  if (S.currentView === 'overview') loadOverview();
  if (S.currentView === 'stats')    loadStats();
  if (S.currentView === 'news')     loadNews();
  if (S.currentView === 'scanner')  loadScanner();
}));

// ── Order tabs ────────────────────────────────────────────────────────────────
document.querySelectorAll('.otab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.otab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.oform').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  S.orderType = t.dataset.type;
  id('form-' + S.orderType).classList.add('active');
  syncExecBtn();
  hideResult();
}));

// ── Side buttons ──────────────────────────────────────────────────────────────
document.querySelectorAll('.sbtn').forEach(b => b.addEventListener('click', () => {
  const f = b.dataset.form;
  document.querySelectorAll(`.sbtn[data-form="${f}"]`).forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  S.sides[f] = b.dataset.side;
  syncExecBtn();
}));
function syncExecBtn() {
  const map  = { market:'m', limit:'l', oco:'o', stop_limit:'s', twap:'t' };
  const side = S.sides[map[S.orderType]] || 'BUY';
  const btn  = id('btn-exec');
  btn.className = 'btn btn-exec ' + side.toLowerCase();
  btn.textContent = side;
}
function setSide(form, side) {
  document.querySelectorAll(`.sbtn[data-form="${form}"]`).forEach(b => {
    b.classList.toggle('active', b.dataset.side === side);
  });
  S.sides[form] = side;
}

// ── Order submission ──────────────────────────────────────────────────────────
id('btn-exec').addEventListener('click', () => submitOrder(false));
id('btn-dry').addEventListener('click',  () => submitOrder(true));

function getPayload(dry) {
  const t   = S.orderType;
  const map = { market:'m', limit:'l', oco:'o', stop_limit:'s', twap:'t' };
  const f   = map[t];
  const side = S.sides[f];
  const g = i => (id(i)||{}).value || '';
  const n = i => parseFloat(g(i)) || 0;
  if (t==='market')     return { symbol:g('m-sym').toUpperCase(), side, quantity:n('m-qty'), dry_run:dry };
  if (t==='limit')      return { symbol:g('l-sym').toUpperCase(), side, quantity:n('l-qty'), price:n('l-price'), dry_run:dry };
  if (t==='oco')        return { symbol:g('o-sym').toUpperCase(), side, quantity:n('o-qty'), price:n('o-price'), stop_price:n('o-stop'), stop_limit_price:n('o-slim'), dry_run:dry };
  if (t==='stop_limit') return { symbol:g('s-sym').toUpperCase(), side, quantity:n('s-qty'), stop_price:n('s-stop'), price:n('s-price'), dry_run:dry };
  if (t==='twap')       return { symbol:g('t-sym').toUpperCase(), side, total_quantity:n('t-qty'), parts:parseInt(g('t-parts'))||5, interval_seconds:parseInt(g('t-int'))||60, dry_run:dry };
}

async function submitOrder(dry) {
  const pl = getPayload(dry);
  const t  = S.orderType;
  setAction(`${dry?'Validating':'Placing'} ${t.toUpperCase()}…`);
  hideResult();
  try {
    const res = await api.post(`/api/order/${t}`, pl);
    if (dry) {
      const checks = Object.entries(res).filter(([k]) => !['dry_run','plan'].includes(k)).map(([k,v]) => `${k}: ${v?'✓':'✗'}`).join('\n');
      showResult('info', `DRY RUN OK\n${res.plan||checks}`);
    } else {
      const oid = res.order?.orderId || res.order?.orderListId || '—';
      showResult('ok', `ORDER SUBMITTED\nID: ${oid}\nStatus: ${res.order?.status||'SUBMITTED'}`);
      // Refresh stats in background so Trade Stats tab is up-to-date
      loadStats();
    }
    setAction(`Last: ${t.toUpperCase()}${dry?' (dry)':''}`);
  } catch(err) {
    showResult('err', `FAILED\n${err.message}`);
    setAction('Error: ' + err.message);
  }
}
function showResult(cls, txt) {
  const el = id('oresult');
  el.className = 'oresult show ' + cls;
  el.textContent = txt;
}
function hideResult() { id('oresult').className = 'oresult'; }

// ── Overview ────────────────────────────────────────────────────────────────────────────────
async function loadOverview() {
  try {
    const [stats, risk, kelly, news] = await Promise.all([
      api.get('/api/stats'),
      api.get('/api/risk/status'),
      api.get('/api/kelly'),
      api.get('/api/news?limit=3'),
    ]);
    _renderOvHealth(stats, risk);
    _renderOvRisk(risk, kelly);
    _renderOvPositions(stats);
    _renderOvSignal();
    _renderOvNews(news);
  } catch(e) { /* individual helpers show empty state on failure */ }
}

function _renderOvHealth(stats, risk) {
  const s        = stats.stats || {};
  const pnl      = s.total_pnl || 0;
  const upnl     = stats.total_unrealised || 0;
  const wr       = s.win_rate || 0;
  const halted   = risk.halted;
  const dailyLoss = Math.abs((risk.daily_pnl || 0) < 0 ? (risk.daily_pnl || 0) : 0);
  const equity    = risk.equity || 10000;
  const lossUsed  = dailyLoss / (equity * 0.05);
  const lossPct   = Math.min(100, lossUsed * 100);

  const badge = id('ov-halt-badge');
  badge.textContent = halted ? 'HALTED' : 'ACTIVE';
  badge.className   = 'ov-badge ' + (halted ? 'halt' : 'ok');

  id('ov-daily-pnl').textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
  id('ov-daily-pnl').style.color = pnl >= 0 ? 'var(--buy)' : 'var(--sell)';
  id('ov-daily-pct').textContent = ((pnl / equity) * 100).toFixed(2) + '% today';

  id('ov-upnl').textContent = (upnl >= 0 ? '+' : '') + '$' + upnl.toFixed(2);
  id('ov-upnl').style.color = upnl >= 0 ? 'var(--buy)' : 'var(--sell)';
  id('ov-pos-count').textContent = (stats.open_positions || 0) + ' position' + ((stats.open_positions || 0) !== 1 ? 's' : '');

  id('ov-winrate').textContent   = wr.toFixed(1) + '%';
  id('ov-winrate').style.color   = wr >= 55 ? 'var(--buy)' : wr >= 45 ? 'var(--amber)' : 'var(--sell)';
  id('ov-wl').textContent        = (s.wins || 0) + 'W / ' + (s.losses || 0) + 'L';

  const fill = id('ov-loss-fill');
  fill.style.width  = lossPct + '%';
  fill.className    = 'ov-loss-bar-fill' + (lossPct >= 80 ? ' danger' : lossPct >= 50 ? ' warn' : '');
  const remain      = Math.max(0, 100 - lossPct).toFixed(0);
  id('ov-loss-remain').textContent = remain + '% remaining';
  id('ov-loss-remain').style.color = lossPct >= 80 ? 'var(--sell)' : lossPct >= 50 ? 'var(--amber)' : 'var(--buy)';
}

function _renderOvRisk(risk, kelly) {
  const halted    = risk.halted;
  const positions = risk.open_positions || 0;
  const maxPos    = risk.max_positions  || 10;
  const drawdown  = risk.drawdown_pct   || 0;
  const dailyPnl  = risk.daily_pnl     || 0;
  const kellySize = kelly.next_size_usdt;

  const riskBadge = id('ov-risk-badge');
  riskBadge.textContent = halted ? 'HALTED' : positions >= maxPos - 2 ? 'NEAR LIMIT' : 'OK';
  riskBadge.className   = 'ov-badge ' + (halted ? 'halt' : positions >= maxPos - 2 ? 'warn' : 'ok');

  id('ov-open-pos').textContent  = positions + ' / ' + maxPos;
  id('ov-open-pos').style.color  = positions >= maxPos - 2 ? 'var(--amber)' : 'var(--text-hi)';

  id('ov-drawdown').textContent  = drawdown.toFixed(2) + '%';
  id('ov-drawdown').style.color  = drawdown >= 8 ? 'var(--sell)' : drawdown >= 5 ? 'var(--amber)' : 'var(--buy)';

  id('ov-daily-loss').textContent = (dailyPnl >= 0 ? '+' : '') + dailyPnl.toFixed(2);
  id('ov-daily-loss').style.color = dailyPnl >= 0 ? 'var(--buy)' : 'var(--sell)';

  id('ov-kelly-size').textContent = kellySize ? '$' + parseFloat(kellySize).toFixed(0) + ' USDT' : '—';
}

function _renderOvPositions(stats) {
  const trades = stats.open_trades      || [];
  const upnl   = stats.total_unrealised || 0;

  const total = id('ov-unreal-total');
  total.textContent = trades.length > 0
    ? 'unrealised ' + (upnl >= 0 ? '+' : '') + '$' + upnl.toFixed(2)
    : '';
  total.style.color = upnl >= 0 ? 'var(--buy)' : 'var(--sell)';

  const body = id('ov-positions-body');
  if (!trades.length) {
    body.innerHTML = '<div class="ov-empty">No open positions</div>';
    return;
  }

  body.innerHTML = trades.map(t => {
    const isLong  = t.direction === 'LONG';
    const dirClr  = isLong ? 'var(--buy)' : 'var(--sell)';
    const pnlClr  = (t.unrealised_pnl || 0) >= 0 ? 'var(--buy)' : 'var(--sell)';
    const pnlTxt  = t.unrealised_pnl != null
      ? (t.unrealised_pnl >= 0 ? '+' : '') + '$' + t.unrealised_pnl.toFixed(2)
      : '—';
    const markTxt  = t.current ? fmt(t.current) : '—';
    const entryTxt = t.entry   ? fmt(t.entry)   : '—';
    return '<div class="ov-pos-row">'
      + '<span style="color:' + dirClr + '">' + (isLong ? '▲' : '▼') + '</span>'
      + '<span style="color:var(--amber)">' + esc(t.symbol) + '</span>'
      + '<span>' + entryTxt + '</span>'
      + '<span style="color:var(--gold)">' + markTxt + '</span>'
      + '<span style="color:' + pnlClr + '">' + pnlTxt + '</span>'
      + '<button class="ov-close-btn" data-symbol="' + esc(t.symbol) + '" data-direction="' + esc(t.direction) + '" data-qty="' + esc(String(t.quantity || '')) + '">CLOSE</button>'
      + '</div>';
  }).join('');

  body.querySelectorAll('.ov-close-btn').forEach(btn => {
    btn.addEventListener('click', () => _closePosition(btn));
  });
}

function _renderOvSignal() {
  const d    = S.lastSignal;
  const body = id('ov-signal-body');
  const age  = id('ov-signal-age');

  if (!d || !d.has_signal) {
    body.innerHTML = '<div class="ov-empty">No active signal — run Signal Engine tab to scan</div>';
    age.textContent = '';
    return;
  }

  const isLong = d.direction === 'LONG';
  const dirClr = isLong ? 'var(--buy)' : 'var(--sell)';
  const rrRaw  = d.stop_loss && d.take_profit && d.price
    ? Math.abs(d.take_profit - d.price) / Math.abs(d.price - d.stop_loss) : 0;

  age.textContent = 'from signal engine scan';

  body.innerHTML = '<div class="ov-sig-card">'
    + '<div class="ov-sig-dir" style="color:' + dirClr + '">' + (isLong ? '▲' : '▼') + '</div>'
    + '<div class="ov-sig-meta">'
    +   '<div><span class="ov-sig-sym">' + esc(d.symbol) + '</span>'
    +   ' <span style="color:' + dirClr + '">' + esc(d.direction) + '</span>'
    +   ' <span style="color:var(--text-dim)">· ' + esc(d.primary_tf || '') + '/' + esc(d.confirm_tf || '') + '</span></div>'
    +   '<div class="ov-sig-sub">' + d.confidence + '% confluence · R:R ' + rrRaw.toFixed(2)
    +   ' · SL ' + (d.stop_loss ? fmt(d.stop_loss) : '—')
    +   ' · TP ' + (d.take_profit ? fmt(d.take_profit) : '—') + '</div>'
    + '</div>'
    + '<button class="ov-apply-btn" id="ov-apply-btn">→ APPLY</button>'
    + '</div>';

  id('ov-apply-btn').addEventListener('click', applySignalToOrder);
}

function _renderOvNews(news) {
  const items = (news && news.items) ? news.items : [];
  const body  = id('ov-news-body');
  const badge = id('ov-news-badge');

  const agg = items.reduce((s, n) => s + (n.score || 0), 0);
  badge.textContent = agg > 10 ? 'BULLISH +' + agg : agg < -10 ? 'BEARISH ' + agg : 'NEUTRAL ' + (agg >= 0 ? '+' : '') + agg;
  badge.className   = 'ov-badge ' + (agg > 10 ? 'ok' : agg < -10 ? 'halt' : 'warn');

  if (!items.length) {
    body.innerHTML = '<div class="ov-empty">News engine disabled or no articles yet</div>';
    return;
  }

  body.innerHTML = items.slice(0, 3).map(n => {
    const scoreVal   = n.score || 0;
    const scoreStr   = (scoreVal >= 0 ? '+' : '') + scoreVal;
    const scoreColor = scoreVal >= 30 ? 'var(--buy)' : scoreVal <= -30 ? 'var(--sell)' : 'var(--amber)';
    return '<div class="ov-news-row">'
      + '<span class="ov-news-badge ' + esc(n.sentiment) + '">' + esc(n.sentiment) + '</span>'
      + '<span class="ov-news-title">' + esc(n.title) + '</span>'
      + '<span class="ov-news-score" style="color:' + scoreColor + '">' + scoreStr + '</span>'
      + '</div>';
  }).join('');
}

async function _closePosition(btn) {
  const symbol    = btn.dataset.symbol;
  const direction = btn.dataset.direction;
  const qty       = parseFloat(btn.dataset.qty);
  const closeSide = direction === 'LONG' ? 'SELL' : 'BUY';

  if (!symbol || !qty || isNaN(qty)) {
    btn.textContent = 'ERR';
    setTimeout(() => { btn.textContent = 'CLOSE'; }, 2000);
    return;
  }
  if (!window.confirm('Close ' + direction + ' ' + symbol + '? Places a live ' + closeSide + ' order.')) return;

  btn.textContent = '…';
  btn.disabled    = true;

  try {
    await api.post('/api/order/market', { symbol, side: closeSide, quantity: qty, dry_run: false });
    btn.textContent   = 'CLOSED';
    btn.style.color   = 'var(--buy)';
    setTimeout(() => loadOverview(), 2000);
  } catch(e) {
    btn.textContent = 'FAIL';
    btn.disabled    = false;
    btn.style.color = 'var(--sell)';
    setTimeout(() => { btn.textContent = 'CLOSE'; btn.style.color = ''; }, 3000);
    setAction('Close failed: ' + e.message);
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────
async function loadAnalytics() {
  const sym  = id('a-sym').value;
  const intv = id('a-int').value;
  const btn  = id('rfbtn');
  btn.classList.add('spin'); btn.textContent = '…';
  try {
    const d = await api.get(`/api/ml/analyze?symbol=${sym}&interval=${intv}`);
    renderAnalytics(d);
    updateTicker(d);
    setAction(`Analytics: ${sym}`);
  } catch(err) {
    id('abody').innerHTML = `<div style="padding:20px;color:var(--sell);font-size:11px;line-height:2">✗ LOAD FAILED<br><span style="color:var(--text-dim)">${esc(err.message)}</span></div>`;
    setAction('Analytics error: ' + err.message);
  } finally {
    btn.classList.remove('spin'); btn.textContent = 'REFRESH';
  }
}

function updateTicker(d) {
  const pe = id('tick-price');
  const oldRaw = pe.textContent.replace(/[$,]/g,'');
  pe.textContent = '$' + fmt(d.price);
  if (!isNaN(parseFloat(oldRaw))) {
    const dir = d.price > parseFloat(oldRaw) ? 'flash-up' : 'flash-down';
    pe.classList.add(dir);
    setTimeout(() => pe.classList.remove('flash-up','flash-down'), 900);
  }
  const c = d.price_change_pct;
  const ce = id('tick-chg');
  ce.textContent = (c>=0?'+':'')+c.toFixed(2)+'%';
  ce.className = 'tick-chg ' + (c>=0?'pos':'neg');
}

function renderAnalytics(d) {
  const I = d.indicators, Si = d.signals;
  const pct = d.price_change_pct;
  const rsiPct  = Math.min(100,Math.max(0,I.rsi));
  const bbRange = I.bb_upper - I.bb_lower;
  const bbPos   = bbRange>0 ? Math.min(98,Math.max(2,((d.price-I.bb_lower)/bbRange)*100)) : 50;

  // Mini sparkline
  const sparkline = d.candles ? (() => {
    const cs = d.candles, mn = Math.min(...cs.map(c=>c.l)), mx = Math.max(...cs.map(c=>c.h)), rng = mx-mn||1;
    const W=600, H=110, pts = cs.map((c,i)=>`${i*(W/(cs.length-1))},${H-(c.c-mn)/rng*H}`).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="var(--amber)" stroke-width="1.5" opacity=".8"/>`;
  })() : '';

  const sigClass = (s) => {
    const m = { BULLISH:'bull', BEARISH:'bear', OVERBOUGHT:'overbought', OVERSOLD:'oversold', NEUTRAL:'neutral', HIGH:'high', LOW:'low', NORMAL:'normal' };
    return m[s] || 'neutral';
  };

  const bulls = ['BULLISH','OVERSOLD'].filter(x=>Object.values(Si).includes(x)).length;
  const bears = ['BEARISH','OVERBOUGHT'].filter(x=>Object.values(Si).includes(x)).length;
  const bias  = bulls > bears ? 'bull' : (bears > bulls ? 'bear' : 'neut');
  const biasLabel = bulls > bears ? 'BULLISH BIAS' : (bears > bulls ? 'BEARISH BIAS' : 'NEUTRAL');
  const biasIcon  = bulls > bears ? '▲' : (bears > bulls ? '▼' : '◆');
  const biasSub   = bulls > bears ? 'Consider long positions' : (bears > bulls ? 'Consider short positions' : 'Wait for clearer signals');

  const maItem = (lbl, val, cur) => {
    const cl = val && cur > val ? 'style="color:var(--buy)"' : 'style="color:var(--sell)"';
    return `<div class="ma-item"><div class="ma-lbl">${lbl}</div><div class="ma-val" ${cl}>${val?fmt(val):'—'}</div></div>`;
  };

  id('abody').innerHTML = `
    <div class="analytics-body">
      <div class="price-block">
        <div class="price-top"><span class="price-sym">${d.symbol}</span><span class="price-ts">${new Date(d.ts).toLocaleTimeString()}</span></div>
        <div class="price-main ${pct>=0?'up':'down'}">$${fmt(d.price)}</div>
        <div class="price-chg ${pct>=0?'pos':'neg'}">${pct>=0?'+':''}${pct.toFixed(2)}%</div>
      </div>
      <div class="chart-block">
        <div class="sect-label">PRICE ACTION (30 candles)</div>
        <svg id="chart" viewBox="0 0 600 110" preserveAspectRatio="none">${sparkline}</svg>
      </div>
      <div class="sect-label">MOVING AVERAGES</div>
      <div class="ma-grid">
        ${maItem('SMA 5', I.sma_5, d.price)}
        ${maItem('SMA 10', I.sma_10, d.price)}
        ${maItem('SMA 20', I.sma_20, d.price)}
        ${maItem('EMA 12', I.ema_12, d.price)}
        ${maItem('EMA 26', I.ema_26, d.price)}
      </div>
      <div class="ind-grid">
        <div class="ind-card">
          <div class="ind-name">RSI (14)</div>
          <div class="ind-val" style="color:${I.rsi>70?'var(--sell)':I.rsi<30?'var(--buy)':'var(--text-hi)'}">${I.rsi.toFixed(1)}</div>
          <div class="bar-wrap"><div class="bar ${I.rsi>70?'r':I.rsi<30?'g':''}" style="width:${rsiPct}%"></div></div>
        </div>
        <div class="ind-card">
          <div class="ind-name">MACD</div>
          <div class="ind-val" style="color:${I.macd>=0?'var(--buy)':'var(--sell)'}">${I.macd>=0?'+':''}${I.macd.toFixed(2)}</div>
          <div class="bar-wrap"><div class="bar ${I.macd>=0?'g':'r'}" style="width:${Math.min(100,Math.abs(I.macd)/d.price*5000)}%"></div></div>
        </div>
        <div class="ind-card">
          <div class="ind-name">BB UPPER</div>
          <div class="ind-val">$${fmt(I.bb_upper)}</div>
        </div>
        <div class="ind-card">
          <div class="ind-name">BB LOWER</div>
          <div class="ind-val">$${fmt(I.bb_lower)}</div>
        </div>
      </div>
      <div class="sect-label" style="margin-bottom:4px;">BB POSITION</div>
      <div class="bb-vis" style="margin-bottom:16px">
        <div class="bb-inner" style="left:0;right:0"></div>
        <div class="bb-pin"   style="left:${bbPos}%"></div>
      </div>
      <div class="sect-label">TRADING SIGNALS</div>
      <div class="sig-grid">
        <div class="sig-card"><span class="sig-lbl">SMA·5</span><span class="sig-val ${sigClass(Si.sma5)}">${Si.sma5}</span></div>
        <div class="sig-card"><span class="sig-lbl">SMA·20</span><span class="sig-val ${sigClass(Si.sma20)}">${Si.sma20}</span></div>
        <div class="sig-card"><span class="sig-lbl">RSI</span><span class="sig-val ${sigClass(Si.rsi)}">${Si.rsi}</span></div>
        <div class="sig-card"><span class="sig-lbl">MACD</span><span class="sig-val ${sigClass(Si.macd)}">${Si.macd}</span></div>
        <div class="sig-card"><span class="sig-lbl">BOLL BAND</span><span class="sig-val ${sigClass(Si.bb)}">${Si.bb}</span></div>
        <div class="sig-card"><span class="sig-lbl">VOLUME</span><span class="sig-val ${sigClass(Si.volume)}">${Si.volume}</span></div>
      </div>
      <div class="sect-label" style="margin-top:16px;">MACHINE LEARNING: RANDOM FOREST</div>
      <div class="assess" style="background:var(--bg-raised); border:1px solid var(--border); padding:14px; margin-bottom:16px;">
        <div class="a-icon ${d.ml_action === 'BULLISH' ? 'bull' : (d.ml_action === 'BEARISH' ? 'bear' : 'neut')}">
          ${d.ml_action === 'BULLISH' ? '▲' : (d.ml_action === 'BEARISH' ? '▼' : '◆')}
        </div>
        <div style="flex:1">
          <div class="a-lbl ${d.ml_action === 'BULLISH' ? 'bull' : (d.ml_action === 'BEARISH' ? 'bear' : 'neut')}">
             ${d.ml_action} PROBABILITY
          </div>
          <div class="a-sub" style="display:flex; justify-content:space-between; margin-bottom:6px;">
             <span>Probability Score:</span>
             <span style="font-weight:700; color:var(--text-hi)">${d.ml_probability}%</span>
          </div>
          <div class="bar-wrap" style="height:6px; background:var(--bg-hover); border-radius:3px;">
             <div class="bar ${d.ml_probability > 50 ? 'g' : 'r'}" style="width:${d.ml_probability}%"></div>
          </div>
        </div>
      </div>
      <div class="assess">
        <div class="a-icon ${bias}">${biasIcon}</div>
        <div>
          <div class="a-lbl ${bias}">${biasLabel}</div>
          <div class="a-sub">${biasSub}</div>
        </div>
      </div>
    </div>`;
}

id('rfbtn').addEventListener('click', loadAnalytics);
id('a-sym').addEventListener('change', loadAnalytics);
id('a-int').addEventListener('change', loadAnalytics);
loadAnalytics();
setInterval(loadAnalytics, 30000);

// ── Signal Engine ─────────────────────────────────────────────────────────────
async function runSignalScan() {
  const sym   = id('sig-sym').value;
  const ptf   = id('sig-ptf').value;
  const ctf   = id('sig-ctf').value;
  const btn   = id('sig-scan-btn');
  btn.classList.add('spin'); btn.textContent = '…';
  id('sig-body').innerHTML = '<div class="loading-msg">RUNNING MULTI-TIMEFRAME ANALYSIS<span class="cursor"></span></div>';
  try {
    const d = await api.get(`/api/signal?symbol=${sym}&primary_tf=${ptf}&confirm_tf=${ctf}`);
    S.lastSignal = d;
    renderSignal(d);
    setAction(`Signal scan: ${sym} ${ptf}/${ctf}`);
  } catch(err) {
    id('sig-body').innerHTML = `<div style="padding:20px;color:var(--sell);font-size:11px">${esc(err.message)}</div>`;
  } finally {
    btn.classList.remove('spin'); btn.textContent = 'SCAN';
  }
}

function renderSignal(d) {
  if (!d.has_signal) {
    id('sig-body').innerHTML = `
      <div style="padding:16px;">
        <div class="no-signal">
          <span>◈</span>
          NO HIGH-CONFIDENCE SIGNAL<br>
          <span style="font-size:10px;color:var(--text-dim)">${esc(d.symbol)} ${esc(d.primary_tf)}/${esc(d.confirm_tf)}</span><br>
          <span style="font-size:10px;color:var(--text-dim)">${esc(d.message||'')}</span>
        </div>
      </div>`;
    return;
  }

  const isLong   = d.direction === 'LONG';
  const dirClass = isLong ? 'long' : 'short';
  const confPct  = d.confidence;
  const fillCls  = confPct >= 75 ? 'high' : confPct >= 55 ? 'med' : 'low';
  const rrRaw    = d.stop_loss && d.take_profit && d.price ?
    Math.abs(d.take_profit - d.price) / Math.abs(d.price - d.stop_loss) : 0;
  const rr       = rrRaw.toFixed(2);

  const reasons = (d.reasons||[]).map(r => {
    const pos = /bullish|long|above|oversold|breakout|spike/i.test(r);
    return `<div class="reason-item ${pos?'pos':'neg'}">${esc(r)}</div>`;
  }).join('');

  const indRows = d.indicators ? [
    ['ATR', d.indicators.atr?.toFixed(2)],
    ['ADX', d.indicators.adx?.toFixed(1)],
    ['RSI', d.indicators.rsi?.toFixed(1)],
    ['Stoch K', d.indicators.stoch_k?.toFixed(1)],
    ['MACD Hist', d.indicators.macd_hist?.toFixed(4)],
    ['Vol Ratio', d.indicators.volume_ratio?.toFixed(2)+'x'],
    ['VWAP', d.indicators.vwap?.toFixed(2)],
    ['EMA 50', d.indicators.ema_50?.toFixed(2)],
  ].filter(([,v]) => v !== undefined && v !== 'undefinedx') : [];

  const indHtml = indRows.map(([l,v]) =>
    `<div class="ma-item"><div class="ma-lbl">${l}</div><div class="ma-val">${v||'—'}</div></div>`
  ).join('');

  id('sig-body').innerHTML = `
    <div style="padding:16px">
      <!-- Direction block -->
      <div class="sig-direction">
        <div class="sig-dir-icon ${dirClass}">${isLong?'▲':'▼'}</div>
        <div class="sig-dir-text">
          <div class="sig-dir-main ${dirClass}">${d.direction} SIGNAL</div>
          <div class="sig-dir-sub">${esc(d.symbol)} · ${esc(d.primary_tf)} entry / ${esc(d.confirm_tf)} trend · R:R ≈ ${rr}</div>
        </div>
      </div>

      <!-- Confidence meter -->
      <div class="conf-meter">
        <div class="conf-label">
          <span class="conf-title">CONFLUENCE SCORE</span>
          <span class="conf-pct" style="color:${confPct>=75?'var(--buy)':confPct>=55?'var(--amber)':'var(--sell)'}">${confPct}%</span>
        </div>
        <div class="conf-track"><div class="conf-fill ${fillCls}" style="width:${confPct}%"></div></div>
        <div class="conf-ticks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
      </div>

      <!-- Price levels -->
      <div class="sect-label">KEY LEVELS</div>
      <div class="sig-levels" style="margin-bottom:16px">
        <div class="slev"><div class="slev-lbl">ENTRY</div><div class="slev-val entry">${fmt(d.price)}</div></div>
        <div class="slev"><div class="slev-lbl">STOP LOSS</div><div class="slev-val sl">${fmt(d.stop_loss)}</div></div>
        <div class="slev"><div class="slev-lbl">TAKE PROFIT</div><div class="slev-val tp">${fmt(d.take_profit)}</div></div>
      </div>

      <!-- Signal reasons -->
      <div class="sig-reasons">
        <div class="sig-reasons-title">CONFLUENCE FACTORS (${(d.reasons||[]).length})</div>
        ${reasons}
      </div>

      <!-- Indicator grid -->
      ${indHtml ? `<div class="sect-label" style="margin-bottom:8px">INDICATORS</div><div class="ma-grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:16px">${indHtml}</div>` : ''}

      <!-- Apply to order button -->
      <button class="apply-btn" onclick="applySignalToOrder()">→ APPLY TO ORDER PANEL</button>
    </div>`;
}

function applySignalToOrder() {
  const d = S.lastSignal;
  if (!d || !d.has_signal) return;

  const isLong = d.direction === 'LONG';

  // Switch to market tab
  document.querySelectorAll('.otab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.oform').forEach(t => t.classList.remove('active'));
  const mktTab = document.querySelector('.otab[data-type="market"]');
  if (mktTab) mktTab.classList.add('active');
  id('form-market').classList.add('active');
  S.orderType = 'market';

  id('m-sym').value = d.symbol;
  setSide('m', isLong ? 'BUY' : 'SELL');
  syncExecBtn();
  setAction(`Applied ${d.direction} signal for ${d.symbol}`);
  showResult('info', `Signal applied\nDirection: ${d.direction}\nEntry: ${d.price}\nSL: ${d.stop_loss}  TP: ${d.take_profit}`);
}

id('sig-scan-btn').addEventListener('click', runSignalScan);
id('sig-sym').addEventListener('change', () => {});   // no auto-scan on change

// ── Trade Stats ───────────────────────────────────────────────────────────────
async function loadStats() {
  const btn = id('stats-rfbtn');
  btn.classList.add('spin'); btn.textContent = '…';
  try {
    const d = await api.get('/api/stats');
    renderStats(d);
    // Draw equity curve after DOM updates (canvas must exist)
    requestAnimationFrame(() => loadEquityCurve());
    setAction('Stats refreshed');
  } catch(err) {
    id('stats-body').innerHTML = `<div style="padding:20px;color:var(--sell);font-size:11px">${esc(err.message)}</div>`;
  } finally {
    btn.classList.remove('spin'); btn.textContent = 'REFRESH';
  }
}

function renderStats(d) {
  const s   = d.stats || {};
  const wr  = s.win_rate || 0;
  const pf  = s.profit_factor;
  const pfStr = (!pf || pf === Infinity) ? '∞' : pf.toFixed(2);
  const unreal = d.total_unrealised || 0;

  // ── Open positions table ─────────────────────────────────────────────────
  const openRows = (d.open_trades || []).map(t => {
    const uPnl    = t.unrealised_pnl;
    const pnlCls  = uPnl == null ? '' : (uPnl >= 0 ? 'tr-pos' : 'tr-neg');
    const dirCls  = t.direction === 'LONG' ? 'tr-long' : 'tr-short';
    const pnlTxt  = uPnl != null ? `${uPnl >= 0 ? '+' : ''}${uPnl.toFixed(4)}` : '—';
    const curTxt  = t.current ? fmt(t.current) : '—';
    const entryTs = t.entry_time ? t.entry_time.slice(11,19) : '—';
    return `<div class="trade-row" style="grid-template-columns:55px 70px 80px 80px 80px 55px">
      <span class="${dirCls}">${esc(t.direction)}</span>
      <span>${esc(t.symbol)}</span>
      <span>${t.entry ? fmt(t.entry) : '—'}</span>
      <span style="color:var(--gold)">${curTxt}</span>
      <span class="${pnlCls}">${pnlTxt}</span>
      <span style="color:var(--text-dim)">${entryTs}</span>
    </div>`;
  }).join('');

  const openSection = (d.open_positions || 0) > 0 ? `
    <div style="margin-bottom:16px">
      <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px">
        <div class="sect-label" style="margin-bottom:0">OPEN POSITIONS (${d.open_positions})</div>
        <div style="font-size:10px;color:${unreal>=0?'var(--buy)':'var(--sell)'}">
          UNREALISED ${unreal>=0?'+':''}${unreal.toFixed(4)} USDT
        </div>
      </div>
      <div class="trade-row header" style="grid-template-columns:55px 70px 80px 80px 80px 55px">
        <span>DIR</span><span>SYMBOL</span><span>ENTRY</span><span>MARK</span><span>UNREAL PnL</span><span>TIME</span>
      </div>
      ${openRows}
    </div>` : `
    <div style="padding:10px 0 14px;color:var(--text-dim);font-size:10px;border-bottom:1px solid var(--border);margin-bottom:14px">
      No open positions
    </div>`;

  // ── Closed trades table ──────────────────────────────────────────────────
  const tradeRows = (d.recent_trades || []).map(t => {
    const pnlCls = (t.pnl || 0) >= 0 ? 'tr-pos' : 'tr-neg';
    const dirCls = t.direction === 'LONG' ? 'tr-long' : 'tr-short';
    return `<div class="trade-row">
      <span class="${dirCls}">${esc(t.direction)}</span>
      <span>${esc(t.symbol || '')}</span>
      <span>${t.entry ? fmt(t.entry) : '—'}</span>
      <span>${t.exit  ? fmt(t.exit)  : '—'}</span>
      <span class="${pnlCls}">${t.pnl != null ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(4) : '—'}</span>
      <span style="color:var(--text-dim)">${esc(t.reason || '—')}</span>
    </div>`;
  }).join('') || `<div style="padding:12px;color:var(--text-dim);font-size:10px">
    No closed trades yet — sell/close a position to see P&amp;L stats here
  </div>`;

  const hasClosed = (s.total_trades || 0) > 0;

  id('stats-body').innerHTML = `
    <div style="padding:16px">

      ${openSection}

      <div class="sect-label" style="margin-bottom:8px">CLOSED TRADE PERFORMANCE</div>

      ${!hasClosed ? `<div style="padding:10px;background:var(--bg-raised);border:1px solid var(--border);color:var(--text-dim);font-size:10px;margin-bottom:16px;line-height:1.8">
        Stats populate after you close a position (place a SELL to close a LONG, or a BUY to close a SHORT).<br>
        Open positions with live P&amp;L are shown above.
      </div>` : ''}

      <div class="stats-grid" style="margin-bottom:14px">
        <div class="stat-card">
          <div class="stat-lbl">WIN RATE</div>
          <div class="stat-val ${wr>=55?'pos':wr>=45?'amber':'neg'}">${wr.toFixed(1)}%</div>
          <div class="stat-sub">${s.wins||0}W / ${s.losses||0}L of ${s.total_trades||0}</div>
        </div>
        <div class="stat-card">
          <div class="stat-lbl">REALISED PnL</div>
          <div class="stat-val ${(s.total_pnl||0)>=0?'pos':'neg'}">${(s.total_pnl||0)>=0?'+':''}${(s.total_pnl||0).toFixed(2)}</div>
          <div class="stat-sub">USDT closed trades</div>
        </div>
        <div class="stat-card">
          <div class="stat-lbl">AVG PnL</div>
          <div class="stat-val ${(s.avg_pnl||0)>=0?'pos':'neg'}">${(s.avg_pnl||0)>=0?'+':''}${(s.avg_pnl||0).toFixed(4)}</div>
          <div class="stat-sub">per closed trade</div>
        </div>
        <div class="stat-card">
          <div class="stat-lbl">PROFIT FACTOR</div>
          <div class="stat-val ${parseFloat(pfStr)>=1.5?'pos':parseFloat(pfStr)>=1?'amber':'neg'}">${pfStr}</div>
          <div class="stat-sub">gross profit / loss</div>
        </div>
        <div class="stat-card">
          <div class="stat-lbl">AVG R:R</div>
          <div class="stat-val amber">${(s.avg_rr||0).toFixed(2)}</div>
          <div class="stat-sub">reward:risk ratio</div>
        </div>
        <div class="stat-card">
          <div class="stat-lbl">MAX DRAWDOWN</div>
          <div class="stat-val ${(s.max_drawdown_pct||0)>10?'neg':(s.max_drawdown_pct||0)>5?'amber':'pos'}">${(s.max_drawdown_pct||0).toFixed(2)}%</div>
          <div class="stat-sub">peak-to-trough</div>
        </div>
      </div>

      ${hasClosed ? `<div class="sect-label" style="margin-bottom:5px">WIN RATE</div>
      <div class="win-bar-wrap" style="margin-bottom:14px">
        <div class="win-bar" style="width:${wr}%"></div>
      </div>
      <div class="sect-label" style="margin-bottom:6px">EQUITY CURVE</div>
      <div style="background:var(--bg-raised);border:1px solid var(--border);border-radius:3px;margin-bottom:14px;padding:8px">
        <canvas id="equity-chart" height="90" style="width:100%;display:block"></canvas>
      </div>` : ''}

      <div class="trades-title">RECENT CLOSED TRADES</div>
      <div class="trade-row header">
        <span>DIR</span><span>SYMBOL</span><span>ENTRY</span><span>EXIT</span><span>PnL</span><span>REASON</span>
      </div>
      ${tradeRows}
    </div>`;
}

async function loadEquityCurve() {
  const canvas = id('equity-chart');
  if (!canvas) return;
  try {
    const d = await api.get('/api/stats/equity_curve');
    drawEquityCurve(canvas, d.points || []);
  } catch(e) { /* best-effort */ }
}

function drawEquityCurve(canvas, points) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width  = canvas.offsetWidth  * dpr;
  canvas.height = canvas.offsetHeight * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const W = canvas.offsetWidth, H = canvas.offsetHeight;
  const pad = { t: 8, r: 8, b: 20, l: 44 };
  const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;

  ctx.fillStyle = 'transparent';
  ctx.clearRect(0, 0, W, H);

  if (!points.length) {
    ctx.fillStyle = 'rgba(180,160,210,0.2)';
    ctx.font = '10px IBM Plex Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No closed trades yet', W/2, H/2);
    return;
  }

  const vals = points.map(p => p.cum);
  const minV = Math.min(0, ...vals), maxV = Math.max(0, ...vals);
  const range = maxV - minV || 1;
  const xScale = iW / Math.max(points.length - 1, 1);
  const yScale = iH / range;
  const toX = i => pad.l + i * xScale;
  const toY = v => pad.t + iH - (v - minV) * yScale;

  // Zero line
  const zeroY = toY(0);
  ctx.strokeStyle = 'rgba(180,160,210,0.15)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(W - pad.r, zeroY); ctx.stroke();
  ctx.setLineDash([]);

  // Y axis labels
  ctx.fillStyle = 'rgba(180,160,210,0.4)';
  ctx.font = `${9 * (1/dpr + 0.5)}px IBM Plex Mono, monospace`;
  ctx.textAlign = 'right';
  [minV, 0, maxV].forEach(v => {
    const y = toY(v);
    if (y >= pad.t && y <= H - pad.b)
      ctx.fillText((v >= 0 ? '+' : '') + v.toFixed(2), pad.l - 4, y + 3);
  });

  // Gradient fill
  const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
  const isPos = vals[vals.length - 1] >= 0;
  grad.addColorStop(0, isPos ? 'rgba(0,232,122,0.18)' : 'rgba(255,45,85,0.18)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(0));
  points.forEach((p, i) => ctx.lineTo(toX(i), toY(p.cum)));
  ctx.lineTo(toX(points.length - 1), toY(0));
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Equity line
  ctx.beginPath();
  ctx.strokeStyle = isPos ? '#00e87a' : '#ff2d55';
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';
  points.forEach((p, i) => i === 0 ? ctx.moveTo(toX(i), toY(p.cum)) : ctx.lineTo(toX(i), toY(p.cum)));
  ctx.stroke();

  // Dots for wins/losses
  points.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(toX(i), toY(p.cum), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = p.pnl >= 0 ? '#00e87a' : '#ff2d55';
    ctx.fill();
  });
}

id('stats-rfbtn').addEventListener('click', loadStats);

// ── News ──────────────────────────────────────────────────────────────────────
let _autoTradeOn = false;

async function loadNews() {
  id('news-body').innerHTML = `<div class="loading-msg">FETCHING NEWS<span class="cursor"></span></div>`;
  try {
    const [nd, sd] = await Promise.all([
      api.get('/api/news?limit=40'),
      api.get('/api/news/signals?limit=10'),
    ]);
    _autoTradeOn = nd.auto_trade;
    _updateAutoTradeBadge();
    renderNewsSignals(sd.signals || []);
    renderNews(nd.items || []);
    setAction(`News loaded — ${nd.count} articles`);
  } catch(e) {
    id('news-body').innerHTML = `<div style="padding:20px;color:var(--sell);font-size:11px">Error: ${esc(e.message)}</div>`;
  }
}

function renderNewsSignals(sigs) {
  const el = id('news-signals-strip');
  if (!sigs.length) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div style="font-size:9px;color:var(--text-dim);letter-spacing:1px;margin-bottom:5px">TRIGGERED SIGNALS</div>
    ${sigs.slice(0,5).map(s => `
      <div class="news-signal-card ${s.direction==='BUY'?'buy':'sell'}">
        <span class="news-badge ${s.direction==='BUY'?'BULLISH':'BEARISH'}">${s.direction}</span>
        <span style="color:var(--amber)">${esc(s.symbol)}</span>
        <span style="color:var(--text-dim)">score ${s.score>0?'+':''}${s.score}</span>
        <span style="flex:1;color:var(--text-dim);font-size:9px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(s.headline)}</span>
        <span style="color:var(--text-dim);font-size:9px">${s.ts?_fmtPubTime(s.ts):''}</span>
      </div>`).join('')}`;
}

function _fmtPubTime(pub) {
  if (!pub) return '';
  try {
    const d = new Date(pub);
    if (isNaN(d)) return pub.slice(0, 16);
    const hh = String(d.getUTCHours()).padStart(2,'0');
    const mm = String(d.getUTCMinutes()).padStart(2,'0');
    const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()];
    return `${mo} ${d.getUTCDate()} ${hh}:${mm} UTC`;
  } catch { return ''; }
}

function renderNews(items) {
  if (!items.length) {
    id('news-body').innerHTML = `<div style="padding:20px;color:var(--text-dim);font-size:10px">No news loaded yet — server polls every 2 minutes.</div>`;
    return;
  }
  id('news-body').innerHTML = items.map(n => {
    const cls = n.sentiment === 'BULLISH' ? 'bullish' : n.sentiment === 'BEARISH' ? 'bearish' : 'neutral';
    const scoreVal = n.score || 0;
    const scoreStr = scoreVal > 0 ? `+${scoreVal}` : `${scoreVal}`;
    const scoreColor = scoreVal >= 30 ? 'var(--buy)' : scoreVal <= -30 ? 'var(--sell)' : 'var(--amber)';
    const barPct = Math.min(100, Math.abs(scoreVal));
    const barColor = scoreVal > 0 ? 'var(--buy)' : scoreVal < 0 ? 'var(--sell)' : 'var(--border-hi)';
    const syms = (n.symbols||[]).map(s => `<span class="news-sym">${esc(s)}</span>`).join(' ');
    const pubTime = _fmtPubTime(n.published);
    return `
      <div class="news-card ${cls}">
        <div class="news-title">
          ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title)}
        </div>
        <div style="margin:4px 0 6px;height:3px;background:var(--border);border-radius:2px">
          <div style="width:${barPct}%;height:100%;background:${barColor};border-radius:2px;transition:width .3s"></div>
        </div>
        <div class="news-meta">
          <span class="news-badge ${n.sentiment}">${n.sentiment}</span>
          <span style="font-size:9px;font-weight:700;color:${scoreColor};letter-spacing:.5px">${scoreStr}</span>
          <span style="color:var(--text-dim)">${esc(n.source)}</span>
          ${syms}
          <span style="margin-left:auto;color:var(--text-dim);font-size:8.5px">${pubTime}</span>
        </div>
      </div>`;
  }).join('');
}

async function toggleAutoTrade() {
  _autoTradeOn = !_autoTradeOn;
  try {
    await api.post(`/api/news/auto_trade?enabled=${_autoTradeOn}`, {});
    _updateAutoTradeBadge();
    setAction(`News auto-trade ${_autoTradeOn ? 'ENABLED' : 'DISABLED'}`);
  } catch(e) {
    _autoTradeOn = !_autoTradeOn;
    alert('Failed to toggle auto-trade: ' + e.message);
  }
}

function _updateAutoTradeBadge() {
  const badge = id('news-auto-badge');
  const btn   = id('news-auto-btn');
  if (_autoTradeOn) {
    badge.textContent = 'AUTO-TRADE ON';
    badge.className   = 'auto-trade-on';
    badge.style.cssText = 'font-size:9px;padding:3px 8px;border-radius:2px;background:rgba(0,232,122,.12);border:1px solid var(--buy);color:var(--buy)';
    btn.textContent = 'DISABLE AUTO';
    btn.style.borderColor = 'var(--sell)'; btn.style.color = 'var(--sell)';
  } else {
    badge.textContent = 'AUTO-TRADE OFF';
    badge.style.cssText = 'font-size:9px;padding:3px 8px;border-radius:2px;background:var(--bg-raised);border:1px solid var(--border);color:var(--text-dim)';
    btn.textContent = 'ENABLE AUTO';
    btn.style.borderColor = 'var(--border)'; btn.style.color = 'var(--text-dim)';
  }
}

// Auto-load news when switching to news tab
document.querySelectorAll('.ctab').forEach(tab => {
  if (tab.dataset.view === 'news') {
    tab.addEventListener('click', () => setTimeout(loadNews, 100));
  }
});

// ── Multi-ticker price poll ───────────────────────────────────────────────────
async function pollTicker() {
  try {
    const d = await api.get('/api/prices?symbols=BTCUSDT,ETHUSDT,SOLUSDT');
    if (d.prices.BTCUSDT) id('tick-price').textContent = '$' + fmt(d.prices.BTCUSDT);
    if (d.prices.ETHUSDT) id('tick-eth').textContent   = '$' + fmt(d.prices.ETHUSDT);
    if (d.prices.SOLUSDT) id('tick-sol').textContent   = '$' + fmt(d.prices.SOLUSDT);
  } catch(e) {}
}
pollTicker(); setInterval(pollTicker, 15000);

// ── Market Scanner ────────────────────────────────────────────────────────────
const _SCAN_SYMBOLS = 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT';

async function loadScanner() {
  const ptf = (id('scan-ptf')||{}).value || '5m';
  const ctf = (id('scan-ctf')||{}).value || '1h';
  const btn = id('scan-run-btn');
  if (btn) { btn.classList.add('spin'); btn.textContent = '…'; }
  id('scanner-body').innerHTML = '<div class="loading-msg">FETCHING FUNDING RATES + SCANNING ' + _SCAN_SYMBOLS.split(',').length + ' SYMBOLS<span class="cursor"></span></div>';
  try {
    const [fr, scan] = await Promise.all([
      api.get('/api/funding?symbols=' + _SCAN_SYMBOLS),
      api.get(`/api/signal/scan_multi?symbols=${_SCAN_SYMBOLS}&primary_tf=${ptf}&confirm_tf=${ctf}`),
    ]);
    renderScanner(fr, scan);
    setAction(`Scanner: ${scan.signals_found} signals on ${scan.scanned} symbols`);
  } catch(e) {
    id('scanner-body').innerHTML = `<div style="padding:20px;color:var(--sell);font-size:11px">Error: ${esc(e.message)}</div>`;
    setAction('Scanner error: ' + e.message);
  } finally {
    if (btn) { btn.classList.remove('spin'); btn.textContent = 'SCAN ALL'; }
  }
}

function renderScanner(fr, scan) {
  // ── Funding rates table ──────────────────────────────────────────────────
  const frRows = (fr.rates || []).map(r => {
    const pct     = r.funding_pct || 0;
    const pctCls  = pct > 0.05 ? 'tr-neg' : (pct < -0.05 ? 'tr-pos' : '');
    const biasCls = r.bias === 'SHORT_BIAS' ? 'var(--sell)' : (r.bias === 'LONG_BIAS' ? 'var(--buy)' : 'var(--text-dim)');
    const biasLbl = r.bias === 'SHORT_BIAS' ? '↓ SHORT' : (r.bias === 'LONG_BIAS' ? '↑ LONG' : '— NEUT');
    return `<div class="trade-row" style="grid-template-columns:90px 80px 80px 70px 90px">
      <span style="color:var(--amber)">${esc(r.symbol)}</span>
      <span class="${pctCls}">${pct >= 0 ? '+' : ''}${pct.toFixed(4)}%</span>
      <span style="color:var(--text-dim)">${(r.annualized_pct||0).toFixed(1)}% APR</span>
      <span style="color:${biasCls};font-size:9px">${biasLbl}</span>
      <span style="color:var(--text-dim)">${r.mark_price ? fmt(r.mark_price) : '—'}</span>
    </div>`;
  }).join('');

  // ── Signal scan table ────────────────────────────────────────────────────
  const sigRows = (scan.results || []).map(r => {
    const hasSignal = r.direction !== 'FLAT' && (r.confidence || 0) > 0;
    const dirCls    = r.direction === 'LONG' ? 'tr-long' : (r.direction === 'SHORT' ? 'tr-short' : '');
    const confColor = (r.confidence||0) >= 75 ? 'var(--buy)' : ((r.confidence||0) >= 55 ? 'var(--amber)' : 'var(--text-dim)');
    const dirLabel  = hasSignal ? (r.direction === 'LONG' ? '▲ LONG' : '▼ SHORT') : '— FLAT';
    const topReason = (r.reasons || [])[0] || r.error || '';
    return `<div class="trade-row" style="grid-template-columns:90px 75px 55px 80px 1fr">
      <span style="color:var(--amber)">${esc(r.symbol)}</span>
      <span class="${dirCls}" style="${!hasSignal?'color:var(--text-dim)':''}">${dirLabel}</span>
      <span style="color:${confColor}">${hasSignal ? (r.confidence + '%') : '—'}</span>
      <span style="color:var(--text-dim)">${r.price ? fmt(r.price) : '—'}</span>
      <span style="color:var(--text-dim);font-size:9px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(topReason.slice(0,40))}</span>
    </div>`;
  }).join('');

  const activeCount = scan.signals_found || 0;
  const sigBadge    = activeCount > 0 ? `<span style="color:var(--buy);margin-left:6px">${activeCount} SIGNAL${activeCount>1?'S':''} FOUND</span>` : `<span style="color:var(--text-dim);margin-left:6px">NO SIGNALS</span>`;

  id('scanner-body').innerHTML = `
    <div style="padding:16px">

      <div class="sect-label" style="margin-bottom:6px">FUNDING RATES
        <span style="font-size:9px;color:var(--text-dim);margin-left:8px;font-weight:normal">
          +rate = bulls pay shorts → FADE LONGS · −rate = bears pay longs → FADE SHORTS
        </span>
      </div>
      <div class="trade-row header" style="grid-template-columns:90px 80px 80px 70px 90px">
        <span>SYMBOL</span><span>8H RATE</span><span>APR</span><span>BIAS</span><span>MARK PRICE</span>
      </div>
      ${frRows || '<div style="padding:8px;color:var(--text-dim);font-size:10px">No funding data</div>'}

      <div class="sect-label" style="margin-top:18px;margin-bottom:6px">
        MTF SIGNAL SCAN — ${esc(scan.primary_tf||'5m')}/${esc(scan.confirm_tf||'1h')} · ${scan.scanned||0} symbols${sigBadge}
      </div>
      <div class="trade-row header" style="grid-template-columns:90px 75px 55px 80px 1fr">
        <span>SYMBOL</span><span>DIRECTION</span><span>CONF</span><span>PRICE</span><span>TOP FACTOR</span>
      </div>
      ${sigRows || '<div style="padding:8px;color:var(--text-dim);font-size:10px">No results</div>'}

      <div style="margin-top:12px;font-size:9px;color:var(--text-dim);line-height:1.8">
        Signal threshold: ≥65% confluence · ATR-based stops · Supertrend + ADX + MACD + StochRSI + VWAP + Volume<br>
        Scanned: ${_SCAN_SYMBOLS.split(',').join(', ')}
      </div>
    </div>`;
}

id('scan-run-btn').addEventListener('click', loadScanner);

// ── Status bar helpers ────────────────────────────────────────────────────────
function setAction(msg) { id('sb-action').textContent = msg; }

// ── Stream Tab ────────────────────────────────────────────────────────────────
(function() {
  var logEl = document.getElementById('stream-log');
  var activeFilter = 'ALL';
  var paused = false;
  if (!logEl) return;

  logEl.addEventListener('mouseenter', function() { paused = true; });
  logEl.addEventListener('mouseleave', function() { paused = false; });

  document.querySelectorAll('.stream-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.stream-filter-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      filterStreamLog();
    });
  });

  function filterStreamLog() {
    document.querySelectorAll('#stream-log .stream-line').forEach(function(el) {
      el.style.display = (activeFilter === 'ALL' || el.dataset.type === activeFilter) ? '' : 'none';
    });
  }

  function appendStreamLine(type, msg, ts) {
    var colors = { INFO:'#94a3b8', WARNING:'#f59e0b', ERROR:'#f87171', CRITICAL:'#f87171' };
    var line = document.createElement('div');
    line.className = 'stream-line';
    line.dataset.type = type;
    line.style.cssText = 'margin-bottom:2px;padding:1px 0;';
    line.style.color = colors[type] || '#94a3b8';
    line.textContent = (ts ? ts + ' ' : '') + '[' + type + '] ' + msg;
    logEl.appendChild(line);
    filterStreamLog();
    if (!paused) logEl.scrollTop = logEl.scrollHeight;
    while (logEl.children.length > 500) logEl.removeChild(logEl.firstChild);
  }

  var wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  var wsUrl = wsProto + '://' + location.host + '/ws/log';
  var streamStatusEl = document.getElementById('stream-status');
  var _streamWs = null;
  function connectStream() {
    if (_streamWs && _streamWs.readyState < 2) return;  // already open/connecting
    var ws = _streamWs = new WebSocket(wsUrl);
    ws.onopen = function() { if (streamStatusEl) { streamStatusEl.textContent = 'LIVE'; streamStatusEl.style.background = '#22c55e'; } };
    ws.onmessage = function(e) {
      try {
        var data = JSON.parse(e.data);
        if (data.type === 'ping') return;
        appendStreamLine(data.type || 'INFO', data.msg || e.data, data.ts || '');
      } catch(_) {
        appendStreamLine('INFO', e.data, new Date().toISOString().substring(11,19));
      }
    };
    ws.onclose = function() {
      if (streamStatusEl) { streamStatusEl.textContent = 'RECONNECTING'; streamStatusEl.style.background = '#f59e0b'; }
      setTimeout(connectStream, 3000);
    };
  }
  connectStream();
})();

// ── Journal Tab ───────────────────────────────────────────────────────────────
(function() {
  var tbody = document.getElementById('journal-tbody');
  var statsEl = document.getElementById('journal-stats');
  if (!tbody) return;

  function loadJournal() {
    fetch('/api/journal?limit=100')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var s = data.stats || {};
        statsEl.innerHTML = [
          ['WIN RATE', esc((s.win_rate || 0) + '%'), '#22c55e'],
          ['AVG R:R',  esc(String(s.avg_rr || '--')), '#60a5fa'],
          ['TRADES',   esc(String(s.trade_count || 0)), '#a78bfa'],
          ['TOTAL PNL', esc('$' + (s.total_pnl || 0)), (s.total_pnl || 0) >= 0 ? '#22c55e' : '#f87171'],
          ['KELLY', data.kelly_active ? 'ACTIVE' : 'WARMING', data.kelly_active ? '#22c55e' : '#f59e0b'],
        ].map(function(item) {
          return '<div style="background:#1e293b;border-radius:6px;padding:8px 14px"><div style="color:' + item[2] + ';font-size:15px;font-family:monospace">' + item[1] + '</div><div style="color:#94a3b8;font-size:10px;letter-spacing:1px">' + item[0] + '</div></div>';
        }).join('');

        var regimeFilter  = (document.getElementById('journal-regime-filter')  || {}).value || '';
        var outcomeFilter = (document.getElementById('journal-outcome-filter') || {}).value || '';
        var rows = (data.rows || []).filter(function(r) {
          if (regimeFilter  && r.regime !== regimeFilter) return false;
          if (outcomeFilter === 'WIN'  && r.pnl <= 0) return false;
          if (outcomeFilter === 'LOSS' && r.pnl >  0) return false;
          return true;
        });
        tbody.innerHTML = rows.map(function(r) {
          var pnlColor = r.pnl >= 0 ? '#22c55e' : '#f87171';
          var pnlStr = (r.pnl >= 0 ? '+' : '') + '$' + parseFloat(r.pnl).toFixed(2);
          return '<tr style="border-bottom:1px solid #1e293b">' +
            '<td style="padding:6px;color:#94a3b8">'  + esc(String(r.id))        + '</td>' +
            '<td style="padding:6px">'                + esc(r.symbol)            + '</td>' +
            '<td style="padding:6px;color:' + (r.direction==='LONG'?'#22c55e':'#f87171') + '">' + esc(r.direction) + '</td>' +
            '<td style="padding:6px">'                + esc(r.regime)            + '</td>' +
            '<td style="padding:6px;color:#a78bfa">'  + esc(r.tier)              + '</td>' +
            '<td style="padding:6px">'                + esc(String(r.confidence)) + '</td>' +
            '<td style="padding:6px">'                + esc(r.exit_reason)       + '</td>' +
            '<td style="padding:6px;color:' + pnlColor + '">' + esc(pnlStr)      + '</td>' +
            '<td style="padding:6px;color:#a78bfa;font-size:10px">' + esc(r.lesson || '') + '</td>' +
            '</tr>';
        }).join('');
      }).catch(function(e) { console.error('Journal load failed', e); });
  }

  var regSel = document.getElementById('journal-regime-filter');
  var outSel = document.getElementById('journal-outcome-filter');
  if (regSel) regSel.addEventListener('change', loadJournal);
  if (outSel) outSel.addEventListener('change', loadJournal);
  var journalTab = document.querySelector('.ctab[data-view="journal"]');
  if (journalTab) journalTab.addEventListener('click', loadJournal);
  loadJournal();
})();

// ── SOUL Tab ──────────────────────────────────────────────────────────────────
(function() {
  var editor     = document.getElementById('soul-editor');
  var saveBtn    = document.getElementById('soul-save-btn');
  var saveStatus = document.getElementById('soul-save-status');
  var lessonsEl  = document.getElementById('soul-lessons');
  if (!editor) return;

  function loadSoul() {
    fetch('/api/soul').then(function(r) { return r.json(); }).then(function(d) {
      editor.value = d.text || '';
    }).catch(function() {});
    fetch('/api/kelly').then(function(r) { return r.json(); }).then(function(d) {
      if (lessonsEl) lessonsEl.textContent = (d.active_lessons && d.active_lessons.length) ? d.active_lessons.join('\n') : 'No lessons yet.';
    }).catch(function() { if (lessonsEl) lessonsEl.textContent = 'No lessons yet.'; });
  }

  if (saveBtn) saveBtn.addEventListener('click', function() {
    fetch('/api/soul', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: editor.value})
    }).then(function(r) { return r.json(); }).then(function() {
      saveStatus.textContent = 'Saved ✓';
      setTimeout(function() { saveStatus.textContent = ''; }, 2000);
    }).catch(function() { saveStatus.textContent = 'Save failed'; });
  });

  var soulTab = document.querySelector('.ctab[data-view="soul"]');
  if (soulTab) soulTab.addEventListener('click', loadSoul);
  loadSoul();
})();

// ── Kelly Tab ─────────────────────────────────────────────────────────────────
(function() {
  var fStarEl   = document.getElementById('kelly-f-star');
  var halfEl    = document.getElementById('kelly-half');
  var nextEl    = document.getElementById('kelly-next-size');
  var badgeEl   = document.getElementById('kelly-status-badge');
  var statsBody = document.getElementById('kelly-stats-tbody');
  if (!fStarEl) return;

  function loadKelly() {
    fetch('/api/kelly').then(function(r) { return r.json(); }).then(function(d) {
      badgeEl.textContent = '';
      var badge = document.createElement('span');
      badge.style.cssText = 'padding:4px 12px;border-radius:4px;font-size:11px;letter-spacing:1px;';
      if (d.kelly_active) {
        badge.style.background = '#22c55e'; badge.style.color = '#000';
        badge.textContent = 'KELLY ACTIVE';
      } else {
        badge.style.background = '#f59e0b'; badge.style.color = '#000';
        badge.textContent = 'WARMING UP (' + (d.trade_count || 0) + '/20 TRADES)';
      }
      badgeEl.appendChild(badge);

      var equity   = d.equity || 10000;
      var nextSize = d.next_size_usdt;
      fStarEl.textContent = nextSize ? ((nextSize / equity * 200).toFixed(1) + '%') : '--';
      halfEl.textContent  = nextSize ? ((nextSize / equity * 100).toFixed(1) + '%') : '--';
      nextEl.textContent  = nextSize ? ('$' + parseFloat(nextSize).toFixed(0))      : '--';
      statsBody.innerHTML = [
        ['WIN RATE',  esc((d.win_rate || 0) + '%')],
        ['AVG R:R',   esc(String(d.avg_rr || '--'))],
        ['DRAWDOWN',  esc(((d.drawdown || 0) * 100).toFixed(1) + '%')],
        ['DD SCALE',  d.drawdown >= 0.08 ? '0.25×' : d.drawdown >= 0.05 ? '0.5×' : '1.0×'],
      ].map(function(row) {
        return '<tr><td style="padding:6px;color:#94a3b8;font-size:10px;letter-spacing:1px">' + row[0] + '</td><td style="padding:6px;font-family:monospace">' + row[1] + '</td></tr>';
      }).join('');
    }).catch(function(e) { console.error('Kelly load failed', e); });
  }

  var kellyTab = document.querySelector('.ctab[data-view="kelly"]');
  if (kellyTab) kellyTab.addEventListener('click', loadKelly);
  loadKelly();
})();

(function () {
  var _btChart = null;

  function makeMetricCard(label, value, positive) {
    var card = document.createElement("div");
    card.style.cssText = "background:#111;border:1px solid #333;padding:10px;border-radius:4px";
    var lbl = document.createElement("div");
    lbl.style.cssText = "font-size:10px;color:#888";
    lbl.textContent = label;
    var val = document.createElement("div");
    val.style.cssText = "font-size:18px;font-weight:bold;color:" + (positive ? "#0f0" : "#f44");
    val.textContent = value;
    card.appendChild(lbl);
    card.appendChild(val);
    return card;
  }

  window.runBacktest = function () {
    var status  = document.getElementById("bt-status");
    var results = document.getElementById("bt-results");
    status.textContent = "Running backtest... this may take 30-60s on first run (downloading data)";
    results.style.display = "none";

    fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbols:         [document.getElementById("bt-symbol").value],
        primary_tf:      document.getElementById("bt-ptf").value,
        confirm_tf:      document.getElementById("bt-ctf").value,
        start_date:      document.getElementById("bt-start").value,
        end_date:        document.getElementById("bt-end").value,
        initial_capital: parseFloat(document.getElementById("bt-capital").value),
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.detail) { status.textContent = "Error: " + d.detail; return; }
        status.textContent = "";
        var m = d.metrics;

        var cards = [
          { label: "SHARPE",    value: (+(m.sharpe_ratio   || 0)).toFixed(2),          pos: (m.sharpe_ratio   || 0) >= 0 },
          { label: "CAGR",      value: ((m.cagr            || 0) * 100).toFixed(1) + "%", pos: (m.cagr || 0) >= 0 },
          { label: "MAX DD",    value: ((m.max_drawdown_pct || 0) * 100).toFixed(1) + "%", pos: false },
          { label: "WIN RATE",  value: (+(m.win_rate        || 0)).toFixed(1) + "%",    pos: (m.win_rate || 0) >= 50 },
          { label: "TRADES",    value: String(m.total_trades || 0),                     pos: true },
          { label: "TOTAL PnL", value: "$" + (+(m.total_pnl  || 0)).toFixed(2),        pos: (m.total_pnl || 0) >= 0 },
          { label: "FINAL EQ",  value: "$" + (+(m.final_equity || 0)).toFixed(2),      pos: (m.final_equity || 0) >= 0 },
          { label: "SORTINO",   value: (+(m.sortino_ratio   || 0)).toFixed(2),          pos: (m.sortino_ratio || 0) >= 0 },
        ];

        var container = document.getElementById("bt-metrics");
        container.textContent = "";
        cards.forEach(function (c) { container.appendChild(makeMetricCard(c.label, c.value, c.pos)); });

        var labels = d.equity_curve.map(function (p) { return p.t.slice(0, 10); });
        var values = d.equity_curve.map(function (p) { return p.v; });

        if (_btChart) _btChart.destroy();
        _btChart = new Chart(document.getElementById("bt-chart").getContext("2d"), {
          type: "line",
          data: {
            labels: labels,
            datasets: [{ label: "Equity (USDT)", data: values, borderColor: "#0cf", borderWidth: 1.5, pointRadius: 0, fill: false }],
          },
          options: {
            animation: false,
            plugins: { legend: { labels: { color: "#ccc" } } },
            scales: {
              x: { ticks: { color: "#888", maxTicksLimit: 8 }, grid: { color: "#222" } },
              y: { ticks: { color: "#888" }, grid: { color: "#222" } },
            },
          },
        });
        results.style.display = "block";
      })
      .catch(function (e) { status.textContent = "Error: " + String(e); });
  };
})();

(function () {
  var _token = localStorage.getItem("jwt_token");

  function showLogin() {
    var el = document.getElementById("login-overlay");
    el.style.display = "flex";
  }

  function hideLogin() {
    document.getElementById("login-overlay").style.display = "none";
  }

  if (!_token) { showLogin(); }

  window.doLogin = function () {
    var user = document.getElementById("login-user").value;
    var pass = document.getElementById("login-pass").value;
    fetch("/api/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username: user, password: pass }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.access_token) {
          localStorage.setItem("jwt_token", d.access_token);
          window.location.reload();
        } else {
          document.getElementById("login-err").textContent = d.detail || "Login failed";
        }
      })
      .catch(function () {
        document.getElementById("login-err").textContent = "Server unreachable";
      });
  };

  var _origFetch = window.fetch;
  window.fetch = function (url, opts) {
    opts = opts || {};
    if (_token && typeof url === "string" && (url.startsWith("/api/") || url.includes("/api/"))) {
      opts.headers = Object.assign({}, opts.headers, { Authorization: "Bearer " + _token });
    }
    return _origFetch(url, opts).then(function (r) {
      if (r.status === 401) {
        localStorage.removeItem("jwt_token");
        _token = null;
        showLogin();
      }
      return r;
    });
  };
})();

// ── Overview polling ────────────────────────────────────────────────────────────────────────────────
loadOverview();
setInterval(() => { if (S.currentView === 'overview') loadOverview(); }, 30000);
