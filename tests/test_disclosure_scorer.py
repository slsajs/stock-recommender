"""
test_disclosure_scorer.py
disclosure_scorer.py 단위 테스트.

DB 없이 실행 (순수 함수만 테스트).
"""
import pytest

from src.scoring.disclosure_scorer import (
    CATEGORY_SENTIMENT,
    EARNINGS_KEYWORDS,
    disclosure_adjustment,
    score_single_disclosure,
)


# ============================================================
# score_single_disclosure — 단건 점수 테스트
# ============================================================


class TestScoreSingleDisclosure:
    def test_category_positive_buyback(self):
        """자기주식취득결정 → +0.8"""
        score = score_single_disclosure("자기주식취득결정", "자기주식취득결정")
        assert score == pytest.approx(0.8)

    def test_category_negative_rights_offering(self):
        """유상증자결정 → -0.7"""
        score = score_single_disclosure("유상증자결정", "유상증자결정")
        assert score == pytest.approx(-0.7)

    def test_category_unknown_with_title_turnaround(self):
        """카테고리 매칭 안됨 + 제목에 '흑자전환' → +0.8"""
        score = score_single_disclosure("일반공시", "A기업 흑자전환 발표")
        assert score == pytest.approx(0.8)

    def test_category_unknown_with_title_deficit(self):
        """카테고리 매칭 안됨 + 제목에 '적자전환' → -0.8"""
        score = score_single_disclosure("일반공시", "B기업 적자전환")
        assert score == pytest.approx(-0.8)

    def test_category_and_title_combined_clipped_to_one(self):
        """합병결정(+0.2) + 제목 '사상최대'(+0.7) → min(1.0, 0.9) = 0.9"""
        score = score_single_disclosure("합병결정", "합병 후 사상최대 실적 기대")
        assert score == pytest.approx(0.9)

    def test_category_and_title_combined_clipped_to_minus_one(self):
        """회생절차(-1.0) + 적자전환(-0.8) → max(-1.0, ...) = -1.0"""
        score = score_single_disclosure("회생절차", "적자전환으로 회생절차 신청")
        assert score == pytest.approx(-1.0)

    def test_no_category_no_title_keyword(self):
        """카테고리/키워드 모두 없음 → 0.0"""
        score = score_single_disclosure("일반공시", "신규 사업 검토 중")
        assert score == pytest.approx(0.0)

    def test_empty_strings(self):
        """빈 문자열 → 0.0"""
        score = score_single_disclosure("", "")
        assert score == pytest.approx(0.0)

    def test_category_severe_danger_management_stock(self):
        """관리종목지정 → -0.9"""
        score = score_single_disclosure("관리종목지정", "관리종목지정 안내")
        assert score == pytest.approx(-0.9)

    def test_category_delisting(self):
        """상장폐지 → -1.0"""
        score = score_single_disclosure("상장폐지", "상장폐지 결정")
        assert score == pytest.approx(-1.0)

    def test_only_first_title_keyword_is_applied(self):
        """제목에 키워드 2개 있어도 첫 번째만 반영 — 결과가 ≤ 1.0"""
        # '흑자전환'(+0.8)과 '사상최대'(+0.7)가 모두 있는 제목
        # 흑자전환이 EARNINGS_KEYWORDS에서 먼저 나오므로 +0.8만 반영
        score = score_single_disclosure("일반공시", "흑자전환 및 사상최대 실적")
        assert -1.0 <= score <= 1.0
        # 두 키워드 모두 반영되면 1.0을 초과하지만, 클리핑으로 1.0이어야 함
        # 흑자전환만 반영(첫 매칭)되면 0.8
        assert score == pytest.approx(0.8)

    def test_score_range_always_within_bounds(self):
        """모든 카테고리 감성 값이 -1.0 ~ +1.0 범위 내에 있어야 한다."""
        for category, sentiment in CATEGORY_SENTIMENT.items():
            assert -1.0 <= sentiment <= 1.0, f"{category}: {sentiment}"

    def test_earnings_keyword_range(self):
        """모든 실적 키워드 감성 값이 -1.0 ~ +1.0 범위 내에 있어야 한다."""
        for keyword, sentiment in EARNINGS_KEYWORDS.items():
            assert -1.0 <= sentiment <= 1.0, f"{keyword}: {sentiment}"


# ============================================================
# disclosure_adjustment — 집계 보정값 테스트
# ============================================================


class TestDisclosureAdjustment:
    def test_empty_list_returns_zero(self):
        """공시 없음 → 0.0"""
        result = disclosure_adjustment([])
        assert result == pytest.approx(0.0)

    def test_single_negative_disclosure_today(self):
        """오늘 유상증자(-0.7) → 보정값 = -0.7 × 10 = -7.0"""
        discs = [
            {
                "category": "유상증자결정",
                "title": "유상증자결정",
                "days_ago": 0,
                "dart_rcp_no": "20240101000001",
            }
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(-7.0)

    def test_single_positive_disclosure_today(self):
        """오늘 자기주식취득(+0.8) → 보정값 = +0.8 × 10 = +8.0"""
        discs = [
            {
                "category": "자기주식취득결정",
                "title": "자기주식취득결정",
                "days_ago": 0,
                "dart_rcp_no": "20240101000002",
            }
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(8.0)

    def test_recent_negative_outweighs_old_positive(self):
        """오늘 악재(-0.7) > 30일 전 호재(+0.8) → 최종 보정값은 음수"""
        discs = [
            {
                "category": "유상증자결정",
                "title": "유상증자결정",
                "days_ago": 0,   # 가중치 1.0
                "dart_rcp_no": "rcp001",
            },
            {
                "category": "자기주식취득결정",
                "title": "자기주식취득결정",
                "days_ago": 30,  # 가중치 0.1 (최소)
                "dart_rcp_no": "rcp002",
            },
        ]
        result = disclosure_adjustment(discs)
        # 가중 평균: (-0.7×1.0 + 0.8×0.1) / (1.0 + 0.1) = (-0.7 + 0.08) / 1.1 ≈ -0.564
        # → × 10 ≈ -5.64
        assert result < 0.0

    def test_only_neutral_disclosures_returns_zero(self):
        """감성 점수 0.0인 공시만 있을 때 → 0.0"""
        discs = [
            {
                "category": "일반공시",
                "title": "신규 사업 검토 발표",
                "days_ago": 5,
                "dart_rcp_no": "rcp003",
            }
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(0.0)

    def test_result_clipped_to_plus_10(self):
        """극단적 호재 여러 건 → +10.0 클리핑"""
        discs = [
            {
                "category": "자기주식취득결정",
                "title": "흑자전환 자기주식취득결정",
                "days_ago": 0,
                "dart_rcp_no": f"rcp_{i}",
            }
            for i in range(20)
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(10.0)

    def test_result_clipped_to_minus_10(self):
        """극단적 악재 여러 건 → -10.0 클리핑"""
        discs = [
            {
                "category": "관리종목지정",
                "title": "적자전환 관리종목지정",
                "days_ago": 0,
                "dart_rcp_no": f"rcp_{i}",
            }
            for i in range(20)
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(-10.0)

    def test_time_decay_older_has_less_weight(self):
        """동일 공시라도 오래된 것일수록 가중치가 낮아야 한다."""
        discs_recent = [
            {
                "category": "유상증자결정",
                "title": "",
                "days_ago": 1,
                "dart_rcp_no": "rcp_r",
            }
        ]
        discs_old = [
            {
                "category": "유상증자결정",
                "title": "",
                "days_ago": 29,
                "dart_rcp_no": "rcp_o",
            }
        ]
        # 감성값이 같으면 abs 보정값도 같아야 하지만, 둘 다 단일 공시이므로
        # avg_sentiment는 동일 → adjustment는 동일. 하지만 둘을 합쳤을 때는 최근 것이 더 영향을 미쳐야 함.
        combined = [
            {
                "category": "유상증자결정",
                "title": "",
                "days_ago": 1,
                "dart_rcp_no": "rcp_r",
            },
            {
                "category": "자기주식취득결정",
                "title": "",
                "days_ago": 29,
                "dart_rcp_no": "rcp_o",
            },
        ]
        result = disclosure_adjustment(combined)
        # 최근 악재(-0.7, w=0.973)가 오래된 호재(+0.8, w=0.127)보다 더 영향을 미쳐야 함
        assert result < 0.0

    def test_days_ago_missing_defaults_to_zero(self):
        """days_ago 키가 없으면 0(오늘)으로 처리"""
        discs = [
            {
                "category": "자기주식취득결정",
                "title": "",
                "dart_rcp_no": "rcp_nd",
                # days_ago 없음
            }
        ]
        result = disclosure_adjustment(discs)
        assert result == pytest.approx(8.0)

    def test_return_type_is_float(self):
        """반환 타입이 float인지 확인"""
        result = disclosure_adjustment([])
        assert isinstance(result, float)

    def test_result_always_in_bounds(self):
        """다양한 입력에서 결과값이 -10.0 ~ +10.0 범위 내"""
        import random
        random.seed(42)
        categories = list(CATEGORY_SENTIMENT.keys()) + ["일반공시"]
        for _ in range(100):
            n = random.randint(0, 10)
            discs = [
                {
                    "category": random.choice(categories),
                    "title": "",
                    "days_ago": random.randint(0, 30),
                    "dart_rcp_no": f"rcp_{i}",
                }
                for i in range(n)
            ]
            result = disclosure_adjustment(discs)
            assert -10.0 <= result <= 10.0, f"범위 초과: {result}"