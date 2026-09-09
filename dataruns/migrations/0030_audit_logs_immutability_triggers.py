"""PRD-POLISH-01 §2 — Postgres triggers: audit_logs append-only (audit_read mutable)."""

from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION audit_logs_enforce_immutability()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id THEN
        NEW.id := OLD.id;
    END IF;
    IF NEW.company_id IS DISTINCT FROM OLD.company_id THEN
        NEW.company_id := OLD.company_id;
    END IF;
    IF NEW.run_id IS DISTINCT FROM OLD.run_id THEN
        NEW.run_id := OLD.run_id;
    END IF;
    IF NEW.action IS DISTINCT FROM OLD.action THEN
        NEW.action := OLD.action;
    END IF;
    IF NEW.tone IS DISTINCT FROM OLD.tone THEN
        NEW.tone := OLD.tone;
    END IF;
    IF NEW.summary IS DISTINCT FROM OLD.summary THEN
        NEW.summary := OLD.summary;
    END IF;
    IF NEW.performed_by IS DISTINCT FROM OLD.performed_by THEN
        NEW.performed_by := OLD.performed_by;
    END IF;
    IF NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id THEN
        NEW.actor_user_id := OLD.actor_user_id;
    END IF;
    IF NEW.metadata IS DISTINCT FROM OLD.metadata THEN
        NEW.metadata := OLD.metadata;
    END IF;
    IF NEW.prev_hash IS DISTINCT FROM OLD.prev_hash THEN
        NEW.prev_hash := OLD.prev_hash;
    END IF;
    IF NEW.entry_hash IS DISTINCT FROM OLD.entry_hash THEN
        NEW.entry_hash := OLD.entry_hash;
    END IF;
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        NEW.created_at := OLD.created_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_logs_forbid_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs rows cannot be deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_enforce_immutability_trigger ON audit_logs;
CREATE TRIGGER audit_logs_enforce_immutability_trigger
    BEFORE UPDATE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION audit_logs_enforce_immutability();

DROP TRIGGER IF EXISTS audit_logs_forbid_delete_trigger ON audit_logs;
CREATE TRIGGER audit_logs_forbid_delete_trigger
    BEFORE DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION audit_logs_forbid_delete();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_logs_forbid_delete_trigger ON audit_logs;
DROP TRIGGER IF EXISTS audit_logs_enforce_immutability_trigger ON audit_logs;
DROP FUNCTION IF EXISTS audit_logs_forbid_delete();
DROP FUNCTION IF EXISTS audit_logs_enforce_immutability();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0029_writeback_job_dcs_run_gate"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
