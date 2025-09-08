# app.py
# -*- coding: utf-8 -*-
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, FileResponse
from pathlib import Path
from collections import deque
import asyncio
from datetime import datetime
import pandas as pd

from core import run_both_phases  # lógica en un solo sitio

app = FastAPI(title="PipeCartas Monitor", version="1.0")
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_BUFFER = deque(maxlen=4000)
LAST_RUN_AT = None
RUNNING = False
RESULTS = {"z1": None, "z2": None}

def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    LOG_BUFFER.append(line)
    print(line, flush=True)

def _read_csv_as_html(path: Path):
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        cols = [c for c in ["run_at","phase","chasis","card_id","title","pipefy","sql","updated_fields","detalle"] if c in df.columns]
        if cols:
            df = df[cols]
        return df.to_html(index=False, border=0, justify="left")
    except Exception as e:
        _log(f"⚠️ Error leyendo CSV {path.name}: {e}")
        return None

def _load_tables():
    RESULTS["z1"] = _read_csv_as_html(DATA_DIR / "results_z1.csv")
    RESULTS["z2"] = _read_csv_as_html(DATA_DIR / "results_z2.csv")

async def _run_pipeline_async():
    global RUNNING, LAST_RUN_AT
    if RUNNING:
        _log("⏳ Ya hay una ejecución en curso.")
        return
    RUNNING = True
    try:
        await asyncio.to_thread(lambda: run_both_phases(_log))
        _load_tables()
        LAST_RUN_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _log("💾 Resultados recargados.")
    finally:
        RUNNING = False

@app.on_event("startup")
async def _startup():
    # 1ra corrida inmediata
    asyncio.create_task(_run_pipeline_async())
    # scheduler cada 2 horas
    async def loop():
        while True:
            await asyncio.sleep(2*60*60)
            await _run_pipeline_async()
    asyncio.create_task(loop())

@app.get("/", response_class=HTMLResponse)
async def index():
    html = f"""
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PipeCartas — Monitor</title>
<style>
:root {{
  --bg: #0b1020;
  --card: #121a33;
  --text: #e9f0ff;
  --sub: #aab4d4;
  --line: #1f2a4d;
  --primary: #5ac8fa;
  --accent: #7ef29a;
  --warn: #ffcc66;
  --danger: #ff6b6b;
}}
:root[data-theme="light"] {{
  --bg:#f6f8ff; --card:#ffffff; --text:#0b1020; --sub:#5d6a88; --line:#e6e9f5;
  --primary:#2458ff; --accent:#11a36a; --warn:#8a6d00; --danger:#b61f1f;
}}
* {{ box-sizing: border-box; }}
html,body {{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial; }}
a {{ color: var(--primary); text-decoration: none; }}
.container {{ max-width: 1200px; margin: 32px auto; padding: 0 20px; }}

.header {{
  display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px;
}}
.brand {{
  display:flex; align-items:center; gap:12px;
}}
.brand .logo {{
  width:38px; height:38px; border-radius:12px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  box-shadow: 0 6px 20px rgba(90,200,250,.25);
}}
.brand h1 {{ font-size: 22px; margin:0; letter-spacing:.2px; }}
.brand .muted {{ color: var(--sub); font-size: 12px; margin-top:3px; }}

.toolbar {{
  display:flex; align-items:center; gap:10px; flex-wrap:wrap;
}}

.btn {{
  appearance:none; border:none; cursor:pointer; border-radius:10px; padding:10px 14px;
  background: var(--primary); color:#fff; font-weight:600; letter-spacing:.2px;
  box-shadow: 0 6px 16px rgba(36,88,255,.25);
}}
.btn[disabled] {{ opacity:.7; cursor:not-allowed; }}
.btn-ghost {{ background:transparent; color:var(--primary); border:1px solid var(--line); }}
.badge {{
  display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; font-weight:600; font-size:12px;
  border:1px solid var(--line); background:rgba(255,255,255,.02);
}}
.badge .dot {{ width:8px; height:8px; border-radius:50%; background:var(--warn); }}
.badge.ok .dot {{ background: var(--accent); }}
.badge.idle .dot {{ background: var(--warn); }}
.badge.run .dot {{ background: var(--primary); }}

.kpis {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px; margin:14px 0 20px; }}
.kpi {{ background: var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; }}
.kpi .label {{ color: var(--sub); font-size:12px; }}
.kpi .value {{ font-weight:800; font-size:18px; margin-top:6px; }}

.grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; }}
.card {{ background: var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; }}
.card h3 {{ margin:0 0 10px 0; font-size:16px; letter-spacing:.3px; }}

.actions a {{ margin-left:10px; font-weight:600; }}
.small {{ color: var(--sub); font-size:12px; }}

.table-wrap {{ border:1px solid var(--line); border-radius:10px; overflow:auto; max-height: 380px; }}
table {{ width:100%; border-collapse: collapse; font-size: 13px; }}
thead tr {{ background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,0)); position: sticky; top:0; }}
th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
tbody tr:hover {{ background: rgba(255,255,255,.03); }}

.logs pre {{
  background: #0d142b; border:1px solid var(--line); color:#d7e3ff; border-radius:12px;
  padding:14px; height: 340px; overflow:auto; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size:12px;
}}
.footer {{ color: var(--sub); font-size:12px; text-align:center; margin-top:16px; }}

.switch {{
  border:1px solid var(--line); background:var(--card); color:var(--text); padding:8px 10px; border-radius:10px; cursor:pointer;
}}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="brand">
        <div class="logo"></div>
        <div>
          <h1>PipeCartas — Monitor</h1>
          <div class="muted">Panel de seguimiento para gerencia</div>
        </div>
      </div>
      <div class="toolbar">
        <button id="runBtn" class="btn" onclick="runNow()" {'disabled' if RUNNING else ''}>
          <span id="runIcon">{'⏳' if RUNNING else '▶'}</span> Ejecutar ahora
        </button>
        <span class="badge {('run' if RUNNING else 'idle')}"><span class="dot"></span><span id="status">{'EJECUTANDO' if RUNNING else 'IDLE'}</span></span>
        <span class="badge ok"><span class="dot"></span>Última ejecución: <span id="lastRun">{LAST_RUN_AT or '-'}</span></span>
        <button class="switch" onclick="toggleTheme()">🌗 Tema</button>
        <span class="actions small">
          <a href="/csv/z1" target="_blank">⬇ CSV Z1</a>
          <a href="/csv/z2" target="_blank">⬇ CSV Z2</a>
        </span>
      </div>
    </div>

    <div class="kpis">
      <div class="kpi">
        <div class="label">Frecuencia</div>
        <div class="value">Cada 2 horas</div>
      </div>
      <div class="kpi">
        <div class="label">Estado actual</div>
        <div class="value" id="kpiStatus">{'EJECUTANDO' if RUNNING else 'IDLE'}</div>
      </div>
      <div class="kpi">
        <div class="label">Fecha y hora</div>
        <div class="value" id="nowClock">-</div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>Resultados Z1</h3>
        <div class="table-wrap" id="tblZ1"><div class="small">Cargando…</div></div>
      </div>
      <div class="card">
        <h3>Resultados Z2</h3>
        <div class="table-wrap" id="tblZ2"><div class="small">Cargando…</div></div>
      </div>
    </div>

    <div class="card logs" style="margin-top:16px;">
      <h3>Logs</h3>
      <pre id="logs">Cargando…</pre>
    </div>

    <div class="footer">Se ejecuta automáticamente cada 2 horas · PipeCartas v1.0</div>
  </div>

<script>
(function initTheme(){{
  const saved = localStorage.getItem('pc-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved === 'light' ? 'light' : 'dark');
}})();
function toggleTheme(){{
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('pc-theme', next);
}}
function tickClock(){{
  const d = new Date();
  const p = d.toLocaleString();
  document.getElementById('nowClock').textContent = p;
}}
setInterval(tickClock, 1000); tickClock();

async function refreshLogs(){{
  const r = await fetch('/logs'); const t = await r.text();
  const pre = document.getElementById('logs');
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 6;
  pre.textContent = t || '—';
  if(atBottom) pre.scrollTop = pre.scrollHeight;
}}
async function refreshResults(){{
  const r = await fetch('/results'); const j = await r.json();
  document.getElementById('tblZ1').innerHTML = j.z1_table || '<div class="small">No hay CSV Z1</div>';
  document.getElementById('tblZ2').innerHTML = j.z2_table || '<div class="small">No hay CSV Z2</div>';
  document.getElementById('lastRun').textContent = j.last_run || '-';
  const running = !!j.running;
  document.getElementById('status').textContent = running ? 'EJECUTANDO' : 'IDLE';
  document.getElementById('kpiStatus').textContent = running ? 'EJECUTANDO' : 'IDLE';
  const runBtn = document.getElementById('runBtn');
  runBtn.disabled = running;
  document.getElementById('runIcon').textContent = running ? '⏳' : '▶';
}}
async function runNow(){{
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  document.getElementById('status').textContent = 'EJECUTANDO';
  document.getElementById('kpiStatus').textContent = 'EJECUTANDO';
  document.getElementById('runIcon').textContent = '⏳';
  await fetch('/run', {{method:'POST'}});
}}

refreshLogs(); refreshResults();
setInterval(refreshLogs, 2500);
setInterval(refreshResults, 5000);
</script>
</body></html>
"""
    return HTMLResponse(html)

    html = f"""
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8" />
<title>PipeCartas — Monitor</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial;margin:20px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card{{border:1px solid #ddd;border-radius:10px;padding:12px}}
button{{padding:8px 12px;border-radius:8px;border:1px solid #999;cursor:pointer}}
.muted{{color:#666;font-size:.9rem}}
pre{{background:#0b1020;color:#e9f0ff;padding:12px;border-radius:8px;height:420px;overflow:auto}}
table{{border-collapse:collapse;width:100%;font-size:.92rem}}
th,td{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}}
th{{background:#f6f8ff}}
.actions a{{margin-right:8px}}
</style>
</head><body>
<h1>PipeCartas — Monitor</h1>
<div class="muted">Última ejecución: <span id="lastRun">{LAST_RUN_AT or "-"}</span> |
Estado: <span id="status">{'EJECUTANDO' if RUNNING else 'IDLE'}</span></div>
<div style="margin:12px 0;">
  <button onclick="runNow()">▶ Ejecutar ahora</button>
  <span class="muted">Se ejecuta automáticamente cada 2 horas.</span>
  <span class="actions" style="float:right;">
    <a href="/csv/z1" target="_blank">⬇ CSV Z1</a>
    <a href="/csv/z2" target="_blank">⬇ CSV Z2</a>
  </span>
</div>
<div class="row">
  <div class="card"><h3>Resultados Z1</h3><div id="tblZ1">Cargando...</div></div>
  <div class="card"><h3>Resultados Z2</h3><div id="tblZ2">Cargando...</div></div>
</div>
<div class="card" style="margin-top:16px;">
  <h3>Logs</h3><pre id="logs">Cargando...</pre>
</div>
<script>
async function refreshLogs(){{
  const r = await fetch('/logs'); const t = await r.text();
  const pre = document.getElementById('logs');
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 5;
  pre.textContent = t; if(atBottom) pre.scrollTop = pre.scrollHeight;
}}
async function refreshResults(){{
  const r = await fetch('/results'); const j = await r.json();
  document.getElementById('tblZ1').innerHTML = j.z1_table || '<em>No hay CSV Z1</em>';
  document.getElementById('tblZ2').innerHTML = j.z2_table || '<em>No hay CSV Z2</em>';
  document.getElementById('lastRun').textContent = j.last_run || '-';
  document.getElementById('status').textContent = j.running ? 'EJECUTANDO' : 'IDLE';
}}
async function runNow(){{
  document.getElementById('status').textContent = 'EJECUTANDO';
  await fetch('/run', {{method:'POST'}});
}}
refreshLogs(); refreshResults();
setInterval(refreshLogs, 3000);
setInterval(refreshResults, 7000);
</script>
</body></html>"""
    return HTMLResponse(html)

@app.get("/logs", response_class=PlainTextResponse)
async def get_logs():
    return PlainTextResponse("\n".join(LOG_BUFFER))

@app.get("/results", response_class=JSONResponse)
async def get_results():
    return JSONResponse({
        "last_run": LAST_RUN_AT,
        "running": RUNNING,
        "z1_table": RESULTS["z1"],
        "z2_table": RESULTS["z2"],
    })

@app.post("/run", response_class=JSONResponse)
async def run_now():
    asyncio.create_task(_run_pipeline_async())
    return {"ok": True}

@app.get("/csv/{phase}", response_class=FileResponse)
async def download_csv(phase: str):
    phase = phase.lower().strip()
    if phase not in ("z1","z2"):
        return Response(status_code=404)
    f = DATA_DIR / f"results_{phase}.csv"
    if not f.exists():
        return Response(content="CSV no encontrado aún", status_code=404)
    return FileResponse(str(f), filename=f.name, media_type="text/csv")
