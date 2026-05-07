"""Endpoints de /v1/vagas e /v1/estatisticas."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas import (
    EstadoVaga,
    EstatisticasResponse,
    HistoricoResponse,
    ListaVagasResponse,
)
from src.api.services.repositorio import RepositorioVagas, agora_ms

router = APIRouter(prefix="/v1", tags=["vagas"])


def _repositorio() -> RepositorioVagas:
    """Factory simples — facilita override em testes."""
    return RepositorioVagas()


@router.get("/vagas", response_model=ListaVagasResponse)
def listar_vagas(status: Optional[str] = Query(None, pattern="^(livre|ocupada)$")):
    """Lista o estado atual de todas as vagas. Filtra por status se informado."""
    repo = _repositorio()
    todas = repo.listar_estado()

    if status:
        todas = [v for v in todas if v.status == status]

    livres = sum(1 for v in todas if v.status == "livre")
    ocupadas = sum(1 for v in todas if v.status == "ocupada")

    return ListaVagasResponse(
        total=len(todas),
        livres=livres,
        ocupadas=ocupadas,
        vagas=todas,
    )


@router.get("/vagas/{vaga_id}", response_model=EstadoVaga)
def buscar_vaga(vaga_id: str):
    """Estado atual de uma vaga específica."""
    repo = _repositorio()
    vaga = repo.buscar_estado(vaga_id)
    if vaga is None:
        raise HTTPException(
            status_code=404,
            detail={
                "erro": "VAGA_NAO_ENCONTRADA",
                "mensagem": f"Vaga '{vaga_id}' não existe no sistema",
                "status": 404,
            },
        )
    return vaga


@router.get("/vagas/{vaga_id}/historico", response_model=HistoricoResponse)
def historico_vaga(
    vaga_id: str,
    from_ts: Optional[int] = Query(None, alias="from", description="Epoch ms — início"),
    to_ts: Optional[int] = Query(None, alias="to", description="Epoch ms — fim"),
    limite: int = Query(100, ge=1, le=1000),
):
    """Histórico de eventos de uma vaga, opcionalmente filtrado por janela de tempo."""
    repo = _repositorio()
    eventos = repo.historico(vaga_id, ts_de=from_ts, ts_ate=to_ts, limite=limite)
    return HistoricoResponse(
        vaga_id=vaga_id,
        eventos=eventos,
        total=len(eventos),
    )


@router.get("/estatisticas", response_model=EstatisticasResponse)
def estatisticas():
    """Agregados — total, livres, ocupadas e taxa de ocupação."""
    repo = _repositorio()
    todas = repo.listar_estado()
    total = len(todas)
    livres = sum(1 for v in todas if v.status == "livre")
    ocupadas = sum(1 for v in todas if v.status == "ocupada")
    taxa = (ocupadas / total) if total > 0 else 0.0

    return EstatisticasResponse(
        total_vagas=total,
        livres=livres,
        ocupadas=ocupadas,
        taxa_ocupacao=round(taxa, 3),
        timestamp_consulta=agora_ms(),
    )
