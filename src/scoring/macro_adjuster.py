"""
macro_adjuster.py
거시경제 지표(금리, 환율, 장단기 금리차, 미국 시장)를 기반으로
스코어링 가중치 조정 및 보정값을 산출한다.

STEP A: 금리 트렌드 → FundamentalScorer 내부 가중치 조절
STEP B: 환율 → 섹터별 최종 점수 보정             (추후 구현)
STEP C: 장단기 금리차 → Market Regime 보강        (추후 구현)
STEP D: 미국 시장 급락 → 추천 보류 판단           (추후 구현)

현재 파일에는 STEP A 관련 함수만 구현되어 있다.
"""
from __future__ import annotations

from loguru import logger

# ------------------------------------------------------------------
# STEP A: 금리 트렌드 → FundamentalScorer 내부 가중치 조절
# ------------------------------------------------------------------

# 기본 재무 내부 가중치 (합 = 1.0)
DEFAULT_FUNDAMENTAL_WEIGHTS: dict[str, float] = {
    "per": 0.30,
    "pbr": 0.25,
    "roe": 0.30,
    "debt": 0.15,
}

# 기준금리 변동 임계치 (이 이상 움직여야 트렌드로 인정)
RATE_CHANGE_THRESHOLD = 0.25  # %p


def determine_rate_trend(
    db, lookback_months: int = 3, as_of_date: str | None = None
) -> str:
    """
    최근 N개월간 기준금리 변동 방향을 판단한다.

    ECOS에서 수집한 BASE_RATE(월별)를 기준으로, 기간 내 최초값과
    최신값의 차이가 RATE_CHANGE_THRESHOLD(0.25%p) 이상이면 방향성 있음으로 판단.

    규칙:
    - 0.25%p 이상 상승  → "RISING"
    - 0.25%p 이상 하락  → "FALLING"
    - 변동 없거나 미만   → "STABLE"
    - 데이터 1건 미만    → "STABLE" (안전한 기본값)

    Args:
        db:              StockRepository 인스턴스
        lookback_months: 판단 기간 (개월수, 기본 3개월)
        as_of_date:      기준일 (YYYY-MM-DD). 백테스트 시 해당 날짜 이전 데이터만 사용.
                         None이면 오늘 기준 (운영 모드).

    Returns:
        "RISING" | "FALLING" | "STABLE"
    """
    lookback_days = lookback_months * 30
    rates = db.get_macro_indicator(
        "BASE_RATE", lookback_days=lookback_days, as_of_date=as_of_date
    )

    if rates.empty or len(rates) < 2:
        logger.debug("BASE_RATE 데이터 부족 — STABLE 반환")
        return "STABLE"

    oldest = float(rates.iloc[0]["value"])
    latest = float(rates.iloc[-1]["value"])
    diff = latest - oldest

    if diff >= RATE_CHANGE_THRESHOLD:
        logger.debug(f"금리 트렌드: RISING ({oldest:.2f} → {latest:.2f}, Δ{diff:+.2f})")
        return "RISING"
    elif diff <= -RATE_CHANGE_THRESHOLD:
        logger.debug(f"금리 트렌드: FALLING ({oldest:.2f} → {latest:.2f}, Δ{diff:+.2f})")
        return "FALLING"
    else:
        logger.debug(f"금리 트렌드: STABLE ({oldest:.2f} → {latest:.2f}, Δ{diff:+.2f})")
        return "STABLE"


# ------------------------------------------------------------------
# STEP B: 환율 → 섹터별 점수 보정
# ------------------------------------------------------------------

# 수출 수혜 섹터 — 원화 약세(환율 상승) 시 수익 증가
EXPORT_SECTORS: list[str] = ['반도체', '자동차', '조선', '전자부품', '디스플레이', 'IT하드웨어']

# 수입 비용 증가 섹터 — 원화 약세(환율 상승) 시 비용 증가
IMPORT_SECTORS: list[str] = ['항공', '정유', '철강', '화학']


def get_usd_krw_change(db, lookback_days: int = 20, as_of_date: str | None = None) -> float:
    """
    최근 N거래일 원/달러 환율 변동률(%)을 반환한다.

    양수 = 원화 약세(환율 상승), 음수 = 원화 강세(환율 하락).
    데이터가 없거나 2건 미만이면 0.0 반환.

    Args:
        db:           StockRepository 인스턴스
        lookback_days: 조회 기간 (거래일 기준 20일 ≈ 약 1개월)
        as_of_date:   기준일 (YYYY-MM-DD). 백테스트 look-ahead bias 방지용.

    Returns:
        변동률 (%). 예) +3.0 = 환율 3% 상승(원화 약세)
    """
    rates = db.get_macro_indicator(
        "USD_KRW", lookback_days=lookback_days, as_of_date=as_of_date
    )

    if rates.empty or len(rates) < 2:
        logger.debug("USD_KRW 데이터 부족 — 환율 변동률 0.0 반환")
        return 0.0

    oldest = float(rates.iloc[0]["value"])
    latest = float(rates.iloc[-1]["value"])

    if oldest == 0:
        return 0.0

    change = round((latest - oldest) / oldest * 100, 4)
    logger.debug(f"환율 변동률: {oldest:.1f} → {latest:.1f} ({change:+.2f}%)")
    return change


def currency_adjustment(sector: str | None, usd_krw_change: float) -> float:
    """
    환율 변동률에 따른 섹터별 점수 보정값을 반환한다.

    규칙:
    - 수출 섹터(반도체, 자동차 등): 환율 1% 상승당 +1점, 최대 ±5.0
    - 수입 의존 섹터(항공, 정유 등): 환율 1% 상승당 -1점, 최대 ±5.0
    - 기타 섹터 또는 섹터 미분류 : 0.0 (보정 없음)

    Args:
        sector:          stocks.sector 값. None이면 미분류로 처리.
        usd_krw_change:  최근 20거래일 환율 변동률 (%). get_usd_krw_change() 반환값.

    Returns:
        float, -5.0 ~ +5.0 범위로 클리핑
    """
    if not sector:
        return 0.0

    if sector in EXPORT_SECTORS:
        adj = usd_krw_change * 1.0
    elif sector in IMPORT_SECTORS:
        adj = usd_krw_change * -1.0
    else:
        return 0.0

    return round(max(-5.0, min(5.0, adj)), 2)


def get_fundamental_weights(base_rate_trend: str) -> dict[str, float]:
    """
    금리 트렌드에 따라 FundamentalScorer 내부 가중치를 반환한다.

    조절 원리:
    - RISING  (금리 인상기): 저PER 선호 → PER 가중치 ↑, ROE 가중치 ↓
    - FALLING (금리 인하기): 성장주 선호 → ROE 가중치 ↑, PER 가중치 ↓
    - STABLE               : 기본 가중치 유지

    반환값 합계는 항상 1.0을 보장한다.

    Args:
        base_rate_trend: "RISING" | "FALLING" | "STABLE"

    Returns:
        {"per": float, "pbr": float, "roe": float, "debt": float}
    """
    if base_rate_trend == "RISING":
        # 금리 인상기: 저PER 가치주 유리 → PER 비중 ↑, ROE 비중 ↓
        return {"per": 0.40, "pbr": 0.25, "roe": 0.20, "debt": 0.15}
    elif base_rate_trend == "FALLING":
        # 금리 인하기: 고ROE 성장주 유리 → ROE 비중 ↑, PER/PBR 비중 ↓
        return {"per": 0.20, "pbr": 0.20, "roe": 0.40, "debt": 0.20}
    else:
        # STABLE: 기본 가중치
        return dict(DEFAULT_FUNDAMENTAL_WEIGHTS)
