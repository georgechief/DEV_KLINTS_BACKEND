# M3-SEC-01 — Audit evidence (Phase 4)

**PRD:** [PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md](../sahil/PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md)  
**Audience:** Security review packet §5 (Phase 5 embeds / links this)  
**Claim level:** Runtime hash-chain + DB immutability triggers evidenced by tests — **not** pen-test / SOC2 / DP1.

---

## What exists

| Control | Location |
|---------|----------|
| Append-only hash chain helper | `dataruns/audit.py` → `verify_audit_chain_for_company` |
| Management command | `python manage.py verify_audit_chain --company-id <uuid>` |
| Postgres immutability triggers | `dataruns/migrations/0030_audit_logs_immutability_triggers.py` |
| Hash + sanitize unit/API tests | `dataruns/tests/test_audit.py` |
| Trigger / tamper immutability tests | `dataruns/tests/test_audit_immutability.py` |

`audit_read` remains mutable (mark-read); hash fields and business columns are protected by triggers.

---

## How to verify a company chain

```bash
python manage.py verify_audit_chain --company-id <COMPANY_UUID>
```

Exit **0** + success message → chain OK. Non-zero → printed error lines (broken link / hash mismatch).

Programmatic:

```python
from dataruns.audit import verify_audit_chain_for_company
errors = verify_audit_chain_for_company(company=company)  # [] means OK
```

---

## Test evidence (do not rebuild)

| Assertion | Test |
|-----------|------|
| Genesis + linked hashes | `test_audit.py` (`test_genesis_hash_on_first_entry`, `test_second_entry_links_prev_hash`) |
| `call_command("verify_audit_chain", …)` | `test_audit.py::test_verify_audit_chain_passes` |
| Metadata secret strip | `test_audit.py::test_sanitize_metadata_strips_secrets` |
| Company isolation list / mark-read | `test_audit.py` isolation cases |
| ORM/SQL tamper reverted; delete blocked | `test_audit_immutability.py` |
| Mark-read does not break chain | `test_audit.py` + `test_audit_immutability.py` |

---

## Secret / metadata hygiene (PRD §5.7)

| Control | Evidence |
|---------|----------|
| Connector secrets masked in API responses | `tenants/crypto.py` `SECRET_CONFIG_FIELDS` + `masked_config`; `test_manago_api_v3_key.py` |
| Audit metadata sanitization | `test_audit.py::test_sanitize_metadata_strips_secrets` |

---

## Residual (honest)

- Multi-company-per-tenant: `get_user_company` = first company by `created_at` (not productized).
- Command is **ops/manual** — not claimed as continuous monitoring / SIEM.
- Grafana/Loki (M3-OBS-01) is observability, **not** audit integrity.
