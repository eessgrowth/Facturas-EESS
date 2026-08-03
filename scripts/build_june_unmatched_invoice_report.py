#!/usr/bin/env python3
"""Build June 2026 invoice spend reports before full card-statement matching."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import build_invoice_data as invoice_builder


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
MONTH = "2026-06"


def load_mappings() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reason_social_mappings: list[dict[str, Any]] = []
    campaign_desglose_mappings: list[dict[str, Any]] = []
    warnings: list[invoice_builder.ParseWarning] = []

    excel_files = sorted(ROOT.glob(invoice_builder.EXCEL_PATTERN))
    if excel_files:
        for file in excel_files:
            reason_social_mappings.extend(invoice_builder.parse_reason_social_sheet(file, warnings))
            campaign_desglose_mappings.extend(invoice_builder.parse_desglose_por_rs_sheet(file, warnings))
        return reason_social_mappings, campaign_desglose_mappings

    existing_path = DATA_DIR / "invoices.json"
    if existing_path.exists():
        existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
        reason_social_mappings = existing_data.get("reasonSocialMappings", [])
        campaign_desglose_mappings = existing_data.get("campaignDesgloseMappings", [])

    return reason_social_mappings, campaign_desglose_mappings


def parse_june_invoices() -> tuple[list[dict[str, Any]], list[invoice_builder.ParseWarning]]:
    warnings: list[invoice_builder.ParseWarning] = []
    invoices: list[dict[str, Any]] = []

    for file in sorted((ROOT / "Facturas Google").glob(f"*/junio_2026/*.pdf")):
        invoices.append(invoice_builder.parse_google_invoice(file, warnings))

    meta_grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for month_dir in sorted((ROOT / "Facturas Meta").glob("*/junio_2026")):
        if not month_dir.is_dir():
            continue
        brand, account_name = invoice_builder.normalize_meta_folder_brand(month_dir.parent.name)
        key = (brand, account_name)
        if key not in meta_grouped:
            meta_grouped[key] = {
                "details": [],
                "seenTx": set(),
                "accountIds": [],
                "sourceDir": month_dir.relative_to(ROOT).as_posix(),
                "campaignTotals": defaultdict(int),
                "campaignDetails": [],
            }
        current = meta_grouped[key]
        for pdf_file in sorted(month_dir.glob("*.pdf")):
            parsed = invoice_builder.parse_meta_receipt_pdf(pdf_file, warnings, MONTH)
            if not parsed:
                continue
            tx_id = str(parsed.get("transactionId", "")).strip()
            parsed_ref = str(parsed.get("paymentReference", "")).strip().upper()
            if tx_id in current["seenTx"]:
                if parsed_ref:
                    for detail in current["details"]:
                        if detail.get("transactionId") == tx_id and not detail.get("paymentReference"):
                            detail["paymentReference"] = parsed_ref
                    for campaign_detail in current["campaignDetails"]:
                        if campaign_detail.get("transactionId") == tx_id and not campaign_detail.get("paymentReference"):
                            campaign_detail["paymentReference"] = parsed_ref
                continue

            current["seenTx"].add(tx_id)
            if parsed.get("accountId"):
                current["accountIds"].append(parsed["accountId"])
            status = str(parsed.get("status", "")).strip()
            if status == "Fondos agregados" and parsed_ref:
                status = "Pagado"
            current["details"].append(
                {
                    "date": parsed["date"],
                    "transactionId": tx_id,
                    "paymentMethod": parsed["paymentMethod"],
                    "paymentReference": parsed_ref,
                    "status": status,
                    "amount": parsed["amount"],
                    "sourceFile": parsed["sourceFile"],
                }
            )
            for campaign in parsed.get("campaigns", []):
                campaign_name = str(campaign.get("campaignName", "")).strip()
                campaign_amount = int(campaign.get("amount", 0) or 0)
                if campaign_name and campaign_amount > 0:
                    current["campaignTotals"][campaign_name] += campaign_amount
                    current["campaignDetails"].append(
                        {
                            "name": campaign_name,
                            "amount": campaign_amount,
                            "transactionId": tx_id,
                            "date": parsed["date"],
                            "paymentReference": parsed_ref,
                        }
                    )

    for (brand, account_name), values in sorted(meta_grouped.items()):
        details = sorted(values["details"], key=lambda row: row["date"], reverse=True)
        if not details:
            continue
        total_billed = sum(item["amount"] for item in details if item["status"] == "Pagado")
        total_funds = sum(item["amount"] for item in details if item["status"] == "Fondos agregados")
        campaigns = sorted(
            (
                {"name": campaign_name, "amount": amount}
                for campaign_name, amount in values["campaignTotals"].items()
                if amount > 0
            ),
            key=lambda item: (-item["amount"], item["name"]),
        )
        campaign_details = sorted(
            values["campaignDetails"],
            key=lambda item: (item.get("date", ""), item.get("transactionId", ""), item.get("name", "")),
        )
        notes = [f"Montos agregados desde comprobantes en carpeta: {values['sourceDir']}."]
        if brand == "Almagro Inmobiliaria":
            notes.append("Meta agrupa esta cuenta como ALMAGRO S A y no separa Inmobiliaria/Propiedades.")
        invoices.append(
            {
                "id": f"meta-{brand.lower().replace(' ', '-')}-{MONTH}",
                "sourceFile": values["sourceDir"],
                "pdfFile": "",
                "documentFile": "",
                "platform": "Meta",
                "brand": brand,
                "month": MONTH,
                "invoiceDate": details[0]["date"],
                "periodStart": f"{MONTH}-01",
                "periodEnd": invoice_builder.last_day_of_month(MONTH),
                "dueDate": "",
                "currency": "CLP",
                "accountName": account_name,
                "accountId": values["accountIds"][0] if values["accountIds"] else "",
                "totalAmount": total_billed,
                "summaryBreakdown": [
                    {"label": "Importe total facturado", "amount": total_billed},
                    {"label": "Total de fondos agregado", "amount": total_funds},
                ],
                "details": details,
                "campaigns": campaigns,
                "campaignDetails": campaign_details,
                "notes": notes,
            }
        )

    return sorted(invoices, key=lambda item: (item["platform"], item["brand"], item["invoiceDate"])), warnings


def expanded_rows(
    rows: list[dict[str, Any]],
    month: str = MONTH,
    cartola_status: str = "Pendiente cartola TC junio completa",
) -> list[dict[str, Any]]:
    def allocate_proportional_int(total: int, weights: list[int]) -> list[int]:
        if not weights:
            return []
        if total == 0:
            return [0 for _ in weights]
        safe_weights = [max(int(weight), 0) for weight in weights]
        weight_sum = sum(safe_weights)
        if weight_sum <= 0:
            base = total // len(weights)
            remainder = total - (base * len(weights))
            return [base + (1 if idx < remainder else 0) for idx in range(len(weights))]

        exacts = [total * weight / weight_sum for weight in safe_weights]
        base = [int(value) for value in exacts]
        missing = total - sum(base)
        remainders = sorted(
            ((exacts[idx] - base[idx], idx) for idx in range(len(base))),
            key=lambda item: (-item[0], item[1]),
        )
        for _, idx in remainders[:missing]:
            base[idx] += 1
        return base

    expanded: list[dict[str, Any]] = []
    for row in rows:
        assignments = row.get("splitAssignments", [])
        if not isinstance(assignments, list) or not assignments:
            assignments = [
                {
                    "legalEntity": row.get("legalEntity", ""),
                    "comuna": row.get("comuna", ""),
                    "project": row.get("project", ""),
                    "pepCode": row.get("pepCode", ""),
                    "amount": row.get("amount", 0),
                }
            ]

        row_amount = int(row.get("amount", 0) or 0)
        assignment_amounts = allocate_proportional_int(
            row_amount,
            [int(assignment.get("amount", 0) or 0) for assignment in assignments],
        )
        for assignment, amount in zip(assignments, assignment_amounts, strict=True):
            if amount == 0:
                continue
            expanded.append(
                {
                    "month": month,
                    "platform": row.get("platform", ""),
                    "brand": row.get("brand", ""),
                    "legalEntity": assignment.get("legalEntity", row.get("legalEntity", "")),
                    "comuna": assignment.get("comuna", row.get("comuna", "")),
                    "project": assignment.get("project", row.get("project", "")),
                    "pepCode": assignment.get("pepCode", row.get("pepCode", "")),
                    "campaignName": row.get("campaignName", ""),
                    "amount": amount,
                    "invoiceId": row.get("invoiceId", ""),
                    "invoiceDate": row.get("invoiceDate", ""),
                    "paymentDate": row.get("paymentDate", ""),
                    "paymentReference": row.get("paymentReference", ""),
                    "referenceId": row.get("referenceId", ""),
                    "referenceType": row.get("referenceType", ""),
                    "chargeAmountValidation": row.get("chargeAmountValidation", ""),
                    "matched": row.get("matched", False),
                    "mappingBrand": row.get("mappingBrand", ""),
                    "cartolaMatchStatus": cartola_status,
                }
            )
    return sorted(
        expanded,
        key=lambda item: (
            item["platform"],
            item["brand"],
            item["legalEntity"],
            item["project"],
            item["campaignName"],
            item["paymentDate"],
            item["referenceId"],
        ),
    )


def summarize(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, ...], int] = defaultdict(int)
    for row in rows:
        totals[tuple(str(row.get(key, "")) for key in keys)] += int(row.get("amount", 0) or 0)
    summary_rows: list[dict[str, Any]] = []
    for key_values, amount in totals.items():
        out = {key: value for key, value in zip(keys, key_values, strict=True)}
        out["amount"] = amount
        summary_rows.append(out)
    return sorted(summary_rows, key=lambda item: (-int(item["amount"]), *(str(item[key]) for key in keys)))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    reason_social_mappings, campaign_desglose_mappings = load_mappings()
    invoices, warnings = parse_june_invoices()
    rows = invoice_builder.build_reason_social_rows(
        invoices,
        reason_social_mappings,
        campaign_desglose_mappings,
        {},
    )
    rows = [row for row in rows if row.get("month") == MONTH]
    detail_rows = expanded_rows(rows)

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
    write_csv(REPORTS_DIR / "junio_2026_facturas_sin_match_desglose.csv", detail_rows, detail_fields)

    summary_keys = ["platform", "brand", "legalEntity", "comuna", "project", "pepCode"]
    summary_rows = summarize(detail_rows, summary_keys)
    write_csv(
        REPORTS_DIR / "junio_2026_facturas_sin_match_resumen_proyecto.csv",
        summary_rows,
        [*summary_keys, "amount"],
    )

    legal_summary_keys = ["platform", "legalEntity"]
    legal_rows = summarize(detail_rows, legal_summary_keys)
    write_csv(
        REPORTS_DIR / "junio_2026_facturas_sin_match_resumen_razon_social.csv",
        legal_rows,
        [*legal_summary_keys, "amount"],
    )

    unassigned = [row for row in detail_rows if row.get("legalEntity") == "Sin asignar" or row.get("project") == "Sin asignar"]
    write_csv(
        REPORTS_DIR / "junio_2026_facturas_sin_match_sin_asignar.csv",
        unassigned,
        detail_fields,
    )

    invoice_total = sum(int(invoice.get("totalAmount", 0) or 0) for invoice in invoices)
    detail_total = sum(int(row.get("amount", 0) or 0) for row in detail_rows)
    platform_totals = summarize(detail_rows, ["platform"])
    summary_text = [
        "Reporte junio 2026 facturas sin match de cartola",
        f"Facturas parseadas: {len(invoices)}",
        f"Total facturas: {invoice_total}",
        f"Total desglose asignado: {detail_total}",
        f"Filas detalle: {len(detail_rows)}",
        f"Filas sin asignar: {len(unassigned)}",
        "",
        "Totales por plataforma:",
    ]
    summary_text.extend(f"- {row['platform']}: {row['amount']}" for row in platform_totals)
    if warnings:
        summary_text.extend(["", "Warnings:"])
        summary_text.extend(f"- {warning.source}: {warning.message}" for warning in warnings[:50])
        if len(warnings) > 50:
            summary_text.append(f"- ... {len(warnings) - 50} warnings adicionales")
    (REPORTS_DIR / "junio_2026_facturas_sin_match_resumen.txt").write_text(
        "\n".join(summary_text) + "\n",
        encoding="utf-8",
    )

    print("\n".join(summary_text[:10]))


if __name__ == "__main__":
    main()
