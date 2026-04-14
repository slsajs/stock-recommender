"""
test_filters.py
should_exclude 필터 함수 단위 테스트.

실제 DB 연결 없이 unittest.mock으로 StockRepository를 모킹한다.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.scoring.filters import (
    RSI_OVERBOUGHT_THRESHOLD,
    _calc_rsi,
    should_exclude,
)


def _make_active_stock() -> dict:
    return {"code": "005930", "name": "삼성전자", "is_active": True}


def _make_prices(n: int, last_volumes: list[int] | None = None) -> pd.DataFrame:
    """n일치 가격 데이터. last_volumes로 마지막 5일 거래량을 덮어쓴다."""
    volumes = [1_000_000] * n
    if last_volumes:
        for i, v in enumerate(reversed(last_volumes)):
            volumes[-(i + 1)] = v
    return pd.DataFrame(
        {
            "date": [f"2024-{i:04d}" for i in range(n)],
            "close": [10000] * n,
            "high": [10100] * n,
            "low": [9900] * n,
            "volume": volumes,
        }
    )


def _make_prices_with_rsi(n: int, rsi_value: float) -> pd.DataFrame:
    """
    지정된 RSI 값을 근사하는 가격 데이터 생성.

    RSI = 100 * (avg_gain / (avg_gain + avg_loss)).
    rsi_value ≥ 75: 최근 14일 모두 상승 (RSI ≈ 100).
    rsi_value ≤ 30: 최근 14일 모두 하락 (RSI ≈ 0).
    """
    if rsi_value >= 75:
        # 15일 연속 상승 (최소 15일 필요)
        closes = [10000.0 + i * 100 for i in range(max(n, 30))]
    else:
        # 15일 연속 하락
        closes = [10000.0 - i * 100 for i in range(max(n, 30))]
    closes = [max(c, 100.0) for c in closes]  # 음수 방지
    return _make_prices(len(closes))._update_close(closes)


def _make_prices_high_rsi(n: int = 30) -> pd.DataFrame:
    """RSI ≈ 100에 가까운 가격 데이터 (연속 상승)."""
    closes = [10000.0 + i * 200 for i in range(n)]
    return pd.DataFrame({
        "date": [f"2024-{i:04d}" for i in range(n)],
        "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "volume": [1_000_000] * n,
    })


def _make_prices_low_rsi(n: int = 30) -> pd.DataFrame:
    """RSI ≈ 0에 가까운 가격 데이터 (연속 하락)."""
    closes = [max(10000.0 - i * 200, 100.0) for i in range(n)]
    return pd.DataFrame({
        "date": [f"2024-{i:04d}" for i in range(n)],
        "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "volume": [1_000_000] * n,
    })


def _make_db(
    stock=None,
    prices=None,
    disclosures=None,
    rsi_prices=None,
) -> MagicMock:
    """
    rsi_prices: should_exclude의 두 번째 get_prices 호출(lookback=30)에서 반환할 데이터.
                None이면 기본 60일 가격과 동일하게 반환.
    """
    db = MagicMock()
    db.get_stock.return_value = stock if stock is not None else _make_active_stock()
    base_prices = prices if prices is not None else _make_prices(60)
    db.get_recent_disclosures.return_value = disclosures if disclosures is not None else []

    # get_prices는 lookback 인자에 따라 다른 데이터를 반환해야 함
    # lookback=60 → 기본 필터용, lookback=30 → RSI 계산용
    if rsi_prices is not None:
        def _get_prices(code, lookback=60, as_of_date=None):
            if lookback <= 30:
                return rsi_prices
            return base_prices
        db.get_prices.side_effect = _get_prices
    else:
        db.get_prices.return_value = base_prices
    return db


class TestInactiveStock:
    def test_inactive_stock_is_excluded(self):
        """is_active=False → 제외."""
        db = _make_db(stock={"is_active": False})
        excluded, reason = should_exclude("005930", db)
        assert excluded is True
        assert "비활성" in reason

    def test_missing_stock_is_excluded(self):
        """get_stock이 None 반환 → 제외."""
        db = _make_db(stock=None)
        db.get_stock.return_value = None
        excluded, reason = should_exclude("999999", db)
        assert excluded is True


class TestTradingDays:
    def test_less_than_60_days_is_excluded(self):
        """상장 60거래일 미만 → 제외."""
        db = _make_db(prices=_make_prices(59))
        excluded, reason = should_exclude("005930", db)
        assert excluded is True
        assert "거래일 부족" in reason

    def test_exactly_60_days_is_not_excluded(self):
        """정확히 60거래일 → 통과."""
        db = _make_db(prices=_make_prices(60))
        excluded, _ = should_exclude("005930", db)
        assert excluded is False

    def test_more_than_60_days_is_not_excluded(self):
        """60거래일 초과 → 통과."""
        db = _make_db(prices=_make_prices(100))
        excluded, _ = should_exclude("005930", db)
        assert excluded is False


class TestZeroVolume:
    def test_zero_volume_in_recent_5_days_is_excluded(self):
        """최근 5거래일 내 거래량 0 → 제외."""
        db = _make_db(prices=_make_prices(60, last_volumes=[1000000, 0, 1000000, 1000000, 1000000]))
        excluded, reason = should_exclude("005930", db)
        assert excluded is True
        assert "거래량 0" in reason

    def test_all_zero_volume_recent_days_is_excluded(self):
        """최근 5거래일 전부 거래량 0 → 제외."""
        db = _make_db(prices=_make_prices(60, last_volumes=[0, 0, 0, 0, 0]))
        excluded, _ = should_exclude("005930", db)
        assert excluded is True

    def test_normal_volume_is_not_excluded(self):
        """정상 거래량 → 통과."""
        db = _make_db(prices=_make_prices(60))
        excluded, _ = should_exclude("005930", db)
        assert excluded is False


class TestDangerousDisclosure:
    @pytest.mark.parametrize(
        "category",
        ["관리종목지정", "상장폐지", "불성실공시", "회생절차", "거래정지"],
    )
    def test_dangerous_disclosure_is_excluded(self, category):
        """위험 공시 카테고리 → 제외."""
        discs = [{"category": category, "title": "테스트", "disclosed_at": "2024-01-01"}]
        db = _make_db(disclosures=discs)
        excluded, reason = should_exclude("005930", db)
        assert excluded is True
        assert category in reason

    def test_normal_disclosure_is_not_excluded(self):
        """일반공시 → 통과."""
        discs = [{"category": "일반공시", "title": "분기보고서", "disclosed_at": "2024-01-01"}]
        db = _make_db(disclosures=discs)
        excluded, _ = should_exclude("005930", db)
        assert excluded is False

    def test_no_disclosure_is_not_excluded(self):
        """공시 없음 → 통과."""
        db = _make_db(disclosures=[])
        excluded, _ = should_exclude("005930", db)
        assert excluded is False


class TestPassingStock:
    def test_normal_stock_passes_all_filters(self):
        """정상 종목 → 필터 전부 통과."""
        db = _make_db(
            stock=_make_active_stock(),
            prices=_make_prices(120),
            disclosures=[],
        )
        excluded, reason = should_exclude("005930", db)
        assert excluded is False
        assert reason == ""


class TestRsiOverboughtFilter:
    """개선 D-1: BULL 구간 RSI 과매수 필터 테스트."""

    def test_high_rsi_excluded_in_early_bull(self):
        """EARLY_BULL + RSI 과매수 → 제외."""
        rsi_prices = _make_prices_high_rsi(30)
        db = _make_db(prices=_make_prices(60), rsi_prices=rsi_prices)
        excluded, reason = should_exclude("005930", db, regime="EARLY_BULL")
        assert excluded is True
        assert "RSI 과매수" in reason

    def test_high_rsi_excluded_in_late_bull(self):
        """LATE_BULL + RSI 과매수 → 제외."""
        rsi_prices = _make_prices_high_rsi(30)
        db = _make_db(prices=_make_prices(60), rsi_prices=rsi_prices)
        excluded, reason = should_exclude("005930", db, regime="LATE_BULL")
        assert excluded is True
        assert "RSI 과매수" in reason

    def test_high_rsi_not_excluded_in_bear(self):
        """BEAR + RSI 과매수 → 통과 (BEAR에서는 RSI 필터 없음)."""
        rsi_prices = _make_prices_high_rsi(30)
        db = _make_db(prices=_make_prices(60), rsi_prices=rsi_prices)
        excluded, _ = should_exclude("005930", db, regime="BEAR")
        assert excluded is False

    def test_no_regime_no_rsi_filter(self):
        """regime=None → RSI 필터 미적용 (하위 호환)."""
        rsi_prices = _make_prices_high_rsi(30)
        db = _make_db(prices=_make_prices(60), rsi_prices=rsi_prices)
        excluded, _ = should_exclude("005930", db, regime=None)
        assert excluded is False

    def test_low_rsi_passes_in_bull(self):
        """EARLY_BULL + RSI 낮음(하락) → 통과."""
        rsi_prices = _make_prices_low_rsi(30)
        db = _make_db(prices=_make_prices(60), rsi_prices=rsi_prices)
        excluded, _ = should_exclude("005930", db, regime="EARLY_BULL")
        assert excluded is False

    def test_rsi_insufficient_data_passes(self):
        """RSI 계산 데이터 부족 → 통과 (안전한 기본값)."""
        # 14일 미만 데이터 → _calc_rsi 반환 None → 필터 통과
        short_prices = _make_prices(10)  # 10행만 있는 가격
        db = _make_db(prices=_make_prices(60), rsi_prices=short_prices)
        excluded, _ = should_exclude("005930", db, regime="EARLY_BULL")
        assert excluded is False


class TestCalcRsi:
    """_calc_rsi 헬퍼 함수 단위 테스트."""

    def test_all_rising_gives_high_rsi(self):
        """연속 상승 → RSI 높음 (≥ 75)."""
        prices = _make_prices_high_rsi(30)
        rsi = _calc_rsi(prices)
        assert rsi is not None
        assert rsi >= RSI_OVERBOUGHT_THRESHOLD

    def test_all_falling_gives_low_rsi(self):
        """연속 하락 → RSI 낮음 (< 50)."""
        prices = _make_prices_low_rsi(30)
        rsi = _calc_rsi(prices)
        assert rsi is not None
        assert rsi < 50.0

    def test_insufficient_data_returns_none(self):
        """14일 미만 데이터 → None 반환."""
        prices = _make_prices(10)
        rsi = _calc_rsi(prices)
        assert rsi is None

    def test_empty_dataframe_returns_none(self):
        """빈 DataFrame → None 반환."""
        rsi = _calc_rsi(pd.DataFrame())
        assert rsi is None

    def test_rsi_range(self):
        """RSI는 0~100 범위."""
        prices = _make_prices_high_rsi(30)
        rsi = _calc_rsi(prices)
        assert rsi is not None
        assert 0.0 <= rsi <= 100.0
