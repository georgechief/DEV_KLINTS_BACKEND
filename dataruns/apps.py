from django.apps import AppConfig


class DatarunsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dataruns"
    verbose_name = "Data Runs"

    def ready(self) -> None:
        # Register Architecture Assessment models (PRD-AF-01).
        from dataruns.architecture import models as _architecture_models  # noqa: F401
        # Register Use Case / QA / Handoff models (PRD-UC-01 / QA-01 / HO-01).
        from dataruns.use_cases import models as _use_case_models  # noqa: F401
        # Register persisted orchestration tasks (PRD-GAP-01 Slice A1).
        from dataruns.orchestration import models as _orchestration_task_models  # noqa: F401
