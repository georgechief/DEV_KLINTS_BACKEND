"""Write adapter protocol (PRD-WB-01 §2.1)."""

from __future__ import annotations

from typing import Protocol

from dataruns.writebacks.types import WriteIntent
from tenants.models import Company


class WriteAdapter(Protocol):
    target: str

    def dry_run(self, company: Company, intents: list[WriteIntent]) -> list[WriteIntent]: ...

    def execute(
        self,
        company: Company,
        intents: list[WriteIntent],
        *,
        approval_id: str | None,
        idempotency_key: str | None,
    ) -> list[WriteIntent]: ...
