-- ============================================
-- 종목 마스터
-- ============================================
CREATE TABLE IF NOT EXISTS stocks (
    code            VARCHAR(10)  PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    market          VARCHAR(10)  NOT NULL,
    sector          VARCHAR(50),
    industry        VARCHAR(100),
    listed_at       DATE,
    is_active       BOOLEAN      DEFAULT TRUE,
    updated_at      TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sectors (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) UNIQUE NOT NULL,
    avg_per     NUMERIC(8,2),
    avg_pbr     NUMERIC(8,2),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- stocks.sector → sectors.name FK
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_stocks_sector'
    ) THEN
        ALTER TABLE stocks
            ADD CONSTRAINT fk_stocks_sector
            FOREIGN KEY (sector) REFERENCES sectors(name);
    END IF;
END $$;

-- ============================================
-- 가격/거래량 (TimescaleDB hypertable)
-- ============================================
CREATE TABLE IF NOT EXISTS daily_prices (
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

SELECT create_hypertable('daily_prices', 'date', if_not_exists => TRUE);

-- ============================================
-- 투자자별 매매동향
-- ============================================
CREATE TABLE IF NOT EXISTS investor_trading (
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
CREATE TABLE IF NOT EXISTS financials (
    id               BIGSERIAL PRIMARY KEY,
    code             VARCHAR(10) NOT NULL REFERENCES stocks(code),
    fiscal_year      SMALLINT    NOT NULL,
    fiscal_quarter   SMALLINT    NOT NULL,
    report_type      VARCHAR(10) NOT NULL,
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
    disclosed_at     DATE,
    UNIQUE (code, fiscal_year, fiscal_quarter, report_type)
);

-- ============================================
-- 공시
-- ============================================
CREATE TABLE IF NOT EXISTS disclosures (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(10) REFERENCES stocks(code),
    dart_rcp_no     VARCHAR(20) UNIQUE,
    title           VARCHAR(300) NOT NULL,
    category        VARCHAR(50),
    disclosed_at    TIMESTAMP NOT NULL,
    sentiment_score NUMERIC(4,2),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_disclosures_code_date ON disclosures (code, disclosed_at DESC);

-- ============================================
-- 코스피 지수 (Market Regime 판단용)
-- ============================================
CREATE TABLE IF NOT EXISTS index_prices (
    index_code      VARCHAR(10) NOT NULL,
    date            DATE        NOT NULL,
    close           BIGINT      NOT NULL,
    PRIMARY KEY (index_code, date)
);

-- ============================================
-- [고도화] 거시경제 지표 (STEP A~C)
-- ============================================
CREATE TABLE IF NOT EXISTS macro_indicators (
    date            DATE          NOT NULL,
    indicator_code  VARCHAR(30)   NOT NULL,   -- 'BASE_RATE', 'USD_KRW', 'KTB_10Y', 'CPI_YOY'
    value           NUMERIC(12,4) NOT NULL,
    PRIMARY KEY (date, indicator_code)
);

-- ============================================
-- [고도화] 미국 시장 지수 (STEP D)
-- ============================================
CREATE TABLE IF NOT EXISTS us_market_prices (
    index_code      VARCHAR(10)   NOT NULL,   -- 'SPX' = S&P500, 'IXIC' = 나스닥
    date            DATE          NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    change_pct      NUMERIC(8,4),             -- 전일 대비 변동률 (%)
    PRIMARY KEY (index_code, date)
);

-- ============================================
-- 스코어링 결과
-- ============================================
CREATE TABLE IF NOT EXISTS stock_scores (
    code              VARCHAR(10) NOT NULL REFERENCES stocks(code),
    date              DATE        NOT NULL,
    rsi_score         NUMERIC(5,2),
    macd_score        NUMERIC(5,2),
    bb_score          NUMERIC(5,2),
    technical_score   NUMERIC(5,2),
    per_score         NUMERIC(5,2),
    pbr_score         NUMERIC(5,2),
    roe_score         NUMERIC(5,2),
    debt_score        NUMERIC(5,2),
    fundamental_score NUMERIC(5,2),
    volume_score      NUMERIC(5,2),
    inst_score        NUMERIC(5,2),
    high52_score      NUMERIC(5,2),
    momentum_score    NUMERIC(5,2),
    total_score       NUMERIC(5,2) NOT NULL,
    rank              SMALLINT,
    market_regime     VARCHAR(20),
    -- [고도화] 보정값 컬럼 (STEP B~F에서 채워짐, 기본 0)
    macro_adjustment        NUMERIC(5,2) DEFAULT 0,  -- 환율·미국시장 보정 (STEP B, D)
    disclosure_adjustment   NUMERIC(5,2) DEFAULT 0,  -- 공시 감성 보정 (STEP E)
    news_adjustment         NUMERIC(5,2) DEFAULT 0,  -- 뉴스 감성 보정 (STEP F)
    adjusted_total_score    NUMERIC(5,2),             -- total_score + 보정값 합계
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_scores_date_total ON stock_scores (date, total_score DESC);

CREATE TABLE IF NOT EXISTS recommendations (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE        NOT NULL,
    rank        SMALLINT    NOT NULL,
    code        VARCHAR(10) NOT NULL REFERENCES stocks(code),
    total_score NUMERIC(5,2),
    reason      TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (date, rank)
);

-- ============================================
-- 백테스트 성과
-- ============================================
CREATE TABLE IF NOT EXISTS recommendation_returns (
    recommendation_id BIGINT REFERENCES recommendations(id),
    days_after        SMALLINT NOT NULL,
    return_rate       NUMERIC(8,4),
    benchmark_rate    NUMERIC(8,4),
    PRIMARY KEY (recommendation_id, days_after)
);