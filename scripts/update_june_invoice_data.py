#!/usr/bin/env python3
"""Update the dashboard dataset with June 2026 invoice spend."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_invoice_data as invoice_builder
import build_june_unmatched_invoice_report as june_report


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
JSON_OUT = DATA_DIR / "invoices.json"
JS_OUT = DATA_DIR / "invoices.js"
MONTH = "2026-06"
REPLACED_PLATFORMS = {"Meta", "Google Ads", "Google Cloud"}


def month_of(item: dict[str, Any]) -> str:
    return str(item.get("month") or item.get("invoiceDate") or "")[:7]


def is_replaced_june_item(item: dict[str, Any]) -> bool:
    return month_of(item) == MONTH and str(item.get("platform", "")).strip() in REPLACED_PLATFORMS


def update_unique_sorted(existing: list[str], discovered: set[str], preferred: list[str]) -> list[str]:
    values = set(str(item).strip() for item in existing if str(item).strip())
    values.update(item for item in discovered if item)
    ordered = [item for item in preferred if item in values]
    ordered.extend(sorted(values - set(ordered)))
    return ordered


def main() -> None:
    if not JSON_OUT.exists():
        raise FileNotFoundError(f"Missing dataset: {JSON_OUT}")

    data = json.loads(JSON_OUT.read_text(encoding="utf-8"))
    reason_social_mappings, campaign_desglose_mappings = june_report.load_mappings()
    june_invoices, warnings = june_report.parse_june_invoices()
    june_source_rows = invoice_builder.build_reason_social_rows(
        june_invoices,
        reason_social_mappings,
        campaign_desglose_mappings,
        {},
    )
    june_source_rows = [row for row in june_source_rows if is_replaced_june_item(row)]
    june_rows = june_report.expanded_rows(june_source_rows)

    for row in june_rows:
        if str(row.get("platform", "")).strip() == "Meta":
            row["chargeAmountValidation"] = "Pendiente cartola TC junio completa"
        elif str(row.get("chargeAmountValidation", "")).strip() == "Sin match":
            row["chargeAmountValidation"] = "Pendiente cartola TC junio completa"

    carried_invoices = [
        item for item in data.get("invoices", []) if not is_replaced_june_item(item)
    ]
    carried_rows = [
        item for item in data.get("reasonSocialRows", []) if not is_replaced_june_item(item)
    ]

    invoices = [*carried_invoices, *june_invoices]
    reason_social_rows = [*carried_rows, *june_rows]

    data["generatedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["invoices"] = invoices
    data["reasonSocialRows"] = reason_social_rows
    data["brands"] = update_unique_sorted(
        data.get("brands", []),
        {str(item.get("brand", "")).strip() for item in invoices},
        ["Almagro Inmobiliaria", "Almagro Propiedades", "Socovesa", "Pilares"],
    )
    data["platforms"] = update_unique_sorted(
        data.get("platforms", []),
        {str(item.get("platform", "")).strip() for item in invoices},
        ["Meta", "Google Ads", "Agencia Zeppelin"],
    )

    DATA_DIR.mkdir(exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    JS_OUT.write_text(
        "window.INVOICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    invoice_total = sum(int(item.get("totalAmount", 0) or 0) for item in june_invoices)
    row_total = sum(int(item.get("amount", 0) or 0) for item in june_rows)
    unassigned_total = sum(
        int(item.get("amount", 0) or 0)
        for item in june_rows
        if str(item.get("legalEntity", "")).strip() == "Sin asignar"
    )
    print(f"June invoices: {len(june_invoices)}")
    print(f"June invoice total: {invoice_total}")
    print(f"June reason-social rows: {len(june_rows)}")
    print(f"June reason-social total: {row_total}")
    print(f"June unassigned total: {unassigned_total}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning.source}: {warning.message}")


if __name__ == "__main__":
    main()
