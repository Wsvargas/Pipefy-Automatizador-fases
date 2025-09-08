# core.py
# -*- coding: utf-8 -*-
import os, re, unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Tuple, List, Dict

import requests
import pandas as pd
import pyodbc
from dotenv import load_dotenv

load_dotenv()  # lee .env si existe

API_URL = "https://api.pipefy.com/graphql"
PIPEFY_TOKEN = os.getenv("PIPEFY_TOKEN", "").strip()
PIPE_ID = int(os.getenv("PIPE_ID", "0"))

HEADERS = {
    "Authorization": f"Bearer {PIPEFY_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# phases
Z1_NAME = os.getenv("Z1_NAME", "Z1 Agendado para instalar")
Z2_NAME = os.getenv("Z2_NAME", "Z2 Agendado para instalar")

# fields para lectura
CHASIS_FIELD_ID = "chasis"
FECHA_FIELD_IDS = ["confirme_fecha_1", "confirme_fecha", "fecha_deseada_de_instalaci_n"]

# etiquetas de la FASE ACTUAL (no tocamos supervisor)
OBJETIVOS_FASE_ACTUAL = {
    "instalacion_ejecutada": [
        "instalación confirmada", "instalacion confirmada",
        "instalación ejecutada", "instalacion ejecutada",
        "instalación confirmada?", "instalacion confirmada?",
        "instalación ejecutada?", "instalacion ejecutada?"
    ],
    "carta_confirmada": ["carta confirmada", "carta confirmada?"],
    "mover_siguiente": [
        "mover a siguiente fase", "mover a la siguiente fase",
        "mover a siguiente fase?", "mover a la siguiente fase?"
    ],
    "fecha_carta_ins": ["fecha carta ins", "fecha carta instalación", "fecha carta ins."]
}

# SQL cfg
SQL_DRIVER   = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
SQL_SERVER   = os.getenv("SQL_SERVER", "")
SQL_DATABASE = os.getenv("SQL_DATABASE", "")
SQL_USER     = os.getenv("SQL_USER", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")

RANGO_DIAS = int(os.getenv("RANGO_DIAS", "2"))

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------- helpers ----------------
def _norm(s: str) -> str:
    s = s or ""
    s = s.strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = s.replace("¿", "").replace("?", "")
    s = re.sub(r"\s+", " ", s)
    return s

def _parse_fecha_any(x):
    if x in (None, "", "null"):
        return pd.NaT
    s = str(x).strip()
    try:
        return pd.to_datetime(s, format="%d/%m/%Y", errors="raise")
    except Exception:
        pass
    for dayfirst in (True, False):
        try:
            return pd.to_datetime(s, errors="raise", dayfirst=dayfirst, utc=False)
        except Exception:
            pass
    if "T" in s:
        try:
            return pd.to_datetime(s.split("T")[0], errors="coerce", dayfirst=False)
        except Exception:
            return pd.NaT
    return pd.NaT

def _fmt(dt):
    return dt.strftime("%Y-%m-%d") if pd.notna(dt) else "NaT"

def esta_en_rango(f1, f2, dias=2):
    if pd.isna(f1) or pd.isna(f2):
        return False
    try:
        return abs((f1.date() - f2.date()).days) <= dias
    except Exception:
        return False

def is_placeholder_1900(dt):
    return isinstance(dt, pd.Timestamp) and not pd.isna(dt) and dt.date() == datetime(1900,1,1).date()

def _formato_para_field_date(dt: pd.Timestamp, field_type: str) -> str:
    if (field_type or "").lower() == "datetime":
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return dt.strftime("%Y-%m-%d")


# ---------------- GraphQL ----------------
def gq(query: str, variables: dict | None = None):
    r = requests.post(API_URL, json={"query": query, "variables": variables or {}}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]

def obtener_id_fase(pipe_id: int, nombre_fase: str) -> str | None:
    q = f"""query {{
      pipe(id:{pipe_id}) {{
        phases{{ id name }}
      }}
    }}"""
    d = gq(q)
    for f in d["pipe"]["phases"]:
        if f["name"] == nombre_fase:
            return f["id"]
    return None

def get_phase_fields_map(phase_id: str):
    q = """query($id:ID!){
      phase(id:$id){
        id name
        fields{ id label type }
      }
    }"""
    d = gq(q, {"id": str(phase_id)})
    fields = d["phase"]["fields"] or []
    mp = {_norm(f.get("label","")): (f["id"], f.get("label",""), f.get("type","")) for f in fields}
    return mp, d["phase"]["name"]

def update_fields_values(card_id: str, values: list[dict]) -> tuple[bool, dict]:
    q = """
    mutation Update($nodeId:ID!, $values:[NodeFieldValueInput!]!){
      updateFieldsValues(input:{ nodeId:$nodeId, values:$values }){
        success
        userErrors{ message }
      }
    }"""
    r = requests.post(API_URL, json={"query": q, "variables": {"nodeId": str(card_id), "values": values}}, headers=HEADERS, timeout=60)
    ok = r.status_code == 200
    data = {}
    try:
        data = r.json()
    except Exception:
        return False, {"message": f"No JSON: {r.text[:200]}"}
    if (not ok) or ("errors" in data):
        return False, data
    payload = data.get("data", {}).get("updateFieldsValues", {})
    if not payload.get("success", False):
        return False, payload
    return True, payload

def resolver_field_ids(mp_labels: dict) -> dict:
    res = {}
    for clave, variantes in OBJETIVOS_FASE_ACTUAL.items():
        fid = None
        for v in variantes:
            info = mp_labels.get(_norm(v))
            if info:
                fid = info[0]
                break
        res[clave] = fid
    return res

def listar_tarjetas(fase_id: str):
    tarjetas, chasis_list = [], []
    cursor = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        q = f"""
        query {{
          phase(id:{fase_id}) {{
            cards(first: 50{after}) {{
              pageInfo {{ hasNextPage endCursor }}
              edges {{
                node {{
                  id
                  title
                  current_phase {{ id name }}
                  fields {{
                    name
                    value
                    report_value
                    array_value
                    field {{ id type }}
                  }}
                }}
              }}
            }}
          }}
        }}"""
        d = gq(q)
        cards = d["phase"]["cards"]
        for e in cards["edges"]:
            c = e["node"]
            by_id = {}
            for f in c["fields"]:
                fid = (f.get("field") or {}).get("id")
                if fid:
                    by_id[fid] = f
            chasis_val = ""
            if CHASIS_FIELD_ID in by_id:
                f = by_id[CHASIS_FIELD_ID]
                chasis_val = (f.get("value") or f.get("report_value") or "").strip().upper()
            fecha_inst = pd.NaT
            for fid in FECHA_FIELD_IDS:
                if fid in by_id:
                    fv = by_id[fid].get("value") or by_id[fid].get("report_value")
                    fecha_inst = _parse_fecha_any(fv)
                    if pd.notna(fecha_inst):
                        break
            tarjetas.append({
                "id": c["id"],
                "title": c["title"],
                "chasis": chasis_val,
                "fecha_inst": fecha_inst,
                "current_phase_id": (c.get("current_phase") or {}).get("id"),
                "current_phase_name": (c.get("current_phase") or {}).get("name"),
            })
            if chasis_val:
                chasis_list.append(chasis_val)
        if not cards["pageInfo"]["hasNextPage"]:
            break
        cursor = cards["pageInfo"]["endCursor"]
    return tarjetas, sorted(set(chasis_list))

def marcar_condiciones_fase_actual(card_id: str, phase_id: str, fecha_sql: pd.Timestamp) -> tuple[bool, str]:
    try:
        mp, _ = get_phase_fields_map(phase_id)
    except Exception as e:
        return False, f"No se pudo leer campos de fase: {e}"
    ids = resolver_field_ids(mp)

    valores = []
    if ids.get("instalacion_ejecutada"): valores.append({"fieldId": ids["instalacion_ejecutada"], "value": "Si"})
    if ids.get("carta_confirmada"):      valores.append({"fieldId": ids["carta_confirmada"],      "value": "Si"})
    if ids.get("mover_siguiente"):       valores.append({"fieldId": ids["mover_siguiente"],       "value": "Si"})

    # Fecha carta ins (con hora si el campo es datetime)
    if ids.get("fecha_carta_ins") and pd.notna(fecha_sql):
        tipo = None
        for _, triple in mp.items():
            if triple[0] == ids["fecha_carta_ins"]:
                tipo = triple[2]
                break
        valores.append({"fieldId": ids["fecha_carta_ins"], "value": _formato_para_field_date(fecha_sql, tipo or "datetime")})

    if not valores:
        return False, "No se resolvió ningún field_id."

    ok, resp = update_fields_values(card_id, valores)
    if not ok:
        # fallback de formato
        if ids.get("fecha_carta_ins") and pd.notna(fecha_sql):
            tipo_lower = (tipo or "").lower()
            fallback = fecha_sql.strftime("%d/%m/%Y %H:%M") if tipo_lower == "datetime" else fecha_sql.strftime("%d/%m/%Y")
            otros = [v for v in valores if v["fieldId"] != ids["fecha_carta_ins"]]
            ok2, resp2 = update_fields_values(card_id, otros + [{"fieldId": ids["fecha_carta_ins"], "value": fallback}])
            if ok2:
                return True, "Actualizado (fallback fecha aplicado)."
        return False, f"Error updateFieldsValues: {resp}"
    return True, "Actualizado."


# ---------------- SQL ----------------
def _sql_connect():
    conn_str = (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)

def _sql_top_fecha_por_chasis(conn, chasis_lote):
    if not chasis_lote:
        return pd.DataFrame(columns=["CHASIS", "FECHA_CONFIRMADA"])
    lista = ",".join(f"'{c}'" for c in chasis_lote)
    q = f"""
    WITH base AS (
      SELECT
        LTRIM(RTRIM(UPPER(CHASIS))) AS CHASIS,
        FECHA_CONFIRMADA
      FROM [dbo].[xcvisContRec]
      WHERE CHASIS IN ({lista})
        AND TIPO_DOCUMENTO = 'Carta instalación (I)'
        AND STATUS_DOCUMENTO NOT LIKE '%cancelada%'
        AND Tipo_comision IN ('INSTALADOR', 'Sin comisionista')
        AND politica_vta <> 'Alarmas'
    ),
    rn AS (
      SELECT
        CHASIS,
        FECHA_CONFIRMADA,
        ROW_NUMBER() OVER (PARTITION BY CHASIS ORDER BY FECHA_CONFIRMADA DESC) AS rk
      FROM base
    )
    SELECT CHASIS, FECHA_CONFIRMADA
    FROM rn
    WHERE rk = 1;
    """
    try:
        df = pd.read_sql(q, conn)
    except Exception:
        return pd.DataFrame(columns=["CHASIS", "FECHA_CONFIRMADA"])
    if df.empty:
        return df
    df["CHASIS"] = df["CHASIS"].astype(str).str.strip().str.upper()
    df["FECHA_CONFIRMADA"] = pd.to_datetime(df["FECHA_CONFIRMADA"], errors="coerce")
    return df[["CHASIS", "FECHA_CONFIRMADA"]]

def obtener_datos_sql_por_chasis(chasis_list, batch_size=800):
    conn = _sql_connect()
    try:
        frames = []
        for i in range(0, len(chasis_list), batch_size):
            lote = chasis_list[i:i+batch_size]
            frames.append(_sql_top_fecha_por_chasis(conn, lote))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        set_sql = set(df["CHASIS"].unique()) if not df.empty else set()
        set_in  = set(chasis_list)
        chasis_no_sql = sorted(list(set_in - set_sql))
        return df, chasis_no_sql
    finally:
        try: conn.close()
        except Exception: pass


# ---------------- Pipeline ----------------
def run_phase(phase_name: str, log: Callable[[str], None]) -> Dict[str, any]:
    """Corre una fase (Z1/Z2). Devuelve dict con métricas y guarda CSV."""
    if not PIPEFY_TOKEN or len(PIPEFY_TOKEN) < 20:
        raise SystemExit("PIPEFY_TOKEN inválido.")

    phase_id = obtener_id_fase(PIPE_ID, phase_name)
    if not phase_id:
        log(f"❌ No se encontró la fase: {phase_name}")
        return {"phase": phase_name, "moved": 0, "total": 0, "coincidencias": [], "no_sql": []}

    tarjetas, chasis_list = listar_tarjetas(phase_id)
    log(f"🔎 [{phase_name}] Tarjetas: {len(tarjetas)} | Chasis únicos: {len(chasis_list)}")
    if not chasis_list:
        return {"phase": phase_name, "moved": 0, "total": len(tarjetas), "coincidencias": [], "no_sql": []}

    df_sql, chasis_no_sql = obtener_datos_sql_por_chasis(chasis_list)
    mapa_sql = {r["CHASIS"]: r["FECHA_CONFIRMADA"] for _, r in (df_sql.iterrows() if df_sql is not None and not df_sql.empty else [])}

    coincidencias = []
    actualizadas = 0

    for t in tarjetas:
        chasis = t["chasis"]
        fecha_pipefy = t["fecha_inst"]
        fecha_sql = mapa_sql.get(chasis, pd.NaT)

        log(f"🟨 {chasis or '(sin chasis)'} | Pipefy: {_fmt(fecha_pipefy)} | SQL: {_fmt(fecha_sql)}")
        if is_placeholder_1900(fecha_sql):
            log("⛔ SQL=1900-01-01 → se omite (placeholder).")
            continue

        if esta_en_rango(fecha_pipefy, fecha_sql, dias=RANGO_DIAS):
            ok, detalle = marcar_condiciones_fase_actual(t["id"], t["current_phase_id"], fecha_sql)
            if ok:
                actualizadas += 1
                log("✅ Campos de fase actual marcados (incluye 'Fecha carta ins' con hora).")
            else:
                log(f"⚠️ No se pudieron marcar los campos: {detalle}")
            coincidencias.append({
                "chasis": chasis,
                "card_id": t["id"],
                "title": t["title"],
                "pipefy": _fmt(fecha_pipefy),
                "sql": _fmt(fecha_sql),
                "updated_fields": ok,
                "detalle": "" if ok else detalle
            })
        else:
            log("⛔ Fechas fuera de rango o no coinciden.")

    # export CSV (solo los que pasaron validación/actualizados)
    rows = []
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in coincidencias:
        if r.get("updated_fields"):
            rows.append({
                "run_at": run_at,
                "phase": phase_name,
                "chasis": r.get("chasis"),
                "card_id": r.get("card_id"),
                "title": r.get("title"),
                "pipefy": r.get("pipefy"),
                "sql": r.get("sql"),
                "updated_fields": r.get("updated_fields"),
                "detalle": r.get("detalle","")
            })
    short = "z1" if "z1" in phase_name.lower() else "z2" if "z2" in phase_name.lower() else "other"
    out_path = DATA_DIR / f"results_{short}.csv"
    if rows:
        df_out = pd.DataFrame(rows)
        if out_path.exists():
            df_out.to_csv(out_path, index=False, mode="a", header=False, encoding="utf-8-sig")
        else:
            df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
        log(f"💾 CSV guardado: {out_path}")
    else:
        log("ℹ️ No hubo coincidencias validadas para exportar CSV.")

    log(f"🎯 [{phase_name}] Marcadas: {actualizadas} / {len(tarjetas)}")
    return {"phase": phase_name, "moved": actualizadas, "total": len(tarjetas), "coincidencias": coincidencias, "no_sql": chasis_no_sql}

def run_both_phases(log: Callable[[str], None]) -> Dict[str, any]:
    res1 = run_phase(Z1_NAME, log)
    res2 = run_phase(Z2_NAME, log)
    return {"z1": res1, "z2": res2}
