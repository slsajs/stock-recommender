"""
base.py
스코어링 엔진의 공통 인터페이스와 결과 자료형 정의.

BaseScorer.score()는 **kwargs로 각 하위 클래스에 필요한 데이터를 받는다.
- TechnicalScorer:   prices
- FundamentalScorer: financials, sector_financials, all_financials, sector_stats
- MomentumScorer:    prices, investor
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ScoreResult:
    """단일 종목 스코어링 결과."""

    code: str

    # 기술적 지표 (0~100)
    rsi_score: float | None = None
    macd_score: float | None = None
    bb_score: float | None = None
    technical_score: float | None = None

    # 재무 지표 (0~100)
    per_score: float | None = None
    pbr_score: float | None = None
    roe_score: float | None = None
    debt_score: float | None = None
    fundamental_score: float | None = None

    # 모멘텀 (0~100)
    volume_score: float | None = None
    inst_score: float | None = None
    high52_score: float | None = None
    momentum_score: float | None = None

    # 최종
    total_score: float = 0.0
    rank: int | None = None
    market_regime: str | None = None

    # [고도화] 보정값 (STEP B~F에서 채워짐)
    macro_adjustment: float = 0.0          # 환율·미국시장 보정 (STEP B, D)
    disclosure_adjustment: float = 0.0     # 공시 감성 보정 (STEP E)
    news_adjustment: float = 0.0           # 뉴스 감성 보정 (STEP F)
    adjusted_total_score: float | None = None  # total_score + 모든 보정값 합계


class BaseScorer(ABC):
    """모든 스코어러의 추상 기반 클래스."""

    @abstractmethod
    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        종목 코드와 필요한 데이터(kwargs)를 받아 ScoreResult 반환.

        하위 클래스별 kwargs:
        - TechnicalScorer:   prices (pd.DataFrame)
        - FundamentalScorer: financials (dict), sector_financials (pd.DataFrame),
                             all_financials (pd.DataFrame), sector_stats (dict)
        - MomentumScorer:    prices (pd.DataFrame), investor (pd.DataFrame)
        """

    @staticmethod
    def percentile_score(value: float, series: pd.Series) -> float:
        """
        value가 series 내에서 차지하는 백분위를 반환 (0~100).

        낮은 값이 더 좋은 지표(PER, PBR, 부채비율)는 호출자가 100에서 빼야 한다.
        """
        from scipy.stats import percentileofscore

        clean = series.dropna()
        if clean.empty:
            return 50.0
        return float(percentileofscore(clean, value, kind="rank"))
