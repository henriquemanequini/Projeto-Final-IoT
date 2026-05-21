"""
Lista databases e tabelas do Timestream
========================================

Util quando suspeitamos que os dados estao em outra tabela diferente
da que esta no .env. Lista tudo que a IAM key tem permissao de ver,
e pra cada tabela mostra quantos registros tem nos ultimos 7 dias.

Uso:
    python scripts/list_timestream.py
"""

from __future__ import annotations

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


def main() -> int:
    if sys.platform == "win32":
        os.system("")

    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        print("ERRO: AWS creds nao definidos no .env")
        return 1

    # Cliente WRITE pra listar (precisa de DescribeDatabase/ListTables)
    try:
        write_client = boto3.client(
            "timestream-write",
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            region_name=AWS_REGION,
        )
    except Exception as e:
        print(f"ERRO criando cliente: {e}")
        return 1

    query_client = boto3.client(
        "timestream-query",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    print(f"=== Timestream em {AWS_REGION} ===\n")

    # Listar databases
    print("--- Databases ---")
    try:
        dbs_resp = write_client.list_databases()
        dbs = dbs_resp.get("Databases", [])
        if not dbs:
            print("  (vazio ou sem permissao pra listar)")
        for db in dbs:
            print(f"  • {db['DatabaseName']}")
    except Exception as e:
        print(f"  ERRO listando databases: {e}")
        print("  (provavelmente a IAM key so tem permissao de query, nao list)")
        dbs = []

    # Pra cada DB, listar tabelas e contar registros
    for db in dbs:
        db_name = db["DatabaseName"]
        print(f"\n--- Tabelas em '{db_name}' ---")
        try:
            tables_resp = write_client.list_tables(DatabaseName=db_name)
            tables = tables_resp.get("Tables", [])
            if not tables:
                print("  (sem tabelas)")
            for t in tables:
                table_name = t["TableName"]
                # Conta registros nos ultimos 7 dias
                try:
                    q = f'SELECT COUNT(*) FROM "{db_name}"."{table_name}" WHERE time BETWEEN ago(7d) AND now()'
                    qr = query_client.query(QueryString=q)
                    count = qr["Rows"][0]["Data"][0].get("ScalarValue", "?")
                    print(f"  • {table_name}: {count} registros nos ultimos 7d")
                except Exception as e:
                    print(f"  • {table_name}: erro ao contar ({e})")
        except Exception as e:
            print(f"  ERRO listando tabelas: {e}")

    # Caso nao conseguir listar databases, tenta tabelas conhecidas
    if not dbs:
        print("\n--- Tentando tabelas conhecidas / suspeitas ---")
        candidatos = [
            ("iot-eletiva", "iot-2025"),
            ("iot-eletiva", "iot-2026"),
            ("iot-eletiva", "iot-2024"),
            ("iot-eletiva", "aula13"),
        ]
        for db_name, table_name in candidatos:
            try:
                q = f'SELECT COUNT(*) FROM "{db_name}"."{table_name}" WHERE time BETWEEN ago(7d) AND now()'
                qr = query_client.query(QueryString=q)
                count = qr["Rows"][0]["Data"][0].get("ScalarValue", "?")
                print(f"  • {db_name}.{table_name}: {count} registros nos ultimos 7d")
            except Exception as e:
                err = str(e).split(":")[-1].strip()[:80]
                print(f"  • {db_name}.{table_name}: erro ({err})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
