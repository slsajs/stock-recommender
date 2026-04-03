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
│   │   ├── index_collector.py    # pykrx — 코스피 지수 (Market Regime 판단용)
│   │   ├── macro_collector.py    # [고도화 STEP A~C] ECOS API — 금리, 환율, 국고채
│   │   ├── us_market_collector.py # [고도화 STEP D] yfinance — S&P500/나스닥
│   │   └── news_collector.py     # [고도화 STEP F] 빅카인즈 API — 뉴스
│   │
│   ├── scoring/                  # 스코어링 엔진
│   │   ├── __init__.py
│   │   ├── base.py               # BaseScorer ABC, ScoreResult dataclass
│   │   ├── technical.py          # RSI, MACD, 볼린저밴드
│   │   ├── fundamental.py        # PER, PBR, ROE, 부채비율 (섹터 상대비교)
│   │   ├── momentum.py           # 거래량 급증, 기관 순매수, 52주 신고가
│   │   ├── market_regime.py      # 코스피 MA20/MA60 기반 시장 상태 판단
│   │   ├── aggregator.py         # 가중합 → 최종점수 → 상위 5개
│   │   ├── filters.py            # 추천 제외 필터 (관리종목, 거래정지, 신규상장 등)
│   │   ├── macro_adjuster.py     # [고도화 STEP A~D] 매크로 보정
│   │   ├── disclosure_scorer.py  # [고도화 STEP E] 공시 감성분석 (규칙 기반)
│   │   └── news_scorer.py        # [고도화 STEP F] 뉴스 감성분석
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
    ├── test_aggregator.py
    ├── test_macro_adjuster.py      # [고도화]
    ├── test_disclosure_scorer.py   # [고도화]
    └── test_news_scorer.py         # [고도화]
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
-- [고도화] 거시경제 지표
-- ============================================
CREATE TABLE macro_indicators (
    date            DATE        NOT NULL,
    indicator_code  VARCHAR(30) NOT NULL,            -- 'BASE_RATE', 'USD_KRW', 'KTB_10Y', 'CPI_YOY'
    value           NUMERIC(12,4) NOT NULL,
    PRIMARY KEY (date, indicator_code)
);

-- ============================================
-- [고도화] 미국 시장 지수
-- ============================================
CREATE TABLE us_market_prices (
    index_code      VARCHAR(10) NOT NULL,           -- 'SPX' = S&P500, 'IXIC' = 나스닥
    date            DATE        NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    change_pct      NUMERIC(8,4),                   -- 전일 대비 변동률 (%)
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
    market_regime     VARCHAR(10),                  -- BULL / BEAR / CAUTIOUS_BULL / RECOVERING
    -- [고도화] 보정값
    macro_adjustment    NUMERIC(5,2) DEFAULT 0,     -- 매크로 보정 (-5 ~ +5)
    disclosure_adjustment NUMERIC(5,2) DEFAULT 0,   -- 공시 감성 보정 (-10 ~ +10)
    news_adjustment     NUMERIC(5,2) DEFAULT 0,     -- 뉴스 감성 보정 (-5 ~ +5)
    adjusted_total_score NUMERIC(5,2),              -- total_score + 보정값 합계
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
| [고도화] `macro_indicators` 테이블 추가 | STEP A~C 거시경제 지표 저장 |
| [고도화] `us_market_prices` 테이블 추가 | STEP D 미국 시장 데이터 저장 |
| [고도화] `stock_scores`에 보정 컬럼 4개 추가 | macro/disclosure/news adjustment + adjusted_total_score |

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

### 4-4a. [고도화] 매크로/뉴스용 DB 메서드

`db/repository.py`에 고도화 STEP에서 필요한 메서드들이다. 각 STEP 구현 시 추가한다.

```python
# STEP A~C: 매크로 지표
def get_macro_indicator(self, indicator_code: str, lookback_days: int) -> pd.DataFrame:
    """macro_indicators에서 최근 N일 데이터 반환. 컬럼: date, value"""

def get_latest_macro_indicator(self, indicator_code: str) -> float | None:
    """macro_indicators에서 가장 최근 값 1건 반환."""

# STEP D: 미국 시장
def get_latest_us_market_change(self, index_code: str) -> float | None:
    """us_market_prices에서 가장 최근 변동률(change_pct) 반환. index_code='SPX' or 'IXIC'"""

# STEP E: 공시 (기존 get_recent_disclosures 활용, days_ago 컬럼 추가)
# get_recent_disclosures()가 반환하는 dict에 'days_ago' 필드를 포함해야 함

# STEP F: 뉴스 (메모리 처리 또는 별도 테이블)
# news_collector가 수집한 제목 리스트를 직접 scorer에 전달 (DB 거치지 않아도 됨)
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

# [고도화] 거시경제/미국시장
yfinance = "*"              # S&P500, 나스닥 전일 종가
ecos = "*"                  # 한국은행 ECOS API 래퍼

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

# [고도화] ECOS API (한국은행 경제통계)
ECOS_API_KEY=

# [고도화] 빅카인즈 뉴스 API
BIGKINDS_API_KEY=

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
| 9 | 2개 이상 고도화 STEP 동시 추가 | 효과 분리 불가 → 어떤 STEP이 기여했는지 알 수 없음 |
| 10 | 고도화 STEP 추가 후 백테스트 미실행 | 성과 악화를 감지 못하고 누적됨 |

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
| **고도화** | | |
| STEP A | 금리 트렌드 → 재무 가중치 조절 | 백테스트 alpha 비교 완료 |
| STEP B | 환율 → 섹터 보정 | 백테스트 alpha 비교 완료 |
| STEP C | 장단기 금리차 → Regime 보강 | 하위 호환 테스트 + 백테스트 alpha 비교 완료 |
| STEP D | 미국 시장 급락 → 추천 보류 | 보류 로직 + 모멘텀 감점 테스트 통과 |
| STEP E | 공시 감성 (규칙 기반) | 백테스트 alpha 비교 완료 |
| STEP F | 뉴스 감성 | 백테스트 alpha 비교 완료 |

---

## 12. 고도화 — Step-by-Step 구현 가이드

> 아래 STEP A~F는 MVP 완료 후 순차적으로 추가하는 고도화 기능이다.
> 각 STEP은 독립적으로 구현/테스트 가능하며, **반드시 순서대로 진행**한다.
> 각 STEP 구현 후 백테스트를 돌려 성과가 개선되었는지 확인하고, 악화되면 해당 STEP을 비활성화한다.

### 전체 흐름

```
[기존 MVP 스코어링]
  total_score = 기술(가변%) + 재무(40%) + 모멘텀(가변%)
                                ↓
[STEP A] 금리 트렌드 → 재무 내부 가중치 조절 (PER/ROE 비중 변경)
[STEP B] 환율 변동 → 섹터별 최종 점수 보정 (-5 ~ +5)
[STEP C] 장단기 금리차 → Market Regime 판단 보강
[STEP D] 미국 시장 급락 → 당일 추천 보류 판단
[STEP E] 공시 감성 (규칙 기반) → 최종 점수 보정 (-10 ~ +10)
[STEP F] 뉴스 감성 → 최종 점수 보정 (-5 ~ +5)
                                ↓
  adjusted_total_score = total_score + macro_adj + disclosure_adj + news_adj
```

---

### STEP A: 금리 트렌드 → 재무 가중치 조절

**목적**: 금리 인상기에는 저PER 가치주를, 인하기에는 고ROE 성장주를 더 선호하도록 재무점수 내부 가중치를 동적으로 변경한다.

**배경 지식**:
- 금리 인상 → 미래 이익의 현재 가치 감소 → 고PER 성장주 불리, 저PER 가치주/배당주 유리
- 금리 인하 → 성장 기대감 증가 → ROE 높은 성장주 유리

**영향 범위**: `scoring/fundamental.py`, `scoring/macro_adjuster.py`

**선행 조건**: `macro_indicators` 테이블에 `BASE_RATE` 데이터 적재 완료

#### 파일 1: `collector/macro_collector.py`

```python
"""
ECOS API에서 거시경제 지표를 수집하여 macro_indicators 테이블에 저장.
ECOS API 문서: https://ecos.bok.or.kr/api/#/

수집 대상 (STEP A~C에서 사용):
- BASE_RATE: 한국은행 기준금리 (통계표코드: 722Y001, 항목코드: 0101000)
- USD_KRW: 원/달러 환율 (통계표코드: 731Y003, 항목코드: 0000001)
- KTB_10Y: 국고채 10년물 수익률 (통계표코드: 817Y002, 항목코드: 010200000)
- CPI_YOY: 소비자물가 전년동월비 (통계표코드: 021Y125, 항목코드: 0)

주기:
- BASE_RATE: 변경 시만 업데이트 (연 8회 금통위)
- USD_KRW: 매일
- KTB_10Y: 매일
- CPI_YOY: 월 1회

ECOS API 호출 예시:
import ecos
api = ecos.OpenApi(ECOS_API_KEY)
df = api.get_statistic_search(
    통계표코드='722Y001',
    주기='D',
    검색시작일자='20240101',
    검색종료일자='20241231',
    항목코드1='0101000'
)
"""
```

#### 파일 2: `scoring/macro_adjuster.py` — STEP A 부분

```python
# scoring/macro_adjuster.py

from dataclasses import dataclass

@dataclass
class MacroCondition:
    base_rate_trend: str       # "RISING" / "FALLING" / "STABLE"
    usd_krw_change: float      # 최근 20일 환율 변동률 (%) — STEP B에서 사용
    yield_spread: float        # 장단기 금리차 (%) — STEP C에서 사용
    us_market_change: float    # 전일 S&P500 변동률 (%) — STEP D에서 사용

def determine_rate_trend(db, lookback_months: int = 3) -> str:
    """
    최근 3개월간 기준금리 변동 방향을 판단.

    규칙:
    - 기간 내 기준금리가 0.25%p 이상 상승 → "RISING"
    - 기간 내 기준금리가 0.25%p 이상 하락 → "FALLING"
    - 변동 없거나 0.25%p 미만 → "STABLE"

    반환: "RISING" / "FALLING" / "STABLE"
    """
    rates = db.get_macro_indicator('BASE_RATE', lookback_days=lookback_months * 30)
    if len(rates) < 2:
        return "STABLE"

    oldest = rates.iloc[0]['value']
    latest = rates.iloc[-1]['value']
    diff = latest - oldest

    if diff >= 0.25:
        return "RISING"
    elif diff <= -0.25:
        return "FALLING"
    else:
        return "STABLE"

def get_fundamental_weights(base_rate_trend: str) -> dict:
    """
    금리 트렌드에 따라 FundamentalScorer 내부 가중치를 조절.

    기본값: {"per": 0.30, "pbr": 0.25, "roe": 0.30, "debt": 0.15}

    조절 원리:
    - RISING(금리 인상기): 저PER 선호 → PER 가중치 ↑, ROE ↓
    - FALLING(금리 인하기): 성장주 선호 → ROE 가중치 ↑, PER ↓
    - STABLE: 기본 가중치 유지
    """
    if base_rate_trend == "RISING":
        return {"per": 0.40, "pbr": 0.25, "roe": 0.20, "debt": 0.15}
    elif base_rate_trend == "FALLING":
        return {"per": 0.20, "pbr": 0.20, "roe": 0.40, "debt": 0.20}
    else:
        return {"per": 0.30, "pbr": 0.25, "roe": 0.30, "debt": 0.15}
```

#### aggregator.py 변경점

```python
# ScoreAggregator.run() 에서 fundamental 호출 시 가중치를 주입

rate_trend = determine_rate_trend(db)
fund_weights = get_fundamental_weights(rate_trend)

f = self.fundamental.score(code, fund_internal_weights=fund_weights, ...)
```

#### 테스트 케이스 (`test_macro_adjuster.py`)

```
- 기준금리 3개월간 0.5%p 상승 → "RISING" 반환
- 기준금리 3개월간 0.5%p 하락 → "FALLING" 반환
- 기준금리 변동 없음 → "STABLE" 반환
- RISING → PER 가중치 0.40, ROE 가중치 0.20
- FALLING → PER 가중치 0.20, ROE 가중치 0.40
- 데이터 1건 미만 → "STABLE" 폴백
```

#### 완료 기준

- [x] `macro_collector.py`가 ECOS에서 BASE_RATE 데이터를 수집하여 `macro_indicators`에 저장
- [x] `determine_rate_trend()`가 올바른 트렌드를 반환
- [x] `FundamentalScorer`가 외부에서 주입받은 가중치로 점수를 계산
- [x] 단위 테스트 전체 통과
- [x] 백테스트 결과 비교: STEP A 적용 전/후 평균 alpha 비교

---

### STEP B: 환율 → 섹터 보정

**목적**: 원/달러 환율 변동에 따라 수출주에 가점, 수입 의존주에 감점을 적용한다.

**배경 지식**:
- 환율 상승(원화 약세) → 수출기업 원화 매출 증가 → 수출주 유리
- 환율 하락(원화 강세) → 수입 원자재 비용 감소 → 내수주 유리

**영향 범위**: `scoring/macro_adjuster.py`, `scoring/aggregator.py`

**선행 조건**: `macro_indicators` 테이블에 `USD_KRW` 데이터 적재 완료 (STEP A의 `macro_collector.py`에서 수집)

#### `scoring/macro_adjuster.py` — STEP B 추가

```python
# 섹터 분류 — stocks.sector 값과 일치해야 함
EXPORT_SECTORS = ['반도체', '자동차', '조선', '전자부품', '디스플레이', 'IT하드웨어']
IMPORT_SECTORS = ['항공', '정유', '철강', '화학']

def get_usd_krw_change(db, lookback_days: int = 20) -> float:
    """
    최근 20거래일 원/달러 환율 변동률 (%) 반환.
    양수 = 원화 약세, 음수 = 원화 강세.
    """
    rates = db.get_macro_indicator('USD_KRW', lookback_days=lookback_days)
    if len(rates) < 2:
        return 0.0
    oldest = rates.iloc[0]['value']
    latest = rates.iloc[-1]['value']
    return round((latest - oldest) / oldest * 100, 4)

def currency_adjustment(sector: str, usd_krw_change: float) -> float:
    """
    환율 변동에 따른 섹터별 점수 보정값 반환.

    규칙:
    - 수출 섹터: 원화 약세 시 가점 (환율 1% 상승당 +1점, 최대 ±5)
    - 수입 의존 섹터: 원화 약세 시 감점 (환율 1% 상승당 -1점, 최대 ±5)
    - 기타 섹터: 보정 없음 (0.0)

    반환값: -5.0 ~ +5.0
    """
    if sector in EXPORT_SECTORS:
        return round(max(-5.0, min(5.0, usd_krw_change * 1.0)), 2)
    elif sector in IMPORT_SECTORS:
        return round(max(-5.0, min(5.0, usd_krw_change * -1.0)), 2)
    else:
        return 0.0
```

#### aggregator.py 변경점

```python
# 최종 점수에 환율 보정 가감
usd_change = get_usd_krw_change(db)
macro_adj = currency_adjustment(sector, usd_change)

adjusted_total = total_score + macro_adj
# stock_scores 테이블의 macro_adjustment 컬럼에 저장
```

#### 테스트 케이스

```
- 반도체 섹터 + 환율 3% 상승 → +3.0 보정
- 항공 섹터 + 환율 3% 상승 → -3.0 보정
- 유통 섹터 (기타) + 환율 변동 → 0.0 보정
- 환율 10% 급등 → 최대 +5.0 제한 (클리핑)
- 환율 데이터 없음 → 0.0 반환
```

#### 완료 기준

- [x] `macro_collector.py`가 USD_KRW를 매일 수집
- [x] `currency_adjustment()`가 섹터별로 올바른 보정값 반환
- [x] `stock_scores.macro_adjustment`에 보정값 저장
- [x] 단위 테스트 전체 통과

---

### STEP C: 장단기 금리차 → Market Regime 보강

**목적**: MA20/MA60만으로 판단하던 Market Regime에 장단기 금리차를 추가하여 정확도를 높인다.

**배경 지식**:
- 장단기 금리차 = 국고채 10년물 - 기준금리
- 양수 (정상): 경기 확장 기대
- 축소 중: 경기 둔화 신호
- 음수 (역전): 경기 침체 경고 → 방어주(유틸리티, 필수소비재) 유리

**영향 범위**: `scoring/market_regime.py`

**선행 조건**: `macro_indicators`에 `BASE_RATE`, `KTB_10Y` 데이터 적재 완료

#### `scoring/market_regime.py` 변경

```python
# 기존 MarketRegime dataclass 확장
@dataclass
class MarketRegime:
    regime: str          # "BULL" / "BEAR" / "CAUTIOUS_BULL" / "RECOVERING"
    weights: dict
    ma20: float
    ma60: float
    yield_spread: float  # [STEP C 추가] 장단기 금리차

def determine_regime(kospi_prices: pd.DataFrame, yield_spread: float = None) -> MarketRegime:
    """
    MA 기반 판단 + 장단기 금리차 보강.

    조합 규칙:
    ┌─────────────┬────────────────┬──────────────────────────┐
    │ MA 신호      │ 금리차         │ 최종 Regime               │
    ├─────────────┼────────────────┼──────────────────────────┤
    │ BULL        │ > 0 또는 None  │ BULL                     │
    │ BULL        │ < 0 (역전)     │ CAUTIOUS_BULL            │
    │ BEAR        │ > 1.0          │ RECOVERING               │
    │ BEAR        │ <= 1.0 또는 None│ BEAR                    │
    └─────────────┴────────────────┴──────────────────────────┘

    가중치:
    - BULL:          technical=0.20, fundamental=0.40, momentum=0.40
    - CAUTIOUS_BULL: technical=0.30, fundamental=0.45, momentum=0.25
    - RECOVERING:    technical=0.30, fundamental=0.35, momentum=0.35
    - BEAR:          technical=0.45, fundamental=0.40, momentum=0.15
    """
    close = kospi_prices['close'].astype(float)
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    ma_signal = "BULL" if ma20 > ma60 else "BEAR"

    # yield_spread가 None이면 기존 로직과 동일하게 동작 (하위 호환)
    if yield_spread is not None:
        if ma_signal == "BULL" and yield_spread < 0:
            regime = "CAUTIOUS_BULL"
            weights = {"technical": 0.30, "fundamental": 0.45, "momentum": 0.25}
        elif ma_signal == "BEAR" and yield_spread > 1.0:
            regime = "RECOVERING"
            weights = {"technical": 0.30, "fundamental": 0.35, "momentum": 0.35}
        elif ma_signal == "BULL":
            regime = "BULL"
            weights = {"technical": 0.20, "fundamental": 0.40, "momentum": 0.40}
        else:
            regime = "BEAR"
            weights = {"technical": 0.45, "fundamental": 0.40, "momentum": 0.15}
    else:
        if ma_signal == "BULL":
            regime = "BULL"
            weights = {"technical": 0.20, "fundamental": 0.40, "momentum": 0.40}
        else:
            regime = "BEAR"
            weights = {"technical": 0.45, "fundamental": 0.40, "momentum": 0.15}

    return MarketRegime(
        regime=regime, weights=weights,
        ma20=ma20, ma60=ma60,
        yield_spread=yield_spread if yield_spread is not None else 0.0
    )

def get_yield_spread(db) -> float | None:
    """
    국고채 10년물 - 기준금리 = 장단기 금리차.
    데이터 없으면 None 반환 (하위 호환).
    """
    ktb = db.get_latest_macro_indicator('KTB_10Y')
    base = db.get_latest_macro_indicator('BASE_RATE')
    if ktb is None or base is None:
        return None
    return round(ktb - base, 4)
```

#### 테스트 케이스

```
- MA BULL + 금리차 양수 → BULL
- MA BULL + 금리차 음수 (역전) → CAUTIOUS_BULL, fundamental 45%
- MA BEAR + 금리차 > 1.0 → RECOVERING
- MA BEAR + 금리차 <= 1.0 → BEAR
- yield_spread=None → 기존 BULL/BEAR 로직과 동일 (하위 호환)
```

#### 완료 기준

- [x] `macro_collector.py`가 KTB_10Y 데이터를 수집
- [x] `get_yield_spread()`가 올바른 금리차 계산
- [x] 4가지 Regime 모두 올바른 가중치 반환
- [x] yield_spread=None일 때 기존 동작과 100% 동일 (하위 호환)
- [x] 단위 테스트 전체 통과

---

### STEP D: 미국 시장 급락 → 추천 보류

**목적**: 전일 미국 시장(S&P500)이 급락했을 때 당일 추천을 보류하거나, 방어적으로 조정한다.

**배경 지식**:
- 한국 시장은 전일 미국 시장의 영향을 강하게 받음
- S&P500 -2% 이상 하락 시 다음 날 코스피도 높은 확률로 하락
- 이런 날 추천한 종목은 단기 손실 가능성이 높음

**영향 범위**: `collector/us_market_collector.py`, `scoring/macro_adjuster.py`, `scoring/aggregator.py` (또는 `main.py`)

**선행 조건**: 없음 (독립적, yfinance만 필요)

#### 파일: `collector/us_market_collector.py`

```python
"""
yfinance로 S&P500(^GSPC), 나스닥(^IXIC) 전일 종가 및 변동률 수집.
us_market_prices 테이블에 저장.

실행 시점: 한국 시간 오전 (미국 장 마감 후)
- 미국 동부 시간 16:00 = 한국 시간 06:00 (서머타임 시 05:00)
- 스케줄러의 수집 단계에서 price_collector 이전에 실행

import yfinance as yf

def collect_us_market(date: str):
    sp500 = yf.download('^GSPC', period='5d', auto_adjust=True)
    nasdaq = yf.download('^IXIC', period='5d', auto_adjust=True)
    # 최근 2일 데이터로 전일 대비 변동률 계산
    # us_market_prices 테이블에 UPSERT
"""
```

#### `scoring/macro_adjuster.py` — STEP D 추가

```python
def should_skip_recommendation(db) -> tuple[bool, str]:
    """
    극단적 시장 상황에서 추천 자체를 보류할지 판단.

    규칙:
    - S&P500 전일 -3% 이상 → 추천 보류 (True)
    - S&P500 전일 -2% ~ -3% → 추천은 하되 로그 경고
    - 그 외 → 정상 진행

    반환: (보류 여부, 사유)
    """
    us_change = db.get_latest_us_market_change('SPX')
    if us_change is None:
        return False, ""

    if us_change <= -3.0:
        return True, f"S&P500 급락 ({us_change}%), 추천 보류"
    elif us_change <= -2.0:
        logger.warning(f"S&P500 하락 경고 ({us_change}%), 추천은 진행하되 주의")
        return False, ""
    else:
        return False, ""

def us_market_momentum_penalty(us_change: float, momentum_score: float) -> float:
    """
    미국 시장 하락 시 모멘텀 점수가 높은 종목에 감점.

    규칙:
    - S&P500 -2% 이상 하락 + 모멘텀 점수 70 이상 → -3점 보정
    - S&P500 -2% 이상 하락 + 모멘텀 점수 70 미만 → 보정 없음
    - S&P500 -2% 미만 → 보정 없음

    이유: 추세추종(모멘텀) 종목은 시장 하락에 더 민감

    반환값: -3.0 또는 0.0
    """
    if us_change is not None and us_change <= -2.0 and momentum_score >= 70:
        return -3.0
    return 0.0
```

#### main.py 변경점

```python
# run_daily() 최상단에 추가
skip, reason = should_skip_recommendation(db)
if skip:
    logger.warning(f"금일 추천 보류 | {reason}")
    # 추천은 생성하지 않되, 스코어링 자체는 기록용으로 실행 가능
    return []
```

#### 테스트 케이스

```
- S&P500 -3.5% → should_skip=True
- S&P500 -2.5% → should_skip=False (경고 로그만)
- S&P500 -1.0% → should_skip=False
- S&P500 데이터 없음 → should_skip=False (안전한 기본값)
- S&P500 -2.5% + 모멘텀 80점 → -3.0 감점
- S&P500 -2.5% + 모멘텀 50점 → 0.0 감점 없음
```

#### 완료 기준

- [x] `us_market_collector.py`가 yfinance에서 S&P500/나스닥 데이터 수집
- [x] `should_skip_recommendation()`이 -3% 기준으로 보류 판단
- [x] `main.py`에서 보류 시 추천 생성 중단
- [x] 단위 테스트 전체 통과

---

### STEP E: 공시 감성 (규칙 기반)

**목적**: DART 공시의 카테고리와 제목 키워드를 분석하여 종목별 감성 보정값을 산출한다.

**배경 지식**:
- 공시는 법적 의무로 발행되므로 뉴스보다 신뢰도가 높음
- 유상증자 → 주주 지분 희석 → 악재 / 자기주식 취득 → 호재
- 실적 관련 키워드(흑자전환, 적자전환 등)도 강한 신호

**영향 범위**: `scoring/disclosure_scorer.py`, `scoring/aggregator.py`

**선행 조건**: `disclosures` 테이블에 데이터 적재 완료 (MVP 2단계)

#### 파일: `scoring/disclosure_scorer.py`

```python
# scoring/disclosure_scorer.py

"""
DART 공시의 카테고리와 제목에서 규칙 기반으로 감성 점수를 산출.
NLP 모델 없이 사전 매핑만으로 동작.
"""

# ===== 공시 카테고리별 감성 사전 =====
CATEGORY_SENTIMENT = {
    # === 강한 호재 (+) ===
    "자기주식취득결정":            +0.8,  # 회사가 자사주 매입 → 주주환원
    "주식배당결정":               +0.6,
    "무상증자결정":               +0.7,  # 기존 주주 추가 주식 지급
    "타법인주식및출자증권취득결정":  +0.5,  # M&A, 사업 확장

    # === 강한 악재 (-) ===
    "유상증자결정":               -0.7,  # 지분 희석
    "전환사채권발행결정":          -0.5,  # 잠재적 지분 희석
    "감자결정":                   -0.8,  # 주식 수 감소 (보통 악재)
    "영업정지":                   -1.0,
    "회생절차개시":               -1.0,
    "관리종목지정":               -0.9,
    "불성실공시법인지정":          -0.6,
    "소송등의제기":               -0.3,

    # === 중립 / 상황 의존 ===
    "대표이사변경":               +0.1,
    "합병결정":                   +0.2,
    "분할결정":                   +0.1,
    "최대주주변경":               +0.3,
}

# ===== 실적 관련 키워드 (공시 제목에서 매칭) =====
EARNINGS_KEYWORDS = {
    "영업이익증가":  +0.6,
    "영업이익감소":  -0.6,
    "흑자전환":      +0.8,
    "적자전환":      -0.8,
    "매출액증가":    +0.4,
    "매출액감소":    -0.4,
    "사상최대":      +0.7,
    "최대실적":      +0.7,
}

def score_single_disclosure(category: str, title: str) -> float:
    """
    단일 공시의 감성 점수 산출.
    반환값: -1.0 ~ +1.0
    """
    score = CATEGORY_SENTIMENT.get(category, 0.0)

    for keyword, value in EARNINGS_KEYWORDS.items():
        if keyword in title:
            score = max(-1.0, min(1.0, score + value))
            break  # 첫 매칭 키워드만 반영

    return round(score, 2)

def disclosure_adjustment(disclosures: list[dict], lookback_days: int = 30) -> float:
    """
    최근 N일 공시의 감성 점수를 시간 감쇠 가중 평균하여 최종 보정값 반환.

    규칙:
    - 오늘 공시 → 가중치 1.0
    - 30일 전 공시 → 가중치 0.1
    - 시간에 따라 선형 감쇠
    - 카테고리/키워드 모두 매칭 안 되는 공시(sentiment=0.0)는 무시
    - 최종 보정값: -10.0 ~ +10.0

    반환값: float (-10.0 ~ +10.0), stock_scores.disclosure_adjustment 컬럼에 저장
    """
    if not disclosures:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0

    for disc in disclosures:
        sentiment = score_single_disclosure(disc.get('category', ''), disc.get('title', ''))
        if sentiment == 0.0:
            continue

        days_ago = disc.get('days_ago', 0)
        time_weight = max(0.1, 1.0 - (days_ago / lookback_days) * 0.9)

        weighted_sum += sentiment * time_weight
        weight_total += time_weight

    if weight_total == 0:
        return 0.0

    avg_sentiment = weighted_sum / weight_total     # -1.0 ~ +1.0
    adjustment = avg_sentiment * 10                  # -10.0 ~ +10.0

    return round(max(-10.0, min(10.0, adjustment)), 2)
```

#### aggregator.py 변경점

```python
# 최종 점수에 공시 보정 가감
recent_disclosures = db.get_recent_disclosures(code, days=30)
disc_adj = disclosure_adjustment(recent_disclosures)

adjusted_total = total_score + macro_adj + disc_adj
# stock_scores.disclosure_adjustment 컬럼에 저장
```

#### 테스트 케이스

```
- 카테고리 "자기주식취득결정" → +0.8
- 카테고리 "유상증자결정" → -0.7
- 카테고리 매칭 안됨 + 제목에 "흑자전환" → +0.8
- 카테고리 "합병결정" + 제목에 "사상최대" → min(1.0, 0.2+0.7) = +0.9
- 공시 없음 → 0.0
- 오늘 공시 -0.7 + 30일 전 공시 +0.8 → 시간 감쇠 적용 후 음수 (최근 악재 우세)
- 결과값이 -10 ~ +10 범위 내 클리핑
```

#### 완료 기준

- [x] `score_single_disclosure()`가 카테고리/키워드 조합으로 올바른 점수 반환
- [x] `disclosure_adjustment()`가 시간 감쇠를 적용한 가중 평균 산출
- [x] `stock_scores.disclosure_adjustment`에 보정값 저장
- [x] `disclosures.sentiment_score` 컬럼도 공시별 점수로 업데이트
- [x] 단위 테스트 전체 통과

---

### STEP F: 뉴스 감성

**목적**: 빅카인즈 API로 수집한 뉴스 제목에서 키워드 기반 감성 점수를 산출하여 최종 점수를 보정한다.

**배경 지식**:
- 뉴스는 공시보다 노이즈가 많음 (광고성 기사, 상반된 논조)
- 따라서 보정 범위를 공시(-10~+10)보다 좁게(-5~+5) 설정
- 빅카인즈 API (한국언론진흥재단) = 무료, 일 3,000건, robots.txt 위반 없음

**영향 범위**: `collector/news_collector.py`, `scoring/news_scorer.py`, `scoring/aggregator.py`

**선행 조건**: 빅카인즈 API 키 발급 (https://www.bigkinds.or.kr/)

#### 파일 1: `collector/news_collector.py`

```python
"""
빅카인즈 API에서 종목 관련 뉴스를 수집.
API 문서: https://www.bigkinds.or.kr/api/

수집 대상: 추천 후보 350개 종목의 최근 7일 뉴스 제목
저장: 별도 news 테이블 또는 메모리에서 직접 처리 (MVP는 메모리)

주의:
- 일 3,000건 제한 → 종목당 최대 8~9건
- 종목명으로 검색 (code가 아니라 name)
- 뉴스 본문은 수집하지 않음 (제목만 사용)

호출 예시:
import requests

response = requests.post(
    'https://tools.kinds.or.kr:8888/search/news',
    json={
        'access_key': BIGKINDS_API_KEY,
        'argument': {
            'query': '삼성전자',
            'published_at': {
                'from': '2024-12-01',
                'until': '2024-12-07'
            },
            'sort': {'date': 'desc'},
            'return_from': 0,
            'return_size': 10,
            'fields': ['title', 'published_at']
        }
    }
)
"""
```

#### 파일 2: `scoring/news_scorer.py`

```python
# scoring/news_scorer.py

"""
뉴스 제목 키워드 매칭으로 감성 점수 산출.
공시보다 신뢰도가 낮으므로 보정 범위를 ±5로 제한.
"""

POSITIVE_KEYWORDS = [
    '사상최대', '수주', '흑자전환', '실적개선', '상향',
    '목표가상향', '매수추천', '호실적', '신고가', '돌파',
    '수출호조', '대규모투자', '신사업', '특허취득', '기술혁신',
]

NEGATIVE_KEYWORDS = [
    '적자', '하향', '감소', '리콜', '소송', '횡령',
    '부실', '매도', '급락', '하한가', '워크아웃',
    '목표가하향', '실적부진', '감원', '구조조정', '부도',
]

def score_news_title(title: str) -> float:
    """
    단일 뉴스 제목의 감성 점수.
    반환값: -1.0 ~ +1.0
    """
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in title)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in title)

    total = pos_count + neg_count
    if total == 0:
        return 0.0

    return round((pos_count - neg_count) / total, 2)

def news_adjustment(news_titles: list[str]) -> float:
    """
    최근 7일 뉴스 제목들의 감성 평균 → 최종 보정값.

    규칙:
    - 키워드 매칭 안 되는 뉴스(score=0.0)는 무시
    - 유효 뉴스가 3건 미만이면 보정 없음 (노이즈 방지)
    - 최종 보정값: -5.0 ~ +5.0

    반환값: float (-5.0 ~ +5.0), stock_scores.news_adjustment 컬럼에 저장
    """
    if not news_titles:
        return 0.0

    scores = [score_news_title(t) for t in news_titles]
    valid_scores = [s for s in scores if s != 0.0]

    # 유효 뉴스가 3건 미만이면 신뢰도 부족 → 보정 없음
    if len(valid_scores) < 3:
        return 0.0

    avg = sum(valid_scores) / len(valid_scores)   # -1.0 ~ +1.0
    adjustment = avg * 5                           # -5.0 ~ +5.0

    return round(max(-5.0, min(5.0, adjustment)), 2)
```

#### aggregator.py 최종 변경점

```python
# STEP E + F 모두 적용된 최종 점수 산출
adjusted_total = total_score + macro_adj + disc_adj + news_adj

# stock_scores 테이블에 저장:
# - macro_adjustment = macro_adj
# - disclosure_adjustment = disc_adj
# - news_adjustment = news_adj
# - adjusted_total_score = adjusted_total
```

#### 테스트 케이스

```
- 제목 "삼성전자 사상최대 실적" → +1.0
- 제목 "A기업 적자전환 구조조정" → -1.0
- 제목 "신규 사업 검토 중" (키워드 없음) → 0.0
- 유효 뉴스 2건 → 보정 없음 (3건 미만)
- 긍정 5건 + 부정 2건 → 양수 보정
- 결과값이 -5 ~ +5 범위 내 클리핑
```

#### 완료 기준

- [x] `news_collector.py`가 빅카인즈 API에서 종목별 뉴스 제목 수집
- [x] `score_news_title()`이 키워드 매칭으로 올바른 점수 반환
- [x] `news_adjustment()`가 3건 미만 필터링 + 범위 클리핑 적용
- [x] `stock_scores.news_adjustment`에 보정값 저장
- [x] 단위 테스트 전체 통과

---

### 고도화 STEP 적용 후 최종 스코어 산출 흐름

```
[1단계] Market Regime 판단 (STEP C 적용)
  └── 코스피 MA20/MA60 + 장단기 금리차 → BULL / BEAR / CAUTIOUS_BULL / RECOVERING
  └── 도메인 가중치 결정

[2단계] 금리 트렌드 판단 (STEP A)
  └── 기준금리 3개월 변동 → RISING / FALLING / STABLE
  └── FundamentalScorer 내부 가중치(PER/ROE 비중) 조절

[3단계] 미국 시장 체크 (STEP D)
  └── S&P500 전일 -3% 이상 → 추천 보류, 파이프라인 중단
  └── -2% ~ -3% → 경고 로그, 진행

[4단계] 종목별 기본 스코어링
  └── 기술점수 × 가중치 + 재무점수 × 40% + 모멘텀점수 × 가중치
  └── = total_score (0~100)

[5단계] 매크로 보정 (STEP B + D)
  └── 환율 → 섹터별 가감 (-5 ~ +5)
  └── 미국 시장 하락 + 고모멘텀 → 추가 감점 (-3)
  └── = macro_adjustment

[6단계] 공시 보정 (STEP E)
  └── 최근 30일 공시 감성 → 시간 감쇠 가중 평균
  └── = disclosure_adjustment (-10 ~ +10)

[7단계] 뉴스 보정 (STEP F)
  └── 최근 7일 뉴스 감성 → 키워드 평균
  └── = news_adjustment (-5 ~ +5)

[8단계] 최종 정렬
  └── adjusted_total_score = total_score + macro_adj + disc_adj + news_adj
  └── Top 5 추천
```

### 고도화 구현 순서 및 검증 원칙

> **한 번에 하나의 STEP만 추가**하고, 추가 전/후 백테스트 결과를 비교한다.

| 순서 | STEP | 백테스트 비교 기준 |
|---|---|---|
| 1 | STEP A (금리→재무 가중치) | 평균 alpha 개선 여부 |
| 2 | STEP B (환율→섹터 보정) | 수출/수입 섹터 추천의 승률 변화 |
| 3 | STEP C (금리차→Regime 보강) | Regime 전환 구간에서의 성과 변화 |
| 4 | STEP D (미국 급락→보류) | 보류된 날의 가상 추천 성과 vs 실제 보류 효과 |
| 5 | STEP E (공시 감성) | 공시 보정 적용 종목의 승률 변화 |
| 6 | STEP F (뉴스 감성) | 뉴스 보정 적용 종목의 승률 변화 |

```
검증 원칙:
- STEP 추가 후 평균 alpha가 악화되면 → 해당 STEP을 비활성화하고 원인 분석
- 비활성화 방법: aggregator.py에서 해당 adjustment를 0.0으로 고정
- 2개 이상 STEP을 동시에 추가하지 않는다 (효과 분리 불가)
```
