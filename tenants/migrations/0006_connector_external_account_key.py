from collections import defaultdict

from django.db import migrations, models


OWNING_STATUSES = ("connected", "degraded")


def _resolve_external_account_key(connector, ConnectorSnapshot):
    """Derive canonical external_account_key from snapshots/config (idempotent)."""
    if connector.name == "shopify":
        snapshot = (
            ConnectorSnapshot.objects.filter(connector_id=connector.id)
            .order_by("-version")
            .first()
        )
        shop_domain = None
        if snapshot is not None:
            shop_domain = (snapshot.snapshot_data or {}).get("shop_domain")
        if not shop_domain:
            shop_domain = (connector.config or {}).get("shop_domain")
        if isinstance(shop_domain, str) and shop_domain.strip():
            key = shop_domain.strip().lower()
            if not key.endswith(".myshopify.com"):
                key = f"{key}.myshopify.com"
            return key
        return None

    if connector.name == "manago_ai":
        snapshot = (
            ConnectorSnapshot.objects.filter(connector_id=connector.id)
            .order_by("-version")
            .first()
        )
        workspace_id = None
        if snapshot is not None:
            data = snapshot.snapshot_data or {}
            workspace_id = data.get("workspace_id") or data.get("client_id")
        if not workspace_id:
            config = connector.config or {}
            workspace_id = config.get("workspace_id") or config.get("client_id")
        if isinstance(workspace_id, str) and workspace_id.strip():
            return workspace_id.strip()
        return None

    return None


def _backfill_external_account_keys(apps, schema_editor):
    Connector = apps.get_model("tenants", "Connector")
    ConnectorSnapshot = apps.get_model("tenants", "ConnectorSnapshot")

    for connector in Connector.objects.filter(
        status__in=OWNING_STATUSES,
        external_account_key__isnull=True,
    ):
        key = _resolve_external_account_key(connector, ConnectorSnapshot)
        if key:
            connector.external_account_key = key
            connector.save(update_fields=["external_account_key", "updated_at"])


def _dedupe_external_account_keys(apps, schema_editor):
    """
    Before the partial unique index, ensure at most one owning connector per key.

    Keeps the oldest row (created_at, then pk) and clears external_account_key on
    all later duplicates. Idempotent: re-running leaves data unchanged.
    """
    Connector = apps.get_model("tenants", "Connector")

    candidates = list(
        Connector.objects.filter(
            status__in=OWNING_STATUSES,
            external_account_key__isnull=False,
        )
        .exclude(external_account_key="")
        .order_by("external_account_key", "created_at", "pk")
    )

    by_key: dict[str, list] = defaultdict(list)
    for connector in candidates:
        by_key[connector.external_account_key].append(connector)

    for connectors in by_key.values():
        if len(connectors) <= 1:
            continue
        for duplicate in connectors[1:]:
            if duplicate.external_account_key is not None:
                duplicate.external_account_key = None
                duplicate.save(update_fields=["external_account_key", "updated_at"])


def _ensure_no_index_duplicates(apps, schema_editor):
    """
    Final safety pass: null any key that still collides among owning connectors.

    Handles rows backfilled in a prior partial run before dedupe existed.
    """
    _dedupe_external_account_keys(apps, schema_editor)

    Connector = apps.get_model("tenants", "Connector")
    remaining = (
        Connector.objects.filter(
            status__in=OWNING_STATUSES,
            external_account_key__isnull=False,
        )
        .exclude(external_account_key="")
        .values_list("external_account_key", flat=True)
    )
    seen: set[str] = set()
    for key in remaining:
        if key in seen:
            raise RuntimeError(
                f"Duplicate external_account_key {key!r} remains after dedupe; "
                "cannot create uniq_connectors_external_account_key_owner."
            )
        seen.add(key)


class Migration(migrations.Migration):
    # Dedupe RunPython updates rows; PostgreSQL rejects CREATE INDEX in the
    # same transaction while those row updates have pending trigger events.
    atomic = False

    dependencies = [
        ("tenants", "0005_password_reset_token"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="connector",
                    name="external_account_key",
                    field=models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE connectors "
                        "ADD COLUMN IF NOT EXISTS external_account_key "
                        "varchar(255) NULL;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE connectors "
                        "DROP COLUMN IF EXISTS external_account_key;"
                    ),
                ),
            ],
        ),
        migrations.RunPython(
            _backfill_external_account_keys,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            _dedupe_external_account_keys,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            _ensure_no_index_duplicates,
            migrations.RunPython.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="connector",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("external_account_key__isnull", False),
                            ("status__in", OWNING_STATUSES),
                        ),
                        fields=("external_account_key",),
                        name="uniq_connectors_external_account_key_owner",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "uniq_connectors_external_account_key_owner "
                        "ON connectors (external_account_key) "
                        "WHERE external_account_key IS NOT NULL "
                        "AND status IN ('connected', 'degraded');"
                    ),
                    reverse_sql=(
                        "DROP INDEX IF EXISTS "
                        "uniq_connectors_external_account_key_owner;"
                    ),
                ),
            ],
        ),
    ]
