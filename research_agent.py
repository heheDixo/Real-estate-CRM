"""
Daily research agent.

Given a prospect and raw scraped data (news articles, job postings, website
text), produces a structured ResearchReport using bart-large-mnli zero-shot
classification on the same five CRE-relevant labels defined in
config.RESEARCH_SIGNAL_LABELS.

The HF call is consolidated: all text from today's articles is concatenated
into a single document and scored against the five candidate hypotheses in
one API request. Per-article signals are extracted from the article that
contributed the most to the dominant label.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

import requests

import config


# Per-label keyword cues — used to pick the most relevant sentence from a
# winning article's body when building the signal card. Without this every
# signal card shows the same article.description blob.
_LABEL_KEYWORDS: Dict[str, List[str]] = {
    "hiring":     ["hiring", "hire", "career", "open role", "open position",
                   "we're hiring", "join our team", "now hiring", "recruit",
                   "talent", "head of", "added to the team"],
    "funding":    ["raised", "series ", "funding round", "investment",
                   "valuation", "led the round", "investors", "venture",
                   "capital", "closed a", "secured"],
    "expansion":  ["expand", "expanding", "expansion", "new office",
                   "new location", "opened", "opens", "launch", "launched",
                   "scale", "scaling", "growing", "growth", "new market"],
    "lease":      ["lease", "signed a lease", "office space", "new home",
                   "new headquarters", "hq", "headquartered", "moved to",
                   "moving to", "relocated", "square feet", "sq ft", "sqft"],
    "space_need": ["office space", "workspace", "footprint", "square feet",
                   "sq ft", "sqft", "headcount", "team grew", "hybrid",
                   "return to office", "rto"],
}


def _keyword_match(haystack_lower: str, keywords: List[str]) -> bool:
    """True if any keyword matches *haystack_lower* on a word boundary.

    Substring matching produces false positives like "lease" inside "please"
    or "hire" inside "higher" — `\\b` boundaries fix that.
    """
    for kw in keywords:
        # Allow multi-word keywords; \b around the whole escaped phrase.
        if re.search(r"\b" + re.escape(kw) + r"\b", haystack_lower):
            return True
    return False


def _snippet_for_label(label: str, text: str, max_chars: int = 280) -> str:
    """Find a sentence from *text* that mentions a keyword for *label*."""
    if not text:
        return ""
    sig_type = config.RESEARCH_SIGNAL_LABEL_TYPES.get(label, "")
    keywords = _LABEL_KEYWORDS.get(sig_type, [])
    if not keywords:
        return text[:max_chars].strip()
    # Sentence split. Keep punctuation, allow . ! ? as boundaries.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        if _keyword_match(sent.lower(), keywords):
            return sent.strip()[:max_chars]
    # No keyword match — fall back to the article's opening sentence so the
    # card has *something* readable rather than truncated mid-word chrome.
    return (sentences[0] if sentences else text)[:max_chars].strip()


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class Signal:
    type:        str       # one of: hiring, funding, expansion, lease, space_need
    title:       str       # short headline
    description: str       # 1–2 sentence summary
    source:      str       # "Google News", "NewsAPI", "LinkedIn Jobs", etc.
    strength:    int       # 1–5 visual dots
    score:       float     # 0–100 model confidence
    url:         str = ""  # link back to source if available


@dataclass
class ResearchReport:
    prospect_id:    str
    company:        str
    contact_name:   str
    contact_email:  str
    signals:        List[Signal] = field(default_factory=list)
    composite_score: int   = 0
    tier:           str    = "nurture"
    top_hook:       str    = ""
    skip_today:     bool   = False
    skip_reason:    str    = ""
    raw_articles:   List[Dict] = field(default_factory=list)
    raw_jobs:       List[Dict] = field(default_factory=list)
    generated_at:   str    = ""
    contact_title:  str    = ""
    linkedin_url:   str    = ""
    sector:         str    = ""
    source:         str    = "watchlist"   # "watchlist" | "discovered"
    approved:       bool   = True          # False for discovered leads
    # Firmographic numbers — populated from Apollo enrich + jobs scraper
    headcount:      int    = 0             # Apollo's estimated_num_employees
    industry:       str    = ""            # Apollo's industry slug
    open_roles:     int    = 0             # total live jobs across the ATS
    office_roles:   int    = 0             # subset matching workplace/RE titles
    ats:            str    = ""            # "Greenhouse" | "Ashby" | "Lever" | ""
    research_doc_url: str  = ""            # Google Doc dossier URL
    # draft = {"subject", "body", "linkedin", "variant"}; None if skipped
    draft:          Optional[Dict] = None
    stale:          bool   = False         # set by load_morning_run

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [asdict(s) for s in self.signals]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchReport":
        sigs = [Signal(**s) for s in (d.get("signals") or [])]
        kwargs = {k: v for k, v in d.items() if k != "signals"}
        kwargs["signals"] = sigs
        # tolerate older saved files missing the new fields
        kwargs.setdefault("sector",      "")
        kwargs.setdefault("source",      "watchlist")
        kwargs.setdefault("approved",    True)
        kwargs.setdefault("draft",       None)
        kwargs.setdefault("stale",       False)
        kwargs.setdefault("headcount",    0)
        kwargs.setdefault("industry",     "")
        kwargs.setdefault("open_roles",   0)
        kwargs.setdefault("office_roles", 0)
        kwargs.setdefault("ats",          "")
        kwargs.setdefault("research_doc_url", "")
        return cls(**kwargs)


# ── HF call ─────────────────────────────────────────────────────────────────


_MODEL_URL = f"{config.HF_API_BASE}/{config.SCORING_MODEL}"


def _log_hf_error(scope: str, detail: str) -> None:
    """Surface HF failures into data/error_log.json so the UI can see them."""
    try:
        path = os.path.join("data", "error_log.json")
        os.makedirs("data", exist_ok=True)
        log = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    log = json.load(f) or []
            except (json.JSONDecodeError, OSError):
                log = []
        log.append({
            "at":    datetime.datetime.now().isoformat(),
            "scope": scope,
            "error": detail,
            "type":  "HFInferenceError",
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


def _classify(text: str, labels: List[str]) -> Dict[str, float]:
    """Call bart-large-mnli with a single document and N candidate labels."""
    if not text.strip() or not config.HF_AVAILABLE:
        return {}

    from hf_client import classify_zero_shot
    result = classify_zero_shot(
        text=text,
        candidate_labels=labels,
        fallback_scores=[1.0 / len(labels)] * len(labels),
    )
    return dict(zip(result.get("labels", []), result.get("scores", [])))


# ── Signal construction ─────────────────────────────────────────────────────


def _strength(score_0_100: float) -> int:
    if score_0_100 >= 85: return 5
    if score_0_100 >= 70: return 4
    if score_0_100 >= 55: return 3
    if score_0_100 >= 40: return 2
    return 1


def _best_article_for(label: str,
                       articles: List[Dict]) -> Optional[Dict]:
    """Pick the article whose text most closely matches the label."""
    if not articles:
        return None

    best, best_score = None, -1.0
    for art in articles:
        blob   = f"{art.get('title','')}. {art.get('description','')}"
        confs  = _classify(blob, [label])
        score  = confs.get(label, 0.0)
        if score > best_score:
            best, best_score = art, score
    return best


def _build_signal_from_label(label: str,
                              confidence: float,
                              articles: List[Dict],
                              jobs:     List[Dict]) -> Optional[Signal]:
    """Convert one (label, confidence) pair into a Signal object."""
    sig_type = config.RESEARCH_SIGNAL_LABEL_TYPES.get(label, "unknown")
    score    = round(confidence * 100, 1)
    strength = _strength(score)

    if sig_type == "hiring" and jobs:
        # hiring signals attach to the job postings rather than articles
        from scrapers.linkedin_jobs import SOURCE_LABEL as _LI_SOURCE
        office_jobs = [j for j in jobs if j.get("is_office_role")]
        if office_jobs:
            return Signal(
                type=sig_type,
                title=f"Posted {len(office_jobs)} office/workplace role(s)",
                description=f"Including: {office_jobs[0].get('title', '')}",
                source=_LI_SOURCE,
                strength=max(strength, 4),
                score=max(score, 75.0),
            )
        return Signal(
            type=sig_type,
            title=f"{len(jobs)} active job postings detected",
            description=f"Most recent: {jobs[0].get('title', '')}",
            source=_LI_SOURCE,
            strength=strength,
            score=score,
        )

    article = _best_article_for(label, articles)
    if article:
        body  = article.get("description", "") or ""
        title = article.get("title", "") or ""
        src   = article.get("source_name", "News")
        # bart-mnli will confidently score bland text on every label. Defend
        # against that two ways:
        #   1. If the article body is thin (< 60 chars), there's not enough
        #      text to support a signal regardless of model score.
        #   2. Require the title OR body to mention at least one keyword for
        #      this signal type, else the score is a phantom.
        if len((body or "").strip()) < 60:
            return None
        sig_type_kws = _LABEL_KEYWORDS.get(sig_type, [])
        haystack = f"{title} {body}".lower()
        if sig_type_kws and not _keyword_match(haystack, sig_type_kws):
            return None
        # Pick a sentence that actually mentions a keyword for this label, so
        # signal cards don't all show the same blob from a single article.
        snippet = _snippet_for_label(label, body, max_chars=280)
        return Signal(
            type=sig_type,
            title=title[:140],
            description=snippet or body[:280],
            source=src,
            strength=strength,
            score=score,
            url=article.get("url", ""),
        )

    # signal asserted by the aggregate classifier but no source found
    if confidence >= 0.55:
        return Signal(
            type=sig_type,
            title=label.capitalize(),
            description=(
                "Inferred from combined article and job data — no single "
                "source dominates."
            ),
            source="Aggregate",
            strength=strength,
            score=score,
        )
    return None


def _top_hook_sentence(signal: Signal, company: str) -> str:
    """One-sentence plain-English description of the strongest signal."""
    if signal.type == "expansion":
        return (
            f"{company} appears to be expanding — {signal.title} "
            f"({signal.source})."
        )
    if signal.type == "hiring":
        return (
            f"{company} is hiring aggressively — {signal.title.lower()}."
        )
    if signal.type == "funding":
        return (
            f"{company} has fresh capital — {signal.title} ({signal.source})."
        )
    if signal.type == "lease":
        return (
            f"{company} may be near a lease decision — {signal.title}."
        )
    return f"{company}: {signal.title}."


# ── Main entry point ────────────────────────────────────────────────────────


def generate_report(prospect: Dict,
                     enrichment: Optional[Dict] = None,
                     articles:   Optional[List[Dict]] = None,
                     jobs:       Optional[List[Dict]] = None) -> ResearchReport:
    """
    Build a ResearchReport for a single prospect.

    Args:
        prospect:    dict with keys company, domain, contact_name, contact_email,
                     contact_title, linkedin_url, id
        enrichment:  optional dict of additional context (months_since_funding,
                     headcount_growth_pct, etc.) for tie-breaking signals
        articles:    list of dicts from scrapers (google_news, newsapi)
        jobs:        list of job-posting dicts (currently always empty —
                     LinkedIn jobs scraping is disabled; left in the signature
                     so a future source can plug in without API changes)

    Returns:
        ResearchReport instance
    """
    articles = articles or []
    jobs     = jobs     or []

    company = prospect.get("company") or prospect.get("company_name") or ""

    report = ResearchReport(
        prospect_id   = prospect.get("id", company.lower().replace(" ", "-")),
        company       = company,
        contact_name  = prospect.get("contact_name", ""),
        contact_email = prospect.get("contact_email", ""),
        contact_title = prospect.get("contact_title", ""),
        linkedin_url  = prospect.get("linkedin_url", ""),
        sector        = prospect.get("sector", ""),
        source        = prospect.get("source", "watchlist"),
        approved      = bool(prospect.get("approved", True)),
        raw_articles  = articles,
        raw_jobs      = jobs,
        generated_at  = datetime.datetime.now().isoformat(),
        headcount     = int(prospect.get("headcount") or 0),
        industry      = prospect.get("industry", ""),
        open_roles    = int(prospect.get("open_roles") or 0),
        office_roles  = int(prospect.get("office_roles") or 0),
        ats           = prospect.get("ats", ""),
    )

    # Concatenate article text for aggregate classification
    combined_text = " ".join(
        f"{a.get('title','')}. {a.get('description','')}" for a in articles
    )
    if jobs:
        job_blob = " ".join(
            f"Hiring: {j.get('title','')}" for j in jobs[:10]
        )
        combined_text = f"{combined_text} {job_blob}"

    # If no real signal data, fall back to mock signals using enrichment
    if not combined_text.strip():
        return _mock_fallback(report, prospect, enrichment, jobs)

    confidences = _classify(combined_text, config.RESEARCH_SIGNAL_LABELS)

    if not confidences:
        return _mock_fallback(report, prospect, enrichment, jobs)

    signals: List[Signal] = []
    for label in config.RESEARCH_SIGNAL_LABELS:
        sig = _build_signal_from_label(
            label, confidences.get(label, 0.0), articles, jobs
        )
        if sig:
            signals.append(sig)

    # LinkedIn-derived signal injection. The bart-mnli hiring path inside
    # _build_signal_from_label can produce a weak "X active job postings"
    # LinkedIn signal at whatever low confidence bart-mnli returned on bare
    # job titles. We override that with a deterministic score so a clear CRE
    # signal isn't masked by bart-mnli noise.
    try:
        from scrapers.linkedin_jobs import summarise_jobs, SOURCE_LABEL as _LI_SOURCE
        job_summary = summarise_jobs(jobs, company)
    except Exception:
        job_summary = {"office_signal_count": 0, "total_jobs": 0, "office_roles": []}
        _LI_SOURCE = "LinkedIn Jobs · last 7 days"

    injected_signal = None
    if job_summary.get("office_signal_count", 0) > 0:
        office_roles = ", ".join(job_summary["office_roles"][:2])
        injected_signal = Signal(
            type="hiring",
            title=(
                f"{job_summary['office_signal_count']} office role(s) "
                f"posted on LinkedIn"
            ),
            description=(
                f"{company} is actively hiring: {office_roles}. "
                f"Office-specific hiring is a direct indicator of space "
                f"planning activity."
            ),
            source=_LI_SOURCE,
            strength=5 if job_summary["office_signal_count"] >= 2 else 4,
            score=90.0 if job_summary["office_signal_count"] >= 2 else 75.0,
        )
    elif job_summary.get("total_jobs", 0) >= 3:
        injected_signal = Signal(
            type="hiring",
            title=(
                f"{job_summary['total_jobs']} open roles posted in last 7 days"
            ),
            description=(
                f"{company} has {job_summary['total_jobs']} active job "
                f"postings in the last week — strong hiring velocity signal."
            ),
            source=_LI_SOURCE,
            strength=3,
            score=55.0,
        )

    if injected_signal is not None:
        # Drop any weaker LinkedIn signal the bart-mnli hiring path produced
        # so we don't double-count and so the deterministic score wins.
        signals = [
            s for s in signals
            if not ("linkedin" in (s.source or "").lower()
                    and s.score < injected_signal.score)
        ]
        # If a LinkedIn signal *stronger* than ours already exists, skip.
        if not any("linkedin" in (s.source or "").lower() for s in signals):
            signals.append(injected_signal)

    # Sort by score descending so strongest is first
    signals.sort(key=lambda s: s.score, reverse=True)
    report.signals = signals

    # Composite is a weighted MEAN of signal scores, biased toward the top
    # two — so a single overwhelming signal can carry the day, but the score
    # stays in the 0–100 range each individual signal lives in.
    if signals:
        top_two = signals[:2]
        rest    = signals[2:]
        top_mean = sum(s.score for s in top_two) / len(top_two)
        if rest:
            rest_mean = sum(s.score for s in rest) / len(rest)
            weighted  = top_mean * 0.7 + rest_mean * 0.3
        else:
            weighted = top_mean
        report.composite_score = round(max(0.0, min(100.0, weighted)))
    else:
        report.composite_score = 0

    report.tier        = _tier_for(report.composite_score)
    report.skip_today  = report.composite_score < config.RESEARCH_SKIP_BELOW
    report.skip_reason = (
        "Composite under daily threshold — nothing material to act on today."
        if report.skip_today else ""
    )
    report.top_hook = (
        _top_hook_sentence(signals[0], company) if signals else ""
    )

    return report


def _tier_for(score: int) -> str:
    if score >= config.RESEARCH_TIER_HOT:
        return "hot"
    if score >= config.RESEARCH_TIER_WARM:
        return "warm"
    return "nurture"


def _mock_fallback(report: ResearchReport,
                    prospect:  Dict,
                    enrichment: Optional[Dict],
                    jobs:       List[Dict]) -> ResearchReport:
    """Produce a plausible mock report when scrapers + HF both come back empty."""
    company = report.company or prospect.get("company", "")

    signals: List[Signal] = []
    enrichment = enrichment or {}

    if jobs:
        from scrapers.linkedin_jobs import SOURCE_LABEL as _LI_SOURCE
        office_jobs = [j for j in jobs if j.get("is_office_role")]
        if office_jobs:
            signals.append(Signal(
                type="hiring",
                title=f"{len(office_jobs)} office/workplace role(s) posted",
                description=f"Including {office_jobs[0].get('title','')}",
                source=_LI_SOURCE,
                strength=4, score=78.0,
            ))

    if enrichment.get("months_since_funding") and 10 <= enrichment["months_since_funding"] <= 20:
        signals.append(Signal(
            type="funding",
            title=f"In deployment window — funded {enrichment['months_since_funding']} months ago",
            description=(
                "Inside the typical 12–18 month post-funding deployment window "
                "where companies most often expand their footprint."
            ),
            source="Apollo enrichment",
            strength=4, score=72.0,
        ))

    if enrichment.get("headcount_growth_pct", 0) >= 20:
        signals.append(Signal(
            type="hiring",
            title=f"Headcount grew {enrichment['headcount_growth_pct']:.0f}% in 6 months",
            description="Sustained growth at this rate usually triggers space planning.",
            source="Apollo enrichment",
            strength=4, score=70.0,
        ))

    if not signals:
        signals.append(Signal(
            type="space_need",
            title=f"Monitoring {company}",
            description=(
                "No fresh signals today — keep the prospect on the watchlist "
                "and re-check tomorrow."
            ),
            source="Watchlist",
            strength=1, score=20.0,
        ))

    signals.sort(key=lambda s: s.score, reverse=True)
    report.signals         = signals
    report.composite_score = round(sum(s.score for s in signals) / len(signals))
    report.tier            = _tier_for(report.composite_score)
    report.skip_today      = report.composite_score < config.RESEARCH_SKIP_BELOW
    report.skip_reason     = (
        "No live signals today — only baseline enrichment context."
        if report.skip_today else ""
    )
    report.top_hook = _top_hook_sentence(signals[0], company)
    return report


# ── Persistence helpers ─────────────────────────────────────────────────────


_DATA_DIR = "data"


def _ensure_data_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def save_morning_run(reports: List[ResearchReport],
                       summary: Optional[Dict] = None,
                       date_str: Optional[str] = None) -> str:
    """Write a list of reports to data/morning_run_{date}.json."""
    _ensure_data_dir()
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(_DATA_DIR, f"morning_run_{date_str}.json")
    bundle = {
        "generated_at": datetime.datetime.now().isoformat(),
        "summary":      summary or {},
        "reports":      [r.to_dict() for r in reports],
    }
    with open(path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)
    return path


def load_morning_run(date_str: Optional[str] = None) -> List[ResearchReport]:
    """
    Load a saved morning run.

    If date_str is None, loads today's file. If today's is missing, loads the
    most recent morning_run_*.json available and marks every report as
    stale=True so the UI can warn the broker.
    """
    _ensure_data_dir()

    today = datetime.date.today().isoformat()
    target = date_str or today
    path   = os.path.join(_DATA_DIR, f"morning_run_{target}.json")

    is_stale = False
    if not os.path.exists(path):
        if date_str is not None:
            return []
        # fall back to the most recent file
        candidates = sorted(
            f for f in os.listdir(_DATA_DIR)
            if f.startswith("morning_run_") and f.endswith(".json")
        )
        if not candidates:
            return []
        path = os.path.join(_DATA_DIR, candidates[-1])
        is_stale = True

    try:
        with open(path) as f:
            bundle = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    raw = bundle.get("reports") or bundle.get("drafts") or []
    out: List[ResearchReport] = []
    for r in raw:
        # tolerate the older shape where each entry was {"report": {...}, "subject", ...}
        if "report" in r and isinstance(r["report"], dict):
            base = dict(r["report"])
            if r.get("subject") or r.get("body"):
                base["draft"] = {
                    "subject":  r.get("subject", ""),
                    "body":     r.get("body", ""),
                    "linkedin": r.get("linkedin", ""),
                    "variant":  r.get("variant", "Warm"),
                }
            rep = ResearchReport.from_dict(base)
        else:
            rep = ResearchReport.from_dict(r)
        rep.stale = is_stale
        out.append(rep)

    return out


def save_discovered_leads(leads: List[Dict],
                            date_str: Optional[str] = None) -> str:
    """Persist freshly discovered candidate leads (unapproved)."""
    _ensure_data_dir()
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(_DATA_DIR, f"discovered_leads_{date_str}.json")
    with open(path, "w") as f:
        json.dump(leads, f, indent=2, default=str)
    return path


def load_discovered_leads(date_str: Optional[str] = None) -> List[Dict]:
    _ensure_data_dir()
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(_DATA_DIR, f"discovered_leads_{date_str}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f) or []
    except (json.JSONDecodeError, OSError):
        return []


# ── CLI entry point for manual testing ──────────────────────────────────────


if __name__ == "__main__":
    sample_prospect = {
        "id": "healthaxis-001",
        "company": "HealthAxis",
        "contact_name": "Rachel Kim",
        "contact_email": "rachel.kim@healthaxis.io",
        "contact_title": "VP of Operations",
        "linkedin_url": "https://www.linkedin.com/in/rachelkim-ops",
    }
    rep = generate_report(
        sample_prospect,
        enrichment={"months_since_funding": 14, "headcount_growth_pct": 30},
        articles=[],
        jobs=[],
    )
    print(json.dumps(rep.to_dict(), indent=2))
