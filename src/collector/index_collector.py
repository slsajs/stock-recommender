"""
index_collector.py
pykrx를 이용해 코스피 지수(Market Regime 판단용) 데이터를 수집하여 DB에 저장.
"""
from __future__ import annotations

import time

from loguru import logger
from pykrx import stock as krx

from src.collector.price_collector import REQUEST_DELAY
from src.db.repository import StockRepository

# 코스피 종합지수 KRX 코드
KOSPI_INDEX_CODE = "1001"


class IndexCollector:
    """pykrx를 이용해 코스피 지수 종가를 수집한다."""

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # 수집
    # ------------------------------------------------------------------

    def collect(self, fromdate: str, todate: str, index_code: str = KOSPI_INDEX_CODE) -> int:
        """
        지정 기간 코스피 지수 종가 수집 → index_prices 저장.

        Args:
            fromdate:   수집 시작일 (YYYYMMDD)
            todate:     수집 종료일 (YYYYMMDD)
            index_code: KRX 지수 코드 (기본값: '1001' = 코스피)

        Returns:
            저장된 행 수
        """
        try:
            df = krx.get_index_ohlcv_by_date(fromdate, todate, index_code)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.error(f"지수 조회 실패 | index_code={index_code} | {e}")
            return 0

        if df is None or df.empty:
            logger.warning(f"지수 데이터 없음 | index_code={index_code}")
            return 0

        # 종가 컬럼 탐색 (pykrx 버전에 따라 다를 수 있음)
        close_col = _find_close_col(df.columns)
        if close_col is None:
            logger.error(f"종가 컬럼을 찾을 수 없음 | 컬럼={list(df.columns)}")
            return 0

        rows: list[dict] = []
        for idx in df.index:
            close_val = df.loc[idx, close_col]
            try:
                close_int = int(close_val)
            except (TypeError, ValueError):
                continue
            if close_int == 0:
                continue

            rows.append(
                {
                    "index_code": index_code,
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": close_int,
                }
            )

        if rows:
            self.repo.bulk_insert_index_prices(rows)
        return len(rows)

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(self, fromdate: str, todate: str) -> None:
        """
        코스피 지수 수집 진입점.

        Example:
            repo = StockRepository()
            IndexCollector(repo).run("20240101", "20241231")
        """
        logger.info(f"코스피 지수 수집 시작 | {fromdate} ~ {todate}")
        n = self.collect(fromdate, todate)
        logger.info(f"코스피 지수 수집 완료 | {n}건")


# ------------------------------------------------------------------
# 유틸
# ------------------------------------------------------------------

def _find_close_col(columns) -> str | None:
    """종가 컬럼명을 후보 목록에서 탐색."""
    candidates = ["종가", "Close", "close"]
    for c in candidates:
        if c in columns:
            return c
    return None
