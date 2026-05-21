"""
Bridge PLC (Modbus TCP) -> AWS IoT Core (MQTT/TLS 443)
=======================================================

Substitui o plc_to_mqtt.py. Le o estado das vagas do CLP Siemens e publica
direto no AWS IoT Core do professor. O IoT Rule joga no Timestream
automaticamente, e o dashboard Streamlit le do Timestream.

Vantagens sobre a versao Mosquitto:
- Porta 443 (HTTPS) - fura qualquer firewall corporativo
- TLS+cert X.509 - auth segura, sem senha em texto
- Sem necessidade de EC2/Mosquitto/Worker - infra do professor

Roda no PC do lab (mesma rede do CLP). Nao precisa rodar em nuvem.

Variaveis de ambiente (com defaults):
    PLC_IP            = 10.103.16.41        IP do CLP Siemens
    PLC_PORT          = 502                 Porta Modbus TCP
    COIL_OFFSET       = 588                 Endereco do primeiro coil das vagas
    COIL_QTD          = 8                   Quantidade de vagas
    COIL_INVERSO      = false               true se coil True = "ocupada"
    SPOT_PREFIX       = A                   Prefixo dos vaga_ids (A01..A08)
    INTERVALO_S       = 1                   Polling do PLC em segundos
    DEVICE_ID         = estacionamento-lab  Identificador NOSSO no topico compartilhado
    SKIP_MQTT         = false               true = nao publica, so loga (debug)

Uso (no PC do lab):
    pip install -r requirements.txt
    python scripts/plc_to_iot.py
"""

from __future__ import annotations

import json
import logging
import os
import signal
import ssl
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERRO: paho-mqtt nao instalado. Roda: pip install paho-mqtt==1.6.1")
    sys.exit(1)

try:
    from pyModbusTCP.client import ModbusClient
except ImportError:
    print("ERRO: pyModbusTCP nao instalado. Roda: pip install pyModbusTCP")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("plc_to_iot")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# CLP
PLC_IP = os.getenv("PLC_IP", "10.103.16.41")
PLC_PORT = int(os.getenv("PLC_PORT", "502"))
PLC_TIMEOUT = int(os.getenv("PLC_TIMEOUT", "5"))
COIL_OFFSET = int(os.getenv("COIL_OFFSET", str(73 * 8 + 4)))  # = 588
COIL_QTD = int(os.getenv("COIL_QTD", "8"))
COIL_INVERSO = os.getenv("COIL_INVERSO", "false").lower() == "true"
SPOT_PREFIX = os.getenv("SPOT_PREFIX", "A")
INTERVALO_S = float(os.getenv("INTERVALO_S", "1"))

# AWS IoT Core (config do professor)
BROKER = os.getenv("MQTT_BROKER", "aspvpxjmfalxx-ats.iot.us-east-1.amazonaws.com")
PORT = int(os.getenv("MQTT_PORT", "443"))
TOPIC = os.getenv("MQTT_TOPIC", "iot/aula13")

# Certificados (path relativo ao raiz do projeto)
ROOT = Path(__file__).resolve().parent.parent
CERTS_DIR = Path(os.getenv("CERTS_DIR", str(ROOT / "certs")))
CA_FILE = CERTS_DIR / os.getenv("CA_FILENAME", "AmazonRootCA1.pem")
CERT_FILE = CERTS_DIR / os.getenv(
    "CERT_FILENAME",
    "6f963f6ec45fbc59ebb98cf9df943424944b334aec0a18ce0f2e7f5d256530c9-certificate.pem.crt",
)
KEY_FILE = CERTS_DIR / os.getenv(
    "KEY_FILENAME",
    "6f963f6ec45fbc59ebb98cf9df943424944b334aec0a18ce0f2e7f5d256530c9-private.pem.key",
)

# Identificador do NOSSO grupo no topico compartilhado
DEVICE_ID = os.getenv("DEVICE_ID", "estacionamento-lab")

# Modo offline (debug)
SKIP_MQTT = os.getenv("SKIP_MQTT", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def coil_para_status(coil_value: bool) -> str:
    """
    Converte o booleano lido do CLP em "livre" | "ocupada".

    Convencao padrao: coil True = vaga LIVRE. Defina COIL_INVERSO=true se for
    ao contrario no seu CLP.
    """
    if COIL_INVERSO:
        return "ocupada" if coil_value else "livre"
    return "livre" if coil_value else "ocupada"


def vaga_id_de(spot_num: int) -> str:
    """SPOT 1 -> A01, SPOT 2 -> A02, ..."""
    return f"{SPOT_PREFIX}{spot_num:02d}"


# ---------------------------------------------------------------------------
# MQTT (AWS IoT Core)
# ---------------------------------------------------------------------------

def montar_ssl_context() -> ssl.SSLContext:
    """Cria contexto TLS com ALPN x-amzn-mqtt-ca (padrao IoT Core)."""
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
    ctx.load_verify_locations(cafile=str(CA_FILE))
    ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    return ctx


def montar_cliente() -> mqtt.Client:
    """Cria cliente MQTT autenticado por certificado."""
    client_id = f"plc-bridge-{DEVICE_ID}-{uuid.uuid4().hex[:6]}"
    cli = mqtt.Client(client_id=client_id)
    cli.tls_set_context(context=montar_ssl_context())

    def _on_connect(client, userdata, flags, rc):
        if rc == 0:
            log.info(f"Conectado ao AWS IoT Core {BROKER}:{PORT}")
        else:
            log.error(f"Falha na conexao MQTT - rc={rc}")

    def _on_disconnect(client, userdata, rc):
        log.warning(f"Desconectado do broker (rc={rc})")

    cli.on_connect = _on_connect
    cli.on_disconnect = _on_disconnect
    cli.reconnect_delay_set(min_delay=1, max_delay=30)
    return cli


def publicar_evento(cli: Optional[mqtt.Client], vaga_id: str, status: str) -> None:
    """
    Publica um evento de mudanca de estado no topico do professor.

    Payload no formato esperado pelo IoT Rule:
        device_id, timestamp (unix segundos como string) + measures (vaga_id, status)

    Em SKIP_MQTT=true, so loga o payload que SERIA publicado.
    """
    payload = {
        "device_id": DEVICE_ID,
        "timestamp": str(int(time.time())),
        "vaga_id": vaga_id,
        "status": status,
        "evento_id": str(uuid.uuid4()),
    }
    msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    if SKIP_MQTT or cli is None:
        log.info(f"[OFFLINE] {TOPIC} -> {msg}")
        return

    result = cli.publish(TOPIC, msg, qos=0)
    if result.rc == 0:
        log.info(f"PUBLISH {TOPIC} -> vaga={vaga_id} status={status}")
    else:
        log.error(f"Falha publicando {vaga_id} (rc={result.rc})")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

class FailedTCPConnection(Exception):
    pass


def main() -> int:
    if not SKIP_MQTT:
        for f in (CA_FILE, CERT_FILE, KEY_FILE):
            if not f.exists():
                log.error(f"Arquivo de cert nao encontrado: {f}")
                log.error("Coloque os certs do professor em certs/ no projeto.")
                return 1

    log.info("Bridge PLC->IoT Core iniciando")
    log.info(f"  PLC: {PLC_IP}:{PLC_PORT} (offset={COIL_OFFSET}, qtd={COIL_QTD})")
    if SKIP_MQTT:
        log.info("  MQTT: DESATIVADO (SKIP_MQTT=true)")
    else:
        log.info(f"  IoT Core: {BROKER}:{PORT} topic={TOPIC} device_id={DEVICE_ID}")
    log.info(f"  Convencao: coil True = {coil_para_status(True).upper()}")

    plc = ModbusClient(host=PLC_IP, port=PLC_PORT, timeout=PLC_TIMEOUT)
    cli: Optional[mqtt.Client] = None

    parar = False

    def _shutdown(signum, frame):
        nonlocal parar
        log.info("Sinal de parada recebido - encerrando")
        parar = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if not SKIP_MQTT:
        cli = montar_cliente()
        try:
            cli.connect(BROKER, PORT, keepalive=60)
        except Exception as e:
            log.error(f"Falha ao conectar no IoT Core: {e}")
            log.error(
                "Dica: confirma se os certs existem em certs/ e se a rede "
                "tem internet (porta 443 sempre aberta em qualquer firewall)."
            )
            return 1
        cli.loop_start()

    estado_anterior: dict[str, str] = {}

    try:
        if not plc.open():
            raise FailedTCPConnection

        log.info(f"Conectado ao CLP {PLC_IP}.")
        ciclo = 0

        while not parar and plc.is_open:
            ciclo += 1
            coils = plc.read_coils(COIL_OFFSET, COIL_QTD)

            if coils is None:
                log.warning(f"[ciclo {ciclo}] Falha lendo coils - tentando de novo")
                time.sleep(INTERVALO_S)
                continue

            mudancas = 0
            for i, coil in enumerate(coils):
                vaga_id = vaga_id_de(i + 1)
                novo_status = coil_para_status(coil)
                anterior = estado_anterior.get(vaga_id)

                if anterior != novo_status:
                    publicar_evento(cli, vaga_id, novo_status)
                    estado_anterior[vaga_id] = novo_status
                    mudancas += 1

            if mudancas == 0 and ciclo % 30 == 0:
                log.debug(f"[ciclo {ciclo}] sem mudancas - estado={estado_anterior}")

            time.sleep(INTERVALO_S)

        if not plc.is_open:
            raise FailedTCPConnection

    except FailedTCPConnection:
        log.error(f"Falha conectando no CLP {PLC_IP}.")
        log.error(f"  Erro: {plc.last_error_as_txt}")
        return 1
    except Exception as e:
        log.exception(f"Erro inesperado: {e}")
        return 1
    finally:
        log.info("Fechando conexoes")
        plc.close()
        if cli is not None:
            cli.loop_stop()
            cli.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
