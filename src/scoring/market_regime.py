"""
market_regime.py
코스피 지수의 이동평균(MA20, MA60)을 비교해 시장 상태(BULL/BEAR)를 판단하고
동적 가중치를 결정한다.

- BULL (MA20 > MA60): 추세추종 비중 ↑ → momentum 40%, fundamental 40%, technical 20%
- BEAR (MA20 ≤ MA60): 역추세 비중 ↑  → technical 45%, fundamental 40%, momentum 15%
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketRegime:
    regime: str          # "BULL" or "BEAR"
    weights: dict        # {"technical": float, "fundamental": float, "momentum": float}
    ma20: float
    ma60: float


def determine_regime(kospi_prices: pd.DataFrame) -> MarketRegime:
    """
    코스피 종가 기준 MA20 > MA60이면 BULL, 아니면 BEAR.

    Args:
        kospi_prices: index_prices 테이블에서 조회한 DataFrame.
                      최소 60행 이상의 'close' 컬럼 필요.

    Returns:
        MarketRegime 인스턴스
    """
    close = kospi_prices["close"].astype(float)

    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    if ma20 > ma60:
        return MarketRegime(
            regime="BULL",
            weights={"technical": 0.20, "fundamental": 0.40, "momentum": 0.40},
            ma20=float(ma20),
            ma60=float(ma60),
        )
    else:
        return MarketRegime(
            regime="BEAR",
            weights={"technical": 0.45, "fundamental": 0.40, "momentum": 0.15},
            ma20=float(ma20),
            ma60=float(ma60),
        )
