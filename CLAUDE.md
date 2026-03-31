# Stock Recommender — Claude Code 개발 지시서

> 이 문서는 Claude Code가 프로젝트를 구현할 때 참조하는 **단일 소스 오브 트루스(Single Source of Truth)**입니다.
> 모든 구현 판단은 이 문서를 기준으로 합니다.

---

## 1. 프로젝트 개요

### 한 줄 정의

매일 장마감 후 코스피200 + 코스닥150 (약 350개) 종목을 스코어링하여 상위 5개 종목을 추천하는 Python 애플리케이션.

### 핵심 공식

```
최종점수 = 기술점수(가변%) + 재무점수(40%) + 모멘텀점수(가변%)
→ 기술/모멘텀 가중치는 Market Regime에 따라 동적 조절
```

### 기술 스택

| 항목 | 선택 | 버전                     |
|---|---|------------------------|
| 언어 | Python | 3.13+                  |
| 패키지 관리 | poetry | 최신                     |
| DB | PostgreSQL + TimescaleDB | PG 15+, TimescaleDB 최신 |
| 캐시 | Redis | 7+                     |
| IDE | PyCharm / IntelliJ | -                      |
| 컨테이너 | Docker Compose | -                      |

### 제약 조건

- **Python only** — API 서버(Spring Boot), 프론트엔드(React)는 현재 단계에서 구현하지 않는다.
- **MVP 우선** — 완벽한 기능보다 동작하는 파이프라인을 우선한다.
- **외부 크롤링 금지** — 네이버금융 크롤링은 하지 않는다. 데이터 소스는 pykrx, DART API, KRX만 사용한다.

---

## 2. 프로젝트 구조

```
stock-recommender/
├── pyproject.toml
├── docker-compose.yml
├── .env.example                  # API 키, DB 접속 정보 템플릿
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── main.py                   # 엔트리포인트 — 스케줄러 실행
│   ├── config.py                 # 환경변수 로딩 (pydantic-settings)
│   │
│   ├── collector/                # 데이터 수집 레이어
│   │   ├── __init__.py
│   │   ├── price_collector.py    # pykrx — 주가, 거래량, 시총
│   │   ├── finance_collector.py  # DART API — 재무제표
│   │   ├── investor_collector.py # pykrx — 투자자별 매매동향
│   │   ├── disclosure_collector.py # DART API — 공시 (감성분석 없이 저장만)
│   │   └── index_collector.py    # pykrx — 코스피 지수 (Market Regime 판단용)
│   │
│   ├── scoring/                  # 스코어링 엔진
│   │   ├── __init__.py
│   │   ├── base.py               # BaseScorer ABC, ScoreResult dataclass
│   │   ├── technical.py          # RSI, MACD, 볼린저밴드
│   │   ├── fundamental.py        # PER, PBR, ROE, 부채비율 (섹터 상대비교)
│   │   ├── momentum.py           # 거래량 급증, 기관 순매수, 52주 신고가
│   │   ├── market_regime.py      # 코스피 MA20/MA60 기반 시장 상태 판단
│   │   ├── aggregator.py         # 가중합 → 최종점수 → 상위 5개
│   │   └── filters.py            # 추천 제외 필터 (관리종목, 거래정지, 신규상장 등)
│   │
│   ├── backtest/                 # 백테스트
│   │   ├── __init__.py
│   │   └── evaluator.py          # 추천 후 1/5/20/60일 수익률 계산
│   │
│   ├── db/                       # 데이터 액세스
│   │   ├── __init__.py
│   │   ├── connection.py         # psycopg2 커넥션 풀
│   │   ├── repository.py         # 쿼리 함수 모음
│   │   └── schema.sql            # DDL (테이블 생성 SQL 전체)
│   │
│   ├── notification/             # 알림 (5단계)
│   │   ├── __init__.py
│   │   └── slack_notifier.py     # Slack Incoming Webhook
│   │
│   └── utils/
│       ├── __init__.py
│       └── logger.py             # loguru 설정
│
└── tests/
    ├── __init__.py
    ├── test_technical.py
    ├── test_fundamental.py
    ├── test_momentum.py
    ├── test_market_regime.py
    ├── test_filters.py
    └── test_aggregator.py
```

### 파일 생성 순서

> 반드시 아래 순서대로 구현한다. 이전 단계의 테스트가 통과해야 다음 단계로 넘어간다.

1. `docker-compose.yml` → `config.py` → `db/connection.py` → `db/schema.sql`
2. `collector/price_collector.py` → `collector/investor_collector.py` → `collector/index_collector.py`
3. `collector/finance_collector.py` → `collector/disclosure_collector.py`
4. `scoring/base.py` → `scoring/market_regime.py` → `scoring/filters.py`
5. `scoring/technical.py` → `scoring/fundamental.py` → `scoring/momentum.py`
6. `scoring/aggregator.py` → `main.py` (스케줄러)
7. `backtest/evaluator.py`
8. `notification/slack_notifier.py`

---

## 3. DB 스키마

아래 DDL을 `db/schema.sql`에 그대로 사용한다.

```sql
-- ============================================
-- 종목 마스터
-- ============================================
CREATE TABLE stocks (
    code            VARCHAR(10)  PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    market          VARCHAR(10)  NOT NULL,          -- KOSPI / KOSDAQ
    sector          VARCHAR(50),
    industry        VARCHAR(100),
    listed_at       DATE,
    is_active       BOOLEAN      DEFAULT TRUE,
    updated_at      TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE sectors (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) UNIQUE NOT NULL,
    avg_per     NUMERIC(8,2),
    avg_pbr     NUMERIC(8,2),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- stocks.sector → sectors.name FK
ALTER TABLE stocks
    ADD CONSTRAINT fk_stocks_sector
    FOREIGN KEY (sector) REFERENCES sectors(name);

-- ============================================
-- 가격/거래량 (TimescaleDB hypertable)
-- ============================================
CREATE TABLE daily_prices (
    code            VARCHAR(10) NOT NULL REFERENCES stocks(code),
    date            DATE        NOT NULL,
    open            BIGINT,
    high            BIGINT,
    low             BIGINT,
    close           BIGINT      NOT NULL,
    volume          BIGINT,
    trading_value   BIGINT,
    market_cap      BIGINT,
    shares_out      BIGINT,
    PRIMARY KEY (code, date)
);

SELECT create_hypertable('daily_prices', 'date');
-- PK가 (code, date) B-tree를 이미 생성하므로 별도 인덱스 불필요

-- ============================================
-- 투자자별 매매동향
-- ============================================
CREATE TABLE investor_trading (
    code            VARCHAR(10) NOT NULL REFERENCES stocks(code),
    date            DATE        NOT NULL,
    inst_net_buy    BIGINT,
    foreign_net_buy BIGINT,
    retail_net_buy  BIGINT,
    PRIMARY KEY (code, date)
);

-- ============================================
-- 재무제표
-- ============================================
CREATE TABLE financials (
    id               BIGSERIAL PRIMARY KEY,
    code             VARCHAR(10) NOT NULL REFERENCES stocks(code),
    fiscal_year      SMALLINT    NOT NULL,
    fiscal_quarter   SMALLINT    NOT NULL,
    report_type      VARCHAR(10) NOT NULL,          -- CFS(연결)/OFS(별도)
    revenue          BIGINT,
    operating_profit BIGINT,
    net_income       BIGINT,
    total_assets     BIGINT,
    total_equity     BIGINT,
    total_debt       BIGINT,
    per              NUMERIC(8,2),
    pbr              NUMERIC(8,2),
    roe              NUMERIC(8,2),
    debt_ratio       NUMERIC(8,2),
    operating_margin NUMERIC(8,2),
    disclosed_at     DATE,                          -- 공시일 (look-ahead bias 방지 기준)
    UNIQUE (code, fiscal_year, fiscal_quarter, report_type)
);

-- ============================================
-- 공시
-- ============================================
CREATE TABLE disclosures (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(10) REFERENCES stocks(code),
    dart_rcp_no     VARCHAR(20) UNIQUE,
    title           VARCHAR(300) NOT NULL,
    category        VARCHAR(50),
    disclosed_at    TIMESTAMP NOT NULL,
    sentiment_score NUMERIC(4,2),                   -- 현재 단계에서는 항상 NULL
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_disclosures_code_date ON disclosures (code, disclosed_at DESC);

-- ============================================
-- 코스피 지수 (Market Regime 판단용)
-- ============================================
CREATE TABLE index_prices (
    index_code      VARCHAR(10) NOT NULL,           -- '1001' = 코스피
    date            DATE        NOT NULL,
    close           BIGINT      NOT NULL,
    PRIMARY KEY (index_code, date)
);

-- ============================================
-- 스코어링 결과
-- ============================================
CREATE TABLE stock_scores (
    code              VARCHAR(10) NOT NULL REFERENCES stocks(code),
    date              DATE        NOT NULL,
    -- 기술적 지표 (0~100)
    rsi_score         NUMERIC(5,2),
    macd_score        NUMERIC(5,2),
    bb_score          NUMERIC(5,2),
    technical_score   NUMERIC(5,2),
    -- 재무 지표 (0~100)
    per_score         NUMERIC(5,2),
    pbr_score         NUMERIC(5,2),
    roe_score         NUMERIC(5,2),
    debt_score        NUMERIC(5,2),
    fundamental_score NUMERIC(5,2),
    -- 모멘텀 (0~100)
    volume_score      NUMERIC(5,2),
    inst_score        NUMERIC(5,2),
    high52_score      NUMERIC(5,2),
    momentum_score    NUMERIC(5,2),
    -- 최종
    total_score       NUMERIC(5,2) NOT NULL,
    rank              SMALLINT,
    -- 시장 상태
    market_regime     VARCHAR(10),                  -- BULL / BEAR
    PRIMARY KEY (code, date)
);

CREATE INDEX idx_scores_date_total ON stock_scores (date, total_score DESC);

CREATE TABLE recommendations (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE        NOT NULL,
    rank        SMALLINT    NOT NULL,               -- 1~5
    code        VARCHAR(10) NOT NULL REFERENCES stocks(code),
    total_score NUMERIC(5,2),
    reason      TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (date, rank)
);

-- ============================================
-- 백테스트 성과
-- ============================================
CREATE TABLE recommendation_returns (
    recommendation_id BIGINT REFERENCES recommendations(id),
    days_after        SMALLINT NOT NULL,            -- 1, 5, 20, 60
    return_rate       NUMERIC(8,4),
    benchmark_rate    NUMERIC(8,4),
    PRIMARY KEY (recommendation_id, days_after)
);
```

### 원본 설계 대비 변경사항

| 변경 | 이유 |
|---|---|
| `stocks.sector` → `sectors.name` FK 추가 | 데이터 정합성 보장 |
| `SERIAL` → `BIGSERIAL` (financials, disclosures, recommendations) | FK 타입 일관성 |
| `daily_prices`의 중복 인덱스 제거 | PK가 이미 커버 |
| `index_prices` 테이블 추가 | Market Regime 판단용 코스피 지수 저장 |
| `stock_scores.market_regime` 컬럼 추가 | 해당 일자 시장 상태 기록 |

---

## 4. 핵심 비즈니스 로직

> 아래 규칙은 반드시 준수한다. 위반 시 추천 품질이 심각하게 저하된다.

### 4-1. Market Regime 동적 가중치

기술점수(역추세)와 모멘텀점수(추세추종)는 시장 상태에 따라 유효성이 달라진다.
코스피 지수의 이동평균선으로 시장 상태를 판단하고, 가중치를 동적으로 조절한다.

```python
# scoring/market_regime.py

import pandas as pd
from dataclasses import dataclass

@dataclass
class MarketRegime:
    regime: str          # "BULL" or "BEAR"
    weights: dict        # {"technical": float, "fundamental": float, "momentum": float}
    ma20: float
    ma60: float

def determine_regime(kospi_prices: pd.DataFrame) -> MarketRegime:
    """
    코스피 종가 기준 MA20 > MA60이면 BULL, 아니면 BEAR.
    - BULL: 모멘텀(추세추종) 비중 ↑, 기술(역추세) 비중 ↓
    - BEAR: 기술(역추세) 비중 ↑, 모멘텀(추세추종) 비중 ↓
    - 재무(fundamental)는 시장 상태와 무관하게 40% 고정
    """
    close = kospi_prices['close'].astype(float)
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    if ma20 > ma60:
        return MarketRegime(
            regime="BULL",
            weights={"technical": 0.20, "fundamental": 0.40, "momentum": 0.40},
            ma20=ma20, ma60=ma60
        )
    else:
        return MarketRegime(
            regime="BEAR",
            weights={"technical": 0.45, "fundamental": 0.40, "momentum": 0.15},
            ma20=ma20, ma60=ma60
        )
```

### 4-2. 섹터 상대비교 (Fundamental)

PER, PBR, ROE, 부채비율은 **같은 섹터 내에서** 백분위를 매긴다.
전체 종목 대비 백분위는 사용하지 않는다.

```python
# 핵심 규칙:
# 1. 같은 섹터 종목이 5개 이상이면 → 섹터 내 백분위
# 2. 같은 섹터 종목이 5개 미만이면 → 전체 종목 백분위로 폴백
# 3. sectors.avg_per 대비 20% 이상 할인이면 → 보너스 +10

def _per_score(self, fin: dict, sector_financials: pd.DataFrame, all_financials: pd.DataFrame, sector_avg_per: float) -> float:
    per = fin.get('per')
    if per is None or per <= 0:
        return 30.0

    valid_sector = sector_financials[sector_financials['per'] > 0]['per']
    if len(valid_sector) >= 5:
        score = 100 - self.percentile_score(per, valid_sector)
    else:
        valid_all = all_financials[all_financials['per'] > 0]['per']
        score = 100 - self.percentile_score(per, valid_all)

    # 섹터 평균 대비 할인 보너스
    if sector_avg_per and sector_avg_per > 0 and per < sector_avg_per * 0.8:
        score = min(100, score + 10)

    return round(score, 2)
```

### 4-3. 추천 제외 필터

스코어링 전에 아래 조건에 해당하는 종목은 후보에서 제외한다.

```python
# scoring/filters.py

EXCLUDE_DISCLOSURE_CATEGORIES = [
    '관리종목지정',
    '상장폐지',
    '불성실공시',
    '회생절차',
    '거래정지',
]

def should_exclude(code: str, db) -> tuple[bool, str]:
    """
    Returns: (제외 여부, 사유)
    """
    # 1. 거래정지 / 비활성 종목
    stock = db.get_stock(code)
    if not stock or not stock['is_active']:
        return True, "비활성 종목"

    # 2. 상장일 기준 60거래일 미만 (약 3개월)
    prices = db.get_prices(code, lookback=60)
    if len(prices) < 60:
        return True, f"거래일 부족 ({len(prices)}일)"

    # 3. 최근 5일 거래량 0 (거래정지 의심)
    recent_volume = prices.tail(5)['volume']
    if (recent_volume == 0).any():
        return True, "최근 5일 내 거래량 0 존재"

    # 4. 위험 공시 존재 (최근 30일)
    recent_disclosures = db.get_recent_disclosures(code, days=30)
    for disc in recent_disclosures:
        if disc['category'] in EXCLUDE_DISCLOSURE_CATEGORIES:
            return True, f"위험 공시: {disc['category']}"

    return False, ""
```

### 4-4. Look-Ahead Bias 방지

재무제표 데이터는 반드시 `disclosed_at`(공시일) 기준으로 사용 가능 여부를 판단한다.

```python
# db/repository.py

def get_latest_financials(self, code: str, as_of_date: str) -> dict:
    """
    as_of_date 시점에 실제로 공시되어 있던 가장 최근 재무제표를 반환.
    미래에 공시될 데이터는 절대 포함하지 않는다.
    """
    query = """
        SELECT * FROM financials
        WHERE code = %s
          AND report_type = 'CFS'
          AND disclosed_at <= %s
        ORDER BY fiscal_year DESC, fiscal_quarter DESC
        LIMIT 1
    """
    return self._fetch_one(query, (code, as_of_date))
```

### 4-5. BaseScorer 추상 메서드 시그니처

원본 설계에서 `BaseScorer.score()`의 시그니처가 하위 클래스마다 달라지는 문제가 있었다.
아래와 같이 수정한다.

```python
# scoring/base.py

class BaseScorer(ABC):

    @abstractmethod
    def score(self, code: str, **kwargs) -> ScoreResult:
        """
        하위 클래스는 필요한 데이터를 **kwargs로 받는다.
        - TechnicalScorer: prices
        - FundamentalScorer: financials, sector_financials, all_financials, sector_stats
        - MomentumScorer: prices, investor
        """
        pass
```

---

## 5. 성능 주의사항

### 5-1. 루프 밖 캐싱 필수

`all_financials`와 `sector_financials`는 루프 밖에서 한 번만 조회한다.

```python
# scoring/engine.py — run_daily() 내부

# ✅ 올바른 구현
all_fin = self.db.get_all_financials()
sector_fin_map = self.db.get_financials_grouped_by_sector()  # {sector: DataFrame}

for code in target_pool:
    sector = self.db.get_stock_sector(code)
    score = self.aggregator.run(
        code=code,
        all_financials=all_fin,
        sector_financials=sector_fin_map.get(sector, pd.DataFrame()),
        ...
    )

# ❌ 금지 — 루프 안에서 전체 재무 데이터 매번 조회
for code in target_pool:
    all_fin = self.db.get_all_financials()  # 350번 풀스캔
```

### 5-2. 실패율 임계치

350개 종목 중 스코어링 실패 비율이 30%를 초과하면 해당 일자 추천을 생성하지 않는다.

```python
FAILURE_THRESHOLD = 0.30

failed = [code for code in target_pool if code in errors]
if len(failed) / len(target_pool) > FAILURE_THRESHOLD:
    logger.error(f"실패율 {len(failed)}/{len(target_pool)} — 추천 생성 중단")
    return []
```

---

## 6. 외부 의존성

### pyproject.toml 주요 패키지

```toml
[tool.poetry.dependencies]
python = "^3.11"

# 데이터 수집
pykrx = "*"
opendartreader = "*"

# 데이터 처리
pandas = "^2.0"
numpy = "^1.24"

# 기술적 지표 (선택 — 직접 구현 대신 사용 가능)
ta = "*"

# DB
psycopg2-binary = "*"
redis = "*"

# 스케줄링
apscheduler = "^3.10"

# 설정
pydantic-settings = "*"
python-dotenv = "*"

# 로깅
loguru = "*"

# 알림
requests = "*"

[tool.poetry.group.dev.dependencies]
pytest = "*"
pytest-cov = "*"
```

### 환경 변수 (.env.example)

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock_recommender
DB_USER=postgres
DB_PASSWORD=

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# DART API
DART_API_KEY=

# Slack (5단계)
SLACK_WEBHOOK_URL=

# 스케줄링
SCHEDULE_HOUR=16
SCHEDULE_MINUTE=30
```

---

## 7. Docker Compose

```yaml
version: "3.8"

services:
  db:
    image: timescale/timescaledb:latest-pg15
    container_name: stock-db
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: stock_recommender
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${DB_PASSWORD:-stockpass}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./src/db/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql

  redis:
    image: redis:7-alpine
    container_name: stock-redis
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

---

## 8. 로깅 규칙

모든 모듈에서 `print()`를 사용하지 않는다. 반드시 `loguru`를 사용한다.

```python
# utils/logger.py
from loguru import logger
import sys

def setup_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} | {message}",
        level="INFO"
    )
    logger.add(
        "logs/stock-recommender_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG"
    )
```

```python
# 스코어링 실패 시 로깅 예시 (print 금지)

# ✅
logger.warning(f"스코어링 스킵 | code={code} | reason={e}")

# ❌
print(f"[SKIP] {code}: {e}")
```

---

## 9. 테스트 요구사항

각 Scorer에 대해 최소 아래 케이스를 커버하는 단위 테스트를 작성한다.

### TechnicalScorer

- RSI 30 이하(과매도) → 70점 이상
- RSI 70 이상(과매수) → 30점 이하
- 데이터 부족(5일 미만) 시 기본값 50.0 반환

### FundamentalScorer

- 같은 섹터 내 PER 최저 종목 → 90점 이상
- 섹터 종목 5개 미만 → 전체 폴백 동작 확인
- PER 음수/None → 30.0 반환

### MomentumScorer

- 거래량 5배 급증 → 100점
- 거래량 데이터 없음 → 50.0 반환
- 52주 신고가 갱신 → 100점

### MarketRegime

- MA20 > MA60 → BULL, 모멘텀 가중치 0.40
- MA20 < MA60 → BEAR, 기술 가중치 0.45

### Filters

- 상장 60일 미만 → 제외
- 최근 5일 거래량 0 존재 → 제외
- 관리종목 공시 → 제외

---

## 10. 구현 시 절대 하지 말 것 (Anti-patterns)

| # | 금지 사항 | 이유 |
|---|---|---|
| 1 | 전체 종목 대상 PER/PBR 백분위 | 섹터 특성 무시 → 금융주만 추천됨 |
| 2 | 기술/모멘텀 가중치 고정 | 상승장에서 역추세가 발목 잡음 |
| 3 | `print()` 사용 | 프로덕션 로그 추적 불가 |
| 4 | 루프 안에서 전체 재무 데이터 조회 | 350번 풀스캔 → 성능 치명적 |
| 5 | `disclosed_at` 무시하고 재무 데이터 사용 | look-ahead bias → 백테스트 결과 신뢰 불가 |
| 6 | 네이버금융 크롤링 | robots.txt 위반, IP 차단 리스크 |
| 7 | 실패 종목 무시하고 추천 강행 | 데이터 불완전 시 추천 품질 저하 |
| 8 | `BaseScorer.score()` 시그니처 불일치 | LSP 위반, mypy 에러 |

---

## 11. 로드맵

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| 1단계 | Docker Compose + DB 스키마 + PriceCollector + InvestorCollector + IndexCollector | `daily_prices`, `investor_trading`, `index_prices` 테이블에 최근 1년 데이터 적재 |
| 2단계 | FinanceCollector + DisclosureCollector | `financials`, `disclosures` 테이블에 데이터 적재 |
| 3단계 | MarketRegime + Filters + TechnicalScorer | 단위 테스트 전체 통과 |
| 4단계 | FundamentalScorer + MomentumScorer + Aggregator | 350개 종목 스코어링 → Top 5 추출 성공 |
| 5단계 | main.py (APScheduler) + 매일 자동 실행 | 16:30 자동 실행, 로그 파일 생성 확인 |
| 6단계 | 백테스트 evaluator | 과거 추천 대비 수익률 계산 |
| 7단계 | Slack 알림 연동 | 추천 결과 Slack 메시지 수신 |
