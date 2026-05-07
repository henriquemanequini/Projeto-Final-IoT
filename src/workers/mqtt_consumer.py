"""
Worker MQTT — substitui a Lambda ``atualiza_estado`` no setup self-hosted.

Subscreve no broker Mosquitto local em ``estacionamento/+/vagas`` e grava
cada evento no ``RepositorioVagas`` (default SQLite). Reproduz a mesma
lógica de validação e idempotência da Lambda original.

Execução:
    python -m src.workers.mqtt_consumer
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
from pythonjsonlogger import jsonlogger

from src.api.config import get_settings
from src.api.services.repositorio import RepositorioVagas

# ---------------------------------------------------------------------------
# Logging em JSON estruturado
# ---------------------------------------------------------------------------

log = logging.getLogger("mqtt_consumer")


def _configurar_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Validação do payload
# ---------------------------------------------------------------------------

CAMPOS_OBRIGATORIOS = ("vaga_id", "status", "timestamp", "pi_id")
STATUS_VALIDOS = ("livre", "ocupada")


def validar_payload(payload: dict) -> None:
    """Lança ``ValueError`` se o payload não respeitar o contrato."""
    faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in payload]
    if faltando:
        raise ValueError(f"Campos obrigatórios faltando: {faltando}")
    if payload["status"] not in STATUS_VALIDOS:
        raise ValueError(f"status inválido: {payload['status']!r}")
    if not isinstance(payload["timestamp"], int):
        raise ValueError("timestamp deve ser inteiro (epoch ms)")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class MQTTConsumer:
    """
    Cliente MQTT com reconexão automática (backoff exponencial) e shutdown
    gracioso via SIGTERM/SIGINT.
    """

    BACKOFF_INICIAL = 1.0
    BACKOFF_MAX = 60.0

    def __init__(self) -> None:
        self.settings = get_settings()
        self.repositorio = RepositorioVagas()
        self._parar = threading.Event()
        self._backoff = self.BACKOFF_INICIAL

        self.client = mqtt.Client(
            client_id=self.settings.mqtt_client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            clean_session=False,
        )
        if self.settings.mqtt_user and self.settings.mqtt_password:
            self.client.username_pw_set(
                self.settings.mqtt_user, self.settings.mqtt_password
            )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        # paho já implementa reconexão; controlamos apenas o backoff inicial
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)

    # ------- Callbacks paho ------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._backoff = self.BACKOFF_INICIAL
            client.subscribe(self.settings.mqtt_topic, qos=1)
            log.info(
                "Conectado ao broker MQTT",
                extra={
                    "host": self.settings.mqtt_host,
                    "port": self.settings.mqtt_port,
                    "topic": self.settings.mqtt_topic,
                },
            )
        else:
            log.error(
                "Falha ao conectar no broker MQTT",
                extra={"reason_code": str(reason_code)},
            )

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning(
            "Desconectado do broker MQTT",
            extra={"reason_code": str(reason_code)},
        )

    def _on_message(self, client, userdata, msg):
        inicio = time.time()
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            validar_payload(payload)
            atualizou = self.repositorio.adicionar_evento(
                {
                    "vaga_id": payload["vaga_id"],
                    "status": payload["status"],
                    "timestamp": int(payload["timestamp"]),
                    "pi_id": payload["pi_id"],
                    "evento_id": payload.get("evento_id"),
                }
            )
            latencia_ms = int((time.time() - inicio) * 1000)
            log.info(
                "Evento processado",
                extra={
                    "vaga_id": payload["vaga_id"],
                    "status": payload["status"],
                    "topic": msg.topic,
                    "latencia_ms": latencia_ms,
                    "estado_atualizado": atualizou,
                },
            )
        except json.JSONDecodeError as e:
            log.error(
                "Payload MQTT não é JSON válido",
                extra={"erro": str(e), "topic": msg.topic},
            )
        except ValueError as e:
            log.error(
                "Payload inválido",
                extra={"erro": str(e), "topic": msg.topic},
            )
        except Exception as e:  # noqa: BLE001
            log.exception(
                "Erro inesperado processando mensagem",
                extra={"erro": str(e), "topic": msg.topic},
            )

    # ------- Controle ------------------------------------------------------

    def _conectar_com_backoff(self) -> bool:
        """Tenta conectar; em falha aplica backoff exponencial e retorna False."""
        try:
            self.client.connect(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                keepalive=60,
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.error(
                "Erro conectando no broker; aplicando backoff",
                extra={"erro": str(e), "backoff_s": self._backoff},
            )
            self._parar.wait(timeout=self._backoff)
            self._backoff = min(self._backoff * 2, self.BACKOFF_MAX)
            return False

    def rodar(self) -> None:
        """Loop principal — bloqueia até receber sinal de shutdown."""
        self._instalar_signals()
        log.info(
            "Iniciando worker MQTT",
            extra={
                "host": self.settings.mqtt_host,
                "port": self.settings.mqtt_port,
                "storage": self.settings.storage_efetivo,
            },
        )

        while not self._parar.is_set():
            if not self._conectar_com_backoff():
                continue
            try:
                self.client.loop_forever(retry_first_connection=False)
            except Exception as e:  # noqa: BLE001
                log.error("loop_forever interrompido", extra={"erro": str(e)})

            if not self._parar.is_set():
                self._parar.wait(timeout=self._backoff)
                self._backoff = min(self._backoff * 2, self.BACKOFF_MAX)

        log.info("Worker MQTT finalizado")

    def parar(self, *_: Any) -> None:
        log.info("Sinal de parada recebido — desconectando")
        self._parar.set()
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _instalar_signals(self) -> None:
        signal.signal(signal.SIGTERM, self.parar)
        signal.signal(signal.SIGINT, self.parar)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    settings = get_settings()
    _configurar_logging(settings.log_level)
    consumer = MQTTConsumer()
    consumer.rodar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
