"""Schemas Pydantic — entrada e saída da API."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

StatusVaga = Literal["livre", "ocupada"]


class EventoVaga(BaseModel):
    """Evento publicado pelo Pi via MQTT (para validação na ingestão)."""

    vaga_id: str = Field(..., examples=["A01"])
    status: StatusVaga
    timestamp: int = Field(..., description="Epoch em milissegundos UTC")
    pi_id: str = Field(..., examples=["pi-setor-a"])
    evento_id: str = Field(..., description="UUID v4 — usado para deduplicação")


class EstadoVaga(BaseModel):
    """Estado atual de uma vaga (resposta da API)."""

    vaga_id: str
    status: StatusVaga
    last_update: int = Field(..., description="Epoch em milissegundos UTC")
    pi_id: Optional[str] = None


class ListaVagasResponse(BaseModel):
    """Resposta de GET /v1/vagas."""

    total: int
    livres: int
    ocupadas: int
    vagas: List[EstadoVaga]


class HistoricoEvento(BaseModel):
    """Evento de histórico (resposta de /vagas/{id}/historico)."""

    vaga_id: str
    timestamp: int
    status: StatusVaga
    pi_id: str
    evento_id: Optional[str] = None


class HistoricoResponse(BaseModel):
    """Resposta de GET /v1/vagas/{id}/historico."""

    vaga_id: str
    eventos: List[HistoricoEvento]
    total: int


class EstatisticasResponse(BaseModel):
    """Resposta de GET /v1/estatisticas."""

    total_vagas: int
    livres: int
    ocupadas: int
    taxa_ocupacao: float = Field(..., description="Entre 0 e 1")
    timestamp_consulta: int


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    versao: str = "1.0.0"
    modo: str = "local"


class ErroResponse(BaseModel):
    erro: str
    mensagem: str
    status: int
