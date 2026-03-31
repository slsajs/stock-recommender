"""
test_momentum.py
MomentumScorer 단위 테스트.
"""
import pandas as pd
import pytest

from src.scoring.momentum import MomentumScorer


@pytest.fixture
def scorer() -> MomentumScorer:
    return MomentumScorer()


def _make_prices(
    closes: list[float],
    highs: list[float] | None = None,
    volumes: list[int] | None = None,
) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "close": closes,
            "high": highs or [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "volume": volumes or [1_000_000] * n,
        }
    )


def _make_investor(inst_net_buys: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "inst_net_buy": inst_net_buys,
            "foreign_net_buy": [0] * len(inst_net_buys),
            "retail_net_buy": [0] * len(inst_net_buys),
        }
    )


class TestVolumeScore:
    def test_5x_surge_gives_100(self, scorer):
        """거래량 5배 급증 → volume_score = 100."""
        avg_vol = 1_000_000
        volumes = [avg_vol] * 20 + [avg_vol * 5]  # 마지막 날 5배
        prices = _make_prices([10000] * 21, volumes=volumes)
        result = scorer.score("TEST", prices=prices)
        assert result.volume_score == pytest.approx(100.0, abs=1.0)

    def test_more_than_5x_capped_at_100(self, scorer):
        """거래량 10배 → volume_score = 100 (상한)."""
        volumes = [1_000_000] * 20 + [10_000_000]
        prices = _make_prices([10000] * 21, volumes=volumes)
        result = scorer.score("TEST", prices=prices)
        assert result.volume_score == pytest.approx(100.0, abs=0.1)

    def test_average_volume_gives_moderate_score(self, scorer):
        """평균 거래량 → volume_score ≈ 20."""
        volumes = [1_000_000] * 21
        prices = _make_prices([10000] * 21, volumes=volumes)
        result = scorer.score("TEST", prices=prices)
        # ratio = 1.0, score = (1/5)*100 = 20
        assert result.volume_score == pytest.approx(20.0, abs=1.0)

    def test_empty_prices_returns_default(self, scorer):
        """거래량 데이터 없음 → volume_score = 50.0."""
        result = scorer.score("TEST", prices=pd.DataFrame())
        assert result.volume_score == 50.0

    def test_missing_volume_column_returns_default(self, scorer):
        """volume 컬럼 없음 → 50.0."""
        prices = pd.DataFrame({"close": [10000] * 10, "high": [10100] * 10})
        result = scorer.score("TEST", prices=prices)
        assert result.volume_score == 50.0


class TestInstScore:
    def test_consistent_net_buy_gives_high_score(self, scorer):
        """기관 지속 순매수 → inst_score > 50."""
        investor = _make_investor([1_000_000_000] * 20)
        result = scorer.score("TEST", prices=pd.DataFrame(), investor=investor)
        assert result.inst_score > 50.0

    def test_consistent_net_sell_gives_low_score(self, scorer):
        """기관 지속 순매도 → inst_score < 50."""
        investor = _make_investor([-1_000_000_000] * 20)
        result = scorer.score("TEST", prices=pd.DataFrame(), investor=investor)
        assert result.inst_score < 50.0

    def test_empty_investor_returns_default(self, scorer):
        """투자자 데이터 없음 → inst_score = 50.0."""
        result = scorer.score("TEST", prices=pd.DataFrame())
        assert result.inst_score == 50.0


class TestHigh52Score:
    def test_52week_high_renewal_gives_100(self, scorer):
        """52주 신고가 갱신 → high52_score = 100."""
        # 현재 종가 == 52주 최고가
        closes = list(range(9000, 9990, 10)) + [10000]  # 마지막 날 신고가
        highs = closes.copy()
        prices = _make_prices(closes, highs=highs)
        result = scorer.score("TEST", prices=prices)
        assert result.high52_score == pytest.approx(100.0, abs=1.0)

    def test_far_from_high_gives_low_score(self, scorer):
        """52주 고가 대비 현재가 60% → high52_score ≈ 60."""
        high_price = 10000.0
        current = 6000.0
        # 52주 고가를 히스토리 중 한 번 찍고 현재는 낮음
        closes = [high_price] + [current] * 50
        highs = [high_price] + [current * 1.01] * 50
        prices = _make_prices(closes, highs=highs)
        result = scorer.score("TEST", prices=prices)
        assert result.high52_score == pytest.approx(60.0, abs=5.0)

    def test_empty_prices_returns_default(self, scorer):
        """가격 데이터 없음 → high52_score = 50.0."""
        result = scorer.score("TEST", prices=pd.DataFrame())
        assert result.high52_score == 50.0


class TestMomentumScore:
    def test_momentum_score_is_average(self, scorer):
        """momentum_score = (volume + inst + high52) / 3."""
        volumes = [1_000_000] * 20 + [5_000_000]  # 5배 급증
        closes = list(range(9000, 9100)) + [9100]
        highs = closes.copy()
        prices = _make_prices(closes, highs=highs, volumes=volumes)
        investor = _make_investor([1_000_000_000] * 20)
        result = scorer.score("TEST", prices=prices, investor=investor)
        expected = (result.volume_score + result.inst_score + result.high52_score) / 3
        assert result.momentum_score == pytest.approx(expected, abs=0.01)

    def test_momentum_score_in_range(self, scorer):
        """momentum_score는 0~100 범위."""
        prices = _make_prices([10000] * 30)
        result = scorer.score("TEST", prices=prices)
        assert 0.0 <= result.momentum_score <= 100.0
