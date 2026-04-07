"""
fundamental.py
재무 지표(PER, PBR, ROE, 부채비율)로 0~100 점수를 산출하는 스코어러.

섹터 상대비교 원칙:
  - 같은 섹터 종목이 5개 이상이면 → 섹터 내 백분위
  - 같은 섹터 종목이 5개 미만이면 → 전체 종목 백분위로 폴백
  - PER/PBR/부채비율은 낮을수록 고점수 (value 전략)
  - ROE는 높을수록 고점수
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from src.scoring.base import BaseScorer, ScoreResult
from src.scoring.macro_adjuster import DEFAULT_FUNDAMENTAL_WEIGHTS

# 섹터 상대비교 최소 종목 수
MIN_SECTOR_SIZE = 5

# PER/PBR 음수 또는 None 시 기본값
DEFAULT_NEGATIVE_SCORE = 30.0

# 부채비율 None 시 기본값 (정보 없음 → 중립)
DEFAULT_DEBT_SCORE = 50.0

# ROE None 시 기본값
DEFAULT_ROE_SCORE = 30.0

# 섹터 평균 대비 할인율 임계치 (20%) 보너스 점수
SECTOR_DISCOUNT_THRESHOLD = 0.80
SECTOR_DISCOUNT_BONUS = 10.0


class FundamentalScorer(BaseScorer):
    """PER / PBR / ROE / 부채비율 기반 재무 점수 계산 (섹터 상대비교)."""

    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        Args:
            financials (dict):               get_latest_financials() 반환값
            sector_financials (pd.DataFrame): 같은 섹터 종목들의 재무 DataFrame
            all_financials (pd.DataFrame):    전체 종목 재무 DataFrame (폴백용)
            sector_stats (dict | None):       섹터 통계 (avg_per 등)
            fund_internal_weights (dict | None):
                PER/PBR/ROE/부채비율 내부 가중치.
                {"per": float, "pbr": float, "roe": float, "debt": float}
                None이면 DEFAULT_FUNDAMENTAL_WEIGHTS 사용.
                [STEP A] macro_adjuster.get_fundamental_weights()가 주입한다.
        """
        fin: dict = kwargs.get("financials") or {}
        sector_fin: pd.DataFrame = kwargs.get("sector_financials", pd.DataFrame())
        all_fin: pd.DataFrame = kwargs.get("all_financials", pd.DataFrame())
        sector_stats: dict = kwargs.get("sector_stats") or {}
        weights: dict[str, float] = kwargs.get("fund_internal_weights") or dict(DEFAULT_FUNDAMENTAL_WEIGHTS)

        result = ScoreResult(code=code)

        avg_per = sector_stats.get("avg_per")

        result.per_score = self._per_score(fin, sector_fin, all_fin, avg_per)
        result.pbr_score = self._pbr_score(fin, sector_fin, all_fin)
        result.roe_score = self._roe_score(fin, sector_fin, all_fin)
        result.debt_score = self._debt_score(fin, sector_fin, all_fin)

        # 가중 평균: None인 지표는 제외하고 나머지 가중치를 재정규화
        score_weight_pairs = [
            (result.per_score,  weights.get("per",  0.30)),
            (result.pbr_score,  weights.get("pbr",  0.25)),
            (result.roe_score,  weights.get("roe",  0.30)),
            (result.debt_score, weights.get("debt", 0.15)),
        ]
        valid_pairs = [(s, w) for s, w in score_weight_pairs if s is not None]

        if not valid_pairs:
            result.fundamental_score = 50.0
        else:
            total_weight = sum(w for _, w in valid_pairs)
            if total_weight == 0:
                result.fundamental_score = 50.0
            else:
                result.fundamental_score = round(
                    sum(s * w for s, w in valid_pairs) / total_weight, 2
                )

        return result

    # ------------------------------------------------------------------
    # PER 점수
    # ------------------------------------------------------------------

    def _per_score(
        self,
        fin: dict,
        sector_fin: pd.DataFrame,
        all_fin: pd.DataFrame,
        sector_avg_per: float | None,
    ) -> float:
        per = fin.get("per")
        if per is None or float(per) <= 0:
            return DEFAULT_NEGATIVE_SCORE

        per = float(per)

        valid_sector = _positive_series(sector_fin, "per")
        if len(valid_sector) >= MIN_SECTOR_SIZE:
            score = 100.0 - self.percentile_score(per, valid_sector)
        else:
            valid_all = _positive_series(all_fin, "per")
            if valid_all.empty:
                return DEFAULT_NEGATIVE_SCORE
            score = 100.0 - self.percentile_score(per, valid_all)

        # 섹터 평균 대비 20% 이상 할인 → 보너스 +10
        if sector_avg_per and float(sector_avg_per) > 0 and per < float(sector_avg_per) * SECTOR_DISCOUNT_THRESHOLD:
            score = min(100.0, score + SECTOR_DISCOUNT_BONUS)

        return round(score, 2)

    # ------------------------------------------------------------------
    # PBR 점수
    # ------------------------------------------------------------------

    def _pbr_score(
        self,
        fin: dict,
        sector_fin: pd.DataFrame,
        all_fin: pd.DataFrame,
    ) -> float:
        pbr = fin.get("pbr")
        if pbr is None or float(pbr) <= 0:
            return DEFAULT_NEGATIVE_SCORE

        pbr = float(pbr)

        valid_sector = _positive_series(sector_fin, "pbr")
        if len(valid_sector) >= MIN_SECTOR_SIZE:
            score = 100.0 - self.percentile_score(pbr, valid_sector)
        else:
            valid_all = _positive_series(all_fin, "pbr")
            if valid_all.empty:
                return DEFAULT_NEGATIVE_SCORE
            score = 100.0 - self.percentile_score(pbr, valid_all)

        return round(score, 2)

    # ------------------------------------------------------------------
    # ROE 점수
    # ------------------------------------------------------------------

    def _roe_score(
        self,
        fin: dict,
        sector_fin: pd.DataFrame,
        all_fin: pd.DataFrame,
    ) -> float:
        roe = fin.get("roe")
        if roe is None:
            return DEFAULT_ROE_SCORE

        roe = float(roe)

        valid_sector = _nonempty_series(sector_fin, "roe")
        if len(valid_sector) >= MIN_SECTOR_SIZE:
            score = self.percentile_score(roe, valid_sector)
        else:
            valid_all = _nonempty_series(all_fin, "roe")
            if valid_all.empty:
                return DEFAULT_ROE_SCORE
            score = self.percentile_score(roe, valid_all)

        return round(score, 2)

    # ------------------------------------------------------------------
    # 부채비율 점수
    # ------------------------------------------------------------------

    def _debt_score(
        self,
        fin: dict,
        sector_fin: pd.DataFrame,
        all_fin: pd.DataFrame,
    ) -> float:
        debt_ratio = fin.get("debt_ratio")
        if debt_ratio is None:
            return DEFAULT_DEBT_SCORE

        debt_ratio = float(debt_ratio)

        valid_sector = _positive_series(sector_fin, "debt_ratio")
        if len(valid_sector) >= MIN_SECTOR_SIZE:
            score = 100.0 - self.percentile_score(debt_ratio, valid_sector)
        else:
            valid_all = _positive_series(all_fin, "debt_ratio")
            if valid_all.empty:
                return DEFAULT_DEBT_SCORE
            score = 100.0 - self.percentile_score(debt_ratio, valid_all)

        return round(score, 2)


# ------------------------------------------------------------------
# 유틸
# ------------------------------------------------------------------

def _positive_series(df: pd.DataFrame, col: str) -> pd.Series:
    """DataFrame에서 col 컬럼의 양수 값만 Series로 반환."""
    if df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df[col], errors="coerce")
    return s[s > 0].dropna()


def _nonempty_series(df: pd.DataFrame, col: str) -> pd.Series:
    """DataFrame에서 col 컬럼의 non-null 값을 Series로 반환."""
    if df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").dropna()
