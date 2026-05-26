"""
Dashboard Streamlit - Estacionamento Inteligente
=================================================

Le os eventos do AWS Timestream (SmartSpace.Ocupacao) e mostra:
- Status atual de cada vaga (A01..A08)
- Resumo livres/ocupadas/taxa de ocupacao
- Historico de eventos
- Grafico de ocupacao ao longo do tempo

Schema do banco (descoberto via teste_timestream_debug.py):
    device_id   string  -> codificamos vaga aqui: 'DEVICE_ID-VAGA'
    timestamp   bigint  -> unix ms
    ocupacao    bigint  -> 0 = livre, 1 = ocupada

Filtramos por device_id LIKE '<DEVICE_ID>-%' pra ver SO as nossas vagas
(o topico 'iot/aula13' eh compartilhado entre toda a turma).

Uso:
    pip install -r requirements.txt
    python -m streamlit run dashboard/app.py

Acessa em: http://localhost:8501
"""

from __future__ import annotations

import os
from pathlib import Path

# Carrega .env automaticamente (precisa estar antes de boto3 etc)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import boto3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
DATABASE = os.getenv("TIMESTREAM_DB", "SmartSpace")
TABLE = os.getenv("TIMESTREAM_TABLE", "Ocupacao")
DEVICE_ID = os.getenv("DEVICE_ID", "estacionamento-henrique")
NUM_VAGAS = int(os.getenv("NUM_VAGAS", "8"))
SPOT_PREFIX = os.getenv("SPOT_PREFIX", "A")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_client():
    """Cria cliente Timestream uma unica vez por sessao."""
    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        st.error(
            "Credenciais AWS nao definidas. "
            "Configure AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY no .env."
        )
        st.stop()
    return boto3.client(
        "timestream-query",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )


def vaga_de(device_id: str) -> str:
    """Extrai vaga do device_id (ex: 'estacionamento-henrique-A01' -> 'A01')."""
    return device_id.rsplit("-", 1)[-1] if "-" in device_id else device_id


def status_de(ocupacao_val) -> str:
    """0 -> livre, 1 -> ocupada"""
    if ocupacao_val is None or ocupacao_val == "":
        return "desconhecido"
    try:
        return "ocupada" if int(ocupacao_val) == 1 else "livre"
    except (ValueError, TypeError):
        return "desconhecido"


@st.cache_data(ttl=5)
def query_eventos(horas: int = 24, limit: int = 500) -> pd.DataFrame:
    """
    Le os ultimos eventos do Timestream e retorna um DataFrame com
    uma linha por evento: time, device_id, vaga_id (derivada), ocupacao, status.

    O Timestream guarda 1 row por measure, entao reagrupamos por
    time + device_id pra montar o evento completo.
    """
    client = get_client()
    query = f'''
        SELECT *
        FROM "{DATABASE}"."{TABLE}"
        WHERE device_id LIKE '{DEVICE_ID}-%'
          AND time BETWEEN ago({horas}h) AND now()
        ORDER BY time DESC
        LIMIT {limit}
    '''

    try:
        response = client.query(QueryString=query)
    except Exception as e:
        st.error(f"Erro consultando Timestream: {e}")
        return pd.DataFrame()

    cols = [c["Name"] for c in response.get("ColumnInfo", [])]
    rows = response.get("Rows", [])

    grouped: dict[str, dict] = {}
    for row in rows:
        item = {}
        for i, val in enumerate(row.get("Data", [])):
            item[cols[i]] = val.get("ScalarValue")
        key = f"{item.get('time')}_{item.get('device_id')}"
        if key not in grouped:
            grouped[key] = {
                "time": item.get("time"),
                "device_id": item.get("device_id"),
            }
        measure_name = item.get("measure_name")
        if measure_name:
            valor = (
                item.get("measure_value::bigint")
                or item.get("measure_value::varchar")
                or item.get("measure_value::double")
            )
            grouped[key][measure_name] = valor

    if not grouped:
        return pd.DataFrame()

    df = pd.DataFrame(grouped.values())
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time", ascending=False)

    # Deriva vaga_id e status a partir do device_id e ocupacao
    if "device_id" in df.columns:
        df["vaga_id"] = df["device_id"].apply(vaga_de)
    if "ocupacao" in df.columns:
        df["status"] = df["ocupacao"].apply(status_de)
    else:
        df["status"] = "desconhecido"

    return df


def estado_atual_vagas(df_eventos: pd.DataFrame) -> dict[str, dict]:
    """Reconstroi o estado atual de cada vaga pegando o evento mais recente."""
    estado: dict[str, dict] = {}

    for i in range(1, NUM_VAGAS + 1):
        vaga_id = f"{SPOT_PREFIX}{i:02d}"
        estado[vaga_id] = {
            "vaga_id": vaga_id,
            "status": "desconhecido",
            "ultimo_evento": None,
        }

    if df_eventos.empty or "vaga_id" not in df_eventos.columns:
        return estado

    for _, row in df_eventos.iterrows():
        vaga_id = row.get("vaga_id")
        if not vaga_id:
            continue
        if vaga_id in estado and estado[vaga_id]["status"] == "desconhecido":
            estado[vaga_id] = {
                "vaga_id": vaga_id,
                "status": row.get("status", "desconhecido"),
                "ultimo_evento": row.get("time"),
            }

    return estado


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Estacionamento IoT", page_icon="🅿️", layout="wide")

st.title("🅿️ Estacionamento Inteligente")
st.caption(
    f"Device prefix: `{DEVICE_ID}-*` · "
    f"Banco: `{DATABASE}.{TABLE}` · Topico: `iot/aula13`"
)

with st.sidebar:
    st.header("Filtros")
    horas = st.slider("Janela (horas)", 1, 168, 24)
    limit = st.slider("Limite de eventos", 50, 2000, 500, step=50)
    auto_refresh = st.toggle("Auto refresh", False)
    intervalo = st.slider("Intervalo (s)", 2, 60, 10) if auto_refresh else None

    st.divider()
    if st.button("Atualizar agora", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


df = query_eventos(horas=horas, limit=limit)

if df.empty:
    st.warning(
        f"Nenhum evento encontrado para `device_id LIKE {DEVICE_ID}-%` "
        f"nas ultimas {horas}h. Verifique se o bridge esta rodando."
    )
    st.stop()


estado = estado_atual_vagas(df)
livres = sum(1 for v in estado.values() if v["status"] == "livre")
ocupadas = sum(1 for v in estado.values() if v["status"] == "ocupada")
taxa = (ocupadas / max(NUM_VAGAS, 1)) * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total de vagas", NUM_VAGAS)
c2.metric("Livres", livres)
c3.metric("Ocupadas", ocupadas)
c4.metric("Taxa de ocupacao", f"{taxa:.0f}%")

st.divider()

st.subheader("Status atual das vagas")

cols_per_row = 4
for row_start in range(0, NUM_VAGAS, cols_per_row):
    cols = st.columns(cols_per_row)
    for i, col in enumerate(cols):
        vaga_idx = row_start + i + 1
        if vaga_idx > NUM_VAGAS:
            break
        vaga_id = f"{SPOT_PREFIX}{vaga_idx:02d}"
        info = estado[vaga_id]
        status = info["status"]
        ultimo = info["ultimo_evento"]

        if status == "livre":
            cor = "🟢"
            bg = "rgba(0, 200, 0, 0.15)"
        elif status == "ocupada":
            cor = "🔴"
            bg = "rgba(255, 50, 50, 0.18)"
        else:
            cor = "⚪"
            bg = "rgba(150, 150, 150, 0.15)"

        ultimo_txt = (
            ultimo.strftime("%H:%M:%S") if isinstance(ultimo, pd.Timestamp) else "—"
        )

        col.markdown(
            f"""
            <div style="background:{bg};border-radius:12px;padding:18px;
                        text-align:center;border:1px solid rgba(255,255,255,0.1);">
                <div style="font-size:32px;">{cor}</div>
                <div style="font-size:22px;font-weight:600;">{vaga_id}</div>
                <div style="opacity:0.7;text-transform:uppercase;font-size:13px;">{status}</div>
                <div style="opacity:0.5;font-size:11px;margin-top:6px;">ult: {ultimo_txt}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

st.subheader("Eventos por minuto")

if not df.empty and "status" in df.columns:
    df_grafico = df.sort_values("time").copy()
    df_grafico["ocupada_int"] = (df_grafico["status"] == "ocupada").astype(int)
    df_grafico["livre_int"] = (df_grafico["status"] == "livre").astype(int)
    df_grafico = df_grafico.set_index("time")
    contagem = (
        df_grafico.groupby(pd.Grouper(freq="1min"))
        .agg(ocupada=("ocupada_int", "sum"), livre=("livre_int", "sum"))
        .reset_index()
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=contagem["time"], y=contagem["ocupada"],
        name="ocupada", line=dict(color="#ff4d4d", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=contagem["time"], y=contagem["livre"],
        name="livre", line=dict(color="#33cc33", width=2),
    ))
    fig.update_layout(
        height=350, margin=dict(t=20, b=20, l=10, r=10),
        xaxis_title="", yaxis_title="Eventos por minuto",
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Distribuicao de eventos por vaga")
if "vaga_id" in df.columns:
    dist = df.groupby(["vaga_id", "status"]).size().reset_index(name="qtd")
    fig2 = px.bar(
        dist, x="vaga_id", y="qtd", color="status",
        color_discrete_map={"ocupada": "#ff4d4d", "livre": "#33cc33"},
        labels={"qtd": "Eventos", "vaga_id": "Vaga"},
    )
    fig2.update_layout(height=300, margin=dict(t=20, b=20, l=10, r=10))
    st.plotly_chart(fig2, use_container_width=True)

with st.expander(f"Historico bruto ({len(df)} eventos)"):
   