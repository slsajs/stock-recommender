"""
market_regime.py
코스피 지수의 이동평균(MA20, MA60)을 비교해 시장 상태를 판단하고
동적 가중치를 결정한다.

Regime 체계 (개선 C 적용):
  MA20 > MA60 일 때 두 단계로 세분화한다.

  EARLY_BULL  — MA20이 MA60을 돌파한 지 ≤ 20 거래일 AND MA 이격률 ≤ 5%
                추세 초입 / 진짜 전환 신호 → momentum 60%
  LATE_BULL   — MA20이 MA60 위에서 > 20 거래일 OR 이격률 > 5% (과열)
                추세 성숙 / 고점 위험 → 균형 50%
  BEAR        — MA20 ≤ MA60
                하락·횡보 → fundamental 방어 55%

개선 A·C 근거:
  백테스트에서 BULL(momentum=0.65) 구간이 BEAR보다 alpha 열위.
  MA20>MA60 감지 시점 자체가 이미 후행(상승 중반 이상)이어서 BULL 단일 가중치 부여 시
  과매수 종목 선택 → 5일 후 평균 회귀가 발생한다.
  EARLY_BULL에서만 momentum을 60%로 유지하고, LATE_BULL은 50%로 균형을 맞춘다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketRegime:
    regime: str   # "EARLY_BULL" / "LATE_BULL" / "BEAR"
    weights: dict  # {"technical": float, "fundamental": float, "momentum": float}
    ma20: float
    ma60: float


# MA 이격률 임계값 (%) — 이격률이 이를 초과하면 추세 초입이어도 과열로 분류
MA_SPREAD_THRESHOLD: float = 5.0

# EARLY/LATE 경계 거래일 수
DAYS_ABOVE_THRESHOLD: int = 20


def _count_days_above(close: pd.Series) -> int:
    """
    MA20이 MA60을 연속으로 초과한 거래일 수를 반환한다.

    MA20 > MA60이 처음 성립한 날부터 오늘까지 이어진 연속 일수를 카운트한다.
    한 번이라도 MA20 ≤ MA60으로 돌아오면 카운트를 리셋한다.

    데이터 부족(NaN 포함)이나 현재 BEAR 상태이면 0 반환.
    """
    ma20_series = close.rolling(20).mean()
    ma60_series = close.rolling(60).mean()
    above = (ma20_series > ma60_series).dropna()

    if above.empty or not above.iloc[-1]:
        return 0

    count = 0
    for val in reversed(above.values):
        if val:
            count += 1
        else:
            break
    return count


def determine_regime(kospi_prices: pd.DataFrame) -> MarketRegime:
    """
    코스피 종가 기준 MA20/MA60 + 이격률 + 연속 일수를 종합해 Regime을 결정한다.

    Args:
        kospi_prices: index_prices 테이블에서 조회한 DataFrame.
                      최소 60행 이상의 'close' 컬럼 필요.

    Returns:
        MarketRegime 인스턴스.

    판단 로직:
        ┌─────────────────────────┬────────────────┬──────────────┐
        │ MA 조건                  │ 이격률/일수     │ Regime       │
        ├─────────────────────────┼────────────────┼──────────────┤
        │ MA20 > MA60             │ 이격률 > 5%    │ LATE_BULL    │
        │ MA20 > MA60             │ 연속 ≤ 20일    │ EARLY_BULL   │
        │ MA20 > MA60             │ 연속 > 20일    │ LATE_BULL    │
        │ MA20 ≤ MA60             │ (무관)         │ BEAR         │
        └─────────────────────────┴────────────────┴──────────────┘
    """
    close = kospi_prices["close"].astype(float)

    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    if ma20 > ma60:
        ma_spread_pct = (ma20 - ma60) / ma60 * 100

        # 이격률 과열 체크 — 일수와 무관하게 LATE_BULL 강제 분류
        if ma_spread_pct > MA_SPREAD_THRESHOLD:
            return MarketRegime(
                regime="LATE_BULL",
                weights={"technical": 0.00, "fundamental": 0.50, "momentum": 0.50},
                ma20=float(ma20),
                ma60=float(ma60),
            )

        days_above = _count_days_above(close)
        if days_above <= DAYS_ABOVE_THRESHOLD:
            # 추세 초입 — momentum 적극 활용
            return MarketRegime(
                regime="EARLY_BULL",
                weights={"technical": 0.00, "fundamental": 0.40, "momentum": 0.60},
                ma20=float(ma20),
                ma60=float(ma60),
            )
        else:
            # 추세 성숙 — 균형 유지
            return MarketRegime(
                regime="LATE_BULL",
                weights={"technical": 0.00, "fundamental": 0.50, "momentum": 0.50},
                ma20=float(ma20),
                ma60=float(ma60),
            )
    else:
        return MarketRegime(
            regime="BEAR",
            weights={"technical": 0.00, "fundamental": 0.55, "momentum": 0.45},
            ma20=float(ma20),
            ma60=float(ma60),
        )
