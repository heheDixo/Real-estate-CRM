import datetime
import random
from typing import Any
import requests
import config
from models.prospect     import Prospect
from models.enrichment   import EnrichmentResult
from models.score_result import ScoreResult

# ICPProfile lived in the wizard flow which has been retired. The few methods
# on the writer that referenced it (generate_email, generate_linkedin,
# generate_followup) are not invoked by the morning research pipeline —
# scheduler._generate_draft builds prompts directly and bypasses them. The
# annotations remain as Any so the file imports without that module.
ICPProfile = Any


class OutreachWriter:
    """
    Generates email and LinkedIn outreach using Mistral-7B-Instruct
    via the HuggingFace Inference API.

    Three public methods:
      - generate_email(prospect, enrichment, score, icp, brief)
        → (subject, body)
      - generate_linkedin(prospect, enrichment, score, icp)
        → str
      - generate_followup(prospect, enrichment, score, icp)
        → (subject, body)

    Falls back to template-based drafts if HF API unavailable.
    """

    MODEL_URL = f"{config.HF_API_BASE}/{config.WRITING_MODEL}"

    def __init__(self):
        self.available = config.HF_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {
            "Authorization": f"Bearer {config.HF_TOKEN}",
            "Content-Type":  "application/json",
        }

   
    # Public methods


    def generate_email(self, prospect: Prospect,
                        enrichment: EnrichmentResult,
                        score: ScoreResult,
                        icp: ICPProfile,
                        brief: list) -> tuple:
        """
        Generate first-touch email subject line and body.

        Args:
            prospect:   Prospect instance
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance
            icp:        ICPProfile — for tone rules
            brief:      list of brief bullet strings from briefer.py

        Returns:
            tuple of (subject_line: str, email_body: str)
        """
        if self.available:
            prompt  = self._build_email_prompt(
                prospect, enrichment, score, icp, brief)
            raw_out = self._call_hf_api(prompt)
            if raw_out:
                return self._parse_email(raw_out)

        return self._fallback_email(prospect, enrichment, score)

    def generate_linkedin(self, prospect: Prospect,
                           enrichment: EnrichmentResult,
                           score: ScoreResult,
                           icp: ICPProfile) -> str:
        """
        Generate a LinkedIn connection message or InMail.

        Args:
            prospect:   Prospect instance
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance
            icp:        ICPProfile — for tone rules

        Returns:
            LinkedIn message string (under 300 chars)
        """
        if self.available:
            prompt  = self._build_linkedin_prompt(
                prospect, enrichment, score, icp)
            raw_out = self._call_hf_api(prompt, max_tokens=120)
            if raw_out:
                # trim to 300 chars if needed
                cleaned = raw_out.strip()
                return cleaned[:300] if len(cleaned) > 300 else cleaned

        return self._fallback_linkedin(prospect, enrichment, score)

    def generate(self, brief: str,
                  tone_prefix: str = "",
                  tone_injection: str = ""):
        """
        Lightweight free-form draft generation used by the tone-variant
        verification CLI. Returns a small object with email_subject and
        email_body attributes.

        Args:
            brief:          plain-text brief (company, contact, signals, hook)
            tone_prefix:    optional system-prompt prefix from
                            config.TONE_VARIANT_PREFIXES
            tone_injection: optional style block from tone_learner

        Returns:
            namespace-like object with .email_subject and .email_body
        """
        from types import SimpleNamespace

        prefix = (tone_prefix + "\n\n") if tone_prefix else ""
        injection = (tone_injection + "\n\n") if tone_injection else ""

        prompt = (
            f"[INST] {prefix}{config.EMAIL_SYSTEM_PROMPT}\n\n"
            f"{injection}"
            f"Brief:\n{brief}\n\n"
            f"Now write the email. Start with 'Subject:' on line 1.\n"
            f"[/INST]"
        )

        subject, body = "", ""
        if self.available:
            raw = self._call_hf_api(prompt)
            if raw:
                subject, body = self._parse_email(raw)

        if not subject or not body:
            subject = subject or f"Quick thought — {brief.splitlines()[0][:60]}"
            body    = body    or (
                f"{brief}\n\n"
                f"Worth a short conversation?\n\n"
                f"{config.AGENT_NAME}\n{config.FIRM_NAME}"
            )

        return SimpleNamespace(email_subject=subject, email_body=body)

    def generate_followup(self, prospect: Prospect,
                           enrichment: EnrichmentResult,
                           score: ScoreResult,
                           icp: ICPProfile) -> tuple:
        """
        Generate a Day 5 follow-up email (no reply to first touch).

        Args:
            prospect:   Prospect instance
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance
            icp:        ICPProfile — for tone rules

        Returns:
            tuple of (subject_line: str, email_body: str)
        """
        if self.available:
            prompt  = self._build_followup_prompt(
                prospect, enrichment, score, icp)
            raw_out = self._call_hf_api(prompt, max_tokens=200)
            if raw_out:
                return self._parse_email(raw_out)

        return self._fallback_followup(prospect, score)

    # Prompt building


    def _build_email_prompt(self, prospect: Prospect,
                              enrichment: EnrichmentResult,
                              score: ScoreResult,
                              icp: ICPProfile,
                              brief: list) -> str:
        """Build the first-touch email prompt."""

        # key facts to reference
        top_signal = self._get_top_signal_sentence(
            prospect, enrichment, score)

        brief_text = (
            "\n".join(f"- {b}" for b in brief[:3])
            if brief else "No brief available."
        )

        # learned rules from ICP decision history
        learned = icp.get_system_prompt_rules()
        learned_block = f"\n\nAdditional preferences:\n{learned}" if learned else ""

        # tone rules
        tone_block = icp.get_tone_prompt_block()

        prompt = (
            f"[INST] {config.EMAIL_SYSTEM_PROMPT}\n\n"
            f"{tone_block}"
            f"{learned_block}\n\n"
            f"Prospect:\n"
            f"Company: {prospect.company_name}\n"
            f"Contact: {prospect.contact_first_name} {prospect.contact_last_name}, "
            f"{prospect.contact_title}\n"
            f"City: {prospect.city}\n"
            f"Stage: {prospect.company_stage}, {prospect.industry}\n"
            f"Headcount: {enrichment.headcount_current} employees\n"
            f"\nKey signal to open with:\n{top_signal}\n"
            f"\nResearch brief context (do not quote directly — use as background):\n"
            f"{brief_text}\n\n"
            f"Now write the email. Start with 'Subject:' on line 1.\n"
            f"[/INST]"
        )
        return prompt

    def _build_linkedin_prompt(self, prospect: Prospect,
                                 enrichment: EnrichmentResult,
                                 score: ScoreResult,
                                 icp: ICPProfile) -> str:
        """Build the LinkedIn message prompt."""

        top_signal = self._get_top_signal_sentence(
            prospect, enrichment, score)

        prompt = (
            f"[INST] {config.LINKEDIN_SYSTEM_PROMPT}\n\n"
            f"Prospect:\n"
            f"Name: {prospect.contact_first_name}\n"
            f"Title: {prospect.contact_title}\n"
            f"Company: {prospect.company_name} ({prospect.city})\n"
            f"Signal: {top_signal}\n\n"
            f"Write the LinkedIn message now. "
            f"Maximum 300 characters. No subject line. "
            f"Just the message text.\n"
            f"[/INST]"
        )
        return prompt

    def _build_followup_prompt(self, prospect: Prospect,
                                 enrichment: EnrichmentResult,
                                 score: ScoreResult,
                                 icp: ICPProfile) -> str:
        """Build the Day 5 follow-up email prompt."""

        # pick a different signal for the follow-up
        # to avoid repeating the first touch
        followup_signal = self._get_secondary_signal(enrichment, score)

        prompt = (
            f"[INST] {config.FOLLOWUP_SYSTEM_PROMPT}\n\n"
            f"Context:\n"
            f"Prospect: {prospect.contact_first_name} {prospect.contact_last_name}, "
            f"{prospect.contact_title} at {prospect.company_name}\n"
            f"First touch was sent 5 days ago. No reply received.\n"
            f"New signal to add: {followup_signal}\n\n"
            f"Write the follow-up. Start with 'Subject:' on line 1.\n"
            f"[/INST]"
        )
        return prompt

    # HuggingFace API call


    def _call_hf_api(self, prompt: str,
                      max_tokens: int = None) -> str:
        """
        Call Mistral-7B-Instruct and return generated text.

        Args:
            prompt:     full [INST]...[/INST] prompt
            max_tokens: override for max_new_tokens

        Returns:
            generated text string or empty string on failure
        """
        params = dict(config.WRITING_PARAMS)
        if max_tokens:
            params["max_new_tokens"] = max_tokens

        payload = {
            "inputs":     prompt,
            "parameters": params,
        }

        try:
            response = requests.post(
                self.MODEL_URL,
                headers = self.headers,
                json    = payload,
                timeout = config.WRITING_TIMEOUT,
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    return data[0].get("generated_text", "").strip()
                return ""

            if response.status_code == 503:
                import time
                print("[Writer] Model loading. Waiting 20s...")
                time.sleep(20)
                response = requests.post(
                    self.MODEL_URL,
                    headers = self.headers,
                    json    = payload,
                    timeout = config.WRITING_TIMEOUT,
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and data:
                        return data[0].get("generated_text", "").strip()

            print(f"[Writer] HF API returned {response.status_code}")
            return ""

        except requests.exceptions.Timeout:
            print("[Writer] HF API timed out.")
            return ""
        except Exception as e:
            print(f"[Writer] Error: {e}")
            return ""

    # ──────────────────────────────────────────────────────────────────────────
    # Output parsing
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_email(self, raw_text: str) -> tuple:
        """
        Extract subject line and body from Mistral output.

        Handles "Subject: ..." on first line and body below.

        Args:
            raw_text: raw generated text

        Returns:
            tuple of (subject_line, email_body)
        """
        lines   = raw_text.strip().split("\n")
        subject = ""
        body_lines = []
        past_subject = False

        for line in lines:
            stripped = line.strip()

            if not past_subject and stripped.lower().startswith("subject:"):
                subject      = stripped[8:].strip()
                past_subject = True
                continue

            if past_subject or (not subject and stripped):
                # skip blank lines immediately after subject
                if not past_subject and not stripped:
                    continue
                past_subject = True
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        # clean up common Mistral artifacts
        for artifact in ["[/INST]", "[INST]", "</s>", "<s>"]:
            body    = body.replace(artifact, "").strip()
            subject = subject.replace(artifact, "").strip()

        if not subject:
            subject = "Quick thought on your NYC expansion"

        return subject, body


    # Signal helpers


    def _get_top_signal_sentence(self, prospect: Prospect,
                                   enrichment: EnrichmentResult,
                                   score: ScoreResult) -> str:
        """
        Build a one-sentence description of the top signal.
        This is what Mistral opens the email with.
        """
        top_type = score.top_signal_type

        if top_type == "expansion_news" and enrichment.strongest_signal_headline:
            return enrichment.strongest_signal_headline

        if top_type == "hiring_velocity":
            jobs  = enrichment.total_jobs_posted
            geo   = prospect.city
            roles = enrichment.office_roles_posted
            text  = (
                f"{prospect.company_name} has posted {jobs} jobs in {geo} "
                f"in the last 60 days"
            )
            if roles > 0:
                text += (
                    f", including {roles} office/workplace management "
                    f"role{'s' if roles > 1 else ''}"
                )
            return text + "."

        if top_type == "funding_timing":
            stage  = prospect.last_funding_type
            months = enrichment.months_since_funding
            amount = (f"${prospect.last_funding_amount:,}"
                      if prospect.last_funding_amount else "")
            amount_text = f" of {amount}" if amount else ""
            return (
                f"{prospect.company_name} raised {stage}{amount_text} "
                f"{months} months ago and has grown headcount "
                f"{enrichment.headcount_growth_pct:.0f}% since."
            )

        if top_type == "lease_expiry":
            return (
                f"Signals suggest {prospect.company_name}'s current "
                f"office arrangement in {prospect.city} may be changing."
            )

        # default — use whatever the model identified
        return (
            f"{prospect.company_name} is showing strong growth signals in "
            f"{prospect.city} with {enrichment.headcount_current} employees "
            f"and {enrichment.total_jobs_posted} active job openings."
        )

    def _get_secondary_signal(self, enrichment: EnrichmentResult,
                                score: ScoreResult) -> str:
        """
        Return a secondary signal for the follow-up email —
        different from the primary signal used in the first touch.
        """
        top_type = score.top_signal_type

        if top_type != "hiring_velocity" and enrichment.total_jobs_posted > 0:
            return (
                f"They now have {enrichment.total_jobs_posted} open roles — "
                f"headcount growth continues to accelerate."
            )

        if top_type != "funding_timing" and enrichment.is_in_deployment_window:
            return (
                f"Companies at their stage typically make real estate decisions "
                f"12–18 months post-funding — they are right in that window."
            )

        if top_type != "expansion_news" and enrichment.has_expansion_news:
            return enrichment.strongest_signal_headline

        return (
            f"The market in {enrichment.prospect_id.split('.')[0]} "
            f"sector is moving quickly — "
            f"wanted to make sure this stays on your radar."
        )


    # Template fallbacks


    def _fallback_email(self, prospect: Prospect,
                          enrichment: EnrichmentResult,
                          score: ScoreResult) -> tuple:
        """
        Template-based email fallback.

        Rotates between several subject lines and openings so that
        successive regenerations produce visibly different drafts even
        without a live model.
        """
        first     = (prospect.contact_first_name or
                     (prospect.contact_name.split()[0] if prospect.contact_name
                      else "there"))
        company   = prospect.company_name
        city      = prospect.city
        jobs      = enrichment.total_jobs_posted or 0
        growth    = enrichment.headcount_growth_pct or 0
        headcount = getattr(enrichment, "headcount_current", 0) or 0

        # Subjects — only use the percentage one when we actually have growth
        subject_options = [
            f"{company}'s growth in {city} — quick question",
            f"Thinking about {company}'s next move in {city}",
            f"{company} + {city} office footprint",
            f"Quick note on {company}'s {city} trajectory",
        ]
        if growth > 0:
            subject_options.append(f"{company} — {growth:.0f}% growth, one observation")
        subject = random.choice(subject_options)

        # Pick an opener whose claims match the data we actually have. Never
        # mention 0% growth or 0 open roles — that reads as a copy-paste leak.
        opening_options: list = []
        if jobs > 0 and growth > 0:
            opening_options += [
                f"Noticed {company} has been growing quickly in {city} — "
                f"{jobs} open roles and {growth:.0f}% headcount growth in the last "
                f"six months is a meaningful pace.",
                f"{company}'s {city} team has expanded {growth:.0f}% in six months "
                f"with {jobs} active postings — that pace usually shows up in "
                f"space planning conversations sooner than people expect.",
            ]
        elif jobs > 0:
            opening_options += [
                f"Noticed {company} has {jobs} open roles right now — the kind of "
                f"hiring pace that usually puts space on the table within a quarter or two.",
                f"{company}'s {jobs} live roles caught my eye — that's the volume "
                f"where workplace planning starts to surface in our conversations.",
            ]
        elif headcount > 0:
            opening_options += [
                f"{company}'s {headcount:,}-person team in {city} is right in the "
                f"window where space decisions tend to come up before the lease cycle hints at it.",
                f"At {company}'s scale ({headcount:,} people), the timing of the "
                f"next workplace decision is often more about growth than the calendar.",
            ]
        else:
            opening_options += [
                f"Have been tracking {company} for a while — wanted to put a marker "
                f"down before the next workplace conversation kicks off internally.",
                f"Reaching out cold on {company} — your name came up as the right "
                f"person to share a quick read with on the {city} market.",
            ]
        opening = random.choice(opening_options)

        # Middle line — only reference "that pace / growth rate" when the
        # opener actually established a pace. Otherwise use a neutral framing.
        has_pace = jobs > 0 or growth > 0
        if has_pace:
            middle_options = [
                "Companies at that trajectory often find their current space "
                "needs a second look before it becomes urgent.",
                "Most teams at that growth rate end up reassessing their "
                "footprint 6–12 months before they thought they would.",
                "At that pace, the calculus on current space tends to shift "
                "faster than the lease renewal cycle suggests.",
            ]
        else:
            middle_options = [
                "Most workplace decisions get framed against the lease cycle, "
                "but the better window is usually 6–12 months earlier.",
                "Teams at your scale tend to revisit space planning quietly, "
                "before any of the obvious triggers force the conversation.",
                "Worth flagging early — even a brief read of the current "
                "market changes how the next renewal conversation lands.",
            ]
        middle = random.choice(middle_options)

        closing_options = [
            "Is that something on your radar at all?",
            "Worth a short conversation, even if only to put a marker down?",
            "Curious whether that's already a live topic internally.",
        ]
        closing = random.choice(closing_options)

        body = (
            f"Hi {first},\n\n"
            f"{opening}\n\n"
            f"{middle} {closing}\n\n"
            f"{config.AGENT_NAME}\n"
            f"{config.FIRM_NAME}"
        )

        return subject, body

    def _fallback_linkedin(self, prospect: Prospect,
                             enrichment: EnrichmentResult,
                             score: ScoreResult) -> str:
        """Template-based LinkedIn fallback with rotating phrasing."""
        first   = prospect.contact_first_name or prospect.contact_name.split()[0]
        company = prospect.company_name
        jobs    = enrichment.total_jobs_posted

        options = [
            f"Hi {first} — saw {company} has {jobs} open roles in "
            f"{prospect.city}. That kind of growth usually prompts a "
            f"second look at office needs. Worth a quick chat?",
            f"Hi {first} — {company}'s hiring pace in {prospect.city} "
            f"({jobs} open roles) caught my eye. Curious whether space "
            f"planning is already on the table for the team.",
            f"Hi {first} — noticed {company} is staffing up across "
            f"{prospect.city}. At {jobs} open roles, office footprint "
            f"usually becomes a live question. Open to compare notes?",
        ]
        return random.choice(options)[:300]

    def _fallback_followup(self, prospect: Prospect,
                              score: ScoreResult) -> tuple:
        """Template-based follow-up fallback."""
        first   = prospect.contact_first_name or prospect.contact_name.split()[0]
        company = prospect.company_name

        subject = f"Re: {company} — one more thought"
        body = (
            f"Hi {first},\n\n"
            f"Wanted to add one more data point since my last note — "
            f"the market in your sector has tightened meaningfully "
            f"in the last 30 days.\n\n"
            f"Happy to share what I'm seeing if useful.\n\n"
            f"{config.AGENT_NAME}\n"
            f"{config.FIRM_NAME}"
        )
        return subject, body

# Compatibility alias — the verification CLI imports DraftWriter
DraftWriter = OutreachWriter
