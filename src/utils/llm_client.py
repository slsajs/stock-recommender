"""
utils/llm_client.py
Ollama REST API 단일 호출 래퍼.

Qwen3 등 로컬 LLM을 Ollama로 서빙할 때 사용.
타임아웃 또는 오류 시 None 반환 → 호출자가 fallback 처리.

환경변수:
    LLM_BASE_URL  : Ollama 서버 URL (기본: http://localhost:11434)
    LLM_MODEL     : 사용할 모델명 (기본: qwen3)
    LLM_TIMEOUT   : 요청 타임아웃 초 (기본: 15)
    LLM_ENABLED   : false 설정 시 모든 호출을 즉시 None 반환 (기본: true)
"""
from __future__ import annotations

import requests
from loguru import logger

from src.config import settings


def call_llm(prompt: str, timeout: int | None = None) -> str | None:
    """
    Ollama /api/generate 엔드포인트에 단일 요청을 보내고 텍스트 응답을 반환한다.

    Args:
        prompt:  LLM에 전달할 프롬프트 문자열
        timeout: 요청 타임아웃(초). None이면 settings.llm_timeout 사용.

    Returns:
        LLM 응답 문자열 (앞뒤 공백 제거). 오류 또는 비활성화 시 None.
    """
    if not settings.llm_enabled:
        logger.debug("LLM 비활성화 (LLM_ENABLED=false) — None 반환")
        return None

    effective_timeout = timeout if timeout is not None else settings.llm_timeout

    try:
        resp = requests.post(
            f"{settings.llm_base_url}/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=effective_timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        if not raw:
            logger.warning("LLM 응답 비어있음 — None 반환")
            return None
        return raw

    except requests.exceptions.Timeout:
        logger.warning(
            f"LLM 호출 타임아웃 ({effective_timeout}초) — fallback 사용"
        )
        return None
    except requests.exceptions.ConnectionError:
        logger.warning(
            f"LLM 서버 연결 실패 ({settings.llm_base_url}) — Ollama 실행 여부 확인"
        )
        return None
    except Exception as e:
        logger.warning(f"LLM 호출 실패 (fallback 사용): {e}")
        return None
