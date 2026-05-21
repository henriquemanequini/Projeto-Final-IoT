"""
Teste minimo Timestream - Le os ultimos eventos do banco
=========================================================

Conecta no Timestream do professor (database "iot-eletiva", tabela "iot-2025")
e mostra os ultimos eventos do nosso device_id. Use logo depois do
teste_iot_core.py pra confirmar que o pipeline funciona end-to-end.

Uso:
    pip install boto3
    set AWS_ACCESS_KEY_ID=...
    set AWS_SECRET_ACCESS_KEY=...
    python scripts/teste_timestream.py
"""

from __future__ import annotations

import json
import os
import sys

try:
    import boto3
except ImportError:
    print("ERRO: boto3 nao instalado. Roda: pip install boto3")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
DATABASE = os.getenv("TIMESTREAM_DB", "iot-eletiva")
TABLE = os.getenv("TIMESTREAM_TABLE", "iot-2025")
DEVICE_ID = os.getenv("DEVICE_ID", "estacionamento-henrique")
LIMIT = int(os.getenv("LIMIT", "30"))
DIAS = int(os.getenv("DIAS", "1"))


def main() -> int:
    if sys.platform == "win32":
        os.system("")

    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        print("ERRO: defina AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY no ambiente.")
        print("  (Use as credenciais que o professor disponibilizou no Blackboard.)")
        return 1

    print(f"=== Timestream {DATABASE}.{TABLE} (regiao {AWS_REGION}) ===")
    print(f"Filtro: device_id='{DEVICE_ID}', ultimos {DIAS} dia(s), limit {LIMIT}")
    print()

    client = boto3.client(
        "timestream-query",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    # Filtra pelo NOSSO device_id pra nao misturar com outros grupos
    query = f'''
        SELECT *
        FROM "{DATABASE}"."{TABLE}"
        WHERE device_id = '{DEVICE_ID}'
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
        print(f"Nenhum dado encontrado pra device_id='{DEVICE_ID}' nas ultimas {DIAS}d.")
        print("Possiveis causas:")
        print("  - O teste_iot_core.py ainda nao foi rodado")
        print("  - O IoT Rule do professor nao esta mapeando esse topico/payload")
        print("  - O device_id no .env nao bate com o que foi publicado")
        return 1

    print(f"Encontrados {len(rows)} registros:\n")

    # Agrupa por time+device_id porque Timestream retorna uma linha por measure
    agrupado: dict[str, dict] = {}
    for row in rows:
        item = {}
        for i, val in enumerate(row.get("Data", [])):
            item[cols[i]] = val.get("ScalarValue")
        key = f"{item.get('time')}_{item.get('device_id')}"
        if key not in agrupado:
            agrupado[key] = {
                "time": item.get("time"),
                "device_id": item.get("device_id"),
            }
        m = item.get("measure_name")
        if m:
            v = item.get("measure_value::double") or item.get("measure_value::varchar")
            agrupado[key][m] = v

    for ev in agrupado.values():
        print(json.dumps(ev, default=str, ensure_ascii=False))

    print()
    print(f"OK - {len(agrupado)} eventos unicos no Timestream pra device_id='{DEVICE_ID}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
