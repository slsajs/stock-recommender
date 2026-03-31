"""
finance_collector.py
OpenDartReader를 이용해 KOSPI200 + KOSDAQ150 종목의 재무제표를 수집하여 DB에 저장.

공시일(disclosed_at) 기준으로 저장하여 look-ahead bias를 방지한다.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

import pandas as pd
from loguru import logger

from src.collector.price_collector import PriceCollector, REQUEST_DELAY
from src.config import settings
from src.db.repository import StockRepository

try:
    import OpenDartReader
    _DART_AVAILABLE = True
except ImportError:
    _DART_AVAILABLE = False
    logger.warning("OpenDartReader 미설치 — pip install opendartreader")

# 보고서 코드 → fiscal_quarter 매핑
REPRT_CODE_MAP: dict[str, int] = {
    "11013": 1,   # 1분기보고서
    "11012": 2,   # 반기보고서
    "11014": 3,   # 3분기보고서
    "11011": 4,   # 사업보고서 (연간)
}

# 재무 계정명 → 우선순위 순 후보 목록
ACCOUNT_MAP: dict[str, list[str]] = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "operating_profit": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "당기순손익"],
    "total_assets": ["자산총계"],
    "total_equity": ["자본총계"],
    "total_debt": ["부채총계"],
}


class FinanceCollector:
    """OpenDartReader를 이용해 재무제표 데이터를 수집한다."""

    def __init__(self, repo: StockRepository) -> None:
        if not _DART_AVAILABLE:
            raise RuntimeError("OpenDartReader가 설치되어 있지 않습니다. pip install opendartreader")
        self.repo = repo
        self.dart = OpenDartReader.OpenDartReader(settings.dart_api_key)
        self._price_collector = PriceCollector(repo)
        self._corp_code_map: dict[str, str] = {}  # stock_code → corp_code 캐시

    # ------------------------------------------------------------------
    # 법인코드 매핑
    # ------------------------------------------------------------------

    def _build_corp_code_map(self) -> None:
        """DART 상장법인 목록으로 stock_code → corp_code 매핑 구성."""
        try:
            df = self.dart.corp_codes
            if df is None or df.empty:
                logger.error("DART 법인코드 목록 조회 실패")
                return
            # stock_code 있는 상장법인만 필터
            listed = df[df["stock_code"].notna() & (df["stock_code"].str.strip() != "")]
            self._corp_code_map = dict(zip(listed["stock_code"].str.strip(), listed["corp_code"]))
            logger.info(f"법인코드 매핑 완료 | {len(self._corp_code_map)}개 상장법인")
        except Exception as e:
            logger.error(f"법인코드 매핑 실패: {e}")

    def _get_corp_code(self, stock_code: str) -> str | None:
        if not self._corp_code_map:
            self._build_corp_code_map()
        return self._corp_code_map.get(stock_code.zfill(6))

    # ------------------------------------------------------------------
    # 파싱 유틸
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_amount(val: Any) -> int | None:
        """콤마 포함 숫자 문자열 → int. 파싱 불가 시 None."""
        if val is None:
            return None
        s = str(val).replace(",", "").replace(" ", "").strip()
        if s in ("", "-", "―", "N/A"):
            return None
        try:
            return int(s)
        except ValueError:
            return None

    @staticmethod
    def _get_disclosed_at(rcept_no: str) -> date | None:
        """접수번호 앞 8자리(YYYYMMDD)에서 공시일 파싱."""
        if len(rcept_no) >= 8:
            try:
                return datetime.strptime(rcept_no[:8], "%Y%m%d").date()
            except ValueError:
                pass
        return None

    def _extract_account(self, df: pd.DataFrame, candidates: list[str]) -> int | None:
        """finstate DataFrame에서 account_nm 후보 목록으로 금액 추출."""
        for name in candidates:
            rows = df[df["account_nm"] == name]
            if not rows.empty:
                return self._parse_amount(rows.iloc[0].get("thstrm_amount"))
        return None

    # ------------------------------------------------------------------
    # 단일 종목 수집
    # ------------------------------------------------------------------

    def collect_for_ticker(self, stock_code: str, bsns_year: int) -> int:
        """
        단일 종목 특정 사업연도 재무제표 수집 (사업/반기/분기보고서 전부).

        Returns:
            저장 건수
        """
        corp_code = self._get_corp_code(stock_code)
        if corp_code is None:
            logger.debug(f"법인코드 없음 (비상장 또는 미매핑) | code={stock_code}")
            return 0

        saved = 0
        for reprt_code, quarter in REPRT_CODE_MAP.items():
            try:
                df = self.dart.finstate(corp_code, str(bsns_year), reprt_code)
                time.sleep(REQUEST_DELAY)

                if df is None or df.empty:
                    continue

                # 공시일 추출
                rcept_no = str(df.iloc[0].get("rcept_no", ""))
                disclosed_at = self._get_disclosed_at(rcept_no)

                # 재무상태표(BS) / 손익계산서(IS, CIS) 분리
                bs = df[df["sj_div"] == "BS"]
                is_df = df[df["sj_div"].isin(["IS", "CIS"])]

                total_assets = self._extract_account(bs, ACCOUNT_MAP["total_assets"])
                total_equity = self._extract_account(bs, ACCOUNT_MAP["total_equity"])
                total_debt = self._extract_account(bs, ACCOUNT_MAP["total_debt"])
                revenue = self._extract_account(is_df, ACCOUNT_MAP["revenue"])
                op_profit = self._extract_account(is_df, ACCOUNT_MAP["operating_profit"])
                net_income = self._extract_account(is_df, ACCOUNT_MAP["net_income"])

                # 비율 계산
                roe: float | None = None
                if net_income is not None and total_equity and total_equity > 0:
                    roe = round(net_income / total_equity * 100, 2)

                debt_ratio: float | None = None
                if total_debt is not None and total_equity and total_equity > 0:
                    debt_ratio = round(total_debt / total_equity * 100, 2)

                op_margin: float | None = None
                if op_profit is not None and revenue and revenue > 0:
                    op_margin = round(op_profit / revenue * 100, 2)

                self.repo.upsert_financials(
                    {
                        "code": stock_code,
                        "fiscal_year": bsns_year,
                        "fiscal_quarter": quarter,
                        "report_type": "CFS",
                        "revenue": revenue,
                        "operating_profit": op_profit,
                        "net_income": net_income,
                        "total_assets": total_assets,
                        "total_equity": total_equity,
                        "total_debt": total_debt,
                        "per": None,    # 가격 데이터로 별도 계산 필요
                        "pbr": None,    # 가격 데이터로 별도 계산 필요
                        "roe": roe,
                        "debt_ratio": debt_ratio,
                        "operating_margin": op_margin,
                        "disclosed_at": str(disclosed_at) if disclosed_at else None,
                    }
                )
                saved += 1

            except Exception as e:
                logger.warning(
                    f"재무제표 수집 실패 | code={stock_code} "
                    f"year={bsns_year} q={quarter} | {e}"
                )

        return saved

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(self, years: list[int] | None = None, ref_date: str | None = None) -> None:
        """
        코스피200 + 코스닥150 전체 종목 재무제표 수집.

        Args:
            years:    수집할 사업연도 목록 (기본값: 최근 2년)
            ref_date: 종목 풀 기준일 (YYYYMMDD, 기본값: 오늘)

        Example:
            repo = StockRepository()
            FinanceCollector(repo).run(years=[2023, 2024])
        """
        today_str = ref_date or date.today().strftime("%Y%m%d")
        current_year = int(today_str[:4])

        if years is None:
            years = [current_year - 1, current_year]

        logger.info(f"재무제표 수집 시작 | years={years} | 종목풀 기준일={today_str}")
        self._build_corp_code_map()

        pool = self._price_collector.get_target_pool(today_str)
        all_tickers = pool["KOSPI"] + pool["KOSDAQ"]
        total = len(all_tickers)

        total_saved = 0
        for i, code in enumerate(all_tickers, 1):
            for year in years:
                n = self.collect_for_ticker(code, year)
                total_saved += n
            logger.debug(f"[{i}/{total}] {code} | 누적={total_saved}건")

        logger.info(f"재무제표 수집 완료 | 종목={total}, 저장={total_saved}건")
