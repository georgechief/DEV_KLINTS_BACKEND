"""Architecture Assessment persistence (PRD-AF-01 §4.2)."""

from __future__ import annotations

import uuid

from django.db import models

from tenants.models import Company, Tenant


class ArchitectureAssessment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    class Mode(models.TextChoices):
        AUGMENT = "AUGMENT", "Augment"
        SELECTIVE_REBUILD = "SELECTIVE_REBUILD", "Selective rebuild"
        REBUILD = "REBUILD", "Rebuild"
        INCOMPLETE = "INCOMPLETE", "Incomplete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="architecture_assessments",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="architecture_assessments",
    )
    data_run = models.OneToOneField(
        "dataruns.DataRun",
        on_delete=models.CASCADE,
        related_name="architecture_assessment",
        help_text="AF job DataRun (metadata.kind=architecture_assessment).",
    )
    source_dcs_data_run = models.ForeignKey(
        "dataruns.DataRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="architecture_assessments_sourced",
        help_text="DCS DataRun that triggered this assessment.",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    mode = models.CharField(
        max_length=32,
        choices=Mode.choices,
        null=True,
        blank=True,
    )
    weighted_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    critical_defects = models.PositiveIntegerField(default=0)
    evidence_coverage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="0-1 coverage fraction from pack sheet 06.",
    )
    probe_coverage = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "architecture_assessments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["company", "-created_at"],
                name="af_assess_company_created_idx",
            ),
            models.Index(
                fields=["company", "status"],
                name="af_assess_company_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"AF {self.id} ({self.status})"


class ArchitectureAsset(models.Model):
    class AssetType(models.TextChoices):
        WORKFLOW = "WORKFLOW", "Workflow"
        SEGMENT = "SEGMENT", "Segment"
        TAG = "TAG", "Tag"
        PROPERTY = "PROPERTY", "Property"
        SURFACE = "SURFACE", "Surface"
        RECOMMENDATION = "RECOMMENDATION", "Recommendation"
        CHANNEL = "CHANNEL", "Channel"
        METRIC = "METRIC", "Metric"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        ArchitectureAssessment,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    asset_id = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=32, choices=AssetType.choices)
    name = models.CharField(max_length=512)
    status = models.CharField(max_length=64, blank=True, default="")
    definition = models.JSONField(default=dict, blank=True)
    lifecycle_stage = models.CharField(max_length=128, null=True, blank=True)
    capability_path = models.CharField(max_length=255, blank=True, default="")
    provenance = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "architecture_assets"
        ordering = ["asset_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "asset_id"],
                name="uniq_af_assets_assessment_asset_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["assessment", "asset_type"],
                name="af_assets_assess_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_type}:{self.asset_id}"


class ArchitectureEdge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        ArchitectureAssessment,
        on_delete=models.CASCADE,
        related_name="edges",
    )
    source_asset_id = models.CharField(max_length=255)
    target_asset_id = models.CharField(max_length=255)
    edge_type = models.CharField(max_length=64)
    rule_id = models.CharField(max_length=32, blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dataruns"
        db_table = "architecture_edges"
        indexes = [
            models.Index(
                fields=["assessment", "source_asset_id"],
                name="af_edges_src_idx",
            ),
            models.Index(
                fields=["assessment", "target_asset_id"],
                name="af_edges_tgt_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_asset_id} -{self.edge_type}-> {self.target_asset_id}"


class ArchitectureAssetVerdict(models.Model):
    class Verdict(models.TextChoices):
        KEEP = "KEEP", "Keep"
        KEEP_IMPROVE = "KEEP_IMPROVE", "Keep improve"
        FIX_FIRST = "FIX_FIRST", "Fix first"
        CONSOLIDATE = "CONSOLIDATE", "Consolidate"
        RETIRE_CANDIDATE = "RETIRE_CANDIDATE", "Retire candidate"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        ArchitectureAssessment,
        on_delete=models.CASCADE,
        related_name="asset_verdicts",
    )
    asset_id = models.CharField(max_length=255)
    verdict = models.CharField(max_length=32, choices=Verdict.choices)
    evidence_ids = models.JSONField(default=list, blank=True)
    blocked_reason = models.TextField(blank=True, default="")
    failure_code = models.CharField(max_length=64, blank=True, default="")
    dcs_check_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "architecture_asset_verdicts"
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "asset_id"],
                name="uniq_af_verdicts_assessment_asset_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id}:{self.verdict}"


class ArchitectureProbeResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        ArchitectureAssessment,
        on_delete=models.CASCADE,
        related_name="probe_results",
    )
    probe_id = models.CharField(max_length=32)
    status = models.CharField(max_length=64, blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "architecture_probe_results"
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "probe_id"],
                name="uniq_af_probes_assessment_probe_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.probe_id}:{self.status}"
