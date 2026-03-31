from __future__ import annotations

from typing import Any

import pandas as pd
import psycopg2.extras
from loguru import logger

from src.db.connection import DBConnection


class StockRepository:
    """DB 조회/저장 함수 모음."""

    # ------------------------------------------------------------------
    # 종목 마스터
    # ------------------------------------------------------------------

    def get_stock(self, code: str) -> dict | None:
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM stocks WHERE code = %s", (code,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_all_stocks(self, market: str | None = None) -> list[dict]:
        sql = "SELECT * FROM stocks WHERE is_active = TRUE"
        params: tuple = ()
        if market:
            sql += " AND market = %s"
            params = (market,)
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

    def upsert_stock(self, stock: dict) -> None:
        sql = """
            INSERT INTO stocks (code, name, market, sector, industry, listed_at, is_active)
            VALUES (%(code)s, %(name)s, %(market)s, %(sector)s, %(industry)s, %(listed_at)s, %(is_active)s)
            ON CONFLICT (code) DO UPDATE SET
                name       = EXCLUDED.name,
                market     = EXCLUDED.market,
                sector     = EXCLUDED.sector,
                industry   = EXCLUDED.industry,
                listed_at  = EXCLUDED.listed_at,
                is_active  = EXCLUDED.is_active,
                updated_at = NOW()
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, stock)

    def get_stock_sector(self, code: str) -> str | None:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sector FROM stocks WHERE code = %s", (code,))
                row = cur.fetchone()
                return row[0] if row else None

    # ------------------------------------------------------------------
    # 가격
    # ------------------------------------------------------------------

    def get_prices(self, code: str, lookback: int = 252) -> pd.DataFrame:
        sql = """
            SELECT date, open, high, low, close, volume, trading_value, market_cap, shares_out
            FROM daily_prices
            WHERE code = %s
            ORDER BY date DESC
            LIMIT %s
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (code, lookback))
                rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def bulk_insert_prices(self, rows: list[dict]) -> None:
        sql = """
            INSERT INTO daily_prices
                (code, date, open, high, low, close, volume, trading_value, market_cap, shares_out)
            VALUES
                (%(code)s, %(date)s, %(open)s, %(high)s, %(low)s, %(close)s,
                 %(volume)s, %(trading_value)s, %(market_cap)s, %(shares_out)s)
            ON CONFLICT (code, date) DO UPDATE SET
                open          = EXCLUDED.open,
                high          = EXCLUDED.high,
                low           = EXCLUDED.low,
                close         = EXCLUDED.close,
                volume        = EXCLUDED.volume,
                trading_value = EXCLUDED.trading_value,
                market_cap    = EXCLUDED.market_cap,
                shares_out    = EXCLUDED.shares_out
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
        logger.debug(f"daily_prices upsert {len(rows)}건")

    # ------------------------------------------------------------------
    # 투자자별 매매동향
    # ------------------------------------------------------------------

    def bulk_insert_investor_trading(self, rows: list[dict]) -> None:
        sql = """
            INSERT INTO investor_trading (code, date, inst_net_buy, foreign_net_buy, retail_net_buy)
            VALUES (%(code)s, %(date)s, %(inst_net_buy)s, %(foreign_net_buy)s, %(retail_net_buy)s)
            ON CONFLICT (code, date) DO UPDATE SET
                inst_net_buy    = EXCLUDED.inst_net_buy,
                foreign_net_buy = EXCLUDED.foreign_net_buy,
                retail_net_buy  = EXCLUDED.retail_net_buy
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
        logger.debug(f"investor_trading upsert {len(rows)}건")

    def get_investor_trading(self, code: str, lookback: int = 20) -> pd.DataFrame:
        sql = """
            SELECT date, inst_net_buy, foreign_net_buy, retail_net_buy
            FROM investor_trading
            WHERE code = %s
            ORDER BY date DESC
            LIMIT %s
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (code, lookback))
                rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        return df.sort_values("date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # 코스피 지수
    # ------------------------------------------------------------------

    def bulk_insert_index_prices(self, rows: list[dict]) -> None:
        sql = """
            INSERT INTO index_prices (index_code, date, close)
            VALUES (%(index_code)s, %(date)s, %(close)s)
            ON CONFLICT (index_code, date) DO UPDATE SET close = EXCLUDED.close
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
        logger.debug(f"index_prices upsert {len(rows)}건")

    def get_index_prices(self, index_code: str = "1001", lookback: int = 120) -> pd.DataFrame:
        sql = """
            SELECT date, close
            FROM index_prices
            WHERE index_code = %s
            ORDER BY date DESC
            LIMIT %s
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (index_code, lookback))
                rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        return df.sort_values("date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # 재무제표
    # ------------------------------------------------------------------

    def get_latest_financials(self, code: str, as_of_date: str) -> dict | None:
        """look-ahead bias 방지: as_of_date 시점에 공시된 가장 최근 재무제표 반환."""
        sql = """
            SELECT * FROM financials
            WHERE code = %s
              AND report_type = 'CFS'
              AND disclosed_at <= %s
            ORDER BY fiscal_year DESC, fiscal_quarter DESC
            LIMIT 1
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (code, as_of_date))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_all_financials(self, as_of_date: str | None = None) -> pd.DataFrame:
        """모든 종목의 최신 재무제표 (루프 밖 캐싱용)."""
        sql = """
            SELECT DISTINCT ON (code) *
            FROM financials
            WHERE report_type = 'CFS'
        """
        params: tuple = ()
        if as_of_date:
            sql += " AND disclosed_at <= %s"
            params = (as_of_date,)
        sql += " ORDER BY code, fiscal_year DESC, fiscal_quarter DESC"
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def get_financials_grouped_by_sector(self, as_of_date: str | None = None) -> dict[str, pd.DataFrame]:
        """섹터별 재무 데이터 맵 반환 (루프 밖 캐싱용)."""
        all_fin = self.get_all_financials(as_of_date)
        if all_fin.empty:
            return {}
        # stocks 테이블에서 섹터 정보 조인
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT code, sector FROM stocks WHERE is_active = TRUE")
                sector_map = {r["code"]: r["sector"] for r in cur.fetchall()}
        all_fin["sector"] = all_fin["code"].map(sector_map)
        result: dict[str, pd.DataFrame] = {}
        for sector, group in all_fin.groupby("sector"):
            if sector:
                result[sector] = group.reset_index(drop=True)
        return result

    def upsert_financials(self, fin: dict) -> None:
        sql = """
            INSERT INTO financials
                (code, fiscal_year, fiscal_quarter, report_type,
                 revenue, operating_profit, net_income,
                 total_assets, total_equity, total_debt,
                 per, pbr, roe, debt_ratio, operating_margin, disclosed_at)
            VALUES
                (%(code)s, %(fiscal_year)s, %(fiscal_quarter)s, %(report_type)s,
                 %(revenue)s, %(operating_profit)s, %(net_income)s,
                 %(total_assets)s, %(total_equity)s, %(total_debt)s,
                 %(per)s, %(pbr)s, %(roe)s, %(debt_ratio)s, %(operating_margin)s, %(disclosed_at)s)
            ON CONFLICT (code, fiscal_year, fiscal_quarter, report_type) DO UPDATE SET
                revenue          = EXCLUDED.revenue,
                operating_profit = EXCLUDED.operating_profit,
                net_income       = EXCLUDED.net_income,
                total_assets     = EXCLUDED.total_assets,
                total_equity     = EXCLUDED.total_equity,
                total_debt       = EXCLUDED.total_debt,
                per              = EXCLUDED.per,
                pbr              = EXCLUDED.pbr,
                roe              = EXCLUDED.roe,
                debt_ratio       = EXCLUDED.debt_ratio,
                operating_margin = EXCLUDED.operating_margin,
                disclosed_at     = EXCLUDED.disclosed_at
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, fin)

    # ------------------------------------------------------------------
    # 공시
    # ------------------------------------------------------------------

    def get_recent_disclosures(self, code: str, days: int = 30) -> list[dict]:
        sql = """
            SELECT * FROM disclosures
            WHERE code = %s
              AND disclosed_at >= NOW() - INTERVAL '%s days'
            ORDER BY disclosed_at DESC
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (code, days))
                return [dict(r) for r in cur.fetchall()]

    def upsert_disclosure(self, disc: dict) -> None:
        sql = """
            INSERT INTO disclosures (code, dart_rcp_no, title, category, disclosed_at, sentiment_score)
            VALUES (%(code)s, %(dart_rcp_no)s, %(title)s, %(category)s, %(disclosed_at)s, %(sentiment_score)s)
            ON CONFLICT (dart_rcp_no) DO NOTHING
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, disc)

    # ------------------------------------------------------------------
    # 섹터
    # ------------------------------------------------------------------

    def upsert_sector(self, sector: dict) -> None:
        sql = """
            INSERT INTO sectors (name, avg_per, avg_pbr)
            VALUES (%(name)s, %(avg_per)s, %(avg_pbr)s)
            ON CONFLICT (name) DO UPDATE SET
                avg_per    = EXCLUDED.avg_per,
                avg_pbr    = EXCLUDED.avg_pbr,
                updated_at = NOW()
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, sector)

    def get_sector_stats(self, sector_name: str) -> dict | None:
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM sectors WHERE name = %s", (sector_name,))
                row = cur.fetchone()
                return dict(row) if row else None

    # ------------------------------------------------------------------
    # 스코어 저장
    # ------------------------------------------------------------------

    def save_stock_score(self, score: dict) -> None:
        sql = """
            INSERT INTO stock_scores
                (code, date, rsi_score, macd_score, bb_score, technical_score,
                 per_score, pbr_score, roe_score, debt_score, fundamental_score,
                 volume_score, inst_score, high52_score, momentum_score,
                 total_score, rank, market_regime)
            VALUES
                (%(code)s, %(date)s, %(rsi_score)s, %(macd_score)s, %(bb_score)s, %(technical_score)s,
                 %(per_score)s, %(pbr_score)s, %(roe_score)s, %(debt_score)s, %(fundamental_score)s,
                 %(volume_score)s, %(inst_score)s, %(high52_score)s, %(momentum_score)s,
                 %(total_score)s, %(rank)s, %(market_regime)s)
            ON CONFLICT (code, date) DO UPDATE SET
                rsi_score         = EXCLUDED.rsi_score,
                macd_score        = EXCLUDED.macd_score,
                bb_score          = EXCLUDED.bb_score,
                technical_score   = EXCLUDED.technical_score,
                per_score         = EXCLUDED.per_score,
                pbr_score         = EXCLUDED.pbr_score,
                roe_score         = EXCLUDED.roe_score,
                debt_score        = EXCLUDED.debt_score,
                fundamental_score = EXCLUDED.fundamental_score,
                volume_score      = EXCLUDED.volume_score,
                inst_score        = EXCLUDED.inst_score,
                high52_score      = EXCLUDED.high52_score,
                momentum_score    = EXCLUDED.momentum_score,
                total_score       = EXCLUDED.total_score,
                rank              = EXCLUDED.rank,
                market_regime     = EXCLUDED.market_regime
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, score)

    def save_recommendation(self, rec: dict) -> int:
        sql = """
            INSERT INTO recommendations (date, rank, code, total_score, reason)
            VALUES (%(date)s, %(rank)s, %(code)s, %(total_score)s, %(reason)s)
            ON CONFLICT (date, rank) DO UPDATE SET
                code        = EXCLUDED.code,
                total_score = EXCLUDED.total_score,
                reason      = EXCLUDED.reason,
                created_at  = NOW()
            RETURNING id
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, rec)
                return cur.fetchone()[0]

    def get_all_recommendations(self) -> list[dict]:
        """백테스트 평가용: 전체 추천 이력 반환."""
        sql = """
            SELECT id, date, rank, code, total_score
            FROM recommendations
            ORDER BY date DESC, rank
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchall()]

    def get_price_on_date(self, code: str, target_date: str) -> int | None:
        """특정 날짜의 종가를 반환. 없으면 None."""
        sql = """
            SELECT close FROM daily_prices
            WHERE code = %s AND date <= %s
            ORDER BY date DESC
            LIMIT 1
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (code, target_date))
                row = cur.fetchone()
                return row[0] if row else None

    def save_recommendation_return(self, data: dict) -> None:
        """recommendation_returns 테이블 upsert."""
        sql = """
            INSERT INTO recommendation_returns
                (recommendation_id, days_after, return_rate, benchmark_rate)
            VALUES
                (%(recommendation_id)s, %(days_after)s, %(return_rate)s, %(benchmark_rate)s)
            ON CONFLICT (recommendation_id, days_after) DO UPDATE SET
                return_rate    = EXCLUDED.return_rate,
                benchmark_rate = EXCLUDED.benchmark_rate
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, data)

    def get_recommendation_returns(self, recommendation_id: int) -> list[dict]:
        """특정 추천의 수익률 기록 반환."""
        sql = """
            SELECT days_after, return_rate, benchmark_rate
            FROM recommendation_returns
            WHERE recommendation_id = %s
            ORDER BY days_after
        """
        with DBConnection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (recommendation_id,))
                return [dict(r) for r in cur.fetchall()]