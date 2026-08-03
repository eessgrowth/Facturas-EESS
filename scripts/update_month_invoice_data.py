#!/usr/bin/env python3
"""Incrementally add one month of Google and Meta invoices to the dashboard."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_invoice_data as invoice_builder
import build_june_unmatched_invoice_report as report_helpers


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
JSON_OUT = DATA_DIR / "invoices.json"
JS_OUT = DATA_DIR / "invoices.js"
REPLACED_PLATFORMS = {"Meta", "Google Ads", "Google Cloud"}
MONTH_FOLDER_NAMES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="Month in YYYY-MM format")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate without writing files")
    parser.add_argument(
        "--allow-unassigned",
        action="store_true",
        help="Write the dataset even when assignments are missing",
    )
    return parser.parse_args()


def month_folder(month: str) -> str:
    year_text, month_text = month.split("-", 1)
    month_number = int(month_text)
    if month_number not in MONTH_FOLDER_NAMES:
        raise ValueError(f"Invalid month: {month}")
    return f"{MONTH_FOLDER_NAMES[month_number]}_{int(year_text):04d}"


def month_label(month: str) -> str:
    year_text, month_text = month.split("-", 1)
    return f"{MONTH_FOLDER_NAMES[int(month_text)]}_{int(year_text):04d}"


def month_of(item: dict[str, Any]) -> str:
    return str(item.get("month") or item.get("invoiceDate") or "")[:7]


def is_replaced_item(item: dict[str, Any], month: str) -> bool:
    return month_of(item) == month and str(item.get("platform", "")).strip() in REPLACED_PLATFORMS


def update_unique_sorted(existing: list[str], discovered: set[str], preferred: list[str]) -> list[str]:
    values = {str(item).strip() for item in existing if str(item).strip()}
    values.update(item for item in discovered if item)
    ordered = [item for item in preferred if item in values]
    ordered.extend(sorted(values - set(ordered)))
    return ordered


def parse_month_invoices(
    month: str,
) -> tuple[list[dict[str, Any]], list[invoice_builder.ParseWarning]]:
    warnings: list[invoice_builder.ParseWarning] = []
    invoices: list[dict[str, Any]] = []
    folder_name = month_folder(month)

    for file in sorted((ROOT / "Facturas Google").glob(f"*/{folder_name}/*.pdf")):
        invoice = invoice_builder.parse_google_invoice(file, warnings)
        if month_of(invoice) == month:
            invoices.append(invoice)

    invoices.extend(
        invoice
        for invoice in invoice_builder.parse_meta_receipt_folders(
            ROOT / "Facturas Meta", warnings, month_filter=month
        )
        if month_of(invoice) == month
    )
    return sorted(
        invoices,
        key=lambda item: (item.get("platform", ""), item.get("brand", ""), item.get("invoiceDate", "")),
    ), warnings


def write_reports(month: str, rows: list[dict[str, Any]], invoices: list[dict[str, Any]], warnings: list[Any]) -> None:
    prefix = f"{month_label(month)}_facturas_sin_match"
    detail_fields = [
        "month",
        "platform",
        "brand",
        "legalEntity",
        "comuna",
        "project",
        "pepCode",
        "campaignName",
        "amount",
        "invoiceId",
        "invoiceDate",
        "paymentDate",
        "paymentReference",
        "referenceId",
        "referenceType",
        "chargeAmountValidation",
        "matched",
        "mappingBrand",
        "cartolaMatchStatus",
    ]
    report_helpers.write_csv(REPORTS_DIR / f"{prefix}_desglose.csv", rows, detail_fields)

    project_keys = ["platform", "brand", "legalEntity", "comuna", "project", "pepCode"]
    report_helpers.write_csv(
        REPORTS_DIR / f"{prefix}_resumen_proyecto.csv",
        report_helpers.summarize(rows, project_keys),
        [*project_keys, "amount"],
    )
    legal_keys = ["platform", "legalEntity"]
    report_helpers.write_csv(
        REPORTS_DIR / f"{prefix}_resumen_razon_social.csv",
        report_helpers.summarize(rows, legal_keys),
        [*legal_keys, "amount"],
    )
    unassigned = [
        row
        for row in rows
        if str(row.get("legalEntity", "")).strip() == "Sin asignar"
        or str(row.get("project", "")).strip() == "Sin asignar"
    ]
    report_helpers.write_csv(
        REPORTS_DIR / f"{prefix}_sin_asignar.csv",
        unassigned,
        detail_fields,
    )

    invoice_total = sum(int(invoice.get("totalAmount", 0) or 0) for invoice in invoices)
    row_total = sum(int(row.get("amount", 0) or 0) for row in rows)
    platform_totals = report_helpers.summarize(rows, ["platform"])
    summary = [
        f"Reporte {month} facturas sin match de cartola",
        f"Facturas parseadas: {len(invoices)}",
        f"Total facturas: {invoice_total}",
        f"Total desglose asignado: {row_total}",
        f"Filas detalle: {len(rows)}",
        f"Filas sin asignar: {len(unassigned)}",
        "",
        "Totales por plataforma:",
    ]
    summary.extend(f"- {row['platform']}: {row['amount']}" for row in platform_totals)
    if warnings:
        summary.extend(["", "Warnings:"])
        summary.extend(f"- {warning.source}: {warning.message}" for warning in warnings)
    (REPORTS_DIR / f"{prefix}_resumen.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    month = args.month
    if not JSON_OUT.exists():
        raise FileNotFoundError(f"Missing dataset: {JSON_OUT}")

    data = json.loads(JSON_OUT.read_text(encoding="utf-8"))
    invoices, warnings = parse_month_invoices(month)
    if not invoices:
        raise RuntimeError(f"No Google or Meta invoices found for {month}")

    source_rows = invoice_builder.build_reason_social_rows(
        invoices,
        data.get("reasonSocialMappings", []),
        data.get("campaignDesgloseMappings", []),
        {},
    )
    source_rows = [row for row in source_rows if is_replaced_item(row, month)]
    spanish_month = MONTH_FOLDER_NAMES[int(month[5:7])]
    rows = report_helpers.expanded_rows(
        source_rows,
        month=month,
        cartola_status=f"Pendiente cartola TC {spanish_month} completa",
    )

    invoice_total = sum(int(invoice.get("totalAmount", 0) or 0) for invoice in invoices)
    row_total = sum(int(row.get("amount", 0) or 0) for row in rows)
    unassigned = [
        row
        for row in rows
        if str(row.get("legalEntity", "")).strip() == "Sin asignar"
        or str(row.get("project", "")).strip() == "Sin asignar"
    ]
    platform_totals = Counter()
    for row in rows:
        platform_totals[str(row.get("platform", ""))] += int(row.get("amount", 0) or 0)

    print(f"Month: {month}")
    print(f"Invoices: {len(invoices)}")
    print(f"Invoice total: {invoice_total}")
    print(f"Reason-social rows: {len(rows)}")
    print(f"Reason-social total: {row_total}")
    print(f"Unassigned rows: {len(unassigned)}")
    print(f"Unassigned total: {sum(int(row.get('amount', 0) or 0) for row in unassigned)}")
    for platform, total in sorted(platform_totals.items()):
        print(f"{platform}: {total}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning.source}: {warning.message}")
    if unassigned:
        print("Unassigned campaigns:")
        for campaign_name, count in Counter(str(row.get("campaignName", "")) for row in unassigned).most_common():
            print(f"- {campaign_name}: {count}")

    if invoice_total != row_total:
        raise RuntimeError(f"Invoice total {invoice_total} does not match row total {row_total}")
    if unassigned and not args.allow_unassigned:
        raise RuntimeError("Unassigned rows remain; add persistent mappings before updating the dataset")
    if args.dry_run:
        return

    carried_invoices = [item for item in data.get("invoices", []) if not is_replaced_item(item, month)]
    carried_rows = [item for item in data.get("reasonSocialRows", []) if not is_replaced_item(item, month)]
    merged_invoices = [*carried_invoices, *invoices]
    merged_rows = [*carried_rows, *rows]

    data["generatedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["invoices"] = merged_invoices
    data["reasonSocialRows"] = merged_rows
    data["brands"] = update_unique_sorted(
        data.get("brands", []),
        {str(item.get("brand", "")).strip() for item in merged_invoices},
        ["Almagro Inmobiliaria", "Almagro Propiedades", "Socovesa", "Pilares"],
    )
    data["platforms"] = update_unique_sorted(
        data.get("platforms", []),
        {str(item.get("platform", "")).strip() for item in merged_invoices},
        ["Meta", "Google Ads", "Agencia Zeppelin"],
    )

    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    JS_OUT.write_text(
        "window.INVOICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    write_reports(month, rows, invoices, warnings)


if __name__ == "__main__":
    main()
