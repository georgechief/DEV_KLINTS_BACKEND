"""Approval token errors (BL-017)."""

from __future__ import annotations


class ApprovalTokenError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class ApprovalTokenNotFound(ApprovalTokenError):
    def __init__(self) -> None:
        super().__init__("approval_not_found", "Approval token not found.")


class ApprovalJobNotFound(ApprovalTokenError):
    def __init__(self) -> None:
        super().__init__("writeback_job_not_found", "Writeback preview job not found.")
