# odbc.py
# -*- coding: utf-8 -*-
import os, re, unicodedata, json
from datetime import datetime
import requests
import pyodbc
import pandas as pd
from dotenv import load_dotenv

# =========================
# Carga .env
# =========================
load_dotenv()

API_URL     = "https://api.pipefy.com/graphql"
PIPEFY_TOKEN= os.getenv("PIPEFY_TOKEN", "")
PIPE_ID     = int(os.getenv("PIPE_ID", "0"))
PHASES      = [p.strip() for p in os.getenv("PHASES", "").split(",") if p.strip()]

SQL_DRIVER   = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
SQL_SERVER   = os.getenv("SQL_SERVER", "")
SQL_DATABASE = os.getenv("SQL_DATABASE", "")
SQL_USER     = os.getenv("SQL_USER", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
RANGO_DIAS   = int(os.getenv("RANGO_DIAS", "2"))

HEADERS = {
    "Authorization": f"Bearer {PIPEFY_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Field IDs/labels de Pipefy
CHASIS_FIELD_ID = "chasis"
FECHA_FIELD_IDS = ["confirme_fecha_1", "confirme_fecha", "fecha_deseada_de_instalaci_n"]  # prioridad para leer fecha desde la tarjeta

# Campos a marcar en la FASE ACTUAL (NO se modifica Supervisor)
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

# =========================
# Helpers
# =========================
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
    # DD/MM/YYYY
    try:
        return pd.to_datetime(s, format="%d/%m/%Y", errors="raise")
    except Exception:
        pass
    # genérico con/sin dayfirst
    for dayfirst in (True, False):
        try:
            return pd.to_datetime(s, errors="raise", dayfirst=dayfirst, utc=False)
        except Exception:
            pass
    # ISO con hora -> tomar fecha
    if "T" in s:
        try:
            return pd.to_datetime(s.split("T")[0], errors="coerce", dayfirst=False)
        except Exception:
            return pd.NaT
    return pd.NaT

def _fmt(dt):
    return dt.strftime("%Y-%m-%d") if pd.notna(dt) else "NaT"

def esta_en_rango(fecha1, fecha2, dias=2):
    if pd.isna(fecha1) or pd.isna(fecha2):
        return False
    try:
        return abs((fecha1.date() - fecha2.date()).days) <= dias
    except Exception:
        return False

def is_placeholder_1900(dt):
    if isinstance(dt, pd.Timestamp) and not pd.isna(dt):
        return dt.date() == datetime(1900, 1, 1).date()
    return False

def gq(query: str, variables: dict | None = None):
    r = requests.post(API_URL, json={"query": query, "variables": variables or {}}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]

# =========================
# Pipefy (queries)
# =========================
def obtener_id_fase(pipe_id, nombre_fase):
    q = f"""query {{
      pipe(id:{pipe_id}) {{
        phases {{ id name }}
      }}
    }}"""
    d = gq(q)
    for f in d["pipe"]["phases"]:
        if f["name"] == nombre_fase:
            return f["id"]
    return None

def obtener_tarjetas_y_chasis(fase_id):
    tarjetas, chasis_list = [], []
    cursor = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        q = f"""query {{
          phase(id:{fase_id}) {{
            cards(first:50{after}) {{
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
        cards_data = d["phase"]["cards"]

        for edge in cards_data["edges"]:
            card = edge["node"]
            by_id = {}
            for f in card["fields"]:
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
                "id": card["id"],
                "title": card["title"],
                "chasis": chasis_val,
                "fecha_inst": fecha_inst,
                "current_phase_id": (card.get("current_phase") or {}).get("id"),
                "current_phase_name": (card.get("current_phase") or {}).get("name"),
            })
            if chasis_val:
                chasis_list.append(chasis_val)

        if not cards_data["pageInfo"]["hasNextPage"]:
            break
        cursor = cards_data["pageInfo"]["endCursor"]

    return tarjetas, sorted(set(chasis_list))

# ---------- Campos de la FASE ACTUAL ----------
def get_phase_fields_map(phase_id: str):
    q = """query($id:ID!){
      phase(id:$id){
        id name
        fields{ id label type }
      }
    }"""
    d = gq(q, {"id": str(phase_id)})
    fields = d["phase"]["fields"] or []
    mp = {}
    for f in fields:
        mp[_norm(f.get("label",""))] = (f["id"], f.get("label",""), f.get("type",""))
    return mp, d["phase"]["name"]

def resolver_field_ids(mp_labels: dict) -> dict:
    res = {}
    for clave, variantes in OBJETIVOS_FASE_ACTUAL.items():
        fid = None
        for v in variantes:
            fid_label = mp_labels.get(_norm(v))
            if fid_label:
                fid = fid_label[0]
                break
        res[clave] = fid
    return res

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
    try:
        data = r.json()
    except Exception:
        return False, {"message": f"Respuesta no JSON: {r.text[:200]}"}
    if (not ok) or ("errors" in data):
        return False, data
    payload = data.get("data", {}).get("updateFieldsValues", {})
    if not payload.get("success", False):
        return False, payload
    return True, payload

def _formato_para_field_date(dt: pd.Timestamp, field_type: str) -> str:
    # Si el campo es datetime, enviamos fecha y HORA
    if (field_type or "").lower() == "datetime":
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return dt.strftime("%Y-%m-%d")

def marcar_condiciones_fase_actual(card_id: str, phase_id: str, fecha_sql: pd.Timestamp) -> tuple[bool, str]:
    """Marca Instalación/Carta/Mover + 'Fecha carta ins' con FECHA_CONFIRMADA (con hora si aplica)."""
    try:
        mp, _ = get_phase_fields_map(phase_id)
    except Exception as e:
        return False, f"No se pudo leer campos de la fase actual: {e}"

    ids = resolver_field_ids(mp)
    valores = []
    if ids.get("instalacion_ejecutada"): valores.append({"fieldId": ids["instalacion_ejecutada"], "value": "Si"})
    if ids.get("carta_confirmada"):      valores.append({"fieldId": ids["carta_confirmada"],      "value": "Si"})
    if ids.get("mover_siguiente"):       valores.append({"fieldId": ids["mover_siguiente"],       "value": "Si"})

    # Fecha carta ins (con hora real si el tipo es datetime)
    if ids.get("fecha_carta_ins") and pd.notna(fecha_sql):
        # buscar type
        fecha_field_type = None
        for _, triple in mp.items():
            if triple[0] == ids["fecha_carta_ins"]:
                fecha_field_type = triple[2]
                break
        valores.append({
            "fieldId": ids["fecha_carta_ins"],
            "value": _formato_para_field_date(fecha_sql, fecha_field_type or "datetime")
        })

    if not valores:
        return False, "No se resolvió ningún field_id en la fase actual."

    ok, resp = update_fields_values(card_id, valores)

    # Fallback de formato por si el campo exige otra convención
    if (not ok) and ids.get("fecha_carta_ins") and pd.notna(fecha_sql):
        if (fecha_field_type or "").lower() == "datetime":
            fallback_fecha = fecha_sql.strftime("%d/%m/%Y %H:%M")
        else:
            fallback_fecha = fecha_sql.strftime("%d/%m/%Y")
        otros = [v for v in valores if v["fieldId"] != ids["fecha_carta_ins"]]
        ok2, resp2 = update_fields_values(card_id, otros + [{"fieldId": ids["fecha_carta_ins"], "value": fallback_fecha}])
        if ok2:
            ok, resp = ok2, resp2

    if not ok:
        return False, f"Error updateFieldsValues: {resp}"
    return True, "Actualizado."

# =========================
# SQL
# =========================
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
      SELECT LTRIM(RTRIM(UPPER(CHASIS))) AS CHASIS, FECHA_CONFIRMADA
      FROM [dbo].[xcvisContRec]
      WHERE CHASIS IN ({lista})
        AND TIPO_DOCUMENTO = 'Carta instalación (I)'
        AND STATUS_DOCUMENTO NOT LIKE '%cancelada%'
        AND Tipo_comision IN ('INSTALADOR', 'Sin comisionista')
        AND politica_vta <> 'Alarmas'
    ),
    rn AS (
      SELECT CHASIS, FECHA_CONFIRMADA,
             ROW_NUMBER() OVER (PARTITION BY CHASIS ORDER BY FECHA_CONFIRMADA DESC) AS rk
      FROM base
    )
    SELECT CHASIS, FECHA_CONFIRMADA
    FROM rn
    WHERE rk = 1;
    """
    try:
        df = pd.read_sql(q, conn)
    except Exception as e:
        print("❌ Error al ejecutar query SQL:", e)
        return pd.DataFrame(columns=["CHASIS", "FECHA_CONFIRMADA"])
    if df.empty:
        return df
    df["CHASIS"] = df["CHASIS"].astype(str).str.strip().str.upper()
    df["FECHA_CONFIRMADA"] = pd.to_datetime(df["FECHA_CONFIRMADA"], errors="coerce")  # mantiene HORA
    return df[["CHASIS", "FECHA_CONFIRMADA"]]

def obtener_datos_sql_por_chasis(chasis_list, batch_size=800):
    conn = _sql_connect()
    try:
        frames = []
        for i in range(0, len(chasis_list), batch_size):
            lote = chasis_list[i:i+batch_size]
            frames.append(_sql_top_fecha_por_chasis(conn, lote))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        if df.empty:
            chasis_no_sql = sorted(chasis_list)
            print(f"🧾 SQL: 0 chasis con fecha / {len(chasis_list)} solicitados")
            return df, chasis_no_sql

        set_sql = set(df["CHASIS"].unique())
        set_in  = set(chasis_list)
        chasis_no_sql = sorted(list(set_in - set_sql))
        print(f"🧾 SQL: {len(set_sql)} chasis con fecha / {len(set_in)} solicitados")
        if chasis_no_sql:
            print("🔎 (diagnóstico) Chasis sin match en SQL (primeros 12):", ", ".join(chasis_no_sql[:12]))
        return df, chasis_no_sql
    finally:
        try:
            conn.close()
        except Exception:
            pass

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    if not PIPEFY_TOKEN or len(PIPEFY_TOKEN.strip()) < 20:
        raise SystemExit("❌ PIPEFY_TOKEN vacío/incorrecto en el .env.")
    if not PIPE_ID or not PHASES:
        raise SystemExit("❌ PIPE_ID o PHASES faltantes en .env.")

    procesados_rows = []
    ejec_ts = datetime.now()  # timestamp de ejecución
    ejec_str = ejec_ts.strftime("%Y-%m-%d %H:%M:%S")

    for PHASE_NAME in PHASES:
        print("\n" + "="*90)
        print(f"🚀 Fase: {PHASE_NAME}")
        fase_id = obtener_id_fase(PIPE_ID, PHASE_NAME)
        if not fase_id:
            print("❌ No se encontró la fase.")
            continue

        tarjetas, chasis_list = obtener_tarjetas_y_chasis(fase_id)
        print(f"🔎 Tarjetas: {len(tarjetas)} | Chasis únicos: {len(chasis_list)}")
        if not chasis_list:
            print("⛔ No se encontraron chasis.")
            continue

        df_sql, chasis_no_sql = obtener_datos_sql_por_chasis(chasis_list)
        mapa_sql = {row["CHASIS"]: row["FECHA_CONFIRMADA"] for _, row in (df_sql.iterrows() if df_sql is not None and not df_sql.empty else [])}

        actualizadas = 0
        for t in tarjetas:
            chasis = t["chasis"]
            fecha_pipefy = t["fecha_inst"]
            fecha_sql = mapa_sql.get(chasis, pd.NaT)

            print(f"\n🟨 {chasis or '(sin chasis)'} | Pipefy: {_fmt(fecha_pipefy)} | SQL: {_fmt(fecha_sql)}")

            # Omitir placeholder 1900-01-01
            if is_placeholder_1900(fecha_sql):
                print("⛔ SQL=1900-01-01 → se omite marcación (placeholder).")
                continue

            if esta_en_rango(fecha_pipefy, fecha_sql, dias=RANGO_DIAS):
                ok, detalle = marcar_condiciones_fase_actual(t["id"], t["current_phase_id"], fecha_sql)
                if ok:
                    actualizadas += 1
                    print("✅ Campos de fase actual marcados (incluye 'Fecha carta ins' con hora).")
                    # Guardar solo los que pasan la validación
                    dif_dias = abs((fecha_pipefy.date() - fecha_sql.date()).days) if (pd.notna(fecha_pipefy) and pd.notna(fecha_sql)) else None
                    procesados_rows.append({
                        "fase": PHASE_NAME,
                        "card_id": t["id"],
                        "titulo": t["title"],
                        "chasis": chasis,
                        "fecha_pipefy": fecha_pipefy.strftime("%Y-%m-%d"),
                        "fecha_sql": fecha_sql.strftime("%Y-%m-%d %H:%M:%S"),
                        "dif_dias": dif_dias,
                        "fecha_ejecucion": ejec_str
                    })
                else:
                    print(f"⚠️ No se pudieron marcar los campos: {detalle}")
            else:
                print("⛔ Fechas fuera de rango o no coinciden.")

        print(f"\n🎯 Tarjetas con campos marcados en '{PHASE_NAME}': {actualizadas} / {len(tarjetas)}")
        if chasis_no_sql:
            print("🚫 Chasis NO encontrados en SQL (diagnóstico):", ", ".join(chasis_no_sql[:20]), ("..." if len(chasis_no_sql) > 20 else ""))

    # ======= Guardar salidas =======
    if procesados_rows:
        ts_out = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"procesados_{ts_out}.json"
        xlsx_path = f"procesados_{ts_out}.xlsx"

        # JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(procesados_rows, f, ensure_ascii=False, indent=2)

        # Excel
        df_out = pd.DataFrame(procesados_rows)
        try:
            df_out.to_excel(xlsx_path, index=False)
        except Exception as e:
            print("⚠️ No se pudo escribir Excel (¿falta openpyxl?). Error:", e)
            xlsx_path = None

        print("\n📁 Archivos generados:")
        print("   - JSON :", json_path)
        if xlsx_path:
            print("   - Excel:", xlsx_path)
    else:
        print("\nℹ️ No hubo tarjetas que pasaran la validación; no se generaron archivos.")
