"""
Debug do Timestream - mostra tudo que entra (sem filtro de device_id)
=====================================================================

Usa esse script quando o teste_timestream.py retorna vazio. Mostra:
1. Estrutura do banco (colunas, schema)
2. Todos os device_ids que apareceram nas ultimas horas
3. Os ultimos 50 eventos (qualquer device)
4. Linhas brutas (uma por measure)

Assim a gente confirma se o IoT Rule do professor processou nossa
mensagem ou nao, e quais campos sao realmente aceitos.

Uso:
    python scripts/teste_timestream_debug.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

try:
    import boto3
except ImportError:
    print("ERRO: boto3 nao instalado.")
    sys.exit(1)


AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
DATABASE = os.getenv("TIMESTREAM_DB", "iot-eletiva")
TABLE = os.getenv("TIMESTREAM_TABLE", "iot-2025")
HORAS = int(os.getenv("HORAS", "2"))


def main() -> int:
    if sys.platform == "win32":
        os.system("")

    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        print("ERRO: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY nao definidos.")
        return 1

    print(f"=== Debug Timestream {DATABASE}.{TABLE} (ultimas {HORAS}h) ===\n")

    client = boto3.client(
        "timestream-query",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    # 1) device_ids unicos
    print("--- 1) Device IDs que apareceram (sem filtro) ---")
    q1 = f'''
        SELECT DISTINCT device_id
        FROM "{DATABASE}"."{TABLE}"
        WHERE time BETWEEN ago({HORAS}h) AND now()
    '''
    try:
        r1 = client.query(QueryString=q1)
        devices = [row["Data"][0].get("ScalarValue") for row in r1.get("Rows", [])]
        if devices:
            for d in devices:
                marca = " <-- NOSSO!" if d and "estacionamento" in str(d).lower() else ""
                print(f"  {d}{marca}")
        else:
            print("  (nenhum)")
    except Exception as e:
        print(f"  ERRO: {e}")

    # 2) measure_names que aparecem
    print("\n--- 2) Measures que existem no banco ---")
    q2 = f'''
        SELECT DISTINCT measure_name
        FROM "{DATABASE}"."{TABLE}"
        WHERE time BETWEEN ago({HORAS}h) AND now()
    '''
    try:
        r2 = client.query(QueryString=q2)
        measures = [row["Data"][0].get("ScalarValue") for row in r2.get("Rows", [])]
        if measures:
            for m in measures:
                print(f"  {m}")
        else:
            print("  (nenhum)")
    except Exception as e:
        print(f"  ERRO: {e}")

    # 3) Estrutura geral
    print("\n--- 3) Estrutura das colunas ---")
    q3 = f'''
        SELECT *
        FROM "{DATABASE}"."{TABLE}"
        WHERE time BETWEEN ago({HORAS}h) AND now()
        ORDER BY time DESC
        LIMIT 1
    '''
    try:
        r3 = client.query(QueryString=q3)
        for col in r3.get("ColumnInfo", []):
            print(f"  {col.get('Name')}: {col.get('Type', {}).get('ScalarType', '?')}")
    except Exception as e:
        print(f"  ERRO: {e}")

    # 4) Eventos recentes (qualquer device)
    print(f"\n--- 4) Ultimos 30 registros (qualquer device) ---")
    q4 = f'''
        SELECT *
        FROM "{DATABASE}"."{TABLE}"
        WHERE time BETWEEN ago({HORAS}h) AND now()
        ORDER BY time DESC
        LIMIT 30
    '''
    try:
        r4 = client.query(QueryString=q4)
        cols = [c["Name"] for c in r4.get("ColumnInfo", [])]
        rows = r4.get("Rows", [])
        if not rows:
            print("  (nenhum dado em todo o banco nas ultimas 2h)")
            print("  >>> Significa que o IoT Rule nao gravou NADA recentemente,")
            print("      OU o banco esta mesmo vazio. Confira no console AWS.")
        for row in rows[:30]:
            item = {}
            for i, val in enumerate(row.get("Data", [])):
                item[cols[i]] = val.get("ScalarValue")
            # imprime so colunas com valor
            simples = {k: v for k, v in item.items() if v is not None}
            print(f"  {json.dumps(simples, default=str, ensure_ascii=False)}")
    except Exception as e:
        print(f"  ERRO: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
