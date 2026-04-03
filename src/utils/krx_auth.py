"""
krx_auth.py
KRX data.krx.co.kr 로그인 및 pykrx 세션 주입.

2026년 1월부터 KRX가 data.krx.co.kr 전체를 로그인 필수로 변경했다.
pykrx 1.2.4는 자체 로그인을 지원하지 않으므로, 로그인된 requests.Session을
pykrx 내부 webio에 주입하는 방식으로 우회한다.

사용법:
    from src.utils.krx_auth import login_krx_if_needed
    login_krx_if_needed()   # 수집 시작 전 1회 호출
"""
from __future__ import annotations

import requests
from loguru import logger

from pykrx.website.comm import webio

_LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
_LOGIN_JSP  = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
_LOGIN_URL  = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_session = requests.Session()
_logged_in = False


def _inject_session() -> None:
    """pykrx webio의 Post/Get read 메서드를 로그인된 세션으로 교체한다."""

    def _post_read(self, **params):
        return _session.post(self.url, headers=self.headers, data=params)

    def _get_read(self, **params):
        return _session.get(self.url, headers=self.headers, params=params)

    webio.Post.read = _post_read
    webio.Get.read = _get_read


def login_krx(krx_id: str, krx_pw: str) -> bool:
    """
    KRX 계정으로 로그인하고 세션을 pykrx에 주입한다.

    Returns:
        True if login succeeded, False otherwise.
    """
    global _logged_in

    try:
        _session.get(_LOGIN_PAGE, headers={"User-Agent": _UA}, timeout=15)
        _session.get(
            _LOGIN_JSP,
            headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE},
            timeout=15,
        )

        payload = {
            "mbrId": krx_id,
            "pw": krx_pw,
            "mbrNm": "",
            "telNo": "",
            "di": "",
            "certType": "",
        }
        headers = {"User-Agent": _UA, "Referer": _LOGIN_PAGE}

        resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
        error_code = resp.json().get("_error_code", "")

        # CD011: 중복 로그인 — 단일 세션 강제
        if error_code == "CD011":
            payload["skipDup"] = "Y"
            resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
            error_code = resp.json().get("_error_code", "")

        if error_code == "CD001":
            _inject_session()
            _logged_in = True
            logger.info("KRX 로그인 성공 | pykrx 세션 주입 완료")
            return True
        else:
            logger.error(f"KRX 로그인 실패 | error_code={error_code}")
            return False

    except Exception as e:
        logger.error(f"KRX 로그인 오류 | {e}")
        return False


def login_krx_if_needed() -> bool:
    """
    .env의 KRX_ID / KRX_PW로 로그인 시도.
    이미 로그인된 경우 재시도하지 않는다.
    KRX_ID가 없으면 경고만 출력하고 False 반환.
    """
    global _logged_in

    if _logged_in:
        return True

    from src.config import settings

    krx_id = getattr(settings, "krx_id", "")
    krx_pw = getattr(settings, "krx_pw", "")

    if not krx_id:
        logger.warning(
            "KRX_ID가 설정되지 않았습니다. "
            ".env에 KRX_ID / KRX_PW를 추가하면 정확한 코스피200/코스닥150 목록을 사용할 수 있습니다. "
            "(data.krx.co.kr 무료 회원가입 필요)"
        )
        return False

    return login_krx(krx_id, krx_pw)