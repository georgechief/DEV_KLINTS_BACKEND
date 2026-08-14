import uuid

from django.db import models
from django.utils import timezone

from tenants.models import Company, ConnectorSnapshot, Tenant, User


class DataRun(models.Model):
    """
    Existing dataruns API / tasks / admin model.
    DBML equivalent table is `runs` (see Run).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="data_runs",
    )
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    run_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Frozen scoring inputs for this DCS DataRun (PRD-DCS-03).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class Run(models.Model):
    class RunType(models.TextChoices):
        FULL = "full", "Full"
        INCREMENTAL = "incremental", "Incremental"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    run_type = models.TextField(choices=RunType.choices)
    status = models.TextField(choices=Status.choices)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "runs"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.run_type} ({self.status})"


class RunConnector(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="run_connectors",
    )
    connector_snapshot = models.ForeignKey(
        ConnectorSnapshot,
        on_delete=models.CASCADE,
        related_name="run_connectors",
    )

    class Meta:
        db_table = "run_connectors"

    def __str__(self) -> str:
        return f"{self.run_id} → {self.connector_snapshot_id}"


class Contact(models.Model):
    """Core identity layer — one person per company + platform source + external id.

    ``source`` scopes uniqueness so Shopify and Manago rows never overwrite each
    other when platform IDs collide (Excel sheet 06: separate system surfaces;
    CI-05 joins them later).
    """

    class Source(models.TextChoices):
        SHOPIFY = "shopify", "Shopify"
        MANAGO_AI = "manago_ai", "Manago"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    source = models.TextField(
        choices=Source.choices,
        default=Source.UNKNOWN,
        help_text="Origin platform; required for cross-platform uniqueness.",
    )
    external_id = models.TextField()
    # Manago contact.externalId → Shopify customers.id (Excel CI-05 join spine).
    # Empty on Shopify rows (self id is external_id) and when Manago has no link.
    link_key = models.TextField(
        blank=True,
        default="",
        help_text="Cross-system link key (Manago externalId / Shopify customer id).",
    )
    email = models.TextField(blank=True, default="")
    phone = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contacts"
        indexes = [
            models.Index(
                fields=["company", "source", "external_id"],
                name="contacts_co_src_ext_idx",
            ),
            models.Index(fields=["email"], name="contacts_email_idx"),
            models.Index(
                fields=["company", "link_key"],
                name="contacts_co_link_key_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "source", "external_id"],
                name="uniq_contacts_company_source_external_id",
            ),
        ]

    def __str__(self) -> str:
        return self.email or f"{self.source}:{self.external_id}" or str(self.id)


class Order(models.Model):
    """Revenue / transaction layer — orders & Manago purchase events.

    Unique per (company, source, external_id) so Shopify orders and Manago
    transactions with the same raw id cannot collide.
    """

    class Status(models.TextChoices):
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        SHOPIFY = "shopify", "Shopify"
        MANAGO_AI = "manago_ai", "Manago"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    source = models.TextField(
        choices=Source.choices,
        default=Source.UNKNOWN,
        help_text="Origin platform; required for cross-platform uniqueness.",
    )
    external_id = models.TextField()
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.TextField()
    status = models.TextField(choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders"
        indexes = [
            models.Index(fields=["contact"], name="orders_contact_idx"),
            models.Index(
                fields=["company", "source", "external_id"],
                name="orders_co_src_ext_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "source", "external_id"],
                name="uniq_orders_company_source_external_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.external_id} ({self.status})"


class ContactMetric(models.Model):
    """Per-run truth layer — revenue + lifecycle metrics for a contact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="contact_metrics",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="metrics",
    )
    total_orders = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    last_order_at = models.DateTimeField(null=True, blank=True)
    avg_order_value = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    ltv = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    lifecycle_stage = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_metrics"
        indexes = [
            models.Index(fields=["run"], name="contact_metrics_run_idx"),
            models.Index(fields=["contact"], name="contact_metrics_contact_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "contact"],
                name="uniq_contact_metrics_run_contact",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contact_id} @ {self.run_id}"


class RunIssue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    entity_type = models.TextField()  # contact, order, dcs_check, …
    entity_id = models.UUIDField()
    issue_type = models.TextField()
    severity = models.TextField()
    detected_at = models.DateTimeField(null=True, blank=True)
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Check evidence: matches, mismatches, reason_code, message.",
    )

    class Meta:
        db_table = "run_issues"
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["run"], name="run_issues_run_idx"),
            models.Index(fields=["entity_id"], name="run_issues_entity_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.issue_type} ({self.severity})"


class RunIssueImpact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_issue = models.ForeignKey(
        RunIssue,
        on_delete=models.CASCADE,
        related_name="impacts",
    )
    revenue_impact = models.DecimalField(max_digits=20, decimal_places=6)
    risk_score = models.DecimalField(max_digits=20, decimal_places=6)

    class Meta:
        db_table = "run_issue_impact"

    def __str__(self) -> str:
        return f"impact:{self.run_issue_id}"


class LifecycleProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="lifecycle_profiles",
    )
    name = models.TextField()
    description = models.TextField()

    class Meta:
        db_table = "lifecycle_profiles"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LifecycleProfileContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lifecycle_profile = models.ForeignKey(
        LifecycleProfile,
        on_delete=models.CASCADE,
        related_name="profile_contacts",
    )
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="lifecycle_profile_contacts",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="lifecycle_profile_contacts",
    )
    stage = models.TextField()
    score = models.DecimalField(max_digits=20, decimal_places=6)
    signals = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "lifecycle_profile_contacts"
        indexes = [
            models.Index(
                fields=["run", "contact"],
                name="lpc_run_contact_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contact_id} ({self.stage})"


class ScoringModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    version = models.TextField()
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "scoring_models"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


class RunScore(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    scoring_model = models.ForeignKey(
        ScoringModel,
        on_delete=models.CASCADE,
        related_name="run_scores",
    )
    entity_type = models.TextField()
    entity_id = models.TextField()
    score = models.DecimalField(max_digits=20, decimal_places=6)
    breakdown = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "run_scores"

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id}={self.score}"


class Agent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    type = models.TextField()

    class Meta:
        db_table = "agents"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Approval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    status = models.TextField()
    approved_by = models.TextField()
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approvals"
        ordering = ["-approved_at"]

    def __str__(self) -> str:
        return f"{self.status} ({self.approved_by})"


class DataFixBlueprint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="data_fix_blueprints",
    )
    name = models.TextField()
    description = models.TextField()
    expected_revenue_impact = models.DecimalField(max_digits=20, decimal_places=6)
    risk_reduction = models.DecimalField(max_digits=20, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_fix_blueprints"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class DataFixAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(
        DataFixBlueprint,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action_type = models.TextField()
    target_entity = models.TextField()
    target_id = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.TextField()

    class Meta:
        db_table = "data_fix_actions"

    def __str__(self) -> str:
        return f"{self.action_type} ({self.status})"


class RunDiff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="diffs",
    )
    previous_run_id = models.UUIDField()
    diff_summary = models.JSONField(default=dict, blank=True)
    changes_count = models.IntegerField()

    class Meta:
        db_table = "run_diff"

    def __str__(self) -> str:
        return f"diff:{self.run_id}"


class RunVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="verifications",
    )
    verified = models.BooleanField()
    verification_score = models.DecimalField(max_digits=20, decimal_places=6)
    flags = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "run_verification"

    def __str__(self) -> str:
        return f"verified={self.verified}"


class QaCheck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="qa_checks",
    )
    check_type = models.TextField()
    result = models.TextField()
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "qa_checks"

    def __str__(self) -> str:
        return f"{self.check_type}: {self.result}"


class WritebackJob(models.Model):
    """Persisted writeback preview / execute job (PRD-WB-01 §7).

    Canonical writeback persistence — ``DataFixAction`` remains unused for WB-01.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="writeback_jobs",
    )
    check_id = models.CharField(max_length=16)
    mode = models.CharField(max_length=20)
    status = models.CharField(max_length=20)
    diff_hash = models.CharField(max_length=64)
    approval_tier = models.CharField(max_length=20, blank=True, default="")
    approval_id = models.UUIDField(null=True, blank=True)
    token_binds = models.JSONField(default=dict, blank=True)
    intents = models.JSONField(default=list, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    sandbox = models.BooleanField(default=False)
    actor_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="writeback_jobs",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "writeback_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "-created_at"]),
            models.Index(fields=["company", "check_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"writeback:{self.check_id}:{self.mode}"


class WritebackApprovalToken(models.Model):
    """Diff-bound approval token for prod writeback execute (BL-017 / pack approval_token.schema)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="writeback_approval_tokens",
    )
    writeback_job = models.ForeignKey(
        WritebackJob,
        on_delete=models.CASCADE,
        related_name="approval_tokens",
    )
    schema_version = models.CharField(max_length=16, default="1.0.0")
    actor_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_writeback_approvals",
    )
    approver_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_writeback_approvals",
    )
    actor_id = models.CharField(max_length=64)
    actor_role = models.CharField(max_length=32)
    scope = models.JSONField(default=list, blank=True)
    object_id = models.CharField(max_length=16)
    object_version = models.CharField(max_length=32)
    diff_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    approved_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "writeback_approval_tokens"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status", "-created_at"]),
            models.Index(fields=["diff_hash", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"approval:{self.object_id}:{self.status}"


class AuditLog(models.Model):
    class Tone(models.TextChoices):
        INFO = "info", "Info"
        RISK = "risk", "Risk"
        LOSS = "loss", "Loss"
        REVENUE = "revenue", "Revenue"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    run = models.ForeignKey(
        Run,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=128)
    tone = models.CharField(
        max_length=16,
        choices=Tone.choices,
        default=Tone.INFO,
    )
    summary = models.TextField()
    performed_by = models.TextField()
    actor_user_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64)
    entry_hash = models.CharField(max_length=64)
    audit_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "-created_at"]),
            models.Index(
                fields=["company", "audit_read", "-created_at"],
                name="audit_logs_co_read_created_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "entry_hash"],
                name="uniq_audit_logs_company_entry_hash",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.performed_by}"


class Handoff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="handoffs",
    )
    status = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "handoffs"
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"handoff:{self.status}"


class RunSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="run_schedules",
    )
    cron = models.TextField()
    timezone = models.TextField()
    is_active = models.BooleanField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "run_schedules"

    def __str__(self) -> str:
        return f"{self.cron} ({self.timezone})"


class RunJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    trigger_type = models.TextField()
    status = models.TextField()
    priority = models.IntegerField()
    attempts = models.IntegerField()
    max_attempts = models.IntegerField()
    queued_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField()

    class Meta:
        db_table = "run_jobs"
        ordering = ["-queued_at"]

    def __str__(self) -> str:
        return f"{self.trigger_type} ({self.status})"


class DimensionMaster(models.Model):
    """DCS scoring dimension registry (sheet 07)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dimension_id = models.CharField(max_length=2, unique=True)
    key = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=255)
    purpose = models.TextField(blank=True, default="")
    percent_needed = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_percent = models.PositiveSmallIntegerField(default=0)
    result_status_json = models.JSONField(default=dict, blank=True)
    confidence_json = models.JSONField(default=dict, blank=True)
    final_state_json = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dimension_masters"
        ordering = ["dimension_id"]

    def __str__(self) -> str:
        return f"{self.dimension_id} {self.name}"


class RootCauseMaster(models.Model):
    """DCS root-cause codes (sheet 03, RC-01 … RC-15)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    standard_remediation_pattern = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "root_cause_masters"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class CheckMaster(models.Model):
    """Immutable MVP1 check registry (42 checks; sheets 02 + 09)."""

    class CheckClass(models.TextChoices):
        RULE_BASED = "RULE_BASED", "Rule-based"
        DRIFT = "DRIFT", "Drift"

    class Role(models.TextChoices):
        GATE = "GATE", "Gate"
        SCORED = "SCORED", "Scored"

    class Severity(models.TextChoices):
        CRITICAL = "Critical", "Critical"
        HIGH = "High", "High"
        MEDIUM = "Medium", "Medium"
        LOW = "Low", "Low"
        INFORMATIONAL = "Informational", "Informational"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence = models.PositiveSmallIntegerField(unique=True)
    check_id = models.CharField(max_length=8, unique=True)
    check_name = models.CharField(max_length=255)
    dimension = models.ForeignKey(
        DimensionMaster,
        on_delete=models.PROTECT,
        related_name="checks",
    )
    check_class = models.CharField(max_length=32, choices=CheckClass.choices)
    check_type = models.CharField(max_length=64)
    role = models.CharField(max_length=16, choices=Role.choices)
    cadence = models.CharField(max_length=32)
    phase = models.CharField(max_length=16)
    systems_compared = models.TextField()
    numeric_weight = models.PositiveSmallIntegerField(default=0)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    root_cause_ids = models.JSONField(default=list, blank=True)
    suggested_fix = models.TextField(
        blank=True,
        default="",
        help_text="Excel sheet 02 Suggested Fix (catalogue).",
    )
    fix_type = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Excel sheet 02 Fix Type (e.g. Configuration, Automated writeback).",
    )
    fix_owner = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Excel sheet 02 Fix Owner: Klints (automated), Data lead, "
            "External integrator, or CRM manager."
        ),
    )
    is_active = models.BooleanField(default=True)
    is_optional = models.BooleanField(
        default=False,
        help_text="Optional gate/check: FAIL must not block app shell (FE-03).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "check_masters"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.check_id} {self.check_name}"


class AssessmentReport(models.Model):
    """Immutable composed assessment report payload (PRD-RPT-01)."""

    class Variant(models.TextChoices):
        PAID_FULL = "PAID_FULL", "Paid full"
        FREE_DIAGNOSTIC = "FREE_DIAGNOSTIC", "Free diagnostic"

    class Status(models.TextChoices):
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="assessment_reports",
    )
    variant = models.CharField(
        max_length=32,
        choices=Variant.choices,
        default=Variant.PAID_FULL,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.READY,
    )
    dcs_data_run = models.ForeignKey(
        DataRun,
        on_delete=models.PROTECT,
        related_name="assessment_reports",
    )
    architecture_assessment = models.ForeignKey(
        "ArchitectureAssessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_reports",
    )
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)
    window_since = models.DateTimeField(null=True, blank=True)
    window_until = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64)
    template_version = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessment_reports_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_reports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"report:{self.id}:{self.status}"


class AiCall(models.Model):
    """One provider attempt per AI task (PRD-AI-01 §7.1)."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        GATE_DENIED = "gate_denied", "Gate denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_calls",
    )
    task_type = models.CharField(max_length=64)
    check_id = models.CharField(max_length=32, blank=True, default="")
    dcs_data_run = models.ForeignKey(
        DataRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_calls",
    )
    fingerprint = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=64)
    policy_version = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    provider = models.CharField(max_length=64)
    langsmith_run_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_calls"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "-created_at"], name="ai_calls_company_created_idx"),
            models.Index(fields=["company", "task_type"], name="ai_calls_company_task_idx"),
            models.Index(fields=["fingerprint"], name="ai_calls_fingerprint_idx"),
        ]

    def __str__(self) -> str:
        return f"ai_call:{self.id}:{self.status}"


class AiSuggestion(models.Model):
    """Validated AI output artifact — upserted by fingerprint (PRD-AI-01 §7.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ai_call = models.ForeignKey(
        AiCall,
        on_delete=models.PROTECT,
        related_name="suggestions",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_suggestions",
    )
    task_type = models.CharField(max_length=64)
    check_id = models.CharField(max_length=32, blank=True, default="")
    dcs_data_run = models.ForeignKey(
        DataRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_suggestions",
    )
    fingerprint = models.CharField(max_length=64)
    payload_json = models.JSONField(default=dict, blank=True)
    headline = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_suggestions"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "task_type", "fingerprint"],
                name="uniq_ai_suggestions_company_task_fp",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "task_type", "check_id"],
                name="ai_sugg_company_task_check_idx",
            ),
            models.Index(fields=["fingerprint"], name="ai_sugg_fingerprint_idx"),
        ]

    def __str__(self) -> str:
        return f"ai_suggestion:{self.id}:{self.task_type}"
