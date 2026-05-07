"""
Repositório SQLite — persistência self-hosted das vagas.

Substitui o DynamoDB no modo de produção da EC2. Usa apenas a stdlib
(``sqlite3``) para minimizar dependências. Conexão única, compartilhada
entre threads (``check_same_thread=False``) com lock para escritas.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas_eventos (
    vaga_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    status TEXT NOT NULL,
    pi_id TEXT NOT NULL,
    evento_id TEXT,
    PRIMARY KEY (vaga_id, timestamp)
);

CREATE TABLE IF NOT EXISTS vagas_estado (
    vaga_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_update INTEGER NOT NULL,
    pi_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_estado_status ON vagas_estado(status);
"""


class SQLiteRepo:
    """
    Acesso direto ao banco SQLite seguindo o mesmo contrato do
    ``StorageMemoria``. Operações de escrita são serializadas via lock
    para evitar ``database is locked`` em cenários multi-thread (API +
    worker MQTT no mesmo processo, por exemplo).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._garantir_diretorio()
        self._conn = sqlite3.connect(
            path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; controlamos transações manualmente
        )
        self._conn.row_factory = sqlite3.Row
        # WAL melhora concorrência leitor/escritor
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA)
        log.info("SQLiteRepo inicializado em %s", path)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _garantir_diretorio(self) -> None:
        diretorio = Path(self.path).expanduser().resolve().parent
        diretorio.mkdir(parents=True, exist_ok=True)

    def fechar(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def listar_estado(self, status: Optional[str] = None) -> List[dict]:
        """Retorna o estado atual de todas as vagas (opcional: filtrar por status)."""
        if status is not None:
            cur = self._conn.execute(
                "SELECT vaga_id, status, last_update, pi_id "
                "FROM vagas_estado WHERE status = ? ORDER BY vaga_id",
                (status,),
            )
        else:
            cur = self._conn.execute(
                "SELECT vaga_id, status, last_update, pi_id "
                "FROM vagas_estado ORDER BY vaga_id"
            )
        return [dict(row) for row in cur.fetchall()]

    def buscar_estado(self, vaga_id: str) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT vaga_id, status, last_update, pi_id "
            "FROM vagas_estado WHERE vaga_id = ?",
            (vaga_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def historico(
        self,
        vaga_id: str,
        ts_de: Optional[int] = None,
        ts_ate: Optional[int] = None,
        limite: int = 100,
    ) -> List[dict]:
        """Retorna eventos de uma vaga ordenados por timestamp crescente."""
        sql = (
            "SELECT vaga_id, timestamp, status, pi_id, evento_id "
            "FROM vagas_eventos WHERE vaga_id = ?"
        )
        params: list = [vaga_id]
        if ts_de is not None:
            sql += " AND timestamp >= ?"
            params.append(ts_de)
        if ts_ate is not None:
            sql += " AND timestamp <= ?"
            params.append(ts_ate)
        sql += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limite)

        cur = self._conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def adicionar_evento(self, evento: dict) -> bool:
        """
        Insere um evento e atualiza o estado atual de forma idempotente.

        Retorna ``True`` se o estado foi atualizado (evento mais novo),
        ``False`` se foi ignorado (evento mais antigo que o já registrado).
        """
        vaga_id = evento["vaga_id"]
        timestamp = int(evento["timestamp"])
        status = evento["status"]
        pi_id = evento["pi_id"]
        evento_id = evento.get("evento_id")

        with self._lock:
            try:
                self._conn.execute("BEGIN")
                # 1) histórico — PRIMARY KEY composta dá idempotência por (vaga, ts)
                self._conn.execute(
                    "INSERT OR IGNORE INTO vagas_eventos "
                    "(vaga_id, timestamp, status, pi_id, evento_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (vaga_id, timestamp, status, pi_id, evento_id),
                )

                # 2) estado — só atualiza se o evento for mais novo
                cur = self._conn.execute(
                    "INSERT INTO vagas_estado (vaga_id, status, last_update, pi_id) "
                    "VALUES (:vaga_id, :status, :ts, :pi_id) "
                    "ON CONFLICT(vaga_id) DO UPDATE SET "
                    "  status = excluded.status, "
                    "  last_update = excluded.last_update, "
                    "  pi_id = excluded.pi_id "
                    "WHERE vagas_estado.last_update < excluded.last_update",
                    {
                        "vaga_id": vaga_id,
                        "status": status,
                        "ts": timestamp,
                        "pi_id": pi_id,
                    },
                )
                atualizou = cur.rowcount > 0
                self._conn.execute("COMMIT")
                return atualizou
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def atualizar_estado(
        self,
        vaga_id: str,
        status: str,
        last_update: int,
        pi_id: Optional[str],
    ) -> bool:
        """
        Atualiza apenas a tabela de estado (sem registrar evento).
        Idempotente: ignora atualizações com ``last_update`` antigo.
        """
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO vagas_estado (vaga_id, status, last_update, pi_id) "
                "VALUES (:vaga_id, :status, :ts, :pi_id) "
                "ON CONFLICT(vaga_id) DO UPDATE SET "
                "  status = excluded.status, "
                "  last_update = excluded.last_update, "
                "  pi_id = excluded.pi_id "
                "WHERE vagas_estado.last_update < excluded.last_update",
                {
                    "vaga_id": vaga_id,
                    "status": status,
                    "ts": int(last_update),
                    "pi_id": pi_id,
                },
            )
            return cur.rowcount > 0
