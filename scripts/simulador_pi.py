"""
Simulador de Raspberry Pi — Publicador MQTT para AWS IoT Core
================================================================

Simula o Raspberry Pi do projeto de estacionamento inteligente, publicando
eventos de mudança de estado de vagas no AWS IoT Core. Útil para testar
o pipeline cloud (IoT Core → DynamoDB → API → frontend) sem depender
do hardware real.

Modos de operação:
  --modo aleatorio    : muda vagas aleatoriamente (default)
  --modo cenario      : segue um cenário pré-definido (chegadas/saídas realistas)
  --modo burst        : envia N eventos de uma vez (teste de carga)
  --modo heartbeat    : só publica heartbeat (testar detecção de Pi vivo)

Pré-requisitos:
  pip install awsiotsdk

Como obter os arquivos necessários:
  1. AWS Console → IoT Core → Manage → Things → Create thing
  2. Anexa policy permitindo iot:Publish em estacionamento/{pi_id}/*
  3. Baixa: certificate.pem.crt, private.pem.key, AmazonRootCA1.pem
  4. Pega o endpoint em: IoT Core → Settings → Device data endpoint
  5. Coloca os caminhos no .env ou passa via argumento

Uso típico:
  python simulador_pi.py \\
      --endpoint a1b2c3.iot.us-east-1.amazonaws.com \\
      --cert ./certs/certificate.pem.crt \\
      --key ./certs/private.pem.key \\
      --ca ./certs/AmazonRootCA1.pem \\
      --pi-id pi-setor-a \\
      --num-vagas 12 \\
      --intervalo-min 5 \\
      --intervalo-max 30 \\
      --modo aleatorio

Para teste rápido em sandbox (sem certificados, só print):
  python simulador_pi.py --dry-run --num-vagas 5 --intervalo-min 1 --intervalo-max 3
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("simulador_pi")


# =============================================================================
# Modelo de domínio
# =============================================================================

@dataclass
class Vaga:
    """Estado de uma vaga monitorada."""
    vaga_id: str
    status: str = "livre"               # 'livre' | 'ocupada'
    ultima_mudanca: float = field(default_factory=time.time)

    def alternar(self) -> None:
        self.status = "ocupada" if self.status == "livre" else "livre"
        self.ultima_mudanca = time.time()


# =============================================================================
# Cliente MQTT — wrapper que isola o SDK da AWS para permitir dry-run
# =============================================================================

class ClienteMQTT:
    """
    Wrapper sobre awsiotsdk. Quando dry_run=True, apenas imprime o que
    seria publicado, sem precisar de credenciais reais.
    """

    def __init__(
        self,
        endpoint: str,
        client_id: str,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        ca_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self.client_id = client_id
        self.endpoint = endpoint
        self._connection = None

        if dry_run:
            log.warning("Modo DRY-RUN ativo — nada será publicado de verdade.")
            return

        # Importa só quando necessário para permitir dry-run sem dependência
        from awscrt import mqtt
        from awsiot import mqtt_connection_builder

        if not all([cert_path, key_path, ca_path]):
            raise ValueError("cert_path, key_path e ca_path são obrigatórios fora do dry-run.")

        self._mqtt = mqtt
        self._connection = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint,
            cert_filepath=cert_path,
            pri_key_filepath=key_path,
            ca_filepath=ca_path,
            client_id=client_id,
            clean_session=False,
            keep_alive_secs=30,
            on_connection_interrupted=self._on_interrupted,
            on_connection_resumed=self._on_resumed,
        )

    def _on_interrupted(self, connection, error, **kwargs):
        log.warning(f"Conexão interrompida: {error}")

    def _on_resumed(self, connection, return_code, session_present, **kwargs):
        log.info(f"Conexão restabelecida (return_code={return_code})")

    def conectar(self) -> None:
        if self.dry_run:
            return
        log.info(f"Conectando em {self.endpoint} como {self.client_id}...")
        future = self._connection.connect()
        future.result(timeout=10)
        log.info("Conectado ao AWS IoT Core.")

    def publicar(self, topico: str, payload: dict, qos: int = 1) -> None:
        msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        if self.dry_run:
            log.info(f"[DRY-RUN] {topico} → {msg}")
            return

        qos_enum = self._mqtt.QoS.AT_LEAST_ONCE if qos == 1 else self._mqtt.QoS.AT_MOST_ONCE
        self._connection.publish(topic=topico, payload=msg, qos=qos_enum)
        log.info(f"PUBLISH {topico} → {msg}")

    def desconectar(self) -> None:
        if self.dry_run or self._connection is None:
            return
        log.info("Desconectando...")
        self._connection.disconnect().result(timeout=5)


# =============================================================================
# Simulador
# =============================================================================

class SimuladorPi:
    """Orquestra a publicação de eventos seguindo o contrato MQTT v1."""

    def __init__(
        self,
        cliente: ClienteMQTT,
        pi_id: str,
        num_vagas: int = 10,
        prefixo_vaga: str = "A",
    ):
        self.cliente = cliente
        self.pi_id = pi_id
        self.vagas: dict[str, Vaga] = {
            f"{prefixo_vaga}{i:02d}": Vaga(vaga_id=f"{prefixo_vaga}{i:02d}")
            for i in range(1, num_vagas + 1)
        }
        self._inicio = time.time()
        self._parar = threading.Event()

    # ------- Publicação -----------------------------------------------------

    def _publicar_evento_vaga(self, vaga: Vaga) -> None:
        payload = {
            "vaga_id": vaga.vaga_id,
            "status": vaga.status,
            "timestamp": int(time.time() * 1000),
            "pi_id": self.pi_id,
            "evento_id": str(uuid.uuid4()),
        }
        topico = f"estacionamento/{self.pi_id}/vagas"
        self.cliente.publicar(topico, payload, qos=1)

    def _publicar_heartbeat(self) -> None:
        payload = {
            "pi_id": self.pi_id,
            "timestamp": int(time.time() * 1000),
            "uptime_segundos": int(time.time() - self._inicio),
            "vagas_monitoradas": len(self.vagas),
        }
        topico = f"estacionamento/{self.pi_id}/heartbeat"
        self.cliente.publicar(topico, payload, qos=1)

    # ------- Modos ----------------------------------------------------------

    def modo_aleatorio(self, intervalo_min: int, intervalo_max: int) -> None:
        """Muda 1 vaga aleatória a cada intervalo aleatório entre min e max."""
        log.info(
            f"Iniciando modo ALEATÓRIO — {len(self.vagas)} vagas, "
            f"intervalo {intervalo_min}-{intervalo_max}s"
        )
        ultimo_heartbeat = 0.0
        while not self._parar.is_set():
            # Heartbeat a cada 30s
            if time.time() - ultimo_heartbeat > 30:
                self._publicar_heartbeat()
                ultimo_heartbeat = time.time()

            # Muda uma vaga aleatória
            vaga = random.choice(list(self.vagas.values()))
            vaga.alternar()
            self._publicar_evento_vaga(vaga)

            sleep = random.uniform(intervalo_min, intervalo_max)
            self._parar.wait(timeout=sleep)

    def modo_cenario(self) -> None:
        """
        Cenário realista: 90% das vagas começam livres; ao longo de 5 minutos,
        o estacionamento enche progressivamente; depois esvazia.
        """
        log.info("Iniciando modo CENÁRIO — chegada e saída de carros simuladas")

        vagas_lista = list(self.vagas.values())
        random.shuffle(vagas_lista)

        # Fase 1: chegando carros
        log.info("Fase 1/2 — Carros chegando...")
        for vaga in vagas_lista:
            if self._parar.is_set():
                return
            vaga.status = "ocupada"
            self._publicar_evento_vaga(vaga)
            self._parar.wait(timeout=random.uniform(8, 20))

        # Espera com estacionamento cheio
        log.info("Estacionamento cheio. Aguardando 30s...")
        self._parar.wait(timeout=30)

        # Fase 2: saindo carros
        log.info("Fase 2/2 — Carros saindo...")
        random.shuffle(vagas_lista)
        for vaga in vagas_lista:
            if self._parar.is_set():
                return
            vaga.status = "livre"
            self._publicar_evento_vaga(vaga)
            self._parar.wait(timeout=random.uniform(5, 15))

        log.info("Cenário concluído.")

    def modo_burst(self, n_eventos: int) -> None:
        """Envia N eventos seguidos. Útil pra teste de throughput da Rule."""
        log.info(f"Iniciando modo BURST — {n_eventos} eventos sem pausa")
        for i in range(n_eventos):
            if self._parar.is_set():
                return
            vaga = random.choice(list(self.vagas.values()))
            vaga.alternar()
            self._publicar_evento_vaga(vaga)
            if (i + 1) % 50 == 0:
                log.info(f"  ... {i + 1}/{n_eventos} eventos enviados")
        log.info("Burst concluído.")

    def modo_heartbeat(self, intervalo: int) -> None:
        """Só publica heartbeat. Útil pra testar detecção de Pi online/offline."""
        log.info(f"Iniciando modo HEARTBEAT — a cada {intervalo}s")
        while not self._parar.is_set():
            self._publicar_heartbeat()
            self._parar.wait(timeout=intervalo)

    # ------- Controle -------------------------------------------------------

    def parar(self) -> None:
        log.info("Sinal de parada recebido.")
        self._parar.set()


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador de Raspberry Pi para o projeto de estacionamento IoT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Conexão
    parser.add_argument("--endpoint", help="AWS IoT Core endpoint (ex: xxx-ats.iot.us-east-1.amazonaws.com)")
    parser.add_argument("--cert", help="Caminho do certificate.pem.crt")
    parser.add_argument("--key", help="Caminho do private.pem.key")
    parser.add_argument("--ca", help="Caminho do AmazonRootCA1.pem")
    parser.add_argument("--dry-run", action="store_true", help="Não publica de verdade — só imprime os payloads")

    # Identificação
    parser.add_argument("--pi-id", default="pi-setor-a", help="Identificador do Pi (default: pi-setor-a)")
    parser.add_argument("--client-id", default=None, help="Client ID MQTT (default: igual ao pi-id)")

    # Vagas
    parser.add_argument("--num-vagas", type=int, default=10, help="Quantas vagas monitorar (default: 10)")
    parser.add_argument("--prefixo", default="A", help="Prefixo dos vaga_ids (default: 'A' → A01, A02...)")

    # Modo
    parser.add_argument(
        "--modo",
        choices=["aleatorio", "cenario", "burst", "heartbeat"],
        default="aleatorio",
        help="Modo de operação (default: aleatorio)",
    )
    parser.add_argument("--intervalo-min", type=int, default=5, help="Intervalo mínimo entre eventos (s) — modo aleatorio")
    parser.add_argument("--intervalo-max", type=int, default=30, help="Intervalo máximo entre eventos (s) — modo aleatorio")
    parser.add_argument("--burst-n", type=int, default=100, help="Quantos eventos no modo burst")
    parser.add_argument("--heartbeat-intervalo", type=int, default=30, help="Intervalo de heartbeat (s)")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.dry_run:
        if not all([args.endpoint, args.cert, args.key, args.ca]):
            log.error("Sem --dry-run, é obrigatório passar --endpoint, --cert, --key e --ca.")
            return 1

    client_id = args.client_id or args.pi_id

    cliente = ClienteMQTT(
        endpoint=args.endpoint or "dry-run-endpoint",
        client_id=client_id,
        cert_path=args.cert,
        key_path=args.key,
        ca_path=args.ca,
        dry_run=args.dry_run,
    )

    sim = SimuladorPi(
        cliente=cliente,
        pi_id=args.pi_id,
        num_vagas=args.num_vagas,
        prefixo_vaga=args.prefixo,
    )

    # Trata Ctrl+C de forma limpa
    def shutdown(signum, frame):
        sim.parar()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        cliente.conectar()

        if args.modo == "aleatorio":
            sim.modo_aleatorio(args.intervalo_min, args.intervalo_max)
        elif args.modo == "cenario":
            sim.modo_cenario()
        elif args.modo == "burst":
            sim.modo_burst(args.burst_n)
        elif args.modo == "heartbeat":
            sim.modo_heartbeat(args.heartbeat_intervalo)

    except Exception as e:
        log.error(f"Erro: {e}", exc_info=True)
        return 1
    finally:
        cliente.desconectar()

    return 0


if __name__ == "__main__":
    sys.exit(main())
