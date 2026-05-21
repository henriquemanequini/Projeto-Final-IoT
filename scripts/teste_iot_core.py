"""
Teste minimo AWS IoT Core - Publicar evento de vaga
====================================================

Valida que:
1. Os certificados X.509 do professor funcionam
2. A conexao TLS na porta 443 fura qualquer firewall
3. O payload chega no IoT Core
4. O IoT Rule do professor joga no Timestream

Roda de qualquer PC (casa, lab, qualquer wifi). Nao precisa Mosquitto local,
EC2, ou abrir portas. So precisa de internet e os certs em certs/.

Uso:
    pip install paho-mqtt==1.6.1
    python scripts/teste_iot_core.py

Depois, pra ver se chegou no banco:
    python scripts/teste_timestream.py
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import uuid
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERRO: paho-mqtt nao instalado. Roda: pip install paho-mqtt==1.6.1")
    sys.exit(1)

# Carrega .env se disponivel (vem com uvicorn[standard])
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Config (broker e cert vem do professor)
# ---------------------------------------------------------------------------

BROKER = "aspvpxjmfalxx-ats.iot.us-east-1.amazonaws.com"
PORT = 443
TOPIC = "iot/aula13"  # topico compartilhado da turma - filtramos por device_id

ROOT = Path(__file__).resolve().parent.parent
CERTS_DIR = ROOT / "certs"
CA_FILE = CERTS_DIR / "AmazonRootCA1.pem"
CERT_FILE = CERTS_DIR / "6f963f6ec45fbc59ebb98cf9df943424944b334aec0a18ce0f2e7f5d256530c9-certificate.pem.crt"
KEY_FILE = CERTS_DIR / "6f963f6ec45fbc59ebb98cf9df943424944b334aec0a18ce0f2e7f5d256530c9-private.pem.key"

# device_id identifica o NOSSO grupo no topico compartilhado.
# Usa um valor unico/reconhecivel pra filtrar no Timestream depois.
DEVICE_ID = os.getenv("DEVICE_ID", "estacionamento-henrique")


# ---------------------------------------------------------------------------
# Cores pra log
# ---------------------------------------------------------------------------

class Cor:
    OK = "\033[92m"
    ERR = "\033[91m"
    INFO = "\033[96m"
    WARN = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{Cor.OK}✓ {msg}{Cor.RESET}")


def err(msg: str) -> None:
    print(f"{Cor.ERR}✗ {msg}{Cor.RESET}")


def info(msg: str) -> None:
    print(f"{Cor.INFO}ℹ {msg}{Cor.RESET}")


# ---------------------------------------------------------------------------
# Conexao MQTT com TLS+ALPN (modelo AWS IoT Core)
# ---------------------------------------------------------------------------

conectado = False
connack_rc = None


def montar_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
    ctx.load_verify_locations(cafile=str(CA_FILE))
    ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    return ctx


def on_connect(client, userdata, flags, rc):
    global conectado, connack_rc
    connack_rc = rc
    if rc == 0:
        conectado = True
        ok(f"Conectado ao AWS IoT Core {BROKER}:{PORT}")
    else:
        err(f"CONNACK rejeitado, rc={rc}")


def on_disconnect(client, userdata, rc):
    global conectado
    conectado = False
    info(f"Desconectado (rc={rc})")


def on_publish(client, userdata, mid):
    ok(f"Publicacao confirmada pelo broker (mid={mid})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if sys.platform == "win32":
        os.system("")  # habilita ANSI no Windows

    print()
    print(f"{Cor.BOLD}=== Teste minimo AWS IoT Core ==={Cor.RESET}")
    print(f"  Broker:    {Cor.INFO}{BROKER}:{PORT}{Cor.RESET}")
    print(f"  Topico:    {Cor.INFO}{TOPIC}{Cor.RESET}")
    print(f"  Device ID: {Cor.INFO}{DEVICE_ID}{Cor.RESET}")
    print()

    # Pre-checagens
    info("Conferindo arquivos de cert...")
    for f in (CA_FILE, CERT_FILE, KEY_FILE):
        if not f.exists():
            err(f"Arquivo nao encontrado: {f}")
            return 1
        ok(f"  {f.name}")
    print()

    # Setup do cliente
    client_id = f"estacionamento-test-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id)
    client.tls_set_context(context=montar_ssl_context())
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish

    info(f"Conectando como client_id={client_id}...")
    try:
        client.connect(BROKER, PORT, keepalive=30)
    except Exception as e:
        err(f"Falha na conexao TCP/TLS: {e}")
        return 1

    client.loop_start()

    # Aguarda CONNACK
    for _ in range(20):
        if conectado:
            break
        time.sleep(0.5)

    if not conectado:
        err(f"Nao confirmou conexao em 10s. rc={connack_rc}")
        client.loop_stop()
        client.disconnect()
        return 1

    print()
    info("Publicando 3 eventos de teste...")

    eventos = [
        ("A01", "ocupada"),
        ("A02", "livre"),
        ("A03", "ocupada"),
    ]

    sucesso = 0
    for vaga_id, status in eventos:
        # Payload no formato que o IoT Rule do professor espera (igual ao
        # exemplo dele): device_id + timestamp + measures como campos extras.
        # vaga_id e status entram como measures no Timestream.
        payload = {
            "device_id": DEVICE_ID,
            "timestamp": str(int(time.time())),
            "vaga_id": vaga_id,
            "status": status,
            "evento_id": str(uuid.uuid4()),
        }
        msg = json.dumps(payload)
        result = client.publish(TOPIC, msg, qos=0)
        if result.rc == 0:
            info(f"  → PUBLISH vaga={vaga_id} status={status}")
            sucesso += 1
        else:
            err(f"  Falha publicando {vaga_id} (rc={result.rc})")
        time.sleep(0.3)

    # Aguarda o broker processar
    time.sleep(2)

    client.loop_stop()
    client.disconnect()

    print()
    if sucesso == len(eventos):
        ok(f"Os {sucesso} eventos foram aceitos pelo broker")
        print()
        info("Pro verificar se chegaram no Timestream, rode:")
        print(f"  {Cor.INFO}python scripts/teste_timestream.py{Cor.RESET}")
        print()
        info("Ou abra o dashboard:")
        print(f"  {Cor.INFO}stre