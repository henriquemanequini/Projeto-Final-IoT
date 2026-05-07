"""
Popula o storage com vagas e eventos de teste.

Uso:
    python scripts/seed_dynamo.py --local        # popula memória da API local
    python scripts/seed_dynamo.py --num-vagas 20 # padrão é 12

NOTA: o modo --local funciona via HTTP, chamando a API. Por isso a API
precisa estar rodando em outro terminal (uvicorn). Como nosso storage
em memória vive no processo da API, esse script publica eventos via
um endpoint interno temporário para popular dados.

Para popular DynamoDB real (não-local), o seed grava direto via boto3.
"""

import argparse
import random
import sys
import time
import uuid
from pathlib import Path

# Permite importar src.* quando rodando este script da raiz
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.config import get_settings
from src.api.services.repositorio import RepositorioVagas


def gerar_eventos(num_vagas: int, eventos_por_vaga: int = 5) -> list[dict]:
    """Gera eventos sintéticos pra cada vaga, com timestamps progressivos."""
    eventos = []
    agora = int(time.time() * 1000)

    for i in range(1, num_vagas + 1):
        vaga_id = f"A{i:02d}"
        status = "livre"
        # Eventos espalhados nos últimos 60 minutos
        for j in range(eventos_por_vaga):
            ts = agora - (eventos_por_vaga - j) * random.randint(60_000, 600_000)
            status = "ocupada" if status == "livre" else "livre"
            eventos.append({
                "vaga_id": vaga_id,
                "status": status,
                "timestamp": ts,
                "pi_id": "pi-setor-a",
                "evento_id": str(uuid.uuid4()),
            })

    eventos.sort(key=lambda e: e["timestamp"])
    return eventos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-vagas", type=int, default=12)
    parser.add_argument("--eventos-por-vaga", type=int, default=5)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Força modo local mesmo se MODO_LOCAL=false no .env",
    )
    args = parser.parse_args()

    if args.local:
        # Sobrescreve setting em runtime
        settings = get_settings()
        settings.modo_local = True
        settings.modo_storage = "memoria"
        print(f"[seed] Modo LOCAL — populando storage em memória")
    else:
        settings = get_settings()
        modo = settings.storage_efetivo.upper()
        print(f"[seed] Modo {modo}")

    eventos = gerar_eventos(args.num_vagas, args.eventos_por_vaga)
    print(f"[seed] Gerados {len(eventos)} eventos para {args.num_vagas} vagas")

    repo = RepositorioVagas()
    for ev in eventos:
        repo.adicionar_evento(ev)

    todas = repo.listar_estado()
    livres = sum(1 for v in todas if v.status == "livre")
    ocupadas = sum(1 for v in todas if v.status == "ocupada")

    print(f"[seed] OK — {len(todas)} vagas no storage ({livres} livres, {ocupadas} ocupadas)")
    print()
    print("AVISO: Se você rodou em modo local, o storage vive no processo desta execução.")
    print("Para a API ver os dados, use o endpoint POST /v1/_seed que adicionamos.")
    print("Em prod (DynamoDB real) os dados ficam persistidos.")


if __name__ == "__main__":
    main()
