# Stock Recommender

코스피200 + 코스닥150 (약 350개) 종목을 매일 장마감 후 스코어링하여 상위 5개 종목을 추천하는 Python 자동화 시스템.

---

## 목차

1. [핵심 공식](#핵심-공식)
2. [구현 현황](#구현-현황)
3. [사전 준비 — 처음 설치하는 경우](#사전-준비--처음-설치하는-경우)
   - [1. Python 설치](#1-python-설치)
   - [2. Git 설치](#2-git-설치)
   - [3. Poetry 설치](#3-poetry-설치)
   - [4. Docker Desktop 설치](#4-docker-desktop-설치)
4. [프로젝트 설정](#프로젝트-설정)
   - [1. 저장소 클론](#1-저장소-클론)
   - [2. 환경 변수 파일 생성](#2-환경-변수-파일-생성)
   - [3. PowerShell 인코딩 설정 (Windows 필수)](#3-powershell-인코딩-설정-windows-필수)
   - [4. DB + Redis 컨테이너 기동](#4-db--redis-컨테이너-기동)
   - [5. Python 의존성 설치](#5-python-의존성-설치)
5. [데이터 초기 적재](#데이터-초기-적재)
6. [실행 방법](#실행-방법)
7. [테스트](#테스트)
8. [백테스트](#백테스트)
9. [프로젝트 구조](#프로젝트-구조)
10. [트러블슈팅](#트러블슈팅)

---

## 핵심 공식


```
최종점수 = 기술점수(가변%) + 재무점수(40%) + 모멘텀점수(가변%)
```

| 시장 상태 | 기술점수 | 재무점수 | 모멘텀점수 |
|---|---|---|---|
| BULL (MA20 > MA60) | 20% | 40% | 40% |
| BEAR (MA20 ≤ MA60) | 45% | 40% | 15% |

---

## 구현 현황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1단계 | Docker Compose + DB 스키마 + PriceCollector + InvestorCollector + IndexCollector | 완료 |
| 2단계 | FinanceCollector + DisclosureCollector | 완료 |
| 3단계 | MarketRegime + Filters + TechnicalScorer | 완료 |
| 4단계 | FundamentalScorer + MomentumScorer + Aggregator | 완료 |
| 5단계 | main.py (APScheduler 16:30 자동 실행) | 완료 |
| 6단계 | BacktestEvaluator (1/5/20/60일 수익률) | 완료 |
| 7단계 | Slack 알림 | 미구현 |

---

## 사전 준비 — 처음 설치하는 경우

> 이미 설치되어 있는 항목은 건너뜁니다. 각 단계 끝의 확인 명령으로 설치 여부를 먼저 점검하세요.

### 1. Python 설치

**확인 먼저:**
```powershell
python --version
```
`Python 3.11.x` 이상이 출력되면 건너뜁니다.

**Windows 설치 방법:**

1. [python.org/downloads](https://www.python.org/downloads/) 접속
2. **Python 3.13.x** (최신 안정 버전) 다운로드
3. 설치 시 **반드시** 아래 옵션 체크:
   - `Add Python to PATH` ← 이걸 빠뜨리면 터미널에서 python 명령이 안 됨
   - `Install for all users` (선택)
4. 설치 완료 후 PowerShell을 **새로 열고** 확인:

```powershell
python --version
# Python 3.13.x
pip --version
# pip 24.x.x
```

> **Microsoft Store 버전은 사용하지 마세요.** 권한 문제로 Poetry, psycopg2 등 일부 패키지 설치가 실패합니다.
> 반드시 python.org에서 직접 다운로드합니다.

---

### 2. Git 설치

**확인 먼저:**
```powershell
git --version
```
버전이 출력되면 건너뜁니다.

**Windows 설치 방법:**

1. [git-scm.com](https://git-scm.com/download/win) 접속 → `64-bit Git for Windows Setup` 다운로드
2. 설치 옵션은 모두 기본값으로 진행해도 됩니다.
3. 설치 완료 후 PowerShell을 새로 열고 확인:

```powershell
git --version
# git version 2.x.x
```

---

### 3. Poetry 설치

**확인 먼저:**
```powershell
poetry --version
```
버전이 출력되면 건너뜁니다.

**Windows 설치 방법 (PowerShell에서 실행):**

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
```

설치 완료 후 Poetry 경로를 PATH에 추가합니다.

```powershell
# 아래 경로를 시스템 환경변수 PATH에 추가
# C:\Users\<사용자명>\AppData\Roaming\Python\Scripts

# 또는 PowerShell 프로필에 추가 (터미널마다 자동 적용):
$env:PATH += ";$env:APPDATA\Python\Scripts"
```

PowerShell을 **새로 열고** 확인:

```powershell
poetry --version
# Poetry (version 1.x.x)
```

> `poetry` 명령을 못 찾는다면 PATH 설정이 안 된 것입니다.
> `C:\Users\<사용자명>\AppData\Roaming\Python\Scripts` 경로를 시스템 환경변수에 수동 추가하세요.
> (제어판 → 시스템 → 고급 시스템 설정 → 환경 변수)

---

### 4. Docker Desktop 설치

**확인 먼저:**
```powershell
docker --version
docker compose version
```
둘 다 버전이 출력되면 건너뜁니다.

**Windows 설치 방법:**

1. [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) 접속 → `Docker Desktop for Windows` 다운로드
2. 설치 시 **WSL 2 backend** 선택 (권장)
   - WSL 2 미설치 시 설치 도중 안내가 나옴 → 안내에 따라 설치
3. 설치 완료 후 Docker Desktop 앱을 **실행**하고 고래 아이콘(트레이)이 초록색이 될 때까지 대기
4. PowerShell을 새로 열고 확인:

```powershell
docker --version
# Docker version 27.x.x
docker compose version
# Docker Compose version v2.x.x
```

> Docker Desktop이 백그라운드에서 **실행 중**이어야 합니다.
> 컴퓨터를 재시작하면 Docker Desktop을 다시 켜야 합니다.

---

## 프로젝트 설정

> 여기서부터는 Python, Git, Poetry, Docker Desktop이 모두 설치된 상태를 전제합니다.

### 1. 저장소 클론

```powershell
git clone <repo-url>
cd stock-recommender
```

---

### 2. 환경 변수 파일 생성

`.env.example`을 복사하여 `.env`를 만들고 값을 채웁니다.

```powershell
copy .env.example .env
```

`.env` 파일을 텍스트 편집기로 열어 아래 항목을 수정합니다:

```env
# ── Database ──────────────────────────────────────────────────────
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock_recommender
DB_USER=postgres
DB_PASSWORD=stockpass       # docker-compose.yml 기본값과 반드시 일치시킬 것

# ── Redis ─────────────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379

# ── DART API ──────────────────────────────────────────────────────
# https://opendart.fss.or.kr/ 에서 회원가입 후 발급
# 재무제표·공시 수집에 필요. 가격/투자자/지수는 API 키 없이 수집 가능.
DART_API_KEY=your_dart_api_key_here

# ── Slack (7단계 — 현재 미구현) ───────────────────────────────────
SLACK_WEBHOOK_URL=

# ── 스케줄링 ──────────────────────────────────────────────────────
SCHEDULE_HOUR=16
SCHEDULE_MINUTE=30
```

> `.env` 파일은 `.gitignore`에 포함되어 있습니다. **절대 커밋하지 마세요.**

---

### 3. PowerShell 인코딩 설정 (Windows 필수)

로그 메시지에 한국어가 포함되어 있어 Windows 기본 인코딩(CP949/CP1252)에서 출력이 깨지거나 **아무것도 안 뜨는 증상**이 발생합니다.
데이터 수집·실행 전에 **반드시** 아래 명령을 먼저 실행하세요.

```powershell
# PowerShell 세션에서 UTF-8 강제 적용 (터미널 재시작 시 다시 실행 필요)
$env:PYTHONUTF8 = "1"
chcp 65001
```

매번 입력하기 귀찮다면 PowerShell 프로필에 영구 등록합니다:

```powershell
# 프로필 파일 열기 (없으면 자동 생성)
notepad $PROFILE

# 아래 두 줄 추가 후 저장
$env:PYTHONUTF8 = "1"
chcp 65001 | Out-Null
```

---

### 4. DB + Redis 컨테이너 기동

Docker Desktop이 실행 중인 상태에서 진행합니다.

```powershell
# 백그라운드 실행
docker compose up -d
```

30초 정도 기다린 후 상태를 확인합니다:

```powershell
docker compose ps
```

정상 기동 시 출력:

```
NAME          IMAGE                               STATUS
stock-db      timescale/timescaledb:latest-pg15   Up
stock-redis   redis:7-alpine                      Up
```

> `src/db/schema.sql` (DDL 전체)이 컨테이너 **최초 기동 시 자동 적용**됩니다.
> 볼륨(`pgdata`)이 남아있으면 재기동해도 schema.sql이 다시 실행되지 않습니다.
> 스키마를 처음부터 다시 적용하려면 `docker compose down -v` 후 재기동하세요.

DB 접속이 정상인지 확인 (선택):

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "\dt"
```

아래와 같이 테이블 목록이 나오면 정상입니다:

```
             List of relations
 Schema |          Name           | Type  |  Owner
--------+-------------------------+-------+----------
 public | daily_prices            | table | postgres
 public | disclosures             | table | postgres
 public | financials              | table | postgres
 public | index_prices            | table | postgres
 public | investor_trading        | table | postgres
 public | recommendation_returns  | table | postgres
 public | recommendations         | table | postgres
 public | sectors                 | table | postgres
 public | stock_scores            | table | postgres
 public | stocks                  | table | postgres
```

---

### 5. Python 의존성 설치

```powershell
poetry install
```

설치 완료 후 가상환경 확인:

```powershell
poetry env info
```

`Python` 항목에 3.11 이상이 표시되면 정상입니다.

설치되는 주요 패키지:

| 패키지 | 용도 |
|---|---|
| `pykrx` | 주가·투자자·지수 데이터 수집 (KRX 공식, API 키 불필요) |
| `opendartreader` | DART 재무제표·공시 수집 |
| `pandas`, `numpy` | 데이터 처리 |
| `ta` | 기술적 지표 (RSI, MACD, 볼린저밴드) |
| `psycopg2-binary` | PostgreSQL 연결 |
| `apscheduler` | 매일 16:30 스케줄링 |
| `pydantic-settings` | 환경 변수 로딩 |
| `loguru` | 구조화 로깅 |

---

## 데이터 초기 적재

스코어링 실행 전에 **최소 60거래일** 이상의 가격 데이터가 필요합니다.
**최초 1회만** 실행합니다. 이후 매일 스케줄러가 자동으로 당일 데이터를 수집합니다.

> 모든 명령은 프로젝트 루트(`stock-recommender/`)에서 실행합니다.
> `$env:PYTHONUTF8 = "1"` 설정이 적용된 PowerShell 세션이어야 합니다.

---

### Step 1. 가격 데이터 (pykrx — API 키 불필요)

코스피200 + 코스닥150 약 350개 종목의 OHLCV + 시총을 수집합니다.

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.price_collector import PriceCollector
setup_logger()
repo = StockRepository()
PriceCollector(repo).run('20240101', '20241231')
"
```

- `stocks`, `daily_prices` 테이블에 저장
- 소요 시간: **약 30~60분** (pykrx rate limit 0.5초 간격 × 350종목 × 2회)
- 수집 중 종목별 진행 상황이 로그로 출력됩니다

---

### Step 2. 투자자별 매매동향 (pykrx — API 키 불필요)

기관·외국인·개인 순매수 데이터를 수집합니다.

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.investor_collector import InvestorCollector
setup_logger()
repo = StockRepository()
InvestorCollector(repo).run('20240101', '20241231')
"
```

- `investor_trading` 테이블에 저장
- 소요 시간: **약 20~40분**

---

### Step 3. 코스피 지수 (Market Regime 판단용 — API 키 불필요)

Market Regime(BULL/BEAR) 판단에 사용되는 코스피 종합지수 종가를 수집합니다.
MA60 계산을 위해 **최소 60일치** 필요합니다.

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.index_collector import IndexCollector
setup_logger()
repo = StockRepository()
IndexCollector(repo).run('20240101', '20241231')
"
```

- `index_prices` 테이블에 저장
- 소요 시간: **약 1~2분**

---

### Step 4. 재무제표 (DART API — API 키 필요)

PER, PBR, ROE, 부채비율 등 재무 스코어링에 사용합니다.

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.finance_collector import FinanceCollector
setup_logger()
repo = StockRepository()
FinanceCollector(repo).run(years=[2023, 2024])
"
```

- `financials` 테이블에 저장
- 소요 시간: **약 1~2시간** (DART API 호출량 많음)
- DART API는 하루 10,000건 호출 제한 — 초과 시 다음 날 재시도

---

### Step 5. 공시 데이터 (DART API — API 키 필요)

관리종목·상장폐지·거래정지 등 위험 공시를 수집합니다. 추천 제외 필터에 사용합니다.

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.disclosure_collector import DisclosureCollector
setup_logger()
repo = StockRepository()
DisclosureCollector(repo).run('2024-01-01', '2024-12-31')
"
```

- `disclosures` 테이블에 저장

---

> **Step 4, 5는 선택 사항입니다.**
> DART API 키가 없어도 Step 1~3만으로 기술적·모멘텀 스코어링은 동작합니다.
> 재무 스코어는 기본값(50.0)으로 처리됩니다.

---

### 적재 현황 확인

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT
  (SELECT COUNT(*) FROM stocks)               AS stocks,
  (SELECT COUNT(DISTINCT code) FROM daily_prices)    AS price_codes,
  (SELECT COUNT(*) FROM daily_prices)         AS price_rows,
  (SELECT COUNT(*) FROM investor_trading)     AS investor_rows,
  (SELECT COUNT(*) FROM index_prices)         AS index_rows,
  (SELECT COUNT(*) FROM financials)           AS financial_rows;
"
```

---

## 실행 방법

### 스케줄러 모드 (운영용) — 매일 16:30 KST 자동 실행

```powershell
$env:PYTHONUTF8 = "1"
poetry run python -m src.main
```

실행 시 출력 예시:

```
2024-01-15 16:30:00 | INFO    | 스케줄러 시작 | 매일 16:30 KST 실행
2024-01-15 16:30:01 | INFO    | Market Regime: BULL | MA20=2534.2, MA60=2489.7
2024-01-15 16:30:02 | INFO    | 대상 종목 수: 347
...
2024-01-15 16:35:10 | INFO    | ====== Top 5 추천 ======
2024-01-15 16:35:10 | INFO    | #1 005380 | 총점=83.45
2024-01-15 16:35:10 | INFO    | #2 000660 | 총점=81.20
```

종료: `Ctrl+C`

---

### 즉시 1회 실행 (테스트용)

스케줄러 없이 파이프라인을 바로 실행합니다.

```powershell
$env:PYTHONUTF8 = "1"
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.main import run_daily
setup_logger()
init_pool()
run_daily()
close_pool()
"
```

---

### 로그 파일 확인

로그는 stderr 출력과 함께 `logs/` 디렉토리에 날짜별로 파일로 저장됩니다.

```powershell
# 오늘 로그 파일 실시간 확인 (PowerShell)
Get-Content "logs\stock-recommender_$(Get-Date -Format 'yyyy-MM-dd').log" -Wait
```

로그 파일은 매일 교체되며 **30일치** 자동 보관됩니다.

---

## 테스트

테스트는 **DB 없이** 실행됩니다 (Mock 사용).

```powershell
# 전체 테스트
poetry run pytest tests/ -v

# 커버리지 포함
poetry run pytest tests/ -v --cov=src --cov-report=term-missing

# 파일별 실행
poetry run pytest tests/test_technical.py -v
poetry run pytest tests/test_fundamental.py -v
poetry run pytest tests/test_momentum.py -v
poetry run pytest tests/test_market_regime.py -v
poetry run pytest tests/test_filters.py -v
poetry run pytest tests/test_aggregator.py -v
```

| 테스트 파일 | 주요 케이스 |
|---|---|
| `test_technical.py` | RSI ≤ 30 → 70점 이상, RSI ≥ 70 → 30점 이하, 데이터 5일 미만 → 50.0 |
| `test_fundamental.py` | 섹터 내 PER 최저 → 90점 이상, 섹터 5개 미만 → 전체 폴백, PER 음수/None → 30.0 |
| `test_momentum.py` | 거래량 5배 급증 → 100점, 데이터 없음 → 50.0, 52주 신고가 → 100점 |
| `test_market_regime.py` | MA20 > MA60 → BULL + 모멘텀 0.40, MA20 < MA60 → BEAR + 기술 0.45 |
| `test_filters.py` | 상장 60일 미만 → 제외, 5일 거래량 0 → 제외, 관리종목 공시 → 제외 |
| `test_aggregator.py` | 가중합·순위 계산, 실패율 30% 초과 → 추천 중단 |

---

## 백테스트

과거 추천 종목의 실제 수익률을 계산합니다 (추천 후 1/5/20/60 거래일 기준).

```powershell
# 미평가된 추천 전체 자동 평가
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.backtest.evaluator import BacktestEvaluator
setup_logger()
repo = StockRepository()
BacktestEvaluator(repo).run()
"
```

결과 조회 (psql):

```sql
SELECT r.date, r.rank, r.code,
       rr.days_after,
       rr.return_rate,
       rr.benchmark_rate,
       rr.return_rate - rr.benchmark_rate AS alpha
FROM recommendations r
JOIN recommendation_returns rr ON r.id = rr.recommendation_id
ORDER BY r.date DESC, r.rank;
```

---

## 프로젝트 구조

```
stock-recommender/
├── docker-compose.yml            # TimescaleDB(PG15) + Redis 7
├── pyproject.toml                # Poetry 의존성 관리
├── .env.example                  # 환경 변수 템플릿
├── .env                          # 실제 환경 변수 (gitignore — 커밋 금지)
│
├── src/
│   ├── main.py                   # 진입점 — APScheduler (16:30 KST)
│   ├── config.py                 # 환경 변수 로딩 (pydantic-settings)
│   │
│   ├── collector/
│   │   ├── price_collector.py    # pykrx: OHLCV + 시총 + 종목 마스터
│   │   ├── investor_collector.py # pykrx: 기관/외국인/개인 순매수
│   │   ├── index_collector.py    # pykrx: 코스피 지수 (Market Regime)
│   │   ├── finance_collector.py  # DART: 재무제표 (ROE, 부채비율 등)
│   │   └── disclosure_collector.py # DART: 공시 (위험 공시 필터용)
│   │
│   ├── scoring/
│   │   ├── base.py               # BaseScorer ABC, ScoreResult dataclass
│   │   ├── market_regime.py      # MA20/MA60 → BULL/BEAR + 동적 가중치
│   │   ├── filters.py            # 추천 제외 필터
│   │   ├── technical.py          # RSI, MACD, 볼린저밴드 (역추세)
│   │   ├── fundamental.py        # PER, PBR, ROE, 부채비율 (섹터 상대비교)
│   │   ├── momentum.py           # 거래량 급증, 기관 순매수, 52주 신고가
│   │   └── aggregator.py         # 가중합 → Top 5 추출
│   │
│   ├── backtest/
│   │   └── evaluator.py          # 추천 후 수익률 계산 + KOSPI 벤치마크
│   │
│   ├── db/
│   │   ├── connection.py         # psycopg2 커넥션 풀
│   │   ├── repository.py         # DB 쿼리 함수 전체
│   │   └── schema.sql            # DDL (TimescaleDB hypertable 포함)
│   │
│   ├── notification/
│   │   └── slack_notifier.py     # Slack 알림 (미구현)
│   │
│   └── utils/
│       └── logger.py             # loguru 설정
│
└── tests/
    ├── test_technical.py
    ├── test_fundamental.py
    ├── test_momentum.py
    ├── test_market_regime.py
    ├── test_filters.py
    └── test_aggregator.py
```

---

## 트러블슈팅

### 로그가 아무것도 안 뜨거나 실행이 멈춘 것처럼 보인다

**원인 1 — Windows 인코딩 문제 (가장 흔함)**

한국어 로그 메시지를 출력할 때 Windows 기본 인코딩이 UTF-8이 아니면 loguru가 내부 오류를 일으켜 아무것도 출력하지 않습니다.

```powershell
$env:PYTHONUTF8 = "1"
chcp 65001
# 위 명령 실행 후 다시 시도
```

**원인 2 — `setup_logger()` 미호출**

`poetry run python -c "..."` 명령에서 직접 코드를 실행할 때 `setup_logger()`를 반드시 먼저 호출해야 합니다. 이 README의 모든 예시 명령은 `setup_logger()`가 포함되어 있습니다.

**원인 3 — pykrx 네트워크 지연**

첫 번째 로그 출력 후 KRX 서버에 HTTP 요청을 보내는데, KRX 점검 시간(07:00~09:00 KST)이거나 네트워크가 느리면 수 분간 멈춘 것처럼 보일 수 있습니다. 기다리면 됩니다.

---

### Docker 컨테이너가 시작되지 않는다

```powershell
# 오류 로그 확인
docker compose logs db
docker compose logs redis

# 포트 충돌 확인 (5432, 6379)
netstat -ano | findstr :5432
netstat -ano | findstr :6379

# 컨테이너 재시작
docker compose down
docker compose up -d
```

5432 포트가 이미 사용 중이면 로컬에 PostgreSQL이 설치된 것입니다.
`docker-compose.yml`에서 포트를 변경하거나 로컬 PostgreSQL을 중지하세요.

---

### DB 연결 실패 (`could not connect to server` / `Connection refused`)

1. Docker Desktop이 실행 중인지 확인 (`docker compose ps`)
2. `.env`의 `DB_PASSWORD`와 `docker-compose.yml`의 `POSTGRES_PASSWORD` 값이 일치하는지 확인

```powershell
# docker-compose.yml 기본값: stockpass
# .env 확인
Get-Content .env | Select-String "DB_PASSWORD"
```

3. 컨테이너가 완전히 시작되기까지 최대 30초 걸립니다. 기동 직후 연결 시도 시 실패할 수 있습니다.

---

### `schema.sql`이 적용되지 않았다 (테이블이 없다)

`pgdata` 볼륨이 이미 존재하면 `schema.sql`이 다시 실행되지 않습니다.

```powershell
# 볼륨까지 완전 삭제 후 재생성 (기존 데이터 모두 삭제됨)
docker compose down -v
docker compose up -d
```

---

### `poetry install` 실패 — `psycopg2` 빌드 오류

`psycopg2-binary`를 사용하므로 빌드 오류가 발생하면 안 됩니다.
`psycopg2` (binary 아닌 버전)가 `pyproject.toml`에 있다면 `psycopg2-binary`로 교체하세요.

Visual C++ 관련 오류 시:

```powershell
# Microsoft C++ Build Tools 설치
winget install Microsoft.VisualStudio.2022.BuildTools
```

---

### Poetry를 못 찾는다 (`poetry: command not found`)

```powershell
# Poetry 설치 경로 직접 실행
$env:PATH += ";$env:APPDATA\Python\Scripts"
poetry --version

# 영구 등록 (PowerShell 프로필에 추가)
Add-Content $PROFILE "`n`$env:PATH += `";`$env:APPDATA\Python\Scripts`""
```

---

### pykrx 데이터가 빈 DataFrame으로 반환된다

- KRX 서버 점검 시간(07:00~09:00 KST 사이)에는 당일 데이터가 없을 수 있습니다.
- 당일 데이터는 장마감(15:30) 이후에 확정됩니다. `todate`를 전일로 설정하세요.

```powershell
# 오늘이 2024-12-20이면
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.price_collector import PriceCollector
setup_logger()
PriceCollector(StockRepository()).run('20240101', '20241219')
"
```

---

### DART API 오류 (`invalid api key` / `API 한도 초과`)

- `.env`의 `DART_API_KEY` 값을 확인합니다.
- DART 오픈API는 **하루 10,000건** 호출 제한이 있습니다. 초과 시 다음 날 재시도하세요.

---

### 실패율 30% 초과 — 추천이 생성되지 않는다

```
실패율 X/350 — 추천 생성 중단
```

데이터 초기 적재(Step 1~3)가 완료되지 않은 경우입니다.

```powershell
# 적재 현황 확인
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT
  (SELECT COUNT(DISTINCT code) FROM daily_prices) AS price_codes,
  (SELECT MAX(date) FROM daily_prices)            AS latest_price_date,
  (SELECT COUNT(*) FROM index_prices)             AS index_rows;
"
```

`price_codes`가 300 미만이면 Step 1 재실행, `index_rows`가 60 미만이면 Step 3 재실행하세요.

---

## 데이터 소스 정책

| 데이터 | 소스 | API 키 |
|---|---|---|
| 주가·거래량·시총 | pykrx (KRX 공식) | 불필요 |
| 투자자별 매매동향 | pykrx (KRX 공식) | 불필요 |
| 코스피 지수 | pykrx (KRX 공식) | 불필요 |
| 재무제표 | DART 오픈API | **필요** |
| 공시 정보 | DART 오픈API | **필요** |

네이버금융 크롤링은 사용하지 않습니다.
