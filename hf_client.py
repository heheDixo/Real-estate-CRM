"""
hf_client.py
Resilient wrapper around HuggingFace Inference API calls.

Handles:
- 3 retries with exponential backoff (2s, 4s, 8s)
- 30 second timeout per call
- Score caching in Supabase (same text + labels = skip API call)
- Safe fallback return values when all retries fail
- Model warm-up ping before the 5am pipeline
"""

import os
import time
import requests
from typing import Optional

from database import get_cached_score, save_cached_score, make_cache_key, _log_error
import config

HF_TOKEN     = os.getenv("HF_TOKEN", "")
MAX_RETRIES  = 3
TIMEOUT      = 30
BACKOFF_BASE = 2  # seconds — waits 2s, 4s, 8s between retries

SCORER_MODEL = "facebook/bart-large-mnli"
WRITER_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"


# ─────────────────────────────────────────
# ZERO-SHOT CLASSIFICATION (scorer)
# ─────────────────────────────────────────

def classify_zero_shot(
    text: str,
    candidate_labels: list[str],
    model: str = SCORER_MODEL,
    use_cache: bool = True,
    fallback_scores: Optional[list[float]] = None,
) -> dict:
    """
    Calls bart-large-mnli zero-shot classification.
    Returns {"labels": [...], "scores": [...]} — same format as HF API.

    Falls back to equal distribution if all retries fail.
    Caches results in Supabase to avoid redundant API calls.
    """
    if use_cache:
        cache_key = make_cache_key(text, candidate_labels)
        cached = get_cached_score(cache_key)
        if cached:
            return cached

    last_error = None
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": text[:4000],
        "parameters": {"candidate_labels": candidate_labels, "multi_label": True}
    }
    url = f"{config.HF_API_BASE}/{model}"

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, list):
                output = {
                    "labels": [item.get("label", "") for item in data if isinstance(item, dict)],
                    "scores": [float(item.get("score", 0.0)) for item in data if isinstance(item, dict)]
                }
            elif isinstance(data, dict):
                output = {
                    "labels": data.get("labels", []),
                    "scores": data.get("scores", []),
                }
            else:
                raise ValueError("Unexpected response shape")

            if use_cache:
                save_cached_score(cache_key, output)
            return output

        except Exception as e:
            last_error = e
            _log_error(
                "hf_client.classify_zero_shot",
                f"Attempt {attempt + 1}/{MAX_RETRIES}: {e}"
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** attempt)

    _log_error("hf_client.classify_zero_shot", f"All retries failed: {last_error}")
    if fallback_scores and len(fallback_scores) == len(candidate_labels):
        return {"labels": candidate_labels, "scores": fallback_scores}
    n = len(candidate_labels)
    return {"labels": candidate_labels, "scores": [1.0 / n] * n}


# ─────────────────────────────────────────
# TEXT GENERATION (writer + briefer)
# ─────────────────────────────────────────

def generate_text(
    prompt: str,
    model: str = WRITER_MODEL,
    max_new_tokens: int = 400,
    temperature: float = 0.7,
    fallback_text: str = "",
) -> str:
    """
    Calls Mistral-7B text generation with retry + fallback.
    Returns generated text string, or fallback_text if all retries fail.
    """
    last_error = None
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "return_full_text": False
        }
    }
    url = f"{config.HF_API_BASE}/{model}"

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, list) and data:
                text = data[0].get("generated_text", "").strip()
                if text:
                    return text

        except Exception as e:
            last_error = e
            _log_error(
                "hf_client.generate_text",
                f"Attempt {attempt + 1}/{MAX_RETRIES}: {e}"
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** attempt)

    _log_error("hf_client.generate_text", f"All retries failed: {last_error}")
    return fallback_text


# ─────────────────────────────────────────
# MODEL WARM-UP
# ─────────────────────────────────────────

def warm_up_models() -> dict:
    """
    Pings both models with minimal input to wake them from cold start.
    Called at 4:50 AM before the main pipeline runs at 5:00 AM.
    Returns {"scorer": True/False, "writer": True/False}
    """
    results = {}

    print("[warm-up] Pinging scorer model...")
    try:
        classify_zero_shot(
            text="test company signal",
            candidate_labels=["positive", "negative"],
            use_cache=False,
        )
        results["scorer"] = True
        print("[warm-up] Scorer OK")
    except Exception as e:
        results["scorer"] = False
        _log_error("warm_up_models.scorer", str(e))
        print(f"[warm-up] Scorer FAILED: {e}")

    print("[warm-up] Pinging writer model...")
    try:
        out = generate_text("Hello", max_new_tokens=5)
        results["writer"] = bool(out)
        print(f"[warm-up] Writer {'OK' if results['writer'] else 'FAILED (empty)'}")
    except Exception as e:
        results["writer"] = False
        _log_error("warm_up_models.writer", str(e))
        print(f"[warm-up] Writer FAILED: {e}")

    return results
