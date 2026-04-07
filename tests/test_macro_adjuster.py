"""
test_macro_adjuster.py
STEP A: 금리 트렌드 판단 및 FundamentalScorer 내부 가중치 조절 단위 테스트.
STEP B: 환율 변동률 계산 및 섹터별 점수 보정 단위 테스트.

테스트 케이스:
  - 기준금리 3개월간 0.5%p 상승 → "RISING"
  - 기준금리 3개월간 0.5%p 하락 → "FALLING"
  - 기준금리 변동 없음 (0.1%p)  → "STABLE"
  - 정확히 경계값 (0.25%p 상승) → "RISING"
  - 데이터 1건                  → "STABLE" (폴백)
  - 데이터 0건                  → "STABLE" (폴백)
  - RISING  → PER 가중치 0.40, ROE 가중치 0.20
  - FALLING → PER 가중치 0.20, ROE 가중치 0.40
  - STABLE  → 기본 가중치 (per=0.30, pbr=0.25, roe=0.30, debt=0.15)
  - 가중치 합계가 항상 1.0
  - FundamentalScorer가 주입받은 가중치로 점수를 다르게 계산
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.scoring.macro_adjuster import (
    DEFAULT_FUNDAMENTAL_WEIGHTS,
    EXPORT_SECTORS,
    IMPORT_SECTORS,
    currency_adjustment,
    determine_rate_trend,
    get_fundamental_weights,
    get_usd_krw_change,
)
from src.scoring.fundamental import FundamentalScorer


# ------------------------------------------------------------------
# 픽스처: DB 목업
# ------------------------------------------------------------------

def _make_db(rates: list[float]) -> MagicMock:
    """rates 리스트로 BASE_RATE DataFrame을 반환하는 DB 목업."""
    db = MagicMock()
    if rates:
        df = pd.DataFrame({"date": range(len(rates)), "value": rates})
    else:
        df = pd.DataFrame(columns=["date", "value"])
    db.get_macro_indicator.return_value = df
    return db


# ------------------------------------------------------------------
# determine_rate_trend 테스트
# ------------------------------------------------------------------

class TestDetermineRateTrend:

    def test_rising_when_rate_up_05(self):
        """0.5%p 상승 → RISING"""
        db = _make_db([3.00, 3.25, 3.50])
        assert determine_rate_trend(db) == "RISING"

    def test_falling_when_rate_down_05(self):
        """0.5%p 하락 → FALLING"""
        db = _make_db([3.50, 3.25, 3.00])
        assert determine_rate_trend(db) == "FALLING"

    def test_stable_when_no_change(self):
        """변동 없음 → STABLE"""
        db = _make_db([3.50, 3.50, 3.50])
        assert determine_rate_trend(db) == "STABLE"

    def test_stable_when_small_change(self):
        """0.1%p 변동은 임계치 미만 → STABLE"""
        db = _make_db([3.40, 3.50])
        assert determine_rate_trend(db) == "STABLE"

    def test_rising_at_boundary(self):
        """정확히 0.25%p 상승 → RISING (경계값 포함)"""
        db = _make_db([3.00, 3.25])
        assert determine_rate_trend(db) == "RISING"

    def test_falling_at_boundary(self):
        """정확히 0.25%p 하락 → FALLING (경계값 포함)"""
        db = _make_db([3.25, 3.00])
        assert determine_rate_trend(db) == "FALLING"

    def test_stable_when_one_record(self):
        """데이터 1건 → STABLE (비교 불가)"""
        db = _make_db([3.50])
        assert determine_rate_trend(db) == "STABLE"

    def test_stable_when_empty(self):
        """데이터 0건 → STABLE"""
        db = _make_db([])
        assert determine_rate_trend(db) == "STABLE"


# ------------------------------------------------------------------
# get_fundamental_weights 테스트
# ------------------------------------------------------------------

class TestGetFundamentalWeights:

    def test_rising_per_weight(self):
        """RISING → PER 가중치 0.40"""
        w = get_fundamental_weights("RISING")
        assert w["per"] == pytest.approx(0.40)

    def test_rising_roe_weight(self):
        """RISING → ROE 가중치 0.20"""
        w = get_fundamental_weights("RISING")
        assert w["roe"] == pytest.approx(0.20)

    def test_falling_per_weight(self):
        """FALLING → PER 가중치 0.20"""
        w = get_fundamental_weights("FALLING")
        assert w["per"] == pytest.approx(0.20)

    def test_falling_roe_weight(self):
        """FALLING → ROE 가중치 0.40"""
        w = get_fundamental_weights("FALLING")
        assert w["roe"] == pytest.approx(0.40)

    def test_stable_default_weights(self):
        """STABLE → 기본 가중치 그대로"""
        w = get_fundamental_weights("STABLE")
        assert w == DEFAULT_FUNDAMENTAL_WEIGHTS

    def test_weights_sum_to_one_rising(self):
        """RISING 가중치 합 = 1.0"""
        w = get_fundamental_weights("RISING")
        assert sum(w.values()) == pytest.approx(1.0)

    def test_weights_sum_to_one_falling(self):
        """FALLING 가중치 합 = 1.0"""
        w = get_fundamental_weights("FALLING")
        assert sum(w.values()) == pytest.approx(1.0)

    def test_weights_sum_to_one_stable(self):
        """STABLE 가중치 합 = 1.0"""
        w = get_fundamental_weights("STABLE")
        assert sum(w.values()) == pytest.approx(1.0)

    def test_unknown_trend_returns_default(self):
        """알 수 없는 트렌드 값 → STABLE과 동일한 기본 가중치"""
        w = get_fundamental_weights("UNKNOWN_VALUE")
        assert w == DEFAULT_FUNDAMENTAL_WEIGHTS


# ------------------------------------------------------------------
# FundamentalScorer — fund_internal_weights 주입 테스트
# ------------------------------------------------------------------

class TestFundamentalScorerWithWeights:
    """
    FundamentalScorer가 fund_internal_weights 주입에 따라
    동일 데이터에서 다른 fundamental_score를 반환하는지 검증.
    """

    @pytest.fixture
    def sample_financials(self) -> dict:
        """PER·PBR·ROE·부채비율이 모두 유효한 재무 데이터."""
        return {
            "per": 10.0,
            "pbr": 1.0,
            "roe": 15.0,
            "debt_ratio": 50.0,
        }

    @pytest.fixture
    def sector_fin(self) -> pd.DataFrame:
        """섹터 내 10개 종목 재무 데이터 (백분위 계산에 충분한 수)."""
        return pd.DataFrame(
            {
                "per": [5, 8, 10, 12, 15, 20, 25, 30, 35, 40],
                "pbr": [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
                "roe": [5, 8, 10, 12, 15, 18, 20, 22, 25, 30],
                "debt_ratio": [20, 30, 40, 50, 60, 70, 80, 90, 100, 120],
            }
        )

    def test_rising_weights_emphasize_per(self, sample_financials, sector_fin):
        """
        RISING 가중치(PER 40%)는 STABLE 가중치(PER 30%)보다
        PER 점수를 더 강조한다.
        per_score가 높은 케이스: PER=10으로 섹터 중간 이하 → 70점대 예상.
        RISING 가중치 적용 시 fundamental_score가 변해야 한다.
        """
        scorer = FundamentalScorer()
        stable_result = scorer.score(
            "TEST",
            financials=sample_financials,
            sector_financials=sector_fin,
            all_financials=sector_fin,
            fund_internal_weights=get_fundamental_weights("STABLE"),
        )
        rising_result = scorer.score(
            "TEST",
            financials=sample_financials,
            sector_financials=sector_fin,
            all_financials=sector_fin,
            fund_internal_weights=get_fundamental_weights("RISING"),
        )
        # STABLE과 RISING은 가중치가 다르므로 점수가 달라야 한다
        assert stable_result.fundamental_score != rising_result.fundamental_score

    def test_default_weights_when_none(self, sample_financials, sector_fin):
        """
        fund_internal_weights=None → DEFAULT_FUNDAMENTAL_WEIGHTS와 동일한 결과.
        """
        scorer = FundamentalScorer()
        result_none = scorer.score(
            "TEST",
            financials=sample_financials,
            sector_financials=sector_fin,
            all_financials=sector_fin,
            fund_internal_weights=None,
        )
        result_default = scorer.score(
            "TEST",
            financials=sample_financials,
            sector_financials=sector_fin,
            all_financials=sector_fin,
            fund_internal_weights=dict(DEFAULT_FUNDAMENTAL_WEIGHTS),
        )
        assert result_none.fundamental_score == pytest.approx(result_default.fundamental_score)

    def test_score_range(self, sample_financials, sector_fin):
        """fundamental_score는 0~100 범위 이내."""
        scorer = FundamentalScorer()
        for trend in ["RISING", "FALLING", "STABLE"]:
            result = scorer.score(
                "TEST",
                financials=sample_financials,
                sector_financials=sector_fin,
                all_financials=sector_fin,
                fund_internal_weights=get_fundamental_weights(trend),
            )
            assert 0.0 <= result.fundamental_score <= 100.0, (
                f"trend={trend} → fundamental_score={result.fundamental_score} 범위 초과"
            )

    def test_partial_none_financials(self):
        """
        일부 지표가 None인 경우에도 가중 평균을 올바르게 처리.
        per, pbr만 유효 → roe·debt 제외한 가중치 재정규화.
        """
        scorer = FundamentalScorer()
        fin = {"per": 10.0, "pbr": 1.0, "roe": None, "debt_ratio": None}
        sector_fin = pd.DataFrame(
            {
                "per": [5, 8, 10, 12, 15, 20, 25, 30, 35, 40],
                "pbr": [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
            }
        )
        result = scorer.score(
            "TEST",
            financials=fin,
            sector_financials=sector_fin,
            all_financials=sector_fin,
            fund_internal_weights=get_fundamental_weights("RISING"),
        )
        # 점수가 반환되어야 하고 0~100 범위
        assert result.fundamental_score is not None
        assert 0.0 <= result.fundamental_score <= 100.0


# ------------------------------------------------------------------
# STEP B: get_usd_krw_change 테스트
# ------------------------------------------------------------------

def _make_usd_db(rates: list[float]) -> MagicMock:
    """USD_KRW DataFrame을 반환하는 DB 목업."""
    db = MagicMock()
    if rates:
        df = pd.DataFrame({"date": range(len(rates)), "value": rates})
    else:
        df = pd.DataFrame(columns=["date", "value"])
    db.get_macro_indicator.return_value = df
    return db


class TestGetUsdKrwChange:

    def test_rising_exchange_rate(self):
        """환율 상승 (원화 약세) → 양수 반환."""
        db = _make_usd_db([1200.0, 1236.0])  # +3%
        result = get_usd_krw_change(db)
        assert result == pytest.approx(3.0, abs=0.01)

    def test_falling_exchange_rate(self):
        """환율 하락 (원화 강세) → 음수 반환."""
        db = _make_usd_db([1200.0, 1164.0])  # -3%
        result = get_usd_krw_change(db)
        assert result == pytest.approx(-3.0, abs=0.01)

    def test_no_change(self):
        """환율 변동 없음 → 0.0."""
        db = _make_usd_db([1300.0, 1300.0])
        assert get_usd_krw_change(db) == pytest.approx(0.0)

    def test_empty_data_returns_zero(self):
        """데이터 없음 → 0.0 (안전 폴백)."""
        db = _make_usd_db([])
        assert get_usd_krw_change(db) == 0.0

    def test_single_record_returns_zero(self):
        """데이터 1건 → 비교 불가 → 0.0."""
        db = _make_usd_db([1300.0])
        assert get_usd_krw_change(db) == 0.0


# ------------------------------------------------------------------
# STEP B: currency_adjustment 테스트
# ------------------------------------------------------------------

class TestCurrencyAdjustment:

    def test_export_sector_rate_up(self):
        """수출 섹터 + 환율 3% 상승 → +3.0."""
        for sector in EXPORT_SECTORS:
            result = currency_adjustment(sector, 3.0)
            assert result == pytest.approx(3.0), f"섹터={sector}"

    def test_import_sector_rate_up(self):
        """수입 의존 섹터 + 환율 3% 상승 → -3.0."""
        for sector in IMPORT_SECTORS:
            result = currency_adjustment(sector, 3.0)
            assert result == pytest.approx(-3.0), f"섹터={sector}"

    def test_export_sector_rate_down(self):
        """수출 섹터 + 환율 하락 → 음수 보정."""
        result = currency_adjustment(EXPORT_SECTORS[0], -3.0)
        assert result == pytest.approx(-3.0)

    def test_import_sector_rate_down(self):
        """수입 섹터 + 환율 하락 → 양수 보정."""
        result = currency_adjustment(IMPORT_SECTORS[0], -3.0)
        assert result == pytest.approx(3.0)

    def test_other_sector_returns_zero(self):
        """기타 섹터 → 보정 없음 (0.0)."""
        for sector in ['유통', '제약', '금융', '건설', '식품']:
            assert currency_adjustment(sector, 5.0) == 0.0, f"섹터={sector}"

    def test_none_sector_returns_zero(self):
        """섹터 None (미분류) → 0.0."""
        assert currency_adjustment(None, 3.0) == 0.0

    def test_clipping_max_positive(self):
        """환율 10% 급등 → 최대 +5.0으로 클리핑."""
        result = currency_adjustment(EXPORT_SECTORS[0], 10.0)
        assert result == pytest.approx(5.0)

    def test_clipping_max_negative(self):
        """수입 섹터 + 환율 10% 급등 → 최소 -5.0으로 클리핑."""
        result = currency_adjustment(IMPORT_SECTORS[0], 10.0)
        assert result == pytest.approx(-5.0)

    def test_zero_change_always_zero(self):
        """환율 변동 없음 → 어떤 섹터든 0.0."""
        for sector in EXPORT_SECTORS + IMPORT_SECTORS:
            assert currency_adjustment(sector, 0.0) == 0.0


# ------------------------------------------------------------------
# STEP B: aggregator — adjusted_total_score 반영 테스트
# ------------------------------------------------------------------

class TestAggregatorWithMacroAdjustment:
    """aggregator.aggregate()가 macro_adjustment를 adjusted_total_score에 반영하는지 확인."""

    def test_adjusted_score_includes_macro_adjustment(self):
        """total_score + macro_adjustment = adjusted_total_score."""
        from src.scoring.aggregator import ScoreAggregator
        from src.scoring.base import ScoreResult

        agg = ScoreAggregator()
        weights = {"technical": 0.45, "fundamental": 0.40, "momentum": 0.15}
        result = ScoreResult(
            code="TEST",
            technical_score=60.0,
            fundamental_score=70.0,
            momentum_score=50.0,
            macro_adjustment=3.0,  # 수출 섹터 + 환율 상승 가정
        )
        agg.aggregate(result, weights)

        expected_total = 60.0 * 0.45 + 70.0 * 0.40 + 50.0 * 0.15
        assert result.total_score == pytest.approx(expected_total, abs=0.01)
        assert result.adjusted_total_score == pytest.approx(expected_total + 3.0, abs=0.01)

    def test_no_adjustment_keeps_scores_equal(self):
        """보정값 0이면 total_score == adjusted_total_score."""
        from src.scoring.aggregator import ScoreAggregator
        from src.scoring.base import ScoreResult

        agg = ScoreAggregator()
        weights = {"technical": 0.20, "fundamental": 0.40, "momentum": 0.40}
        result = ScoreResult(code="TEST", technical_score=70.0, fundamental_score=70.0, momentum_score=70.0)
        agg.aggregate(result, weights)

        assert result.total_score == pytest.approx(result.adjusted_total_score, abs=0.01)

    def test_top_n_sorted_by_adjusted_score(self):
        """get_top_n은 adjusted_total_score 기준으로 정렬한다."""
        from src.scoring.aggregator import ScoreAggregator
        from src.scoring.base import ScoreResult

        agg = ScoreAggregator()
        weights = {"technical": 0.20, "fundamental": 0.40, "momentum": 0.40}

        # A: total=70, macro=+5 → adjusted=75
        # B: total=75, macro=0  → adjusted=75 ... total 기준으론 B가 높지만
        # C: total=60, macro=+20 → adjusted=80 → 1등이어야 함
        results = []
        for code, tech, macro in [("A", 70.0, 5.0), ("B", 75.0, 0.0), ("C", 60.0, 20.0)]:
            r = ScoreResult(code=code, technical_score=tech, fundamental_score=tech, momentum_score=tech, macro_adjustment=macro)
            agg.aggregate(r, weights)
            results.append(r)

        top = agg.get_top_n(results, n=3)
        assert top[0].code == "C", f"1위는 C여야 함 (adjusted=80), 실제={top[0].code}"