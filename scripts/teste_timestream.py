"""
Teste minimo Timestream - Le as ultimas vagas do estacionamento
================================================================

Conecta no Timestream do prof (SmartSpace.Ocupacao) e mostra as vagas
do nosso DEVICE_ID (que e usado como prefixo: DEVICE_ID-A01, DEVICE_ID-A02, ...).

Schema do banco (descoberto via teste_timestream_debug.py):
    device_id   -> string (a gente codifica vaga aqui: 'DEVICE_ID-VAGA')
    timestamp   -> bigint (unix ms)
    ocupacao    -> bigint (0 = livre, 1 = ocupada)

Uso:
    python scripts/teste_timestream.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import boto3
except ImportError:
    print("ERRO: boto3 nao instalado. Roda: pip install boto3")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
DATABASE = os.getenv("TIMESTREAM_DB", "SmartSpace")
TABLE = os.getenv("TIMESTREAM_TABLE", "Ocupacao")
DEVICE_ID = os.getenv("DEVICE_ID", "estacionamento-henrique")
LIMIT = int(os.getenv("LIMIT", "50"))
DIAS = int(os.getenv("DIAS", "1"))


def status_str(ocupacao: str | int | None) -> str:
    """0 -> livre, 1 -> ocupada, outro -> desconhecido"""
    if ocupacao is None:
        return "desconhecido"
    try:
        return "ocupada" if int(ocupacao) == 1 else "livre"
    except (ValueError, TypeError):
        return str(ocupacao)


def main() -> int:
    if sys.platform == "win32":
        os.system("")

    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        print("ERRO: defina AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY no ambiente.")
        return 1

    print(f"=== Timestream {DATABASE}.{TABLE} (regiao {AWS_REGION}) ===")
    print(f"Filtro: device_id LIKE '{DEVICE_ID}-%', ultimos {DIAS} dia(s), limit {LIMIT}")
    print()

    client = boto3.client(
        "timestream-query",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    # Filtra todas as vagas do NOSSO estacionamento (DEVICE_ID-A01, DEVICE_ID-A02, ...)
    query = f'''
        SELECT *
        FROM "{DATABASE}"."{TABLE}"
        WHERE device_id LIKE '{DEVICE_ID}-%'
          AND time BETWEEN ago({DIAS}d) AND now()
        ORDER BY time DESC
        LIMIT {LIMIT}
    '''

    try:
        response = client.query(QueryString=query)
    except Exception as e:
        print(f"ERRO ao consultar Timestream: {e}")
        return 1

    cols = [c["Name"] for c in response.get("ColumnInfo", [])]
    rows = response.get("Rows", [])

    if not rows:
        print(f"Nenhum dado encontrado pra device_id LIKE '{DEVICE_ID}-%' nas ultimas {DIAS}d.")
        print("Possiveis causas:")
        print("  - O teste_iot_core.py ainda nao foi rodado")
        print("  - Aguarde uns 30s pro IoT Rule processar")
        print("  - DEVICE_ID nao bate com o que foi publicado")
        return 1

    print(f"Encontrados {len(rows)} registros (1 linha por measure no banco):\n")

    # Reagrupa por (time, device_id) ja que cada evento vira 3 linhas (1 por measure)
    agrupado: dict[str, dict] = {}
    for row in rows:
        item = {}
        for i, val in enumerate(row.get("Data", [])):
            item[cols[i]] = val.get("ScalarValue")
        key = f"{item.get('time')}_{item.get('device_id')}"
        if key not in agrupado:
            agrupado[key] = {
                "time": item.get("time"),
 