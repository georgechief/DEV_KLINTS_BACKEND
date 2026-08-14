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
