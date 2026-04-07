"""
macro_collector.py
한국은행 ECOS Open API에서 거시경제 지표를 수집하여
macro_indicators 테이블에 저장한다.

ECOS API 문서: https://ecos.bok.or.kr/api/#/
엔드포인트:
    https://ecos.bok.or.kr/api/StatisticSearch
    /{api_key}/json/kr/{start_count}/{end_count}
    /{stat_code}/{period}/{start_date}/{end_date}/{item_code1}

수집 대상:
  STEP A: BASE_RATE — 한국은행 기준금리 (통계표: 722Y001, 항목: 0101000, 주기: M)
  STEP B: USD_KRW  — 원/달러 환율      (통계표: 731Y001, 항목: 0000001, 주기: D)
  STEP C: KTB_10Y  — 국고채 10년물     (통계표: 817Y002, 항목: 010200000, 주기: D)

날짜 형식 주의:
  - 주기 D (일별) : YYYYMMDD
  - 주기 M (월별) : YYYYMM   ← BASE_RATE가 해당, YYYYMMDD로 보내면 ERROR-101

ECOS_API_KEY 미설정 시 수집을 건너뛴다.

사용법:
    from src.collector.macro_collector import MacroCollector
    MacroCollector(repo).run()
"""
from __future__ import annotations

from datetime import date, timedelta

import requests
from loguru import logger

from src.db.repository import StockRepository

# ECOS API 베이스 URL
_ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# 수집 대상 명세: (통계표코드, 주기, 항목코드1)
_SERIES: dict[str, tuple[str, str, str]] = {
    "BASE_RATE": ("722Y001", "M", "0101000"),    # 월별 기준금리  (날짜 형식: YYYYMM)
    "USD_KRW":   ("731Y001", "D", "0000001"),    # 일별 원/달러 환율 (날짜 형식: YYYYMMDD)
    "KTB_10Y":   ("817Y002", "D", "010200000"),  # 일별 국고채 10년물 (날짜 형식: YYYYMMDD)
}

# 한 번에 요청할 최대 건수 (ECOS API 권장값)
_PAGE_SIZE = 1000


class MacroCollector:
    """ECOS REST API를 통해 거시경제 지표를 수집하고 DB에 저장한다."""

    def __init__(self, repo: StockRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def run(
        self,
        indicator_codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> None:
        """
        Args:
            indicator_codes: 수집할 지표 코드 리스트. None이면 전체(_SERIES 키).
            start_date:      수집 시작일 (YYYYMMDD). None이면 1년 전.
            end_date:        수집 종료일 (YYYYMMDD). None이면 오늘.
        """
        from src.config import settings  # 순환 임포트 방지

        if not settings.ecos_api_key:
            logger.warning("ECOS_API_KEY 미설정 — 거시경제 지표 수집 스킵")
            return

        today = date.today()
        end = end_date or today.strftime("%Y%m%d")
        start = start_date or (today - timedelta(days=365)).strftime("%Y%m%d")

        targets = indicator_codes or list(_SERIES.keys())

        for code in targets:
            if code not in _SERIES:
                logger.warning(f"알 수 없는 지표 코드: {code}")
                continue
            self._collect_one(settings.ecos_api_key, code, start, end)

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _collect_one(
        self, api_key: str, indicator_code: str, start: str, end: str
    ) -> None:
        stat_code, period, item_code = _SERIES[indicator_code]

        # 주기별 날짜 형식 변환
        # - D (일별): YYYYMMDD 그대로
        # - M (월별): YYYYMM (앞 6자리만 사용)
        api_start = _to_period_date(start, period)
        api_end = _to_period_date(end, period)

        logger.info(f"거시경제 지표 수집 | {indicator_code} | {api_start} ~ {api_end}")

        url = (
            f"{_ECOS_BASE}/{api_key}/json/kr"
            f"/1/{_PAGE_SIZE}"
            f"/{stat_code}/{period}/{api_start}/{api_end}/{item_code}"
        )

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"ECOS API 요청 실패 | {indicator_code}: {e}")
            return
        except ValueError as e:
            logger.error(f"ECOS API 응답 파싱 실패 | {indicator_code}: {e}")
            return

        # ECOS API 오류 응답 확인
        if "RESULT" in data:
            err = data["RESULT"]
            logger.error(
                f"ECOS API 오류 | {indicator_code} | "
                f"code={err.get('CODE')} msg={err.get('MESSAGE')}"
            )
            return

        rows = data.get("StatisticSearch", {}).get("row", [])
        if not rows:
            logger.warning(f"데이터 없음 | {indicator_code}")
            return

        saved = 0
        for row in rows:
            raw_date = str(row.get("TIME", "")).strip()
            raw_value = str(row.get("DATA_VALUE", "")).strip()

            if not raw_date or not raw_value or raw_value in ("", "-", "nan"):
                continue

            normalized_date = _normalize_date(raw_date)
            if normalized_date is None:
                continue

            try:
                value = float(raw_value.replace(",", ""))
            except ValueError:
                continue

            try:
                self.repo.upsert_macro_indicator(
                    {
                        "date": normalized_date,
                        "indicator_code": indicator_code,
                        "value": value,
                    }
                )
                saved += 1
            except Exception as e:
                logger.warning(f"upsert 실패 | {indicator_code} {normalized_date}: {e}")

        logger.info(f"거시경제 지표 저장 완료 | {indicator_code} | {saved}건")


# ------------------------------------------------------------------
# 유틸
# ------------------------------------------------------------------

def _to_period_date(yyyymmdd: str, period: str) -> str:
    """
    YYYYMMDD 형식의 날짜를 ECOS API 주기에 맞는 형식으로 변환.

    - period='D': YYYYMMDD 그대로 반환
    - period='M': YYYYMM (앞 6자리)
    - period='Q': YYYYQ  (분기 — 현재 미사용)
    - period='A': YYYY   (연간 — 현재 미사용)
    """
    yyyymmdd = yyyymmdd.strip()
    if period == "D":
        return yyyymmdd
    if period == "M":
        return yyyymmdd[:6]
    if period == "Q":
        return yyyymmdd[:4]
    if period == "A":
        return yyyymmdd[:4]
    return yyyymmdd


def _normalize_date(raw: str) -> str | None:
    """
    ECOS API 날짜 문자열을 PostgreSQL DATE 형식(YYYY-MM-DD)으로 변환.

    - 'YYYYMM'   → 'YYYY-MM-01'  (월별 데이터)
    - 'YYYYMMDD' → 'YYYY-MM-DD'  (일별 데이터)
    """
    raw = raw.strip()
    if len(raw) == 6:   # 월별: YYYYMM
        return f"{raw[:4]}-{raw[4:6]}-01"
    if len(raw) == 8:   # 일별: YYYYMMDD
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return None