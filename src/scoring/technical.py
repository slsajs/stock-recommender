"""
technical.py
기술적 지표(RSI, MACD, 볼린저밴드)로 0~100 점수를 산출하는 스코어러.

역추세(contrarian) 전략:
  - RSI 과매도(≤30) → 높은 점수 (반등 기대)
  - RSI 과매수(≥70) → 낮은 점수
  - 볼린저 하단 근접 → 높은 점수
  - MACD 히스토그램 양수 → 추세 전환 시작 → 높은 점수
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.scoring.base import BaseScorer, ScoreResult

# 최소 데이터 수 — 이보다 적으면 전체 50.0 반환
MIN_PERIODS = 5

# RSI 파라미터
RSI_PERIOD = 14

# MACD 파라미터
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL_PERIOD = 9

# 볼린저밴드 파라미터
BB_PERIOD = 20
BB_STD_MULT = 2.0

# 기본값 (데이터 부족 시)
DEFAULT_SCORE = 50.0


class TechnicalScorer(BaseScorer):
    """RSI, MACD, 볼린저밴드 기반 기술적 점수 계산."""

    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        Args:
            prices (pd.DataFrame): daily_prices 조회 결과.
                                   'close' 컬럼 필수, 'high'/'low' 선택.
        """
        prices: pd.DataFrame = kwargs.get("prices", pd.DataFrame())
        result = ScoreResult(code=code)

        if len(prices) < MIN_PERIODS:
            result.rsi_score = DEFAULT_SCORE
            result.macd_score = DEFAULT_SCORE
            result.bb_score = DEFAULT_SCORE
            result.technical_score = DEFAULT_SCORE
            return result

        close = prices["close"].astype(float)

        result.rsi_score = self._rsi_score(close)
        result.macd_score = self._macd_score(close)
        result.bb_score = self._bb_score(close)
        result.technical_score = round(
            (result.rsi_score + result.macd_score + result.bb_score) / 3, 2
        )
        return result

    # ------------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------------

    def _rsi_score(self, close: pd.Series) -> float:
        """RSI 역추세 점수. 과매도(RSI 낮음) → 고점수."""
        if len(close) < RSI_PERIOD + 1:
            return DEFAULT_SCORE

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        # Wilder EMA (com = period - 1)
        avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
        avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()

        last_loss = avg_loss.iloc[-1]
        last_gain = avg_gain.iloc[-1]

        if pd.isna(last_gain) or pd.isna(last_loss):
            return DEFAULT_SCORE

        if last_loss == 0:
            rsi = 100.0
        else:
            rs = last_gain / last_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 역추세: score = 100 - RSI
        # RSI=30 → score=70, RSI=70 → score=30
        score = 100.0 - rsi
        return round(float(np.clip(score, 0.0, 100.0)), 2)

    # ------------------------------------------------------------------
    # MACD
    # ------------------------------------------------------------------

    def _macd_score(self, close: pd.Series) -> float:
        """MACD 히스토그램으로 추세 전환 강도 점수화."""
        if len(close) < MACD_SLOW + MACD_SIGNAL_PERIOD:
            return DEFAULT_SCORE

        ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=MACD_SIGNAL_PERIOD, adjust=False).mean()
        histogram = macd_line - signal_line

        last_hist = histogram.iloc[-1]
        if pd.isna(last_hist):
            return DEFAULT_SCORE

        hist_std = histogram.std()
        if pd.isna(hist_std) or hist_std == 0:
            return 100.0 if last_hist > 0 else (0.0 if last_hist < 0 else DEFAULT_SCORE)

        # z-score → sigmoid → 0~100
        z = last_hist / hist_std
        score = 100.0 / (1.0 + np.exp(-z))
        return round(float(np.clip(score, 0.0, 100.0)), 2)

    # ------------------------------------------------------------------
    # 볼린저밴드
    # ------------------------------------------------------------------

    def _bb_score(self, close: pd.Series) -> float:
        """볼린저밴드 %B 역추세 점수. 하단 근접 → 고점수."""
        if len(close) < BB_PERIOD:
            return DEFAULT_SCORE

        ma = close.rolling(BB_PERIOD).mean()
        std = close.rolling(BB_PERIOD).std()
        upper = ma + BB_STD_MULT * std
        lower = ma - BB_STD_MULT * std

        last_close = close.iloc[-1]
        last_upper = upper.iloc[-1]
        last_lower = lower.iloc[-1]

        if pd.isna(last_upper) or pd.isna(last_lower):
            return DEFAULT_SCORE

        band_width = last_upper - last_lower
        if band_width == 0:
            return DEFAULT_SCORE

        # %B: 0 = 하단밴드, 1 = 상단밴드
        pct_b = (last_close - last_lower) / band_width
        # 역추세: 하단 근접(pct_b ≈ 0) → 100점
        score = 100.0 * (1.0 - pct_b)
        return round(float(np.clip(score, 0.0, 100.0)), 2)
