"""
Camada de acesso aos dados — fachada com 3 modos.

Modos suportados (selecionados via ``Settings.modo_storage``):

- ``memoria``   : ``StorageMemoria`` em RAM, sem persistência (dev/testes)
- ``sqlite``    : ``SQLiteRepo`` (produção self-hosted EC2 — default)
- ``dynamodb``  : DynamoDB via boto3 (legado, mantido por compat)

A flag legada ``modo_local=True`` força ``memoria`` (compat com testes).
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import List, Optional

from src.api.config import get_settings
from src.api.schemas import EstadoVaga, HistoricoEvento
from src.api.services.sqlite_repo import SQLiteRepo

log = logging.getLogger(__name__)


# =============================================================================
# Storage em memória (modo "memoria")
# =============================================================================

class StorageMemoria:
    """
    Implementação em memória que imita os dois acessos que precisamos:
    estado atual de vagas e histórico de eventos.
    """

    def __init__(self) -> None:
        # vagas_estado: {vaga_id: dict}
        self._estado: dict[str, dict] = {}
        # vagas_eventos: lista de eventos ordenados por timestamp
        self._eventos: list[dict] = []

    def listar_estado(self, status: Optional[str] = None) -> list[dict]:
        items = list(self._estado.values())
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return items

    def buscar_estado(self, vaga_id: str) -> dict | None:
        return self._estado.get(vaga_id)

    def atualizar_estado(
        self, vaga_id: str, status: str, last_update: int, pi_id: Optional[str]
    ) -> bool:
        atual = self._estado.get(vaga_id)
        # Idempotência: só atualiza se for evento mais recente
        if atual and atual["last_update"] >= last_update:
            return False
        self._estado[vaga_id] = {
            "vaga_id": vaga_id,
            "status": status,
            "last_update": last_update,
            "pi_id": pi_id,
        }
        return True

    def adicionar_evento(self, evento: dict) -> bool:
        # Dedup por (vaga_id, timestamp)
        chave = (evento["vaga_id"], evento["timestamp"])
        existente = next(
            (e for e in self._eventos if (e["vaga_id"], e["timestamp"]) == chave),
            None,
        )
        if existente is None:
            self._eventos.append(evento)
        return self.atualizar_estado(
            vaga_id=evento["vaga_id"],
            status=evento["status"],
            last_update=evento["timestamp"],
            pi_id=evento["pi_id"],
        )

    def historico(
        self,
        vaga_id: str,
        ts_de: int | None,
        ts_ate: int | None,
        limite: int = 100,
    ) -> list[dict]:
        eventos = [e for e in self._eventos if e["vaga_id"] == vaga_id]
        if ts_de is not None:
            eventos = [e for e in eventos if e["timestamp"] >= ts_de]
        if ts_ate is not None:
            eventos = [e for e in eventos if e["timestamp"] <= ts_ate]
        return sorted(eventos, key=lambda e: e["timestamp"])[:limite]


# Instância única em memória (recriada a cada start da API)
_storage_memoria = StorageMemoria()


def get_storage_memoria() -> StorageMemoria:
    return _storage_memoria


def reset_storage_memoria() -> None:
    """Limpa o storage em memória (útil em testes e troca de modo)."""
    global _storage_memoria
    _storage_memoria = StorageMemoria()


# =============================================================================
# SQLite (modo "sqlite")
# =============================================================================

_sqlite_repo: Optional[SQLiteRepo] = None


def get_sqlite_repo() -> SQLiteRepo:
    global _sqlite_repo
    if _sqlite_repo is None:
        _sqlite_repo = SQLiteRepo(get_settings().sqlite_path)
    return _sqlite_repo


def reset_sqlite_repo() -> None:
    """Fecha e descarta a conexão SQLite (útil em testes)."""
    global _sqlite_repo
    if _sqlite_repo is not None:
        _sqlite_repo.fechar()
    _sqlite_repo = None


# =============================================================================
# DynamoDB (modo "dynamodb" — legado)
# =============================================================================

@lru_cache(maxsize=1)
def _resource_dynamo():
    """Cliente DynamoDB cacheado (singleton)."""
    import boto3  # import tardio: só carrega se modo=dynamodb
    settings = get_settings()
    return boto3.resource("dynamodb", region_name=settings.aws_region)


def _tabela_estado():
    return _resource_dynamo().Table(get_settings().tabela_estado)


def _tabela_eventos():
    return _resource_dynamo().Table(get_settings().tabela_eventos)


# =============================================================================
# Repositório — fachada que escolhe entre os 3 modos
# =============================================================================

class RepositorioVagas:
    """Fachada para acesso aos dados (memória, SQLite ou DynamoDB)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.modo = self.settings.storage_efetivo

    # ------- Listagens ------------------------------------------------------

    def listar_estado(self, status: Optional[str] = None) -> List[EstadoVaga]:
        if self.modo == "memoria":
            items = get_storage_memoria().listar_estado(status=status)
        elif self.modo == "sqlite":
            items = get_sqlite_repo().listar_estado(status=status)
        else:  # dynamodb
            items = self._dynamo_listar_estado()
            if status is not None:
                items = [i for i in items if i.get("status") == status]

        return [EstadoVaga(**self._normalizar_estado(i)) for i in items]

    def buscar_estado(self, vaga_id: str) -> Optional[EstadoVaga]:
        if self.modo == "memoria":
            item = get_storage_memoria().buscar_estado(vaga_id)
        elif self.modo == "sqlite":
            item = get_sqlite_repo().buscar_estado(vaga_id)
        else:
            response = _tabela_estado().get_item(Key={"vaga_id": vaga_id})
            item = response.get("Item")

        if not item:
            return None
        return EstadoVaga(**self._normalizar_estado(item))

    def historico(
        self,
        vaga_id: str,
        ts_de: Optional[int] = None,
        ts_ate: Optional[int] = None,
        limite: int = 100,
    ) -> List[HistoricoEvento]:
        if self.modo == "memoria":
            items = get_storage_memoria().historico(vaga_id, ts_de, ts_ate, limite)
        elif self.modo == "sqlite":
            items = get_sqlite_repo().historico(vaga_id, ts_de, ts_ate, limite)
        else:
            items = self._dynamo_historico(vaga_id, ts_de, ts_ate, limite)

        return [HistoricoEvento(**self._normalizar_evento(i)) for i in items]

    # ------- Mutação --------------------------------------------------------

    def adicionar_evento(self, evento: dict) -> bool:
        """Persiste evento + atualiza estado. Retorna True se estado foi atualizado."""
        if self.modo == "memoria":
            return get_storage_memoria().adicionar_evento(evento)
        if self.modo == "sqlite":
            return get_sqlite_repo().adicionar_evento(evento)
        # DynamoDB
        _tabela_eventos().put_item(Item=evento)
        _tabela_estado().put_item(
            Item={
                "vaga_id": evento["vaga_id"],
                "status": evento["status"],
                "last_update": evento["timestamp"],
                "pi_id": evento["pi_id"],
            }
        )
        return True

    def atualizar_estado(
        self, vaga_id: str, status: str, last_update: int, pi_id: Optional[str]
    ) -> bool:
        """Atualiza só o estado (sem registrar evento). Idempotente."""
        if self.modo == "memoria":
            return get_storage_memoria().atualizar_estado(
                vaga_id, status, last_update, pi_id
            )
        if self.modo == "sqlite":
            return get_sqlite_repo().atualizar_estado(
                vaga_id, status, last_update, pi_id
            )
        _tabela_estado().put_item(
            Item={
                "vaga_id": vaga_id,
                "status": status,
                "last_update": last_update,
                "pi_id": pi_id,
            }
        )
        return True

    # ------- DynamoDB helpers (modo legado) --------------------------------

    @staticmethod
    def _dynamo_listar_estado() -> list[dict]:
        response = _tabela_estado().scan()
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = _tabela_estado().scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            items.extend(response.get("Items", []))
        return items

    @staticmethod
    def _dynamo_historico(
        vaga_id: str,
        ts_de: Optional[int],
        ts_ate: Optional[int],
        limite: int,
    ) -> list[dict]:
        from boto3.dynamodb.conditions import Key  # import tardio

        condicao = Key("vaga_id").eq(vaga_id)
        if ts_de is not None and ts_ate is not None:
            condicao = condicao & Key("timestamp").between(ts_de, ts_ate)
        elif ts_de is not None:
            condicao = condicao & Key("timestamp").gte(ts_de)
        elif ts_ate is not None:
            condicao = condicao & Key("timestamp").lte(ts_ate)

        response = _tabela_eventos().query(
            KeyConditionExpression=condicao,
            Limit=limite,
            ScanIndexForward=True,
        )
        return response.get("Items", [])

    # ------- Normalização --------------------------------------------------

    @staticmethod
    def _normalizar_estado(item: dict) -> dict:
        """Aceita Decimal (DynamoDB), int (SQLite) e dict puro (memória)."""
        return {
            "vaga_id": str(item.get("vaga_id")),
            "status": str(item.get("status")),
            "last_update": int(item.get("last_update", 0)),
            "pi_id": item.get("pi_id"),
        }

    @staticmethod
    def _normalizar_evento(item: dict) -> dict:
        return {
            "vaga_id": str(item.get("vaga_id")),
            "timestamp": int(item.get("timestamp", 0)),
            "status": str(item.get("status")),
            "pi_id": str(item.get("pi_id", "desconhecido")),
            "evento_id": item.get("evento_id"),
        }


# =============================================================================
# Helper — agora em ms (usado em /estatisticas)
# =============================================================================

def agora_ms() -> int:
    return int(time.time() * 1000)
