from django.apps import AppConfig


class DatarunsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dataruns"
    verbose_name = "Data Runs"

    def ready(self) -> None:
        # Register Architecture Assessment models (PRD-AF-01).
        from dataruns.architecture import models as _architecture_models  # noqa: F401
