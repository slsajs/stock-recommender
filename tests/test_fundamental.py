"""
test_fundamental.py
FundamentalScorer 단위 테스트.

섹터 상대비교 로직과 폴백(전체 평균) 동작을 검증한다.
"""
import pandas as pd
import pytest

from src.scoring.fundamental import FundamentalScorer


@pytest.fixture
def scorer() -> FundamentalScorer:
    return FundamentalScorer()


def _make_sector_fin(pers: list[float], pbrs=None, roes=None, debt_ratios=None) -> pd.DataFrame:
    n = len(pers)
    return pd.DataFrame(
        {
            "per": pers,
            "pbr": pbrs or [1.0] * n,
            "roe": roes or [10.0] * n,
            "debt_ratio": debt_ratios or [50.0] * n,
        }
    )


class TestPerScore:
    def test_lowest_per_in_sector_gives_high_score(self, scorer):
        """섹터 내 PER 최저 종목 → per_score ≥ 90."""
        sector_fin = _make_sector_fin([5.0, 10.0, 15.0, 20.0, 25.0, 30.0])
        all_fin = sector_fin.copy()
        fin = {"per": 5.0}  # 최저 PER
        result = scorer.score("TEST", financials=fin, sector_financials=sector_fin, all_financials=all_fin)
        assert result.per_score >= 90.0, f"per_score={result.per_score}"

    def test_highest_per_in_sector_gives_low_score(self, scorer):
        """섹터 내 PER 최고 종목 → per_score 낮음."""
        sector_fin = _make_sector_fin([5.0, 10.0, 15.0, 20.0, 25.0, 30.0])
        all_fin = sector_fin.copy()
        fin = {"per": 30.0}
        result = scorer.score("TEST", financials=fin, sector_financials=sector_fin, all_financials=all_fin)
        assert result.per_score <= 30.0, f"per_score={result.per_score}"

    def test_negative_per_returns_default(self, scorer):
        """PER 음수 → per_score = 30.0 (기본값)."""
        fin = {"per": -5.0}
        result = scorer.score("TEST", financials=fin)
        assert result.per_score == 30.0

    def test_none_per_returns_default(self, scorer):
        """PER None → per_score = 30.0."""
        fin = {}
        result = scorer.score("TEST", financials=fin)
        assert result.per_score == 30.0

    def test_small_sector_falls_back_to_all(self, scorer):
        """섹터 종목 5개 미만 → 전체 폴백 동작."""
        sector_fin = _make_sector_fin([10.0, 20.0])  # 2개 (< 5개)
        all_fin = _make_sector_fin([5.0, 10.0, 15.0, 20.0, 25.0, 30.0])
        fin = {"per": 5.0}
        result = scorer.score("TEST", financials=fin, sector_financials=sector_fin, all_financials=all_fin)
        # 전체 기준 최저 PER → 높은 점수
        assert result.per_score >= 80.0, f"per_score={result.per_score}"

    def test_sector_discount_bonus(self, scorer):
        """섹터 평균 대비 20% 이상 할인 → 보너스 +10."""
        sector_fin = _make_sector_fin([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
        all_fin = sector_fin.copy()
        sector_avg_per = 15.0
        fin = {"per": 10.0}  # 15 * 0.8 = 12 → 10 < 12 → 할인

        # bonus 없는 경우
        result_no_bonus = scorer.score(
            "TEST",
            financials=fin,
            sector_financials=sector_fin,
            all_financials=all_fin,
            sector_stats={},
        )
        # bonus 있는 경우
        result_bonus = scorer.score(
            "TEST",
            financials=fin,
            sector_financials=sector_fin,
            all_financials=all_fin,
            sector_stats={"avg_per": sector_avg_per},
        )
        assert result_bonus.per_score >= result_no_bonus.per_score


class TestRoeScore:
    def test_high_roe_gives_high_score(self, scorer):
        """섹터 내 ROE 최고 → roe_score 높음."""
        sector_fin = pd.DataFrame({"per": [10]*6, "pbr": [1]*6, "roe": [5.0, 8.0, 10.0, 12.0, 15.0, 20.0], "debt_ratio": [50]*6})
        fin = {"roe": 20.0}
        result = scorer.score("TEST", financials=fin, sector_financials=sector_fin, all_financials=sector_fin)
        assert result.roe_score >= 80.0

    def test_none_roe_returns_default(self, scorer):
        """ROE None → roe_score = 30.0."""
        result = scorer.score("TEST", financials={})
        assert result.roe_score == 30.0


class TestFundamentalScore:
    def test_fundamental_score_in_range(self, scorer):
        """fundamental_score는 0~100 범위."""
        sector_fin = _make_sector_fin([10.0, 15.0, 20.0, 25.0, 30.0, 35.0])
        fin = {"per": 10.0, "pbr": 1.0, "roe": 15.0, "debt_ratio": 50.0}
        result = scorer.score("TEST", financials=fin, sector_financials=sector_fin, all_financials=sector_fin)
        assert 0.0 <= result.fundamental_score <= 100.0

    def test_empty_financials_returns_neutral(self, scorer):
        """재무 데이터 없음 → fundamental_score = 50.0."""
        result = scorer.score("TEST", financials={})
        assert result.fundamental_score == pytest.approx(
            (30.0 + 30.0 + 30.0 + 50.0) / 4, abs=0.1
        )
