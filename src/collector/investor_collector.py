"""
investor_collector.py
pykrx를 이용해 코스피200 + 코스닥150 종목의 투자자별 순매수 데이터를 수집하여 DB에 저장.
"""
from __future__ import annotations

import time

import pandas as pd
from loguru import logger
from pykrx import stock as krx

from src.collector.price_collector import PriceCollector, REQUEST_DELAY
from src.db.repository import StockRepository

# 투자자 유형별 컬럼명 후보 (pykrx 버전에 따라 다를 수 있음)
_INST_COLS = ["기관합계", "기관계"]
_FOREIGN_COLS = ["외국인합계", "외국인"]
_RETAIL_COLS = ["개인"]


class InvestorCollector:
    """pykrx를 이용해 종목별 투자자별 순매수금액을 수집한다."""

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo
        self._price_collector = PriceCollector(repo)

    # ------------------------------------------------------------------
    # 단일 종목
    # ------------------------------------------------------------------

    def collect_for_ticker(self, code: str, fromdate: str, todate: str) -> int:
        """
        단일 종목 투자자별 순매수 수집 → investor_trading 저장.

        Returns:
            저장된 행 수
        """
        try:
            df = krx.get_market_trading_value_by_date(fromdate, todate, code)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"투자자 데이터 조회 실패 | code={code} | {e}")
            return 0

        if df is None or df.empty:
            return 0

        rows: list[dict] = []
        for idx in df.index:
            row = df.loc[idx]
            rows.append(
                {
                    "code": code,
                    "date": idx.strftime("%Y-%m-%d"),
                    "inst_net_buy": _find_col(row, _INST_COLS),
                    "foreign_net_buy": _find_col(row, _FOREIGN_COLS),
                    "retail_net_buy": _find_col(row, _RETAIL_COLS),
                }
            )

        if rows:
            self.repo.bulk_insert_investor_trading(rows)
        return len(rows)

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(self, fromdate: str, todate: str, ref_date: str | None = None) -> None:
        """
        코스피200 + 코스닥150 전체 종목 투자자별 순매수 수집.

        Args:
            fromdate: 수집 시작일 (YYYYMMDD)
            todate:   수집 종료일 (YYYYMMDD)
            ref_date: 종목 풀 기준일 (기본값: todate)

        Example:
            repo = StockRepository()
            InvestorCollector(repo).run("20240101", "20241231")
        """
        ref_date = ref_date or todate
        logger.info(f"투자자 데이터 수집 시작 | {fromdate} ~ {todate} | 종목풀 기준일={ref_date}")

        pool = self._price_collector.get_target_pool(ref_date)
        pairs: list[tuple[str, str]] = (
            [(t, "KOSPI") for t in pool["KOSPI"]]
            + [(t, "KOSDAQ") for t in pool["KOSDAQ"]]
        )
        total = len(pairs)
        saved = 0

        for i, (code, market) in enumerate(pairs, 1):
            n = self.collect_for_ticker(code, fromdate, todate)
            saved += n
            if n == 0:
                logger.warning(f"저장 0건 | [{i}/{total}] code={code} market={market}")
            else:
                logger.debug(f"저장 {n}건 | [{i}/{total}] code={code} market={market}")

        logger.info(f"투자자 데이터 수집 완료 | 종목={total}, 저장={saved}건")


# ------------------------------------------------------------------
# 유틸
# ------------------------------------------------------------------

def _find_col(row: pd.Series, candidates: list[str]) -> int | None:
    """후보 컬럼명 중 실제로 존재하는 첫 번째 값을 int로 반환."""
    for col in candidates:
        if col in row.index:
            try:
                return int(row[col])
            except (TypeError, ValueError):
                return None
    return None
