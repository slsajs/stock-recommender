from __future__ import annotations

import psycopg2
from psycopg2 import pool
from loguru import logger

from src.config import settings

_pool: pool.ThreadedConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    """커넥션 풀 초기화. 애플리케이션 시작 시 한 번 호출."""
    global _pool
    if _pool is not None:
        return
    _pool = pool.ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=settings.db_dsn,
    )
    logger.info(f"DB 커넥션 풀 초기화 완료 (min={minconn}, max={maxconn})")


def get_connection() -> psycopg2.extensions.connection:
    """풀에서 커넥션을 빌려 반환한다."""
    if _pool is None:
        init_pool()
    return _pool.getconn()  # type: ignore[union-attr]


def release_connection(conn: psycopg2.extensions.connection) -> None:
    """커넥션을 풀에 반납한다."""
    if _pool is not None:
        _pool.putconn(conn)


def close_pool() -> None:
    """애플리케이션 종료 시 풀 전체를 닫는다."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB 커넥션 풀 종료")


class DBConnection:
    """with 문으로 커넥션을 안전하게 사용하기 위한 컨텍스트 매니저."""

    def __init__(self, autocommit: bool = False) -> None:
        self._autocommit = autocommit
        self._conn: psycopg2.extensions.connection | None = None

    def __enter__(self) -> psycopg2.extensions.connection:
        self._conn = get_connection()
        self._conn.autocommit = self._autocommit
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is None:
            return
        if exc_type is not None:
            self._conn.rollback()
            logger.warning(f"DB 트랜잭션 롤백 | {exc_type.__name__}: {exc_val}")
        else:
            if not self._autocommit:
                self._conn.commit()
        release_connection(self._conn)
        self._conn = None