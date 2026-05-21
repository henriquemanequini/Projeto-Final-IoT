"""
Bridge PLC (Modbus TCP) → MQTT (broker AWS EC2)
================================================

Lê o estado das vagas direto do CLP Siemens via Modbus TCP e publica os
eventos no broker Mosquitto rodando na EC2. Mantém estado em memória pra
publicar APENAS quando há mudança (evita flood do broker).

Roda no laptop conectado fisicamente à mesma rede do PLC (parte esquerda
da arquitetura). Não roda na EC2.

Variáveis de ambiente (com defaults de exemplo):
    PLC_IP            = 10.103.16.41        # IP do CLP Siemens na rede local
    PLC_PORT          = 502                 # Porta Modbus TCP padrão
    MQTT_HOST         = 3.89.194.80         # IP público da EC2 do Henrique
    MQTT_PORT         = 1883
    MQTT_USER         = estacionamento
    MQTT_PASSWORD     = <senha forte>       # Pedir pro Henrique
    PI_ID             = laptop-augusto      # Identificador deste dispositivo
    SPOT_PREFIX       = A                   # Prefixo dos vaga_ids (A01..A08)
    INTERVALO_S       = 1                   # Intervalo de polling do PLC
    COIL_INVERSO      = false               # true = True coil significa "ocupada"

Uso:
    pip install pyModbusTCP paho-mqtt
    python plc_to_mqtt.py

    # Ou com config via env vars:
    MQTT_HOST=3.89.194.80 MQTT_PASSWORD='SuaSenha' python plc_to_mqtt.py
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import uuid
from typing import Optional

import paho.mqtt.client as mqtt
from pyModbusTCP.client import ModbusClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("plc_to_mqtt")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLC_IP = os.getenv("PLC_IP", "10.103.16.41")
PLC_PORT = int(os.getenv("PLC_PORT", "502"))
PLC_TIMEOUT = int(os.getenv("PLC_TIMEOUT", "5"))
COIL_OFFSET = int(os.getenv("COIL_OFFSET", str(73 * 8 + 4)))  # = 588
COIL_QTD = int(os.getenv("COIL_QTD", "8"))
COIL_INVERSO = os.getenv("COIL_INVERSO", "false").lower() == "true"

MQTT_HOST = os.getenv("MQTT_HOST", "3.89.194.80")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "estacionamento")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
PI_ID = os.getenv("PI_ID", "laptop-augusto")
SPOT_PREFIX = os.getenv("SPOT_PREFIX", "A")
INTERVALO_S = float(os.getenv("INTERVALO_S", "1"))
TOPICO = f"estacionamento/{PI_ID}/vagas"

# Modo offline: lê o PLC mas NÃO tenta publicar MQTT (útil pra debug
# quando a porta 1883 do Security Group ainda está fechada)
SKIP_MQTT = os.getenv("SKIP_MQTT", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def coil_para_status(coil_value: bool) -> str:
    """
    Converte o booleano lido do CLP em "livre" | "ocupada".

    Convenção atual (assumida): coil True = luz verde acesa = vaga LIVRE.
    Se a convenção do seu CLP for o contrário, defina ``COIL_INVERSO=true``
    nas variáveis de ambiente.
    """
    if COIL_INVERSO:
        return "ocupada" if coil_value else "livre"
    return "livre" if coil_value else "ocupada"


def vaga_id_de(spot_num: int) -> str:
    """SPOT 1 → A01, SPOT 2 → A02, ..."""
    return f"{SPOT_PREFIX}{spot_num:02d}"


def agora_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

def montar_cliente_mqtt() -> mqtt.Client:
    """Cria o cliente MQTT com auth e callbacks de log."""
    cli = mqtt.Client(
        client_id=f"plc-bridge-{PI_ID}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        clean_session=False,
    )
    if MQTT_USER and MQTT_PASSWORD:
        cli.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    def _on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            log.info(f"Conectado ao broker MQTT {MQTT_HOST}:{MQTT_PORT}")
        else:
            log.error(f"Falha na conexão MQTT — reason_code={reason_code}")

    def _on_disconnect(client, userdata, flags, reason_code, properties=None):
        log.warning(f"Desconectado do broker — reason_code={reason_code}")

    cli.on_connect = _on_connect
    cli.on_disconnect = _on_disconnect
    cli.reconnect_delay_set(min_delay=1, max_delay=30)
    return cli


def publicar_evento(cli: Optional[mqtt.Client], vaga_id: str, status: str) -> None:
    """Publica um evento de mudança de estado no tópico padrão.

    Em modo SKIP_MQTT apenas loga o payload que SERIA publicado (útil
    pra Fase 1 — testar só a leitura do CLP sem depender da rede).
    """
    payload = {
        "vaga_id": vaga_id,
        "status": status,
        "timestamp": agora_ms(),
        "pi_id": PI_ID,
        "evento_id": str(uuid.uuid4()),
    }
    msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    if SKIP_MQTT or cli is None:
        log.info(f"[OFFLINE] {TOPICO} → {msg}")
        return

    info = cli.publish(TOPICO, msg, qos=1)
    info.wait_for_publish(timeout=5)
    log.info(f"PUBLISH {TOPICO} → vaga={vaga_id} status={status}")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

class FailedTCPConnection(Exception):
    pass


def main() -> int:
    if not SKIP_MQTT and not MQTT_PASSWORD:
        log.error(
            "Defina MQTT_PASSWORD no ambiente, ou use SKIP_MQTT=true pra modo offline."
        )
        return 1

    log.info(f"Bridge PLC→MQTT iniciando")
    log.info(f"  PLC: {PLC_IP}:{PLC_PORT} (offset={COIL_OFFSET}, qtd={COIL_QTD})")
    if SKIP_MQTT:
        log.info("  MQTT: DESATIVADO (SKIP_MQTT=true) — apenas leitura do CLP")
    else:
        log.info(f"  MQTT: {MQTT_HOST}:{MQTT_PORT} topic={TOPICO}")
    log.info(f"  Convenção: coil True = {coil_para_status(True).upper()}")

    plc = ModbusClient(host=PLC_IP, port=PLC_PORT, timeout=PLC_TIMEOUT)
    cli_mqtt: Optional[mqtt.Client] = None

    parar = False

    def _shutdown(signum, frame):
        nonlocal parar
        log.info("Sinal de parada recebido — encerrando")
        parar = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if not SKIP_MQTT:
        cli_mqtt = montar_cliente_mqtt()
        try:
            cli_mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        except Exception as e:
            log.error(f"Falha ao conectar no broker MQTT: {e}")
            log.error(
                "Dica: se a porta 1883 ainda não foi liberada no Security Group, "
                "rode novamente com SKIP_MQTT=true pra testar só o CLP."
            )
            return 1
        cli_mqtt.loop_start()

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
                log.warning(f"[ciclo {ciclo}] Falha lendo coils — tentando de novo")
                time.sleep(INTERVALO_S)
                continue

            mudancas = 0
            for i, coil in enumerate(coils):
                vaga_id = vaga_id_de(i + 1)
                novo_status = coil_para_status(coil)
                anterior = estado_anterior.get(vaga_id)

                if anterior != novo_status:
                    publicar_evento(cli_mqtt, vaga_id, novo_status)
                    estado_anterior[vaga_id] = novo_status
                    mudancas += 1

            if mudancas == 0 and ciclo % 30 == 0:
                # Heartbeat de log a cada 30 ciclos (se INTERVALO_S=1, a cada 30s)
                log.debug(f"[ciclo {ciclo}] sem mudanças — estado={estado_anterior}")

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
        log.info("Fechando conexões")
        plc.close()
        if cli_mqtt is not None:
            cli_mqtt.loop_stop()
            cli_mqtt.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
