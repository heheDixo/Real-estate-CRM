import csv
import io
import datetime
import config
from models.prospect    import Prospect
from models.icp_profile import ICPProfile
from connectors         import ApolloConnector
from mock_data          import get_all_mock_prospects


class IngestionPipeline:
    """
    Handles lead ingestion from three sources:
      - Apollo API search
      - CSV file upload
      - Mock data (demo fallback)

    All three paths return list[Prospect] with status = "new".
    Deduplicates by domain against an existing list.
    """

    def __init__(self):
        self.apollo = ApolloConnector()

    def ingest(self, source: str,
                icp: ICPProfile,
                existing_domains: list = None,
                csv_content: str = None,
                max_results: int = 10) -> list:
        """
        Ingest prospects from the specified source.

        Args:
            source:           "apollo" | "csv" | "mock"
            icp:              active ICPProfile
            existing_domains: list of domains already in session state
            csv_content:      CSV file content string (for source="csv")
            max_results:      max prospects to return

        Returns:
            list of new Prospect instances (deduplicated)
        """
        existing = set(existing_domains or [])

        if source == "apollo" and not config.FORCE_MOCK_MODE:
            prospects = self._from_apollo(icp, max_results)
        elif source == "csv" and csv_content:
            prospects = self._from_csv(csv_content, icp)
        else:
            prospects = self._from_mock()

        # deduplicate
        new_prospects = [
            p for p in prospects
            if p.domain not in existing
        ]

        # set ICP profile name on each
        for p in new_prospects:
            p.icp_profile_name = icp.name

        return new_prospects[:max_results]

    # Source handlers


    def _from_apollo(self, icp: ICPProfile, max_results: int) -> list:
        """Pull prospects from Apollo search."""
        try:
            return self.apollo.search_prospects(icp, max_results)
        except Exception as e:
            print(f"[IngestionPipeline] Apollo search failed: {e}")
            return self._from_mock()

    def _from_csv(self, csv_content: str, icp: ICPProfile) -> list:
        """
        Parse a CSV file into Prospect objects.

        Expects columns (case-insensitive):
          company, domain, first_name, last_name, title,
          email, phone, city, state, headcount, stage, industry
        """
        prospects = []

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            # normalise header names to lowercase
            for row in reader:
                row_lower = {k.lower().strip(): v.strip()
                             for k, v in row.items() if k}
                prospect = Prospect(
                    id                 = row_lower.get("domain", ""),
                    source             = "csv",
                    company_name       = row_lower.get("company", ""),
                    domain             = row_lower.get("domain", ""),
                    city               = row_lower.get("city", ""),
                    state              = row_lower.get("state", ""),
                    headcount          = int(row_lower.get("headcount", 0) or 0),
                    company_stage      = row_lower.get("stage", ""),
                    industry           = row_lower.get("industry", ""),
                    contact_first_name = row_lower.get("first_name", ""),
                    contact_last_name  = row_lower.get("last_name", ""),
                    contact_name       = (
                        f"{row_lower.get('first_name','')} "
                        f"{row_lower.get('last_name','')}".strip()
                    ),
                    contact_title      = row_lower.get("title", ""),
                    contact_email      = row_lower.get("email", ""),
                    contact_phone      = row_lower.get("phone", ""),
                    status             = "new",
                    ingested_at        = datetime.datetime.now().isoformat(),
                )

                # skip rows without a domain
                if not prospect.domain:
                    continue

                prospects.append(prospect)

        except Exception as e:
            print(f"[IngestionPipeline] CSV parse error: {e}")

        return prospects

    def _from_mock(self) -> list:
        """Return pre-built mock prospects."""
        return get_all_mock_prospects()