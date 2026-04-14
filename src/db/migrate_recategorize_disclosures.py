"""
migrate_recategorize_disclosures.py
기존 disclosures 테이블의 category를 확장된 CATEGORY_KEYWORD_MAP으로 재분류한다.

배경:
  STEP E 공시 감성 보정을 위해 disclosure_collector.py의 카테고리 분류가 확장되었다.
  기존에 "일반공시"로 저장된 레코드 중 유상증자결정, 자기주식취득결정 등이 포함되어 있으며,
  이를 올바른 카테고리로 업데이트해야 STEP E가 실제로 동작한다.

실행:
  poetry run python -m src.db.migrate_recategorize_disclosures
"""
from __future__ import annotations

import psycopg2.extras
from loguru import logger

from src.collector.disclosure_collector import _categorize
from src.db.connection import DBConnection, init_pool, close_pool
from src.utils.logger import setup_logger


def run() -> None:
    """
    disclosures 테이블에서 category = '일반공시'인 레코드를 전부 조회하여
    title 기준으로 재분류 후 업데이트한다.

    실행 시간: 공시 건수에 따라 다르지만 수만 건 기준 수십 초 내외.
    """
    # 1. 재분류 대상 전체 조회
    logger.info("재분류 대상 공시 조회 중...")
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, category
                FROM disclosures
                WHERE category = '일반공시'
                ORDER BY id
                """
            )
            rows = [dict(r) for r in cur.fetchall()]

    total = len(rows)
    logger.info(f"재분류 대상: {total}건 (category='일반공시')")

    if total == 0:
        logger.info("재분류 대상 없음 — 완료")
        return

    # 2. 재분류 수행
    updates: list[tuple[str, int]] = []  # (new_category, id)
    changed = 0

    for row in rows:
        new_category = _categorize(row["title"])
        if new_category != "일반공시":
            updates.append((new_category, row["id"]))
            changed += 1

    logger.info(f"카테고리 변경 대상: {changed}건 / {total}건")

    if not updates:
        logger.info("변경할 레코드 없음 — 완료")
        return

    # 3. 배치 업데이트
    sql = "UPDATE disclosures SET category = %s WHERE id = %s"
    with DBConnection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, updates, page_size=500)
        conn.commit()

    logger.info(f"재분류 완료 | 변경={changed}건")

    # 4. 결과 확인
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM disclosures
                GROUP BY category
                ORDER BY cnt DESC
                """
            )
            stats = cur.fetchall()

    logger.info("카테고리 분포:")
    for row in stats:
        logger.info(f"  {row['category']:30s}: {row['cnt']:,}건")


if __name__ == "__main__":
    setup_logger()
    init_pool()
    try:
        run()
    finally:
        close_pool()
