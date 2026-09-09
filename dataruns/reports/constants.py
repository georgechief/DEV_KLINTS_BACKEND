"""Assessment report constants (PRD-RPT-01)."""

SCHEMA_VERSION = "1.0.0"
REPORT_VERSION = "1"
TEMPLATE_VERSION = "KLINTS-REPORT-1.1.0"
# Overview Export brief + DCS Export fix plan (FE-13) share overview_brief profile.
REPORT_PROFILE_OVERVIEW_BRIEF = "overview_brief"
OVERVIEW_BRIEF_TEMPLATE_VERSION = "KLINTS-OVERVIEW-BRIEF-1.0.0"
IMPACT_METHOD_NOTE = (
    "Impact figures are directional (DCS revenue model) and rounded to the nearest dollar."
)
RENDERER = "reportlab"
RETENTION_POLICY_ID = "tenant-default"

PII_FORBIDDEN_KEYS = frozenset(
    {
        "evidence_preview",
        "evidence",
        "mismatches",
        "matches",
        "contact_id",
        "email",
        "phone",
        "external_id",
    }
)
