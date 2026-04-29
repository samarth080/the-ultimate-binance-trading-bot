# Recruiter Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five production-grade features that make the project immediately impressive to recruiters: CI badge, Docker, backtesting dashboard tab, live P&L header card, and JWT auth.

**Architecture:** Each task is fully independent and can be merged on its own. Tasks 1-2 are infra (no Python changes). Tasks 3-4 wire the existing `backtesting/` engine into FastAPI and the frontend. Task 5 extends the `/ws` WebSocket tick with unrealized PnL. Task 6 gates the dashboard behind a JWT login page.

**Tech Stack:** GitHub Actions, Docker, FastAPI, Chart.js (already in frontend), python-jose + passlib (JWT)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `.github/workflows/ci.yml` | Create | Run pytest on every push/PR |
| `Dockerfile` | Create | Single-stage Python image |
| `docker-compose.yml` | Create | One-command local dev start |
| `.dockerignore` | Create | Exclude venv/cache from image |
| `api.py` | Modify | Add /api/backtest/run, JWT middleware, P&L in /ws |
| `frontend/index.html` | Modify | BACKTEST tab, live P&L card in header, login page |
| `Readme.md` | Modify | CI badge, Docker quickstart, auth docs |

---

## Task 1: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `Readme.md`

- [ ] **Step 1: Create the workflow file**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        env:
          BINANCE_API_KEY: "test"
          BINANCE_SECRET_KEY: "test"
        run: python3 -m pytest tests/test_intelligence.py tests/test_signal_tiers.py -v --tb=short
```

- [ ] **Step 2: Add CI badge to Readme.md**

Add this line immediately after the existing Status badge:

```markdown
![CI](https://github.com/samarth080/the-ultimate-binance-trading-bot/actions/workflows/ci.yml/badge.svg)
```

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/ci.yml Readme.md
git commit -m "ci: add GitHub Actions pytest workflow and README badge"
git push origin main
```

Expected: Actions tab on GitHub shows the workflow running. Badge turns green within ~2 minutes.

---

## Task 2: Docker + docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
services:
  bot:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
    restart: unless-stopped
```

- [ ] **Step 3: Write .dockerignore**

```
venv/
__pycache__/
*.pyc
*.pyo
.git/
.pytest_cache/
runs/
data/cache/
*.log
```

- [ ] **Step 4: Test the build**

```bash
docker compose build && docker compose up
```

Expected: Server starts at http://localhost:8000, same as running uvicorn directly.

- [ ] **Step 5: Update Readme.md — add Docker quickstart**

Add after the "Running the Bot" section:

```markdown
### Docker (one command)

    docker compose up --build

Dashboard available at http://localhost:8000.
Logs and trade data persist in ./logs and ./data via volume mounts.
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore Readme.md
git commit -m "feat: add Dockerfile and docker-compose for one-command start"
git push origin main
```

---

## Task 3: Backtest API Endpoint

**Files:**
- Modify: `api.py`

Wire the existing `backtesting/` engine into a FastAPI endpoint. The endpoint accepts params, downloads/caches OHLCV data via the existing `download_klines` function, runs the backtester, and returns metrics + equity curve as JSON.

- [ ] **Step 1: Add imports near the top of api.py** (after existing imports)

```python
from backtesting.types import BacktestConfig
from backtesting.data_loader import download_klines, _tf_to_ms
from backtesting.data_feed import DataFeed
from backtesting.backtester import Backtester
from backtesting.performance import calculate_performance_report
import tempfile
```

- [ ] **Step 2: Add the request model and endpoint to api.py**

Add before the order routes section:

```python
class BacktestRequest(BaseModel):
    symbols: list[str] = ["BTCUSDT"]
    primary_tf: str = "5m"
    confirm_tf: str = "1h"
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-01"
    initial_capital: float = 10_000.0


@app.post("/api/backtest/run")
@limiter.limit("3/minute")
async def run_backtest(request: Request, body: BacktestRequest):
    try:
        start = datetime.fromisoformat(body.start_date).replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(body.end_date).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date format: {e}")

    if end <= start:
        raise HTTPException(400, "end_date must be after start_date")
    if (end - start).days > 180:
        raise HTTPException(400, "Date range cannot exceed 180 days")

    cfg = BacktestConfig(
        symbols=body.symbols,
        primary_tf=body.primary_tf,
        confirm_tf=body.confirm_tf,
        start=start,
        end=end,
        initial_capital=body.initial_capital,
        mode="portfolio",
    )

    client = _get_client()
    cache_dir = Path("data/cache")
    bars = {}

    for sym in cfg.symbols:
        for tf in [cfg.primary_tf, cfg.confirm_tf]:
            pad_ms  = _tf_to_ms(tf) * 200
            padded  = datetime.fromtimestamp(start.timestamp() - pad_ms / 1000, tz=timezone.utc)
            bars[(sym, tf)] = download_klines(client, sym, tf, padded, end, cache_dir)

    feed = DataFeed(
        bars=bars, primary_tf=cfg.primary_tf,
        symbols=cfg.symbols, start=start, end=end,
    )

    with tempfile.TemporaryDirectory() as tmp:
        bt = Backtester(config=cfg, feed=feed, run_dir=Path(tmp))
        trades_df, _ = bt.run()

    metrics = calculate_performance_report(trades_df, bt.equity_curve, body.initial_capital)

    equity_curve = [
        {
            "t": pt["timestamp"].isoformat()
                 if hasattr(pt["timestamp"], "isoformat") else str(pt["timestamp"]),
            "v": round(pt["equity"], 2),
        }
        for pt in bt.equity_curve
    ]

    return {"metrics": metrics, "equity_curve": equity_curve, "trade_count": len(trades_df)}
```

- [ ] **Step 3: Test the endpoint**

```bash
curl -s -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"symbols":["BTCUSDT"],"primary_tf":"5m","confirm_tf":"1h","start_date":"2024-01-01","end_date":"2024-02-01","initial_capital":10000}' \
  | python3 -m json.tool | head -30
```

Expected: JSON response with `metrics` dict (sharpe_ratio, cagr, win_rate, max_drawdown_pct, total_pnl, final_equity) and `equity_curve` array of `{t, v}` objects.

- [ ] **Step 4: Commit**

```bash
git add api.py
git commit -m "feat: add POST /api/backtest/run wired to backtesting engine"
```

---

## Task 4: Backtest Dashboard Tab

**Files:**
- Modify: `frontend/index.html`

Add a BACKTEST tab with a form and results panel. All dynamic content uses `textContent` (never raw innerHTML with untrusted data). The equity curve uses Chart.js which is already loaded in the page.

- [ ] **Step 1: Add the tab button**

In the tab buttons block, add:

```html
<button class="tab-btn" onclick="showTab('view-backtest',this)">BACKTEST</button>
```

- [ ] **Step 2: Add the tab content panel**

Add before the closing `</div>` of the views container:

```html
<div id="view-backtest" class="cview" style="display:none">
  <div class="panel" style="max-width:700px;margin:0 auto">
    <div class="panel-title">BACKTEST</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
      <div>
        <label class="lbl">SYMBOL</label>
        <select id="bt-symbol" class="inp">
          <option>BTCUSDT</option><option>ETHUSDT</option>
          <option>SOLUSDT</option><option>BNBUSDT</option>
        </select>
      </div>
      <div>
        <label class="lbl">CAPITAL (USDT)</label>
        <input id="bt-capital" class="inp" type="number" value="10000" min="100">
      </div>
      <div>
        <label class="lbl">START DATE</label>
        <input id="bt-start" class="inp" type="date" value="2024-01-01">
      </div>
      <div>
        <label class="lbl">END DATE</label>
        <input id="bt-end" class="inp" type="date" value="2024-03-01">
      </div>
      <div>
        <label class="lbl">PRIMARY TF</label>
        <select id="bt-ptf" class="inp">
          <option>5m</option><option>15m</option><option>1h</option>
        </select>
      </div>
      <div>
        <label class="lbl">CONFIRM TF</label>
        <select id="bt-ctf" class="inp">
          <option>1h</option><option>4h</option><option>1d</option>
        </select>
      </div>
    </div>
    <button class="btn" onclick="runBacktest()" style="width:100%">RUN BACKTEST</button>
    <div id="bt-status" style="margin-top:8px;color:#aaa;font-size:12px"></div>
    <div id="bt-results" style="display:none;margin-top:18px">
      <div id="bt-metrics" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px"></div>
      <canvas id="bt-chart" height="120"></canvas>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add the backtest JavaScript before the closing script tag**

```javascript
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
          { label: "SHARPE",    value: (+(m.sharpe_ratio  || 0)).toFixed(2),        pos: (m.sharpe_ratio  || 0) >= 0 },
          { label: "CAGR",      value: ((m.cagr           || 0) * 100).toFixed(1) + "%", pos: (m.cagr || 0) >= 0 },
          { label: "MAX DD",    value: ((m.max_drawdown_pct|| 0) * 100).toFixed(1) + "%", pos: false },
          { label: "WIN RATE",  value: (+(m.win_rate       || 0)).toFixed(1) + "%",  pos: (m.win_rate || 0) >= 50 },
          { label: "TRADES",    value: String(m.total_trades || 0),                  pos: true },
          { label: "TOTAL PnL", value: "$" + (+(m.total_pnl || 0)).toFixed(2),      pos: (m.total_pnl || 0) >= 0 },
          { label: "FINAL EQ",  value: "$" + (+(m.final_equity || 0)).toFixed(2),   pos: (m.final_equity || 0) >= 0 },
          { label: "SORTINO",   value: (+(m.sortino_ratio  || 0)).toFixed(2),        pos: (m.sortino_ratio || 0) >= 0 },
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
```

- [ ] **Step 4: Reload and test**

Navigate to http://localhost:8000, click BACKTEST, set a 1-month range, click RUN BACKTEST. After 30-60s you should see 8 metric cards and an equity curve chart.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add Backtest dashboard tab with equity curve and performance metrics"
```

---

## Task 5: Live P&L Header Card

**Files:**
- Modify: `api.py` — include unrealized PnL in `/ws` tick payload
- Modify: `frontend/index.html` — render P&L in header

- [ ] **Step 1: Extend the /ws tick payload in api.py**

Inside the `/ws` WebSocket handler, after building the `tick` dict, add:

```python
try:
    positions = _get_client().get_position_risk(recvWindow=5000)
    upnl = sum(
        float(p.get("unrealizedProfit", 0))
        for p in positions
        if float(p.get("positionAmt", 0)) != 0
    )
except Exception:
    upnl = None

tick["upnl"] = round(upnl, 2) if upnl is not None else None
```

- [ ] **Step 2: Add P&L card element to the header in frontend/index.html**

Find the header price ticker section and add:

```html
<span id="hdr-upnl" style="padding:4px 12px;border:1px solid #333;border-radius:4px;font-size:13px;margin-left:10px">
  PnL: <span id="upnl-val">--</span>
</span>
```

- [ ] **Step 3: Update the WebSocket onmessage handler**

Inside the existing `ws.onmessage` block, add:

```javascript
if (typeof data.upnl === "number") {
  var upnlEl = document.getElementById("upnl-val");
  upnlEl.textContent = (data.upnl >= 0 ? "+" : "") + "$" + data.upnl.toFixed(2);
  upnlEl.style.color = data.upnl >= 0 ? "#0f0" : "#f44";
}
```

- [ ] **Step 4: Test**

Reload http://localhost:8000. Header shows PnL card next to price tickers. On testnet with no open positions it shows `+$0.00`.

- [ ] **Step 5: Commit**

```bash
git add api.py frontend/index.html
git commit -m "feat: add live unrealized P&L card to header via /ws tick"
```

---

## Task 6: JWT Auth (Login Gate)

**Files:**
- Modify: `api.py`
- Modify: `requirements.txt`
- Modify: `frontend/index.html`
- Modify: `Readme.md`

- [ ] **Step 1: Add dependencies**

```bash
pip install "python-jose[cryptography]" passlib bcrypt
```

Add to `requirements.txt`:
```
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
```

- [ ] **Step 2: Add auth helpers to api.py** (after existing imports)

```python
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

_JWT_SECRET   = os.getenv("JWT_SECRET", "change-me-in-production")
_JWT_ALGO     = "HS256"
_JWT_EXP_MINS = 60 * 8

_pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
_oauth2   = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

_DASH_USER = os.getenv("DASHBOARD_USER", "admin")
_DASH_PASS = os.getenv("DASHBOARD_PASS", "changeme")
_DASH_HASH = _pwd_ctx.hash(_DASH_PASS)


def _create_token(username: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=_JWT_EXP_MINS)
    return jwt.encode({"sub": username, "exp": exp}, _JWT_SECRET, algorithm=_JWT_ALGO)


async def _require_auth(token: str = Depends(_oauth2)):
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
        if not payload.get("sub"):
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


@app.post("/api/auth/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    if form.username != _DASH_USER or not _pwd_ctx.verify(form.password, _DASH_HASH):
        raise HTTPException(401, "Incorrect username or password")
    return {"access_token": _create_token(form.username), "token_type": "bearer"}
```

- [ ] **Step 3: Gate sensitive routes**

Add `_=Depends(_require_auth)` to each of these endpoints:
- `POST /api/order/market`
- `POST /api/order/limit`
- `POST /api/order/oco`
- `POST /api/order/stop_limit`
- `POST /api/order/twap`
- `POST /api/backtest/run`
- `POST /api/soul`
- `POST /api/news/auto_trade`

Example:
```python
@app.post("/api/order/market")
@limiter.limit("10/minute")
async def place_market_order(request: Request, body: MarketOrderRequest, _=Depends(_require_auth)):
    ...
```

Leave read-only endpoints (`/api/status`, `/api/prices`, `/api/news`, `/`) ungated.

- [ ] **Step 4: Add login overlay to frontend/index.html**

Add immediately after the `<body>` tag:

```html
<div id="login-overlay" style="display:none;position:fixed;inset:0;background:#000e;z-index:9999;align-items:center;justify-content:center">
  <div style="background:#111;border:1px solid #333;padding:32px;border-radius:8px;width:320px">
    <div style="font-size:18px;font-weight:bold;margin-bottom:20px;color:#0cf">LOGIN</div>
    <input id="login-user" class="inp" placeholder="Username" style="width:100%;margin-bottom:10px">
    <input id="login-pass" class="inp" type="password" placeholder="Password" style="width:100%;margin-bottom:16px">
    <button class="btn" onclick="doLogin()" style="width:100%">SIGN IN</button>
    <div id="login-err" style="color:#f44;margin-top:8px;font-size:12px"></div>
  </div>
</div>
```

- [ ] **Step 5: Add login + fetch-intercept JavaScript before closing script tag**

```javascript
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
          _token = d.access_token;
          hideLogin();
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
    if (_token && typeof url === "string" && url.startsWith("/api/")) {
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
```

- [ ] **Step 6: Add env vars to .env**

```env
JWT_SECRET=your-random-secret-here
DASHBOARD_USER=admin
DASHBOARD_PASS=yourpassword
```

Generate a strong secret: `python3 -c "import secrets; print(secrets.token_hex(32))"`

- [ ] **Step 7: Update Readme.md**

Add under Configuration:

```markdown
### Dashboard Auth
The dashboard is protected by JWT. Set in `.env`:
- `DASHBOARD_USER` / `DASHBOARD_PASS` — login credentials
- `JWT_SECRET` — signing secret (generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`)
Token expires after 8 hours. Public read-only endpoints (prices, news) remain ungated.
```

- [ ] **Step 8: Test**

1. Reload http://localhost:8000 — login overlay appears
2. Wrong password → error message in overlay
3. Correct credentials → overlay hides, dashboard loads
4. `curl -X POST http://localhost:8000/api/backtest/run` → 401 Unauthorized
5. Refresh page → no re-login needed (token persists in localStorage for 8h)

- [ ] **Step 9: Commit and push**

```bash
git add api.py frontend/index.html requirements.txt Readme.md
git commit -m "feat: add JWT auth — login overlay, token endpoint, protected routes"
git push origin main
```

---

## Completion Checklist

- [ ] CI badge is green on GitHub
- [ ] `docker compose up --build` starts the server
- [ ] BACKTEST tab renders metric cards and equity curve chart
- [ ] Header shows live P&L updating every WebSocket tick
- [ ] Login overlay appears on fresh page load; 401 responses re-trigger it
