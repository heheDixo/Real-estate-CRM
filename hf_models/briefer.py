import datetime
import requests
import config
from models.prospect    import Prospect
from models.enrichment  import EnrichmentResult
from models.score_result import ScoreResult
from models.draft_result import DraftResult


class ProspectBriefer:
    """
    Generates a 5-bullet research brief for a prospect using
    Mistral-7B-Instruct via the HuggingFace Inference API.

    One public method:
      - generate_brief(prospect, enrichment, score) → list[str]

    Falls back to a rule-based brief if the HF API is unavailable.
    """

    MODEL_URL = f"{config.HF_API_BASE}/{config.BRIEFING_MODEL}"

    def __init__(self):
        self.available = config.HF_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {
            "Authorization": f"Bearer {config.HF_TOKEN}",
            "Content-Type":  "application/json",
        }


    # Public method


    def generate_brief(self, prospect: Prospect,
                        enrichment: EnrichmentResult,
                        score: ScoreResult) -> list:
        """
        Generate a 5-bullet analyst research brief.

        Args:
            prospect:   Prospect instance
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance

        Returns:
            list of 5 bullet strings
        """
        if self.available:
            prompt  = self._build_prompt(prospect, enrichment, score)
            raw_out = self._call_hf_api(prompt)
            if raw_out:
                bullets = self._parse_bullets(raw_out)
                if len(bullets) >= 3:   # accept if at least 3 bullets came back
                    return bullets[:5]

        # fallback to rule-based brief
        return self._rule_based_brief(prospect, enrichment, score)


    # Prompt building
    
    def _build_prompt(self, prospect: Prospect,
                       enrichment: EnrichmentResult,
                       score: ScoreResult) -> str:
        """
        Build the Mistral [INST] prompt for brief generation.

        We provide all key enrichment facts as structured input and
        instruct the model to produce exactly 5 bullets in specific
        category order.
        """
        # format funding line
        funding_line = "No recent funding on record."
        if prospect.last_funding_type and enrichment.months_since_funding:
            amount = (f"${prospect.last_funding_amount:,}"
                      if prospect.last_funding_amount else "undisclosed amount")
            funding_line = (
                f"Raised {prospect.last_funding_type} of {amount} "
                f"{enrichment.months_since_funding} months ago."
            )
            if enrichment.is_in_deployment_window:
                funding_line += " In the 12–18 month deployment window."

        # format headcount line
        headcount_line = f"Current headcount: {enrichment.headcount_current}."
        if enrichment.headcount_growth_pct > 0:
            headcount_line += (
                f" Grew {enrichment.headcount_growth_pct:.0f}% "
                f"in the last 6 months "
                f"(from {enrichment.headcount_6mo_ago})."
            )

        # format jobs line
        jobs_line = f"Active job postings: {enrichment.total_jobs_posted}."
        if enrichment.office_roles_posted > 0:
            jobs_line += (
                f" Includes {enrichment.office_roles_posted} "
                f"office/workplace role(s) — direct space signal."
            )

        # format news line
        news_line = "No significant news signals detected."
        if enrichment.strongest_signal_headline:
            news_line = (
                f"Recent news ({enrichment.strongest_signal_type}): "
                f"{enrichment.strongest_signal_headline}"
            )

        # format score line
        score_line = (
            f"AI space need score: {score.composite}/100 — {score.tier}. "
            f"Top signal: {score.top_signal_text}."
        )

        prompt = (
            f"[INST] {config.BRIEFING_SYSTEM_PROMPT}\n\n"
            f"Prospect data:\n"
            f"Company: {prospect.company_name}\n"
            f"Sector: {prospect.industry}\n"
            f"Location: {prospect.city}, {prospect.state}\n"
            f"Stage: {prospect.company_stage}\n"
            f"Funding: {funding_line}\n"
            f"Headcount: {headcount_line}\n"
            f"Jobs: {jobs_line}\n"
            f"News: {news_line}\n"
            f"Contact: {prospect.contact_name}, {prospect.contact_title}\n"
            f"Score: {score_line}\n\n"
            f"Write exactly 5 bullets in this category order:\n"
            f"1. Company stage\n"
            f"2. Space need signal\n"
            f"3. Right contact\n"
            f"4. Best angle\n"
            f"5. Main risk\n"
            f"[/INST]"
        )
        return prompt


    # HuggingFace API call


    def _call_hf_api(self, prompt: str) -> str:
        """
        Call Mistral-7B-Instruct and return the generated text.

        Args:
            prompt: full [INST]...[/INST] prompt string

        Returns:
            generated text string or empty string on failure
        """
        payload = {
            "inputs":     prompt,
            "parameters": config.BRIEFING_PARAMS,
        }

        try:
            response = requests.post(
                self.MODEL_URL,
                headers = self.headers,
                json    = payload,
                timeout = config.BRIEFING_TIMEOUT,
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    return data[0].get("generated_text", "").strip()
                return ""

            if response.status_code == 503:
                import time
                print("[Briefer] Model loading. Waiting 20s...")
                time.sleep(20)
                response = requests.post(
                    self.MODEL_URL,
                    headers = self.headers,
                    json    = payload,
                    timeout = config.BRIEFING_TIMEOUT,
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and data:
                        return data[0].get("generated_text", "").strip()

            print(f"[Briefer] HF API returned {response.status_code}")
            return ""

        except requests.exceptions.Timeout:
            print("[Briefer] HF API timed out.")
            return ""
        except Exception as e:
            print(f"[Briefer] Error: {e}")
            return ""


    # Output parsing

    def _parse_bullets(self, raw_text: str) -> list:
        """
        Extract bullet points from Mistral's output.

        Handles multiple formats: "• text", "- text", "1. text",
        "**Category:** text", and plain numbered lines.

        Args:
            raw_text: raw generated text from Mistral

        Returns:
            list of clean bullet strings
        """
        bullets = []
        lines   = raw_text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # strip leading bullet markers
            for marker in ["•", "-", "*", "–", "—"]:
                if line.startswith(marker):
                    line = line[len(marker):].strip()
                    break

            # strip leading numbers like "1." "1)" "1:"
            if len(line) > 2 and line[0].isdigit() and line[1] in ".):":
                line = line[2:].strip()

            # skip very short lines (likely noise)
            if len(line) < 15:
                continue

            bullets.append(line)

        return bullets


    # Rule-based fallback brief
   
    def _rule_based_brief(self, prospect: Prospect,
                            enrichment: EnrichmentResult,
                            score: ScoreResult) -> list:
        """
        Generate a factual brief from enrichment data without using
        the HuggingFace API.

        Used when the API is unavailable. Less polished than the
        Mistral output but fully informative and demo-safe.
        """
        bullets = []

        # 1. Company stage
        funding_text = ""
        if prospect.last_funding_type and enrichment.months_since_funding:
            amount = (f"${prospect.last_funding_amount:,}"
                      if prospect.last_funding_amount else "undisclosed")
            window = (
                " — in the 12–18 month deployment window"
                if enrichment.is_in_deployment_window else ""
            )
            funding_text = (
                f" Raised {prospect.last_funding_type} of {amount} "
                f"{enrichment.months_since_funding} months ago{window}."
            )

        bullets.append(
            f"**Company stage:** {prospect.company_stage} "
            f"{prospect.industry} company in {prospect.city} "
            f"with {enrichment.headcount_current} employees.{funding_text}"
        )

        # 2. Space need signal
        signals = []
        if enrichment.headcount_growth_pct >= 20:
            signals.append(
                f"headcount grew {enrichment.headcount_growth_pct:.0f}% "
                f"in 6 months"
            )
        if enrichment.office_roles_posted > 0:
            signals.append(
                f"actively hiring for "
                f"{enrichment.office_roles_posted} office/workplace role(s)"
            )
        if enrichment.has_expansion_news:
            signals.append("public expansion announcement detected")
        if enrichment.is_in_deployment_window:
            signals.append(
                f"in the 12–18 month post-funding deployment window"
            )

        signal_text = (
            ", ".join(signals) if signals
            else "limited space need signals detected at this time"
        )
        bullets.append(
            f"**Space need signal:** {signal_text.capitalize()}. "
            f"AI space need score: {score.composite}/100 ({score.tier})."
        )

        # 3. Right contact
        bullets.append(
            f"**Right contact:** {prospect.contact_name}, "
            f"{prospect.contact_title} — "
            f"{'likely has authority over real estate and operations decisions' if any(t in prospect.contact_title.lower() for t in ['vp', 'coo', 'cfo', 'chief', 'head', 'director', 'president', 'ceo']) else 'verify real estate decision authority before investing heavily'}."
        )

        # 4. Best angle
        top_signal = score.top_signal_text or "their recent growth trajectory"
        bullets.append(
            f"**Best angle:** Lead with {top_signal}. "
            f"{'Reference the expansion announcement directly — it is specific and verifiable.' if enrichment.has_expansion_news else 'Reference their hiring velocity and headcount growth as the hook.'}"
        )

        # 5. Main risk
        risks = []
        if not enrichment.is_in_deployment_window and enrichment.months_since_funding:
            if enrichment.months_since_funding > 20:
                risks.append(
                    f"funding was {enrichment.months_since_funding} months ago "
                    f"— past the peak deployment window"
                )
        if enrichment.triggers_count < 2:
            risks.append("fewer than 2 trigger signals fired — lower conviction")
        if not prospect.contact_email:
            risks.append("no verified email on file — outreach may need LinkedIn first")

        risk_text = (
            "; ".join(risks) if risks
            else "no significant risks identified — proceed with standard outreach"
        )
        bullets.append(f"**Main risk:** {risk_text.capitalize()}.")

        return bullets