"""Stable diff hashing for writeback previews (BL-017 token_binds)."""

from __future__ import annotations

import hashlib

from dataruns.audit import stable_json
from dataruns.writebacks.types import WriteIntent


def compute_diff_hash(intents: list[WriteIntent]) -> str:
    payload = [intent.to_hash_dict() for intent in intents if intent.status != "error"]
    canonical = stable_json({"intents": payload})
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
