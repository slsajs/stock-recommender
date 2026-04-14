"""
aggregator.py
종목별 기술/재무/모멘텀 점수를 MarketRegime 가중치로 합산하여 최종 점수를 산출하고
상위 5개 종목을 추천한다.

개선 D-2: 동일 섹터 최대 2종목 제한
개선 D-3: Regime별 최소 추천 점수 임계값 도입
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

# 동일 섹터 최대 추천 수 (개선 D-2)
MAX_SAME_SECTOR: int = 2

# Regime별 최소 추천 점수 임계값 (개선 D-3)
# LATE_BULL(과열 구간)에서 가장 엄격하게 적용
MIN_SCORE_THRESHOLD: dict[str, float] = {
    "EARLY_BULL": 58.0,
    "LATE_BULL":  63.0,
    "BEAR":       55.0,
    "BULL":       60.0,   # 구형 호환용
}


class ScoreAggregator:
    """개별 스코어를 집계하여 최종 점수·순위를 결정한다."""

    def aggregate(self, result: ScoreResult, weights: dict[str, float]) -> ScoreResult:
        """
        3개 부문 점수를 가중합하여 result.total_score 갱신.
        이후 보정값(macro_adjustment 등)을 합산해 adjusted_total_score 계산.

        None인 부문은 중립값 50.0으로 대체한다.
        """
        tech = result.technical_score if result.technical_score is not None else 50.0
        fund = result.fundamental_score if result.fundamental_score is not None else 50.0
        mom = result.momentum_score if result.momentum_score is not None else 50.0

        result.total_score = round(
            tech * weights.get("technical", 0.0)
            + fund * weights["fundamental"]
            + mom * weights["momentum"],
            2,
        )

        # [고도화] 보정값 합산 → adjusted_total_score
        total_adjustment = (
            result.macro_adjustment
            + result.disclosure_adjustment
            + result.news_adjustment
        )
        result.adjusted_total_score = round(result.total_score + total_adjustment, 2)

        return result

    def get_top_n(
        self,
        results: list[ScoreResult],
        n: int = TOP_N,
        sector_map: dict[str, str] | None = None,
        regime: str = "BEAR",
    ) -> list[ScoreResult]:
        """
        adjusted_total_score 내림차순 정렬 후 상위 n개 선정.

        Args:
            results:    집계된 ScoreResult 목록.
            n:          추천 종목 수 (기본 TOP_N=5).
            sector_map: {code: sector} 맵. 있으면 동일 섹터 MAX_SAME_SECTOR 제한 적용.
            regime:     현재 Regime 문자열. MIN_SCORE_THRESHOLD 조회에 사용.

        Returns:
            상위 n개 ScoreResult (rank 1~n 부여). 임계값 미달 시 n보다 적을 수 있음.
        """
        # 최소 점수 임계값 필터링 (개선 D-3)
        min_score = MIN_SCORE_THRESHOLD.get(regime, 55.0)
        eligible = [
            r for r in results
            if (r.adjusted_total_score if r.adjusted_total_score is not None else r.total_score or 0.0) >= min_score
        ]

        if len(eligible) < len(results):
            excluded_count = len(results) - len(eligible)
            if excluded_count > 0:
                logger.debug(
                    f"최소 점수 임계값({min_score}) 미달 {excluded_count}건 제외 "
                    f"| regime={regime}"
                )

        if len(eligible) < n:
            logger.warning(
                f"임계값({min_score}) 이상 종목 {len(eligible)}개 — "
                f"Top {n} 미달, {len(eligible)}개만 추천 가능"
            )

        # 점수 내림차순 정렬
        sorted_results = sorted(
            eligible,
            key=lambda r: r.adjusted_total_score if r.adjusted_total_score is not None else r.total_score,
            reverse=True,
        )

        # 섹터 집중도 제한 적용 (개선 D-2)
        if sector_map is None:
            top = sorted_results[:n]
        else:
            top: list[ScoreResult] = []
            sector_count: dict[str, int] = {}
            for r in sorted_results:
                if len(top) >= n:
                    break
                sector = sector_map.get(r.code, "기타")
                if sector_count.get(sector, 0) < MAX_SAME_SECTOR:
                    top.append(r)
                    sector_count[sector] = sector_count.get(sector, 0) + 1
                else:
                    logger.debug(
                        f"섹터 집중도 제한 초과 — 제외 | code={r.code} | sector={sector} "
                        f"({sector_count[sector]}/{MAX_SAME_SECTOR})"
                    )

        for i, r in enumerate(top, 1):
            r.rank = i
        return top

    def run(
        self,
        code_results: dict[str, ScoreResult | Exception],
        regime: MarketRegime,
        sector_map: dict[str, str] | None = None,
    ) -> list[ScoreResult]:
        """
        전체 종목 집계 진입점.

        Args:
            code_results: {code: ScoreResult 또는 Exception}
            regime:       당일 MarketRegime (가중치 포함)
            sector_map:   {code: sector} 맵 (섹터 집중도 제한용, 없으면 제한 없음)

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

        top = self.get_top_n(valid, sector_map=sector_map, regime=regime.regime)
        logger.info(
            f"집계 완료 | 유효={len(valid)}, 실패={len(failed)}, "
            f"regime={regime.regime} | 추천={len(top)}개"
        )
        return top
