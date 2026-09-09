"""Skincare vertical corpus for GAP-01F offline demo seed (W9-03)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class SkincareCorpus:
    shopify_raw: dict[str, list[dict[str, Any]]]
    manago_raw: dict[str, list[dict[str, Any]]]
    contact_count: int
    matched_count: int
    shopify_only_count: int
    manago_only_count: int
    mismatch_count: int
    manago_dup_count: int


def build_skincare_corpus(*, contacts: int, seed: int = 42) -> SkincareCorpus:
    """
    Build dual-platform raw payloads sized for offline DCS.

    Deterministic failure mix (by index) aimed at REMEDIATE (50–69):
    - 10% matched Shopify+Manago (same email/phone)
    - 55% Shopify-only (unbalance CI-01 contact counts)
    - 10% Manago-only
    - 15% email mismatch across platforms
    - 10% Manago duplicate emails (CI-03)

    ``seed`` reserved for future RNG tweaks; mix is index-stable.
    """
    if contacts < 1:
        raise ValueError("contacts must be >= 1")
    _ = seed  # reserved

    shopify_customers: list[dict[str, Any]] = []
    shopify_orders: list[dict[str, Any]] = []
    manago_contacts: list[dict[str, Any]] = []
    manago_transactions: list[dict[str, Any]] = []

    matched = shopify_only = manago_only = mismatch = manago_dup = 0
    base_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(contacts):
        bucket = i % 20  # 2/11/2/3/2 → 10% / 55% / 10% / 15% / 10%
        email = f"guest{i:05d}@skincare-demo.test"
        phone = f"+1555{i:07d}"
        shopify_id = 10_000 + i
        manago_id = f"mg-{i:05d}"
        created = (base_ts + timedelta(hours=i % 720)).strftime("%Y-%m-%dT%H:%M:%SZ")
        amount = f"{(25 + (i % 40)) + 0.5:.2f}"
        ts_ms = int((base_ts + timedelta(hours=i % 720)).timestamp() * 1000)

        if bucket < 2:  # 10% matched
            matched += 1
            shopify_customers.append(
                {
                    "id": shopify_id,
                    "email": email,
                    "phone": phone,
                    "created_at": created,
                }
            )
            shopify_orders.append(
                {
                    "id": 50_000 + i,
                    "email": email,
                    "customer": {"id": shopify_id, "email": email},
                    "total_price": amount,
                    "currency": "USD",
                    "financial_status": "paid",
                    "created_at": created,
                }
            )
            manago_contacts.append(
                {
                    "contactId": manago_id,
                    "email": email,
                    "phone": phone,
                }
            )
            # Missing externalId → LE-03 FAIL; value/count gaps vs Shopify → LE-01/02/05.
            manago_transactions.append(
                {
                    "transactionId": f"tx-{i:05d}",
                    "value": float(amount) * 0.85,
                    "currency": "USD",
                    "email": email,
                    "date": ts_ms,
                    "contactExtEventType": "PURCHASE",
                }
            )
        elif bucket < 13:  # 55% Shopify-only
            shopify_only += 1
            shopify_customers.append(
                {
                    "id": shopify_id,
                    "email": email,
                    "phone": phone,
                    "created_at": created,
                }
            )
            shopify_orders.append(
                {
                    "id": 50_000 + i,
                    "email": email,
                    "customer": {"id": shopify_id, "email": email},
                    "total_price": amount,
                    "currency": "USD",
                    "financial_status": "paid",
                    "created_at": created,
                }
            )
        elif bucket < 15:  # 10% Manago-only
            manago_only += 1
            manago_contacts.append(
                {
                    "contactId": manago_id,
                    "email": email,
                    "phone": phone,
                }
            )
            manago_transactions.append(
                {
                    "transactionId": f"tx-{i:05d}",
                    "value": float(amount),
                    "currency": "USD",
                    "email": email,
                    "date": ts_ms,
                    "contactExtEventType": "PURCHASE",
                }
            )
        elif bucket < 18:  # 15% email mismatch
            mismatch += 1
            shopify_customers.append(
                {
                    "id": shopify_id,
                    "email": email,
                    "phone": phone,
                    "created_at": created,
                }
            )
            shopify_orders.append(
                {
                    "id": 50_000 + i,
                    "email": email,
                    "customer": {"id": shopify_id, "email": email},
                    "total_price": amount,
                    "currency": "USD",
                    "financial_status": "paid",
                    "created_at": created,
                }
            )
            manago_contacts.append(
                {
                    "contactId": manago_id,
                    "email": f"drift{i:05d}@skincare-demo.test",
                    "phone": phone,
                }
            )
        else:  # 10% Manago duplicate emails (CI-03)
            manago_dup += 1
            # Pair with a prior matched-style email so clusters form at rate > 2%.
            dup_email = f"guest{(i - (i % 20)):05d}@skincare-demo.test"
            manago_contacts.append(
                {
                    "contactId": manago_id,
                    "email": dup_email,
                    "phone": phone,
                }
            )
            manago_contacts.append(
                {
                    "contactId": f"{manago_id}-b",
                    "email": dup_email,
                    "phone": f"+1556{i:07d}",
                }
            )

    return SkincareCorpus(
        shopify_raw={
            "customers": shopify_customers,
            "orders": shopify_orders,
            "transactions": [],
        },
        manago_raw={
            "contacts": manago_contacts,
            "transactions": manago_transactions,
            "events": [],
        },
        contact_count=contacts,
        matched_count=matched,
        shopify_only_count=shopify_only,
        manago_only_count=manago_only,
        mismatch_count=mismatch,
        manago_dup_count=manago_dup,
    )
