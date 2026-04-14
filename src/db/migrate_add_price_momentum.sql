-- migrate_add_price_momentum.sql
-- 방향 B: 52주 신고가 대신 60거래일 가격 모멘텀 도입
--
-- 실행:
--   psql -U postgres -d stock_recommender -f src/db/migrate_add_price_momentum.sql

-- stock_scores 테이블에 price_momentum_score 컬럼 추가
ALTER TABLE stock_scores
    ADD COLUMN IF NOT EXISTS price_momentum_score NUMERIC(5,2);

COMMENT ON COLUMN stock_scores.price_momentum_score
    IS '60거래일(약 3개월) 가격 수익률 기반 모멘텀 점수 (0~100). 방향 B에서 high52_score 대체.';
