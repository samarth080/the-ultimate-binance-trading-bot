# Overview Tab — Command Centre Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Overview tab as the default landing screen showing account health, open positions with inline close, latest signal with apply, and top news headlines — all without switching tabs.

**Architecture:** Pure frontend change — three files touched, no new backend endpoints. The Overview tab follows the existing `ctab` / `cview` pattern already used by all other tabs. Data comes from existing API endpoints polled on a 30 s interval (guarded to only fire when the tab is active).

**Tech Stack:** Vanilla JS (existing `api.get/post`, `esc`, `id`, `S` state object), CSS variables (existing design tokens), HTML (existing `ctab`/`cview` pattern).

---

## File Map

| File | Change |
|---|---|
| `frontend/index.html` | Add OVERVIEW ctab (first position), add `#view-overview` cview HTML skeleton |
| `frontend/style.css` | Add `.ov-*` CSS classes for the two-column grid, KPI strip, loss bar, risk cells, position rows, signal card, news rows |
| `frontend/app.js` | Change default `S.currentView` to `'overview'`, add `loadOverview()`, polling, CLOSE + APPLY handlers, tab-switch auto-load hook |

---

## Task 1: Add the OVERVIEW tab and HTML skeleton to index.html

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Insert OVERVIEW as the first ctab**

In `frontend/index.html`, find:

```html
      <div class="centre-tabs" style="border-bottom:none;flex:1;">
        <div class="ctab active" data-view="analytics">ML ANALYTICS</div>
```

Replace with:

```html
      <div class="centre-tabs" style="border-bottom:none;flex:1;">
        <div class="ctab active" data-view="overview">OVERVIEW</div>
        <div class="ctab"        data-view="analytics">ML ANALYTICS</div>
```

- [ ] **Step 2: Remove active from the analytics cview**

Find:

```html
    <!-- ANALYTICS VIEW -->
    <div class="cview active" id="view-analytics">
```

Replace with:

```html
    <!-- ANALYTICS VIEW -->
    <div class="cview" id="view-analytics">
```

- [ ] **Step 3: Insert the overview cview HTML immediately before the analytics cview**

Find the comment `<!-- ANALYTICS VIEW -->` and insert this block immediately before it:

```html
    <!-- OVERVIEW VIEW -->
    <div class="cview active" id="view-overview" style="display:grid">
      <!-- Left column: Account Health + Risk -->
      <div class="ov-col">

        <!-- Account Health -->
        <div class="ov-panel">
          <div class="ph">
            <span class="ph-title">ACCOUNT HEALTH</span>
            <span class="ov-badge" id="ov-halt-badge">ACTIVE</span>
          </div>
          <div class="ov-kpi-row">
            <div class="ov-kpi">
              <div class="ov-kpi-lbl">DAILY PnL</div>
              <div class="ov-kpi-val" id="ov-daily-pnl">—</div>
              <div class="ov-kpi-sub" id="ov-daily-pct">—</div>
            </div>
            <div class="ov-kpi">
              <div class="ov-kpi-lbl">UNREALISED</div>
              <div class="ov-kpi-val" id="ov-upnl">—</div>
              <div class="ov-kpi-sub" id="ov-pos-count">—</div>
            </div>
            <div class="ov-kpi">
              <div class="ov-kpi-lbl">WIN RATE</div>
              <div class="ov-kpi-val" id="ov-winrate">—</div>
              <div class="ov-kpi-sub" id="ov-wl">—</div>
            </div>
          </div>
          <div class="ov-loss-bar-wrap">
            <div class="ov-loss-bar-lbl">
              <span>DAILY LOSS LIMIT</span>
              <span id="ov-loss-remain">—</span>
            </div>
            <div class="ov-loss-bar-track">
              <div class="ov-loss-bar-fill" id="ov-loss-fill" style="width:0%"></div>
            </div>
            <div class="ov-loss-bar-lbl"><span>0%</span><span>halt at 5%</span></div>
          </div>
        </div>

        <!-- Risk Status -->
        <div class="ov-panel">
          <div class="ph">
            <span class="ph-title">RISK STATUS</span>
            <span class="ov-badge" id="ov-risk-badge">—</span>
          </div>
          <div class="ov-risk-grid">
            <div class="ov-risk-cell">
              <div class="ov-risk-lbl">OPEN POSITIONS</div>
              <div class="ov-risk-val" id="ov-open-pos">—</div>
            </div>
            <div class="ov-risk-cell">
              <div class="ov-risk-lbl">DRAWDOWN</div>
              <div class="ov-risk-val" id="ov-drawdown">—</div>
            </div>
            <div class="ov-risk-cell">
              <div class="ov-risk-lbl">DAILY LOSS</div>
              <div class="ov-risk-val" id="ov-daily-loss">—</div>
            </div>
            <div class="ov-risk-cell">
              <div class="ov-risk-lbl">KELLY SIZE</div>
              <div class="ov-risk-val" id="ov-kelly-size">—</div>
            </div>
          </div>
        </div>

      </div>

      <!-- Right column: Positions + Signal + News -->
      <div class="ov-col">

        <!-- Open Positions -->
        <div class="ov-panel">
          <div class="ph">
            <span class="ph-title">OPEN POSITIONS</span>
            <span id="ov-unreal-total" style="font-size:9px;color:var(--text-dim)">—</span>
          </div>
          <div class="ov-pos-header">
            <span></span><span>SYMBOL</span><span>ENTRY</span><span>MARK</span><span>UNREAL</span><span></span>
          </div>
          <div id="ov-positions-body">
            <div class="ov-empty">No open positions</div>
          </div>
        </div>

        <!-- Latest Signal -->
        <div class="ov-panel">
          <div class="ph">
            <span class="ph-title">LATEST SIGNAL</span>
            <span id="ov-signal-age" style="font-size:9px;color:var(--text-dim)">—</span>
          </div>
          <div id="ov-signal-body">
            <div class="ov-empty">No active signal — run Signal Engine tab to scan</div>
          </div>
        </div>

        <!-- News Sentiment -->
        <div class="ov-panel">
          <div class="ph">
            <span class="ph-title">NEWS SENTIMENT</span>
            <span class="ov-badge" id="ov-news-badge">—</span>
          </div>
          <div id="ov-news-body">
            <div class="ov-empty">News engine disabled or loading…</div>
          </div>
        </div>

      </div>
    </div>

```

- [ ] **Step 4: Verify the file has no unclosed tags**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
try:
    V().feed(open('frontend/index.html').read())
    print('OK')
except Exception as e:
    print('ERROR:', e)
"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat(overview): add overview tab HTML skeleton"
```

---

## Task 2: Add CSS classes for the Overview layout

**Files:**
- Modify: `frontend/style.css`

- [ ] **Step 1: Append overview CSS at the end of style.css**

Append at the very end of `frontend/style.css`:

```css
/* ── Overview Tab ──────────────────────────────────────────────────────────────────────────── */
#view-overview {
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 12px;
  align-content: start;
  overflow-y: auto;
}
.ov-col   { display: flex; flex-direction: column; gap: 12px; }
.ov-panel { background: var(--bg-panel); border: 1px solid var(--border); }

.ov-badge      { font-size: 8px; padding: 2px 7px; border-radius: 2px; letter-spacing: .5px; border: 1px solid var(--border); color: var(--text-dim); }
.ov-badge.ok   { background: var(--buy-dim);  border-color: rgba(0,232,122,.3);  color: var(--buy);  }
.ov-badge.warn { background: var(--amber-dim); border-color: rgba(240,160,32,.3); color: var(--amber); }
.ov-badge.halt { background: var(--sell-dim); border-color: rgba(255,45,85,.3);  color: var(--sell); }

.ov-kpi-row { display: grid; grid-template-columns: repeat(3,1fr); gap: 1px; background: var(--border); }
.ov-kpi     { background: var(--bg-panel); padding: 10px 12px; }
.ov-kpi-lbl { font-size: 8px; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 4px; }
.ov-kpi-val { font-size: 16px; font-weight: 700; color: var(--text-hi); }
.ov-kpi-sub { font-size: 8px; color: var(--text-dim); margin-top: 2px; }

.ov-loss-bar-wrap  { padding: 10px 12px; border-top: 1px solid var(--border); }
.ov-loss-bar-lbl   { display: flex; justify-content: space-between; font-size: 8px; color: var(--text-dim); margin-bottom: 5px; }
.ov-loss-bar-track { height: 3px; background: var(--border); border-radius: 2px; }
.ov-loss-bar-fill  { height: 100%; border-radius: 2px; background: var(--buy); transition: width .4s, background .4s; }
.ov-loss-bar-fill.warn   { background: var(--amber); }
.ov-loss-bar-fill.danger { background: var(--sell); }

.ov-risk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border); }
.ov-risk-cell { background: var(--bg-panel); padding: 9px 12px; }
.ov-risk-lbl  { font-size: 8px; color: var(--text-dim); letter-spacing: .5px; margin-bottom: 3px; }
.ov-risk-val  { font-size: 12px; font-weight: 600; color: var(--text-hi); }

.ov-pos-header { display: grid; grid-template-columns: 18px 68px 80px 80px 76px 58px; padding: 5px 12px; font-size: 8px; color: var(--text-dim); letter-spacing: .5px; border-bottom: 1px solid var(--border); }
.ov-pos-row    { display: grid; grid-template-columns: 18px 68px 80px 80px 76px 58px; padding: 7px 12px; border-bottom: 1px solid var(--border); font-size: 10px; align-items: center; }
.ov-pos-row:last-child { border-bottom: none; }
.ov-close-btn  { font-size: 8px; padding: 2px 6px; background: var(--sell-dim); border: 1px solid rgba(255,45,85,.3); color: var(--sell); cursor: pointer; letter-spacing: .5px; transition: background .15s; font-family: var(--mono); }
.ov-close-btn:hover { background: rgba(255,45,85,.2); }

.ov-sig-card  { padding: 10px 12px; display: flex; align-items: center; gap: 10px; }
.ov-sig-dir   { font-size: 20px; line-height: 1; }
.ov-sig-meta  { flex: 1; }
.ov-sig-sym   { font-weight: 700; color: var(--amber); }
.ov-sig-sub   { font-size: 9px; color: var(--text-dim); margin-top: 2px; }
.ov-apply-btn { font-size: 8px; padding: 4px 10px; background: var(--blue-dim); border: 1px solid rgba(77,143,255,.3); color: var(--blue); cursor: pointer; letter-spacing: .5px; white-space: nowrap; transition: background .15s; font-family: var(--mono); }
.ov-apply-btn:hover { background: rgba(77,143,255,.2); }

.ov-news-row              { padding: 7px 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--border); font-size: 10px; }
.ov-news-row:last-child   { border-bottom: none; }
.ov-news-badge            { font-size: 8px; padding: 2px 6px; border-radius: 2px; letter-spacing: .3px; flex-shrink: 0; }
.ov-news-badge.BULLISH    { background: var(--buy-dim);   border: 1px solid rgba(0,232,122,.3);  color: var(--buy);      }
.ov-news-badge.BEARISH    { background: var(--sell-dim);  border: 1px solid rgba(255,45,85,.3);  color: var(--sell);     }
.ov-news-badge.NEUTRAL    { background: var(--bg-raised); border: 1px solid var(--border);       color: var(--text-dim); }
.ov-news-title { flex: 1; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ov-news-score { font-size: 9px; font-weight: 700; flex-shrink: 0; }

.ov-empty { padding: 16px 12px; color: var(--text-dim); font-size: 9.5px; text-align: center; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "feat(overview): add overview CSS classes"
```

---

## Task 3: Set Overview as default and hook tab-switch auto-load

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Change the initial currentView in the S state object**

Find:

```js
const S = {
  orderType: 'market',
  sides: { m:'BUY', l:'BUY', o:'BUY', s:'BUY', t:'BUY' },
  logFilter: 'ALL',
  logs: [],
  currentView: 'analytics',
  lastSignal: null,
};
```

Replace with:

```js
const S = {
  orderType: 'market',
  sides: { m:'BUY', l:'BUY', o:'BUY', s:'BUY', t:'BUY' },
  logFilter: 'ALL',
  logs: [],
  currentView: 'overview',
  lastSignal: null,
};
```

- [ ] **Step 2: Add overview to the tab-switch auto-load block**

Find:

```js
  // Auto-load data when switching tabs
  if (S.currentView === 'stats')   loadStats();
  if (S.currentView === 'news')    loadNews();
  if (S.currentView === 'scanner') loadScanner();
```

Replace with:

```js
  // Auto-load data when switching tabs
  if (S.currentView === 'overview') loadOverview();
  if (S.currentView === 'stats')    loadStats();
  if (S.currentView === 'news')     loadNews();
  if (S.currentView === 'scanner')  loadScanner();
```

- [ ] **Step 3: Fix the cview display reset so overview keeps its grid layout**

Find:

```js
  document.querySelectorAll('.cview').forEach(x => x.classList.remove('active'));
```

Replace with:

```js
  document.querySelectorAll('.cview').forEach(x => { x.classList.remove('active'); x.style.display = ''; });
```

Then find:

```js
  id('view-' + S.currentView).classList.add('active');
```

Replace with:

```js
  const _activeView = id('view-' + S.currentView);
  _activeView.classList.add('active');
  if (S.currentView === 'overview') _activeView.style.display = 'grid';
```

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat(overview): wire overview as default tab with auto-load hook"
```

---

## Task 4: Implement loadOverview() and all render helpers

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Insert the full overview JS block**

Insert the following immediately before the comment `// ── Analytics` in `frontend/app.js`.

Each render helper uses `textContent` for scalar values and escaped template literals (via the existing `esc()` function) for dynamic HTML, matching the pattern used throughout the rest of app.js.

```js
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app.js
git commit -m "feat(overview): add loadOverview and all render helpers"
```

---

## Task 5: Add polling and call loadOverview on page load

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Append polling at the very end of app.js**

At the very end of `frontend/app.js`, after the last `})();` block, append:

```js
// ── Overview polling ────────────────────────────────────────────────────────────────────────────────
loadOverview();
setInterval(() => { if (S.currentView === 'overview') loadOverview(); }, 30000);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app.js
git commit -m "feat(overview): add 30s polling while overview tab is active"
```

---

## Task 6: Smoke test and push

- [ ] **Step 1: Start the server**

```bash
uvicorn api:app --reload
```

Expected: starts on port 8000, no import errors in the terminal.

- [ ] **Step 2: Open the dashboard — verify Overview is the landing tab**

Navigate to `http://localhost:8000`. After login:
- OVERVIEW tab is highlighted amber (active)
- Both columns render: left has Account Health + Risk Status, right has Open Positions + Latest Signal + News Sentiment
- Placeholder dashes (`—`) fill in within ~2 s as API calls return

- [ ] **Step 3: Switch tabs and return**

Click ML ANALYTICS, SIGNAL ENGINE, TRADE STATS, then back to OVERVIEW. Expected:
- Each tab content renders correctly
- Returning to OVERVIEW triggers a fresh `loadOverview()` call
- No JS console errors

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| Default landing tab | Task 3 (`S.currentView = 'overview'`, ctab active) |
| Two-column layout | Task 1 (HTML), Task 2 (`#view-overview` grid CSS) |
| Daily PnL, Unrealised, Win Rate KPI tiles | Task 4 `_renderOvHealth` |
| Daily loss limit progress bar (green/amber/red) | Task 4 `_renderOvHealth` (ov-loss-fill classes) |
| Risk: positions count, drawdown, daily loss, Kelly | Task 4 `_renderOvRisk` |
| Open positions table with CLOSE button | Task 4 `_renderOvPositions` + `_closePosition` |
| CLOSE: confirm dialog, opposite-side market order | Task 4 `_closePosition` |
| Latest signal with APPLY button | Task 4 `_renderOvSignal` (calls existing `applySignalToOrder`) |
| Top 3 news headlines with sentiment badge + score | Task 4 `_renderOvNews` |
| 30 s refresh, only while overview tab active | Task 5 (setInterval guard on `S.currentView`) |
| Navigate away stops polling | Task 5 (guard prevents API calls while on other tabs) |
