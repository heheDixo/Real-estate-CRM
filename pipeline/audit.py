import datetime
import config


class AuditBuilder:
    """
    Builds the pipeline audit log and calculates time savings.
    No AI or API calls — pure logic and formatting.
    """

    def build_log(self, timestamps: dict,
                   sources_used: list,
                   sources_failed: list,
                   score_composite: float,
                   tier: str,
                   used_hf: bool) -> list:
        """
        Build a formatted audit log from pipeline step timestamps.

        Args:
            timestamps:     dict of step_name → ISO timestamp string
            sources_used:   list of source names that succeeded
            sources_failed: list of source names that failed
            score_composite: final composite score
            tier:           Hot | Warm | Nurture
            used_hf:        True if HF API was used, False if fallback

        Returns:
            list of audit entry dicts with time, action, result, duration_ms
        """
        entries = []

        step_labels = {
            "ingestion_start":   "Lead ingested",
            "ingestion_end":     "Ingestion complete",
            "apollo_start":      "Apollo org enrichment started",
            "apollo_end":        "Apollo org enrichment complete",
            "proxycurl_start":   "LinkedIn hiring data requested",
            "proxycurl_end":     "LinkedIn hiring data received",
            "newsapi_start":     "News signal search started",
            "newsapi_end":       "News signal search complete",
            "scoring_start":     "AI scoring started (bart-large-mnli)",
            "scoring_end":       "AI scoring complete",
            "briefing_start":    "Research brief generation started",
            "briefing_end":      "Research brief generated",
            "writing_start":     "Email + LinkedIn draft generation started",
            "writing_end":       "Drafts generated",
        }

        # pair start/end timestamps to calculate durations
        step_names = [
            ("ingestion_start",  "ingestion_end",  "Lead ingested"),
            ("apollo_start",     "apollo_end",     "Apollo enrichment"),
            ("proxycurl_start",  "proxycurl_end",  "LinkedIn enrichment"),
            ("newsapi_start",    "newsapi_end",    "News signal search"),
            ("scoring_start",    "scoring_end",    "AI scoring"),
            ("briefing_start",   "briefing_end",   "Brief generation"),
            ("writing_start",    "writing_end",    "Draft generation"),
        ]

        for start_key, end_key, label in step_names:
            if start_key not in timestamps:
                continue

            start_str = timestamps[start_key]
            end_str   = timestamps.get(end_key, start_str)

            start_dt  = datetime.datetime.fromisoformat(start_str)
            end_dt    = datetime.datetime.fromisoformat(end_str)
            duration  = int((end_dt - start_dt).total_seconds() * 1000)

            # determine result text
            if "apollo" in start_key and "apollo" in str(sources_failed):
                result_text = "⚠️ Failed — mock data used"
            elif "proxycurl" in start_key and "proxycurl" in str(sources_failed):
                result_text = "⚠️ Failed — skipped"
            elif "newsapi" in start_key and "newsapi" in str(sources_failed):
                result_text = "⚠️ Failed — skipped"
            elif "scoring" in start_key:
                model = "HuggingFace API" if used_hf else "Rule-based fallback"
                result_text = f"✅ {score_composite:.0f}/100 — {tier} ({model})"
            elif "brief" in start_key or "writing" in start_key:
                model = "Mistral-7B-Instruct" if used_hf else "Template fallback"
                result_text = f"✅ Complete ({model})"
            else:
                result_text = "✅ Complete"

            entries.append({
                "time":        start_dt.strftime("%H:%M:%S.%f")[:-3],
                "action":      label,
                "result":      result_text,
                "duration_ms": duration,
            })

        return entries

    def calculate_time_savings(self, prospect_count: int = 1) -> dict:
        """
        Calculate and format the time savings comparison.

        Args:
            prospect_count: number of prospects processed this session

        Returns:
            dict with manual_mins, system_mins, saved_mins, saved_hours,
            weekly_manual_hrs, weekly_system_hrs, weekly_saved_hrs
        """
        manual = config.MANUAL_TIME_PER_PROSPECT["total"]
        system = config.SYSTEM_TIME_PER_PROSPECT["total"]
        saved  = manual - system

        # weekly estimates at 15-20 prospects/week
        weekly_low  = 15
        weekly_high = 20
        weekly_mid  = (weekly_low + weekly_high) / 2

        return {
            # per prospect
            "manual_mins":      manual,
            "system_mins":      system,
            "saved_mins":       saved,
            "time_reduction_pct": round((saved / manual) * 100),

            # this session
            "session_prospects":    prospect_count,
            "session_manual_mins":  manual * prospect_count,
            "session_system_mins":  system * prospect_count,
            "session_saved_mins":   saved * prospect_count,

            # weekly at current volume
            "weekly_prospects_low":  weekly_low,
            "weekly_prospects_high": weekly_high,
            "weekly_manual_hrs_low":  round(manual * weekly_low  / 60, 1),
            "weekly_manual_hrs_high": round(manual * weekly_high / 60, 1),
            "weekly_system_hrs_low":  round(system * weekly_low  / 60, 1),
            "weekly_system_hrs_high": round(system * weekly_high / 60, 1),
            "weekly_saved_hrs_low":   round(saved  * weekly_low  / 60, 1),
            "weekly_saved_hrs_high":  round(saved  * weekly_high / 60, 1),

            # breakdown of where time is saved
            "breakdown": config.MANUAL_TIME_PER_PROSPECT,
        }

    def build_salesforce_csv(self, prospects_data: list) -> str:
        """
        Build a Salesforce Engage-compatible CSV string from
        a list of pipeline result dicts.

        Args:
            prospects_data: list of dicts, each containing
                            'prospect', 'score', 'draft' keys

        Returns:
            CSV string ready for Salesforce import
        """
        import csv, io

        field_map = config.SALESFORCE_EXPORT_FIELDS
        output    = io.StringIO()
        writer    = csv.DictWriter(
            output,
            fieldnames = list(field_map.values()),
            extrasaction = "ignore",
        )
        writer.writeheader()

        for item in prospects_data:
            prospect = item.get("prospect")
            score    = item.get("score")
            draft    = item.get("draft")

            if not prospect:
                continue

            row = {
                "Company":           getattr(prospect, "company_name", ""),
                "Full Name":         getattr(prospect, "contact_name", ""),
                "First Name":        getattr(prospect, "contact_first_name", ""),
                "Last Name":         getattr(prospect, "contact_last_name", ""),
                "Title":             getattr(prospect, "contact_title", ""),
                "Email":             getattr(prospect, "contact_email", ""),
                "Phone":             getattr(prospect, "contact_phone", ""),
                "Website":           getattr(prospect, "domain", ""),
                "City":              getattr(prospect, "city", ""),
                "State":             getattr(prospect, "state", ""),
                "Number of Employees": getattr(prospect, "headcount", ""),
                "Lead Source Detail":  getattr(prospect, "company_stage", ""),
                "Industry":          getattr(prospect, "industry", ""),
                "LeadFlow Score":    getattr(score, "composite", "") if score else "",
                "LeadFlow Tier":     getattr(score, "tier", "") if score else "",
                "LeadFlow Top Signal": getattr(score, "top_signal_text", "") if score else "",
                "Email Subject":     getattr(draft, "email_subject", "") if draft else "",
                "Email Body":        getattr(draft, "final_body", "") if draft else "",
                "Outreach Status":   getattr(draft, "approval_status", "") if draft else "",
            }
            writer.writerow(row)

        return output.getvalue()