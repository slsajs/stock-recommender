"""
backtest/summary_builder.py
백테스트 수익률 데이터를 집계하여 BacktestSummary를 생성한다.

BacktestSummaryBuilder.build()가 반환하는 BacktestSummary는
BacktestInsightGenerator에 전달되어 LLM 프롬프트로 직렬화된다.

집계 항목:
  - 보유 기간별 (1/5/20/60일) 평균 수익률, alpha, 승률, 변동성
  - Market Regime별 성과 (5일 기준)
  - 섹터별 성과 (5일 기준)
  - 월별 추이 (5일 기준)
  - 스코어 분포별 승률 (고점수 vs 저점수)
  - 연속 손실 월 수, drawdown 구간
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger

from src.db.repository import StockRepository


# ─────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────

@dataclass
class PeriodStats:
    """특정 보유 기간(days_after)에 대한 성과 요약."""
    days_after: int
    avg_return: float            # 평균 수익률 (%)
    avg_alpha: float             # 평균 alpha = avg_return - avg_benchmark
    win_rate: float              # 수익률 > 0 비율 (0~1)
    beat_benchmark_rate: float   # alpha > 0 비율 (0~1)
    sample_count: int
    best_return: float
    worst_return: float
    std_dev: float               # 수익률 표준편차


@dataclass
class RegimeStats:
    """Market Regime별 성과 요약 (5일 기준)."""
    regime: str
    avg_alpha_5d: float
    win_rate_5d: float
    sample_count: int


@dataclass
class SectorStats:
    """섹터별 성과 요약 (5일 기준)."""
    sector: str
    avg_alpha_5d: float
    win_rate_5d: float
    sample_count: int


@dataclass
class TimeSeriesPoint:
    """월별 성과 추이 포인트 (5일 기준)."""
    year_month: str              # "2025-11"
    avg_alpha_5d: float
    win_rate_5d: float
    rec_count: int


@dataclass
class BacktestSummary:
    """백테스트 전체 요약 — LLM 입력 단위."""

    # 평가 기간
    eval_start: str
    eval_end: str
    total_recommendations: int

    # 기간별 성과
    period_stats: dict[int, PeriodStats]       # {1: ..., 5: ..., 20: ..., 60: ...}

    # Regime별 성과
    regime_stats: list[RegimeStats]
    worst_regime: str
    best_regime: str

    # 섹터별 성과 (alpha 내림차순)
    sector_stats: list[SectorStats]
    worst_sector: str
    best_sector: str

    # 월별 추이
    monthly_trend: list[TimeSeriesPoint]

    # 파생 지표
    consecutive_losing_months: int
    drawdown_periods: list[str]                # alpha < -1.0인 월

    # 스코어 분포
    high_score_win_rate: float                 # total_score > 70 추천 승률
    low_score_win_rate: float                  # total_score <= 50 추천 승률


# ─────────────────────────────────────────────
# 집계 클래스
# ─────────────────────────────────────────────

class BacktestSummaryBuilder:
    """
    StockRepository로부터 백테스트 데이터를 조회하고
    BacktestSummary 형태로 집계한다.

    사용 예:
        builder = BacktestSummaryBuilder(repo)
        summary = builder.build(start_date="2025-01-01")
        if summary:
            report = BacktestInsightGenerator().generate(summary)
    """

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo

    def build(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        min_samples: int = 5,
    ) -> BacktestSummary | None:
        """
        BacktestSummary를 계산하여 반환한다.

        Args:
            start_date:  평가 시작일 (None=전체)
            end_date:    평가 종료일 (None=전체)
            min_samples: Regime/섹터 집계 최소 샘플 수

        Returns:
            BacktestSummary | None (데이터 부족 시)
        """
        df = self.repo.get_backtest_joined_data(start_date, end_date)

        if df.empty or df["recommendation_id"].nunique() < 10:
            logger.warning(
                f"백테스트 집계 데이터 부족 "
                f"(추천 수={df['recommendation_id'].nunique() if not df.empty else 0}) "
                f"— 인사이트 생성 생략"
            )
            return None

        logger.info(
            f"백테스트 집계 시작 | "
            f"추천={df['recommendation_id'].nunique()}건 / 행={len(df)}건"
        )

        period_stats  = self._calc_period_stats(df)
        regime_stats  = self._calc_regime_stats(df, min_samples)
        sector_stats  = self._calc_sector_stats(df, min_samples)
        monthly_trend = self._calc_monthly_trend(df)
        score_dist    = self._calc_score_distribution(df)

        # worst / best regime
        valid_regimes = [r for r in regime_stats if r.sample_count >= min_samples]
        worst_regime = (
            min(valid_regimes, key=lambda x: x.avg_alpha_5d).regime
            if valid_regimes else "N/A"
        )
        best_regime = (
            max(valid_regimes, key=lambda x: x.avg_alpha_5d).regime
            if valid_regimes else "N/A"
        )

        # worst / best sector
        valid_sectors = [s for s in sector_stats if s.sample_count >= min_samples]
        worst_sector = (
            min(valid_sectors, key=lambda x: x.avg_alpha_5d).sector
            if valid_sectors else "N/A"
        )
        best_sector = (
            max(valid_sectors, key=lambda x: x.avg_alpha_5d).sector
            if valid_sectors else "N/A"
        )

        losing_streak = self._calc_consecutive_losing_months(monthly_trend)
        drawdown = [t.year_month for t in monthly_trend if t.avg_alpha_5d < -1.0]

        # 실제 데이터 기반 날짜 범위
        actual_start = start_date or df["date"].min()
        actual_end   = end_date   or df["date"].max()

        summary = BacktestSummary(
            eval_start=str(actual_start),
            eval_end=str(actual_end),
            total_recommendations=df["recommendation_id"].nunique(),
            period_stats=period_stats,
            regime_stats=regime_stats,
            worst_regime=worst_regime,
            best_regime=best_regime,
            sector_stats=sector_stats,
            worst_sector=worst_sector,
            best_sector=best_sector,
            monthly_trend=monthly_trend,
            consecutive_losing_months=losing_streak,
            drawdown_periods=drawdown,
            high_score_win_rate=score_dist["high"],
            low_score_win_rate=score_dist["low"],
        )

        logger.info(
            f"백테스트 집계 완료 | "
            f"기간={summary.eval_start}~{summary.eval_end} | "
            f"추천={summary.total_recommendations}건"
        )
        return summary

    # ── 기간별 집계 ─────────────────────────────────────────

    def _calc_period_stats(self, df: pd.DataFrame) -> dict[int, PeriodStats]:
        stats: dict[int, PeriodStats] = {}
        for days in [1, 5, 20, 60]:
            sub = df[df["days_after"] == days].dropna(subset=["return_rate"]).copy()
            if sub.empty:
                continue

            bm = sub["benchmark_rate"].fillna(0)
            alpha = sub["return_rate"] - bm

            stats[days] = PeriodStats(
                days_after=days,
                avg_return=round(float(sub["return_rate"].mean()), 4),
                avg_alpha=round(float(alpha.mean()), 4),
                win_rate=round(float((sub["return_rate"] > 0).mean()), 4),
                beat_benchmark_rate=round(float((alpha > 0).mean()), 4),
                sample_count=len(sub),
                best_return=round(float(sub["return_rate"].max()), 4),
                worst_return=round(float(sub["return_rate"].min()), 4),
                std_dev=round(float(sub["return_rate"].std()), 4),
            )
        return stats

    # ── Regime별 집계 (5일 기준) ─────────────────────────

    def _calc_regime_stats(
        self, df: pd.DataFrame, min_samples: int
    ) -> list[RegimeStats]:
        sub5 = df[
            (df["days_after"] == 5)
        ].dropna(subset=["return_rate", "market_regime"]).copy()

        result: list[RegimeStats] = []
        for regime, grp in sub5.groupby("market_regime"):
            if len(grp) < min_samples:
                continue
            alpha = grp["return_rate"] - grp["benchmark_rate"].fillna(0)
            result.append(RegimeStats(
                regime=str(regime),
                avg_alpha_5d=round(float(alpha.mean()), 4),
                win_rate_5d=round(float((grp["return_rate"] > 0).mean()), 4),
                sample_count=len(grp),
            ))
        return sorted(result, key=lambda x: x.avg_alpha_5d, reverse=True)

    # ── 섹터별 집계 (5일 기준) ─────────────────────────────

    def _calc_sector_stats(
        self, df: pd.DataFrame, min_samples: int
    ) -> list[SectorStats]:
        sub5 = df[
            (df["days_after"] == 5)
        ].dropna(subset=["return_rate", "sector"]).copy()

        result: list[SectorStats] = []
        for sector, grp in sub5.groupby("sector"):
            if len(grp) < min_samples:
                continue
            alpha = grp["return_rate"] - grp["benchmark_rate"].fillna(0)
            result.append(SectorStats(
                sector=str(sector),
                avg_alpha_5d=round(float(alpha.mean()), 4),
                win_rate_5d=round(float((grp["return_rate"] > 0).mean()), 4),
                sample_count=len(grp),
            ))
        return sorted(result, key=lambda x: x.avg_alpha_5d, reverse=True)

    # ── 월별 추이 집계 (5일 기준) ─────────────────────────

    def _calc_monthly_trend(self, df: pd.DataFrame) -> list[TimeSeriesPoint]:
        sub5 = df[df["days_after"] == 5].dropna(subset=["return_rate"]).copy()
        sub5["year_month"] = (
            pd.to_datetime(sub5["date"]).dt.to_period("M").astype(str)
        )

        result: list[TimeSeriesPoint] = []
        for ym, grp in sub5.groupby("year_month"):
            alpha = grp["return_rate"] - grp["benchmark_rate"].fillna(0)
            result.append(TimeSeriesPoint(
                year_month=str(ym),
                avg_alpha_5d=round(float(alpha.mean()), 4),
                win_rate_5d=round(float((grp["return_rate"] > 0).mean()), 4),
                rec_count=len(grp),
            ))
        return sorted(result, key=lambda x: x.year_month)

    # ── 연속 손실 월 계산 ─────────────────────────────────

    def _calc_consecutive_losing_months(
        self, trend: list[TimeSeriesPoint]
    ) -> int:
        """
        월별 추이에서 가장 최근부터 역순으로 alpha < 0인 연속 개월 수를 반환.
        최신 구간의 부진을 포착하는 것이 목적.
        """
        streak = 0
        for point in reversed(trend):
            if point.avg_alpha_5d < 0:
                streak += 1
            else:
                break
        return streak

    # ── 스코어 분포별 승률 ────────────────────────────────

    def _calc_score_distribution(self, df: pd.DataFrame) -> dict[str, float]:
        sub5 = df[
            (df["days_after"] == 5)
        ].dropna(subset=["return_rate", "total_score"]).copy()

        high = sub5[sub5["total_score"] > 70]
        low  = sub5[sub5["total_score"] <= 50]

        return {
            "high": round(float((high["return_rate"] > 0).mean()), 4)
                    if len(high) >= 3 else 0.0,
            "low":  round(float((low["return_rate"] > 0).mean()), 4)
                    if len(low) >= 3 else 0.0,
        }
