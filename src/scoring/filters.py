"""
filters.py
스코어링 전에 추천 제외 대상 종목을 걸러내는 필터 함수 모음.

should_exclude(code, db, as_of_date, regime) → (제외 여부, 사유) 를 반환하는 단일 진입점.

개선 D-1: BULL 구간 RSI 과매수 필터 추가
  EARLY_BULL / LATE_BULL 장에서 RSI ≥ 75인 종목은 단기 평균 회귀 위험이 높으므로 제외한다.
  BEAR 구간에서는 RSI 필터를 적용하지 않는다 (하락장에서 과매도 탈출 종목을 놓칠 수 있음).
"""
from __future__ import annotations

import pandas as pd
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

# RSI 과매수 필터 (개선 D-1)
RSI_OVERBOUGHT_THRESHOLD: float = 75.0   # BULL 장 RSI 과매수 기준
RSI_OVERBOUGHT_LOOKBACK: int = 14        # RSI 계산 기간 (거래일)
RSI_OVERBOUGHT_DATA_WINDOW: int = 30     # RSI 필터용 가격 데이터 조회 기간

# RSI 필터를 적용할 Regime 목록
RSI_FILTER_REGIMES = {"EARLY_BULL", "LATE_BULL", "BULL"}


def _calc_rsi(prices: pd.DataFrame, period: int = RSI_OVERBOUGHT_LOOKBACK) -> float | None:
    """
    RSI(Relative Strength Index) 계산.

    Args:
        prices: 'close' 컬럼을 포함하는 가격 DataFrame.
        period: RSI 계산 기간 (기본 14일).

    Returns:
        RSI 값 (0~100). 데이터 부족 시 None 반환.
    """
    if prices.empty or "close" not in prices.columns:
        return None

    close = pd.to_numeric(prices["close"], errors="coerce").dropna()
    if len(close) < period + 1:
        return None

    delta = close.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()

    last_loss = loss.iloc[-1]
    if last_loss == 0 or pd.isna(last_loss):
        # 최근 period일 내 하락이 없으면 RSI = 100
        return 100.0 if gain.iloc[-1] > 0 else 50.0

    rs = gain.iloc[-1] / last_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi)


def should_exclude(
    code: str,
    db,
    as_of_date: str | None = None,
    regime: str | None = None,
) -> tuple[bool, str]:
    """
    종목이 추천 후보에서 제외되어야 하는지 판단한다.

    Args:
        code:        종목코드
        db:          StockRepository 인스턴스
        as_of_date:  기준일 (백테스트용, None이면 현재 기준)
        regime:      현재 Market Regime 문자열 ("EARLY_BULL", "LATE_BULL", "BEAR" 등).
                     None이면 RSI 필터를 적용하지 않는다 (하위 호환).

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

    # 5. BULL 구간 RSI 과매수 필터 (개선 D-1)
    #    EARLY_BULL / LATE_BULL / BULL 장에서만 적용 — BEAR에서는 적용 안 함
    if regime in RSI_FILTER_REGIMES:
        try:
            rsi_prices = db.get_prices(
                code, lookback=RSI_OVERBOUGHT_DATA_WINDOW, as_of_date=as_of_date
            )
            rsi = _calc_rsi(rsi_prices, period=RSI_OVERBOUGHT_LOOKBACK)
            if rsi is not None and rsi >= RSI_OVERBOUGHT_THRESHOLD:
                return True, f"RSI 과매수 ({rsi:.1f} ≥ {RSI_OVERBOUGHT_THRESHOLD})"
        except Exception as e:
            logger.warning(f"RSI 계산 실패 (필터 스킵) | code={code} | {e}")

    return False, ""
