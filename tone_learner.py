"""
Tone learner. Stores approved emails locally and extracts a writing-style
profile that is injected into the Mistral writer's prompt so successive
drafts converge toward the broker's actual voice.

No external API. Storage is plain JSON in ./data/.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import statistics
from typing import Dict, List

import config


DATA_DIR              = "data"
TONE_PROFILE_PATH     = os.path.join(DATA_DIR, "tone_profile.json")
APPROVED_EMAILS_PATH  = os.path.join(DATA_DIR, "approved_emails.json")

_DEFAULT_PROFILE: Dict = {
    "avg_sentence_length": 12,
    "opening_style":       "market observation",
    "cta_style":           "single question",
    "avg_word_count":      90,
    "sign_off":            f"Best, {config.AGENT_NAME.split()[0]}",
    "forbidden_phrases":   [
        "leverage", "circle back", "touching base", "synergy",
        "I hope this finds you", "I hope this finds you well",
        "I wanted to reach out", "innovative", "disruptive",
    ],
    "example_emails":      [],
}


# ── File helpers (defensive) ────────────────────────────────────────────────


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str, default):
    _ensure_dir()
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[tone_learner] cannot read {path}: {exc} — using default.")
        return default


def _write_json(path: str, data):
    _ensure_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Public API ──────────────────────────────────────────────────────────────


def load_tone_profile() -> Dict:
    """Load the tone profile, seeding the file with defaults on first read."""
    return _read_json(TONE_PROFILE_PATH, dict(_DEFAULT_PROFILE))


def save_approved_email(subject: str, body: str,
                          prospect_name: str = "") -> None:
    """Append one approved email to the local archive."""
    emails = _read_json(APPROVED_EMAILS_PATH, [])
    emails.append({
        "subject":       subject,
        "body":          body,
        "prospect_name": prospect_name,
        "approved_at":   datetime.datetime.now().isoformat(),
    })
    _write_json(APPROVED_EMAILS_PATH, emails)


def analyse_tone_from_emails(emails: List[str]) -> Dict:
    """
    Derive a tone profile from a list of email bodies.

    Uses simple deterministic heuristics — no LLM call needed for the
    quantitative parts (sentence length, word count, sign-off detection).
    """
    if not emails:
        return dict(_DEFAULT_PROFILE)

    sentence_lengths: List[int] = []
    word_counts:      List[int] = []
    openings:         List[str] = []
    sign_offs:        List[str] = []

    for body in emails:
        if not body:
            continue
        text = body.strip()

        # word count of full body
        word_counts.append(len(text.split()))

        # sentences
        sents = [s.strip() for s in re.split(r"[.!?]\s+", text) if s.strip()]
        if sents:
            for s in sents:
                sentence_lengths.append(len(s.split()))
            openings.append(sents[0])

        # sign-off: last non-empty line group
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 2:
            sign_offs.append(lines[-2] + " " + lines[-1])
        elif lines:
            sign_offs.append(lines[-1])

    avg_sent = round(statistics.mean(sentence_lengths)) if sentence_lengths else 12
    avg_word = round(statistics.mean(word_counts)) if word_counts else 90

    opening_style = _classify_opening(openings)
    cta_style     = _classify_cta(emails)

    profile = dict(_DEFAULT_PROFILE)
    profile["avg_sentence_length"] = avg_sent
    profile["avg_word_count"]      = avg_word
    profile["opening_style"]       = opening_style
    profile["cta_style"]           = cta_style
    if sign_offs:
        profile["sign_off"] = sign_offs[-1][:120]

    profile["example_emails"] = emails[-3:]
    return profile


def build_tone_injection(profile: Dict) -> str:
    """
    Compose a plain-English style-rule block that can be prepended to
    the Mistral system prompt.
    """
    forbidden = profile.get("forbidden_phrases") or []
    forbidden_line = (
        f"Never use: {', '.join(forbidden)}." if forbidden else ""
    )

    return (
        f"Style rules learned from past approved emails:\n"
        f"- Average sentence length: under {profile.get('avg_sentence_length', 12) + 3} words.\n"
        f"- Opening: {profile.get('opening_style', 'market observation')}.\n"
        f"- Call to action: {profile.get('cta_style', 'single question')}.\n"
        f"- Total length: around {profile.get('avg_word_count', 90)} words.\n"
        f"- Sign off: {profile.get('sign_off', f'Best, {config.AGENT_NAME.split()[0]}')}.\n"
        f"- {forbidden_line}"
    ).strip()


def update_tone_profile() -> Dict:
    """Re-read approved emails, regenerate the profile, persist it."""
    archive = _read_json(APPROVED_EMAILS_PATH, [])
    bodies  = [e.get("body", "") for e in archive if e.get("body")]
    profile = analyse_tone_from_emails(bodies)
    _write_json(TONE_PROFILE_PATH, profile)
    return profile


# ── Heuristics ──────────────────────────────────────────────────────────────


def _classify_opening(openings: List[str]) -> str:
    if not openings:
        return "market observation"
    lowered = [o.lower() for o in openings]
    if sum(1 for o in lowered if o.startswith(("noticed", "saw", "spotted"))) >= len(openings) / 2:
        return "specific observation about their company"
    if sum(1 for o in lowered if any(k in o[:30] for k in ["market", "sector", "industry"])) >= len(openings) / 2:
        return "market observation"
    if sum(1 for o in lowered if o.startswith(("congrat", "great", "impressive"))) >= 1:
        return "compliment-led (use sparingly)"
    return "specific observation about their company"


def _classify_cta(emails: List[str]) -> str:
    if not emails:
        return "single question"
    qcount = sum(1 for e in emails if "?" in e)
    if qcount >= len(emails) * 0.6:
        return "single question"
    if any("worth a" in e.lower() or "happy to" in e.lower() for e in emails):
        return "soft optional offer"
    return "low-pressure observation"


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    p = load_tone_profile()
    print(json.dumps(p, indent=2))
    print()
    print("── Tone injection ──")
    print(build_tone_injection(p))
