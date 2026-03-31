"""
test_filters.py
should_exclude 필터 함수 단위 테스트.

실제 DB 연결 없이 unittest.mock으로 StockRepository를 모킹한다.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.scoring.filters import should_exclude


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


def _make_db(
    stock=None,
    prices=None,
    disclosures=None,
) -> MagicMock:
    db = MagicMock()
    db.get_stock.return_value = stock if stock is not None else _make_active_stock()
    db.get_prices.return_value = prices if prices is not None else _make_prices(60)
    db.get_recent_disclosures.return_value = disclosures if disclosures is not None else []
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
