"""Excel sheet 02/06 product catalog join for DCS scoring (PRD-DCS-04 batch 4c).

Surfaces:
- Manago event ``products`` (comma-separated IDs on PURCHASE/CART)
- Manago ``product_catalogs`` (v3 catalogList) + ``products`` (XML feed when configured)
- Shopify ``products`` (status=active) with variants; line_items as fallback

KNOWN LIMITATION: Manago catalog *entries* require ``product_feed_url`` and/or
``api_v3_key`` on the Manago connector. Without them PT-03 (and Manago-side
PT-01 catalog resolve) stay UNKNOWN — intentional, not incomplete check code.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dataruns.dcs.lifecycle_join import _latest_connector_raw
from tenants.models import Company

PT_SAMPLE = 50
_PURCHASE_CART = frozenset({"PURCHASE", "TRANSACTION", "CART", "CART_UPDATE", "ADD_TO_CART"})


def _split_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for item in raw:
            out.extend(_split_ids(item))
        return out
    text = str(raw).strip()
    if not text:
        return []
    return [p.strip() for p in text.split(",") if p.strip()]


def build_catalog_snapshot(*, company: Company) -> dict[str, Any]:
    shopify_raw = _latest_connector_raw(company=company, platform="shopify")
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")
    orders = [o for o in (shopify_raw.get("orders") or []) if isinstance(o, dict)]
    shopify_products_raw = [
        p for p in (shopify_raw.get("products") or []) if isinstance(p, dict)
    ]
    transactions = [
        t for t in (manago_raw.get("transactions") or []) if isinstance(t, dict)
    ]
    events = [e for e in (manago_raw.get("events") or []) if isinstance(e, dict)]
    manago_catalogs = [
        c for c in (manago_raw.get("product_catalogs") or []) if isinstance(c, dict)
    ]
    manago_products_raw = [
        p for p in (manago_raw.get("products") or []) if isinstance(p, dict)
    ]

    # Shopify active products (preferred) + variants.
    shopify_variants: dict[str, dict[str, Any]] = {}
    shopify_products: dict[str, dict[str, Any]] = {}
    shopify_from_products_api = bool(shopify_products_raw)
    for prod in shopify_products_raw:
        pid = prod.get("id")
        if pid is None:
            continue
        sid = str(pid)
        status = str(prod.get("status") or "active").lower()
        if status and status != "active":
            continue
        title = str(prod.get("title") or "")
        shopify_products[sid] = {
            "product_id": sid,
            "title": title,
            "status": "active",
            "sku": "",
            "variant_ids": [],
        }
        for variant in prod.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            vid = variant.get("id")
            if vid is None:
                continue
            vkey = str(vid)
            shopify_variants[vkey] = {
                "variant_id": vkey,
                "product_id": sid,
                "sku": str(variant.get("sku") or ""),
                "title": str(variant.get("title") or title),
            }
            shopify_products[sid]["variant_ids"].append(vkey)
            if not shopify_products[sid]["sku"] and variant.get("sku"):
                shopify_products[sid]["sku"] = str(variant.get("sku"))

    # Fallback: line items when products.json not available.
    if not shopify_products:
        for order in orders:
            if order.get("test") is True:
                continue
            for li in order.get("line_items") or []:
                if not isinstance(li, dict):
                    continue
                vid = li.get("variant_id")
                pid = li.get("product_id")
                sku = str(li.get("sku") or "")
                title = str(li.get("title") or li.get("name") or "")
                if vid is not None:
                    shopify_variants[str(vid)] = {
                        "variant_id": str(vid),
                        "product_id": str(pid) if pid is not None else None,
                        "sku": sku,
                        "title": title,
                    }
                if pid is not None:
                    shopify_products[str(pid)] = {
                        "product_id": str(pid),
                        "sku": sku,
                        "title": title,
                        "status": "active",
                        "variant_ids": [],
                    }

    # Manago catalog products (XML feed / future list API).
    manago_catalog: dict[str, dict[str, Any]] = {}
    for prod in manago_products_raw:
        pid = (
            prod.get("productId")
            or prod.get("product_id")
            or prod.get("id")
            or prod.get("sku")
        )
        if pid is None:
            continue
        key = str(pid)
        active = prod.get("active")
        available = prod.get("available")
        manago_catalog[key] = {
            "product_id": key,
            "name": prod.get("name") or prod.get("title") or "",
            "sku": prod.get("sku") or "",
            "active": active if active is not None else True,
            "available": available,
            "margin": prod.get("margin"),
            "price": prod.get("price"),
            "attribute_empty": not bool(
                (prod.get("name") or prod.get("title") or prod.get("sku"))
            ),
        }
    manago_catalog_available = bool(manago_catalog)
    manago_catalog_meta_available = bool(manago_catalogs)

    # Event product IDs (Excel PT-01).
    event_product_refs: list[dict[str, Any]] = []
    ref_counts: dict[str, int] = defaultdict(int)

    def _consume_event(event: dict[str, Any], *, default_type: str) -> None:
        etype = str(event.get("contactExtEventType") or default_type).upper()
        if etype not in _PURCHASE_CART:
            return
        ids = _split_ids(event.get("products"))
        if not ids:
            return
        for pid in ids:
            ref_counts[pid] += 1
            event_product_refs.append(
                {
                    "product_id": pid,
                    "event_type": etype,
                    "event_id": str(
                        event.get("eventId") or event.get("transactionId") or ""
                    ),
                    "external_id": str(event.get("externalId") or ""),
                    "contact_id": str(event.get("contactId") or ""),
                    "location": event.get("location") or event.get("shopDomain"),
                }
            )

    for event in transactions:
        _consume_event(event, default_type="PURCHASE")
    for event in events:
        _consume_event(event, default_type="")

    unique_event_ids = set(ref_counts)
    # Prefer Manago catalog; else Shopify variants then products (Excel shopify surface).
    resolve_target = "manago_catalog"
    catalog_ids = set(manago_catalog)
    if not catalog_ids:
        resolve_target = "shopify_variants"
        catalog_ids = set(shopify_variants)
    if not catalog_ids:
        resolve_target = "shopify_products"
        catalog_ids = set(shopify_products)

    dangling = sorted(unique_event_ids - catalog_ids)
    resolved = sorted(unique_event_ids & catalog_ids)
    dangling_rate = round(len(dangling) / max(len(unique_event_ids), 1), 4)

    # PT-03: active Shopify vs Manago catalog entries.
    shopify_active = set(shopify_products)
    manago_ids = set(manago_catalog)
    missing_in_manago = (
        sorted(shopify_active - manago_ids) if manago_catalog_available else []
    )
    surplus_in_manago = (
        sorted(manago_ids - shopify_active) if manago_catalog_available else []
    )
    attribute_empty = [
        row["product_id"]
        for row in manago_catalog.values()
        if row.get("attribute_empty")
    ]
    # Also treat missing name+sku as empty.
    for row in manago_catalog.values():
        if not (row.get("name") or row.get("sku")) and row["product_id"] not in attribute_empty:
            attribute_empty.append(row["product_id"])

    margin_populated = sum(
        1
        for row in manago_catalog.values()
        if row.get("margin") not in (None, "", 0, "0")
    )

    return {
        "products": list(shopify_products.values())[:500],
        "catalog": {
            "manago_catalog_available": manago_catalog_available,
            "manago_catalog_meta_available": manago_catalog_meta_available,
            "manago_catalog_count": len(manago_catalog),
            "manago_catalog_list_count": len(manago_catalogs),
            "manago_catalogs": [
                {
                    "catalogId": c.get("catalogId"),
                    "name": c.get("name"),
                    "location": c.get("location"),
                    "currency": c.get("currency"),
                    "setAsDefault": c.get("setAsDefault"),
                }
                for c in manago_catalogs[:20]
            ],
            "shopify_products_from_api": shopify_from_products_api,
            "shopify_products_from_line_items": (
                0 if shopify_from_products_api else len(shopify_products)
            ),
            "shopify_active_product_count": len(shopify_products),
            "shopify_variants_from_line_items": len(shopify_variants),
            "event_product_id_refs": len(event_product_refs),
            "unique_event_product_ids": len(unique_event_ids),
            "resolve_target": resolve_target,
            "resolved_count": len(resolved),
            "dangling_count": len(dangling),
            "dangling_rate": dangling_rate,
            "dangling_sample": [
                {"product_id": pid, "ref_count": ref_counts[pid]}
                for pid in dangling[:PT_SAMPLE]
            ],
            "pt03": {
                "shopify_active_count": len(shopify_active),
                "manago_catalog_count": len(manago_ids),
                "missing_in_manago": len(missing_in_manago),
                "surplus_in_manago": len(surplus_in_manago),
                "attribute_empty": len(attribute_empty),
                "missing_sample": missing_in_manago[:PT_SAMPLE],
                "surplus_sample": surplus_in_manago[:PT_SAMPLE],
                "attribute_empty_sample": attribute_empty[:PT_SAMPLE],
            },
            "margin": {
                "manago_products": len(manago_catalog),
                "margin_populated": margin_populated,
                "margin_unknown": max(len(manago_catalog) - margin_populated, 0),
                "margin_share": round(
                    margin_populated / max(len(manago_catalog), 1), 4
                ),
            },
            "raw_enrichment": {
                "shopify_products_api_present": shopify_from_products_api,
                "shopify_line_items_present": bool(shopify_products or shopify_variants),
                "manago_event_products_present": bool(unique_event_ids),
                "manago_catalog_present": manago_catalog_available,
                "manago_catalog_meta_present": manago_catalog_meta_available,
                "catalog_fetch_note": manago_raw.get("catalog_fetch_note"),
                "products_fetch_note": manago_raw.get("products_fetch_note"),
                "shopify_products_fetch_error": shopify_raw.get("products_fetch_error"),
            },
        },
    }
