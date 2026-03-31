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
| 3-1 | `src/collector/finance_collector.py` | ⬜ 미구현 | DART API 재무제표 |
| 3-2 | `src/collector/disclosure_collector.py` | ⬜ 미구현 | DART API 공시 |
| **4단계 — 스코어링 기반** | | | |
| 4-1 | `src/scoring/__init__.py` | ⬜ 미구현 | |
| 4-2 | `src/scoring/base.py` | ⬜ 미구현 | BaseScorer ABC |
| 4-3 | `src/scoring/market_regime.py` | ⬜ 미구현 | MA20/MA60 기반 BULL/BEAR 판단 |
| 4-4 | `src/scoring/filters.py` | ⬜ 미구현 | 추천 제외 필터 |
| **5단계 — 스코어러** | | | |
| 5-1 | `src/scoring/technical.py` | ⬜ 미구현 | RSI, MACD, 볼린저밴드 |
| 5-2 | `src/scoring/fundamental.py` | ⬜ 미구현 | PER, PBR, ROE, 부채비율 (섹터 상대비교) |
| 5-3 | `src/scoring/momentum.py` | ⬜ 미구현 | 거래량 급증, 기관 순매수, 52주 신고가 |
| **6단계 — 집계 및 엔트리** | | | |
| 6-1 | `src/scoring/aggregator.py` | ⬜ 미구현 | 가중합 → 최종점수 → Top5 |
| 6-2 | `src/main.py` | ⬜ 미구현 | APScheduler 16:30 자동 실행 |
| **7단계 — 백테스트** | | | |
| 7-1 | `src/backtest/__init__.py` | ⬜ 미구현 | |
| 7-2 | `src/backtest/evaluator.py` | ⬜ 미구현 | 추천 후 1/5/20/60일 수익률 |
| **8단계 — 알림** | | | |
| 8-1 | `src/notification/__init__.py` | ⬜ 미구현 | |
| 8-2 | `src/notification/slack_notifier.py` | ⬜ 미구현 | Slack Incoming Webhook |
| **테스트** | | | |
| T-1 | `tests/test_technical.py` | ⬜ 미구현 | |
| T-2 | `tests/test_fundamental.py` | ⬜ 미구현 | |
| T-3 | `tests/test_momentum.py` | ⬜ 미구현 | |
| T-4 | `tests/test_market_regime.py` | ⬜ 미구현 | |
| T-5 | `tests/test_filters.py` | ⬜ 미구현 | |
| T-6 | `tests/test_aggregator.py` | ⬜ 미구현 | |

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

## 다음 단계 작업 예정

3단계: DART API 수집기 구현
- `src/collector/finance_collector.py`: opendartreader로 재무제표 수집
- `src/collector/disclosure_collector.py`: opendartreader로 공시 목록 수집