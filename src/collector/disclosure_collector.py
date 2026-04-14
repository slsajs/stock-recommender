"""
disclosure_collector.py
OpenDartReader를 이용해 KOSPI200 + KOSDAQ150 종목의 공시 목록을 수집하여 DB에 저장.

수집 대상 공시 종류 (DART kind 코드):
  B — 주요사항보고: 유상증자결정, 자기주식취득결정, 전환사채권발행결정,
                   무상증자결정, 감자결정 등 이벤트성 공시 (STEP E 핵심)
  E — 기타공시:    관리종목지정, 거래정지, 불성실공시 등 위험 공시 (filters.py 핵심)

  ※ kind="A" (분기/반기/사업보고서)는 이벤트 정보가 없어 수집하지 않는다.

감성분석(sentiment_score)은 현재 단계에서 항상 NULL로 저장한다.
  → STEP E 스코어링 실행 후 batch_update_disclosure_sentiments()로 채워진다.
"""
from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
from loguru import logger

from src.collector.finance_collector import FinanceCollector
from src.collector.price_collector import PriceCollector, REQUEST_DELAY
from src.config import settings
from src.db.repository import StockRepository

try:
    import OpenDartReader
    _DART_AVAILABLE = True
except ImportError:
    _DART_AVAILABLE = False

# 보고서명에서 카테고리를 판단하는 키워드 매핑
# key: 저장할 category 값, value: report_nm에 포함되어야 하는 키워드 목록 (OR 조건)
# 우선순위: 위에 있을수록 먼저 매칭 (더 구체적인 패턴 먼저 배치)
CATEGORY_KEYWORD_MAP: dict[str, list[str]] = {
    # ── 위험 공시 (filters.py EXCLUDE_DISCLOSURE_CATEGORIES 와 일치) ──────
    "관리종목지정":              ["관리종목", "관리 종목"],
    "상장폐지":                 ["상장폐지", "폐지결정"],
    "불성실공시":               ["불성실공시", "불성실 공시"],
    "회생절차":                 ["회생절차", "기업회생", "회생신청"],
    "거래정지":                 ["거래정지", "매매거래정지"],
    "영업정지":                 ["영업정지"],
    # ── 강한 호재 (disclosure_scorer.py CATEGORY_SENTIMENT 와 일치) ────────
    "자기주식취득결정":          ["자기주식취득결정", "자기주식 취득 결정", "자기주식취득 결정"],
    "주식배당결정":             ["주식배당결정", "주식배당 결정"],
    "무상증자결정":             ["무상증자결정", "무상증자 결정"],
    "타법인주식및출자증권취득결정": ["타법인주식및출자증권취득결정", "타법인주식 취득"],
    # ── 강한 악재 ─────────────────────────────────────────────────────────
    "유상증자결정":             ["유상증자결정", "유상증자 결정"],
    "전환사채권발행결정":        ["전환사채권발행결정", "전환사채 발행", "전환사채권 발행"],
    "감자결정":                 ["감자결정", "감자 결정"],
    "소송등의제기":             ["소송등의제기", "소송 제기"],
    # ── 중립 / 상황 의존 ──────────────────────────────────────────────────
    "대표이사변경":             ["대표이사변경", "대표이사 변경", "최고경영자변경"],
    "합병결정":                 ["합병결정", "합병 결정"],
    "분할결정":                 ["분할결정", "분할 결정"],
    "최대주주변경":             ["최대주주변경", "최대주주 변경"],
}

# 하위 호환성 유지 (filters.py 등 외부 참조 대비)
DANGER_KEYWORD_MAP = CATEGORY_KEYWORD_MAP


def _categorize(report_nm: str) -> str:
    """보고서명으로 공시 카테고리 분류.

    CATEGORY_KEYWORD_MAP 순서대로 키워드를 매칭하여 첫 번째 매칭된 카테고리를 반환.
    매칭 안 되면 '일반공시' 반환.
    """
    for category, keywords in CATEGORY_KEYWORD_MAP.items():
        if any(kw in report_nm for kw in keywords):
            return category
    return "일반공시"


class DisclosureCollector:
    """OpenDartReader를 이용해 공시 목록을 수집한다."""

    def __init__(self, repo: StockRepository) -> None:
        if not _DART_AVAILABLE:
            raise RuntimeError("OpenDartReader가 설치되어 있지 않습니다. pip install opendartreader")
        self.repo = repo
        self.dart = OpenDartReader(settings.dart_api_key)
        self._price_collector = PriceCollector(repo)
        # finance_collector의 법인코드 맵 재사용
        self._finance_collector = FinanceCollector(repo)

    # ------------------------------------------------------------------
    # 단일 종목 수집
    # ------------------------------------------------------------------

    # STEP E + 필터에 필요한 공시 종류
    # B: 주요사항보고 (이벤트성 — 유상증자, 자기주식취득 등)
    # E: 기타공시     (위험 공시 — 관리종목지정, 거래정지 등)
    COLLECT_KINDS: list[str] = ["B", "E"]

    def collect_for_ticker(
        self, stock_code: str, corp_code: str, start: str, end: str
    ) -> int:
        """
        단일 종목 기간 내 공시 목록 수집 → disclosures 테이블 저장.

        kind="B" (주요사항보고)와 kind="E" (기타공시)를 순서대로 조회하여 저장한다.
        kind="A" (정기보고서)는 이벤트 정보가 없어 수집하지 않는다.

        Args:
            stock_code: 종목코드 (pykrx 6자리)
            corp_code:  DART 법인코드
            start:      시작일 (YYYY-MM-DD)
            end:        종료일 (YYYY-MM-DD)

        Returns:
            저장 건수 (kind B + E 합산)
        """
        saved = 0

        for kind in self.COLLECT_KINDS:
            try:
                df = self.dart.list(corp_code, start=start, end=end, kind=kind)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.warning(f"공시 목록 조회 실패 | code={stock_code} kind={kind} | {e}")
                continue

            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                try:
                    rcept_no = str(row.get("rcept_no", ""))
                    report_nm = str(row.get("report_nm", ""))
                    rcept_dt = str(row.get("rcept_dt", ""))

                    if not rcept_no or not rcept_dt:
                        continue

                    disclosed_at = datetime.strptime(rcept_dt, "%Y%m%d")
                    category = _categorize(report_nm)

                    self.repo.upsert_disclosure(
                        {
                            "code": stock_code,
                            "dart_rcp_no": rcept_no,
                            "title": report_nm[:300],
                            "category": category,
                            "disclosed_at": disclosed_at,
                            "sentiment_score": None,
                        }
                    )
                    saved += 1

                except Exception as e:
                    logger.warning(
                        f"공시 저장 실패 | code={stock_code} kind={kind} "
                        f"rcept_no={row.get('rcept_no', '')} | {e}"
                    )

        return saved

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def run(
        self, start: str, end: str, ref_date: str | None = None
    ) -> None:
        """
        코스피200 + 코스닥150 전체 종목 공시 수집.

        Args:
            start:    수집 시작일 (YYYY-MM-DD)
            end:      수집 종료일 (YYYY-MM-DD)
            ref_date: 종목 풀 기준일 (YYYYMMDD, 기본값: 오늘)

        Example:
            repo = StockRepository()
            DisclosureCollector(repo).run("2024-01-01", "2024-12-31")
        """
        today_str = ref_date or date.today().strftime("%Y%m%d")
        logger.info(f"공시 수집 시작 | {start} ~ {end} | 종목풀 기준일={today_str}")

        # 법인코드 맵 구성 (finance_collector 내부 캐시 활용)
        self._finance_collector._build_corp_code_map()
        corp_code_map = self._finance_collector._corp_code_map

        pool = self._price_collector.get_target_pool(today_str)
        all_tickers = pool["KOSPI"] + pool["KOSDAQ"]
        total = len(all_tickers)

        total_saved = 0
        for i, code in enumerate(all_tickers, 1):
            corp_code = corp_code_map.get(code.zfill(6))
            if corp_code is None:
                logger.debug(f"법인코드 없음 | code={code}")
                continue

            n = self.collect_for_ticker(code, corp_code, start, end)
            total_saved += n
            logger.debug(f"[{i}/{total}] {code} | {n}건 | 누적={total_saved}건")

        logger.info(f"공시 수집 완료 | 종목={total}, 저장={total_saved}건")
