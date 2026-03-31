"""
test_market_regime.py
MarketRegime 판단 로직 단위 테스트.
"""
import pandas as pd
import pytest

from src.scoring.market_regime import determine_regime


def _make_kospi(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": prices})


def _make_bull_prices(n: int = 100) -> list[float]:
    """MA20 > MA60이 되도록 최근 구간이 더 높은 가격 시계열 생성."""
    # 앞 60일은 낮고 뒤 40일은 높아서 MA20 > MA60
    base = list(range(1000, 1000 + 60))        # 낮은 구간
    surge = list(range(2000, 2000 + (n - 60))) # 높은 구간
    return base + surge


def _make_bear_prices(n: int = 100) -> list[float]:
    """MA20 < MA60이 되도록 최근 구간이 더 낮은 가격 시계열 생성."""
    # 앞 60일은 높고 뒤 40일은 낮아서 MA20 < MA60
    base = list(range(2000, 2000 + 60))
    drop = list(range(1000, 1000 + (n - 60)))
    return base + drop


class TestDetermineRegime:
    def test_bull_regime_when_ma20_above_ma60(self):
        """MA20 > MA60 → BULL."""
        df = _make_kospi(_make_bull_prices())
        regime = determine_regime(df)
        assert regime.regime == "BULL"

    def test_bear_regime_when_ma20_below_ma60(self):
        """MA20 < MA60 → BEAR."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.regime == "BEAR"

    def test_bull_momentum_weight(self):
        """BULL 시 모멘텀 가중치 0.40."""
        df = _make_kospi(_make_bull_prices())
        regime = determine_regime(df)
        assert regime.weights["momentum"] == pytest.approx(0.40)

    def test_bull_technical_weight(self):
        """BULL 시 기술 가중치 0.20."""
        df = _make_kospi(_make_bull_prices())
        regime = determine_regime(df)
        assert regime.weights["technical"] == pytest.approx(0.20)

    def test_bear_technical_weight(self):
        """BEAR 시 기술 가중치 0.45."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.weights["technical"] == pytest.approx(0.45)

    def test_bear_momentum_weight(self):
        """BEAR 시 모멘텀 가중치 0.15."""
        df = _make_kospi(_make_bear_prices())
        regime = determine_regime(df)
        assert regime.weights["momentum"] == pytest.approx(0.15)

    def test_fundamental_weight_always_40(self):
        """재무 가중치는 시장 상태와 무관하게 항상 0.40."""
        for prices in [_make_bull_prices(), _make_bear_prices()]:
            df = _make_kospi(prices)
            regime = determine_regime(df)
            assert regime.weights["fundamental"] == pytest.approx(0.40)

    def test_weights_sum_to_one(self):
        """가중치 합은 항상 1.0."""
        for prices in [_make_bull_prices(), _make_bear_prices()]:
            df = _make_kospi(prices)
            regime = determine_regime(df)
            total = sum(regime.weights.values())
            assert total == pytest.approx(1.0)

    def test_ma_values_are_set(self):
        """MarketRegime에 ma20, ma60 값이 설정된다."""
        df = _make_kospi(_make_bull_prices())
        regime = determine_regime(df)
        assert regime.ma20 > 0
        assert regime.ma60 > 0
