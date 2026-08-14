from django.contrib import admin

from dataruns.models import DataRun, WritebackApprovalToken, WritebackJob


@admin.register(DataRun)
class DataRunAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "status", "created_at", "finished_at")
    list_filter = ("status", "tenant")
    search_fields = ("name", "tenant__name", "tenant__slug")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("tenant",)


@admin.register(WritebackJob)
class WritebackJobAdmin(admin.ModelAdmin):
    list_display = (
        "check_id",
        "company",
        "mode",
        "status",
        "sandbox",
        "created_at",
    )
    list_filter = ("mode", "status", "sandbox", "check_id")
    search_fields = ("check_id", "diff_hash", "company__name")
    readonly_fields = ("created_at",)
    raw_id_fields = ("company", "actor_user")


@admin.register(WritebackApprovalToken)
class WritebackApprovalTokenAdmin(admin.ModelAdmin):
    list_display = (
        "object_id",
        "company",
        "status",
        "approval_tier_display",
        "issued_at",
        "expires_at",
    )
    list_filter = ("status",)
    search_fields = ("object_id", "diff_hash", "company__name")
    readonly_fields = ("created_at",)
    raw_id_fields = ("company", "writeback_job", "actor_user", "approver_user")

    @admin.display(description="Approval tier")
    def approval_tier_display(self, obj: WritebackApprovalToken) -> str:
        metadata = obj.metadata if isinstance(obj.metadata, dict) else {}
        return str(metadata.get("approval_tier") or "")
