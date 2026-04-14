# Qwen3 로컬 LLM 통합 아이디어

> 현재 stock-recommender는 규칙 기반(사전 매핑, 키워드 매칭)으로 감성 분석을 수행한다.
> 로컬에 설치된 Qwen3를 활용하면 문맥 이해 기반의 더 정교한 분석과
> 자연어 출력 기능을 외부 API 비용 없이 추가할 수 있다.

---

## 연결 방식 (공통 전제)

Qwen3는 Ollama나 LM Studio로 띄우면 OpenAI 호환 엔드포인트를 제공한다.

```python
# utils/llm_client.py (신규)
import requests
from loguru import logger

OLLAMA_BASE = "http://localhost:11434"
MODEL_NAME  = "qwen3"          # ollama pull qwen3 로 내려받은 모델명

def call_llm(prompt: str, timeout: int = 15) -> str | None:
    """
    Ollama REST API 단일 호출 래퍼.
    타임아웃 또는 오류 시 None 반환 → 호출자가 fallback 처리.
    """
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning(f"LLM 호출 실패 (fallback 사용): {e}")
        return None
```

> **openai 라이브러리**를 쓰고 싶다면 `base_url="http://localhost:11434/v1"` 로 동일하게 연결된다.

---

## 아이디어 1 — 공시 감성 분석 고도화 (STEP E 대체/보완)

### 현재 한계

`disclosure_scorer.py`의 `score_single_disclosure()`는 카테고리 사전 매핑 + 키워드 매칭이라
사전에 없는 표현("대규모 계약 체결", "신약 임상 3상 성공" 등)은 0.0으로 처리된다.

### 통합 방식

```
[기존 규칙 기반 점수] → 0.0인 경우에만 LLM 호출 → 비용/속도 절감
```

```python
# scoring/disclosure_scorer.py 에 추가

def score_with_llm_fallback(category: str, title: str) -> float:
    """
    규칙 기반으로 0.0이 나올 때만 Qwen3에 판단 위임.
    LLM이 느리거나 실패하면 0.0 유지 (안전한 기본값).
    """
    rule_score = score_single_disclosure(category, title)
    if rule_score != 0.0:
        return rule_score      # 이미 사전에서 판단됨

    from src.utils.llm_client import call_llm

    prompt = f"""다음 한국 주식 공시를 읽고 주가에 미치는 영향을 -1.0~+1.0 숫자 하나로만 답하라.
양수 = 호재, 음수 = 악재, 0 = 중립 또는 판단 불가.
숫자 외 다른 텍스트는 절대 출력하지 말 것.

카테고리: {category}
제목: {title}
"""
    raw = call_llm(prompt, timeout=10)
    if raw is None:
        return 0.0
    try:
        return round(max(-1.0, min(1.0, float(raw))), 2)
    except ValueError:
        return 0.0
```

### 기대 효과

- 사전 미등록 공시(계약 체결, 임상 결과, 특허 등)에서 신호 포착
- 기존 규칙 기반 대비 커버리지 확장, 속도 영향 최소화

---

## 아이디어 2 — 추천 이유 자동 생성 (reason 컬럼 채우기)

### 현재 상태

`recommendations` 테이블의 `reason` 컬럼이 `None`으로 저장된다 (`main.py:389`).
Slack 알림도 숫자 나열에 그쳐 투자 판단 근거를 파악하기 어렵다.

### 통합 방식

```python
# main.py — run_daily() 내 Top 5 저장 루프에 추가

def generate_reason(r: ScoreResult, regime: str, rate_trend: str) -> str:
    """
    ScoreResult 수치를 요약해 Qwen3에 자연어 설명 요청.
    LLM 실패 시 규칙 기반 템플릿 문자열로 폴백.
    """
    from src.utils.llm_client import call_llm

    prompt = f"""아래는 한국 주식 종목 {r.code}의 오늘 스코어링 결과이다.
투자자가 이해할 수 있도록 추천 이유를 2~3문장으로 설명하라.
기술적·재무적·모멘텀 중 강점 위주로 서술하고, 시장 상태와 연결지어라.

- 시장 상태: {regime}
- 금리 트렌드: {rate_trend}
- 기술점수: {r.technical_score} (RSI={r.rsi_score}, MACD={r.macd_score})
- 재무점수: {r.fundamental_score} (PER={r.per_score}, ROE={r.roe_score})
- 모멘텀점수: {r.momentum_score} (거래량={r.volume_score}, 기관={r.inst_score})
- 최종점수: {r.adjusted_total_score}
"""
    result = call_llm(prompt, timeout=20)
    if result:
        return result

    # 폴백: 가장 높은 점수 부문 강조
    scores = {
        "기술적 분석": r.technical_score or 0,
        "재무 건전성": r.fundamental_score or 0,
        "모멘텀": r.momentum_score or 0,
    }
    top_area = max(scores, key=scores.get)
    return f"{top_area} 부문에서 높은 점수({scores[top_area]:.1f})를 기록. 시장 상태: {regime}."
```

### 기대 효과

- Slack 메시지 가독성 향상
- `recommendations.reason` 컬럼 실질적 활용
- 백테스트 리뷰 시 해당 날짜 추천 근거 빠르게 파악

---

## 아이디어 3 — 뉴스 감성 분석 (STEP F 구현 방법 선택지)

STEP F(`news_scorer.py`)는 아직 구현 전이다. Qwen3를 쓰면 키워드 사전 없이 바로 구현 가능하다.

### 옵션 A — 키워드 기반 (CLAUDE.md 설계 그대로)

```python
# 현재 CLAUDE.md에 명시된 방식
# POSITIVE_KEYWORDS / NEGATIVE_KEYWORDS 사전 매칭
```

### 옵션 B — Qwen3 배치 분석 (권장)

```python
# scoring/news_scorer.py 에 LLM 경로 추가

def news_adjustment_llm(news_titles: list[str]) -> float:
    """
    뉴스 제목 목록을 Qwen3에 한 번에 전달해 종합 감성 점수 반환.
    3건 미만이면 신뢰도 부족으로 0.0 반환 (기존 규칙과 동일).
    """
    if len(news_titles) < 3:
        return 0.0

    from src.utils.llm_client import call_llm

    titles_text = "\n".join(f"- {t}" for t in news_titles[:10])  # 최대 10건
    prompt = f"""아래는 한국 주식 종목과 관련된 최근 뉴스 제목 목록이다.
전체적인 주가 영향을 -1.0~+1.0 숫자 하나로만 답하라.
숫자 외 텍스트 절대 금지.

{titles_text}
"""
    raw = call_llm(prompt, timeout=15)
    if raw is None:
        return 0.0
    try:
        avg = float(raw)
        return round(max(-5.0, min(5.0, avg * 5)), 2)
    except ValueError:
        return 0.0
```

**옵션 B의 장점**: 키워드 미등록 표현("공급계약 연장", "FDA 승인", "수주 잭팟") 처리 가능

---

## 아이디어 4 — 일일 시장 브리핑 생성

### 개요

스코어링 파이프라인 완료 후, 당일 Market Regime·Top 5 결과를 요약한
자연어 시장 브리핑을 Slack으로 전송한다.

```python
# notification/slack_notifier.py 에 추가

def generate_market_brief(regime: str, top5: list[ScoreResult], rate_trend: str) -> str:
    from src.utils.llm_client import call_llm

    rec_summary = "\n".join(
        f"  #{r.rank} {r.code}: 총점={r.adjusted_total_score:.1f} "
        f"(기술={r.technical_score:.1f}/재무={r.fundamental_score:.1f}/모멘텀={r.momentum_score:.1f})"
        for r in top5
    )
    prompt = f"""오늘의 한국 주식 시장 상태와 추천 종목을 바탕으로
투자자에게 전달할 간결한 데일리 브리핑을 3~4문장으로 작성하라.
전문 투자 보고서 톤, 한국어.

시장 상태: {regime}
금리 트렌드: {rate_trend}
추천 종목:
{rec_summary}
"""
    result = call_llm(prompt, timeout=25)
    return result or f"오늘 시장 상태: {regime} | 추천 {len(top5)}종목 선정 완료."
```

### Slack 메시지 구성 (예시)

```
📊 [오늘의 종목 추천] 2026-04-13

🏛 시장 상태: CAUTIOUS_BULL (MA 상향 / 금리차 역전 경고)

[Qwen3 생성 브리핑]
오늘 코스피는 단기 상승 추세를 유지하고 있으나, 장단기 금리차 역전이
지속되며 경계 신호가 포착됩니다. 이에 재무 건전성이 높은 가치주 중심으로
방어적 포지션을 권장합니다. 기관 순매수가 집중된 반도체 섹터 종목이
상위권을 차지했습니다.

#1 005930 | 총점 78.4
   └ 추천 이유: [Qwen3 생성 텍스트]
...
```

---

## 아이디어 5 — 백테스트 결과 인사이트 생성

```python
# backtest/evaluator.py 에 추가 (선택)

def generate_backtest_insight(summary: dict) -> str:
    """
    백테스트 요약 통계를 LLM에게 전달해 개선 포인트 제안 요청.

    summary 예시:
    {
        "avg_alpha_1d": 0.12, "avg_alpha_5d": 0.45,
        "win_rate_5d": 0.62,
        "worst_regime": "BEAR",
        "best_sector": "반도체",
    }
    """
    from src.utils.llm_client import call_llm

    prompt = f"""아래는 주식 추천 시스템의 백테스트 성과 요약이다.
성과 개선을 위한 구체적인 제안 3가지를 bullet point로 작성하라. 한국어.

{summary}
"""
    return call_llm(prompt, timeout=30) or "백테스트 분석 완료 (LLM 응답 없음)"
```

---

## 통합 시 고려사항

### 성능

| 항목 | 영향 | 대응 방안 |
|---|---|---|
| LLM 응답 지연 | 종목당 +5~15초 | 규칙 기반 결과가 0.0인 경우에만 호출 |
| 350종목 전체 LLM 호출 | 너무 느림 | Top 20 필터링 후에만 LLM 적용 |
| Ollama 미실행 | 오류 | `call_llm`이 None 반환 → fallback 자동 적용 |

### 권장 적용 순서

```
1단계 (즉시 가능)  — 아이디어 2: 추천 이유 생성 (Top 5만 호출, 영향 최소)
2단계             — 아이디어 4: 일일 시장 브리핑 (1회 호출, 부담 없음)
3단계             — 아이디어 1: 공시 감성 fallback (규칙 기반 보완)
4단계 (STEP F)    — 아이디어 3: 뉴스 감성 LLM 버전 (배치 처리)
5단계             — 아이디어 5: 백테스트 인사이트 (필요 시)
```

### 환경 변수 추가 (.env)

```env
# Qwen3 로컬 LLM
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen3
LLM_TIMEOUT=15          # 초
LLM_ENABLED=true        # false로 설정하면 모든 LLM 호출 스킵
```

### config.py 추가 항목

```python
llm_base_url: str = "http://localhost:11434"
llm_model: str = "qwen3"
llm_timeout: int = 15
llm_enabled: bool = True
```

---

## 요약

| 아이디어 | 파일 | 난이도 | 즉시 효과 |
|---|---|---|---|
| 1. 공시 감성 fallback | `disclosure_scorer.py` + `llm_client.py` | 낮음 | 커버리지 확장 |
| 2. 추천 이유 생성 | `main.py` + `llm_client.py` | 낮음 | Slack 가독성 |
| 3. 뉴스 감성 LLM | `news_scorer.py` (STEP F 신규) | 중간 | 키워드 한계 극복 |
| 4. 일일 시장 브리핑 | `slack_notifier.py` + `llm_client.py` | 낮음 | 알림 품질 향상 |
| 5. 백테스트 인사이트 | `evaluator.py` | 낮음 | 개선 방향 제안 |

> **핵심 원칙**: LLM은 항상 보조 레이어로 동작하고 실패 시 기존 로직으로 폴백한다.
> 스코어링 파이프라인의 결정론적 동작을 해치지 않는다.