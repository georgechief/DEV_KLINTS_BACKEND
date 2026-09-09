from django.contrib import admin

from tenants.models import Company, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "tenant", "writeback_execute_enabled", "created_at")
    list_filter = ("writeback_execute_enabled",)
    search_fields = ("name", "domain", "id")
    readonly_fields = ("id", "created_at")
