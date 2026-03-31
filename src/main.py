"""
main.py
APScheduler를 이용해 매일 16:30에 일일 스코어링 파이프라인을 실행한다.

파이프라인 순서:
  1. Market Regime 판단 (코스피 MA20/MA60)
  2. 재무 데이터 캐시 (루프 밖 한 번만)
  3. 대상 종목 풀 조회
  4. 종목별 필터 → 스코어링
  5. 집계 → Top 5 추출 → DB 저장

실행:
  poetry run python -m src.main
"""
from __future__ import annotations

import signal
import sys
from datetime import date

import pandas as pd
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.config import settings
from src.db.connection import close_pool, init_pool
from src.db.repository import StockRepository
from src.scoring.aggregator import ScoreAggregator
from src.scoring.base import ScoreResult
from src.scoring.filters import should_exclude
from src.scoring.fundamental import FundamentalScorer
from src.scoring.market_regime import determine_regime
from src.scoring.momentum import MomentumScorer
from src.scoring.technical import TechnicalScorer
from src.utils.logger import setup_logger


def run_daily() -> None:
    """일일 스코어링 파이프라인 메인 함수."""
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"{'=' * 50}")
    logger.info(f"일일 스코어링 시작 | {today}")
    logger.info(f"{'=' * 50}")

    repo = StockRepository()
    tech_scorer = TechnicalScorer()
    fund_scorer = FundamentalScorer()
    mom_scorer = MomentumScorer()
    aggregator = ScoreAggregator()

    # ------------------------------------------------------------------
    # 1. Market Regime 판단
    # ------------------------------------------------------------------
    kospi = repo.get_index_prices(lookback=120)
    if kospi.empty:
        logger.error("코스피 지수 데이터 없음 — 스코어링 중단 (index_collector 실행 필요)")
        return

    regime = determine_regime(kospi)
    logger.info(
        f"Market Regime: {regime.regime} "
        f"| MA20={regime.ma20:.1f}, MA60={regime.ma60:.1f} "
        f"| 가중치={regime.weights}"
    )

    # ------------------------------------------------------------------
    # 2. 재무 데이터 캐시 (루프 밖 한 번만 — 성능 필수)
    # ------------------------------------------------------------------
    all_fin = repo.get_all_financials(as_of_date=today)
    sector_fin_map = repo.get_financials_grouped_by_sector(as_of_date=today)
    logger.info(f"재무 데이터 캐시 | 전체={len(all_fin)}건, 섹터={len(sector_fin_map)}개")

    # ------------------------------------------------------------------
    # 3. 대상 종목 풀
    # ------------------------------------------------------------------
    all_stocks = repo.get_all_stocks()
    target_pool = [s["code"] for s in all_stocks]
    logger.info(f"대상 종목 수: {len(target_pool)}")

    # ------------------------------------------------------------------
    # 4. 종목별 필터 → 스코어링
    # ------------------------------------------------------------------
    code_results: dict[str, ScoreResult | Exception] = {}

    for code in target_pool:
        try:
            # 필터 검사
            excluded, reason = should_exclude(code, repo)
            if excluded:
                logger.debug(f"제외 | code={code} | {reason}")
                continue

            # 데이터 조회
            prices = repo.get_prices(code, lookback=300)
            investor = repo.get_investor_trading(code, lookback=20)
            fin = repo.get_latest_financials(code, as_of_date=today) or {}
            stock_info = repo.get_stock(code) or {}
            sector = stock_info.get("sector")
            sector_fin = sector_fin_map.get(sector or "", pd.DataFrame())
            sector_stats = repo.get_sector_stats(sector) if sector else {}

            # 스코어링
            tech = tech_scorer.score(code, prices=prices)
            fund = fund_scorer.score(
                code,
                financials=fin,
                sector_financials=sector_fin,
                all_financials=all_fin,
                sector_stats=sector_stats or {},
            )
            mom = mom_scorer.score(code, prices=prices, investor=investor)

            # 합산 ScoreResult 조립
            combined = ScoreResult(
                code=code,
                rsi_score=tech.rsi_score,
                macd_score=tech.macd_score,
                bb_score=tech.bb_score,
                technical_score=tech.technical_score,
                per_score=fund.per_score,
                pbr_score=fund.pbr_score,
                roe_score=fund.roe_score,
                debt_score=fund.debt_score,
                fundamental_score=fund.fundamental_score,
                volume_score=mom.volume_score,
                inst_score=mom.inst_score,
                high52_score=mom.high52_score,
                momentum_score=mom.momentum_score,
            )
            code_results[code] = combined

        except Exception as e:
            logger.warning(f"스코어링 스킵 | code={code} | reason={e}")
            code_results[code] = e

    # ------------------------------------------------------------------
    # 5. 집계 → Top 5 → DB 저장
    # ------------------------------------------------------------------
    top5 = aggregator.run(code_results, regime)
    if not top5:
        logger.error("추천 종목 없음 — 파이프라인 종료")
        return

    logger.info(f"{'=' * 30} Top 5 추천 {'=' * 30}")
    for r in top5:
        logger.info(
            f"  #{r.rank} {r.code} | 총점={r.total_score} "
            f"| tech={r.technical_score} fund={r.fundamental_score} mom={r.momentum_score}"
        )
        repo.save_stock_score(
            {
                "code": r.code,
                "date": today,
                "rsi_score": r.rsi_score,
                "macd_score": r.macd_score,
                "bb_score": r.bb_score,
                "technical_score": r.technical_score,
                "per_score": r.per_score,
                "pbr_score": r.pbr_score,
                "roe_score": r.roe_score,
                "debt_score": r.debt_score,
                "fundamental_score": r.fundamental_score,
                "volume_score": r.volume_score,
                "inst_score": r.inst_score,
                "high52_score": r.high52_score,
                "momentum_score": r.momentum_score,
                "total_score": r.total_score,
                "rank": r.rank,
                "market_regime": r.market_regime,
            }
        )
        repo.save_recommendation(
            {
                "date": today,
                "rank": r.rank,
                "code": r.code,
                "total_score": r.total_score,
                "reason": None,
            }
        )

    logger.info(f"일일 스코어링 완료 | {today}")


def main() -> None:
    """스케줄러 시작 진입점."""
    setup_logger()
    init_pool()

    # 종료 시그널 처리
    def _shutdown(signum, frame):
        logger.info("종료 시그널 수신 — 스케줄러 중단")
        scheduler.shutdown(wait=False)
        close_pool()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_daily,
        CronTrigger(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone="Asia/Seoul",
        ),
        id="daily_scoring",
        name="일일 스코어링",
        misfire_grace_time=300,   # 5분 내 지연 허용
        coalesce=True,            # 누락된 실행 하나로 합산
    )

    logger.info(
        f"스케줄러 시작 | 매일 {settings.schedule_hour:02d}:{settings.schedule_minute:02d} KST 실행"
    )
    scheduler.start()


if __name__ == "__main__":
    main()
