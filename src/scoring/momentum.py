"""
momentum.py
모멘텀 지표(거래량 급증, 기관 순매수, 가격 모멘텀)로 0~100 점수를 산출하는 스코어러.

추세추종(trend-following) 전략:
  - 거래량 급증 → 관심 집중 신호 (가중치 35%)
  - 기관 순매수 지속 → 스마트머니 유입 (가중치 35%)
  - 60거래일 가격 모멘텀 → 3개월 추세 강도 (가중치 30%)

개선 B 근거:
  거래량 급증이 BULL 장에서 분배(distribution) 신호로 작동하여 과매수 종목을 선택함.
  기관 순매수(스마트머니)의 가중치를 20% → 35%로 상향하고
  거래량 가중치는 50% → 35%로 조정한다.

  60일 수익률 +30% 초과 종목은 과열 구간으로 판단하여 모멘텀 점수에 페널티를 적용한다.
  이를 통해 이미 급등한 종목의 단기 평균 회귀 위험을 줄인다.

  52주 신고가 지표는 백테스트에서 음의 alpha를 보임 (-0.082 상관계수).
  대신 60거래일(약 3개월) 수익률로 중기 추세를 측정한다.
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

# 가격 모멘텀 계산 기간 (거래일 기준, 약 3개월)
PRICE_MOM_WINDOW = 60

# 거래량 급증 배수 기준 (5배 → 100점)
VOLUME_SURGE_THRESHOLD = 5.0

# 모멘텀 점수 내부 가중치 (개선 B-1)
# 기관 순매수를 20% → 35%로 상향 (스마트머니 신뢰도 반영)
# 거래량은 50% → 35%로 하향 (BULL 장 분배 신호 과대 가중치 제거)
MOMENTUM_WEIGHTS = {
    "volume": 0.35,
    "inst": 0.35,
    "price_momentum": 0.30,
}

# 60일 과열 구간 페널티 (개선 B-2)
# +30% 초과 시 초과분 1%당 0.5점 감점, 최대 -15점
OVEREXTENSION_THRESHOLD: float = 0.30   # 60일 수익률 기준 (30%)
OVEREXTENSION_PENALTY: float = 15.0    # 최대 감점 (점)

# 기본값
DEFAULT_SCORE = 50.0


class MomentumScorer(BaseScorer):
    """거래량 급증 / 기관 순매수 / 가격 모멘텀 기반 모멘텀 점수 계산."""

    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        Args:
            prices (pd.DataFrame):   daily_prices 조회 결과.
                                     'close', 'volume' 컬럼 필요.
            investor (pd.DataFrame): investor_trading 조회 결과.
                                     'inst_net_buy' 컬럼 필요.
        """
        prices: pd.DataFrame = kwargs.get("prices", pd.DataFrame())
        investor: pd.DataFrame = kwargs.get("investor", pd.DataFrame())

        result = ScoreResult(code=code)
        result.volume_score = self._volume_score(prices)
        result.inst_score = self._inst_score(investor)
        result.price_momentum_score = self._price_momentum_score(prices)

        # 가중 평균 (각 신호가 None이면 기본값 50.0으로 대체)
        vol = result.volume_score if result.volume_score is not None else DEFAULT_SCORE
        inst = result.inst_score if result.inst_score is not None else DEFAULT_SCORE
        pmom = result.price_momentum_score if result.price_momentum_score is not None else DEFAULT_SCORE

        result.momentum_score = round(
            vol * MOMENTUM_WEIGHTS["volume"]
            + inst * MOMENTUM_WEIGHTS["inst"]
            + pmom * MOMENTUM_WEIGHTS["price_momentum"],
            2,
        )
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
    # 가격 모멘텀 (60거래일 수익률)
    # ------------------------------------------------------------------

    def _price_momentum_score(self, prices: pd.DataFrame, lookback: int = PRICE_MOM_WINDOW) -> float:
        """
        최근 lookback 거래일 수익률을 sigmoid로 0~100 점수로 변환.

        공식:
            return_60d = (현재가 - 60일전 종가) / 60일전 종가
            score = 100 / (1 + exp(-return_60d / 0.10))

        참조값:
            수익률  0%   → 50점 (중립)
            수익률 +10%  → 73점
            수익률 +20%  → 88점
            수익률 -10%  → 27점
            수익률 -20%  → 12점

        데이터 부족(lookback + 1일 미만) → DEFAULT_SCORE(50.0) 반환.
        """
        if prices.empty or "close" not in prices.columns:
            return DEFAULT_SCORE

        close = pd.to_numeric(prices["close"], errors="coerce").dropna()
        if len(close) < lookback + 1:
            return DEFAULT_SCORE

        current_close = close.iloc[-1]
        past_close = close.iloc[-(lookback + 1)]

        if past_close == 0 or pd.isna(past_close) or pd.isna(current_close):
            return DEFAULT_SCORE

        return_60d = (current_close - past_close) / past_close
        score = 100.0 / (1.0 + np.exp(-return_60d / 0.10))

        # 과열 구간 페널티 (개선 B-2): 60일 수익률 +30% 초과분에 비례해 감점
        # +30%에서 0점, +60%에서 최대 -15점 (초과분 * 50)
        if return_60d > OVEREXTENSION_THRESHOLD:
            overextension = return_60d - OVEREXTENSION_THRESHOLD
            penalty = min(OVEREXTENSION_PENALTY, overextension * 50.0)
            score = max(0.0, score - penalty)

        return round(float(np.clip(score, 0.0, 100.0)), 2)