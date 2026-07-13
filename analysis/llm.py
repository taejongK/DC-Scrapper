"""Thin LLM client for the analysis layer, with two interchangeable backends.

Backends (auto-detected by which key is set; OpenRouter wins if both are):
  * OpenRouter  — OPENROUTER_API_KEY. OpenAI-compatible HTTP (uses ``requests``,
    already a core dependency), so no extra SDK is needed.
  * Anthropic   — ANTHROPIC_API_KEY. Uses the ``anthropic`` SDK if installed.

The rest of the analysis code depends only on ``complete`` / ``complete_json`` /
``available`` / ``status`` — never on a specific provider — so swapping backends
is just an env change.

Config via environment:
  OPENROUTER_API_KEY  use OpenRouter (recommended here)
  ANTHROPIC_API_KEY   use the Anthropic API directly
  DC_LLM_MODEL        model id override (defaults per backend, see below)
Keys are read from the environment only and never written to disk or logged.
"""

from __future__ import annotations

import json
import os
import re

import requests

# Default model per backend. OpenRouter uses namespaced slugs.
DEFAULT_MODEL = "claude-sonnet-5"                       # Anthropic-native id
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-5"  # OpenRouter slug
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Any failure talking to the LLM (missing key, SDK, or API error)."""


def _backend() -> str | None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def model_name() -> str:
    override = os.environ.get("DC_LLM_MODEL")
    if override:
        return override
    return DEFAULT_OPENROUTER_MODEL if _backend() == "openrouter" else DEFAULT_MODEL


def _has_anthropic_sdk() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def available() -> bool:
    """True when a backend is configured and usable (real calls possible)."""
    b = _backend()
    if b == "openrouter":
        return True  # requests is always available
    if b == "anthropic":
        return _has_anthropic_sdk()
    return False


def status() -> dict:
    """Diagnostic for the UI: is the LLM usable, which backend, and why not."""
    b = _backend()
    reason = None
    if b is None:
        reason = "OPENROUTER_API_KEY 또는 ANTHROPIC_API_KEY 환경변수 미설정"
    elif b == "anthropic" and not _has_anthropic_sdk():
        reason = "anthropic SDK 미설치 (pip install anthropic) — 또는 OpenRouter 사용"
    return {"available": reason is None, "backend": b, "model": model_name(),
            "has_key": b is not None, "reason": reason}


# A module-level hook so tests can inject a fake completion without any network.
_COMPLETE_OVERRIDE = None


def set_override(fn) -> None:
    """Install (or clear with None) a stand-in for ``complete`` — used by tests."""
    global _COMPLETE_OVERRIDE
    _COMPLETE_OVERRIDE = fn


def _complete_openrouter(system, user, max_tokens, temperature, model) -> str:
    headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
        "X-Title": "dc-scraper",  # optional attribution shown on OpenRouter
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise LLMError(f"OpenRouter 오류 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("error"):
        raise LLMError(f"OpenRouter 오류: {data['error']}")
    return data["choices"][0]["message"]["content"]


def _complete_anthropic(system, user, max_tokens, temperature, model) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        system=system, messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def complete(system: str, user: str, *, max_tokens: int = 2000,
             temperature: float = 0.2, model: str | None = None) -> str:
    """Single-turn completion. Returns the assistant's text.

    Raises ``LLMError`` if no backend is configured or the call fails.
    """
    if _COMPLETE_OVERRIDE is not None:
        return _COMPLETE_OVERRIDE(system=system, user=user, max_tokens=max_tokens,
                                  temperature=temperature, model=model or model_name())
    b = _backend()
    mdl = model or model_name()
    try:
        if b == "openrouter":
            return _complete_openrouter(system, user, max_tokens, temperature, mdl)
        if b == "anthropic":
            if not _has_anthropic_sdk():
                raise LLMError("anthropic SDK 미설치 (pip install anthropic).")
            return _complete_anthropic(system, user, max_tokens, temperature, mdl)
        raise LLMError("API 키가 설정되지 않았습니다 (OPENROUTER_API_KEY 또는 ANTHROPIC_API_KEY).")
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any backend error uniformly
        raise LLMError(f"LLM 호출 실패: {exc}") from exc


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Pull a JSON object/array out of a model response, fenced or bare."""
    m = _JSON_FENCE.search(text)
    if m:
        return m.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        return text.strip()
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start:end + 1].strip() if end > start else text.strip()


_JSON_RULES = (
    "\n\n반드시 유효한 JSON 하나만 출력하라. 설명 문장이나 코드펜스는 금지한다. "
    "문자열 값 안에서 인용을 넣을 때는 큰따옴표(\") 대신 작은따옴표(')나 「」를 사용하고, "
    "값 안에 줄바꿈을 넣지 마라."
)


def complete_json(system: str, user: str, *, max_tokens: int = 2000,
                  temperature: float = 0.1, model: str | None = None) -> dict | list:
    """Completion whose response is parsed as JSON.

    Hardens against the usual LLM-JSON failure modes: instructs the model to
    avoid unescaped inner quotes, strips code fences, and — if the first parse
    still fails — makes one cheap "repair this into valid JSON" pass before
    giving up with ``LLMError``.
    """
    raw = complete(system + _JSON_RULES, user, max_tokens=max_tokens,
                   temperature=temperature, model=model)
    try:
        return json.loads(_extract_json(raw))
    except (ValueError, json.JSONDecodeError):
        pass  # fall through to a single repair attempt

    repaired = complete(
        "너는 깨진 JSON을 고치는 도구다. 입력을 유효한 JSON으로 고쳐 JSON만 출력하라. "
        "내용은 바꾸지 말고 문법만 고쳐라(따옴표 이스케이프, 누락된 괄호/쉼표 등).",
        f"다음을 유효한 JSON으로 고쳐라:\n{raw}",
        max_tokens=max_tokens, temperature=0.0, model=model)
    try:
        return json.loads(_extract_json(repaired))
    except (ValueError, json.JSONDecodeError) as exc:
        raise LLMError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}\n원문: {raw[:500]}") from exc
