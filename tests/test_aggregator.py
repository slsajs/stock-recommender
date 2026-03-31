"""
test_aggregator.py
ScoreAggregator 단위 테스트.
"""
import pytest

from src.scoring.aggregator import FAILURE_THRESHOLD, TOP_N, ScoreAggregator
from src.scoring.base import ScoreResult
from src.scoring.market_regime import MarketRegime


def _make_regime(regime: str = "BULL") -> MarketRegime:
    if regime == "BULL":
        return MarketRegime(
            regime="BULL",
            weights={"technical": 0.20, "fundamental": 0.40, "momentum": 0.40},
            ma20=2500.0,
            ma60=2400.0,
        )
    return MarketRegime(
        regime="BEAR",
        weights={"technical": 0.45, "fundamental": 0.40, "momentum": 0.15},
        ma20=2300.0,
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
    def test_bull_weighting(self, aggregator):
        """BULL 가중치 적용 확인: 0.20*tech + 0.40*fund + 0.40*mom."""
        regime = _make_regime("BULL")
        result = _make_result("A", technical=80.0, fundamental=60.0, momentum=70.0)
        aggregator.aggregate(result, regime.weights)
        expected = 0.20 * 80 + 0.40 * 60 + 0.40 * 70
        assert result.total_score == pytest.approx(expected, abs=0.01)

    def test_bear_weighting(self, aggregator):
        """BEAR 가중치 적용 확인: 0.45*tech + 0.40*fund + 0.15*mom."""
        regime = _make_regime("BEAR")
        result = _make_result("A", technical=80.0, fundamental=60.0, momentum=40.0)
        aggregator.aggregate(result, regime.weights)
        expected = 0.45 * 80 + 0.40 * 60 + 0.15 * 40
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
        results = [_make_result(f"S{i:02d}", technical=float(i * 10)) for i in range(10)]
        regime = _make_regime()
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results)
        assert len(top) == TOP_N

    def test_ranks_assigned_correctly(self, aggregator):
        """rank는 1부터 순서대로."""
        results = [_make_result(f"S{i}", technical=float(i)) for i in range(6)]
        regime = _make_regime()
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results)
        for i, r in enumerate(top, 1):
            assert r.rank == i

    def test_highest_score_is_rank1(self, aggregator):
        """가장 높은 점수가 1위."""
        results = [
            _make_result("LOW", technical=10.0, fundamental=10.0, momentum=10.0),
            _make_result("HIGH", technical=90.0, fundamental=90.0, momentum=90.0),
        ]
        regime = _make_regime()
        for r in results:
            aggregator.aggregate(r, regime.weights)
        top = aggregator.get_top_n(results, n=2)
        assert top[0].code == "HIGH"

    def test_market_regime_is_set(self, aggregator):
        """run() 후 결과에 market_regime이 설정된다."""
        code_results = {f"S{i}": _make_result(f"S{i}") for i in range(10)}
        regime = _make_regime("BEAR")
        top = aggregator.run(code_results, regime)
        for r in top:
            assert r.market_regime == "BEAR"


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
        code_results = {
            f"S{i}": (ValueError("err") if i < fail_count else _make_result(f"S{i}"))
            for i in range(total)
        }
        top = aggregator.run(code_results, _make_regime())
        assert len(top) > 0

    def test_empty_results_returns_empty(self, aggregator):
        """입력 없음 → 빈 리스트."""
        top = aggregator.run({}, _make_regime())
        assert top == []

    def test_fewer_than_5_stocks_returns_all(self, aggregator):
        """유효 종목 5개 미만이면 전체 반환."""
        code_results = {f"S{i}": _make_result(f"S{i}") for i in range(3)}
        top = aggregator.run(code_results, _make_regime())
        assert len(top) == 3
