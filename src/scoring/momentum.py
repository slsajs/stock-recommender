"""
momentum.py
모멘텀 지표(거래량 급증, 기관 순매수, 52주 신고가)로 0~100 점수를 산출하는 스코어러.

추세추종(trend-following) 전략:
  - 거래량 급증 → 관심 집중 신호
  - 기관 순매수 지속 → 스마트머니 유입
  - 52주 신고가 근접 → 모멘텀 강세
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.scoring.base import BaseScorer, ScoreResult

# 거래량 평균 계산 기간
VOLUME_WINDOW = 20

# 기관 순매수 합산 기간
INST_WINDOW = 20

# 52주 고가 계산 기간 (거래일 기준)
HIGH52_WINDOW = 252

# 거래량 급증 배수 기준 (5배 → 100점)
VOLUME_SURGE_THRESHOLD = 5.0

# 기본값
DEFAULT_SCORE = 50.0


class MomentumScorer(BaseScorer):
    """거래량 급증 / 기관 순매수 / 52주 신고가 기반 모멘텀 점수 계산."""

    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        Args:
            prices (pd.DataFrame):   daily_prices 조회 결과.
                                     'close', 'high', 'volume' 컬럼 필요.
            investor (pd.DataFrame): investor_trading 조회 결과.
                                     'inst_net_buy' 컬럼 필요.
        """
        prices: pd.DataFrame = kwargs.get("prices", pd.DataFrame())
        investor: pd.DataFrame = kwargs.get("investor", pd.DataFrame())

        result = ScoreResult(code=code)
        result.volume_score = self._volume_score(prices)
        result.inst_score = self._inst_score(investor)
        result.high52_score = self._high52_score(prices)

        valid = [
            s for s in [result.volume_score, result.inst_score, result.high52_score]
            if s is not None
        ]
        result.momentum_score = round(sum(valid) / len(valid), 2) if valid else DEFAULT_SCORE
        return result

    # ------------------------------------------------------------------
    # 거래량 급증
    # ------------------------------------------------------------------

    def _volume_score(self, prices: pd.DataFrame) -> float:
        """
        당일 거래량 / 최근 N일 평균 거래량.
        5배 급증 시 100점, 평균 수준(1배)에서 20점.
        """
        if prices.empty or "volume" not in prices.columns:
            return DEFAULT_SCORE

        vol = pd.to_numeric(prices["volume"], errors="coerce").dropna()
        if len(vol) < 2:
            return DEFAULT_SCORE

        current_vol = vol.iloc[-1]
        avg_vol = vol.iloc[:-1].tail(VOLUME_WINDOW).mean()

        if avg_vol == 0 or pd.isna(avg_vol) or current_vol == 0:
            return DEFAULT_SCORE

        ratio = current_vol / avg_vol
        # 5배 이상 → 100점, 0배 → 0점, 선형 스케일
        score = min(100.0, (ratio / VOLUME_SURGE_THRESHOLD) * 100.0)
        return round(float(np.clip(score, 0.0, 100.0)), 2)

    # ------------------------------------------------------------------
    # 기관 순매수
    # ------------------------------------------------------------------

    def _inst_score(self, investor: pd.DataFrame) -> float:
        """
        최근 N일 기관 순매수 누적액 → z-score → sigmoid → 0~100.
        """
        if investor.empty or "inst_net_buy" not in investor.columns:
            return DEFAULT_SCORE

        recent = pd.to_numeric(
            investor.tail(INST_WINDOW)["inst_net_buy"], errors="coerce"
        ).dropna()

        if recent.empty:
            return DEFAULT_SCORE

        net_sum = recent.sum()
        std = recent.std()

        if std == 0 or pd.isna(std):
            if net_sum > 0:
                return 75.0
            if net_sum < 0:
                return 25.0
            return DEFAULT_SCORE

        # 누적 순매수의 표준화 z-score (단위: 개별 거래일 std * sqrt(N))
        z = net_sum / (std * np.sqrt(len(recent)))
        score = 100.0 / (1.0 + np.exp(-z / 2.0))
        return round(float(np.clip(score, 0.0, 100.0)), 2)

    # ------------------------------------------------------------------
    # 52주 신고가
    # ------------------------------------------------------------------

    def _high52_score(self, prices: pd.DataFrame) -> float:
        """
        현재가 / 52주 최고가 비율.
        신고가 갱신(비율=1.0) → 100점, 멀수록 낮아짐.
        """
        if prices.empty or "high" not in prices.columns or "close" not in prices.columns:
            return DEFAULT_SCORE

        data = prices.tail(HIGH52_WINDOW)
        if len(data) < 2:
            return DEFAULT_SCORE

        high52 = pd.to_numeric(data["high"], errors="coerce").max()
        current_close = pd.to_numeric(data["close"], errors="coerce").iloc[-1]

        if pd.isna(high52) or high52 == 0 or pd.isna(current_close):
            return DEFAULT_SCORE

        ratio = current_close / high52   # 0 < ratio ≤ 1
        score = ratio * 100.0
        return round(float(np.clip(score, 0.0, 100.0)), 2)