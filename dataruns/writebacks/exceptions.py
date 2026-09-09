"""Writeback-specific exceptions."""

from __future__ import annotations


class DiffHashMismatchError(Exception):
    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"diff_hash mismatch: expected {expected}, got {actual}")


class WritebackAlreadyExecutedForRunError(Exception):
    """PRD-WB-04 / WB-07 — successful or in-flight execute for check per DCS data_run."""

    def __init__(
        self,
        *,
        check_id: str,
        data_run_id: int,
        execute_job_id: str,
    ) -> None:
        self.check_id = check_id
        self.data_run_id = data_run_id
        self.execute_job_id = execute_job_id
        self.code = "writeback_already_executed_for_run"
        super().__init__(
            "Writeback already executed for this check on the current Data Consistency Score."
        )


class WritebackDcsRunRequiredError(Exception):
    """PRD-WB-07 §3.4 — execute denied when no terminal DCS score run exists."""

    def __init__(self) -> None:
        self.code = "dcs_run_required"
        super().__init__(
            "Run a Data Consistency Score before approving writebacks."
        )
