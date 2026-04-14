"""
test_aggregator.py
ScoreAggregator 단위 테스트.
"""
import pytest

from src.scoring.aggregator import (
    FAILURE_THRESHOLD,
    MAX_SAME_SECTOR,
    MIN_SCORE_THRESHOLD,
    TOP_N,
    ScoreAggregator,
)
from src.scoring.base import ScoreResult
from src.scoring.market_regime import MarketRegime


def _make_regime(regime: str = "LATE_BULL") -> MarketRegime:
    weights_map = {
        "EARLY_BULL": {"technical": 0.00, "fundamental": 0.40, "momentum": 0.60},
        "LATE_BULL":  {"technical": 0.00, "fundamental": 0.50, "momentum": 0.50},
        "BEAR":       {"technical": 0.00, "fundamental": 0.55, "momentum": 0.45},
    }
    weights = weights_map.get(regime, weights_map["LATE_BULL"])
    return MarketRegime(
        regime=regime,
        weights=weights,
        ma20=2500.0,
        ma60=2400.0,
    )


def _make_result(
    code: str,
    technical: float = 50.0,
    fundamental: float = 50.0,
    momentum: float = 50.0,
) -> ScoreResult:
    r = ScoreResult(code=code)
    r.technical_score = technical
    r.fundamental_score = fundamental
    r.momentum_score = momentum
    return r


@pytest.fixture
def aggregator() -> ScoreAggregator:
    return ScoreAggregator()


class TestAggregate:
    def test_early_bull_weighting(self, aggregator):
        """EARLY_BULL 가중치 적용 확인: 0.00*tech + 0.40*fund + 0.60*mom."""
        regime = _make_regime("EARLY_BULL")
        result = _make_result("A", technical=80.0, fundamental=60.0, momentum=70.0)
        aggregator.aggregate(result, regime.weights)
        expected = 0.00 * 80 + 0.40 * 60 + 0.60 * 70
        assert result.total_score == pytest.approx(expected, abs=0.01)

    def test_late_bull_weighting(self, aggregator):
        """LATE_BULL 가중치 적용 확인: 0.00*tech + 0.50*fund + 0.50*mom."""
        regime = _make_regime("LATE_BULL")
        result = _make_result("A", technical=80.0, fundamental=60.0, momentum=70.0)
        aggregator.aggregate(result, regime.weights)
        expected = 0.00 * 80 + 0.50 * 60 + 0.50 * 70
        assert result.total_score == pytest.approx(expected, abs=0.01)

    def test_bear_weighting(self, aggregator):
        """BEAR 가중치 적용 확인: 0.00*tech + 0.55*fund + 0.45*mom."""
        regime = _make_regime("BEAR")
        result = _make_result("A", technical=80.0, fundamental=60.0, momentum=40.0)
        aggregator.aggregate(result, regime.weights)
        expected = 0.00 * 80 + 0.55 * 60 + 0.45 * 40
        assert result.total_score == pytest.approx(expected, abs=0.01)

    def test_none_score_uses_neutral_50(self, aggregator):
        """None 부문 점수 → 50.0으로 대체."""
        regime = _make_regime()
        result = ScoreResult(code="A")  # 모든 sub-score None
        aggregator.aggregate(result, regime.weights)
        # 전부 50 → 결과도 50
        assert result.total_score == pytest.approx(50.0, abs=0.01)


class TestGetTopN:
    def test_returns_top_5(self, aggregator):
        """10개 중 상위 5개만 반환."""
        # 최소 점수 임계값 미달 방지: 점수를 충분히 높게 설정
        results = [_make_result(f"S{i:02d}", fundamental=70.0, momentum=70.0) for i in range(10)]
        regime = _make_regime("BEAR")   # BEAR min_score=55, 70*0.55+70*0.45=70 > 55
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, regime="BEAR")
        assert len(top) == TOP_N

    def test_ranks_assigned_correctly(self, aggregator):
        """rank는 1부터 순서대로."""
        results = [
            _make_result(f"S{i}", fundamental=float(50 + i), momentum=float(50 + i))
            for i in range(6)
        ]
        regime = _make_regime("BEAR")
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, regime="BEAR")
        for i, r in enumerate(top, 1):
            assert r.rank == i

    def test_highest_score_is_rank1(self, aggregator):
        """가장 높은 점수가 1위."""
        results = [
            _make_result("LOW", fundamental=30.0, momentum=30.0),
            _make_result("HIGH", fundamental=90.0, momentum=90.0),
        ]
        regime = _make_regime("BEAR")
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, n=2, regime="BEAR")
        assert top[0].code == "HIGH"

    def test_market_regime_is_set(self, aggregator):
        """run() 후 결과에 market_regime이 설정된다."""
        code_results = {
            f"S{i}": _make_result(f"S{i}", fundamental=70.0, momentum=70.0)
            for i in range(10)
        }
        regime = _make_regime("BEAR")
        top = aggregator.run(code_results, regime)
        for r in top:
            assert r.market_regime == "BEAR"


class TestSectorConcentration:
    """개선 D-2: 동일 섹터 집중도 제한 테스트."""

    def test_same_sector_limited_to_max(self, aggregator):
        """동일 섹터 3종목 후보 → Top 5에서 최대 MAX_SAME_SECTOR(2)개만 선택."""
        # 10종목: 반도체 3개(최고점), 항공 3개, 바이오 4개
        results = []
        for i in range(3):
            r = _make_result(f"SEMI{i}", fundamental=90.0 - i, momentum=90.0 - i)
            results.append(r)
        for i in range(3):
            r = _make_result(f"AIR{i}", fundamental=80.0 - i, momentum=80.0 - i)
            results.append(r)
        for i in range(4):
            r = _make_result(f"BIO{i}", fundamental=70.0 - i, momentum=70.0 - i)
            results.append(r)

        regime = _make_regime("BEAR")
        for r in results:
            aggregator.aggregate(r, regime.weights)

        sector_map = {
            **{f"SEMI{i}": "반도체" for i in range(3)},
            **{f"AIR{i}": "항공" for i in range(3)},
            **{f"BIO{i}": "바이오" for i in range(4)},
        }
        top = aggregator.get_top_n(
            results, n=5, sector_map=sector_map, regime="BEAR"
        )

        # 각 섹터에서 최대 MAX_SAME_SECTOR개만 포함
        from collections import Counter
        sector_counts = Counter(sector_map.get(r.code, "기타") for r in top)
        for sector, count in sector_counts.items():
            assert count <= MAX_SAME_SECTOR, \
                f"섹터 '{sector}'에서 {count}개 선택 (최대 {MAX_SAME_SECTOR})"

    def test_no_sector_map_no_limit(self, aggregator):
        """sector_map 없으면 섹터 제한 없이 점수 순 반환."""
        results = [
            _make_result(f"S{i}", fundamental=90.0 - i, momentum=90.0 - i)
            for i in range(10)
        ]
        regime = _make_regime("BEAR")
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, regime="BEAR")
        assert len(top) == TOP_N

    def test_max_same_sector_constant(self):
        """MAX_SAME_SECTOR = 2."""
        assert MAX_SAME_SECTOR == 2


class TestMinScoreThreshold:
    """개선 D-3: 최소 점수 임계값 테스트."""

    def test_late_bull_threshold_strictest(self):
        """LATE_BULL 임계값이 EARLY_BULL / BEAR보다 높다 (과열 구간 엄격)."""
        assert MIN_SCORE_THRESHOLD["LATE_BULL"] > MIN_SCORE_THRESHOLD["EARLY_BULL"]
        assert MIN_SCORE_THRESHOLD["LATE_BULL"] > MIN_SCORE_THRESHOLD["BEAR"]

    def test_low_score_excluded_in_late_bull(self, aggregator):
        """LATE_BULL + 점수 < 63 → 추천 제외."""
        # LATE_BULL 가중치: fund 50%, mom 50%
        # fund=60, mom=60 → total=60 < 63 → 제외
        results = [_make_result(f"S{i}", fundamental=60.0, momentum=60.0) for i in range(5)]
        regime = _make_regime("LATE_BULL")
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, regime="LATE_BULL")
        # 60 < 63 → 모두 제외
        assert len(top) == 0

    def test_sufficient_score_passes_threshold(self, aggregator):
        """BEAR + 점수 ≥ 55 → 추천 포함."""
        # BEAR 가중치: fund 55%, mom 45%
        # fund=70, mom=70 → total=70 ≥ 55 → 포함
        results = [_make_result(f"S{i}", fundamental=70.0, momentum=70.0) for i in range(5)]
        regime = _make_regime("BEAR")
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, regime="BEAR")
        assert len(top) == TOP_N

    def test_threshold_dict_has_all_regimes(self):
        """MIN_SCORE_THRESHOLD에 주요 Regime이 모두 정의되어 있다."""
        assert "EARLY_BULL" in MIN_SCORE_THRESHOLD
        assert "LATE_BULL" in MIN_SCORE_THRESHOLD
        assert "BEAR" in MIN_SCORE_THRESHOLD


class TestFailureThreshold:
    def test_above_30pct_failure_returns_empty(self, aggregator):
        """실패율 > 30% → 빈 리스트 반환."""
        total = 10
        fail_count = 4  # 40% > 30%
        code_results = {
            f"S{i}": (ValueError("err") if i < fail_count else _make_result(f"S{i}"))
            for i in range(total)
        }
        top = aggregator.run(code_results, _make_regime())
        assert top == []

    def test_exactly_30pct_failure_returns_results(self, aggregator):
        """실패율 = 30% → 추천 생성 (경계값 통과)."""
        total = 10
        fail_count = 3  # 30% (not >, so allowed)
        # 점수를 충분히 높게 설정하여 BEAR 임계값(55) 통과
        code_results = {
            f"S{i}": (
                ValueError("err")
                if i < fail_count
                else _make_result(f"S{i}", fundamental=70.0, momentum=70.0)
            )
            for i in range(total)
        }
        top = aggregator.run(code_results, _make_regime("BEAR"))
        assert len(top) > 0

    def test_empty_results_returns_empty(self, aggregator):
        """입력 없음 → 빈 리스트."""
        top = aggregator.run({}, _make_regime())
        assert top == []

    def test_fewer_than_5_stocks_returns_all(self, aggregator):
        """유효 종목 5개 미만이면 임계값 통과하는 종목 전체 반환."""
        # 점수를 충분히 높게 설정하여 BEAR 임계값(55) 통과
        code_results = {
            f"S{i}": _make_result(f"S{i}", fundamental=70.0, momentum=70.0)
            for i in range(3)
        }
        top = aggregator.run(code_results, _make_regime("BEAR"))
        assert len(top) == 3
