"""
Tone learner. Stores approved emails and extracts a writing-style profile
that is injected into the Mistral writer's prompt so successive drafts
converge toward the broker's actual voice.

Storage is Supabase (with JSON fallback) via database.py.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Dict, List

import config
import database


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


# ── Public API ──────────────────────────────────────────────────────────────


def load_tone_profile() -> Dict:
    """Load the tone profile from the database (with JSON fallback)."""
    profile = database.get_tone_profile()
    if not profile:
        return dict(_DEFAULT_PROFILE)
    # Backfill any missing keys with defaults so older saved profiles still work.
    merged = dict(_DEFAULT_PROFILE)
    merged.update(profile)
    return merged


def save_approved_email(subject: str, body: str,
                          prospect_name: str = "",
                          tone_variant: str = "") -> None:
    """Append one approved email to the archive (Supabase + JSON fallback)."""
    database.save_approved_email(subject, body, prospect_name, tone_variant)


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

        word_counts.append(len(text.split()))

        sents = [s.strip() for s in re.split(r"[.!?]\s+", text) if s.strip()]
        if sents:
            for s in sents:
                sentence_lengths.append(len(s.split()))
            openings.append(sents[0])

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
    archive = database.get_approved_emails(limit=200)
    bodies  = [e.get("body", "") for e in archive if e.get("body")]
    profile = analyse_tone_from_emails(bodies)
    database.save_tone_profile(profile)
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
