"""Use Case Library persistence (PRD-UC-01 §8)."""

from __future__ import annotations

import uuid

from django.db import models


class UseCasePilot(models.Model):
    """MVP1 pilot registry row — tenant-global seed from pilot_manifest.json."""

    use_case_id = models.CharField(max_length=16, primary_key=True)
    pilot_rank = models.PositiveSmallIntegerField(unique=True)
    title = models.CharField(max_length=512)
    release = models.CharField(max_length=32, default="MVP1")
    manifest_status = models.CharField(max_length=64, blank=True, default="")
    mcp_dependency = models.BooleanField(default=True)
    fallback = models.CharField(max_length=128, blank=True, default="")
    blueprint_file = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "use_case_pilots"
        ordering = ["pilot_rank"]

    def __str__(self) -> str:
        return f"{self.use_case_id} ({self.title})"


class UseCaseBlueprint(models.Model):
    """Full workflow blueprint JSON for a pilot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pilot = models.OneToOneField(
        UseCasePilot,
        on_delete=models.CASCADE,
        related_name="blueprint",
        to_field="use_case_id",
        db_column="use_case_id",
    )
    blueprint_id = models.CharField(max_length=128, unique=True)
    schema_version = models.CharField(max_length=32)
    body = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "use_case_blueprints"
        ordering = ["pilot__pilot_rank"]

    def __str__(self) -> str:
        return self.blueprint_id


class PilotStageMap(models.Model):
    """Primary lifecycle stages for gap → pilot matching (PRD §6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pilot = models.ForeignKey(
        UseCasePilot,
        on_delete=models.CASCADE,
        related_name="stage_maps",
        to_field="use_case_id",
        db_column="use_case_id",
    )
    stage_id = models.CharField(max_length=32)
    is_primary = models.BooleanField(default=True)

    class Meta:
        app_label = "dataruns"
        db_table = "pilot_stage_maps"
        constraints = [
            models.UniqueConstraint(
                fields=["pilot", "stage_id"],
                name="pilot_stage_map_unique",
            ),
        ]
        ordering = ["pilot__pilot_rank", "stage_id"]

    def __str__(self) -> str:
        return f"{self.pilot_id} → {self.stage_id}"


class WorkflowBuildPackage(models.Model):
    """Generated BL-016 build package for a company-scoped pilot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        related_name="workflow_build_packages",
    )
    pilot = models.ForeignKey(
        UseCasePilot,
        on_delete=models.PROTECT,
        related_name="build_packages",
        to_field="use_case_id",
    )
    payload = models.JSONField(default=dict)
    provisional_supplemental = models.BooleanField(default=False)
    blueprint_content_hash = models.CharField(max_length=64)
    package_content_hash = models.CharField(max_length=64, db_index=True)
    dcs_data_run_id = models.IntegerField(null=True, blank=True)
    af_assessment_id = models.UUIDField(null=True, blank=True)
    generated_by = models.ForeignKey(
        "tenants.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_build_packages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dataruns"
        db_table = "workflow_build_packages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["company", "pilot_id", "-created_at"],
                name="wf_bpkg_co_uc_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.pilot_id} @ {self.id}"

    @property
    def use_case_id(self) -> str:
        return str(self.pilot_id)


class WorkflowQaResult(models.Model):
    """One QA evaluation of a build package (PRD-QA-01 / BL-018).

    v1 lock: append history per package; GET returns latest by created_at.
    """

    class Status(models.TextChoices):
        PASS = "PASS", "PASS"
        FAIL = "FAIL", "FAIL"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        related_name="workflow_qa_results",
    )
    package = models.ForeignKey(
        WorkflowBuildPackage,
        on_delete=models.CASCADE,
        related_name="qa_results",
    )
    use_case_id = models.CharField(max_length=16, db_index=True)
    score = models.FloatField()
    status = models.CharField(max_length=8, choices=Status.choices)
    payload = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        "tenants.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_qa_results",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dataruns"
        db_table = "workflow_qa_results"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["company", "package", "-created_at"],
                name="wf_qa_co_pkg_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"QA {self.use_case_id} {self.status} ({self.score}) @ {self.id}"


class HandoffPackage(models.Model):
    """Staged handoff package after QA PASS (PRD-HO-01 / pack handoff_package.schema.json).

    Idempotent on (company, package, qa_result). HO-01 emits status=STAGED;
    HO-02 transitions via ``activation_meta`` + status column.
    """

    class Status(models.TextChoices):
        STAGED = "STAGED", "STAGED"
        APPROVED_FOR_ACTIVATION = (
            "APPROVED_FOR_ACTIVATION",
            "APPROVED_FOR_ACTIVATION",
        )
        REJECTED = "REJECTED", "REJECTED"
        ACTIVATED = "ACTIVATED", "ACTIVATED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        related_name="handoff_packages",
    )
    package = models.ForeignKey(
        WorkflowBuildPackage,
        on_delete=models.CASCADE,
        related_name="handoffs",
    )
    qa_result = models.ForeignKey(
        WorkflowQaResult,
        on_delete=models.CASCADE,
        related_name="handoffs",
    )
    use_case_id = models.CharField(max_length=16, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.STAGED,
    )
    payload = models.JSONField(default=dict)
    activation_meta = models.JSONField(default=dict, blank=True)
    manifest_hash = models.CharField(max_length=64, db_index=True)
    created_by = models.ForeignKey(
        "tenants.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handoff_packages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dataruns"
        db_table = "handoff_packages"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "package", "qa_result"],
                name="handoff_pkg_co_pkg_qa_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "package", "-created_at"],
                name="handoff_co_pkg_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Handoff {self.use_case_id} {self.status} @ {self.id}"

    @property
    def handoff_id(self) -> str:
        return str(self.id)
