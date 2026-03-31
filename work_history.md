# 작업 이력

## 최종 업데이트: 2026-03-31

---

## 단계별 구현 현황

| 단계 | 파일 | 상태 | 비고 |
|------|------|------|------|
| **1단계 — DB 기반** | | | |
| 1-1 | `docker-compose.yml` | ✅ 완료 | TimescaleDB PG15 + Redis 7 |
| 1-2 | `.env.example` | ✅ 완료 | 환경변수 템플릿 |
| 1-3 | `pyproject.toml` | ✅ 완료 | Poetry 의존성 정의 |
| 1-4 | `src/__init__.py` | ✅ 완료 | 패키지 루트 |
| 1-5 | `src/config.py` | ✅ 완료 | pydantic-settings 기반 설정 로딩 |
| 1-6 | `src/utils/__init__.py` | ✅ 완료 | |
| 1-7 | `src/utils/logger.py` | ✅ 완료 | loguru 설정 |
| 1-8 | `src/db/__init__.py` | ✅ 완료 | |
| 1-9 | `src/db/connection.py` | ✅ 완료 | psycopg2 ThreadedConnectionPool + DBConnection context manager |
| 1-10 | `src/db/schema.sql` | ✅ 완료 | 전체 DDL (TimescaleDB hypertable 포함) |
| 1-11 | `src/db/repository.py` | ✅ 완료 | 쿼리 함수 전체 (stocks, prices, investor, index, financials, disclosures, scores) |
| 1-12 | `tests/__init__.py` | ✅ 완료 | |
| **2단계 — 수집기 (pykrx)** | | | |
| 2-1 | `src/collector/__init__.py` | ✅ 완료 | |
| 2-2 | `src/collector/price_collector.py` | ✅ 완료 | pykrx 주가/거래량/시총 |
| 2-3 | `src/collector/investor_collector.py` | ✅ 완료 | pykrx 투자자별 매매동향 |
| 2-4 | `src/collector/index_collector.py` | ✅ 완료 | pykrx 코스피 지수 |
| **3단계 — 수집기 (DART)** | | | |
| 3-1 | `src/collector/finance_collector.py` | ✅ 완료 | DART API 재무제표 |
| 3-2 | `src/collector/disclosure_collector.py` | ✅ 완료 | DART API 공시 |
| **4단계 — 스코어링 기반** | | | |
| 4-1 | `src/scoring/__init__.py` | ✅ 완료 | |
| 4-2 | `src/scoring/base.py` | ✅ 완료 | BaseScorer ABC, ScoreResult dataclass |
| 4-3 | `src/scoring/market_regime.py` | ✅ 완료 | MA20/MA60 기반 BULL/BEAR 판단 |
| 4-4 | `src/scoring/filters.py` | ✅ 완료 | 추천 제외 필터 |
| **5단계 — 스코어러** | | | |
| 5-1 | `src/scoring/technical.py` | ✅ 완료 | RSI, MACD, 볼린저밴드 |
| 5-2 | `src/scoring/fundamental.py` | ✅ 완료 | PER, PBR, ROE, 부채비율 (섹터 상대비교) |
| 5-3 | `src/scoring/momentum.py` | ✅ 완료 | 거래량 급증, 기관 순매수, 52주 신고가 |
| **6단계 — 집계 및 엔트리** | | | |
| 6-1 | `src/scoring/aggregator.py` | ✅ 완료 | 가중합 → 최종점수 → Top5 |
| 6-2 | `src/main.py` | ✅ 완료 | APScheduler 16:30 자동 실행 |
| **7단계 — 백테스트** | | | |
| 7-1 | `src/backtest/__init__.py` | ✅ 완료 | |
| 7-2 | `src/backtest/evaluator.py` | ✅ 완료 | 추천 후 1/5/20/60일 수익률 |
| **8단계 — 알림** | | | |
| 8-1 | `src/notification/__init__.py` | ⬜ 미구현 | |
| 8-2 | `src/notification/slack_notifier.py` | ⬜ 미구현 | Slack Incoming Webhook |
| **테스트** | | | |
| T-1 | `tests/test_technical.py` | ✅ 완료 | |
| T-2 | `tests/test_fundamental.py` | ✅ 완료 | |
| T-3 | `tests/test_momentum.py` | ✅ 완료 | |
| T-4 | `tests/test_market_regime.py` | ✅ 완료 | |
| T-5 | `tests/test_filters.py` | ✅ 완료 | |
| T-6 | `tests/test_aggregator.py` | ✅ 완료 | |

---

## 1단계 완료 메모

- `docker-compose.yml`: `./src/db/schema.sql`을 init sql로 마운트. DB_PASSWORD 환경변수 없으면 `stockpass` 기본값 사용.
- `src/config.py`: `.env` 파일을 자동 로딩. `settings.db_dsn` 프로퍼티로 psycopg2 DSN 문자열 반환.
- `src/db/connection.py`: `ThreadedConnectionPool` 사용. `DBConnection` context manager로 트랜잭션/롤백 자동 처리.
- `src/db/schema.sql`: `IF NOT EXISTS`, `if_not_exists => TRUE` 옵션으로 멱등 실행 가능.
- `src/db/repository.py`:
  - `get_latest_financials()`: `disclosed_at <= as_of_date` 조건으로 look-ahead bias 방지.
  - `get_all_financials()` / `get_financials_grouped_by_sector()`: 루프 밖 캐싱용 메서드.
  - `bulk_insert_prices()` / `bulk_insert_investor_trading()`: `execute_batch`로 배치 upsert.

## 2단계 완료 메모 (2026-03-31)

- `src/collector/__init__.py`: 빈 패키지 파일
- `src/collector/price_collector.py`:
  - `PriceCollector.get_target_pool(date)`: 코스피200(1028) + 코스닥150(2203) 구성종목 조회
  - `collect_stock_master()`: 종목 이름·시장 upsert (sector/listed_at은 이 단계에서 None)
  - `collect_prices_for_ticker()`: `get_market_ohlcv_by_date` + `get_market_cap_by_date` 합산 → `bulk_insert_prices`
  - `run(fromdate, todate, ref_date)`: 전체 수집 진입점
  - `REQUEST_DELAY = 0.5`: pykrx rate limit 방지, investor/index에서 공유
- `src/collector/investor_collector.py`:
  - `InvestorCollector.collect_for_ticker()`: `get_market_trading_value_by_date` → 기관합계/외국인합계/개인 순매수 추출
  - 컬럼명 후보 목록으로 pykrx 버전 차이 대응 (`_INST_COLS`, `_FOREIGN_COLS`, `_RETAIL_COLS`)
  - `PriceCollector`에 의존해 종목 풀 재사용
- `src/collector/index_collector.py`:
  - `IndexCollector.collect()`: `get_index_ohlcv_by_date("1001")` → `bulk_insert_index_prices`
  - 종가 컬럼명 후보 탐색(`_find_close_col`) — 한글/영문 대응

## 3~7단계 완료 메모 (2026-03-31)

### 3단계 — DART 수집기

- `src/collector/finance_collector.py`:
  - `FinanceCollector._build_corp_code_map()`: `dart.corp_codes`로 stock_code → corp_code 맵 구성
  - `collect_for_ticker(stock_code, bsns_year)`: 4개 보고서코드(11011/11012/11013/11014) 순회
  - `rcept_no` 앞 8자리에서 공시일(disclosed_at) 파싱 — look-ahead bias 방지
  - BS/IS/CIS sj_div로 분리하여 계정명 후보 목록(`ACCOUNT_MAP`)으로 금액 추출
  - ROE / 부채비율 / 영업이익률 직접 계산; PER/PBR은 None (별도 계산 필요)

- `src/collector/disclosure_collector.py`:
  - `dart.list(corp_code, start, end, kind='A', final='T')`으로 공시 목록 조회
  - `_categorize(report_nm)`: DANGER_KEYWORD_MAP 키워드 매핑으로 카테고리 분류
  - sentiment_score는 항상 NULL
  - `FinanceCollector._corp_code_map` 재사용으로 중복 API 호출 방지

### 4단계 — 스코어링 기반

- `src/scoring/base.py`:
  - `ScoreResult` dataclass: 모든 sub-score + total_score + rank + market_regime
  - `BaseScorer.score(code, **kwargs)`: LSP 준수 공통 시그니처
  - `BaseScorer.percentile_score()`: `scipy.stats.percentileofscore` 래핑

- `src/scoring/market_regime.py`: CLAUDE.md 명세 그대로 구현
  - BULL: tech=0.20, fund=0.40, mom=0.40
  - BEAR: tech=0.45, fund=0.40, mom=0.15

- `src/scoring/filters.py`:
  - 4가지 필터: 비활성 / 60거래일 미만 / 5일 거래량0 / 위험공시(30일내)
  - `should_exclude(code, db) → (bool, str)` 인터페이스

### 5단계 — 스코어러

- `src/scoring/technical.py`: 역추세(contrarian) 전략
  - RSI: Wilder EMA 방식, score = 100 - RSI (과매도→고점수)
  - MACD: histogram → z-score → sigmoid → 0~100
  - 볼린저밴드: %B 역방향 (하단 근접→고점수)
  - MIN_PERIODS=5 미만 시 모두 50.0 반환

- `src/scoring/fundamental.py`: 섹터 상대비교 (CLAUDE.md 핵심 규칙 준수)
  - MIN_SECTOR_SIZE=5 미만 시 전체 폴백
  - PER/PBR: 낮을수록 고점수 (100 - percentile)
  - ROE: 높을수록 고점수 (percentile)
  - 부채비율: 낮을수록 고점수 (100 - percentile)
  - 섹터 평균 대비 20% 이상 PER 할인 → +10 보너스

- `src/scoring/momentum.py`: 추세추종(trend-following) 전략
  - 거래량: ratio/5×100 (5배=100점), 5배 이상 cap
  - 기관 순매수: 누적합 z-score → sigmoid
  - 52주 신고가: close/high52×100 (신고가 갱신=100점)

### 6단계 — 집계 및 메인

- `src/scoring/aggregator.py`:
  - `ScoreAggregator.aggregate()`: None 부문 → 50.0 대체 후 가중합
  - `run()`: 실패율 30% 초과 시 빈 리스트 반환, market_regime 설정
  - `get_top_n()`: total_score 내림차순, rank 1~5 부여

- `src/main.py`:
  - `run_daily()`: Market Regime → 재무캐시 → 필터→스코어링 → 집계 → DB저장
  - 재무 데이터는 루프 밖에서 한 번만 조회 (`get_all_financials`, `get_financials_grouped_by_sector`)
  - APScheduler `BlockingScheduler`, `CronTrigger(hour=16, minute=30, tz=Asia/Seoul)`
  - SIGINT/SIGTERM 처리로 graceful shutdown
  - `misfire_grace_time=300`, `coalesce=True`

### 7단계 — 백테스트

- `src/backtest/evaluator.py`:
  - `evaluate_recommendation()`: 추천일 종가 기준 1/5/20/60거래일 후 수익률 계산
  - 달력일 버퍼(CALENDAR_DAYS_BUFFER) 사용으로 비거래일 처리
  - 코스피 지수(`1001`) 벤치마크 수익률도 함께 저장
  - `run()`: 미평가 추천만 선별 처리, 아직 기간 미경과 건 스킵
  - `run_for_date(date)`: 특정 날짜 재평가 지원

- `src/db/repository.py` 추가 메서드:
  - `get_all_recommendations()`
  - `get_price_on_date(code, target_date)`: date ≤ target_date 최근 종가
  - `save_recommendation_return(data)`
  - `get_recommendation_returns(recommendation_id)`

### 테스트 (단위 테스트 전체)

- `test_market_regime.py`: BULL/BEAR 판단, 가중치 값, 합산=1.0 검증
- `test_technical.py`: 하락50일→RSI≥70, 상승50일→RSI≤30, 5일미만→50.0
- `test_fundamental.py`: 최저PER→≥90, 섹터폴백, 음수PER→30.0, 할인보너스
- `test_momentum.py`: 5배급증→100, 평균→20, 신고가→100, 빈데이터→50.0
- `test_filters.py`: mock DB 사용, 5가지 위험공시 카테고리 파라미터화 테스트
- `test_aggregator.py`: BULL/BEAR 가중합, 실패율30% 경계, 빈입력

## 다음 단계 작업 예정

8단계: Slack 알림 연동
- `src/notification/__init__.py`
- `src/notification/slack_notifier.py`: Slack Incoming Webhook으로 Top5 전송