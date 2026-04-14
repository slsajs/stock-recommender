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
9. [고도화 — STEP A: 금리 트렌드 기반 재무 가중치 조절](#고도화--step-a-금리-트렌드-기반-재무-가중치-조절)
10. [고도화 — STEP B: 환율 → 섹터별 점수 보정](#고도화--step-b-환율--섹터별-점수-보정)
11. [고도화 — STEP E: 공시 감성 보정](#고도화--step-e-공시-감성-보정)
12. [섹터 데이터 수집 가이드](#섹터-데이터-수집-가이드)
13. [프로젝트 구조](#프로젝트-구조)
14. [트러블슈팅](#트러블슈팅)

---

## 핵심 공식

```
최종점수 = 재무점수(가변%) + 모멘텀점수(가변%)

adjusted_total_score = total_score + macro_adjustment + disclosure_adjustment + news_adjustment
```

> **방향 B 설계 변경**: 백테스트 alpha 분석에서 기술적 지표(RSI/MACD/BB)가 음의 상관계수(-0.055~-0.082)를 보여 가중치에서 제외했습니다. 재무점수 + 모멘텀점수만 사용합니다.

**도메인 가중치 — Market Regime에 따라 동적 결정**

| 시장 상태 | 재무점수 | 모멘텀점수 | 비고 |
|---|---|---|---|
| BULL (MA20 > MA60) | 35% | 65% | 추세 상승장 — 모멘텀 집중 |
| BEAR (MA20 ≤ MA60) | 45% | 55% | 방어적 하락장 — 재무 비중 ↑ |

**재무점수 내부 가중치 — [STEP A] 금리 트렌드에 따라 동적 결정**

| 금리 트렌드 | PER | PBR | ROE | 부채비율 |
|---|---|---|---|---|
| STABLE (기본) | 30% | 25% | 30% | 15% |
| RISING (인상기) | 40% | 25% | 20% | 15% |
| FALLING (인하기) | 20% | 20% | 40% | 20% |

> ECOS_API_KEY 미설정 시 STABLE(기본값)로 동작합니다.

**섹터 보정 — [STEP B] 환율 변동에 따라 섹터별 adjusted_total_score 가감**

| 섹터 유형 | 해당 섹터 | 보정 방향 |
|---|---|---|
| 수출 수혜 | 반도체, 자동차, 조선, 전자부품, 디스플레이, IT하드웨어 | 환율 1% 상승당 +1점 (최대 +5) |
| 수입 비용 | 항공, 정유, 철강, 화학 | 환율 1% 상승당 -1점 (최대 -5) |
| 기타 | (위 이외) | 0 (보정 없음) |

> 섹터 정보(`stocks.sector`)가 NULL인 종목은 보정값 0.0으로 처리됩니다.
> 섹터 데이터 수집 방법은 [섹터 데이터 수집 가이드](#섹터-데이터-수집-가이드)를 참고하세요.

**공시 감성 보정 — [STEP E] 최근 30일 DART 공시 카테고리·제목 키워드 기반**

| 공시 유형 | 예시 | 감성 점수 | 보정 범위 |
|---|---|---|---|
| 자기주식취득결정 | 자사주 매입 공시 | +0.8 | |
| 무상증자결정 | 무상증자 공시 | +0.7 | |
| 유상증자결정 | 유상증자 공시 | -0.7 | |
| 관리종목지정 | 관리종목 지정 | -0.9 | |
| 실적 키워드 | 흑자전환, 사상최대 | ±0.7~0.8 | |

보정값 = 시간 감쇠 가중 평균(오늘=1.0, 30일 전=0.1) × 10, **-10.0 ~ +10.0** 클리핑

> DART_API_KEY 설정 및 공시 수집 완료 시 자동으로 적용됩니다.
> 미적용 시 `disclosure_adjustment = 0.0`으로 처리됩니다.

---

## 구현 현황

**MVP**

| 단계 | 내용 | 상태 |
|---|---|---|
| 1단계 | Docker Compose + DB 스키마 + PriceCollector + InvestorCollector + IndexCollector | 완료 |
| 2단계 | FinanceCollector + DisclosureCollector | 완료 |
| 3단계 | MarketRegime + Filters + TechnicalScorer | 완료 |
| 4단계 | FundamentalScorer + MomentumScorer + Aggregator | 완료 |
| 5단계 | main.py (APScheduler 16:30 자동 실행) | 완료 |
| 6단계 | BacktestEvaluator (1/5/20/60일 수익률) | 완료 |
| 7단계 | Slack 알림 | 미구현 |

**고도화**

| STEP | 내용 | 상태 |
|---|---|---|
| 방향 B | 모멘텀 팩터 재설계: 52주 신고가 → 60일 가격 모멘텀, 기술 가중치 → 0 | 완료 |
| STEP A | 금리 트렌드 → FundamentalScorer 내부 가중치 동적 조절 | 완료 |
| STEP B | 환율 → 섹터별 점수 보정 | 완료 |
| STEP C | 장단기 금리차 → Market Regime 보강 | 미구현 |
| STEP D | 미국 시장 급락 → 추천 보류 | 미구현 |
| STEP E | 공시 감성 (규칙 기반) 보정 | 완료 |
| STEP F | 뉴스 감성 보정 | 미구현 |

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

# ── [고도화] ECOS API (한국은행 경제통계 — STEP A~C) ─────────────
# https://ecos.bok.or.kr/ 에서 회원가입 후 발급 (무료)
# 기준금리(BASE_RATE), 환율(USD_KRW), 국고채(KTB_10Y) 수집에 필요
# 미설정 시 재무 내부 가중치는 STABLE 기본값으로 동작
ECOS_API_KEY=

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

### Step 6. 거시경제 지표 — [고도화 STEP A·B] ECOS API 키 필요

기준금리(BASE_RATE), 원/달러 환율(USD_KRW), 국고채 10년물(KTB_10Y) 데이터를 수집합니다.

- **STEP A**: BASE_RATE 3개월 변동 → 재무점수 내부 가중치(PER/ROE 비중) 동적 조절
- **STEP B**: USD_KRW 20거래일 변동률 → 수출/수입 섹터 종목의 adjusted_total_score 가감

**API 키 발급:**

1. [ecos.bok.or.kr](https://ecos.bok.or.kr/) 접속 → 로그인 → `Open API` 메뉴
2. `인증키 신청` → 이메일 인증 후 발급 (무료, 당일 발급)
3. `.env`의 `ECOS_API_KEY`에 발급받은 키 입력

**패키지 설치 확인 (이미 poetry install로 설치되어 있어야 합니다):**

```powershell
poetry run python -c "import ecos; print('ecos 설치 확인')"
```

`ModuleNotFoundError`가 나오면:

```powershell
poetry add ecos

docker exec -i stock-db psql -U postgres -d stock_recommender < src/db/migrate_upgrade.sql
```

**초기 수집 (1년치):**

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.collector.macro_collector import MacroCollector
setup_logger()
init_pool()
repo = StockRepository()
MacroCollector(repo).run(
    indicator_codes=['BASE_RATE', 'USD_KRW', 'KTB_10Y'],
    start_date='20240101',
    end_date='20241231',
)
close_pool()
"
```

- `macro_indicators` 테이블에 저장
- 소요 시간: **약 1~2분** (3개 지표 × 약 12~250건)
- ECOS API는 하루 호출 제한이 없음

**적재 확인:**

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT indicator_code, COUNT(*) AS rows, MIN(date) AS from_date, MAX(date) AS to_date
FROM macro_indicators
GROUP BY indicator_code
ORDER BY indicator_code;
"
```

정상 적재 시 출력:

```
 indicator_code | rows | from_date  |  to_date
----------------+------+------------+------------
 BASE_RATE      |   12 | 2024-01-01 | 2024-12-01
 KTB_10Y        |  250 | 2024-01-02 | 2024-12-31
 USD_KRW        |  248 | 2024-01-02 | 2024-12-31
```

> BASE_RATE는 한국은행 금통위 결정 시에만 변경(연 8회)되므로 월별 데이터로 수집됩니다.
> USD_KRW, KTB_10Y는 영업일 기준 일별 데이터입니다.

---

> **Step 6는 선택 사항입니다.**
> ECOS_API_KEY 미설정 시 금리 트렌드 판단을 건너뛰고 재무 내부 가중치는 STABLE 기본값
> (PER 30%, PBR 25%, ROE 30%, 부채비율 15%)으로 고정됩니다.

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
poetry run pytest tests/test_macro_adjuster.py -v       # [STEP A, B]
poetry run pytest tests/test_disclosure_scorer.py -v    # [STEP E]
```

| 테스트 파일 | 주요 케이스 |
|---|---|
| `test_technical.py` | RSI ≤ 30 → 70점 이상, RSI ≥ 70 → 30점 이하, 데이터 5일 미만 → 50.0 |
| `test_fundamental.py` | 섹터 내 PER 최저 → 높은 점수, 섹터 5개 미만 → 전체 폴백, PER 음수/None → 30.0 |
| `test_momentum.py` | 거래량 5배 급증 → 100점, 60일 수익률 +20% → 80점 이상, 데이터 없음 → 50.0, 가중치 합 = 1.0 |
| `test_market_regime.py` | MA20 > MA60 → BULL + 모멘텀 0.65, MA20 < MA60 → BEAR + 재무 0.45, 기술 가중치 = 0.0 |
| `test_filters.py` | 상장 60일 미만 → 제외, 5일 거래량 0 → 제외, 관리종목 공시 → 제외 |
| `test_aggregator.py` | 가중합·순위 계산, 실패율 30% 초과 → 추천 중단 |
| `test_macro_adjuster.py` | [STEP A] 금리 0.5%p 상승 → RISING, 가중치 합 = 1.0 / [STEP B] 수출 섹터+환율 상승 → +보정, 클리핑 ±5.0 |
| `test_disclosure_scorer.py` | [STEP E] 자기주식취득 → +0.8, 유상증자 → -0.7, 최근 악재 > 오래된 호재, 클리핑 ±10.0 |

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

## 고도화 — STEP A: 금리 트렌드 기반 재무 가중치 조절

### 개요

기준금리 방향에 따라 `FundamentalScorer` 내부의 PER/ROE 가중치를 자동으로 조절합니다.

- **금리 인상기(RISING)**: 미래 이익의 현재 가치 감소 → 저PER 가치주 선호 → PER 비중 ↑, ROE 비중 ↓
- **금리 인하기(FALLING)**: 성장 기대감 증가 → 고ROE 성장주 선호 → ROE 비중 ↑, PER 비중 ↓
- **변동 없음(STABLE)**: 기본 가중치 유지

### 판단 기준

ECOS API에서 수집한 `BASE_RATE`(월별 기준금리)를 기준으로, 최근 3개월간 변동폭이 0.25%p 이상이면 트렌드가 있다고 판단합니다.

| 조건 | 트렌드 |
|---|---|
| 3개월간 0.25%p 이상 상승 | RISING |
| 3개월간 0.25%p 이상 하락 | FALLING |
| 변동폭 0.25%p 미만 | STABLE |
| 데이터 1건 이하 | STABLE (안전 폴백) |

### 파이프라인 내 동작 위치

```
run_daily()
  ├── [1] Market Regime 판단 (코스피 MA20/MA60)
  ├── [1-b] 금리 트렌드 판단 → FundamentalScorer 내부 가중치 결정  ← STEP A
  ├── [2] 재무 데이터 캐시
  └── [4] 종목별 스코어링
           └── FundamentalScorer.score(..., fund_internal_weights=...)
```

### 로그 확인

STEP A가 적용되면 아래와 같은 로그가 출력됩니다:

```
2024-01-15 16:30:01 | INFO | 금리 트렌드: RISING | 재무 내부 가중치={'per': 0.40, 'pbr': 0.25, 'roe': 0.20, 'debt': 0.15}
```

ECOS 키가 없거나 데이터 부족 시:

```
2024-01-15 16:30:01 | INFO | 금리 트렌드: STABLE | 재무 내부 가중치={'per': 0.30, 'pbr': 0.25, 'roe': 0.30, 'debt': 0.15}
```

### 수동으로 금리 트렌드 확인

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.scoring.macro_adjuster import determine_rate_trend, get_fundamental_weights
setup_logger()
init_pool()
repo = StockRepository()
trend = determine_rate_trend(repo)
weights = get_fundamental_weights(trend)
print(f'트렌드: {trend}')
print(f'가중치: {weights}')
close_pool()
"
```

### 백테스트로 STEP A 효과 검증

STEP A 적용 전후 추천 성과를 비교하는 방법:

```powershell
# STEP A 적용 전 추천 이력이 있어야 합니다
# 비교 쿼리 (psql)
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT
  AVG(rr.return_rate - rr.benchmark_rate) AS avg_alpha,
  COUNT(*) AS sample_count
FROM recommendation_returns rr
JOIN recommendations r ON r.id = rr.recommendation_id
WHERE rr.days_after = 20;
"
```

> STEP A 적용 전 alpha와 비교했을 때 개선되지 않으면 `macro_adjuster.py`의
> `determine_rate_trend()`에서 항상 `"STABLE"`을 반환하도록 임시 변경하여 비활성화할 수 있습니다.

---

## 고도화 — STEP B: 환율 → 섹터별 점수 보정

### 개요

원/달러 환율(USD_KRW) 최근 20거래일 변동률에 따라 수출 수혜주에 가점, 수입 비용 증가주에 감점을 적용합니다.
보정값은 `stock_scores.macro_adjustment` 컬럼에 저장되며 `adjusted_total_score`에 반영됩니다.

- **원화 약세(환율 상승)**: 수출기업 원화 매출 증가 → 반도체·자동차·조선 등 가점
- **원화 강세(환율 하락)**: 수입 원자재 비용 절감 → 항공·정유·철강·화학 가점

### 보정 규칙

| 섹터 유형 | 해당 섹터 | 보정값 계산 | 최대/최소 |
|---|---|---|---|
| 수출 수혜 | 반도체, 자동차, 조선, 전자부품, 디스플레이, IT하드웨어 | 환율변동률(%) × +1.0 | ±5.0 |
| 수입 비용 | 항공, 정유, 철강, 화학 | 환율변동률(%) × -1.0 | ±5.0 |
| 기타 / NULL | (위 이외 또는 섹터 미분류) | 0.0 | - |

**예시:**
- 환율 +3% 상승(원화 약세) + 반도체 종목 → `macro_adjustment = +3.0`
- 환율 +3% 상승(원화 약세) + 항공 종목 → `macro_adjustment = -3.0`
- 환율 +8% 급등 + 자동차 종목 → `macro_adjustment = +5.0` (클리핑)

### 파이프라인 내 동작 위치

```
run_daily()
  ├── [1] Market Regime 판단
  ├── [1-b] 금리 트렌드 판단 (STEP A)
  ├── [1-c] 환율 변동률 계산 (usd_krw_change)        ← STEP B (루프 밖 1회 계산)
  ├── [2] 재무 데이터 캐시
  └── [4] 종목별 스코어링
           ├── FundamentalScorer → 기본 점수
           ├── currency_adjustment(sector, usd_krw_change)  ← STEP B (섹터별 적용)
           └── ScoreResult.macro_adjustment = 보정값
                  ↓
  aggregator.aggregate()
    adjusted_total_score = total_score + macro_adjustment + disclosure_adjustment + news_adjustment
```

### 로그 확인

STEP B가 적용되면 종목별로 다음 로그가 출력됩니다:

```
2024-01-15 16:31:22 | DEBUG | 환율 변동률: 1289.4 → 1328.1 (+3.00%)
2024-01-15 16:31:23 | DEBUG | [005380] 자동차 섹터 | 환율 보정 +3.00 → macro_adjustment=+3.00
```

섹터 데이터가 없으면(NULL):
```
2024-01-15 16:31:23 | DEBUG | [005380] 섹터=None → 환율 보정 0.0
```

### 수동으로 환율 보정값 확인

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.scoring.macro_adjuster import get_usd_krw_change, currency_adjustment
setup_logger()
init_pool()
repo = StockRepository()
change = get_usd_krw_change(repo)
print(f'최근 20거래일 환율 변동률: {change:+.2f}%')
for sector in ['반도체', '항공', '유통']:
    adj = currency_adjustment(sector, change)
    print(f'  {sector}: {adj:+.2f}')
close_pool()
"
```

### 백테스트로 STEP B 효과 검증

```sql
-- psql에서 실행
SELECT
  s.sector,
  AVG(ss.macro_adjustment) AS avg_macro_adj,
  COUNT(*)                 AS cnt
FROM stock_scores ss
JOIN stocks s ON s.code = ss.code
WHERE ss.date >= CURRENT_DATE - INTERVAL '30 days'
  AND ss.macro_adjustment != 0
GROUP BY s.sector
ORDER BY avg_macro_adj DESC;
```

> STEP B가 실질적으로 동작하려면 `stocks.sector`가 채워져 있어야 합니다.
> 현재 pykrx는 섹터 정보를 제공하지 않아 대부분 NULL입니다.
> 섹터 수집 방법은 아래 [섹터 데이터 수집 가이드](#섹터-데이터-수집-가이드)를 참고하세요.

> STEP B를 비활성화하려면 `main.py`에서 `currency_adjustment()` 호출 결과를 0.0으로 고정하거나
> `macro_adjuster.py`의 `currency_adjustment()`가 항상 `0.0`을 반환하도록 임시 변경하세요.

---

## 고도화 — STEP E: 공시 감성 보정

### 개요

DART에서 수집한 공시의 **카테고리**와 **제목 키워드**를 규칙 기반으로 분석하여 종목별 감성 보정값을 산출합니다.
NLP 모델 없이 사전 매핑만으로 동작하므로 외부 의존성이 없고 실시간 처리가 가능합니다.

- **호재 공시**: 자기주식취득, 무상증자 등 → 최종 점수 가점 (최대 +10)
- **악재 공시**: 유상증자, 관리종목지정, 회생절차 등 → 최종 점수 감점 (최대 -10)
- **시간 감쇠**: 최근 공시일수록 가중치가 높음 (오늘=1.0, 30일 전=0.1)

### 카테고리별 감성 점수 사전

| 카테고리 | 감성 점수 | 배경 |
|---|---|---|
| 자기주식취득결정 | +0.8 | 자사주 매입 → 주주환원 신호 |
| 무상증자결정 | +0.7 | 기존 주주 추가 주식 지급 |
| 주식배당결정 | +0.6 | 배당 지급 |
| 타법인주식취득 | +0.5 | M&A, 사업 확장 |
| 유상증자결정 | -0.7 | 지분 희석 |
| 전환사채권발행 | -0.5 | 잠재적 지분 희석 |
| 감자결정 | -0.8 | 주식 수 감소 |
| 관리종목지정 | -0.9 | 상장 위험 신호 |
| 회생절차·영업정지·상장폐지 | -1.0 | 치명적 위험 |

### 제목 키워드 감성 점수

| 키워드 | 감성 점수 |
|---|---|
| 흑자전환, 사상최대, 최대실적 | +0.7 ~ +0.8 |
| 영업이익증가, 매출액증가 | +0.4 ~ +0.6 |
| 적자전환 | -0.8 |
| 영업이익감소, 매출액감소 | -0.4 ~ -0.6 |

> 카테고리와 제목 키워드가 동시에 매칭되면 합산 후 -1.0 ~ +1.0으로 클리핑합니다.
> 제목은 첫 번째 매칭 키워드만 반영합니다.

### 보정값 산출 공식

```
avg_sentiment = Σ(sentiment_i × time_weight_i) / Σ(time_weight_i)
time_weight   = max(0.1, 1.0 - days_ago / 30 × 0.9)   # 오늘=1.0, 30일 전=0.1
disclosure_adjustment = clip(avg_sentiment × 10, -10, +10)
```

### 파이프라인 내 동작 위치

```
run_daily()
  ├── [1] Market Regime 판단
  ├── [1-b] 금리 트렌드 판단 (STEP A)
  ├── [1-c] 환율 변동률 계산 (STEP B)
  ├── [2] 재무 데이터 캐시
  └── [4] 종목별 스코어링
           ├── TechnicalScorer / FundamentalScorer / MomentumScorer
           ├── disclosure_adjustment(recent_discs)   ← STEP E (공시 보정값)
           └── ScoreResult.disclosure_adjustment = disc_adj
                  ↓
  aggregator.aggregate()
    adjusted_total_score = total_score + macro_adj + disclosure_adj + news_adj

  [루프 종료 후]
  repo.batch_update_disclosure_sentiments(...)        ← disclosures.sentiment_score 업데이트
```

### 로그 확인

STEP E가 적용되면 다음 로그가 출력됩니다:

```
2024-01-15 16:33:12 | DEBUG | 공시 보정 | 유효=2건 avg_sentiment=-0.412 → adjustment=-4.12
2024-01-15 16:35:10 | INFO  | #1 005380 | 총점=83.45 → 보정후=79.33 (macro=+0.00, disc=-4.12)
2024-01-15 16:35:25 | INFO  | 공시 sentiment_score 업데이트 | 47건
```

공시 데이터가 없거나 중립 공시만 있을 경우:

```
2024-01-15 16:33:12 | DEBUG | 공시 보정 | 유효=0건 avg_sentiment=0.000 → adjustment=+0.00
```

### 수동으로 공시 보정값 확인

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.scoring.disclosure_scorer import disclosure_adjustment
setup_logger()
init_pool()
repo = StockRepository()
code = '005380'  # 현대차 예시
discs = repo.get_recent_disclosures(code, days=30)
adj = disclosure_adjustment(discs)
print(f'{code} 공시 보정값: {adj:+.2f}')
print(f'공시 건수: {len(discs)}건')
for d in discs:
    print(f'  [{d[\"days_ago\"]}일 전] {d[\"category\"]} — {d[\"title\"][:50]}')
close_pool()
"
```

### 백테스트로 STEP E 효과 검증

```sql
-- psql에서 실행 — STEP E 적용 종목의 성과 확인
SELECT
  AVG(ss.disclosure_adjustment)                          AS avg_disc_adj,
  AVG(rr.return_rate - rr.benchmark_rate)                AS avg_alpha,
  COUNT(*)                                               AS sample_count
FROM stock_scores ss
JOIN recommendations r ON r.code = ss.code AND r.date = ss.date
JOIN recommendation_returns rr ON rr.recommendation_id = r.id
WHERE rr.days_after = 20
  AND ss.disclosure_adjustment != 0;
```

```sql
-- 공시 보정이 적용된 날의 추천 vs 미적용 날 alpha 비교
SELECT
  CASE WHEN ABS(ss.disclosure_adjustment) > 0 THEN '보정 있음' ELSE '보정 없음' END AS group_label,
  AVG(rr.return_rate - rr.benchmark_rate) AS avg_alpha,
  COUNT(*) AS cnt
FROM stock_scores ss
JOIN recommendations r ON r.code = ss.code AND r.date = ss.date
JOIN recommendation_returns rr ON rr.recommendation_id = r.id
WHERE rr.days_after = 20
GROUP BY group_label;
```

> STEP E를 비활성화하려면 `main.py`의 `disclosure_adjustment()` 호출 결과를 0.0으로 고정하세요:
>
> ```python
> # disc_adj = disclosure_adjustment(recent_discs)
> disc_adj = 0.0
> ```

### 선행 조건

STEP E가 실질적으로 동작하려면 `disclosures` 테이블에 데이터가 있어야 합니다.

```powershell
# 공시 데이터 수집 (DART_API_KEY 필요)
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.collector.disclosure_collector import DisclosureCollector
setup_logger()
init_pool()
repo = StockRepository()
DisclosureCollector(repo).run('2024-01-01', '2024-12-31')
close_pool()
"
```

공시 수집 후 카테고리 분포 확인:

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT category, COUNT(*) AS cnt
FROM disclosures
GROUP BY category
ORDER BY cnt DESC;
"
```

---

## 섹터 데이터 수집 가이드

### 왜 필요한가

pykrx는 주가·거래량 데이터를 제공하지만 **섹터 분류는 제공하지 않습니다**.
현재 `stocks.sector` 컬럼이 모두 NULL이어서 STEP B 환율 보정이 동작하지 않습니다.

아래 방법 중 하나로 섹터 데이터를 채울 수 있습니다.

---

### 방법 1 — KRX 정보데이터시스템 (권장, 무료)

KRX 공식 사이트에서 업종분류 파일을 CSV로 다운로드한 후 DB에 업데이트합니다.

**다운로드 경로:**

1. [data.krx.co.kr](https://data.krx.co.kr) 접속
2. `주식 > 기본 통계 > 주식 종목 검색` → `업종별 현황` 선택
3. 코스피200, 코스닥150 각각 전체 다운로드 (CSV, Excel 모두 가능)

다운로드한 CSV에는 `종목코드`, `종목명`, `업종명` 컬럼이 포함되어 있습니다.

**DB 업데이트 스크립트:**

```python
# scripts/update_sectors.py — 프로젝트 루트에 직접 실행
import csv
from src.db.connection import init_pool, close_pool, get_connection

# KRX에서 다운받은 CSV 파일 경로 (컬럼: 종목코드, 업종명)
KRX_CSV = "krx_sectors.csv"

# KRX 업종명 → stocks.sector 매핑 (필요 시 확장)
SECTOR_MAP = {
    "반도체":       "반도체",
    "자동차":       "자동차",
    "조선":         "조선",
    "전자부품":     "전자부품",
    "디스플레이":   "디스플레이",
    "IT하드웨어":   "IT하드웨어",
    "항공":         "항공",
    "정유":         "정유",
    "철강":         "철강",
    "화학":         "화학",
    # KRX 업종명과 STEP B 섹터명이 다른 경우 여기서 매핑
}

init_pool()
conn = get_connection()
cur = conn.cursor()

with open(KRX_CSV, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    updated = 0
    for row in reader:
        code = row.get("종목코드", "").strip().zfill(6)
        krx_sector = row.get("업종명", "").strip()
        sector = SECTOR_MAP.get(krx_sector, krx_sector)  # 매핑 없으면 원본 사용
        cur.execute(
            "UPDATE stocks SET sector = %s WHERE code = %s",
            (sector, code)
        )
        if cur.rowcount:
            updated += 1

conn.commit()
cur.close()
conn.close()
close_pool()
print(f"섹터 업데이트 완료: {updated}건")
```

```powershell
# 실행
poetry run python scripts/update_sectors.py
```

---

### 방법 2 — pykrx get_market_sector_classifications (간편)

pykrx에서 KRX 업종 분류를 직접 조회할 수 있습니다.

```python
from pykrx import stock as pykrx_stock

# 코스피 업종 분류
kospi_sectors = pykrx_stock.get_market_sector_classifications(date="20241231", market="KOSPI")
# 코스닥 업종 분류
kosdaq_sectors = pykrx_stock.get_market_sector_classifications(date="20241231", market="KOSDAQ")
```

반환 DataFrame 컬럼: `티커`, `종목명`, `업종`

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool, get_connection
from pykrx import stock as pykrx_stock
import pandas as pd
setup_logger()
init_pool()

dfs = []
for market in ['KOSPI', 'KOSDAQ']:
    df = pykrx_stock.get_market_sector_classifications('20241231', market)
    dfs.append(df)

df_all = pd.concat(dfs)
print(df_all.head())

conn = get_connection()
cur = conn.cursor()
updated = 0
for _, row in df_all.iterrows():
    code = str(row.get('티커', '')).strip().zfill(6)
    sector = str(row.get('업종', '')).strip()
    if not code or not sector:
        continue
    cur.execute('UPDATE stocks SET sector = %s WHERE code = %s', (sector, code))
    if cur.rowcount:
        updated += 1
conn.commit()
cur.close()
conn.close()
close_pool()
print(f'섹터 업데이트 완료: {updated}건')
"
```

> pykrx의 업종명이 STEP B의 섹터명과 정확히 일치해야 보정이 적용됩니다.
> 예: pykrx가 `"전기전자"` 로 반환하지만 STEP B는 `"IT하드웨어"` 로 매핑되어 있지 않으면 보정이 0.0이 됩니다.
> 위의 `SECTOR_MAP`에 추가 매핑을 넣어 조정하세요.

---

### 방법 3 — DART 고유번호 파일 (corpCode.zip)

DART API의 고유번호 파일에는 업종코드가 포함되어 있습니다.

```powershell
# DART API 키 필요
poetry run python -c "
import OpenDartReader
dart = OpenDartReader.OpenDartReader('YOUR_DART_API_KEY')
corp_list = dart.corp_codes
print(corp_list.columns.tolist())
print(corp_list[corp_list['stock_code'].notna()].head(10))
"
```

> DART의 업종분류는 금융감독원 기준이며 KRX 업종과 다를 수 있습니다.
> 정밀한 섹터 매핑이 필요하면 DART 업종코드를 STEP B의 섹터명으로 수동 매핑하는 별도 파일을 관리하세요.

---

### 섹터 적재 현황 확인

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT
  sector,
  COUNT(*) AS cnt
FROM stocks
GROUP BY sector
ORDER BY cnt DESC
LIMIT 20;
"
```

`sector = NULL`이 대부분이면 아직 수집이 안 된 상태입니다.

---

### STEP B가 실제로 동작하는지 확인

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT code, date, macro_adjustment, adjusted_total_score, total_score
FROM stock_scores
WHERE macro_adjustment != 0
ORDER BY date DESC
LIMIT 10;
"
```

`macro_adjustment != 0` 인 행이 있으면 STEP B 보정이 적용된 것입니다.

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
│   │   ├── disclosure_collector.py # DART: 공시 (위험 공시 필터용)
│   │   └── macro_collector.py    # [STEP A] ECOS: 기준금리·환율·국고채
│   │
│   ├── scoring/
│   │   ├── base.py               # BaseScorer ABC, ScoreResult dataclass
│   │   ├── market_regime.py      # MA20/MA60 → BULL/BEAR + 동적 가중치
│   │   ├── filters.py            # 추천 제외 필터
│   │   ├── technical.py          # RSI, MACD, 볼린저밴드 (역추세)
│   │   ├── fundamental.py        # PER, PBR, ROE, 부채비율 (섹터 상대비교)
│   │   ├── momentum.py           # 거래량 급증(50%), 기관 순매수(20%), 60일 가격 모멘텀(30%)
│   │   ├── aggregator.py         # 가중합 → Top 5 추출
│   │   └── macro_adjuster.py     # [STEP A] 금리 트렌드 → 재무 내부 가중치 / [STEP B] 환율 → 섹터 보정
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
    ├── test_aggregator.py
    └── test_macro_adjuster.py    # [STEP A·B]
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

### ECOS API 오류 / 금리 트렌드가 항상 STABLE이다

**키 미설정 확인:**

```powershell
Get-Content .env | Select-String "ECOS"
# ECOS_API_KEY= 이면 키가 없는 것
```

**패키지 미설치 확인:**

```powershell
poetry run python -c "import ecos"
# ModuleNotFoundError 시: poetry add ecos
```

**데이터 적재 확인:**

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "SELECT COUNT(*) FROM macro_indicators WHERE indicator_code='BASE_RATE';"
# 0이면 Step 6 초기 수집이 안 된 것
```

**BASE_RATE 데이터가 1건뿐이라 STABLE로 판단되는 경우:**

ECOS에서 BASE_RATE는 월별 데이터입니다. 최근 3개월치(3건 이상)가 있어야 트렌드 판단이 가능합니다.
`start_date`를 6개월 이전으로 늘려 재수집하세요:

```powershell
poetry run python -c "
from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.collector.macro_collector import MacroCollector
setup_logger()
init_pool()
MacroCollector(StockRepository()).run(
    indicator_codes=['BASE_RATE'],
    start_date='20230101',
    end_date='20241231',
)
close_pool()
"
```

---

### STEP B 환율 보정이 모두 0.0이다

**원인 1 — 섹터 데이터 없음 (가장 흔함)**

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT COUNT(*) AS null_sector FROM stocks WHERE sector IS NULL;
"
```

0이 아니면 섹터 수집이 안 된 것입니다.
[섹터 데이터 수집 가이드](#섹터-데이터-수집-가이드)를 참고하여 수집하세요.

**원인 2 — 섹터명 불일치**

`stocks.sector` 값이 STEP B의 `EXPORT_SECTORS` / `IMPORT_SECTORS` 목록과 정확히 일치해야 합니다.

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector;
"
```

출력된 섹터명이 `macro_adjuster.py`의 `EXPORT_SECTORS`, `IMPORT_SECTORS` 리스트 값과 다르면
해당 파일의 리스트를 DB 값에 맞게 수정하거나 DB 값을 리스트에 맞게 업데이트하세요.

**원인 3 — USD_KRW 데이터 없음**

```powershell
docker exec -it stock-db psql -U postgres -d stock_recommender -c "
SELECT COUNT(*) FROM macro_indicators WHERE indicator_code='USD_KRW';
"
```

0이면 Step 6 초기 수집(MacroCollector)이 안 된 것입니다.

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

| 데이터 | 소스 | API 키 | 용도 |
|---|---|---|---|
| 주가·거래량·시총 | pykrx (KRX 공식) | 불필요 | 기술·모멘텀 스코어링 |
| 투자자별 매매동향 | pykrx (KRX 공식) | 불필요 | 모멘텀 스코어링 |
| 코스피 지수 | pykrx (KRX 공식) | 불필요 | Market Regime 판단 |
| 재무제표 | DART 오픈API | **필요** | 재무 스코어링 |
| 공시 정보 | DART 오픈API | **필요** | 위험 공시 필터 |
| 기준금리·환율·국고채 | ECOS (한국은행) | **필요** (STEP A~C) | 재무 내부 가중치 동적 조절 + 섹터별 환율 보정 |
| 섹터 분류 | KRX 정보데이터시스템 / pykrx | 불필요 | STEP B 환율 보정 동작 조건 |

네이버금융 크롤링은 사용하지 않습니다.
