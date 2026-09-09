"""Persisted orchestration tasks (PRD-GAP-01 Slice A1 / pack orchestration_task.schema.json)."""

from __future__ import annotations

import uuid

from django.db import models

from dataruns.orchestration.task_constants import ORCH_STATUS_PENDING


class OrchestrationTask(models.Model):
    """Company-scoped orchestration task with pack 8-state lifecycle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        related_name="orchestration_tasks",
    )
    task_id = models.CharField(max_length=128)
    task_type = models.CharField(max_length=32)
    status = models.CharField(
        max_length=32,
        default=ORCH_STATUS_PENDING,
    )
    title = models.CharField(max_length=512, blank=True, default="")
    check_id = models.CharField(max_length=16, blank=True, default="")
    priority_class = models.CharField(max_length=8, blank=True, default="")
    priority_inputs = models.JSONField(default=dict, blank=True)
    priority_score = models.FloatField(default=0.0)
    depends_on = models.JSONField(default=list, blank=True)
    wave = models.PositiveSmallIntegerField(default=0)
    capability_dependencies = models.JSONField(default=list, blank=True)
    approval = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=256)
    provenance = models.JSONField(default=dict, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dataruns"
        db_table = "orchestration_tasks"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                name="orch_task_co_idempotency_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "status", "-created_at"],
                name="orch_task_co_status_idx",
            ),
            models.Index(
                fields=["company", "task_type", "-created_at"],
                name="orch_task_co_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"ORCH {self.task_type} {self.task_id} {self.status} @ {self.id}"
