"""Testes do ``SQLiteRepo`` — banco em arquivo temporário (tmp_path)."""

from __future__ import annotations

import uuid

import pytest

from src.api.services.sqlite_repo import SQLiteRepo


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "vagas_test.db"
    r = SQLiteRepo(str(db_path))
    yield r
    r.fechar()


def _evento(vaga_id: str, status: str, ts: int, pi_id: str = "pi-test") -> dict:
    return {
        "vaga_id": vaga_id,
        "status": status,
        "timestamp": ts,
        "pi_id": pi_id,
        "evento_id": str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# 1. Insert + read estado
# ---------------------------------------------------------------------------

def test_insert_e_read_estado(repo):
    repo.adicionar_evento(_evento("A01", "ocupada", 1_000_000))
    estado = repo.buscar_estado("A01")
    assert estado is not None
    assert estado["vaga_id"] == "A01"
    assert estado["status"] == "ocupada"
    assert estado["last_update"] == 1_000_000
    assert estado["pi_id"] == "pi-test"


# ---------------------------------------------------------------------------
# 2. Insert evento — vai pra histórico
# ---------------------------------------------------------------------------

def test_insert_evento_aparece_no_historico(repo):
    base = 1_700_000_000_000
    for i in range(3):
        repo.adicionar_evento(_evento("A01", "ocupada" if i % 2 else "livre", base + i))

    eventos = repo.historico("A01")
    assert len(eventos) == 3
    timestamps = [e["timestamp"] for e in eventos]
    assert timestamps == sorted(timestamps)  # ordem crescente


# ---------------------------------------------------------------------------
# 3. Histórico com janela [from, to]
# ---------------------------------------------------------------------------

def test_query_historico_com_janela(repo):
    base = 1_700_000_000_000
    for i in range(10):
        repo.adicionar_evento(
            _evento("A01", "ocupada" if i % 2 else "livre", base + i * 1000)
        )

    janela = repo.historico("A01", ts_de=base + 3000, ts_ate=base + 6000)
    assert len(janela) == 4  # 3000, 4000, 5000, 6000
    for ev in janela:
        assert base + 3000 <= ev["timestamp"] <= base + 6000


# ---------------------------------------------------------------------------
# 4. Idempotência — evento antigo não sobrescreve estado mais recente
# ---------------------------------------------------------------------------

def test_idempotencia_evento_antigo_nao_sobrescreve(repo):
    base = 1_700_000_000_000

    # Estado fica em "ocupada" no ts mais recente
    assert repo.adicionar_evento(_evento("A01", "ocupada", base + 5000)) is True
    # Evento antigo (livre) não deve sobrescrever o estado
    assert repo.adicionar_evento(_evento("A01", "livre", base + 1000)) is False

    estado = repo.buscar_estado("A01")
    assert estado["status"] == "ocupada"
    assert estado["last_update"] == base + 5000

    # Mas o histórico tem os dois eventos
    eventos = repo.historico("A01")
    assert len(eventos) == 2


# ---------------------------------------------------------------------------
# 5. Listagem por status (índice idx_estado_status)
# ---------------------------------------------------------------------------

def test_listar_estado_filtrado_por_status(repo):
    base = 1_700_000_000_000
    repo.adicionar_evento(_evento("A01", "ocupada", base))
    repo.adicionar_evento(_evento("A02", "ocupada", base))
    repo.adicionar_evento(_evento("A03", "livre", base))
    repo.adicionar_evento(_evento("A04", "livre", base))

    livres = repo.listar_estado(status="livre")
    ocupadas = repo.listar_estado(status="ocupada")

    assert {v["vaga_id"] for v in livres} == {"A03", "A04"}
    assert {v["vaga_id"] for v in ocupadas} == {"A01", "A02"}
    assert all(v["status"] == "livre" for v in livres)
    assert all(v["status"] == "ocupada" for v in ocupadas)
