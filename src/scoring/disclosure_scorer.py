"""
disclosure_scorer.py
DART 공시의 카테고리와 제목 키워드를 분석하여 종목별 감성 보정값을 산출한다.

NLP 모델 없이 사전 매핑만으로 동작하므로 외부 의존성이 없고 실시간 처리가 가능하다.

처리 흐름:
  1. 각 공시에 대해 category → CATEGORY_SENTIMENT 매핑
  2. 제목 키워드 → EARNINGS_KEYWORDS 매핑 (첫 매칭만 반영)
  3. 두 값을 합산 → -1.0 ~ +1.0 클리핑
  4. 전체 공시를 시간 감쇠 가중 평균 → × 10 → -10.0 ~ +10.0 보정값

최종 보정값은 stock_scores.disclosure_adjustment 컬럼에 저장된다.
disclosures.sentiment_score 컬럼은 공시별 단건 점수로 업데이트된다.
"""
from __future__ import annotations

from loguru import logger

# ============================================================
# 공시 카테고리별 감성 점수 사전
# 값 범위: -1.0 ~ +1.0
# ============================================================
CATEGORY_SENTIMENT: dict[str, float] = {
    # ── 강한 호재 ──────────────────────────────────────────
    "자기주식취득결정":              +0.8,  # 자사주 매입 → 주주환원 신호
    "주식배당결정":                 +0.6,  # 기존 주주 배당
    "무상증자결정":                 +0.7,  # 기존 주주 추가 주식 지급
    "타법인주식및출자증권취득결정":  +0.5,  # M&A, 사업 확장
    # ── 강한 악재 ──────────────────────────────────────────
    "유상증자결정":                 -0.7,  # 지분 희석
    "전환사채권발행결정":            -0.5,  # 잠재적 지분 희석
    "감자결정":                     -0.8,  # 주식 수 감소 (보통 악재)
    "영업정지":                     -1.0,
    "회생절차":                     -1.0,
    "관리종목지정":                 -0.9,
    "불성실공시":                   -0.6,
    "상장폐지":                     -1.0,
    "거래정지":                     -0.9,
    "소송등의제기":                 -0.3,
    # ── 중립 / 상황 의존 ───────────────────────────────────
    "대표이사변경":                 +0.1,
    "합병결정":                     +0.2,
    "분할결정":                     +0.1,
    "최대주주변경":                 +0.3,
}

# ============================================================
# 실적 관련 키워드 (공시 제목 매칭)
# 값 범위: -1.0 ~ +1.0
# 첫 번째 매칭 키워드만 반영
# ============================================================
EARNINGS_KEYWORDS: dict[str, float] = {
    "영업이익증가": +0.6,
    "영업이익감소": -0.6,
    "흑자전환":     +0.8,
    "적자전환":     -0.8,
    "매출액증가":   +0.4,
    "매출액감소":   -0.4,
    "사상최대":     +0.7,
    "최대실적":     +0.7,
}


def score_single_disclosure(category: str, title: str) -> float:
    """
    단일 공시의 감성 점수를 산출한다.

    처리 순서:
    1. CATEGORY_SENTIMENT 사전에서 카테고리 매핑 (없으면 0.0)
    2. EARNINGS_KEYWORDS 사전에서 제목 키워드 매핑 (첫 번째 매칭만 더함)
    3. 두 값을 합산 후 -1.0 ~ +1.0으로 클리핑

    Args:
        category: disclosures.category 값
        title:    disclosures.title 값

    Returns:
        float, -1.0 ~ +1.0
    """
    score = CATEGORY_SENTIMENT.get(category, 0.0)

    for keyword, value in EARNINGS_KEYWORDS.items():
        if keyword in title:
            score += value
            break  # 첫 번째 매칭 키워드만 반영

    return round(max(-1.0, min(1.0, score)), 2)


def disclosure_adjustment(
    disclosures: list[dict],
    lookback_days: int = 30,
) -> float:
    """
    최근 N일 공시의 감성 점수를 시간 감쇠 가중 평균하여 최종 보정값을 반환한다.

    규칙:
    - 오늘 공시(days_ago=0) → 가중치 1.0
    - lookback_days 전 공시   → 가중치 0.1 (선형 감쇠)
    - 카테고리/키워드 모두 매칭 안 되는 공시(score == 0.0)는 무시
    - 최종 보정값: -10.0 ~ +10.0

    각 dict는 'category', 'title', 'days_ago' 키를 가져야 한다.
    'days_ago'가 없으면 0(오늘)으로 처리한다.

    Args:
        disclosures:   get_recent_disclosures() 반환 리스트
        lookback_days: 시간 감쇠 기준 기간 (기본 30일)

    Returns:
        float, -10.0 ~ +10.0. stock_scores.disclosure_adjustment 컬럼에 저장.
    """
    if not disclosures:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    scored_count = 0

    for disc in disclosures:
        sentiment = score_single_disclosure(
            disc.get("category", ""),
            disc.get("title", ""),
        )

        if sentiment == 0.0:
            continue

        days_ago = max(0, disc.get("days_ago", 0))
        # 선형 감쇠: days_ago=0 → 1.0, days_ago=lookback_days → 0.1
        time_weight = max(0.1, 1.0 - (days_ago / lookback_days) * 0.9)

        weighted_sum += sentiment * time_weight
        weight_total += time_weight
        scored_count += 1

    if weight_total == 0:
        return 0.0

    avg_sentiment = weighted_sum / weight_total   # -1.0 ~ +1.0
    adjustment = avg_sentiment * 10               # -10.0 ~ +10.0
    adjustment = round(max(-10.0, min(10.0, adjustment)), 2)

    logger.debug(
        f"공시 보정 | 유효={scored_count}건 "
        f"avg_sentiment={avg_sentiment:.3f} → adjustment={adjustment:+.2f}"
    )
    return adjustment
