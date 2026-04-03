"""
main.py
APScheduler를 이용해 매일 자동으로 데이터를 수집하고 스코어링을 실행한다.

스케줄:
  16:00 KST — collect_daily()       : 가격·투자자·지수·공시 수집 (pykrx + DART)
  16:30 KST — run_daily()           : 스코어링 → Top 5 추천 저장
  토요일 02:00 KST — collect_finance_weekly() : 재무제표 수집 (분기 데이터)

파이프라인 순서 (run_daily):
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
from datetime import date, datetime, timedelta

import pandas as pd
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.collector.disclosure_collector import DisclosureCollector
from src.collector.finance_collector import FinanceCollector
from src.collector.index_collector import IndexCollector
from src.collector.investor_collector import InvestorCollector
from src.collector.price_collector import PriceCollector
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


def collect_daily(target_date: str | None = None) -> None:
    """
    일일 데이터 수집 파이프라인 (16:00 실행).

    수집 항목:
      1. 코스피 지수   — index_prices (Market Regime 판단용)
      2. 가격·종목마스터 — daily_prices + stocks (OHLCV, 시총)
      3. 투자자 매매동향 — investor_trading
      4. 공시 (최근 30일) — disclosures (필터용, DART 키 필요)

    재무제표는 분기 단위라 매일 수집 불필요 → collect_finance_weekly() 에서 처리.

    Args:
        target_date: 수집 기준일 (YYYY-MM-DD). None이면 오늘.
                     백테스트·수동 재수집 시 과거 날짜 지정 가능.
    """
    today_dt = (
        datetime.strptime(target_date, "%Y-%m-%d").date()
        if target_date
        else date.today()
    )
    today_yyyymmdd = today_dt.strftime("%Y%m%d")
    today_str = today_dt.strftime("%Y-%m-%d")

    logger.info(f"{'=' * 50}")
    logger.info(f"일일 데이터 수집 시작 | {today_str}")
    logger.info(f"{'=' * 50}")

    repo = StockRepository()

    # ------------------------------------------------------------------
    # 1. 코스피 지수 — 스코어링 전에 index_prices 테이블에 있어야 함
    # ------------------------------------------------------------------
    logger.info("[수집 1/4] 코스피 지수")
    try:
        IndexCollector(repo).run(today_yyyymmdd, today_yyyymmdd)
    except Exception as e:
        logger.error(f"코스피 지수 수집 실패 (스코어링 시 Market Regime 판단 불가): {e}")

    # ------------------------------------------------------------------
    # 2. 가격 + 종목 마스터 (PriceCollector.run 내부에서 함께 처리)
    # ------------------------------------------------------------------
    logger.info("[수집 2/4] 가격 · 종목 마스터")
    try:
        PriceCollector(repo).run(today_yyyymmdd, today_yyyymmdd)
    except Exception as e:
        logger.error(f"가격 수집 실패: {e}")

    # ------------------------------------------------------------------
    # 3. 투자자별 매매동향
    # ------------------------------------------------------------------
    logger.info("[수집 3/4] 투자자 매매동향")
    try:
        InvestorCollector(repo).run(today_yyyymmdd, today_yyyymmdd)
    except Exception as e:
        logger.error(f"투자자 데이터 수집 실패: {e}")

    # ------------------------------------------------------------------
    # 4. 공시 — filters.py에서 최근 30일치가 필요하므로 30일 범위 수집
    #    DART API 키 미설정 시 스킵 (필터에서 위험 공시 체크가 작동하지 않음)
    # ------------------------------------------------------------------
    if settings.dart_api_key:
        logger.info("[수집 4/4] 공시 (최근 30일)")
        start_str = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            DisclosureCollector(repo).run(start=start_str, end=today_str)
        except RuntimeError as e:
            # OpenDartReader 미설치 시
            logger.warning(f"공시 수집 스킵 — {e}")
        except Exception as e:
            logger.error(f"공시 수집 실패: {e}")
    else:
        logger.warning(
            "[수집 4/4] DART_API_KEY 미설정 — 공시 수집 스킵 "
            "(위험 공시 필터가 작동하지 않습니다. .env에 DART_API_KEY를 설정하세요)"
        )

    logger.info(f"일일 데이터 수집 완료 | {today_str}")


def collect_finance_weekly() -> None:
    """
    재무제표 주간 수집 (토요일 02:00 실행).

    당해연도 + 전년도 2개 연도를 수집한다.
    재무제표는 분기(3개월)마다 갱신되므로 매일 수집할 필요가 없고,
    350종목 × 분기 4회 × 2년 = DART API 호출 비용이 크다.

    DART API 키 미설정 시 스킵.
    """
    if not settings.dart_api_key:
        logger.warning("DART_API_KEY 미설정 — 재무제표 주간 수집 스킵")
        return

    current_year = date.today().year
    repo = StockRepository()

    logger.info(f"{'=' * 50}")
    logger.info(f"재무제표 주간 수집 시작 | years=[{current_year - 1}, {current_year}]")
    logger.info(f"{'=' * 50}")

    try:
        FinanceCollector(repo).run(years=[current_year - 1, current_year])
    except RuntimeError as e:
        logger.warning(f"재무제표 수집 스킵 — {e}")
    except Exception as e:
        logger.error(f"재무제표 수집 실패: {e}")

    logger.info("재무제표 주간 수집 완료")


def run_daily(target_date: str | None = None) -> None:
    """
    일일 스코어링 파이프라인 메인 함수.

    Args:
        target_date: 스코어링 기준일 (YYYY-MM-DD). None이면 오늘.
                     백테스트 시 과거 날짜를 지정하면 해당 시점 데이터만 사용한다.
    """
    today = target_date or date.today().strftime("%Y-%m-%d")
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
    kospi = repo.get_index_prices(lookback=120, as_of_date=today)
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
            excluded, reason = should_exclude(code, repo, as_of_date=today)
            if excluded:
                logger.debug(f"제외 | code={code} | {reason}")
                continue

            # 데이터 조회
            prices = repo.get_prices(code, lookback=300, as_of_date=today)
            investor = repo.get_investor_trading(code, lookback=20, as_of_date=today)
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

    # 16:00 — 일일 데이터 수집 (가격·투자자·지수·공시)
    # 스코어링(16:30)보다 30분 먼저 실행해 데이터가 준비되도록 한다.
    # 350종목 기준 수집 소요시간 약 10~15분으로 충분한 여유가 있다.
    scheduler.add_job(
        collect_daily,
        CronTrigger(hour=16, minute=0, timezone="Asia/Seoul"),
        id="daily_collect",
        name="일일 데이터 수집",
        misfire_grace_time=300,
        coalesce=True,
    )

    # 16:30 — 일일 스코어링 → Top 5 추천
    scheduler.add_job(
        run_daily,
        CronTrigger(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone="Asia/Seoul",
        ),
        id="daily_scoring",
        name="일일 스코어링",
        misfire_grace_time=300,
        coalesce=True,
    )

    # 토요일 02:00 — 재무제표 주간 수집 (분기 데이터, DART API)
    scheduler.add_job(
        collect_finance_weekly,
        CronTrigger(day_of_week="sat", hour=2, minute=0, timezone="Asia/Seoul"),
        id="weekly_finance",
        name="주간 재무제표 수집",
        misfire_grace_time=1800,   # 30분 내 지연 허용
        coalesce=True,
    )

    logger.info(
        f"스케줄러 시작 | "
        f"수집=매일 16:00, "
        f"스코어링=매일 {settings.schedule_hour:02d}:{settings.schedule_minute:02d}, "
        f"재무제표=토요일 02:00 (KST)"
    )
    scheduler.start()


if __name__ == "__main__":
    main()
