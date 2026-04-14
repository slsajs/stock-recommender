"""
test_momentum.py
MomentumScorer 단위 테스트.

개선 B 변경 반영:
  - MOMENTUM_WEIGHTS: volume(35%) + inst(35%) + price_momentum(30%)
  - 60일 수익률 +30% 초과 시 과열 페널티 적용 (최대 -15점)
"""
import pandas as pd
import pytest

from src.scoring.momentum import (
    MomentumScorer,
    MOMENTUM_WEIGHTS,
    OVEREXTENSION_THRESHOLD,
    OVEREXTENSION_PENALTY,
)


@pytest.fixture
def scorer() -> MomentumScorer:
    return MomentumScorer()


def _make_prices(
    closes: list[float],
    volumes: list[int] | None = None,
) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "close": closes,
            "high": [c * 1.01 for c in closes],
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


class TestPriceMomentumScore:
    def test_positive_return_gives_high_score(self, scorer):
        """60일 수익률 +20% → price_momentum_score > 80."""
        # 61개 데이터: 처음 10000, 이후 12000 (20% 상승)
        closes = [10000.0] + [12000.0] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert result.price_momentum_score > 80.0

    def test_negative_return_gives_low_score(self, scorer):
        """60일 수익률 -20% → price_momentum_score < 20."""
        closes = [10000.0] + [8000.0] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert result.price_momentum_score < 20.0

    def test_zero_return_gives_50(self, scorer):
        """60일 수익률 0% → price_momentum_score ≈ 50."""
        closes = [10000.0] * 61
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert result.price_momentum_score == pytest.approx(50.0, abs=1.0)

    def test_insufficient_data_returns_default(self, scorer):
        """60일 미만 데이터 → price_momentum_score = 50.0."""
        closes = [10000.0] * 30   # 30개 (61 미만)
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert result.price_momentum_score == 50.0

    def test_empty_prices_returns_default(self, scorer):
        """가격 데이터 없음 → price_momentum_score = 50.0."""
        result = scorer.score("TEST", prices=pd.DataFrame())
        assert result.price_momentum_score == 50.0

    def test_score_in_range(self, scorer):
        """price_momentum_score는 0~100 범위."""
        # 극단적 상승 (+100%)
        closes = [5000.0] + [10000.0] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert 0.0 <= result.price_momentum_score <= 100.0


class TestMomentumScore:
    def test_momentum_score_uses_weighted_average(self, scorer):
        """momentum_score = volume(35%) + inst(35%) + price_momentum(30%) 가중 평균."""
        closes = [10000.0] * 61  # 61개, 수익률 0%
        prices = _make_prices(closes, volumes=[1_000_000] * 61)
        investor = _make_investor([1_000_000_000] * 20)
        result = scorer.score("TEST", prices=prices, investor=investor)
        expected = (
            result.volume_score * MOMENTUM_WEIGHTS["volume"]
            + result.inst_score * MOMENTUM_WEIGHTS["inst"]
            + result.price_momentum_score * MOMENTUM_WEIGHTS["price_momentum"]
        )
        assert result.momentum_score == pytest.approx(expected, abs=0.01)

    def test_momentum_score_in_range(self, scorer):
        """momentum_score는 0~100 범위."""
        closes = [10000.0] * 30
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)
        assert 0.0 <= result.momentum_score <= 100.0

    def test_weights_sum_to_one(self):
        """MOMENTUM_WEIGHTS 합계는 1.0 (개선 B-1)."""
        total = sum(MOMENTUM_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=0.001)

    def test_volume_weight_is_35(self):
        """거래량 가중치 0.35 (개선 B-1: 0.50 → 0.35)."""
        assert MOMENTUM_WEIGHTS["volume"] == pytest.approx(0.35)

    def test_inst_weight_is_35(self):
        """기관 순매수 가중치 0.35 (개선 B-1: 0.20 → 0.35)."""
        assert MOMENTUM_WEIGHTS["inst"] == pytest.approx(0.35)


class TestOverextensionPenalty:
    """60일 과열 구간 페널티 테스트 (개선 B-2)."""

    def test_no_penalty_below_threshold(self, scorer):
        """60일 수익률 +25% → OVEREXTENSION_THRESHOLD(30%) 미만 → 페널티 없음."""
        past_close = 10000.0
        current_close = past_close * 1.25   # +25%
        closes = [past_close] + [current_close] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)

        # 페널티 없는 경우의 기대 점수 (sigmoid: 25% → ~92점)
        import numpy as np
        expected_no_penalty = 100.0 / (1.0 + np.exp(-0.25 / 0.10))
        # 실제 점수와 페널티 없는 점수가 같아야 함
        assert result.price_momentum_score == pytest.approx(expected_no_penalty, abs=1.0)

    def test_penalty_applied_above_threshold(self, scorer):
        """60일 수익률 +35% → 페널티 적용 → score < 페널티 없는 경우."""
        past_close = 10000.0
        current_close = past_close * 1.35   # +35%
        closes = [past_close] + [current_close] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)

        import numpy as np
        # 페널티 없는 경우
        score_no_penalty = 100.0 / (1.0 + np.exp(-0.35 / 0.10))
        # 페널티 = (0.35 - 0.30) * 50 = 2.5점
        expected = max(0.0, score_no_penalty - 2.5)
        assert result.price_momentum_score == pytest.approx(expected, abs=1.0)
        assert result.price_momentum_score < score_no_penalty

    def test_max_penalty_capped_at_15(self, scorer):
        """60일 수익률 +80% → 최대 페널티 15점 적용."""
        past_close = 10000.0
        current_close = past_close * 1.80   # +80%
        closes = [past_close] + [current_close] * 60
        prices = _make_prices(closes)
        result = scorer.score("TEST", prices=prices)

        import numpy as np
        # 페널티 없는 경우
        score_no_penalty = 100.0 / (1.0 + np.exp(-0.80 / 0.10))
        # 페널티 = min(15, (0.80 - 0.30) * 50) = min(15, 25) = 15
        expected = max(0.0, score_no_penalty - OVEREXTENSION_PENALTY)
        assert result.price_momentum_score == pytest.approx(expected, abs=0.5)

    def test_overextension_threshold_value(self):
        """OVEREXTENSION_THRESHOLD = 0.30."""
        assert OVEREXTENSION_THRESHOLD == pytest.approx(0.30)

    def test_overextension_penalty_value(self):
        """OVEREXTENSION_PENALTY = 15.0."""
        assert OVEREXTENSION_PENALTY == pytest.approx(15.0)
