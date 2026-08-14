"""Assessment report constants (PRD-RPT-01)."""

SCHEMA_VERSION = "1.0.0"
REPORT_VERSION = "1"
TEMPLATE_VERSION = "KLINTS-REPORT-1.1.0"
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
