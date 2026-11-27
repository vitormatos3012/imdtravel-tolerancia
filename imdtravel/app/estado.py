from collections.abc import Callable
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import sqlite3
import threading
import time
from app.config import CONFIG
from app.instrumentacao import log
from app.resposta import corpo_202, json_exato

_ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cid TEXT NOT NULL,
    flight TEXT NOT NULL,
    day TEXT NOT NULL,
    user TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('SELLING','SOLD','UNCERTAIN','NOT_SOLD')),
    transaction_id TEXT,
    bonus INTEGER,
    bonus_estado TEXT NOT NULL DEFAULT 'NA' CHECK (bonus_estado IN ('NA','PENDENTE','CREDITADO')),
    bonus_tentativas INTEGER NOT NULL DEFAULT 0,
    bonus_proxima_em REAL,
    resposta_status INTEGER,
    resposta_corpo TEXT,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    UNIQUE (cid, flight, day, user)
);
CREATE INDEX IF NOT EXISTS idx_bonus_pendente ON compras (bonus_estado, bonus_proxima_em);
"""


def _agora_iso_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class Linha:
    cid: str
    flight: str
    day: str
    user: str
    estado: str
    transaction_id: str | None
    bonus: int | None
    bonus_estado: str
    resposta_status: int | None
    resposta_corpo: str | None


def _linha_de_tupla(registro: tuple[object, ...]) -> Linha:
    cid, flight, day, user, estado, tx_id, bonus, bonus_estado, status, corpo = registro
    assert isinstance(cid, str)
    assert isinstance(flight, str)
    assert isinstance(day, str)
    assert isinstance(user, str)
    assert isinstance(estado, str)
    assert tx_id is None or isinstance(tx_id, str)
    assert bonus is None or isinstance(bonus, int)
    assert isinstance(bonus_estado, str)
    assert status is None or isinstance(status, int)
    assert corpo is None or isinstance(corpo, str)
    return Linha(
        cid=cid,
        flight=flight,
        day=day,
        user=user,
        estado=estado,
        transaction_id=tx_id,
        bonus=bonus,
        bonus_estado=bonus_estado,
        resposta_status=status,
        resposta_corpo=corpo,
    )


class Estado:
    """Persistência de compras em SQLite (Remote Storage em volume persistente).

    Aplica Checkpoint e What to Save: grava SELLING antes da chamada externa
    com efeito colateral (/sell) e consolida o desfecho final (SOLD, UNCERTAIN
    ou NOT_SOLD) junto com a resposta serializada para idempotência.
    """

    def __init__(self, caminho: str, relogio: Callable[[], float] = time.time) -> None:
        self._caminho = caminho
        self._relogio = relogio
        self._lock_esquema = threading.Lock()
        self._esquema_pronto = False

    def _garantir_esquema(self) -> None:
        if self._esquema_pronto:
            return
        with self._lock_esquema:
            if self._esquema_pronto:
                return
            diretorio = os.path.dirname(self._caminho)
            if diretorio:
                os.makedirs(diretorio, exist_ok=True)
            with contextlib.closing(
                sqlite3.connect(self._caminho, timeout=5.0, isolation_level=None)
            ) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_ESQUEMA_SQL)
            self._esquema_pronto = True

    def _conectar(self) -> sqlite3.Connection:
        self._garantir_esquema()
        return sqlite3.connect(self._caminho, timeout=5.0, isolation_level=None)

    def _selecionar(
        self,
        conn: sqlite3.Connection,
        cid: str,
        flight: str,
        day: str,
        user: str,
    ) -> Linha | None:
        cur = conn.execute(
            """
            SELECT cid, flight, day, user, estado, transaction_id,
                   bonus, bonus_estado, resposta_status, resposta_corpo
            FROM compras
            WHERE cid = ? AND flight = ? AND day = ? AND user = ?
            """,
            (cid, flight, day, user),
        )
        registro = cur.fetchone()
        return _linha_de_tupla(registro) if registro is not None else None

    def iniciar_compra(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
    ) -> tuple[bool, Linha | None]:
        agora = _agora_iso_utc()
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO compras (
                        cid, flight, day, user, estado,
                        bonus_estado, bonus_tentativas, criado_em, atualizado_em
                    )
                    VALUES (?, ?, ?, ?, 'SELLING', 'NA', 0, ?, ?)
                    """,
                    (cid, flight, day, user, agora, agora),
                )
                conn.execute("COMMIT")
                return True, None
            except sqlite3.IntegrityError:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                existente = self._selecionar(conn, cid, flight, day, user)
                return False, existente
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def buscar(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
    ) -> Linha | None:
        with contextlib.closing(self._conectar()) as conn:
            return self._selecionar(conn, cid, flight, day, user)

    def concluir_vendida(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
        transaction_id: str,
        bonus: int,
        status: int,
        corpo: str,
    ) -> None:
        agora = _agora_iso_utc()
        proxima_em = self._relogio()
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE compras
                    SET estado = 'SOLD',
                        transaction_id = ?,
                        bonus = ?,
                        bonus_estado = 'PENDENTE',
                        bonus_proxima_em = ?,
                        resposta_status = ?,
                        resposta_corpo = ?,
                        atualizado_em = ?
                    WHERE cid = ? AND flight = ? AND day = ? AND user = ?
                      AND estado = 'SELLING'
                    """,
                    (
                        transaction_id,
                        bonus,
                        proxima_em,
                        status,
                        corpo,
                        agora,
                        cid,
                        flight,
                        day,
                        user,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def concluir_incerta(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
        status: int,
        corpo: str,
    ) -> None:
        agora = _agora_iso_utc()
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE compras
                    SET estado = 'UNCERTAIN',
                        resposta_status = ?,
                        resposta_corpo = ?,
                        atualizado_em = ?
                    WHERE cid = ? AND flight = ? AND day = ? AND user = ?
                      AND estado = 'SELLING'
                    """,
                    (status, corpo, agora, cid, flight, day, user),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def concluir_nao_vendida(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
        status: int,
        corpo: str,
    ) -> None:
        agora = _agora_iso_utc()
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE compras
                    SET estado = 'NOT_SOLD',
                        resposta_status = ?,
                        resposta_corpo = ?,
                        atualizado_em = ?
                    WHERE cid = ? AND flight = ? AND day = ? AND user = ?
                      AND estado = 'SELLING'
                    """,
                    (status, corpo, agora, cid, flight, day, user),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def liberar(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
    ) -> None:
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    DELETE FROM compras
                    WHERE cid = ? AND flight = ? AND day = ? AND user = ?
                      AND estado = 'SELLING'
                    """,
                    (cid, flight, day, user),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def marcar_bonus_creditado(
        self,
        cid: str,
        flight: str,
        day: str,
        user: str,
    ) -> None:
        agora = _agora_iso_utc()
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE compras
                    SET bonus_estado = 'CREDITADO',
                        atualizado_em = ?
                    WHERE cid = ? AND flight = ? AND day = ? AND user = ?
                      AND bonus_estado = 'PENDENTE'
                    """,
                    (agora, cid, flight, day, user),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def recuperar_orfas(self) -> list[str]:
        agora = _agora_iso_utc()
        cids_recuperados: list[str] = []
        with contextlib.closing(self._conectar()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    """
                    SELECT id, cid, flight, day, user
                    FROM compras
                    WHERE estado = 'SELLING'
                    """
                )
                orfas = cur.fetchall()
                for row_id, cid, flight, day, user in orfas:
                    assert isinstance(cid, str)
                    assert isinstance(flight, str)
                    assert isinstance(day, str)
                    assert isinstance(user, str)
                    corpo = json_exato(corpo_202(cid, flight, day, user, []))
                    conn.execute(
                        """
                        UPDATE compras
                        SET estado = 'UNCERTAIN',
                            resposta_status = 202,
                            resposta_corpo = ?,
                            atualizado_em = ?
                        WHERE id = ? AND estado = 'SELLING'
                        """,
                        (corpo, agora, row_id),
                    )
                    cids_recuperados.append(cid)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

        for cid in cids_recuperados:
            log("venda.incerta.recuperada", cid=cid)
        return cids_recuperados


ESTADO = Estado(CONFIG.db_path)
