"""
filters.py
스코어링 전에 추천 제외 대상 종목을 걸러내는 필터 함수 모음.

should_exclude(code, db) → (제외 여부, 사유) 를 반환하는 단일 진입점을 사용한다.
"""
from __future__ import annotations

from loguru import logger

# 이 카테고리의 최근 공시가 있으면 제외
EXCLUDE_DISCLOSURE_CATEGORIES = [
    "관리종목지정",
    "상장폐지",
    "불성실공시",
    "회생절차",
    "거래정지",
]

# 최소 거래일 수 (약 3개월)
MIN_TRADING_DAYS = 60

# 최근 거래량 0 체크 기간
RECENT_VOLUME_DAYS = 5

# 위험 공시 체크 기간 (일)
DISCLOSURE_CHECK_DAYS = 30


def should_exclude(code: str, db, as_of_date: str | None = None) -> tuple[bool, str]:
    """
    종목이 추천 후보에서 제외되어야 하는지 판단한다.

    Args:
        code:        종목코드
        db:          StockRepository 인스턴스
        as_of_date:  기준일 (백테스트용, None이면 현재 기준)

    Returns:
        (제외 여부, 사유 문자열)
    """
    # 1. 비활성 종목
    stock = db.get_stock(code)
    if not stock or not stock.get("is_active", False):
        return True, "비활성 종목"

    # 2. 상장 60거래일 미만
    prices = db.get_prices(code, lookback=MIN_TRADING_DAYS, as_of_date=as_of_date)
    if len(prices) < MIN_TRADING_DAYS:
        return True, f"거래일 부족 ({len(prices)}일 < {MIN_TRADING_DAYS}일)"

    # 3. 최근 5거래일 내 거래량 0 (거래정지 의심)
    if "volume" in prices.columns:
        recent_volume = prices.tail(RECENT_VOLUME_DAYS)["volume"]
        if recent_volume.fillna(0).eq(0).any():
            return True, "최근 5거래일 내 거래량 0"

    # 4. 위험 공시 존재 (최근 30일)
    try:
        recent_disclosures = db.get_recent_disclosures(
            code, days=DISCLOSURE_CHECK_DAYS, as_of_date=as_of_date
        )
        for disc in recent_disclosures:
            cat = disc.get("category", "")
            if cat in EXCLUDE_DISCLOSURE_CATEGORIES:
                return True, f"위험 공시: {cat}"
    except Exception as e:
        logger.warning(f"공시 조회 실패 (필터 스킵) | code={code} | {e}")

    return False, ""
