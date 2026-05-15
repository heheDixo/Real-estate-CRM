from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DraftResult:
    """
    Output of the drafting step.

    Contains the research brief, email draft, and LinkedIn
    message for one prospect. Also tracks the approval decision
    and any edits made in the review UI.

    Page 3 (draft review) reads from and writes to this model.
    """

    # Identity 
    prospect_id: str = ""
    drafted_at: str = ""
    icp_profile_name: str = ""
    scoring_model: str = "facebook/bart-large-mnli"
    writing_model: str = "mistralai/Mistral-7B-Instruct-v0.2"

    # Research brief 
    # 5-bullet analyst summary produced by hf_models/briefer.py.
    # Shown above the draft on Page 3 so he has context while reviewing.
    brief_bullets: list = field(default_factory=list)

    #  Email draft
    email_subject: str = ""
    email_body: str = ""

    # LinkedIn message 
    linkedin_message: str = ""

    # Personalisation transparency
    # Which enrichment fields fed into the draft.
    # Shown as chips in the UI: "expansion news signal used"
    personalisation_tags: list = field(default_factory=list)

    #Top signal reference 
    # The specific signal the email opens with.
    # e.g. "TechCo expansion into New York announced 8 weeks ago"
    opening_signal: str = ""

    #  Approval tracking 
    approval_status: str = "pending"
    # "pending" | "approved" | "edited_approved" | "rejected"

    approved_at: str = ""
    rejected_at: str = ""
    rejection_reason: str = ""

    #  Edit tracking (feeds tone learning) 
    was_edited: bool = False
    edited_subject: str = ""         # if he changed the subject
    edited_body: str = ""            # if he changed the body
    edited_linkedin: str = ""        # if he changed the LinkedIn message

    #Final versions (what actually goes out)
    # If he edited, these contain his version. If not, copies of originals.
    final_subject: str = ""
    final_body: str = ""
    final_linkedin: str = ""

    # ──────────────────────────────────────────────────────────────────────────
    # Methods
    # ──────────────────────────────────────────────────────────────────────────

    def approve(self, edited_body: str = "",
                edited_subject: str = "",
                edited_linkedin: str = "") -> None:
        """
        Record approval — with or without edits.
        Sets final versions and updates approval status.

        """
        import datetime
        self.approved_at = datetime.datetime.now().isoformat()

        # detect edits
        if edited_body and edited_body != self.email_body:
            self.was_edited    = True
            self.edited_body   = edited_body
            self.approval_status = "edited_approved"
        else:
            self.approval_status = "approved"

        if edited_subject and edited_subject != self.email_subject:
            self.was_edited      = True
            self.edited_subject  = edited_subject

        if edited_linkedin and edited_linkedin != self.linkedin_message:
            self.was_edited       = True
            self.edited_linkedin  = edited_linkedin

        # set final versions
        self.final_subject  = edited_subject  or self.email_subject
        self.final_body     = edited_body     or self.email_body
        self.final_linkedin = edited_linkedin or self.linkedin_message

    def reject(self, reason: str = "") -> None:
        """
        Record rejection.

        """
        import datetime
        self.approval_status = "rejected"
        self.rejected_at     = datetime.datetime.now().isoformat()
        self.rejection_reason = reason

    def word_count(self, text: str) -> int:
        """Count words in a text string."""
        return len(text.split()) if text else 0

    def email_word_count(self) -> int:
        """Word count of the current email body."""
        body = self.edited_body or self.email_body
        return self.word_count(body)

    def linkedin_char_count(self) -> int:
        """Character count of the LinkedIn message."""
        msg = self.edited_linkedin or self.linkedin_message
        return len(msg) if msg else 0

    def to_dict(self) -> dict:
        """Serialise to dict for session state storage."""
        return {
            "prospect_id":        self.prospect_id,
            "drafted_at":         self.drafted_at,
            "icp_profile_name":   self.icp_profile_name,
            "scoring_model":      self.scoring_model,
            "writing_model":      self.writing_model,
            "brief_bullets":      self.brief_bullets,
            "email_subject":      self.email_subject,
            "email_body":         self.email_body,
            "linkedin_message":   self.linkedin_message,
            "personalisation_tags":self.personalisation_tags,
            "opening_signal":     self.opening_signal,
            "approval_status":    self.approval_status,
            "approved_at":        self.approved_at,
            "rejected_at":        self.rejected_at,
            "rejection_reason":   self.rejection_reason,
            "was_edited":         self.was_edited,
            "edited_subject":     self.edited_subject,
            "edited_body":        self.edited_body,
            "edited_linkedin":    self.edited_linkedin,
            "final_subject":      self.final_subject,
            "final_body":         self.final_body,
            "final_linkedin":     self.final_linkedin,
        }