-- ============================================================
-- migrate_upgrade.sql
-- 이미 DB가 구축된 상태에서 고도화 STEP 추가 시 실행하는 마이그레이션.
-- 신규 설치(schema.sql)에는 이미 포함되어 있으므로 실행 불필요.
--
-- 실행 방법 (Docker 컨테이너 기준):
--   docker exec -i stock-db psql -U postgres -d stock_recommender < src/db/migrate_upgrade.sql
--
-- 또는 컨테이너 접속 후 실행:
--   docker exec -it stock-db psql -U postgres -d stock_recommender
--   \i /path/to/migrate_upgrade.sql
--
-- 모든 구문은 IF NOT EXISTS / DO $$ 로 멱등성을 보장합니다.
-- 이미 적용된 상태에서 재실행해도 오류가 발생하지 않습니다.
-- ============================================================

-- ============================================================
-- [STEP A~C] 거시경제 지표 테이블
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_indicators (
    date            DATE          NOT NULL,
    indicator_code  VARCHAR(30)   NOT NULL,   -- 'BASE_RATE', 'USD_KRW', 'KTB_10Y', 'CPI_YOY'
    value           NUMERIC(12,4) NOT NULL,
    PRIMARY KEY (date, indicator_code)
);

-- ============================================================
-- [STEP D] 미국 시장 지수 테이블
-- ============================================================
CREATE TABLE IF NOT EXISTS us_market_prices (
    index_code      VARCHAR(10)   NOT NULL,   -- 'SPX' = S&P500, 'IXIC' = 나스닥
    date            DATE          NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    change_pct      NUMERIC(8,4),             -- 전일 대비 변동률 (%)
    PRIMARY KEY (index_code, date)
);

-- ============================================================
-- stock_scores 테이블 — 고도화 보정 컬럼 추가 (STEP B~F)
-- ============================================================
DO $$
BEGIN
    -- macro_adjustment (STEP B, D: 환율·미국시장 보정)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stock_scores' AND column_name = 'macro_adjustment'
    ) THEN
        ALTER TABLE stock_scores ADD COLUMN macro_adjustment NUMERIC(5,2) DEFAULT 0;
    END IF;

    -- disclosure_adjustment (STEP E: 공시 감성 보정)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stock_scores' AND column_name = 'disclosure_adjustment'
    ) THEN
        ALTER TABLE stock_scores ADD COLUMN disclosure_adjustment NUMERIC(5,2) DEFAULT 0;
    END IF;

    -- news_adjustment (STEP F: 뉴스 감성 보정)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stock_scores' AND column_name = 'news_adjustment'
    ) THEN
        ALTER TABLE stock_scores ADD COLUMN news_adjustment NUMERIC(5,2) DEFAULT 0;
    END IF;

    -- adjusted_total_score (total_score + 보정값 합계)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'stock_scores' AND column_name = 'adjusted_total_score'
    ) THEN
        ALTER TABLE stock_scores ADD COLUMN adjusted_total_score NUMERIC(5,2);
    END IF;

    -- market_regime 컬럼 크기 확장: VARCHAR(10) → VARCHAR(20)
    -- CAUTIOUS_BULL(13자) 등 긴 Regime 이름 지원 (STEP C)
    ALTER TABLE stock_scores ALTER COLUMN market_regime TYPE VARCHAR(20);
END $$;

-- ============================================================
-- 적용 확인
-- ============================================================
SELECT
    'macro_indicators'   AS table_name, COUNT(*) AS row_count FROM macro_indicators
UNION ALL
SELECT
    'us_market_prices'   AS table_name, COUNT(*) AS row_count FROM us_market_prices
UNION ALL
SELECT
    column_name          AS table_name,
    CASE WHEN column_name IS NOT NULL THEN 1 ELSE 0 END AS row_count
FROM information_schema.columns
WHERE table_name = 'stock_scores'
  AND column_name IN ('macro_adjustment', 'disclosure_adjustment', 'news_adjustment', 'adjusted_total_score')
ORDER BY table_name;