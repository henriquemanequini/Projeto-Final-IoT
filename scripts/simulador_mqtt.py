"""
Simulador MQTT — Substitui o PC do lab para validação end-to-end.

Este script SIMULA o publisher do laboratório:
- Conecta no broker MQTT da EC2 da AWS (pela internet)
- Publica eventos de vagas em formato idêntico ao plc_to_mqtt.py
- Não precisa de CLP, nem rede do Insper, nem hardware
- Pode rodar do PC pessoal, de qualquer lugar com internet

Uso:
    pip install paho-mqtt
    set MQTT_HOST=3.89.194.80
    set MQTT_PASSWORD=<senha do broker>
    python scripts/simulador_mqtt.py

Modo manual (publica apenas 3 eventos e sai):
    set MODO=manual
    python scripts/simulador_mqtt.py

Modo contínuo (publica aleatoriamente, intervalo configurável):
    set MODO=continuo
    set INTERVALO_S=5
    python scripts/simulador_mqtt.py
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
import uuid
from typing import Optional

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Config (via env vars)
# ---------------------------------------------------------------------------

MQTT_HOST = os.getenv("MQTT_HOST", "3.89.194.80")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "estacionamento")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
PI_ID = os.getenv("PI_ID", "simulador-casa")
NUM_VAGAS = int(os.getenv("NUM_VAGAS", "8"))
SPOT_PREFIX = os.getenv("SPOT_PREFIX", "A")
MODO = os.getenv("MODO", "manual").lower()  # "manual" | "continuo"
INTERVALO_S = float(os.getenv("INTERVALO_S", "5"))

TOPICO = f"estacionamento/{PI_ID}/vagas"

# ---------------------------------------------------------------------------
# Logging colorido (funciona no PowerShell e CMD modernos)
# ---------------------------------------------------------------------------

class Cores:
    VERDE = "\033[92m"
    AMARELO = "\033[93m"
    VERMELHO = "\033[91m"
    AZUL = "\033[94m"
    CIANO = "\033[96m"
    RESET = "\033[0m"
    NEGRITO = "\033[1m"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("simulador")


def log_ok(msg: str) -> None:
    log.info(f"{Cores.VERDE}✓ {msg}{Cores.RESET}")


def log_erro(msg: str) -> None:
    log.error(f"{Cores.VERMELHO}✗ {msg}{Cores.RESET}")


def log_info(msg: str) -> None:
    log.info(f"{Cores.CIANO}ℹ {msg}{Cores.RESET}")


def log_publish(vaga_id: str, status: str) -> None:
    cor = Cores.AMARELO if status == "ocupada" else Cores.VERDE
    log.info(
        f"{Cores.AZUL}→ PUBLISH{Cores.RESET} "
        f"vaga={Cores.NEGRITO}{vaga_id}{Cores.RESET} "
        f"status={cor}{status}{Cores.RESET}"
    )


# ---------------------------------------------------------------------------
# Cliente MQTT
# ---------------------------------------------------------------------------

conectado = False


def montar_cliente() -> mqtt.Client:
    global conectado

    cli = mqtt.Client(
        client_id=f"simulador-{PI_ID}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        clean_session=True,
    )
    cli.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    def _on_connect(client, userdata, flags, reason_code, properties=None):
        global conectado
        if reason_code == 0 or (hasattr(reason_code, "value") and reason_code.value == 0):
            conectado = True
            log_ok(f"Conectado ao broker {MQTT_HOST}:{MQTT_PORT}")
        else:
            log_erro(f"Conexão recusada — reason_code={reason_code}")

    def _on_disconnect(client, userdata, flags, reason_code, properties=None):
        global conectado
        conectado = False
        log_erro(f"Desconectado do broker — reason_code={reason_code}")

    cli.on_connect = _on_connect
    cli.on_disconnect = _on_disconnect
    return cli


def publicar(cli: mqtt.Client, vaga_id: str, status: str) -> bool:
    """Publica um evento. Retorna True se confirmado pelo broker."""
    payload = {
        "vaga_id": vaga_id,
        "status": status,
        "timestamp": int(time.time() * 1000),
        "pi_id": PI_ID,
        "evento_id": str(uuid.uuid4()),
    }
    msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    info = cli.publish(TOPICO, msg, qos=1)
    try:
        info.wait_for_publish(timeout=5)
        log_publish(vaga_id, status)
        return True
    except RuntimeError as e:
        log_erro(f"Falha publicando {vaga_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Modos de operação
# ---------------------------------------------------------------------------

def modo_manual(cli: mqtt.Client) -> int:
    """Publica 3 eventos sequenciais e mostra como verificar."""
    log_info("Modo MANUAL: publicando 3 eventos de teste")
    print()

    eventos = [
        (f"{SPOT_PREFIX}01", "ocupada"),
        (f"{SPOT_PREFIX}02", "livre"),
        (f"{SPOT_PREFIX}03", "ocupada"),
    ]

    sucesso = 0
    for vaga_id, status in eventos:
        if publicar(cli, vaga_id, status):
            sucesso += 1
        time.sleep(0.5)

    print()
    if sucesso == len(eventos):
        log_ok(f"Todos os {sucesso} eventos foram entregues ao broker")
        print()
        log_info("Pra verificar do lado da AWS, rode na EC2:")
        print(f"  {Cores.CIANO}curl http://localhost:8000/v1/vagas | python3 -m json.tool{Cores.RESET}")
        print(f"  {Cores.CIANO}sqlite3 ~/estacionamento-iot/vagas.db \"SELECT * FROM vagas_estado WHERE pi_id='{PI_ID}';\"{Cores.RESET}")
        print()
        log_info("Pra verificar via API pública (do seu navegador):")
        print(f"  {Cores.CIANO}http://{MQTT_HOST}:8000/v1/vagas{Cores.RESET}")
        return 0
    else:
        log_erro(f"Só {sucesso}/{len(eventos)} eventos foram entregues")
        return 1


def modo_continuo(cli: mqtt.Client) -> int:
    """Roda alternando estados aleatoriamente até Ctrl+C."""
    global conectado
    log_info(f"Modo CONTÍNUO: mudando 1 vaga aleatória a cada {INTERVALO_S}s")
    log_info("Pra parar: Ctrl+C")
    print()

    estado = {
        f"{SPOT_PREFIX}{i:02d}": "livre" for i in range(1, NUM_VAGAS + 1)
    }
    parar = False

    def _shutdown(signum, frame):
        nonlocal parar
        log_info("Parando…")
        parar = True

    signal.signal(signal.SIGINT, _shutdown)

    total = 0
    while not parar:
        vaga_id = random.choice(list(estado.keys()))
        novo = "ocupada" if estado[vaga_id] == "livre" else "livre"
        estado[vaga_id] = novo
        if publicar(cli, vaga_id, novo):
            total += 1
        time.sleep(INTERVALO_S)

    print()
    log_ok(f"Total de eventos publicados nesta sessão: {total}")
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    # Habilita ANSI no Windows
    if sys.platform == "win32":
        os.system("")

    print()
    print(f"{Cores.NEGRITO}=== Simulador MQTT — Estacionamento IoT ==={Cores.RESET}")
    print(f"  Broker:  {Cores.CIANO}{MQTT_HOST}:{MQTT_PORT}{Cores.RESET}")
    print(f"  User:    {Cores.CIANO}{MQTT_USER}{Cores.RESET}")
    print(f"  Tópico:  {Cores.CIANO}{TOPICO}{Cores.RESET}")
    print(f"  Modo:    {Cores.CIANO}{MODO}{Cores.RESET}")
    print()

    if not MQTT_PASSWORD:
        log_erro("MQTT_PASSWORD não foi definida. Configure antes de rodar:")
        print(f'  {Cores.CIANO}set MQTT_PASSWORD=<senha>{Cores.RESET}  (CMD)')
        print(f'  {Cores.CIANO}$env:MQTT_PASSWORD="<senha>"{Cores.RESET}  (PowerShell)')
        return 1

    cli = montar_cliente()
    log_info(f"Tentando conectar em {MQTT_HOST}:{MQTT_PORT}…")

    try:
        cli.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as e:
        log_erro(f"Falha de TCP/IP: {e}")
        print()
        log_info("Possíveis causas:")
        print("  - Sua rede bloqueia a porta 1883 (típico de Wi-Fi corporativo)")
        print("  - O Security Group da AWS não está aberto")
        print("  - O IP do broker está errado")
        return 1

    cli.loop_start()

    # Aguarda confirmação de conexão (até 10s)
    for _ in range(20):
        if conectado:
            break
        time.sleep(0.5)

    if not conectado:
        log_erro("Não confirmou conexão em 10s. Auth pode ter falhado.")
        cli.loop_stop()
        cli.disconnect()
        return 1

    print()
    try:
        if MODO == "continuo":
            ret = modo_continuo(cli)
        else:
            ret = modo_manual(cli)
    finally:
        cli.loop_stop()
        cli.disconnect()

    return ret


if __name__ == "__main__":
    sys.exit(main())
