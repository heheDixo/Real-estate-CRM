"""
Hunter.io email verifier (free tier — 25 verifications/month).

If the key is missing or quota is exceeded, returns a safe default
({"valid": True, "score": 50, "status": "unknown"}) so the pipeline does
not stall.
"""

from typing import Dict
import requests

import config

_ENDPOINT = "https://api.hunter.io/v2/email-verifier"
_TIMEOUT  = 10

_DEFAULT_UNKNOWN = {"valid": True, "score": 50, "status": "unknown"}


def verify(email: str) -> Dict:
    """
    Verify an email address with Hunter.io.

    Args:
        email: address to verify

    Returns:
        dict with keys: valid (bool), score (int 0–100), status (str)
    """
    if not email or "@" not in email:
        return {"valid": False, "score": 0, "status": "invalid_format"}

    if not config.HUNTER_AVAILABLE:
        return dict(_DEFAULT_UNKNOWN)

    try:
        resp = requests.get(
            _ENDPOINT,
            params  = {"email": email, "api_key": config.HUNTER_API_KEY},
            timeout = _TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"[hunter] request failed for {email}: {exc}")
        return dict(_DEFAULT_UNKNOWN)

    if resp.status_code == 429:
        return dict(_DEFAULT_UNKNOWN)
    if resp.status_code != 200:
        print(f"[hunter] returned {resp.status_code} for {email}")
        return dict(_DEFAULT_UNKNOWN)

    try:
        data = resp.json().get("data", {})
    except ValueError:
        return dict(_DEFAULT_UNKNOWN)

    return {
        "valid":  (data.get("result") in ("deliverable", "risky")),
        "score":  int(data.get("score", 50) or 50),
        "status": data.get("result", "unknown"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(verify("rachel.kim@healthaxis.io"), indent=2))
