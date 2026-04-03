"""
price_collector.py
코스피200 + 코스닥150 종목의 일별 OHLCV·시총 데이터를 pykrx로 수집하여 DB에 저장.
"""
from __future__ import annotations

import time

import requests
from loguru import logger
from pykrx import stock as krx

from src.db.repository import StockRepository

# KRX 지수 코드
KOSPI200_IDX = "1028"
KOSDAQ150_IDX = "2203"

# pykrx 연속 요청 간 최소 대기 시간 (초) — rate limit 방지
REQUEST_DELAY = 0.5

# finder_stkisu 폴백 시 종목 수 제한
KOSPI_LIMIT = 200
KOSDAQ_LIMIT = 150


def _get_tickers_via_finder(mktsel: str, limit: int) -> list[str]:
    """
    KRX finder_stkisu API(공개 엔드포인트)로 종목 코드 목록을 가져온다.
    MDCSTAT* 엔드포인트가 차단된 경우의 폴백으로 사용한다.

    종목은 시가총액 순서를 알 수 없으므로 6자리 숫자 코드를 숫자 오름차순으로 정렬한다.
    (낮은 번호 = 오래된 대형주와 높은 상관관계)
    limit개만 반환한다.
    """
    url = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
    }
    data = {"bld": "dbms/comm/finder/finder_stkisu", "mktsel": mktsel, "searchText": ""}
    resp = requests.post(url, headers=headers, data=data, timeout=10)
    items = resp.json().get("block1", [])

    # 6자리 순수 숫자 코드만 (우선주·전환주 제외)
    codes = [
        i["short_code"]
        for i in items
        if len(i["short_code"]) == 6 and i["short_code"].isdigit()
    ]
    codes.sort()  # 숫자 오름차순 → 오래된 대형주 우선
    return codes[:limit]


class PriceCollector:
    """pykrx를 이용해 코스피200 + 코스닥150 가격 데이터를 수집한다."""

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # 종목 풀
    # ------------------------------------------------------------------

    def get_target_pool(self, date: str) -> dict[str, list[str]]:
        """
        date 기준 코스피200 + 코스닥150 구성 티커 목록 반환.

        KRX MDCSTAT 엔드포인트가 차단된 경우 finder_stkisu 폴백을 사용한다.

        Args:
            date: 기준일 (YYYYMMDD)

        Returns:
            {"KOSPI": [...], "KOSDAQ": [...]}
        """
        from src.utils.krx_auth import login_krx_if_needed
        login_krx_if_needed()

        result: dict[str, list[str]] = {"KOSPI": [], "KOSDAQ": []}

        try:
            kospi200 = krx.get_index_portfolio_deposit_file(KOSPI200_IDX, date)
            result["KOSPI"] = list(kospi200)
            logger.info(f"코스피200 종목 수: {len(result['KOSPI'])}")
        except Exception as e:
            logger.error(f"코스피200 종목 조회 실패: {e}")

        time.sleep(REQUEST_DELAY)

        try:
            kosdaq150 = krx.get_index_portfolio_deposit_file(KOSDAQ150_IDX, date)
            result["KOSDAQ"] = list(kosdaq150)
            logger.info(f"코스닥150 종목 수: {len(result['KOSDAQ'])}")
        except Exception as e:
            logger.error(f"코스닥150 종목 조회 실패: {e}")

        # KRX MDCSTAT API가 차단된 경우 finder_stkisu 폴백
        if not result["KOSPI"]:
            logger.warning(
                "KRX 지수구성종목 API 응답 없음 — finder_stkisu 폴백 사용 "
                f"(KOSPI 상위 {KOSPI_LIMIT}개, 숫자코드 오름차순 근사치)"
            )
            try:
                result["KOSPI"] = _get_tickers_via_finder("STK", KOSPI_LIMIT)
                logger.info(f"폴백 KOSPI 종목 수: {len(result['KOSPI'])}")
            except Exception as e:
                logger.error(f"KOSPI 폴백 조회 실패: {e}")

        if not result["KOSDAQ"]:
            logger.warning(
                "KRX 지수구성종목 API 응답 없음 — finder_stkisu 폴백 사용 "
                f"(KOSDAQ 상위 {KOSDAQ_LIMIT}개, 숫자코드 오름차순 근사치)"
            )
            try:
                result["KOSDAQ"] = _get_tickers_via_finder("KSQ", KOSDAQ_LIMIT)
                logger.info(f"폴백 KOSDAQ 종목 수: {len(result['KOSDAQ'])}")
            except Exception as e:
                logger.error(f"KOSDAQ 폴백 조회 실패: {e}")

        return result

    # ------------------------------------------------------------------
    # 종목 마스터
    # ------------------------------------------------------------------

    def collect_stock_master(self, date: str, pool: dict[str, list[str]] | None = None) -> None:
        """
        종목 이름·시장 정보를 stocks 테이블에 upsert.
        sector / industry / listed_at 은 이 단계에서 수집하지 않는다.

        Args:
            date: 기준일 (YYYYMMDD)
            pool: 미리 조회된 종목 풀 (없으면 내부에서 조회)
        """
        if pool is None:
            pool = self.get_target_pool(date)

        count = 0
        for market, tickers in pool.items():
            for ticker in tickers:
                try:
                    name = krx.get_market_ticker_name(ticker)
                    self.repo.upsert_stock(
                        {
                            "code": ticker,
                            "name": name,
                            "market": market,
                            "sector": None,
                            "industry": None,
                            "listed_at": None,
                            "is_active": True,
                        }
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"종목 마스터 수집 실패 | code={ticker} | {e}")
                time.sleep(REQUEST_DELAY)

        logger.info(f"종목 마스터 upsert 완료 | {count}건")

    # ------------------------------------------------------------------
    # 가격
    # ------------------------------------------------------------------

    def collect_prices_for_ticker(self, code: str, fromdate: str, todate: str) -> int:
        """
        단일 종목 OHLCV + 시총 데이터를 수집하여 daily_prices에 저장.
        시총 조회 실패 시에도 OHLCV는 저장한다.

        Returns:
            저장된 행 수
        """
        try:
            ohlcv = krx.get_market_ohlcv_by_date(fromdate, todate, code)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"OHLCV 조회 실패 | code={code} | {e}")
            return 0

        if ohlcv is None or ohlcv.empty:
            logger.debug(f"가격 데이터 없음 | code={code}")
            return 0

        # 시총·상장주식수는 현재 KRX API 차단으로 수집 불가 — NULL 허용
        cap = None
        try:
            cap = krx.get_market_cap_by_date(fromdate, todate, code)
            time.sleep(REQUEST_DELAY)
        except Exception:
            pass  # 시총 없어도 OHLCV는 저장

        cap_index = set(cap.index) if (cap is not None and not cap.empty) else set()

        rows: list[dict] = []
        for idx in ohlcv.index:
            o = ohlcv.loc[idx]
            close_val = _to_int(o.get("종가"))
            if not close_val:
                continue  # close NOT NULL — 0이거나 None이면 스킵

            market_cap: int | None = None
            shares_out: int | None = None
            if idx in cap_index:
                c = cap.loc[idx]
                market_cap = _to_int(c.get("시가총액"))
                shares_out = _to_int(c.get("상장주식수"))

            rows.append(
                {
                    "code": code,
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": _to_int(o.get("시가")),
                    "high": _to_int(o.get("고가")),
                    "low": _to_int(o.get("저가")),
                    "close": close_val,
                    "volume": _to_int(o.get("거래량")),
                    "trading_value": _to_int(o.get("거래대금")),
                    "market_cap": market_cap,
                    "shares_out": shares_out,
                }
            )

        if rows:
            self.repo.bulk_insert_prices(rows)
        return len(rows)

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(self, fromdate: str, todate: str, ref_date: str | None = None) -> None:
        """
        코스피200 + 코스닥150 전체 종목 가격 수집.

        Args:
            fromdate: 수집 시작일 (YYYYMMDD)
            todate:   수집 종료일 (YYYYMMDD)
            ref_date: 종목 풀 기준일 (기본값: todate)

        Example:
            from src.db.repository import StockRepository
            repo = StockRepository()
            PriceCollector(repo).run("20240101", "20241231")
        """
        ref_date = ref_date or todate
        logger.info(f"가격 수집 시작 | {fromdate} ~ {todate} | 종목풀 기준일={ref_date}")

        pool = self.get_target_pool(ref_date)
        self.collect_stock_master(ref_date, pool=pool)

        pairs: list[tuple[str, str]] = (
            [(t, "KOSPI") for t in pool["KOSPI"]]
            + [(t, "KOSDAQ") for t in pool["KOSDAQ"]]
        )
        total = len(pairs)
        saved = 0

        for i, (code, market) in enumerate(pairs, 1):
            n = self.collect_prices_for_ticker(code, fromdate, todate)
            saved += n
            if n == 0:
                logger.warning(f"저장 0건 | [{i}/{total}] code={code} market={market}")
            else:
                logger.debug(f"저장 {n}건 | [{i}/{total}] code={code} market={market}")

        logger.info(f"가격 수집 완료 | 종목={total}, 저장={saved}건")


# ------------------------------------------------------------------
# 유틸
# ------------------------------------------------------------------

def _to_int(val) -> int | None:
    """값을 int로 변환. 0 또는 변환 불가 시 None 반환."""
    try:
        v = int(val)
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None