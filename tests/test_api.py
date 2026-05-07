"""Testes da API — usa storage em memória."""

from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient

# Garante storage=memoria antes de importar a app
os.environ["MODO_STORAGE"] = "memoria"
os.environ["MODO_LOCAL"] = "false"

from src.api.config import reset_settings
reset_settings()

from src.api.main import criar_app
from src.api.services.repositorio import RepositorioVagas, get_storage_memoria


@pytest.fixture
def client():
    app = criar_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def limpar_storage():
    """Garante storage limpo entre testes."""
    storage = get_storage_memoria()
    storage._estado.clear()
    storage._eventos.clear()
    yield
    storage._estado.clear()
    storage._eventos.clear()


def _evento(vaga_id: str, status: str, ts: Optional[int] = None) -> dict:
    return {
        "vaga_id": vaga_id,
        "status": status,
        "timestamp": ts or int(time.time() * 1000),
        "pi_id": "pi-test",
        "evento_id": str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["modo"] == "memoria"


def test_raiz_redireciona(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


# ---------------------------------------------------------------------------
# /v1/vagas
# ---------------------------------------------------------------------------

def test_listar_vagas_vazio(client):
    r = client.get("/v1/vagas")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["vagas"] == []


def test_listar_vagas_com_dados(client):
    repo = RepositorioVagas()
    repo.adicionar_evento(_evento("A01", "ocupada"))
    repo.adicionar_evento(_evento("A02", "livre"))
    repo.adicionar_evento(_evento("A03", "ocupada"))

    r = client.get("/v1/vagas")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["livres"] == 1
    assert body["ocupadas"] == 2


def test_filtrar_por_status(client):
    repo = RepositorioVagas()
    repo.adicionar_evento(_evento("A01", "ocupada"))
    repo.adicionar_evento(_evento("A02", "livre"))

    r = client.get("/v1/vagas?status=livre")
    body = r.json()
    assert body["total"] == 1
    assert body["vagas"][0]["vaga_id"] == "A02"


def test_buscar_vaga_existente(client):
    repo = RepositorioVagas()
    repo.adicionar_evento(_evento("A01", "ocupada"))

    r = client.get("/v1/vagas/A01")
    assert r.status_code == 200
    assert r.json()["status"] == "ocupada"


def test_buscar_vaga_inexistente(client):
    r = client.get("/v1/vagas/NAO_EXISTE")
    assert r.status_code == 404
    assert r.json()["detail"]["erro"] == "VAGA_NAO_ENCONTRADA"


# ---------------------------------------------------------------------------
# Histórico
# ---------------------------------------------------------------------------

def test_historico_completo(client):
    repo = RepositorioVagas()
    base = 1_700_000_000_000
    repo.adicionar_evento(_evento("A01", "ocupada", base))
    repo.adicionar_evento(_evento("A01", "livre", base + 1000))
    repo.adicionar_evento(_evento("A01", "ocupada", base + 2000))

    r = client.get("/v1/vagas/A01/historico")
    assert r.status_code == 200
    assert r.json()["total"] == 3
    # Ordenados por timestamp crescente
    eventos = r.json()["eventos"]
    assert eventos[0]["timestamp"] < eventos[-1]["timestamp"]


def test_historico_filtrado_janela(client):
    repo = RepositorioVagas()
    base = 1_700_000_000_000
    for i in range(10):
        repo.adicionar_evento(
            _evento("A01", "ocupada" if i % 2 else "livre", base + i * 1000)
        )

    r = client.get(
        f"/v1/vagas/A01/historico?from={base + 3000}&to={base + 6000}"
    )
    assert r.status_code == 200
    assert r.json()["total"] == 4  # ts 3000, 4000, 5000, 6000


# ---------------------------------------------------------------------------
# Estatísticas
# ---------------------------------------------------------------------------

def test_estatisticas_vazio(client):
    r = client.get("/v1/estatisticas")
    assert r.status_code == 200
    body = r.json()
    assert body["total_vagas"] == 0
    assert body["taxa_ocupacao"] == 0.0


def test_estatisticas_calculo(client):
    repo = RepositorioVagas()
    for i in range(8):
        repo.adicionar_evento(_evento(f"A{i:02d}", "ocupada"))
    for i in range(8, 10):
        repo.adicionar_evento(_evento(f"A{i:02d}", "livre"))

    r = client.get("/v1/estatisticas")
    body = r.json()
    assert body["total_vagas"] == 10
    assert body["ocupadas"] == 8
    assert body["livres"] == 2
    assert body["taxa_ocupacao"] == 0.8


# ---------------------------------------------------------------------------
# Idempotência (eventos fora de ordem não devem reverter estado)
# ---------------------------------------------------------------------------

def test_evento_antigo_nao_sobrescreve_recente(client):
    repo = RepositorioVagas()
    base = 1_700_000_000_000
    repo.adicionar_evento(_evento("A01", "ocupada", base + 5000))
    repo.adicionar_evento(_evento("A01", "livre", base + 1000))  # mais antigo

    r = client.get("/v1/vagas/A01")
    assert r.json()["status"] == "ocupada"
    assert r.json()["last_update"] == base + 5000
