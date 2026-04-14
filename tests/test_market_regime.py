"""
test_market_regime.py
MarketRegime 판단 로직 단위 테스트.

개선 A·C 반영:
  BULL → EARLY_BULL / LATE_BULL 두 단계로 세분화.
  - EARLY_BULL: MA20이 MA60을 돌파한 지 ≤ 20 거래일 AND 이격률 ≤ 5%
                weights = {fundamental: 0.40, momentum: 0.60}
  - LATE_BULL:  MA20이 MA60 위 > 20 거래일 OR 이격률 > 5%
                weights = {fundamental: 0.50, momentum: 0.50}
  - BEAR:       MA20 ≤ MA60
                weights = {fundamental: 0.55, momentum: 0.45}
"""
import pandas as pd
import pytest

from src.scoring.market_regime import (
    DAYS_ABOVE_THRESHOLD,
    MA_SPREAD_THRESHOLD,
    _count_days_above,
    determine_regime,
)


def _make_kospi(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": prices})


# ---------------------------------------------------------------------------
# 헬퍼 — 다양한 Regime 시나리오를 만드는 가격 시계열 생성기
# ---------------------------------------------------------------------------

def _make_bear_prices(n: int = 100) -> list[float]:
    """MA20 < MA60 — 하락 구간."""
    base = list(range(2000, 2000 + 60))
    drop = list(range(1000, 1000 + (n - 60)))
    return base + drop


def _make_early_bull_prices(n_flat: int = 80, n_high: int = 10) -> list[float]:
    """
    EARLY_BULL 조건:
      - MA20이 MA60을 돌파한 지 ≤ 20 거래일
      - MA 이격률 ≤ 5% (소폭 상승)

    n_flat=80 flat(2000) + n_high=10 high(2050) = 90일.
    MA20 ≈ 2025, MA60 ≈ 2008 → 이격률 ≈ 0.8% < 5%.
    MA20>MA60 연속 일수 = n_high = 10 ≤ 20 → EARLY_BULL.
    """
    return [2000.0] * n_flat + [2050.0] * n_high


def _make_late_bull_by_days(n_flat: int = 70, n_high: int = 25) -> list[float]:
    """
    LATE_BULL 조건 (일수 기준):
      - MA20>MA60 연속 > 20 거래일
      - 이격률은 5% 이하 (소폭 상승)

    n_flat=70 flat(2000) + n_high=25 high(2050) = 95일.
    MA20>MA60 연속 일수 = 25 > 20 → LATE_BULL.
    """
    return [2000.0] * n_flat + [2050.0] * n_high


def _make_late_bull_by_spread() -> list[float]:
    """
    LATE_BULL 조건 (이격률 기준):
      - MA 이격률 > 5% → 추세 초입이어도 LATE_BULL 강제 분류
      - n_flat=80 flat(2000) + n_high=10 high(3000) = 90일.
      - MA20 ≈ 2500, MA60 ≈ 2167 → 이격률 ≈ 15% > 5%.
      - MA20>MA60 연속 일수 = 10 ≤ 20 이지만 이격률로 LATE_BULL.
    """
    return [2000.0] * 80 + [3000.0] * 10


# ---------------------------------------------------------------------------
# BEAR 테스트
# ---------------------------------------------------------------------------

class TestBearRegime:
    def test_bear_when_ma20_below_ma60(self):
        """MA20 < MA60 → BEAR."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.regime == "BEAR"

    def test_bear_fundamental_weight(self):
        """BEAR 재무 가중치 0.55 (개선 C)."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.weights["fundamental"] == pytest.approx(0.55)

    def test_bear_momentum_weight(self):
        """BEAR 모멘텀 가중치 0.45 (개선 C)."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.weights["momentum"] == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# EARLY_BULL 테스트
# ---------------------------------------------------------------------------

class TestEarlyBullRegime:
    def test_early_bull_regime(self):
        """MA20>MA60 연속 ≤ 20일 + 이격률 ≤ 5% → EARLY_BULL."""
        df = _make_kospi(_make_early_bull_prices(n_flat=80, n_high=10))
        regime = determine_regime(df)
        assert regime.regime == "EARLY_BULL"

    def test_early_bull_momentum_weight(self):
        """EARLY_BULL 모멘텀 가중치 0.60."""
        df = _make_kospi(_make_early_bull_prices(n_flat=80, n_high=10))
        regime = determine_regime(df)
        assert regime.weights["momentum"] == pytest.approx(0.60)

    def test_early_bull_fundamental_weight(self):
        """EARLY_BULL 재무 가중치 0.40."""
        df = _make_kospi(_make_early_bull_prices(n_flat=80, n_high=10))
        regime = determine_regime(df)
        assert regime.weights["fundamental"] == pytest.approx(0.40)

    def test_early_bull_boundary_20_days(self):
        """MA20>MA60 연속 정확히 20일 → EARLY_BULL (경계값)."""
        df = _make_kospi(_make_early_bull_prices(n_flat=70, n_high=20))
        regime = determine_regime(df)
        assert regime.regime == "EARLY_BULL"


# ---------------------------------------------------------------------------
# LATE_BULL 테스트
# ---------------------------------------------------------------------------

class TestLateBullRegime:
    def test_late_bull_by_days(self):
        """MA20>MA60 연속 > 20일 → LATE_BULL."""
        df = _make_kospi(_make_late_bull_by_days(n_flat=70, n_high=25))
        regime = determine_regime(df)
        assert regime.regime == "LATE_BULL"

    def test_late_bull_by_spread(self):
        """MA 이격률 > 5% → LATE_BULL 강제 분류 (일수 ≤ 20이어도)."""
        df = _make_kospi(_make_late_bull_by_spread())
        regime = determine_regime(df)
        assert regime.regime == "LATE_BULL"

    def test_late_bull_momentum_weight(self):
        """LATE_BULL 모멘텀 가중치 0.50."""
        df = _make_kospi(_make_late_bull_by_days(n_flat=70, n_high=25))
        regime = determine_regime(df)
        assert regime.weights["momentum"] == pytest.approx(0.50)

    def test_late_bull_fundamental_weight(self):
        """LATE_BULL 재무 가중치 0.50."""
        df = _make_kospi(_make_late_bull_by_days(n_flat=70, n_high=25))
        regime = determine_regime(df)
        assert regime.weights["fundamental"] == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# 공통 불변 조건
# ---------------------------------------------------------------------------

class TestRegimeInvariants:
    def test_technical_weight_always_zero(self):
        """기술 가중치는 모든 Regime에서 0.0."""
        scenarios = [
            _make_bear_prices(),
            _make_early_bull_prices(),
            _make_late_bull_by_days(),
            _make_late_bull_by_spread(),
        ]
        for prices in scenarios:
            df = _make_kospi(prices)
            regime = determine_regime(df)
            assert regime.weights["technical"] == pytest.approx(0.0), \
                f"{regime.regime}에서 기술 가중치 != 0"

    def test_weights_sum_to_one(self):
        """가중치 합은 모든 Regime에서 1.0."""
        scenarios = [
            _make_bear_prices(),
            _make_early_bull_prices(),
            _make_late_bull_by_days(),
            _make_late_bull_by_spread(),
        ]
        for prices in scenarios:
            df = _make_kospi(prices)
            regime = determine_regime(df)
            total = sum(regime.weights.values())
            assert total == pytest.approx(1.0), \
                f"{regime.regime} 가중치 합 = {total} ≠ 1.0"

    def test_ma_values_are_set(self):
        """MarketRegime에 ma20, ma60 값이 양수로 설정된다."""
        df = _make_kospi(_make_early_bull_prices())
        regime = determine_regime(df)
        assert regime.ma20 > 0
        assert regime.ma60 > 0


# ---------------------------------------------------------------------------
# _count_days_above 단위 테스트
# ---------------------------------------------------------------------------

class TestCountDaysAbove:
    def test_zero_when_bear(self):
        """BEAR 상태 → 0 반환."""
        prices = pd.Series(_make_bear_prices())
        assert _count_days_above(prices) == 0

    def test_counts_consecutive_bull_days(self):
        """EARLY_BULL 10일 → 10 반환."""
        prices = pd.Series(_make_early_bull_prices(n_flat=80, n_high=10))
        count = _count_days_above(prices)
        assert count == 10

    def test_counts_25_days(self):
        """LATE_BULL 25일 → 25 반환."""
        prices = pd.Series(_make_late_bull_by_days(n_flat=70, n_high=25))
        count = _count_days_above(prices)
        assert count == 25

    def test_resets_after_bear_interruption(self):
        """BULL → BEAR → BULL 흐름에서 마지막 BULL 연속 일수만 카운트.

        구성:
          80일 flat(2000) + 10일 high(2100) → MA20 > MA60 (BULL)
          60일 crash(1500)                  → MA20 < MA60 (BEAR 복귀)
          5일 recovery(2100)               → MA20 > MA60 재진입 → count=5

        검증 포인트:
          crash 마지막 시점: MA20=1500, MA60=1600 → BEAR ✓
          recovery 5일 후:   MA20≈1650, MA60≈1550 → BULL, days_above=5 ✓
        """
        prices = [2000.0] * 80 + [2100.0] * 10 + [1500.0] * 60 + [2100.0] * 5
        count = _count_days_above(pd.Series(prices))
        assert count == 5
