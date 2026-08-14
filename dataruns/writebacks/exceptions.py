"""Writeback-specific exceptions."""

from __future__ import annotations


class DiffHashMismatchError(Exception):
    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"diff_hash mismatch: expected {expected}, got {actual}")
