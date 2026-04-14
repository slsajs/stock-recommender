"""
backtest/insight_generator.py
BacktestSummary를 Qwen3(Ollama)에 전달하여 자연어 인사이트 보고서를 생성한다.

LLM 호출 실패 시 규칙 기반 폴백 텍스트를 자동 생성하므로
Ollama가 꺼져 있어도 항상 InsightReport를 반환한다.

출력:
  - InsightReport dataclass (메모리)
  - logs/backtest_insight_YYYY-MM-DD.md (파일)
  - Slack 메시지 포맷 문자열 (format_slack_message)

프롬프트 설계 원칙:
  1. 역할 지정: "한국 주식 퀀트 전략 분석 전문가" → 금융 맥락 유지
  2. 구조화 입력: 수치 블록으로 직렬화 → 자유형 서술보다 정확한 해석
  3. 섹션 헤더 강제: [전체평가] / [취약점] / [개선제안] / [긍정신호] → 파싱 용이
  4. 한국어 명시: 혼용 방지
  5. <think> 태그 필터링: Qwen3 thinking mode 출력 제거
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.backtest.summary_builder import BacktestSummary, PeriodStats, TimeSeriesPoint
from src.utils.llm_client import call_llm


# ─────────────────────────────────────────────
# 결과 데이터 클래스
# ─────────────────────────────────────────────

@dataclass
class InsightReport:
    """LLM 또는 규칙 기반 폴백으로 생성된 인사이트 보고서."""
    generated_at: str            # "2026-04-14 16:30"
    eval_period: str             # "2025-01-01 ~ 2026-04-14"
    total_recs: int

    overall_assessment: str      # 전체 성과 평가
    weak_points: str             # 취약 구간 / 패턴
    improvement_suggestions: str # 전략 개선 제안
    positive_signals: str        # 잘 작동한 부분

    llm_used: bool               # True=Qwen3 응답, False=규칙 기반 폴백


# ─────────────────────────────────────────────
# 인사이트 생성 클래스
# ─────────────────────────────────────────────

class BacktestInsightGenerator:
    """
    BacktestSummary → InsightReport 변환기.

    사용 예:
        generator = BacktestInsightGenerator()
        report = generator.generate(summary)
        filepath = save_insight_report(report)
    """

    # LLM 섹션 파싱용 헤더
    _HEADER_MAP: dict[str, str] = {
        "[전체평가]":  "overall",
        "[취약점]":    "weak",
        "[개선제안]":  "improve",
        "[긍정신호]":  "positive",
    }

    def generate(self, summary: BacktestSummary) -> InsightReport:
        """
        BacktestSummary를 LLM에 전달해 InsightReport를 생성한다.
        LLM 실패(타임아웃/연결오류/응답없음) 시 규칙 기반 폴백 텍스트 사용.
        """
        prompt = self._build_prompt(summary)
        raw = call_llm(prompt, timeout=60)   # 긴 응답 → timeout 넉넉히

        if raw:
            parsed = self._parse_response(raw)
            llm_used = True
            logger.info("LLM 인사이트 생성 완료")
        else:
            parsed = self._fallback_report(summary)
            llm_used = False
            logger.warning("LLM 호출 실패 — 규칙 기반 폴백 인사이트 사용")

        return InsightReport(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            eval_period=f"{summary.eval_start} ~ {summary.eval_end}",
            total_recs=summary.total_recommendations,
            overall_assessment=parsed.get("overall", "").strip(),
            weak_points=parsed.get("weak", "").strip(),
            improvement_suggestions=parsed.get("improve", "").strip(),
            positive_signals=parsed.get("positive", "").strip(),
            llm_used=llm_used,
        )

    # ── 프롬프트 구성 ─────────────────────────────────────

    def _build_prompt(self, s: BacktestSummary) -> str:
        """BacktestSummary를 섹션별 텍스트 블록으로 직렬화하여 프롬프트를 구성."""

        def fmt_period(p: PeriodStats | None) -> str:
            if p is None:
                return "데이터 없음"
            return (
                f"평균수익률={p.avg_return:+.2f}%, alpha={p.avg_alpha:+.2f}%, "
                f"승률={p.win_rate:.1%}, 벤치마크초과={p.beat_benchmark_rate:.1%}, "
                f"샘플={p.sample_count}건, "
                f"최대={p.best_return:+.2f}%, 최소={p.worst_return:+.2f}%, "
                f"변동성(σ)={p.std_dev:.2f}%"
            )

        p1  = s.period_stats.get(1)
        p5  = s.period_stats.get(5)
        p20 = s.period_stats.get(20)
        p60 = s.period_stats.get(60)

        # Regime 섹션
        if s.regime_stats:
            regime_lines = "\n".join(
                f"  - {r.regime}: alpha={r.avg_alpha_5d:+.2f}%, "
                f"승률={r.win_rate_5d:.1%} ({r.sample_count}건)"
                for r in s.regime_stats
            )
        else:
            regime_lines = "  - 데이터 없음"

        # 섹터 섹션 (상위/하위 3개)
        top3 = s.sector_stats[:3]
        bot3 = s.sector_stats[-3:] if len(s.sector_stats) >= 3 else s.sector_stats
        sector_lines = "  [상위 섹터]\n" + "\n".join(
            f"  - {se.sector}: alpha={se.avg_alpha_5d:+.2f}%, "
            f"승률={se.win_rate_5d:.1%} ({se.sample_count}건)"
            for se in top3
        )
        if bot3 and bot3 != top3:
            sector_lines += "\n  [하위 섹터]\n" + "\n".join(
                f"  - {se.sector}: alpha={se.avg_alpha_5d:+.2f}%, "
                f"승률={se.win_rate_5d:.1%} ({se.sample_count}건)"
                for se in bot3
            )

        # 월별 추이 섹션
        if s.monthly_trend:
            monthly_lines = "\n".join(
                f"  - {t.year_month}: alpha={t.avg_alpha_5d:+.2f}%, "
                f"승률={t.win_rate_5d:.1%} ({t.rec_count}건)"
                for t in s.monthly_trend
            )
        else:
            monthly_lines = "  - 데이터 없음"

        drawdown_str = (
            ", ".join(s.drawdown_periods) if s.drawdown_periods else "없음"
        )

        prompt = f"""당신은 한국 주식 퀀트 전략 분석 전문가입니다.
아래는 주식 추천 시스템의 백테스트 성과 요약 데이터입니다.
이를 분석하여 전략 개선을 위한 인사이트를 작성하십시오.

=== 평가 기간 및 규모 ===
- 평가 기간: {s.eval_start} ~ {s.eval_end}
- 총 추천 수: {s.total_recommendations}건

=== 보유 기간별 성과 ===
- 1일  후: {fmt_period(p1)}
- 5일  후: {fmt_period(p5)}
- 20일 후: {fmt_period(p20)}
- 60일 후: {fmt_period(p60)}

=== 시장 상태(Regime)별 성과 (5일 기준) ===
{regime_lines}
- 최우수 Regime: {s.best_regime}
- 최취약 Regime: {s.worst_regime}

=== 섹터별 성과 (5일 기준) ===
{sector_lines}
- 최우수 섹터: {s.best_sector}
- 최취약 섹터: {s.worst_sector}

=== 월별 성과 추이 (5일 기준) ===
{monthly_lines}
- 연속 손실 월: {s.consecutive_losing_months}개월
- 심각 손실 구간(alpha < -1%): {drawdown_str}

=== 스코어 품질 분포 ===
- 고점수(>70) 추천 승률: {s.high_score_win_rate:.1%}
- 저점수(≤50) 추천 승률: {s.low_score_win_rate:.1%}

=== 출력 형식 (반드시 아래 형식 준수, 한국어) ===

[전체평가]
(전반적인 전략 성과를 2~3문장으로 요약. 벤치마크 대비 특징 포함.)

[취약점]
(성과가 저하되는 패턴/조건을 3가지 이하 bullet로 서술. 데이터 근거 포함.)
-
-
-

[개선제안]
(구체적이고 실행 가능한 전략 수정 방향 3가지를 bullet로 작성.
 파라미터, 필터 조건, 가중치 등 코드 수준에서 변경 가능한 것 위주.)
-
-
-

[긍정신호]
(잘 작동한 부분을 2가지 이하 bullet로 서술. 유지해야 할 강점.)
-
-
"""
        return prompt

    # ── LLM 응답 파싱 ────────────────────────────────────

    def _parse_response(self, raw: str) -> dict[str, str]:
        """
        LLM 응답에서 섹션 헤더([전체평가] 등)를 기준으로 텍스트를 분리한다.
        <think>...</think> 블록(Qwen3 thinking mode 출력)은 제거한다.
        파싱 실패 시 전체 텍스트를 'overall'에 저장.
        """
        sections: dict[str, str] = {k: "" for k in self._HEADER_MAP.values()}
        current_key: str | None = None
        buffer: list[str] = []
        in_think_block = False

        for line in raw.splitlines():
            stripped = line.strip()

            # <think> 블록 토글 처리
            if "<think>" in stripped:
                in_think_block = True
            if "</think>" in stripped:
                in_think_block = False
                continue
            if in_think_block:
                continue

            # 섹션 헤더 감지
            if stripped in self._HEADER_MAP:
                if current_key is not None and buffer:
                    sections[current_key] = "\n".join(buffer).strip()
                current_key = self._HEADER_MAP[stripped]
                buffer = []
            elif current_key is not None:
                buffer.append(line)

        # 마지막 섹션 저장
        if current_key is not None and buffer:
            sections[current_key] = "\n".join(buffer).strip()

        # 섹션이 하나도 파싱되지 않으면 전체 텍스트를 overall에 담음
        if not any(sections.values()):
            logger.warning("LLM 응답 섹션 파싱 실패 — 전체 텍스트를 overall에 저장")
            sections["overall"] = raw.strip()

        return sections

    # ── 규칙 기반 폴백 ────────────────────────────────────

    def _fallback_report(self, s: BacktestSummary) -> dict[str, str]:
        """
        LLM 호출 실패 시 수치 기반 텍스트를 자동 생성한다.
        단순하지만 핵심 수치는 모두 포함한다.
        """
        p5 = s.period_stats.get(5)
        alpha_5d = p5.avg_alpha if p5 else 0.0
        wr_5d    = p5.win_rate  if p5 else 0.0
        sample   = p5.sample_count if p5 else 0

        overall = (
            f"평가 기간 {s.eval_start} ~ {s.eval_end} ({s.total_recommendations}건 추천). "
            f"5일 기준 평균 alpha {alpha_5d:+.2f}%, 승률 {wr_5d:.1%} ({sample}건 샘플). "
            f"최우수 Regime: {s.best_regime} / 최취약 Regime: {s.worst_regime}."
        )

        weak_items = [f"- {s.worst_regime} 구간에서 성과 저조"]
        if s.worst_sector != "N/A":
            weak_items.append(f"- {s.worst_sector} 섹터 추천 부진")
        if s.consecutive_losing_months >= 2:
            weak_items.append(
                f"- 최근 {s.consecutive_losing_months}개월 연속 alpha 음수"
            )
        weak = "\n".join(weak_items)

        improve_items = [
            f"- {s.worst_regime} 구간 필터 조건 재검토",
        ]
        if s.worst_sector != "N/A":
            improve_items.append(f"- {s.worst_sector} 섹터 추천 비중 축소 고려")
        if s.high_score_win_rate > 0 and s.low_score_win_rate > 0:
            improve_items.append(
                f"- 고점수(>70) 승률 {s.high_score_win_rate:.1%} vs "
                f"저점수(≤50) 승률 {s.low_score_win_rate:.1%} — 추천 임계값 상향 검토"
            )
        else:
            improve_items.append("- 스코어 분포 데이터 부족 — 추가 백테스트 실행 권장")
        improve = "\n".join(improve_items)

        positive_items = [f"- {s.best_regime} 구간에서 우수한 성과"]
        if s.best_sector != "N/A":
            positive_items.append(f"- {s.best_sector} 섹터 추천 강점 유지")
        positive = "\n".join(positive_items)

        return {
            "overall":  overall,
            "weak":     weak,
            "improve":  improve,
            "positive": positive,
        }


# ─────────────────────────────────────────────
# 보고서 저장 / 포맷 유틸리티
# ─────────────────────────────────────────────

def save_insight_report(
    report: InsightReport,
    output_dir: str = "logs",
) -> str:
    """
    InsightReport를 마크다운 파일로 저장하고 파일 경로를 반환한다.

    파일명: backtest_insight_YYYY-MM-DD.md
    경로:   {output_dir}/backtest_insight_YYYY-MM-DD.md
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    date_str = report.generated_at[:10]
    filename = f"backtest_insight_{date_str}.md"
    filepath = os.path.join(output_dir, filename)

    generation_method = "Qwen3 LLM" if report.llm_used else "규칙 기반 폴백"

    content = f"""# 백테스트 인사이트 보고서

| 항목 | 값 |
|---|---|
| 생성일시 | {report.generated_at} |
| 평가 기간 | {report.eval_period} |
| 총 추천 수 | {report.total_recs}건 |
| 생성 방법 | {generation_method} |

---

## 전체 성과 평가

{report.overall_assessment}

---

## 취약점 분석

{report.weak_points}

---

## 전략 개선 제안

{report.improvement_suggestions}

---

## 잘 작동한 부분

{report.positive_signals}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"인사이트 보고서 저장 완료 | {filepath}")
    return filepath


def format_slack_message(report: InsightReport) -> str:
    """
    InsightReport를 Slack 메시지 형식으로 변환한다.
    Slack 메시지 길이 제한을 고려하여 핵심만 요약.
    """
    generation_method = "Qwen3 LLM" if report.llm_used else "규칙 기반"
    date_str = report.generated_at[:10]

    return (
        f"*📊 백테스트 인사이트 보고서* ({generation_method})\n"
        f"평가 기간: {report.eval_period} | 총 {report.total_recs}건\n\n"
        f"*전체 평가*\n{report.overall_assessment}\n\n"
        f"*개선 제안*\n{report.improvement_suggestions}\n\n"
        f"_전체 보고서: logs/backtest_insight_{date_str}.md_"
    )
