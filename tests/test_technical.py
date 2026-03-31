"""
test_technical.py
TechnicalScorer 단위 테스트.

가격 시계열을 직접 생성하여 RSI / MACD / 볼린저밴드 점수를 검증한다.
"""
import pandas as pd
import pytest

from src.scoring.technical import TechnicalScorer


def _make_prices(closes: list[float]) -> pd.DataFrame:
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1_000_000] * len(closes)
    return pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": volumes})


def _declining_prices(n: int = 50, start: float = 10_000, drop: float = 100) -> list[float]:
    """일관된 하락 → RSI 낮음 (과매도)."""
    return [max(1, start - drop * i) for i in range(n)]


def _rising_prices(n: int = 50, start: float = 5_000, rise: float = 100) -> list[float]:
    """일관된 상승 → RSI 높음 (과매수)."""
    return [start + rise * i for i in range(n)]


@pytest.fixture
def scorer() -> TechnicalScorer:
    return TechnicalScorer()


class TestRsiScore:
    def test_rsi_oversold_gives_high_score(self, scorer):
        """RSI ≤ 30 (과매도) → rsi_score ≥ 70."""
        prices = _make_prices(_declining_prices(50))
        result = scorer.score("TEST", prices=prices)
        assert result.rsi_score is not None
        assert result.rsi_score >= 70.0, f"rsi_score={result.rsi_score}"

    def test_rsi_overbought_gives_low_score(self, scorer):
        """RSI ≥ 70 (과매수) → rsi_score ≤ 30."""
        prices = _make_prices(_rising_prices(50))
        result = scorer.score("TEST", prices=prices)
        assert result.rsi_score is not None
        assert result.rsi_score <= 30.0, f"rsi_score={result.rsi_score}"

    def test_insufficient_data_returns_default(self, scorer):
        """5일 미만 데이터 → 전체 점수 50.0."""
        prices = _make_prices([10000, 10100, 10200, 9900])  # 4일
        result = scorer.score("TEST", prices=prices)
        assert result.rsi_score == 50.0
        assert result.macd_score == 50.0
        assert result.bb_score == 50.0
        assert result.technical_score == 50.0

    def test_empty_prices_returns_default(self, scorer):
        """빈 DataFrame → 전체 점수 50.0."""
        result = scorer.score("TEST", prices=pd.DataFrame())
        assert result.technical_score == 50.0

    def test_rsi_score_in_range(self, scorer):
        """rsi_score는 항상 0~100 범위."""
        for prices_list in [_declining_prices(), _rising_prices()]:
            result = scorer.score("TEST", prices=_make_prices(prices_list))
            assert 0.0 <= result.rsi_score <= 100.0


class TestMacdScore:
    def test_macd_score_in_range(self, scorer):
        """macd_score는 항상 0~100 범위."""
        prices = _make_prices(_rising_prices(60))
        result = scorer.score("TEST", prices=prices)
        assert 0.0 <= result.macd_score <= 100.0

    def test_insufficient_data_for_macd(self, scorer):
        """MACD 계산에 필요한 데이터 부족 시 기본값 반환."""
        prices = _make_prices(_rising_prices(10))  # MACD 최소 35일 필요
        result = scorer.score("TEST", prices=prices)
        assert result.macd_score == 50.0


class TestBbScore:
    def test_bb_score_in_range(self, scorer):
        """bb_score는 항상 0~100 범위."""
        prices = _make_prices(_declining_prices(30))
        result = scorer.score("TEST", prices=prices)
        assert 0.0 <= result.bb_score <= 100.0

    def test_price_near_lower_band_gives_high_score(self, scorer):
        """볼린저 하단 근접(과매도) → bb_score 높음."""
        # 급락 후 하단 밴드 근처에 위치
        prices = _make_prices(_declining_prices(30))
        result = scorer.score("TEST", prices=prices)
        assert result.bb_score >= 50.0


class TestTechnicalScore:
    def test_technical_score_is_average_of_three(self, scorer):
        """technical_score = (rsi + macd + bb) / 3 의 근사값."""
        prices = _make_prices(_declining_prices(50))
        result = scorer.score("TEST", prices=prices)
        expected = (result.rsi_score + result.macd_score + result.bb_score) / 3
        assert result.technical_score == pytest.approx(expected, abs=0.01)
