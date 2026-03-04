#!/usr/bin/env python3
"""Build a normalized invoice dataset from local Meta and Google Ads PDFs."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdfs"
DATA_DIR = ROOT / "data"
JSON_OUT = DATA_DIR / "invoices.json"
JS_OUT = DATA_DIR / "invoices.js"
EXCEL_PATTERN = "*EESS.xlsx"

SPANISH_MONTHS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "septiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}

DATE_DMY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
DATE_DMONY_RE = re.compile(r"^(\d{1,2})\s+([a-zA-Z]{3})\s+(\d{4})$")


@dataclass
class ParseWarning:
    source: str
    message: str


def clp_to_int(value: str) -> int:
    clean = value.replace(".", "").replace(",", "").replace("$", "").strip()
    return int(clean)


def iso_from_dmy(value: str) -> str:
    m = DATE_DMY_RE.match(value.strip())
    if not m:
        raise ValueError(f"Invalid dd/mm/yyyy date: {value}")
    day, month, year = map(int, m.groups())
    return datetime(year, month, day).strftime("%Y-%m-%d")


def iso_from_dmony(value: str) -> str:
    m = DATE_DMONY_RE.match(value.strip().lower())
    if not m:
        raise ValueError(f"Invalid d mon yyyy date: {value}")
    day, mon_txt, year = m.groups()
    month = SPANISH_MONTHS[mon_txt]
    return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")


def month_key(date_iso: str) -> str:
    return date_iso[:7]


def month_key_from_spanish_name(value: str) -> str:
    parts = value.strip().lower().split()
    if len(parts) < 2:
        raise ValueError(f"Invalid month name: {value}")
    month = SPANISH_MONTHS[parts[0]]
    year = int(parts[1])
    return f"{year:04d}-{month:02d}"


def excel_number_to_str(raw: str) -> str:
    # Excel stores long ids as scientific notation in XML.
    as_int = int(round(float(raw)))
    return str(as_int)


def extract_text_pypdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_layout_lines(path: Path) -> list[str]:
    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            lines.extend([ln.strip() for ln in text.splitlines() if ln.strip()])
    return lines


def parse_google_invoice(path: Path, warnings: list[ParseWarning]) -> dict[str, Any]:
    filename = path.name
    brand = (
        "Almagro Inmobiliaria"
        if "Almagro_Inmobiliaria" in filename
        else "Almagro Propiedades"
        if "Almagro_Propiedades" in filename
        else "Socovesa"
        if "Socovesa" in filename
        else "Pilares"
    )

    text = extract_text_pypdf(path)
    lines = extract_layout_lines(path)

    invoice_number_m = re.search(r"Número de factura:\s*(\d+)", text)
    invoice_number = invoice_number_m.group(1) if invoice_number_m else filename.split("_")[0]

    header_date_m = re.search(r"\.{5,}(\d{1,2}\s+[a-zA-Z]{3}\s+\d{4})", text)
    invoice_date_iso = iso_from_dmony(header_date_m.group(1)) if header_date_m else "1970-01-01"

    due_date_m = re.search(r"Vencimiento:\s*(\d{1,2}\s+[a-zA-Z]{3}\s+\d{4})", text)
    due_date_iso = iso_from_dmony(due_date_m.group(1)) if due_date_m else ""

    period_m = re.search(
        r"Resumen del\s+(\d{1,2}\s+[a-zA-Z]{3}\s+\d{4})\s*-\s*(\d{1,2}\s+[a-zA-Z]{3}\s+\d{4})",
        text,
    )
    period_start_iso = iso_from_dmony(period_m.group(1)) if period_m else invoice_date_iso
    period_end_iso = iso_from_dmony(period_m.group(2)) if period_m else invoice_date_iso

    account_id_m = re.search(r"ID de la cuenta:\s*([\d-]+)", text)
    account_id = account_id_m.group(1) if account_id_m else ""

    account_name = ""
    for line in lines:
        if line.startswith("Cuenta: "):
            account_name = line.replace("Cuenta:", "").strip()
            break

    summary_items: list[dict[str, Any]] = []
    total_amount = 0
    in_summary = False
    pending_label = ""
    for line in lines:
        if line.startswith("Pagar en CLP:"):
            in_summary = True
            pending_label = ""
            continue
        if not in_summary:
            continue
        if line.startswith("Importe total adeudado en CLP"):
            m = re.search(r"CLP\s*([\d,]+)$", line)
            if m:
                total_amount = clp_to_int(m.group(1))
            in_summary = False
            continue
        if line == "Impuesto (0%)" or line == "Importe en CLP":
            pending_label = line
            continue
        if line.startswith("CLP "):
            if pending_label:
                summary_items.append({"label": pending_label, "amount": clp_to_int(line.replace("CLP", ""))})
                pending_label = ""
            continue

        same_line = re.match(r"^(.*?)\s+CLP\s*([\d,]+)$", line)
        if same_line:
            label, amount = same_line.groups()
            summary_items.append({"label": label.strip(), "amount": clp_to_int(amount)})
            pending_label = ""
            continue

        if pending_label:
            pending_label = f"{pending_label} {line}".strip()
        else:
            pending_label = line

    details: list[dict[str, Any]] = []
    in_table = False
    for line in lines:
        if line.startswith("Descripción"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("Subtotal en CLP"):
            in_table = False
            continue
        if line.startswith("Si tiene alguna pregunta"):
            continue
        if line.startswith("Factura") or line.startswith("Número de factura:"):
            continue

        invalid_m = re.match(r"^(Actividad no válida\.\.\.)\s+(-?[\d,]+)$", line)
        if invalid_m:
            details.append(
                {
                    "description": invalid_m.group(1),
                    "quantity": None,
                    "unit": None,
                    "amount": clp_to_int(invalid_m.group(2)),
                }
            )
            continue

        row_m = re.match(r"^(.*?)\s+([\d,]+)\s+(Clics|Impresiones)\s+(-?[\d,]+)$", line)
        if row_m:
            desc, qty, unit, amount = row_m.groups()
            details.append(
                {
                    "description": desc.strip(),
                    "quantity": int(qty.replace(",", "")),
                    "unit": unit,
                    "amount": clp_to_int(amount),
                }
            )
            continue

        fee_m = re.match(r"^(.*?)\s+(-?[\d,]+)$", line)
        if fee_m and "CLP" not in line:
            desc, amount = fee_m.groups()
            details.append(
                {
                    "description": desc.strip(),
                    "quantity": None,
                    "unit": None,
                    "amount": clp_to_int(amount),
                }
            )
            continue

    detail_sum = sum(item["amount"] for item in details)
    if total_amount and detail_sum != total_amount:
        warnings.append(
            ParseWarning(
                source=filename,
                message=f"Detail sum ({detail_sum}) does not match total ({total_amount}).",
            )
        )

    return {
        "id": invoice_number,
        "sourceFile": filename,
        "pdfFile": f"pdfs/{filename}",
        "documentFile": f"pdfs/{filename}",
        "platform": "Google Ads",
        "brand": brand,
        "month": month_key(invoice_date_iso),
        "invoiceDate": invoice_date_iso,
        "periodStart": period_start_iso,
        "periodEnd": period_end_iso,
        "dueDate": due_date_iso,
        "currency": "CLP",
        "accountName": account_name,
        "accountId": account_id,
        "totalAmount": total_amount,
        "summaryBreakdown": summary_items,
        "details": details,
        "notes": [],
    }


def parse_meta_invoice(path: Path, warnings: list[ParseWarning]) -> dict[str, Any]:
    filename = path.name
    is_pilares = "Pilares" in filename
    brand = "Pilares" if is_pilares else "Almagro Inmobiliaria"

    text = extract_text_pypdf(path)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    account_m = re.search(r"Cuenta:\s*([0-9]+)", text)
    account_id = account_m.group(1) if account_m else ""

    period_m = re.search(r"Informe de facturación:\s*(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    period_start_iso = iso_from_dmy(period_m.group(1)) if period_m else "1970-01-01"
    period_end_iso = iso_from_dmy(period_m.group(2)) if period_m else "1970-01-01"

    total_billed_m = re.search(r"Importe total facturado\s+\$([\d\.]+)\s+CLP", text)
    total_funds_m = re.search(r"Total de fondos agregado\s+\$([\d\.]+)\s+CLP", text)
    total_billed = clp_to_int(total_billed_m.group(1)) if total_billed_m else 0
    total_funds = clp_to_int(total_funds_m.group(1)) if total_funds_m else 0

    default_method_m = re.search(r"Método de pago:\s*(.+)", text)
    default_method = default_method_m.group(1).strip() if default_method_m else "No disponible"

    date_re = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4})\s*(.*)$")
    amount_status_re = re.compile(r"\$([\d\.]+)\s+CLP\s+(Pagado|Fondos agregados)\s*$")
    method_re = re.compile(r"(Visa\s+·+\s*\d{4}|No disponible)")

    details: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = date_re.match(line)
        if not date_match:
            i += 1
            continue

        date_txt = date_match.group(1)
        buffer = [date_match.group(2).strip()] if date_match.group(2).strip() else []
        i += 1
        while i < len(lines) and not date_re.match(lines[i]):
            if lines[i].startswith("Importe total facturado"):
                break
            buffer.append(lines[i])
            candidate = " ".join(buffer).strip()
            if amount_status_re.search(candidate):
                i += 1
                break
            i += 1

        candidate = " ".join(buffer).strip()
        am = amount_status_re.search(candidate)
        if not am:
            continue
        amount = clp_to_int(am.group(1))
        status = am.group(2)
        before_amount = candidate[: am.start()].strip()

        method = default_method
        method_match = method_re.search(before_amount)
        if method_match:
            method = method_match.group(1)
            tx_raw = (before_amount[: method_match.start()] + before_amount[method_match.end() :]).strip()
        else:
            tx_raw = before_amount
        tx_id = re.sub(r"\s+", "", tx_raw)

        details.append(
            {
                "date": iso_from_dmy(date_txt),
                "transactionId": tx_id,
                "paymentMethod": method,
                "status": status,
                "amount": amount,
            }
        )

    paid_sum = sum(row["amount"] for row in details if row["status"] == "Pagado")
    funds_sum = sum(row["amount"] for row in details if row["status"] == "Fondos agregados")
    if paid_sum != total_billed:
        warnings.append(
            ParseWarning(
                source=filename,
                message=f"Paid sum ({paid_sum}) does not match billed total ({total_billed}).",
            )
        )
    if funds_sum != total_funds:
        warnings.append(
            ParseWarning(
                source=filename,
                message=f"Funds sum ({funds_sum}) does not match funds total ({total_funds}).",
            )
        )

    invoice_date_iso = details[0]["date"] if details else period_end_iso

    notes: list[str] = []
    if not is_pilares:
        notes.append("Meta agrupa esta cuenta como ALMAGRO S A y no separa Inmobiliaria/Propiedades en el PDF.")

    return {
        "id": f"meta-{brand.lower().replace(' ', '-')}-{month_key(period_start_iso)}",
        "sourceFile": filename,
        "pdfFile": f"pdfs/{filename}",
        "documentFile": f"pdfs/{filename}",
        "platform": "Meta",
        "brand": brand,
        "month": month_key(period_start_iso),
        "invoiceDate": invoice_date_iso,
        "periodStart": period_start_iso,
        "periodEnd": period_end_iso,
        "dueDate": "",
        "currency": "CLP",
        "accountName": "ALMAGRO S A" if not is_pilares else "Pilares",
        "accountId": account_id,
        "totalAmount": total_billed,
        "summaryBreakdown": [
            {"label": "Importe total facturado", "amount": total_billed},
            {"label": "Total de fondos agregado", "amount": total_funds},
        ],
        "details": details,
        "notes": notes,
    }


def parse_excel_sheet_rows(path: Path) -> tuple[str, dict[int, dict[str, str]]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

    with zipfile.ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_el = workbook.find("m:sheets/m:sheet", ns)
        if sheet_el is None:
            raise ValueError(f"No sheets found in {path.name}")
        sheet_name = sheet_el.attrib.get("name", "")
        rel_id = sheet_el.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_target = ""
        for rel in rels.findall("r:Relationship", rel_ns):
            if rel.attrib.get("Id") == rel_id:
                rel_target = rel.attrib["Target"]
                break
        if not rel_target:
            raise ValueError(f"Could not resolve sheet relationship in {path.name}")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst.findall("m:si", ns):
                text = "".join(t.text or "" for t in si.findall(".//m:t", ns))
                shared_strings.append(text)

        sheet = ET.fromstring(zf.read(f"xl/{rel_target}"))
        rows: dict[int, dict[str, str]] = {}
        for row in sheet.findall("m:sheetData/m:row", ns):
            row_idx = int(row.attrib["r"])
            row_map: dict[str, str] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "")
                col = "".join(ch for ch in ref if ch.isalpha())
                value_el = cell.find("m:v", ns)
                if not col or value_el is None:
                    continue
                val = value_el.text or ""
                if cell.attrib.get("t") == "s" and val:
                    row_map[col] = shared_strings[int(val)]
                else:
                    row_map[col] = val
            if row_map:
                rows[row_idx] = row_map
        return sheet_name, rows


def parse_zeppelin_excel(path: Path, warnings: list[ParseWarning], document_file: str) -> list[dict[str, Any]]:
    sheet_name, rows = parse_excel_sheet_rows(path)
    month = month_key_from_spanish_name(sheet_name)
    year, month_num = map(int, month.split("-"))
    last_day = monthrange(year, month_num)[1]
    period_start = f"{month}-01"
    period_end = f"{month}-{last_day:02d}"

    concept_cell = rows.get(3, {}).get("B", "")
    if "Zeppelin" not in concept_cell:
        warnings.append(ParseWarning(source=path.name, message="Could not find 'Línea de Crédito Zeppelin' section."))
        return []

    invoices: list[dict[str, Any]] = []
    for row_idx in sorted(rows):
        row = rows[row_idx]
        brand_raw = row.get("B", "").strip()
        if not brand_raw or brand_raw in {"Inmobiliaria"}:
            continue
        if brand_raw == "Total":
            break

        po_raw = row.get("C", "").strip()
        invoice_raw = row.get("D", "").strip()
        amount_raw = row.get("E", "").strip()
        if not amount_raw:
            continue

        brand = brand_raw
        notes: list[str] = []
        if brand_raw == "Almagro":
            brand = "Almagro Inmobiliaria"
            notes.append("En el Excel de Zeppelin esta marca figura consolidada como 'Almagro'.")

        po_number = excel_number_to_str(po_raw) if po_raw else ""
        supplier_invoice = excel_number_to_str(invoice_raw) if invoice_raw else ""
        amount = int(round(float(amount_raw)))

        invoices.append(
            {
                "id": f"zeppelin-{supplier_invoice}",
                "sourceFile": path.name,
                "pdfFile": document_file,
                "documentFile": document_file,
                "platform": "Agencia Zeppelin",
                "brand": brand,
                "month": month,
                "invoiceDate": period_end,
                "periodStart": period_start,
                "periodEnd": period_end,
                "dueDate": "",
                "currency": "CLP",
                "accountName": "Línea de Crédito Zeppelin",
                "accountId": po_number,
                "totalAmount": amount,
                "summaryBreakdown": [
                    {"label": "Inversión", "amount": amount},
                ],
                "details": [
                    {
                        "concept": "Línea de Crédito Zeppelin",
                        "purchaseOrder": po_number,
                        "supplierInvoice": supplier_invoice,
                        "amount": amount,
                    }
                ],
                "notes": notes,
            }
        )
    return invoices


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    warnings: list[ParseWarning] = []

    invoices: list[dict[str, Any]] = []
    google_files = sorted(PDF_DIR.glob("*GoogleAds.pdf"))
    meta_files = sorted(PDF_DIR.glob("*Meta*.pdf"))

    for file in google_files:
        invoices.append(parse_google_invoice(file, warnings))
    for file in meta_files:
        invoices.append(parse_meta_invoice(file, warnings))
    excel_files = sorted(ROOT.glob(EXCEL_PATTERN))
    for file in excel_files:
        target_excel = PDF_DIR / "Facturacion_EESS.xlsx"
        if file.resolve() != target_excel.resolve():
            shutil.copy2(file, target_excel)
        invoices.extend(parse_zeppelin_excel(file, warnings, document_file=f"pdfs/{target_excel.name}"))

    invoices.sort(key=lambda item: (item["month"], item["platform"], item["brand"], item["invoiceDate"]))

    known_brand_order = [
        "Almagro Inmobiliaria",
        "Almagro Propiedades",
        "Socovesa",
        "Pilares",
    ]
    brand_set = {item["brand"] for item in invoices}
    brands = [brand for brand in known_brand_order if brand in brand_set]
    brands.extend(sorted(brand_set - set(brands)))

    platform_order = ["Meta", "Google Ads", "Agencia Zeppelin"]
    platform_set = {item["platform"] for item in invoices}
    platforms = [platform for platform in platform_order if platform in platform_set]
    platforms.extend(sorted(platform_set - set(platforms)))

    data: dict[str, Any] = {
        "generatedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "CLP",
        "invoices": invoices,
        "brands": brands,
        "platforms": platforms,
    }

    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    JS_OUT.write_text(
        "window.INVOICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- [{warning.source}] {warning.message}")
    else:
        print("Dataset generated without warnings.")
    print(f"Wrote {JSON_OUT}")
    print(f"Wrote {JS_OUT}")


if __name__ == "__main__":
    main()
