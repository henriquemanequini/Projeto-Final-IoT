"""Entrypoint da API — FastAPI app."""

from __future__ import annotations

import logging
import os
import random
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger import jsonlogger

from src.api.config import get_settings
from src.api.routers import vagas
from src.api.schemas import HealthResponse
from src.api.services.repositorio import RepositorioVagas


def _configurar_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


_configurar_logging(get_settings().log_level)
log = logging.getLogger("api")


def criar_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Estacionamento Inteligente — API",
        description="Backend do sistema de gestão de estacionamento via IoT.",
        version="1.0.0",
        contact={"name": "Henrique"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", versao="1.0.0", modo=settings.storage_efetivo
        )

    @app.get("/", include_in_schema=False)
    def raiz():
        return {
            "api": "Estacionamento Inteligente",
            "docs": "/docs",
            "health": "/v1/health",
        }

    app.include_router(vagas.router)

    # Seed automático em modo memória — facilita desenvolvimento
    if (
        settings.storage_efetivo == "memoria"
        and os.environ.get("PYTEST_CURRENT_TEST") is None
    ):
        _seed_dados_iniciais()

    log.info(f"API iniciada — storage={settings.storage_efetivo}")
    return app


def _seed_dados_iniciais(num_vagas: int = 12, eventos_por_vaga: int = 5) -> None:
    """Popula storage em memória com dados sintéticos no startup."""
    repo = RepositorioVagas()
    if repo.listar_estado():
        return  # já tem dados

    agora = int(time.time() * 1000)
    total = 0
    for i in range(1, num_vagas + 1):
        vaga_id = f"A{i:02d}"
        status = "livre"
        for j in range(eventos_por_vaga):
            ts = agora - (eventos_por_vaga - j) * random.randint(60_000, 600_000)
            status = "ocupada" if status == "livre" else "livre"
            repo.adicionar_evento({
                "vaga_id": vaga_id,
                "status": status,
                "timestamp": ts,
                "pi_id": "pi-setor-a",
                "evento_id": str(uuid.uuid4()),
            })
            total += 1
    log.info(f"Seed local: {num_vagas} vagas, {total} eventos")


app = criar_app()


# Adapter Lambda — usado quando deploy em AWS Lambda + API Gateway
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None
