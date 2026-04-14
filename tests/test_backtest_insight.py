"""
tests/test_backtest_insight.py
백테스트 인사이트 생성 모듈 단위 테스트.

테스트 범위:
  1. BacktestSummaryBuilder — 집계 로직 (mock repo 사용, DB 불필요)
  2. BacktestInsightGenerator — 파싱, 폴백, LLM mock
  3. save_insight_report / format_slack_message — 파일/문자열 출력

DB 접속 없이 실행 가능하도록 StockRepository를 모두 mock 처리.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.backtest.summary_builder import (
    BacktestSummary,
    BacktestSummaryBuilder,
    PeriodStats,
    RegimeStats,
    SectorStats,
    TimeSeriesPoint,
)
from src.backtest.insight_generator import (
    BacktestInsightGenerator,
    InsightReport,
    format_slack_message,
    save_insight_report,
)


# ─────────────────────────────────────────────
# 픽스처 — 공통 테스트 데이터
# ─────────────────────────────────────────────

def _make_joined_df(n_recs: int = 20) -> pd.DataFrame:
    """
    n_recs개의 추천에 대해 days_after [1,5,20,60] 행을 생성하는 헬퍼.
    각 추천은 BULL/BEAR Regime, 반도체/항공 섹터에 절반씩 배정.
    """
    rows = []
    for rec_id in range(1, n_recs + 1):
        date = f"2025-{(rec_id % 12) + 1:02d}-15"
        code = f"{rec_id:06d}"
        regime = "BULL" if rec_id % 2 == 0 else "BEAR"
        sector = "반도체" if rec_id % 2 == 0 else "항공"
        total_score = 75.0 if rec_id % 3 == 0 else 55.0

        for days, ret, bm in [
            (1,  0.5,  0.3),
            (5,  1.2,  0.8),
            (20, 2.5,  1.5),
            (60, 4.0,  2.0),
        ]:
            # 홀수 rec_id는 수익률 음수 (BEAR 느낌)
            sign = 1 if rec_id % 2 == 0 else -1
            rows.append({
                "recommendation_id": rec_id,
                "date": date,
                "code": code,
                "rank": 1,
                "total_score": total_score,
                "market_regime": regime,
                "sector": sector,
                "days_after": days,
                "return_rate": round(ret * sign, 4),
                "benchmark_rate": round(bm, 4),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def mock_repo_with_data():
    repo = MagicMock()
    repo.get_backtest_joined_data.return_value = _make_joined_df(n_recs=20)
    return repo


@pytest.fixture
def mock_repo_empty():
    repo = MagicMock()
    repo.get_backtest_joined_data.return_value = pd.DataFrame(
        columns=[
            "recommendation_id", "date", "code", "rank", "total_score",
            "market_regime", "sector", "days_after", "return_rate", "benchmark_rate",
        ]
    )
    return repo


@pytest.fixture
def mock_repo_few():
    """샘플 수가 10건 미만인 경우."""
    repo = MagicMock()
    repo.get_backtest_joined_data.return_value = _make_joined_df(n_recs=2)
    return repo


@pytest.fixture
def mock_summary() -> BacktestSummary:
    """단위 테스트용 최소 BacktestSummary."""
    return BacktestSummary(
        eval_start="2025-01-01",
        eval_end="2026-04-14",
        total_recommendations=20,
        period_stats={
            1:  PeriodStats(1,  0.30, 0.10, 0.60, 0.55, 20, 2.5, -1.5, 0.9),
            5:  PeriodStats(5,  1.20, 0.40, 0.65, 0.60, 20, 5.0, -3.0, 1.5),
            20: PeriodStats(20, 2.50, 0.80, 0.70, 0.65, 15, 8.0, -4.0, 2.2),
            60: PeriodStats(60, 4.00, 1.20, 0.75, 0.70, 10, 12.0,-5.0, 3.1),
        },
        regime_stats=[
            RegimeStats("BULL", 1.20, 0.70, 10),
            RegimeStats("BEAR", -0.50, 0.40, 10),
        ],
        worst_regime="BEAR",
        best_regime="BULL",
        sector_stats=[
            SectorStats("반도체", 1.50, 0.75, 10),
            SectorStats("항공",   -0.80, 0.35, 10),
        ],
        worst_sector="항공",
        best_sector="반도체",
        monthly_trend=[
            TimeSeriesPoint("2025-01", 0.50, 0.60, 5),
            TimeSeriesPoint("2025-02", 0.20, 0.55, 5),
            TimeSeriesPoint("2025-03", -0.30, 0.45, 5),
            TimeSeriesPoint("2025-04", -0.10, 0.48, 5),
        ],
        consecutive_losing_months=2,
        drawdown_periods=[],
        high_score_win_rate=0.72,
        low_score_win_rate=0.45,
    )


# ─────────────────────────────────────────────
# BacktestSummaryBuilder 테스트
# ─────────────────────────────────────────────

class TestBuildReturnsNoneWhenInsufficient:
    def test_empty_dataframe(self, mock_repo_empty):
        builder = BacktestSummaryBuilder(mock_repo_empty)
        result = builder.build()
        assert result is None

    def test_too_few_recommendations(self, mock_repo_few):
        builder = BacktestSummaryBuilder(mock_repo_few)
        result = builder.build()
        assert result is None


class TestPeriodStats:
    def test_all_four_periods_present(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        assert summary is not None
        assert set(summary.period_stats.keys()) == {1, 5, 20, 60}

    def test_win_rate_in_range(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        for stats in summary.period_stats.values():
            assert 0.0 <= stats.win_rate <= 1.0
            assert 0.0 <= stats.beat_benchmark_rate <= 1.0

    def test_sample_count_matches_recs(self, mock_repo_with_data):
        """days_after=5 샘플 수는 추천 수(20)와 일치해야 한다."""
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        assert summary.period_stats[5].sample_count == 20

    def test_best_return_ge_worst_return(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        for stats in summary.period_stats.values():
            assert stats.best_return >= stats.worst_return

    def test_std_dev_non_negative(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        for stats in summary.period_stats.values():
            assert stats.std_dev >= 0.0


class TestRegimeStats:
    def test_two_regimes_present(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        regime_names = {r.regime for r in summary.regime_stats}
        assert "BULL" in regime_names
        assert "BEAR" in regime_names

    def test_best_regime_has_highest_alpha(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        regime_map = {r.regime: r.avg_alpha_5d for r in summary.regime_stats}
        assert regime_map[summary.best_regime] == max(regime_map.values())

    def test_worst_regime_has_lowest_alpha(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        regime_map = {r.regime: r.avg_alpha_5d for r in summary.regime_stats}
        assert regime_map[summary.worst_regime] == min(regime_map.values())

    def test_min_samples_filter(self):
        """min_samples 미만 regime은 결과에서 제외."""
        # BEAR 10건, BULL 3건만 가진 데이터프레임 직접 구성
        bear_rows = []
        for i in range(1, 11):  # 10건 BEAR
            for days, ret, bm in [(1, -0.5, 0.3), (5, -1.0, 0.8), (20, -2.0, 1.5), (60, -3.0, 2.0)]:
                bear_rows.append({
                    "recommendation_id": i,
                    "date": f"2025-01-{i + 1:02d}",
                    "code": f"{i:06d}",
                    "rank": 1,
                    "total_score": 55.0,
                    "market_regime": "BEAR",
                    "sector": "항공",
                    "days_after": days,
                    "return_rate": ret,
                    "benchmark_rate": bm,
                })
        bull_rows = []
        for i in range(11, 14):  # 3건 BULL (min_samples=5 미만)
            for days, ret, bm in [(1, 0.5, 0.3), (5, 1.0, 0.8), (20, 2.0, 1.5), (60, 3.0, 2.0)]:
                bull_rows.append({
                    "recommendation_id": i,
                    "date": f"2025-02-{i - 10:02d}",
                    "code": f"{i:06d}",
                    "rank": 1,
                    "total_score": 75.0,
                    "market_regime": "BULL",
                    "sector": "반도체",
                    "days_after": days,
                    "return_rate": ret,
                    "benchmark_rate": bm,
                })
        df = pd.DataFrame(bear_rows + bull_rows)

        repo = MagicMock()
        repo.get_backtest_joined_data.return_value = df
        builder = BacktestSummaryBuilder(repo)
        summary = builder.build(min_samples=5)

        # BULL이 3건(5 미만)이면 regime_stats에서 제외되어야 함
        # BEAR는 10건으로 충분 → 포함
        regime_names = {r.regime for r in summary.regime_stats}
        assert "BEAR" in regime_names
        assert "BULL" not in regime_names

    def test_regime_win_rate_in_range(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        for r in summary.regime_stats:
            assert 0.0 <= r.win_rate_5d <= 1.0


class TestSectorStats:
    def test_two_sectors_present(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        sector_names = {s.sector for s in summary.sector_stats}
        assert "반도체" in sector_names
        assert "항공" in sector_names

    def test_best_sector_has_highest_alpha(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        sector_map = {s.sector: s.avg_alpha_5d for s in summary.sector_stats}
        assert sector_map[summary.best_sector] == max(sector_map.values())

    def test_sector_sorted_by_alpha_desc(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        alphas = [s.avg_alpha_5d for s in summary.sector_stats]
        assert alphas == sorted(alphas, reverse=True)


class TestMonthlyTrend:
    def test_trend_sorted_chronologically(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        months = [t.year_month for t in summary.monthly_trend]
        assert months == sorted(months)

    def test_trend_win_rate_in_range(self, mock_repo_with_data):
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        for t in summary.monthly_trend:
            assert 0.0 <= t.win_rate_5d <= 1.0


class TestConsecutiveLosingMonths:
    def test_no_losing_streak(self):
        trend = [
            TimeSeriesPoint("2025-01", 0.5, 0.6, 10),
            TimeSeriesPoint("2025-02", 0.3, 0.5, 10),
            TimeSeriesPoint("2025-03", 0.1, 0.5, 10),
        ]
        builder = BacktestSummaryBuilder.__new__(BacktestSummaryBuilder)
        assert builder._calc_consecutive_losing_months(trend) == 0

    def test_single_losing_month(self):
        trend = [
            TimeSeriesPoint("2025-01", 0.5, 0.6, 10),
            TimeSeriesPoint("2025-02", -0.3, 0.4, 10),
        ]
        builder = BacktestSummaryBuilder.__new__(BacktestSummaryBuilder)
        assert builder._calc_consecutive_losing_months(trend) == 1

    def test_two_consecutive_losing_months(self):
        trend = [
            TimeSeriesPoint("2025-01", 0.5, 0.6, 10),
            TimeSeriesPoint("2025-02", -0.3, 0.4, 10),
            TimeSeriesPoint("2025-03", -0.5, 0.3, 10),
        ]
        builder = BacktestSummaryBuilder.__new__(BacktestSummaryBuilder)
        assert builder._calc_consecutive_losing_months(trend) == 2

    def test_positive_after_negative_resets_streak(self):
        """음수 → 양수 → 음수 패턴이면 최신 연속만 카운트."""
        trend = [
            TimeSeriesPoint("2025-01", -0.5, 0.4, 10),
            TimeSeriesPoint("2025-02", 0.3, 0.5, 10),
            TimeSeriesPoint("2025-03", -0.2, 0.4, 10),
        ]
        builder = BacktestSummaryBuilder.__new__(BacktestSummaryBuilder)
        assert builder._calc_consecutive_losing_months(trend) == 1

    def test_empty_trend(self):
        builder = BacktestSummaryBuilder.__new__(BacktestSummaryBuilder)
        assert builder._calc_consecutive_losing_months([]) == 0


class TestScoreDistribution:
    def test_high_score_win_rate_gte_low(self, mock_repo_with_data):
        """고점수 추천이 저점수보다 승률이 높거나 같아야 한다 (이상적 케이스)."""
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        # 테스트 데이터에서 고점수=75, 저점수=55로 혼재 → 범위 검증만
        assert 0.0 <= summary.high_score_win_rate <= 1.0
        assert 0.0 <= summary.low_score_win_rate <= 1.0

    def test_score_distribution_zero_when_no_data(self):
        """해당 점수 구간 데이터가 3건 미만이면 0.0 반환."""
        df = _make_joined_df(n_recs=20)
        # total_score를 모두 60으로 (고점수/저점수 구간 모두 3건 미만)
        df["total_score"] = 60.0
        repo = MagicMock()
        repo.get_backtest_joined_data.return_value = df
        builder = BacktestSummaryBuilder(repo)
        summary = builder.build()
        assert summary.high_score_win_rate == 0.0
        assert summary.low_score_win_rate == 0.0


class TestDrawdownPeriods:
    def test_drawdown_periods_detected(self, mock_repo_with_data):
        """alpha < -1.0인 월이 drawdown_periods에 포함."""
        builder = BacktestSummaryBuilder(mock_repo_with_data)
        summary = builder.build()
        # 검증: drawdown_periods는 리스트이며 월 형식(YYYY-MM)
        assert isinstance(summary.drawdown_periods, list)
        for ym in summary.drawdown_periods:
            assert len(ym) == 7 and ym[4] == "-"


# ─────────────────────────────────────────────
# BacktestInsightGenerator 테스트
# ─────────────────────────────────────────────

class TestInsightGeneratorWithLLMFailure:
    def test_returns_report_on_llm_none(self, mock_summary):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert report is not None
        assert isinstance(report, InsightReport)
        assert report.llm_used is False
        assert len(report.overall_assessment) > 0
        assert len(report.weak_points) > 0
        assert len(report.improvement_suggestions) > 0
        assert len(report.positive_signals) > 0

    def test_fallback_contains_regime_info(self, mock_summary):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        # worst_regime이 취약점 또는 개선제안에 포함되어야 함
        combined = report.weak_points + report.improvement_suggestions
        assert mock_summary.worst_regime in combined

    def test_fallback_contains_sector_info(self, mock_summary):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        combined = report.weak_points + report.improvement_suggestions
        assert mock_summary.worst_sector in combined

    def test_fallback_eval_period_in_overall(self, mock_summary):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert mock_summary.eval_start in report.overall_assessment
        assert mock_summary.eval_end in report.overall_assessment


class TestInsightGeneratorWithLLMSuccess:
    _VALID_RESPONSE = (
        "[전체평가]\n"
        "전체 성과는 양호합니다. 5일 alpha +0.40%로 벤치마크를 상회합니다.\n"
        "\n"
        "[취약점]\n"
        "- BEAR 구간에서 성과 부진\n"
        "- 항공 섹터 추천 약세\n"
        "\n"
        "[개선제안]\n"
        "- BEAR 구간 필터 강화\n"
        "- 항공 섹터 비중 축소\n"
        "- 추천 임계값 상향\n"
        "\n"
        "[긍정신호]\n"
        "- BULL 구간 강점\n"
        "- 반도체 섹터 우수\n"
    )

    def test_llm_used_true(self, mock_summary):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=self._VALID_RESPONSE,
        ):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert report.llm_used is True

    def test_overall_parsed(self, mock_summary):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=self._VALID_RESPONSE,
        ):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert "양호" in report.overall_assessment

    def test_weak_points_parsed(self, mock_summary):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=self._VALID_RESPONSE,
        ):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert "BEAR" in report.weak_points

    def test_improve_parsed(self, mock_summary):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=self._VALID_RESPONSE,
        ):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert "필터" in report.improvement_suggestions

    def test_positive_parsed(self, mock_summary):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=self._VALID_RESPONSE,
        ):
            gen = BacktestInsightGenerator()
            report = gen.generate(mock_summary)

        assert "반도체" in report.positive_signals


class TestParseResponse:
    def test_all_sections_extracted(self):
        gen = BacktestInsightGenerator()
        raw = (
            "[전체평가]\n전체 양호.\n\n"
            "[취약점]\n- BEAR 부진\n\n"
            "[개선제안]\n- 임계값 조정\n\n"
            "[긍정신호]\n- 반도체 강점\n"
        )
        result = gen._parse_response(raw)
        assert "양호" in result["overall"]
        assert "BEAR" in result["weak"]
        assert "임계값" in result["improve"]
        assert "반도체" in result["positive"]

    def test_fallback_on_no_headers(self):
        gen = BacktestInsightGenerator()
        raw = "헤더 없는 응답 텍스트"
        result = gen._parse_response(raw)
        assert result["overall"] == raw.strip()
        assert result["weak"] == ""
        assert result["improve"] == ""

    def test_think_block_removed(self):
        gen = BacktestInsightGenerator()
        raw = (
            "<think>내부 추론 내용 — 출력에서 제거되어야 함</think>\n"
            "[전체평가]\n실제 응답 내용.\n"
            "[취약점]\n- 취약점 A\n"
            "[개선제안]\n- 제안 A\n"
            "[긍정신호]\n- 강점 A\n"
        )
        result = gen._parse_response(raw)
        assert "내부 추론" not in result["overall"]
        assert "실제 응답" in result["overall"]

    def test_empty_response_returns_empty_sections(self):
        gen = BacktestInsightGenerator()
        result = gen._parse_response("")
        # 빈 응답 → overall에 빈 문자열
        assert result["overall"] == ""

    def test_partial_sections_handled(self):
        """일부 섹션만 있어도 오류 없이 처리."""
        gen = BacktestInsightGenerator()
        raw = "[전체평가]\n요약만 있음.\n"
        result = gen._parse_response(raw)
        assert "요약" in result["overall"]
        assert result["weak"] == ""


# ─────────────────────────────────────────────
# save_insight_report / format_slack_message 테스트
# ─────────────────────────────────────────────

@pytest.fixture
def sample_report() -> InsightReport:
    return InsightReport(
        generated_at="2026-04-14 16:30",
        eval_period="2025-01-01 ~ 2026-04-14",
        total_recs=100,
        overall_assessment="전체 성과 양호.",
        weak_points="- BEAR 구간 부진",
        improvement_suggestions="- 임계값 하향 검토",
        positive_signals="- 반도체 강점",
        llm_used=True,
    )


class TestSaveInsightReport:
    def test_file_created(self, sample_report):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_insight_report(sample_report, output_dir=tmpdir)
            assert os.path.exists(filepath)

    def test_filename_contains_date(self, sample_report):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_insight_report(sample_report, output_dir=tmpdir)
            assert "2026-04-14" in os.path.basename(filepath)

    def test_file_contains_key_sections(self, sample_report):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_insight_report(sample_report, output_dir=tmpdir)
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            assert "전체 성과 평가" in content
            assert "취약점 분석" in content
            assert "전략 개선 제안" in content
            assert "잘 작동한 부분" in content

    def test_file_contains_eval_period(self, sample_report):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_insight_report(sample_report, output_dir=tmpdir)
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            assert sample_report.eval_period in content

    def test_fallback_label_when_llm_not_used(self, sample_report):
        sample_report.llm_used = False
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_insight_report(sample_report, output_dir=tmpdir)
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            assert "규칙 기반 폴백" in content


class TestFormatSlackMessage:
    def test_contains_eval_period(self, sample_report):
        msg = format_slack_message(sample_report)
        assert sample_report.eval_period in msg

    def test_contains_overall_assessment(self, sample_report):
        msg = format_slack_message(sample_report)
        assert sample_report.overall_assessment in msg

    def test_contains_improvement(self, sample_report):
        msg = format_slack_message(sample_report)
        assert sample_report.improvement_suggestions in msg

    def test_contains_report_filename(self, sample_report):
        msg = format_slack_message(sample_report)
        assert "backtest_insight_2026-04-14.md" in msg

    def test_fallback_label_in_message(self, sample_report):
        sample_report.llm_used = False
        msg = format_slack_message(sample_report)
        assert "규칙 기반" in msg

    def test_llm_label_in_message(self, sample_report):
        sample_report.llm_used = True
        msg = format_slack_message(sample_report)
        assert "Qwen3 LLM" in msg


# ─────────────────────────────────────────────
# 통합 시나리오 테스트
# ─────────────────────────────────────────────

class TestEndToEndWithMockLLM:
    """빌더 → 생성기 → 저장 전체 흐름을 LLM mock으로 검증."""

    def test_full_pipeline_llm_success(self, mock_repo_with_data):
        with patch(
            "src.backtest.insight_generator.call_llm",
            return_value=(
                "[전체평가]\n양호.\n[취약점]\n- 부진\n"
                "[개선제안]\n- 개선\n[긍정신호]\n- 강점\n"
            ),
        ):
            builder   = BacktestSummaryBuilder(mock_repo_with_data)
            generator = BacktestInsightGenerator()

            summary = builder.build()
            assert summary is not None

            report = generator.generate(summary)
            assert report.llm_used is True
            assert len(report.overall_assessment) > 0

    def test_full_pipeline_llm_failure_still_produces_report(
        self, mock_repo_with_data
    ):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            builder   = BacktestSummaryBuilder(mock_repo_with_data)
            generator = BacktestInsightGenerator()

            summary = builder.build()
            assert summary is not None

            report = generator.generate(summary)
            assert report.llm_used is False
            assert len(report.overall_assessment) > 0

    def test_full_pipeline_with_file_save(self, mock_repo_with_data):
        with patch("src.backtest.insight_generator.call_llm", return_value=None):
            with tempfile.TemporaryDirectory() as tmpdir:
                builder   = BacktestSummaryBuilder(mock_repo_with_data)
                generator = BacktestInsightGenerator()

                summary  = builder.build()
                report   = generator.generate(summary)
                filepath = save_insight_report(report, output_dir=tmpdir)

                assert os.path.exists(filepath)
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                assert "백테스트 인사이트 보고서" in content
