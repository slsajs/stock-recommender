"""
aggregator.py
종목별 기술/재무/모멘텀 점수를 MarketRegime 가중치로 합산하여 최종 점수를 산출하고
상위 5개 종목을 추천한다.

실패율이 30%를 초과하면 해당 일자 추천을 생성하지 않는다.
"""
from __future__ import annotations

from loguru import logger

from src.scoring.base import ScoreResult
from src.scoring.market_regime import MarketRegime

# 추천 종목 수
TOP_N = 5

# 스코어링 실패 허용 임계치
FAILURE_THRESHOLD = 0.30


class ScoreAggregator:
    """개별 스코어를 집계하여 최종 점수·순위를 결정한다."""

    def aggregate(self, result: ScoreResult, weights: dict[str, float]) -> ScoreResult:
        """
        3개 부문 점수를 가중합하여 result.total_score 갱신.

        None인 부문은 중립값 50.0으로 대체한다.
        """
        tech = result.technical_score if result.technical_score is not None else 50.0
        fund = result.fundamental_score if result.fundamental_score is not None else 50.0
        mom = result.momentum_score if result.momentum_score is not None else 50.0

        result.total_score = round(
            tech * weights["technical"]
            + fund * weights["fundamental"]
            + mom * weights["momentum"],
            2,
        )
        return result

    def get_top_n(
        self, results: list[ScoreResult], n: int = TOP_N
    ) -> list[ScoreResult]:
        """total_score 내림차순 정렬 후 상위 n개에 rank 부여."""
        sorted_results = sorted(results, key=lambda r: r.total_score, reverse=True)
        top = sorted_results[:n]
        for i, r in enumerate(top, 1):
            r.rank = i
        return top

    def run(
        self,
        code_results: dict[str, ScoreResult | Exception],
        regime: MarketRegime,
    ) -> list[ScoreResult]:
        """
        전체 종목 집계 진입점.

        Args:
            code_results: {code: ScoreResult 또는 Exception}
            regime:       당일 MarketRegime (가중치 포함)

        Returns:
            상위 TOP_N 추천 종목 리스트.
            실패율 > FAILURE_THRESHOLD이면 빈 리스트 반환.
        """
        total = len(code_results)
        if total == 0:
            logger.warning("집계할 종목 결과가 없음")
            return []

        failed = [k for k, v in code_results.items() if isinstance(v, Exception)]
        fail_rate = len(failed) / total

        if fail_rate > FAILURE_THRESHOLD:
            logger.error(
                f"실패율 {len(failed)}/{total} ({fail_rate:.1%}) > "
                f"{FAILURE_THRESHOLD:.0%} — 추천 생성 중단"
            )
            return []

        if failed:
            logger.warning(f"스코어링 실패 {len(failed)}건 (무시하고 집계 진행)")

        valid: list[ScoreResult] = [
            v for v in code_results.values() if isinstance(v, ScoreResult)
        ]

        for r in valid:
            self.aggregate(r, regime.weights)
            r.market_regime = regime.regime

        top = self.get_top_n(valid)
        logger.info(
            f"집계 완료 | 유효={len(valid)}, 실패={len(failed)}, "
            f"regime={regime.regime}"
        )
        return top
