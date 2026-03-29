"""
Unified LLM client with Gemini primary + OpenAI fallback.
Falls back to OpenAI when Gemini hits rate limits or errors.
"""

import os
import json
import re
import time
from dotenv import load_dotenv

load_dotenv()

_gemini_client = None
_openai_client = None
_gemini_blocked_until = 0.0


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        from openai import OpenAI
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def strip_code_fences(text):
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text


def _prepare_text(text, expect_json=False, provider="llm"):
    if not text or not str(text).strip():
        raise ValueError(f"Empty response from {provider}")
    cleaned = strip_code_fences(text) if expect_json else text.strip()
    if expect_json:
        # Validate JSON shape here so malformed Gemini output can trigger OpenAI fallback.
        json.loads(cleaned)
    return cleaned


def call_llm(prompt, expect_json=False):
    """
    Call LLM with automatic fallback: Gemini → OpenAI.
    Returns the raw text response.
    Raises if both fail.
    """
    errors = []
    global _gemini_blocked_until

    # Try Gemini first
    gemini = get_gemini_client()
    openai = get_openai_client()
    now = time.time()
    gemini_error = None
    gemini_quota_error = False
    if gemini and now < _gemini_blocked_until:
        remaining = int(max(1, _gemini_blocked_until - now))
        msg = f"Gemini temporarily blocked due to quota. Retry in ~{remaining}s."
        print(f"⚠️  {msg}")
        errors.append(("gemini", RuntimeError(msg)))
    elif gemini:
        try:
            response = gemini.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            text = response.text
            return _prepare_text(text, expect_json=expect_json, provider="Gemini")
        except Exception as e:
            error_str = str(e).lower()
            gemini_error = e
            gemini_quota_error = any(k in error_str for k in ["quota", "rate", "limit", "429", "resource_exhausted"])
            if gemini_quota_error:
                # Respect server hint to avoid repeated slow failures.
                delay = 60
                m = re.search(r"retry in\s*([\d.]+)s", error_str)
                if m:
                    try:
                        delay = max(5, int(float(m.group(1))))
                    except ValueError:
                        delay = 60
                _gemini_blocked_until = time.time() + delay
            if any(k in error_str for k in ["quota", "rate", "limit", "429", "timeout", "deadline", "503", "overload"]):
                print(f"⚠️  Gemini rate limited: {e} — trying OpenAI fallback...")
            else:
                print(f"⚠️  Gemini error: {e} — trying OpenAI fallback...")
            errors.append(("gemini", e))

    # Try OpenAI fallback
    if openai:
        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            text = response.choices[0].message.content
            return _prepare_text(text, expect_json=expect_json, provider="OpenAI")
        except Exception as e:
            print(f"⚠️  OpenAI error: {e}")
            errors.append(("openai", e))
    elif gemini and gemini_quota_error:
        # Make this explicit so caller can take fast deterministic fallback path.
        raise RuntimeError("Gemini quota exceeded and OPENAI_API_KEY is not configured.")

    # Both failed
    if not gemini and not openai:
        raise ValueError("No LLM API keys configured. Set GEMINI_API_KEY or OPENAI_API_KEY in .env")

    last_provider, last_error = errors[-1] if errors else ("unknown", gemini_error or ValueError("No LLM available"))
    raise last_error
