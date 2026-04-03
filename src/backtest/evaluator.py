"""
backtest/evaluator.py
과거 추천 종목의 실제 수익률을 계산하여 recommendation_returns 테이블에 저장.

추천일 기준 1 / 5 / 20 / 60 거래일 후 수익률과
코스피 지수 벤치마크 수익률을 함께 기록한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from src.db.repository import StockRepository

# 평가할 보유 기간 (거래일 기준 — 실제 달력일로 조회하므로 여유 있게 잡음)
# 20거래일 ≈ 28일, 60거래일 ≈ 90일
DAYS_AFTER = [1, 5, 20, 60]
CALENDAR_DAYS_BUFFER = {1: 5, 5: 10, 20: 35, 60: 90}

# 코스피 지수 코드
KOSPI_CODE = "1001"


class BacktestEvaluator:
    """
    추천 종목의 사후 수익률을 계산하는 백테스트 평가기.

    사용 예:
        repo = StockRepository()
        evaluator = BacktestEvaluator(repo)
        evaluator.run()                 # 아직 계산되지 않은 추천 전체 평가
        evaluator.run_for_date("2024-01-15")  # 특정 날짜 추천만 재평가
    """

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # 수익률 계산
    # ------------------------------------------------------------------

    def _calc_return(self, entry_price: int | None, exit_price: int | None) -> float | None:
        """단순 수익률 계산: (exit - entry) / entry * 100."""
        if entry_price is None or exit_price is None or entry_price == 0:
            return None
        return round((exit_price - entry_price) / entry_price * 100, 4)

    def _get_price_after_n_days(
        self, code: str, base_date: str, n_calendar_days: int
    ) -> int | None:
        """
        base_date로부터 n_calendar_days 이후(달력일 기준) 최근 종가 반환.
        거래일이 아닌 날이면 그 이후 가장 가까운 거래일 종가를 사용.
        """
        base_dt = datetime.strptime(base_date, "%Y-%m-%d").date()
        target_dt = base_dt + timedelta(days=n_calendar_days)
        return self.repo.get_price_on_date(code, str(target_dt))

    def _get_index_price_after_n_days(
        self, index_code: str, base_date: str, n_calendar_days: int
    ) -> int | None:
        """코스피 등 지수의 n_calendar_days 이후 종가 반환 (index_prices 테이블)."""
        base_dt = datetime.strptime(base_date, "%Y-%m-%d").date()
        target_dt = base_dt + timedelta(days=n_calendar_days)
        return self.repo.get_index_price_on_date(index_code, str(target_dt))

    def evaluate_recommendation(
        self, recommendation_id: int, rec_date: str, code: str
    ) -> int:
        """
        단일 추천에 대해 days_after별 수익률을 계산하고 저장.

        Returns:
            저장된 평가 건수
        """
        # 추천일 종가 (진입 가격)
        entry_price = self.repo.get_price_on_date(code, rec_date)
        if entry_price is None:
            logger.warning(f"진입 가격 없음 | id={recommendation_id} code={code} date={rec_date}")
            return 0

        # 코스피 기준 가격 (index_prices 테이블 조회)
        kospi_entry = self.repo.get_index_price_on_date(KOSPI_CODE, rec_date)

        saved = 0
        for days in DAYS_AFTER:
            buffer = CALENDAR_DAYS_BUFFER[days]
            exit_price = self._get_price_after_n_days(code, rec_date, buffer)
            return_rate = self._calc_return(entry_price, exit_price)

            # 벤치마크 수익률
            benchmark_rate: float | None = None
            if kospi_entry is not None:
                kospi_exit = self._get_index_price_after_n_days(KOSPI_CODE, rec_date, buffer)
                benchmark_rate = self._calc_return(kospi_entry, kospi_exit)

            try:
                self.repo.save_recommendation_return(
                    {
                        "recommendation_id": recommendation_id,
                        "days_after": days,
                        "return_rate": return_rate,
                        "benchmark_rate": benchmark_rate,
                    }
                )
                saved += 1
                logger.debug(
                    f"수익률 저장 | id={recommendation_id} code={code} "
                    f"days={days} return={return_rate} bench={benchmark_rate}"
                )
            except Exception as e:
                logger.warning(f"수익률 저장 실패 | id={recommendation_id} days={days} | {e}")

        return saved

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        아직 평가되지 않은 모든 추천의 수익률을 계산한다.

        이미 모든 days_after가 계산된 추천은 건너뛴다.
        """
        logger.info("백테스트 평가 시작")
        recs = self.repo.get_all_recommendations()
        today = date.today()

        total_saved = 0
        evaluated = 0

        for rec in recs:
            rec_id = rec["id"]
            rec_date = str(rec["date"])
            code = rec["code"]

            # 이미 계산된 days_after 확인
            existing = {
                r["days_after"]
                for r in self.repo.get_recommendation_returns(rec_id)
                if r["return_rate"] is not None
            }
            missing_days = [d for d in DAYS_AFTER if d not in existing]

            if not missing_days:
                logger.debug(f"이미 평가 완료 | id={rec_id} code={code}")
                continue

            # 아직 기간이 지나지 않은 days_after 제외
            rec_dt = datetime.strptime(rec_date, "%Y-%m-%d").date()
            days_elapsed = (today - rec_dt).days
            evaluable = [
                d for d in missing_days
                if days_elapsed >= CALENDAR_DAYS_BUFFER[d]
            ]

            if not evaluable:
                continue

            n = self.evaluate_recommendation(rec_id, rec_date, code)
            total_saved += n
            evaluated += 1

        logger.info(f"백테스트 평가 완료 | 추천={evaluated}건, 저장={total_saved}건")

    def run_for_date(self, rec_date: str) -> None:
        """특정 날짜 추천에 대해 백테스트를 (재)실행한다."""
        logger.info(f"백테스트 평가 | date={rec_date}")
        recs = [r for r in self.repo.get_all_recommendations() if str(r["date"]) == rec_date]

        if not recs:
            logger.warning(f"추천 없음 | date={rec_date}")
            return

        total_saved = 0
        for rec in recs:
            n = self.evaluate_recommendation(rec["id"], rec_date, rec["code"])
            total_saved += n

        logger.info(f"백테스트 평가 완료 | date={rec_date}, 저장={total_saved}건")
