#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""Build a normalized invoice dataset from local Meta and Google Ads PDFs."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unicodedata
import zipfile
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pdfplumber
from pypdf import PdfReader
try:
    import xlrd
except ImportError:  # pragma: no cover - optional dependency in some environments
    xlrd = None

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdfs"
GOOGLE_INVOICES_DIR = ROOT / "Facturas Google"
META_INVOICES_DIR = ROOT / "Facturas Meta"
META_CARD_STATEMENTS_DIR = META_INVOICES_DIR / "Cartola TC"
DATA_DIR = ROOT / "data"
JSON_OUT = DATA_DIR / "invoices.json"
JS_OUT = DATA_DIR / "invoices.js"
EXCEL_PATTERN = "*EESS.xlsx"
META_TOTAL_OVERRIDES = {
    "Resumen_Facturacion_Socovesa_Meta_Febrero2026.pdf": 15_977_002,
}

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
META_RECEIPT_DATE_RE = re.compile(r"(\d{1,2})\s+([a-zA-ZÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂºÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±\.]+)\s+(\d{4})", re.IGNORECASE)
FACEBK_CODE_RE = re.compile(r"FACEBK\s*\*([A-Z0-9]{8,12})", re.IGNORECASE)
STAR_CHARGE_CODE_RE = re.compile(r"\*([A-Z0-9]{8,12})", re.IGNORECASE)
DECIMAL_COMMA_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")

DESGLOSE_BRAND_PREFIXES = [
    ("Socovesa Santiago", "socovesasantiago"),
    ("Socovesa Sur", "socovesasur"),
    ("Socovesa", "socovesa"),
    ("Almagro", "almagro"),
    ("Pilares", "pilares"),
]

GCLOUD_SPLIT_ENTITIES = [
    {
        "legalEntity": "Almagro S.A",
        "comuna": "GCloud",
        "project": "GCloud",
        "pepCode": "",
    },
    {
        "legalEntity": "Pilares",
        "comuna": "GCloud",
        "project": "GCloud",
        "pepCode": "",
    },
    {
        "legalEntity": "INSOCO",
        "comuna": "GCloud",
        "project": "GCloud",
        "pepCode": "",
    },
]


@dataclass
class ParseWarning:
    source: str
    message: str


def normalize_key(value: str) -> str:
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", str(value).lower()) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", plain)


CANONICAL_ENCINAS_LEGAL_ENTITY = "INMOBILIARIA ENCINAS DE PE\u00d1ALOLEN"


def normalize_legal_entity_name(value: str) -> str:
    raw = str(value or "").strip()
    key = normalize_key(raw)
    if key == "inmobiliariaencinasdepenalolen" or (
        "inmobiliariaencinasdepe" in key and key.endswith("alolen")
    ):
        return CANONICAL_ENCINAS_LEGAL_ENTITY
    return raw


PROJECT_LEGAL_ENTITY_OVERRIDES = {
    normalize_key("Almagro Plus"): "Almagro S.A",
    normalize_key("San Eugenio 2"): "Almagro S.A",
    normalize_key("Indico"): "Almagro S.A",
    normalize_key("Parque Brasil"): "Almagro S.A",
    normalize_key("Balance"): "Almagro S.A",
    normalize_key("Lyon Bilbao"): "Almagro S.A",
    normalize_key("Carrera 4"): "Almagro S.A",
    normalize_key("Insigne"): "Almagro S.A",
    normalize_key("Los Cactus"): "Almagro S.A",
    normalize_key("PLP 1"): "Arcilla Roja",
    normalize_key("PLP 2"): "Arcilla Roja",
    normalize_key("Almagro Hub"): "Arcilla Roja",
    normalize_key("Rengo"): "Arcilla Roja",
    normalize_key("Las Palmas"): "Consorcio Inmobiliario Macul",
    normalize_key("Conde del Maule"): "ICSA",
    normalize_key("Edificio ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“uble"): "ICSA",
    normalize_key("Lo Ovalle"): "ICSA",
    normalize_key("Santos Dumont"): "ICSA",
    normalize_key("Pajaritos"): "Inmobiliaria El Descubridor",
    normalize_key("Las Pataguas"): "Inmobiliaria Encinas de PeÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±alolen",
    normalize_key("Los Coihues"): "Inmobiliaria Encinas de PeÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±alolen",
    normalize_key("Almagro District"): "Madagascar",
    normalize_key("Marathon"): "Pilares S.A",
    normalize_key("Guillermo Mann"): "Pilares S.A",
    normalize_key("Rodriguez Velasco"): "Pilares S.A",
    normalize_key("VicuÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±a Mackenna 7244"): "Pilares S.A",
    normalize_key("Coipue"): "Sociedad Comercializadora Metropolitana",
    normalize_key("Alto Maderos"): "Socovesa Sur S.A",
    normalize_key("Edificio VÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©rtice"): "Socovesa Sur S.A",
    normalize_key("GarcÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­a Reyes"): "Socovesa Sur S.A",
    normalize_key("Icono"): "Socovesa Sur S.A",
    normalize_key("N3"): "Socovesa Sur S.A",
    normalize_key("Nueva Toledo"): "Socovesa Sur S.A",
    normalize_key("O3"): "Socovesa Sur S.A",
    normalize_key("Origen"): "Socovesa Sur S.A",
    normalize_key("Parque Avellanos"): "Socovesa Sur S.A",
    normalize_key("PDL"): "Socovesa Sur S.A",
    normalize_key("Portal Austral"): "Socovesa Sur S.A",
    normalize_key("Reserva Magallanes"): "Socovesa Sur S.A",
    normalize_key("Terraza Mirador"): "Socovesa Sur S.A",
}

PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Las Pataguas")] = CANONICAL_ENCINAS_LEGAL_ENTITY
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Los Coihues")] = CANONICAL_ENCINAS_LEGAL_ENTITY
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Edificio \u00d1uble")] = "ICSA"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Vicu\u00f1a Mackenna 7244")] = "Pilares S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Edificio V\u00e9rtice")] = "Socovesa Sur S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Garc\u00eda Reyes")] = "Socovesa Sur S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Almagro Terra")] = "Almagro S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Franklin")] = "Arcilla Roja"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Valle del Mar")] = "Almagro S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Signature")] = "Almagro S.A"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Agust\u00edn del Castillo")] = "Almagro SA"
PROJECT_LEGAL_ENTITY_OVERRIDES[normalize_key("Plaza Mirador")] = "INSOCO"

PROJECT_PEP_CODES = {
    normalize_key("Insigne"): "I-ALM-2157",
    normalize_key("Parque Brasil"): "I-ALM-2285",
    normalize_key("PLP 1"): "I-ALM-2226",
    normalize_key("Los Cactus"): "I-ALM-2342",
    normalize_key("Almagro Plus"): "I-ALM-2234",
    normalize_key("Lyon Bilbao"): "I-ALM-2211",
    normalize_key("Carrera 4"): "I-ALM-2275",
    normalize_key("Almagro District"): "I-ALM-2399",
    normalize_key("Rengo"): "I-ALM-2288",
    normalize_key("Indico"): "I-ALM-1453",
    normalize_key("Almagro Hub"): "I-ALM-2189",
    normalize_key("Balance"): "I-ALM-2358",
    normalize_key("PLP 2"): "I-ALM-2306",
    normalize_key("San Eugenio 2"): "I-ALM-2227",
    normalize_key("Guillermo Mann"): "I-SVS-2250",
    normalize_key("Conde del Maule"): "I-SVS-2255",
    normalize_key("Santos Dumont"): "I-SVS-2246",
    normalize_key("Lo Ovalle"): "I-SVS-2296",
    normalize_key("Rodriguez Velasco"): "I-SVS-2289",
    normalize_key("Edificio Ñuble"): "I-SVS-2173",
    normalize_key("Franklin"): "I-ALM-2212",
    normalize_key("Vicuña Mackenna 7244"): "I-SVS-2131",
    normalize_key("Los Coihues"): "I-STG-2325",
    normalize_key("Las Palmas"): "I-STG-2205",
    normalize_key("Pajaritos"): "I-STG-2204",
    normalize_key("Marathon"): "I-SVS-2349",
    normalize_key("Las Pataguas"): "I-STG-2366",
    normalize_key("Coipue"): "I-STG-2229",
    normalize_key("PDL"): "I-SUR-2372",
    normalize_key("Alto Maderos"): "I-SUR-2335",
    normalize_key("N3"): "I-SUR-2331",
    normalize_key("García Reyes"): "I-SUR-2283",
    normalize_key("Portal Austral"): "I-SUR-2340",
    normalize_key("Reserva Magallanes"): "I-SUR-2323",
    normalize_key("Parque Avellanos"): "I-SUR-2336",
    normalize_key("Nueva Toledo"): "I-SUR-2334",
    normalize_key("Origen"): "I-SUR-2346",
    normalize_key("Icono"): "I-SUR-2346",
    normalize_key("Edificio Vértice"): "I-SUR-2297",
    normalize_key("O3"): "I-SUR-2373",
    normalize_key("Terraza Mirador"): "I-SUR-2333",
    normalize_key("Almagro Terra"): "I-ALM-2360",
}

PROJECT_PEP_CODES[normalize_key("Edificio \u00d1uble")] = "I-SVS-2173"
PROJECT_PEP_CODES[normalize_key("Vicu\u00f1a Mackenna 7244")] = "I-SVS-2131"
PROJECT_PEP_CODES[normalize_key("Garc\u00eda Reyes")] = "I-SUR-2283"
PROJECT_PEP_CODES[normalize_key("Edificio V\u00e9rtice")] = "I-SUR-2297"
PROJECT_PEP_CODES[normalize_key("Plaza Mirador")] = "I-STG-2391"
PROJECT_PEP_CODES[normalize_key("Valle del Mar")] = "I-ALM-1453"
PROJECT_PEP_CODES[normalize_key("Signature")] = "I-ALM-2354"

MANUAL_CAMPAIGN_PROJECT_OVERRIDES = {
    normalize_key("ValleDelMar"): ("Antofagasta", "Valle del Mar"),
    normalize_key("Signature"): ("Santiago", "Signature"),
    normalize_key("Carrera_IV"): ("Santiago", "Carrera 4"),
    normalize_key("Carrera IV"): ("Santiago", "Carrera 4"),
    normalize_key("SanEugenio"): ("Santiago", "San Eugenio 2"),
    normalize_key("AlmagroTerra"): ("Antofagasta", "Almagro Terra"),
    normalize_key("Parque Brasil"): ("Antofagasta", "Parque Brasil"),
    normalize_key("Franklin"): ("Santiago Centro", "Franklin"),
    normalize_key("GarciaReyes"): ("Valdivia", "Garc\u00eda Reyes"),
    normalize_key("Garc\u00eda Reyes"): ("Valdivia", "Garc\u00eda Reyes"),
    normalize_key("EdificioVertice"): ("Temuco", "Edificio V\u00e9rtice"),
    normalize_key("Edificio V\u00e9rtice"): ("Temuco", "Edificio V\u00e9rtice"),
    normalize_key("VistaNielol"): ("Temuco", "N3"),
    normalize_key("Temuco N3"): ("Temuco", "N3"),
    normalize_key("Inversionistas"): ("Santiago", "Insigne"),
    normalize_key("Vitacura"): ("Vitacura", "Signature"),
    normalize_key("Plaza Mirador"): ("La Florida", "Plaza Mirador"),
    normalize_key("Santiago | AO S | Comuna | La Florida"): ("La Florida", "Plaza Mirador"),
    normalize_key("Portal del Libertador IX"): ("Chill\u00e1n", "PDL"),
    normalize_key("Costos operativos regulatorios"): ("Coipue", "Coipue"),
    normalize_key("FB_WA_Pilares_Advantage_Proyectos"): ("AON", "Guillermo Mann"),
    normalize_key("FB_WA_SantiagoSubsidio_LasPataguas"): ("Lampa", "Las Pataguas"),
    normalize_key("Santiago | Demand Gen | Insigne"): ("Macul", "Insigne"),
    normalize_key("Santiago | MR | Hub"): ("Providencia", "Almagro Hub"),
    normalize_key("Santiago | Max. Rend. | Por Proyecto | Macul | Coipue"): ("Macul", "Coipue"),
    normalize_key("FB_AOT_Santiago_AlmagroHub"): ("Providencia", "Almagro Hub"),
    normalize_key("FB_WA_Almagro_Advantage_Proyectos"): ("AON", "Almagro Hub"),
    normalize_key("FB_AOT_SantiagoMedio_Coipue"): ("Macul", "Coipue"),
}


def override_legal_entity_by_project(project: str, fallback_legal_entity: str) -> str:
    project_key = normalize_key(project)
    if not project_key:
        return normalize_legal_entity_name(fallback_legal_entity)
    return normalize_legal_entity_name(PROJECT_LEGAL_ENTITY_OVERRIDES.get(project_key, fallback_legal_entity))


def pep_code_by_project(project: str) -> str:
    project_key = normalize_key(project)
    if not project_key:
        return ""
    return PROJECT_PEP_CODES.get(project_key, "")


def manual_assignment_by_campaign(campaign_name: str) -> tuple[str, str, str] | None:
    campaign_key = normalize_key(campaign_name)
    for token, (comuna, project) in MANUAL_CAMPAIGN_PROJECT_OVERRIDES.items():
        if token in campaign_key:
            legal_entity = override_legal_entity_by_project(project, "Sin asignar")
            return legal_entity, comuna, project
    return None


def normalize_brand_group(value: str) -> str:
    plain = normalize_key(value)
    if "almagro" in plain:
        return "almagro"
    if "pilares" in plain:
        return "pilares"
    if "socovesasantiago" in plain:
        return "socovesasantiago"
    if "socovesasur" in plain:
        return "socovesasur"
    if "socovesa" in plain:
        return "socovesa"
    return plain


def brand_group_aliases(brand_group: str) -> list[str]:
    if brand_group == "socovesa":
        return ["socovesa", "socovesasantiago", "socovesasur"]
    return [brand_group]


def is_special_charge_label(label: str) -> bool:
    normalized = normalize_key(label)
    return (
        "actividadnovalida" in normalized
        or "costosoperativosregulatorios" in normalized
        or "couponsgoodwillbugs" in normalized
        or "tarifadelimpuesto" in normalized
        or "tarifasimpuestos" in normalized
    )


def clp_to_int(value: str) -> int:
    clean = re.sub(r"[^\d,.\-]", "", value).strip()
    if not clean:
        return 0

    sign = -1 if clean.startswith("-") else 1
    if clean[0] in "+-":
        clean = clean[1:]
    if not clean:
        return 0

    # Chilean style: 15.977.002 or 15.977.002,50
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", clean):
        normalized = clean.replace(".", "").replace(",", ".")
        return sign * int(round(float(normalized)))

    # US style: 600,000.00
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", clean):
        normalized = clean.replace(",", "")
        return sign * int(round(float(normalized)))

    # Plain decimals without thousand separators.
    if re.fullmatch(r"\d+[.,]\d+", clean):
        normalized = clean.replace(",", ".")
        return sign * int(round(float(normalized)))

    return sign * int(re.sub(r"[^\d]", "", clean))


def decimal_comma_to_float(value: str) -> float:
    clean = str(value).strip().replace(".", "").replace(",", ".")
    if not clean:
        return 0.0
    try:
        return float(clean)
    except ValueError:
        return 0.0


def normalize_text_for_search(value: str) -> str:
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(ch))
    return " ".join(plain.split())


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


def month_key_from_folder_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", " ")
    parts = normalized.split()
    if len(parts) < 2:
        return ""
    month_num = SPANISH_MONTHS.get(parts[0].replace(".", ""))
    if not month_num:
        return ""
    try:
        year = int(parts[1])
    except ValueError:
        return ""
    return f"{year:04d}-{month_num:02d}"


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


def month_key_from_filename(filename: str) -> str:
    m = re.search(
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*(\d{4})",
        filename,
        re.IGNORECASE,
    )
    if not m:
        return ""
    month_txt = m.group(1).lower()
    year = int(m.group(2))
    month_num = SPANISH_MONTHS[month_txt]
    return f"{year:04d}-{month_num:02d}"


def first_day_next_month(month: str) -> str:
    year, month_num = map(int, month.split("-"))
    if month_num == 12:
        return f"{year + 1:04d}-01-01"
    return f"{year:04d}-{month_num + 1:02d}-01"


def last_day_of_month(month: str) -> str:
    year, month_num = map(int, month.split("-"))
    return f"{year:04d}-{month_num:02d}-{monthrange(year, month_num)[1]:02d}"


def parse_meta_invoice_ocr_fallback(path: Path, warnings: list[ParseWarning]) -> dict[str, Any] | None:
    filename = path.name
    month = month_key_from_filename(filename)
    if not month:
        warnings.append(ParseWarning(source=filename, message="Could not infer month from filename for OCR fallback."))
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="meta-ocr-") as tmp_dir:
            prefix = Path(tmp_dir) / "meta_page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "300", str(path), str(prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            first_page = Path(f"{prefix}-1.png")
            if not first_page.exists():
                warnings.append(ParseWarning(source=filename, message="OCR fallback did not produce page images."))
                return None
            ocr_text = subprocess.check_output(
                ["tesseract", str(first_page), "stdout", "-l", "spa+eng", "--psm", "11"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
    except FileNotFoundError:
        warnings.append(
            ParseWarning(
                source=filename,
                message="OCR fallback unavailable (missing 'pdftoppm' or 'tesseract' in PATH).",
            )
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive fallback
        warnings.append(ParseWarning(source=filename, message=f"OCR fallback failed: {exc}"))
        return None

    lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    date_re = re.compile(r"(\d{1,2})\s+([a-zA-Z]{3,10})\s+(\d{4})", re.IGNORECASE)
    amount_re = re.compile(r"\$\s*([\d\.,]+)")
    fbads_re = re.compile(r"(FBADS-\d+-\d+)", re.IGNORECASE)

    details: list[dict[str, Any]] = []
    seen_fbads: set[str] = set()
    for idx, line in enumerate(lines):
        fb_match = fbads_re.search(line)
        if not fb_match:
            continue
        tx_id = fb_match.group(1).upper()
        if tx_id in seen_fbads:
            continue

        date_iso = ""
        amount = None
        start = max(0, idx - 45)
        end = min(len(lines), idx + 46)

        date_candidates: list[tuple[int, str]] = []
        amount_candidates: list[tuple[int, int]] = []
        for near in range(start, end):
            if near == idx:
                continue
            distance = abs(near - idx)

            dm = date_re.search(lines[near])
            if dm:
                day = int(dm.group(1))
                month_txt = dm.group(2).lower()
                year = int(dm.group(3))
                month_num = SPANISH_MONTHS.get(month_txt)
                if month_num:
                    date_candidates.append((distance, f"{year:04d}-{month_num:02d}-{day:02d}"))

            am = amount_re.search(lines[near])
            if am:
                parsed = clp_to_int(am.group(1))
                # OCR correction for common 600.000/10.000 recognition issues.
                if parsed == 60000:
                    parsed = 600000
                if parsed == 1000:
                    parsed = 10000
                amount_candidates.append((distance, parsed))

        if date_candidates:
            date_iso = sorted(date_candidates, key=lambda item: item[0])[0][1]
        if amount_candidates:
            amount = sorted(amount_candidates, key=lambda item: item[0])[0][1]

        if not date_iso or amount is None:
            continue

        seen_fbads.add(tx_id)
        details.append(
            {
                "date": date_iso,
                "transactionId": tx_id,
                "paymentMethod": "Visa ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· 2327",
                "status": "Pagado",
                "amount": amount,
            }
        )

    if not details:
        warnings.append(ParseWarning(source=filename, message="OCR fallback found no transaction rows."))
        return None

    details.sort(key=lambda row: row["date"], reverse=True)
    total_billed = sum(row["amount"] for row in details)
    return {
        "month": month,
        "invoiceDate": details[0]["date"],
        "periodStart": f"{month}-01",
        "periodEnd": first_day_next_month(month),
        "accountId": "",
        "totalBilled": total_billed,
        "totalFunds": 0,
        "details": details,
    }


def parse_meta_invoice_activity_export(text: str, filename: str, warnings: list[ParseWarning]) -> dict[str, Any] | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    row_re = re.compile(
        r"^(\d{1,2}\s+[a-zA-Z]{3}\s+\d{4})\s*([0-9]{10,}-[0-9]{10,})"
        r"(?:Visa\s+.*?\d{4}|No disponible)\s+(Pagado|Fondos agregados)\s+\$([\d,\.]+)$",
        re.IGNORECASE,
    )

    details: list[dict[str, Any]] = []
    for line in lines:
        m = row_re.match(line)
        if not m:
            continue
        date_txt, tx_id, status, amount_txt = m.groups()
        details.append(
            {
                "date": iso_from_dmony(date_txt),
                "transactionId": tx_id,
                "paymentMethod": "Visa ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· 2327",
                "status": status,
                "amount": clp_to_int(amount_txt),
            }
        )

    if not details:
        return None

    details.sort(key=lambda row: row["date"], reverse=True)

    month = month_key_from_filename(filename)
    if not month:
        month = month_key(details[0]["date"])
        warnings.append(
            ParseWarning(
                source=filename,
                message="Could not infer month from filename, inferred from transaction date.",
            )
        )

    total_billed = sum(row["amount"] for row in details if row["status"] == "Pagado")
    total_funds = sum(row["amount"] for row in details if row["status"] == "Fondos agregados")

    return {
        "month": month,
        "invoiceDate": details[0]["date"],
        "periodStart": f"{month}-01",
        "periodEnd": first_day_next_month(month),
        "accountId": "",
        "totalBilled": total_billed,
        "totalFunds": total_funds,
        "details": details,
    }


def normalize_meta_folder_brand(folder_name: str) -> tuple[str, str]:
    key = folder_name.strip().lower()
    if key == "almagro":
        return "Almagro Inmobiliaria", "ALMAGRO S A"
    if key == "socovesa":
        return "Socovesa", "Socovesa"
    if key == "pilares":
        return "Pilares", "Pilares"
    cleaned = folder_name.strip()
    return cleaned, cleaned


META_ACCOUNT_ID_BRAND_MAP = {
    "1933674297549805": ("Almagro Inmobiliaria", "ALMAGRO S A"),
    "2369745096782799": ("Pilares", "Pilares"),
    "854587093857588": ("Socovesa", "Socovesa"),
}


def normalize_meta_account_brand(account_id: str) -> tuple[str, str]:
    return META_ACCOUNT_ID_BRAND_MAP.get(account_id.strip(), ("", ""))


def iso_from_meta_receipt_date(value: str) -> str:
    m = META_RECEIPT_DATE_RE.search(value.strip().lower())
    if not m:
        raise ValueError(f"Invalid Meta receipt date: {value}")
    day, mon_txt, year = m.groups()
    mon_key = mon_txt.replace(".", "")
    month = SPANISH_MONTHS.get(mon_key) or SPANISH_MONTHS.get(mon_key[:3])
    if not month:
        raise ValueError(f"Unsupported month token in Meta receipt date: {value}")
    return datetime(int(year), month, int(day)).strftime("%Y-%m-%d")


def parse_meta_receipt_campaigns(lines: list[str]) -> list[dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    in_campaign_block = False
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        if normalize_key(line) == "campanas":
            in_campaign_block = True
            idx += 1
            continue
        if not in_campaign_block:
            idx += 1
            continue
        if line.startswith("Meta Platforms"):
            break

        if line.startswith("FB_") and "$" not in line:
            campaign_name = " ".join(line.split())
            idx += 1

            standalone_amount = 0
            fallback_amount = 0
            while idx < len(lines):
                current = lines[idx]
                if current.startswith("Meta Platforms"):
                    break
                if current.startswith("FB_") and "$" not in current:
                    break

                amount_only = re.fullmatch(r"\$([\d\.,]+)", current)
                if amount_only:
                    standalone_amount = clp_to_int(amount_only.group(1))
                    idx += 1
                    continue

                amount_trailing = re.search(r"\$([\d\.,]+)\s*$", current)
                if amount_trailing and not current.startswith("FB_") and not current.startswith("De "):
                    fallback_amount += clp_to_int(amount_trailing.group(1))

                idx += 1

            amount = standalone_amount if standalone_amount > 0 else fallback_amount
            if amount > 0:
                campaigns.append({"campaignName": campaign_name, "amount": amount})
            continue

        idx += 1

    return campaigns


def parse_meta_receipt_pdf(path: Path, warnings: list[ParseWarning], month_hint: str) -> dict[str, Any] | None:
    text = extract_text_pypdf(path)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    flat = " | ".join(lines)

    flat_normalized = normalize_text_for_search(flat)

    tx_m = re.search(
        r"Identificador de la transacci(?:ÃƒÆ’Ã‚Â³n|ÃƒÂ³n|Ã³n|on)\s*[:|]?\s*([0-9]{10,}-[0-9]{10,})",
        flat,
        re.IGNORECASE,
    )
    amount_m = re.search(r"(Pagado|Fondos agregados)\s*[:|]?\s*\$([\d\.,]+)", flat, re.IGNORECASE)
    account_m = re.search(r"Identificador de la cuenta\s*[:|]?\s*([0-9]+)", flat, re.IGNORECASE)
    method_m = re.search(r"M(?:ÃƒÆ’Ã‚Â©|ÃƒÂ©|Ã©|e)todo de pago\s*[:|]?\s*([^|]+)", flat, re.IGNORECASE)
    payment_reference_m = re.search(r"N(?:ÃƒÆ’Ã‚Âº|ÃƒÂº|Ãº|u)mero de referencia\s*[:|]?\s*([A-Za-z0-9]+)", flat, re.IGNORECASE)
    if not payment_reference_m:
        payment_reference_m = re.search(r"numero\s+de\s+referencia\s*[:|]?\s*([A-Za-z0-9]{8,12})", flat_normalized, re.IGNORECASE)
    date_m = re.search(
        r"Fecha de nota de pago pendiente/comprobante de pago\s*[:|]?\s*([0-9]{1,2}\s+[a-zA-ZÃƒÆ’Ã‚Â¡ÃƒÆ’Ã‚Â©ÃƒÆ’Ã‚Â­ÃƒÆ’Ã‚Â³ÃƒÆ’Ã‚ÂºÃƒÆ’Ã‚Â±Ã¡Ã©Ã­Ã³ÃºÃ±\.]+\s+[0-9]{4})",
        flat,
        re.IGNORECASE,
    )

    tx_id = tx_m.group(1).strip() if tx_m else ""
    if not tx_id:
        # Fallback: muchas boletas vienen con el ID en el nombre del archivo.
        tx_file_m = re.search(r"([0-9]{10,}-[0-9]{10,})", path.name)
        tx_id = tx_file_m.group(1).strip() if tx_file_m else ""
    if not tx_id:
        warnings.append(ParseWarning(source=path.name, message="Could not parse transaction id in Meta receipt PDF."))
        return None

    if not amount_m:
        warnings.append(ParseWarning(source=path.name, message="Could not parse amount/status in Meta receipt PDF."))
        return None
    status = amount_m.group(1).strip()
    amount = clp_to_int(amount_m.group(2))
    if amount == 0:
        warnings.append(ParseWarning(source=path.name, message="Parsed zero amount in Meta receipt PDF."))
        return None

    date_iso = ""
    if date_m:
        try:
            date_iso = iso_from_meta_receipt_date(date_m.group(1))
        except ValueError as exc:
            warnings.append(ParseWarning(source=path.name, message=str(exc)))

    if not date_iso:
        filename_date_m = re.match(r"(\d{4}-\d{2}-\d{2})T", path.name)
        date_iso = filename_date_m.group(1) if filename_date_m else ""
    if not date_iso and month_hint:
        date_iso = f"{month_hint}-01"
    if not date_iso:
        warnings.append(ParseWarning(source=path.name, message="Could not infer date in Meta receipt PDF."))
        return None

    date_month = month_key(date_iso)
    resolved_month = date_month or month_hint
    if month_hint and date_month and month_hint != date_month:
        warnings.append(
            ParseWarning(
                source=path.name,
                message=(
                    f"Receipt folder month {month_hint} differs from transaction date month {date_month}; "
                    "using the transaction date."
                ),
            )
        )
    campaigns = parse_meta_receipt_campaigns(lines)

    return {
        "month": resolved_month,
        "date": date_iso,
        "transactionId": tx_id,
        "paymentMethod": method_m.group(1).strip() if method_m else "No disponible",
        "paymentReference": payment_reference_m.group(1).strip().upper() if payment_reference_m else "",
        "status": status,
        "amount": amount,
        "accountId": account_m.group(1).strip() if account_m else "",
        "sourceFile": str(path.relative_to(ROOT)),
        "campaigns": campaigns,
    }


def parse_meta_monthly_invoice_pdf(path: Path, warnings: list[ParseWarning]) -> dict[str, Any] | None:
    """Parse Meta's NET 30 monthly invoice format with campaign rows."""
    text = extract_text_pypdf(path)
    if "Invoice #:" not in text or "Billing Period:" not in text or "Invoice Total:" not in text:
        return None

    invoice_number_m = re.search(r"Invoice\s*#:\s*(\d+)", text, re.IGNORECASE)
    invoice_date_m = re.search(r"Invoice Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
    billing_period_m = re.search(r"Billing Period:\s*([A-Za-z]{3})-(\d{2})", text, re.IGNORECASE)
    account_m = re.search(r"Account Id\s*/\s*Group:\s*(\d+)", text, re.IGNORECASE)
    total_m = re.search(r"Invoice Total:\s*([\d,]+)", text, re.IGNORECASE)
    if not invoice_number_m or not invoice_date_m or not billing_period_m or not total_m:
        warnings.append(
            ParseWarning(source=path.name, message="Could not parse required fields from Meta monthly invoice.")
        )
        return None

    invoice_number = invoice_number_m.group(1)
    invoice_date = datetime.strptime(invoice_date_m.group(1), "%d-%b-%Y").strftime("%Y-%m-%d")
    billing_month = datetime.strptime(
        f"{billing_period_m.group(1)}-{billing_period_m.group(2)}", "%b-%y"
    ).strftime("%Y-%m")
    total_amount = clp_to_int(total_m.group(1))
    account_id = account_m.group(1) if account_m else ""

    brand, account_name = normalize_meta_folder_brand(path.parent.parent.name)
    campaign_totals: dict[str, int] = defaultdict(int)
    details: list[dict[str, Any]] = []
    line_re = re.compile(r"^\s*(\d+)\s+(.+?)\s+(-?[\d,]+)\s*$")
    for raw_line in text.splitlines():
        line_m = line_re.match(raw_line)
        if not line_m:
            continue
        label = re.sub(r"^Instagram\s+-\s+", "", line_m.group(2).strip(), flags=re.IGNORECASE)
        if "FB_" not in label and "Coupons" not in label:
            continue
        amount = clp_to_int(line_m.group(3))
        if amount == 0:
            continue
        campaign_totals[label] += amount
        details.append(
            {
                "description": label,
                "lineNumber": int(line_m.group(1)),
                "amount": amount,
            }
        )

    detail_total = sum(int(item.get("amount", 0) or 0) for item in details)
    if detail_total != total_amount:
        warnings.append(
            ParseWarning(
                source=path.name,
                message=f"Monthly invoice detail sum ({detail_total}) does not match total ({total_amount}).",
            )
        )

    campaigns = sorted(
        (
            {"name": campaign_name, "amount": amount}
            for campaign_name, amount in campaign_totals.items()
            if amount > 0
        ),
        key=lambda item: (-item["amount"], item["name"]),
    )
    document_file = path.relative_to(ROOT).as_posix()
    folder_month = month_key_from_folder_name(path.parent.name)
    if folder_month and folder_month != billing_month:
        warnings.append(
            ParseWarning(
                source=path.name,
                message=(
                    f"Monthly invoice folder month {folder_month} differs from billing period {billing_month}; "
                    "using the billing period."
                ),
            )
        )
    notes = [
        "Factura mensual Meta NET 30 asignada según su período de facturación; los comprobantes del mismo mes se incorporan por separado según su fecha de transacción."
    ]
    if brand == "Almagro Inmobiliaria":
        notes.append("Meta agrupa esta cuenta como ALMAGRO S A y no separa Inmobiliaria/Propiedades.")

    return {
        "id": invoice_number,
        "sourceFile": document_file,
        "pdfFile": document_file,
        "documentFile": document_file,
        "platform": "Meta",
        "brand": brand,
        "month": billing_month,
        "invoiceDate": invoice_date,
        "periodStart": f"{billing_month}-01",
        "periodEnd": last_day_of_month(billing_month),
        "dueDate": "",
        "currency": "CLP",
        "accountName": account_name,
        "accountId": account_id,
        "totalAmount": total_amount,
        "summaryBreakdown": [{"label": "Invoice Total", "amount": total_amount}],
        "details": details,
        "campaigns": campaigns,
        "notes": notes,
    }


def parse_meta_receipt_folders(
    root_dir: Path,
    warnings: list[ParseWarning],
    month_filter: str | None = None,
) -> list[dict[str, Any]]:
    if not root_dir.exists():
        return []

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    monthly_invoices: list[dict[str, Any]] = []

    def append_parsed_receipt(
        *,
        brand: str,
        account_name: str,
        source_dir: str,
        month_hint: str,
        pdf_file: Path,
    ) -> None:
        parsed = parse_meta_receipt_pdf(pdf_file, warnings, month_hint)
        if not parsed:
            return

        month = parsed["month"]
        key = (brand, account_name, month)
        if key not in grouped:
            grouped[key] = {
                "details": [],
                "seenTx": set(),
                "accountIds": [],
                "sourceDir": source_dir,
                "campaignTotals": defaultdict(int),
                "campaignDetails": [],
            }
        current = grouped[key]
        tx_id = parsed["transactionId"]
        if tx_id in current["seenTx"]:
            parsed_ref = str(parsed.get("paymentReference", "")).strip().upper()
            if not parsed_ref:
                return

            for detail in current["details"]:
                if str(detail.get("transactionId", "")).strip() != tx_id:
                    continue
                existing_ref = str(detail.get("paymentReference", "")).strip().upper()
                if existing_ref and existing_ref != parsed_ref:
                    warnings.append(
                        ParseWarning(
                            source=pdf_file.name,
                            message=(
                                f"Duplicate transaction id {tx_id} with conflicting payment references: "
                                f"{existing_ref} vs {parsed_ref}."
                            ),
                        )
                    )
                    continue
                if not existing_ref:
                    detail["paymentReference"] = parsed_ref
                    parsed_method = str(parsed.get("paymentMethod", "")).strip()
                    if parsed_method:
                        detail["paymentMethod"] = parsed_method
                    if str(detail.get("status", "")).strip() == "Fondos agregados":
                        detail["status"] = "Pagado"

            for campaign_detail in current["campaignDetails"]:
                if str(campaign_detail.get("transactionId", "")).strip() != tx_id:
                    continue
                if not str(campaign_detail.get("paymentReference", "")).strip():
                    campaign_detail["paymentReference"] = parsed_ref
            return

        current["seenTx"].add(tx_id)
        if parsed["accountId"]:
            current["accountIds"].append(parsed["accountId"])
        detail_status = str(parsed.get("status", "")).strip()
        parsed_ref = str(parsed.get("paymentReference", "")).strip().upper()
        if detail_status == "Fondos agregados" and parsed_ref:
            detail_status = "Pagado"

        current["details"].append(
            {
                "date": parsed["date"],
                "transactionId": tx_id,
                "paymentMethod": parsed["paymentMethod"],
                "paymentReference": parsed_ref,
                "status": detail_status,
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
                        "paymentReference": parsed.get("paymentReference", ""),
                    }
                )

    for brand_dir in sorted(root_dir.iterdir()):
        if not brand_dir.is_dir():
            continue
        brand, account_name = normalize_meta_folder_brand(brand_dir.name)

        for month_dir in sorted(brand_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            month_hint = month_key_from_folder_name(month_dir.name)
            if month_filter and month_hint != month_filter:
                continue

            pdf_files = sorted(month_dir.glob("*.pdf"))
            parsed_formal_by_file = {
                pdf_file: parsed
                for pdf_file in pdf_files
                if (parsed := parse_meta_monthly_invoice_pdf(pdf_file, warnings)) is not None
            }
            formal_invoice_files = set(parsed_formal_by_file)
            parsed_formal_invoices = list(parsed_formal_by_file.values())
            if parsed_formal_invoices:
                monthly_invoices.extend(parsed_formal_invoices)

            for pdf_file in pdf_files:
                if pdf_file in formal_invoice_files:
                    continue
                append_parsed_receipt(
                    brand=brand,
                    account_name=account_name,
                    source_dir=str(month_dir.relative_to(ROOT)),
                    month_hint=month_hint,
                    pdf_file=pdf_file,
                )

    for pdf_file in sorted(root_dir.glob("*.pdf")):
        parsed = parse_meta_receipt_pdf(pdf_file, warnings, "")
        if not parsed:
            continue
        account_id = str(parsed.get("accountId", "")).strip()
        brand, account_name = normalize_meta_account_brand(account_id)
        if not brand:
            warnings.append(
                ParseWarning(
                    source=pdf_file.name,
                    message=(
                        "Root-level Meta receipt skipped because account id "
                        f"'{account_id or 'N/A'}' is unknown. Move it to a brand/month folder."
                    ),
                )
            )
            continue

        # Re-process through shared path to keep grouping and de-duplication logic in one place.
        append_parsed_receipt(
            brand=brand,
            account_name=account_name,
            source_dir=str(root_dir.relative_to(ROOT)),
            month_hint="",
            pdf_file=pdf_file,
        )

    invoices: list[dict[str, Any]] = []
    for (brand, account_name, month), values in sorted(grouped.items()):
        details = sorted(values["details"], key=lambda row: row["date"], reverse=True)
        if not details:
            continue

        total_billed = sum(item["amount"] for item in details if item["status"] == "Pagado")
        total_funds = sum(item["amount"] for item in details if item["status"] == "Fondos agregados")
        account_id = values["accountIds"][0] if values["accountIds"] else ""
        period_start = f"{month}-01"
        period_end = last_day_of_month(month)
        campaigns = sorted(
            (
                {"name": campaign_name, "amount": amount}
                for campaign_name, amount in values["campaignTotals"].items()
                if amount > 0
            ),
            key=lambda item: (-item["amount"], item["name"]),
        )
        campaign_details = sorted(
            values.get("campaignDetails", []),
            key=lambda item: (item.get("date", ""), item.get("transactionId", ""), item.get("name", "")),
        )

        notes = [f"Montos agregados desde comprobantes en carpeta: {values['sourceDir']}."]
        if brand == "Almagro Inmobiliaria":
            notes.append("Meta agrupa esta cuenta como ALMAGRO S A y no separa Inmobiliaria/Propiedades.")

        invoices.append(
            {
                "id": f"meta-{brand.lower().replace(' ', '-')}-{month}",
                "sourceFile": values["sourceDir"],
                "pdfFile": "",
                "documentFile": "",
                "platform": "Meta",
                "brand": brand,
                "month": month,
                "invoiceDate": details[0]["date"],
                "periodStart": period_start,
                "periodEnd": period_end,
                "dueDate": "",
                "currency": "CLP",
                "accountName": account_name,
                "accountId": account_id,
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
    invoices.extend(monthly_invoices)
    return invoices


def collect_meta_payment_references(invoices: list[dict[str, Any]]) -> set[str]:
    references: set[str] = set()
    for invoice in invoices:
        if str(invoice.get("platform", "")).strip() != "Meta":
            continue
        details = invoice.get("details", []) if isinstance(invoice.get("details"), list) else []
        for detail in details:
            ref = str(detail.get("paymentReference", "")).strip().upper()
            if ref:
                references.add(ref)

        campaign_details = invoice.get("campaignDetails", []) if isinstance(invoice.get("campaignDetails"), list) else []
        for detail in campaign_details:
            ref = str(detail.get("paymentReference", "")).strip().upper()
            if ref:
                references.add(ref)
    return references


def extract_card_statement_text(path: Path, warnings: list[ParseWarning]) -> str:
    text = extract_text_pypdf(path)
    if len(re.sub(r"\s+", "", text)) >= 200 and "FACEBK" in text.upper():
        return text

    try:
        with tempfile.TemporaryDirectory(prefix="meta-cartola-ocr-") as tmp_dir:
            prefix = Path(tmp_dir) / "page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "250", str(path), str(prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            images = sorted(Path(tmp_dir).glob("page-*.png"))
            if not images:
                warnings.append(ParseWarning(source=path.name, message="OCR fallback did not produce page images."))
                return text

            chunks: list[str] = []
            for image in images:
                page_text = subprocess.check_output(
                    ["tesseract", str(image), "stdout", "-l", "spa+eng", "--psm", "6"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                chunks.append(page_text)
            ocr_text = "\n".join(chunks)
            if len(re.sub(r"\s+", "", ocr_text)) >= len(re.sub(r"\s+", "", text)):
                return ocr_text
    except FileNotFoundError:
        warnings.append(
            ParseWarning(
                source=path.name,
                message="OCR fallback unavailable (missing 'pdftoppm' or 'tesseract' in PATH).",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        warnings.append(ParseWarning(source=path.name, message=f"OCR fallback failed: {exc}"))

    return text


def parse_date_dmy_to_iso(value: str) -> str:
    match = DATE_DMY_RE.match(str(value).strip())
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def parse_google_cloud_card_charges(root_dir: Path, warnings: list[ParseWarning]) -> list[dict[str, Any]]:
    if not root_dir.exists() or xlrd is None:
        return []

    charges: list[dict[str, Any]] = []
    for xls_file in sorted(root_dir.glob("*.xls")):
        try:
            workbook = xlrd.open_workbook(str(xls_file))
            sheet = workbook.sheet_by_index(0)
        except Exception as exc:
            warnings.append(ParseWarning(source=xls_file.name, message=f"Could not read .xls cartola: {exc}"))
            continue

        for row_idx in range(sheet.nrows):
            description = str(sheet.cell_value(row_idx, 2) or "").strip()
            if "google cloud" not in description.lower():
                continue
            amount_origin = clp_to_int(str(sheet.cell_value(row_idx, 5) or "").strip())
            if amount_origin <= 0:
                continue
            charges.append(
                {
                    "statementReference": str(sheet.cell_value(row_idx, 0) or "").strip(),
                    "cartolaDate": parse_date_dmy_to_iso(str(sheet.cell_value(row_idx, 1) or "").strip()),
                    "cartolaDateRaw": str(sheet.cell_value(row_idx, 1) or "").strip(),
                    "descriptionCharge": description,
                    "amountOriginal": amount_origin,
                    "amountUsd": decimal_comma_to_float(str(sheet.cell_value(row_idx, 8) or "").strip()),
                    "sourceFile": str(xls_file.relative_to(ROOT)),
                }
            )
    return charges


def parse_meta_card_statement_charges(
    root_dir: Path, warnings: list[ParseWarning], known_references: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    if not root_dir.exists():
        return {}

    known_references = known_references or set()
    ambiguous_pairs = {
        ("5", "S"),
        ("S", "5"),
        ("0", "O"),
        ("O", "0"),
        ("1", "I"),
        ("I", "1"),
        ("1", "L"),
        ("L", "1"),
        ("6", "G"),
        ("G", "6"),
        ("8", "B"),
        ("B", "8"),
        ("2", "Z"),
        ("Z", "2"),
        ("7", "T"),
        ("T", "7"),
        ("9", "S"),
        ("S", "9"),
        ("I", "J"),
        ("J", "I"),
    }

    def normalize_code(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value).upper())

    def substitution_cost(a: str, b: str) -> int:
        if a == b:
            return 0
        if (a, b) in ambiguous_pairs:
            return 1
        return 2

    def weighted_edit_distance(a: str, b: str) -> int:
        n, m = len(a), len(b)
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0] = i
        for j in range(1, m + 1):
            dp[0][j] = j
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                dp[i][j] = min(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + substitution_cost(a[i - 1], b[j - 1]),
                )
        return dp[n][m]

    def resolve_to_known_reference(raw_code: str) -> tuple[str, str]:
        code = normalize_code(raw_code)
        if not code or not known_references:
            return code, ""
        if code in known_references:
            return code, ""

        best_distance = 99
        best_refs: list[str] = []
        for candidate in known_references:
            if abs(len(candidate) - len(code)) > 2:
                continue
            distance = weighted_edit_distance(code, candidate)
            if distance < best_distance:
                best_distance = distance
                best_refs = [candidate]
            elif distance == best_distance:
                best_refs.append(candidate)

        if best_distance <= 2 and len(best_refs) == 1:
            return best_refs[0], code
        return code, ""

    def register_charge(entry: dict[str, Any], source_name: str) -> None:
        charge_code = str(entry.get("chargeCode", "")).strip().upper()
        if not charge_code:
            return
        existing = charges_by_code.get(charge_code)
        if existing:
            existing_origin = int(existing.get("amountOriginal", 0) or 0)
            incoming_origin = int(entry.get("amountOriginal", 0) or 0)
            existing_usd = float(existing.get("amountUsd", 0.0) or 0.0)
            incoming_usd = float(entry.get("amountUsd", 0.0) or 0.0)

            if existing_origin != incoming_origin or abs(existing_usd - incoming_usd) > 0.01:
                warnings.append(
                    ParseWarning(
                        source=source_name,
                        message=(
                            f"Duplicate FACEBK code with different amounts: {charge_code} "
                            f"({existing_origin}/{existing_usd:.2f} vs {incoming_origin}/{incoming_usd:.2f})."
                        ),
                    )
                )

            merged_sources = []
            for source in [existing.get("sourceFile", ""), *existing.get("sourceFiles", []), entry.get("sourceFile", "")]:
                source_str = str(source).strip()
                if source_str and source_str not in merged_sources:
                    merged_sources.append(source_str)
            entry["sourceFiles"] = merged_sources

        if "sourceFiles" not in entry:
            source_str = str(entry.get("sourceFile", "")).strip()
            entry["sourceFiles"] = [source_str] if source_str else []

        charges_by_code[charge_code] = entry

    def extract_charge_code(raw_line: str) -> str:
        line = str(raw_line or "")
        direct = FACEBK_CODE_RE.search(line.upper())
        if direct:
            return direct.group(1).upper()

        # OCR on cartolas can drop letters from "FACEBK"; accept STAR code when
        # the line still looks like a Meta/Facebook ads charge context.
        line_upper = line.upper()
        if any(token in line_upper for token in ("FB.ME/ADS", "FBME/ADS", "FACE", "META", "ADS")):
            star_match = STAR_CHARGE_CODE_RE.search(line_upper)
            if star_match:
                return star_match.group(1).upper()
        return ""

    def parse_cartola_xls(file_path: Path) -> tuple[int, int]:
        if xlrd is None:
            warnings.append(
                ParseWarning(source=file_path.name, message="xlrd is not installed; skipping .xls cartola parsing.")
            )
            return 0, 0

        try:
            workbook = xlrd.open_workbook(str(file_path))
            sheet = workbook.sheet_by_index(0)
        except Exception as exc:
            warnings.append(ParseWarning(source=file_path.name, message=f"Could not read .xls cartola: {exc}"))
            return 0, 0

        parsed_rows = 0
        reconciled_rows = 0
        for row_idx in range(sheet.nrows):
            desc_raw = str(sheet.cell_value(row_idx, 2) or "").strip()
            charge_code_raw = extract_charge_code(desc_raw)
            if not charge_code_raw:
                continue

            charge_code, reconciled_from = resolve_to_known_reference(charge_code_raw)
            if reconciled_from:
                reconciled_rows += 1
            amount_origin_raw = str(sheet.cell_value(row_idx, 5) or "").strip()
            amount_usd_raw = str(sheet.cell_value(row_idx, 8) or "").strip()
            amount_origin = clp_to_int(amount_origin_raw)
            amount_usd = decimal_comma_to_float(amount_usd_raw)
            if amount_origin <= 0:
                continue

            parsed_rows += 1
            entry = {
                "chargeCode": charge_code,
                "descriptionCharge": f"FACEBK *{charge_code}",
                "sourceCodeRaw": charge_code_raw,
                "reconciledFromRawCode": reconciled_from,
                "cartolaDate": parse_date_dmy_to_iso(str(sheet.cell_value(row_idx, 1) or "").strip()),
                "cartolaDateRaw": str(sheet.cell_value(row_idx, 1) or "").strip(),
                "amountOriginal": amount_origin,
                "amountOriginalRaw": amount_origin_raw,
                "amountUsd": amount_usd,
                "amountUsdRaw": amount_usd_raw,
                "sourceFile": str(file_path.relative_to(ROOT)),
            }
            register_charge(entry, file_path.name)

        if parsed_rows == 0:
            warnings.append(ParseWarning(source=file_path.name, message="No FACEBK rows parsed from .xls cartola."))
        return parsed_rows, reconciled_rows

    charges_by_code: dict[str, dict[str, Any]] = {}
    reconciled_codes = 0
    for pdf_file in sorted(root_dir.glob("*.pdf")):
        text = extract_card_statement_text(pdf_file, warnings)
        if not text:
            continue

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        parsed_rows = 0
        for idx, raw_line in enumerate(lines):
            line = " ".join(raw_line.split())
            charge_code_raw = extract_charge_code(line)
            if not charge_code_raw:
                continue

            charge_code, reconciled_from = resolve_to_known_reference(charge_code_raw)
            if reconciled_from:
                reconciled_codes += 1
            code_match = re.search(rf"\*{re.escape(charge_code_raw)}", line, re.IGNORECASE)
            tail = line[code_match.end() :] if code_match else line
            amount_tokens = DECIMAL_COMMA_RE.findall(tail)
            if len(amount_tokens) < 2:
                amount_tokens = DECIMAL_COMMA_RE.findall(line)
            if len(amount_tokens) < 2 and idx + 1 < len(lines):
                amount_tokens.extend(DECIMAL_COMMA_RE.findall(lines[idx + 1]))
            if len(amount_tokens) < 2:
                continue

            amount_origin_raw = amount_tokens[-2]
            amount_usd_raw = amount_tokens[-1]
            amount_origin = clp_to_int(amount_origin_raw)
            amount_usd = decimal_comma_to_float(amount_usd_raw)

            if amount_origin <= 0:
                continue

            parsed_rows += 1
            entry = {
                "chargeCode": charge_code,
                "descriptionCharge": f"FACEBK *{charge_code}",
                "sourceCodeRaw": charge_code_raw,
                "reconciledFromRawCode": reconciled_from,
                "amountOriginal": amount_origin,
                "amountOriginalRaw": amount_origin_raw,
                "amountUsd": amount_usd,
                "amountUsdRaw": amount_usd_raw,
                "sourceFile": str(pdf_file.relative_to(ROOT)),
            }
            register_charge(entry, pdf_file.name)

        if parsed_rows == 0:
            warnings.append(
                ParseWarning(source=pdf_file.name, message="No FACEBK charge rows parsed from card statement PDF.")
            )

    for xls_file in sorted(root_dir.glob("*.xls")):
        parsed_rows, reconciled_rows = parse_cartola_xls(xls_file)
        if parsed_rows:
            reconciled_codes += reconciled_rows

    for xlsx_file in sorted(root_dir.glob("*.xlsx")):
        parsed_rows, reconciled_rows = parse_cartola_xls(xlsx_file)
        if parsed_rows:
            reconciled_codes += reconciled_rows

    if reconciled_codes:
        warnings.append(
            ParseWarning(
                source="Cartola TC",
                message=f"Reconciled {reconciled_codes} FACEBK codes to known Meta payment references.",
            )
        )

    return charges_by_code


def parse_google_invoice(path: Path, warnings: list[ParseWarning]) -> dict[str, Any]:
    filename = path.name
    brand_key_candidates: list[str] = [path.parent.name, path.parent.parent.name, filename]
    brand = "Pilares"
    is_gcloud = False
    for candidate in brand_key_candidates:
        normalized = normalize_key(candidate)
        if "gcloud" in normalized or "googlecloud" in normalized:
            brand = "GCloud"
            is_gcloud = True
            break
        if "almagropropiedades" in normalized:
            brand = "Almagro Propiedades"
            break
        if "almagro" in normalized:
            brand = "Almagro Inmobiliaria"
            break
        if "socovesa" in normalized:
            brand = "Socovesa"
            break
        if "pilares" in normalized:
            brand = "Pilares"
            break

    text = extract_text_pypdf(path)
    lines = extract_layout_lines(path)
    if "google cloud" in text.lower():
        brand = "GCloud"
        is_gcloud = True

    invoice_number_m = re.search(r"NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºmero de factura:\s*(\d+)", text)
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
        if normalize_key(line).startswith("descripcion"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("Subtotal en CLP"):
            in_table = False
            continue
        if line.startswith("Si tiene alguna pregunta"):
            continue
        normalized_line = normalize_key(line)
        if line.startswith("Factura") or normalized_line.startswith("numerodefactura"):
            continue

        invalid_m = re.match(r"^(Actividad no vÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lida\.\.\.)\s+(-?[\d,]+)$", line)
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

    campaigns = [
        {"name": item["description"], "amount": item["amount"]}
        for item in details
        if item.get("description") and item.get("quantity") is not None and item.get("amount", 0) > 0
    ]
    if is_gcloud and not campaigns and total_amount > 0:
        campaigns = [{"name": "Google Cloud", "amount": total_amount}]

    gcloud_charge = None
    if is_gcloud and total_amount > 0:
        for charge in parse_google_cloud_card_charges(META_CARD_STATEMENTS_DIR, warnings):
            if int(charge.get("amountOriginal", 0) or 0) == total_amount:
                gcloud_charge = charge
                break

    if gcloud_charge and gcloud_charge.get("cartolaDate"):
        invoice_date_iso = str(gcloud_charge.get("cartolaDate", ""))

    try:
        document_file = path.relative_to(ROOT).as_posix()
    except ValueError:
        document_file = f"pdfs/{filename}"

    return {
        "id": invoice_number,
        "sourceFile": filename,
        "pdfFile": document_file,
        "documentFile": document_file,
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
        "campaigns": campaigns,
        "cardCharge": gcloud_charge or {},
        "notes": [],
    }


def parse_meta_invoice(path: Path, warnings: list[ParseWarning]) -> dict[str, Any]:
    filename = path.name
    is_pilares = "Pilares" in filename
    is_socovesa = "Socovesa" in filename
    if is_pilares:
        brand = "Pilares"
        account_name = "Pilares"
    elif is_socovesa:
        brand = "Socovesa"
        account_name = "Socovesa"
    else:
        brand = "Almagro Inmobiliaria"
        account_name = "ALMAGRO S A"

    text = extract_text_pypdf(path)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    account_m = re.search(r"Cuenta:\s*([0-9]+)", text)
    account_id = account_m.group(1) if account_m else ""

    period_m = re.search(r"Informe de facturaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n:\s*(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    period_start_iso = iso_from_dmy(period_m.group(1)) if period_m else "1970-01-01"
    period_end_iso = iso_from_dmy(period_m.group(2)) if period_m else "1970-01-01"

    total_billed_m = re.search(r"Importe total facturado\s+\$([\d\.]+)\s+CLP", text)
    total_funds_m = re.search(r"Total de fondos agregado\s+\$([\d\.]+)\s+CLP", text)
    total_billed = clp_to_int(total_billed_m.group(1)) if total_billed_m else 0
    total_funds = clp_to_int(total_funds_m.group(1)) if total_funds_m else 0

    default_method_m = re.search(r"MÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©todo de pago:\s*(.+)", text)
    default_method = default_method_m.group(1).strip() if default_method_m else "No disponible"

    date_re = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4})\s*(.*)$")
    amount_status_re = re.compile(r"\$([\d\.]+)\s+CLP\s+(Pagado|Fondos agregados)\s*$")
    method_re = re.compile(r"(Visa\s+ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â·+\s*\d{4}|No disponible)")

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

    if total_billed == 0 and not details:
        export_fallback = parse_meta_invoice_activity_export(text, filename, warnings)
        if export_fallback:
            period_start_iso = export_fallback["periodStart"]
            period_end_iso = export_fallback["periodEnd"]
            invoice_date_iso = export_fallback["invoiceDate"]
            account_id = export_fallback["accountId"]
            total_billed = export_fallback["totalBilled"]
            total_funds = export_fallback["totalFunds"]
            details = export_fallback["details"]
        else:
            ocr_fallback = parse_meta_invoice_ocr_fallback(path, warnings)
            if ocr_fallback:
                period_start_iso = ocr_fallback["periodStart"]
                period_end_iso = ocr_fallback["periodEnd"]
                invoice_date_iso = ocr_fallback["invoiceDate"]
                account_id = ocr_fallback["accountId"]
                total_billed = ocr_fallback["totalBilled"]
                total_funds = ocr_fallback["totalFunds"]
                details = ocr_fallback["details"]

    expected_total = META_TOTAL_OVERRIDES.get(filename)
    if expected_total is not None:
        paid_sum = sum(row["amount"] for row in details if row["status"] == "Pagado")
        adjustment = expected_total - paid_sum
        if adjustment != 0:
            adjustment_date = details[0]["date"] if details else period_end_iso
            details.append(
                {
                    "date": adjustment_date,
                    "transactionId": f"AJUSTE-MANUAL-{month_key(period_start_iso)}",
                    "paymentMethod": "No disponible",
                    "status": "Pagado",
                    "amount": adjustment,
                }
            )
            details.sort(key=lambda row: row["date"], reverse=True)
        total_billed = expected_total

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
    if brand == "Almagro Inmobiliaria":
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
        "accountName": account_name,
        "accountId": account_id,
        "totalAmount": total_billed,
        "summaryBreakdown": [
            {"label": "Importe total facturado", "amount": total_billed},
            {"label": "Total de fondos agregado", "amount": total_funds},
        ],
        "details": details,
        "campaigns": [],
        "notes": notes,
    }


def parse_excel_sheet_rows(path: Path, sheet_name: str | None = None) -> tuple[str, dict[int, dict[str, str]]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

    with zipfile.ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_elements = workbook.findall("m:sheets/m:sheet", ns)
        if not sheet_elements:
            raise ValueError(f"No sheets found in {path.name}")

        selected_sheet = None
        if sheet_name:
            for candidate in sheet_elements:
                if candidate.attrib.get("name", "").strip() == sheet_name.strip():
                    selected_sheet = candidate
                    break
            if selected_sheet is None:
                raise ValueError(f"Sheet '{sheet_name}' not found in {path.name}")
        else:
            selected_sheet = sheet_elements[0]

        selected_sheet_name = selected_sheet.attrib.get("name", "")
        rel_id = selected_sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_target = ""
        for rel in rels.findall("r:Relationship", rel_ns):
            if rel.attrib.get("Id") == rel_id:
                rel_target = rel.attrib["Target"]
                break
        if not rel_target:
            raise ValueError(f"Could not resolve sheet relationship in {path.name}")
        rel_target = rel_target.lstrip("/")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst.findall("m:si", ns):
                text = "".join(t.text or "" for t in si.findall(".//m:t", ns))
                shared_strings.append(text)

        sheet_path = rel_target if rel_target.startswith("xl/") else f"xl/{rel_target}"
        sheet = ET.fromstring(zf.read(sheet_path))
        rows: dict[int, dict[str, str]] = {}
        for row in sheet.findall("m:sheetData/m:row", ns):
            row_idx = int(row.attrib["r"])
            row_map: dict[str, str] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "")
                col = "".join(ch for ch in ref if ch.isalpha())
                if not col:
                    continue

                cell_type = cell.attrib.get("t")
                value_el = cell.find("m:v", ns)
                inline_text = "".join(t.text or "" for t in cell.findall("m:is//m:t", ns))

                if cell_type == "inlineStr":
                    row_map[col] = inline_text
                    continue

                if value_el is None:
                    continue

                val = value_el.text or ""
                if cell_type == "s" and val:
                    row_map[col] = shared_strings[int(val)] if int(val) < len(shared_strings) else ""
                else:
                    row_map[col] = val
            if row_map:
                rows[row_idx] = row_map
        return selected_sheet_name, rows


def parse_rs_excel(path: Path, warnings: list[ParseWarning]) -> list[dict[str, Any]]:
    try:
        _, rows = parse_excel_sheet_rows(path, sheet_name="RS")
    except Exception as exc:
        if "Sheet 'RS' not found" not in str(exc):
            warnings.append(ParseWarning(source=path.name, message=f"Could not parse RS sheet: {exc}"))
        return []

    base_year = datetime.utcnow().year
    try:
        first_sheet_name, _ = parse_excel_sheet_rows(path)
        inferred_month = month_key_from_spanish_name(first_sheet_name)
        base_year = int(inferred_month[:4])
    except Exception:
        pass

    parsed_rules: list[dict[str, Any]] = []
    for row_idx in sorted(rows):
        if row_idx < 3:
            continue
        row = rows[row_idx]
        brand = row.get("B", "").strip()
        platform = row.get("C", "").strip()
        legal_entity = row.get("D", "").strip()
        month_raw = row.get("E", "").strip()
        expense_raw = row.get("F", "").strip()
        percentage_raw = row.get("G", "").strip()

        if not brand or not platform or not legal_entity or not month_raw or not percentage_raw:
            continue
        if platform not in {"Google", "Meta"}:
            continue

        try:
            month_number = int(round(float(month_raw)))
            percentage = float(percentage_raw)
        except ValueError:
            warnings.append(
                ParseWarning(
                    source=path.name,
                    message=f"Invalid RS values on row {row_idx}: month='{month_raw}', pct='{percentage_raw}'.",
                )
            )
            continue

        if month_number < 1 or month_number > 12:
            warnings.append(
                ParseWarning(
                    source=path.name,
                    message=f"Invalid RS month number on row {row_idx}: {month_number}.",
                )
            )
            continue

        expense = None
        if expense_raw:
            try:
                expense = int(round(float(expense_raw)))
            except ValueError:
                expense = None

        parsed_rules.append(
            {
                "month": f"{base_year:04d}-{month_number:02d}",
                "monthNumber": f"{month_number:02d}",
                "brand": brand,
                "platform": platform,
                "legalEntity": legal_entity,
                "percentage": percentage,
                "expense": expense,
            }
        )

    # Deduplicate repeated rows across files while preserving deterministic order.
    deduped: dict[tuple[str, str, str, str, float], dict[str, Any]] = {}
    for rule in parsed_rules:
        key = (
            rule["month"],
            rule["brand"],
            rule["platform"],
            rule["legalEntity"],
            rule["percentage"],
        )
        deduped[key] = rule

    return sorted(
        deduped.values(),
        key=lambda item: (
            item["month"],
            item["brand"],
            item["platform"],
            item["legalEntity"],
        ),
    )


def parse_reason_social_sheet(path: Path, warnings: list[ParseWarning]) -> list[dict[str, Any]]:
    sheet_candidates = [
        "Razón social",
        "Razon social",
        "Razón Social",
        "Razon Social",
    ]
    rows: dict[int, dict[str, str]] | None = None

    for sheet_name in sheet_candidates:
        try:
            _, rows = parse_excel_sheet_rows(path, sheet_name=sheet_name)
            break
        except Exception:
            continue

    if rows is None:
        try:
            workbook = load_workbook(path, data_only=True, read_only=True)
            normalized_target = normalize_key("Razon social")
            for sheet_name in workbook.sheetnames:
                if normalize_key(sheet_name) == normalized_target:
                    _, rows = parse_excel_sheet_rows(path, sheet_name=sheet_name)
                    break
        except Exception:
            rows = None

    if rows is None:
        warnings.append(
            ParseWarning(
                source=path.name,
                message="Could not parse reason-social sheet from Excel.",
            )
        )
        return []

    mappings: list[dict[str, Any]] = []
    for row_idx in sorted(rows):
        row = rows[row_idx]
        brand = row.get("C", "").strip()
        campaign = row.get("D", "").strip()
        legal_entity = row.get("E", "").strip()
        comuna = row.get("F", "").strip()
        project = row.get("G", "").strip()

        if not brand or not campaign or not legal_entity:
            continue
        if campaign.lower().startswith("proyecto") or campaign.lower().startswith("concatenar"):
            continue

        mappings.append(
            {
                "brand": brand,
                "brandGroup": normalize_brand_group(brand),
                "campaignName": campaign,
                "campaignKey": normalize_key(campaign),
                "legalEntity": legal_entity,
                "comuna": comuna,
                "project": project,
            }
        )

    return mappings


def split_desglose_filter(raw_filter: str) -> tuple[str, str, str]:
    value = raw_filter.strip()
    if not value:
        return "", "", ""
    lowered = value.lower()
    for prefix, brand_group in DESGLOSE_BRAND_PREFIXES:
        prefix_lower = prefix.lower()
        if lowered.startswith(prefix_lower):
            campaign_name = value[len(prefix) :].strip()
            return prefix, brand_group, campaign_name
    return "", "", ""

def parse_desglose_por_rs_sheet(path: Path, warnings: list[ParseWarning]) -> list[dict[str, Any]]:
    try:
        _, rows = parse_excel_sheet_rows(path, sheet_name="Desglose por RS")
    except Exception as exc:
        warnings.append(ParseWarning(source=path.name, message=f"Could not parse 'Desglose por RS' sheet: {exc}"))
        return []

    mappings: list[dict[str, Any]] = []
    for row_idx in sorted(rows):
        row = rows[row_idx]
        raw_filter = row.get("C", "").strip()
        comuna = row.get("D", "").strip()
        project = row.get("E", "").strip()
        if not raw_filter or not comuna or not project:
            continue
        if raw_filter.lower() in {"filtro", "concatenar"}:
            continue

        brand, brand_group, campaign_name = split_desglose_filter(raw_filter)
        if not brand_group or not campaign_name:
            continue

        mappings.append(
            {
                "brand": brand,
                "brandGroup": brand_group,
                "campaignName": campaign_name,
                "campaignKey": normalize_key(campaign_name),
                "comuna": comuna,
                "project": project,
            }
        )

    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in mappings:
        key = (item["brandGroup"], item["campaignKey"], item["comuna"], item["project"])
        deduped[key] = item

    return sorted(
        deduped.values(),
        key=lambda item: (item["brand"], item["campaignName"], item["comuna"], item["project"]),
    )


def build_reason_social_rows(
    invoices: list[dict[str, Any]],
    reason_social_mappings: list[dict[str, Any]],
    campaign_desglose_mappings: list[dict[str, Any]],
    card_charges_by_code: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    def extract_special_charges(invoice: dict[str, Any]) -> list[dict[str, Any]]:
        charges: list[dict[str, Any]] = []

        details = invoice.get("details", []) if isinstance(invoice.get("details"), list) else []
        for detail in details:
            label = str(detail.get("description", "")).strip()
            amount = int(detail.get("amount", 0) or 0)
            if not label or amount == 0:
                continue
            if is_special_charge_label(label):
                charges.append({"label": label, "amount": amount})

        if charges:
            return charges

        summary_items = invoice.get("summaryBreakdown", []) if isinstance(invoice.get("summaryBreakdown"), list) else []
        for item in summary_items:
            label = str(item.get("label", "")).strip()
            amount = int(item.get("amount", 0) or 0)
            if not label or amount == 0:
                continue
            if is_special_charge_label(label):
                charges.append({"label": label, "amount": amount})
        return charges

    def campaign_reference_type(platform: str) -> str:
        return "transactionId" if platform == "Meta" else "invoiceNumber"

    def extract_campaign_lines(invoice: dict[str, Any], platform: str) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        invoice_id = str(invoice.get("id", "")).strip()
        invoice_date = str(invoice.get("invoiceDate", "")).strip()

        if platform == "Meta":
            campaign_details = (
                invoice.get("campaignDetails", []) if isinstance(invoice.get("campaignDetails"), list) else []
            )
            covered_transaction_ids: set[str] = set()
            for detail in campaign_details:
                campaign_name = str(detail.get("name", "") or detail.get("campaignName", "")).strip()
                amount = int(detail.get("amount", 0) or 0)
                transaction_id = str(detail.get("transactionId", "")).strip()
                payment_date = str(detail.get("date", "")).strip() or invoice_date
                payment_reference = str(detail.get("paymentReference", "")).strip().upper()
                if not campaign_name or amount <= 0:
                    continue
                if transaction_id:
                    covered_transaction_ids.add(transaction_id)
                lines.append(
                    {
                        "campaignName": campaign_name,
                        "amount": amount,
                        "referenceId": transaction_id or invoice_id,
                        "paymentDate": payment_date,
                        "paymentReference": payment_reference,
                    }
                )

            details = invoice.get("details", []) if isinstance(invoice.get("details"), list) else []
            for detail in details:
                status = str(detail.get("status", "")).strip()
                if status and status != "Pagado":
                    continue
                amount = int(detail.get("amount", 0) or 0)
                if amount <= 0:
                    continue
                transaction_id = str(detail.get("transactionId", "")).strip()
                if not transaction_id or transaction_id in covered_transaction_ids:
                    continue
                payment_date = str(detail.get("date", "")).strip() or invoice_date
                payment_reference = str(detail.get("paymentReference", "")).strip().upper()
                lines.append(
                    {
                        "campaignName": "Sin desglose de campaña (Meta)",
                        "amount": amount,
                        "referenceId": transaction_id,
                        "paymentDate": payment_date,
                        "paymentReference": payment_reference,
                    }
                )

            if lines:
                return lines

        campaigns = invoice.get("campaigns", []) if isinstance(invoice.get("campaigns"), list) else []
        for campaign in campaigns:
            campaign_name = str(campaign.get("name", "")).strip()
            amount = int(campaign.get("amount", 0) or 0)
            if not campaign_name or amount <= 0:
                continue
            lines.append(
                {
                    "campaignName": campaign_name,
                    "amount": amount,
                    "referenceId": invoice_id,
                    "paymentDate": invoice_date,
                    "paymentReference": "",
                }
            )

        return lines

    def split_amount_evenly(total_amount: int, bucket_count: int) -> list[int]:
        if bucket_count <= 0:
            return []
        base = total_amount // bucket_count
        remainder = total_amount % bucket_count
        return [base + (1 if idx < remainder else 0) for idx in range(bucket_count)]

    by_brand_campaign: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_brand_campaign_desglose: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_campaign_desglose: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for mapping in reason_social_mappings:
        key = (mapping["brandGroup"], mapping["campaignKey"])
        by_brand_campaign[key].append(mapping)
        by_campaign[mapping["campaignKey"]].append(mapping)
    for mapping in campaign_desglose_mappings:
        key = (mapping["brandGroup"], mapping["campaignKey"])
        by_brand_campaign_desglose[key].append(mapping)
        by_campaign_desglose[mapping["campaignKey"]].append(mapping)

    rows: list[dict[str, Any]] = []
    for invoice in invoices:
        platform = str(invoice.get("platform", "")).strip()
        if platform not in {"Meta", "Google Ads", "Google Cloud"}:
            continue

        brand = str(invoice.get("brand", "")).strip()
        if platform == "Google Cloud":
            total_amount = int(invoice.get("totalAmount", 0) or 0)
            if total_amount <= 0:
                continue
            split_amounts = split_amount_evenly(total_amount, len(GCLOUD_SPLIT_ENTITIES))
            card_charge = invoice.get("cardCharge", {}) if isinstance(invoice.get("cardCharge"), dict) else {}
            payment_date = str(card_charge.get("cartolaDate", "")).strip() or str(invoice.get("invoiceDate", "")).strip()
            reference_id = str(card_charge.get("statementReference", "")).strip() or str(invoice.get("id", "")).strip()
            for idx, assignment in enumerate(GCLOUD_SPLIT_ENTITIES):
                amount = split_amounts[idx]
                legal_entity = str(assignment.get("legalEntity", "")).strip()
                comuna = str(assignment.get("comuna", "")).strip()
                project = str(assignment.get("project", "")).strip()
                pep_code = str(assignment.get("pepCode", "")).strip()
                rows.append(
                    {
                        "invoiceId": invoice.get("id", ""),
                        "invoiceDate": invoice.get("invoiceDate", ""),
                        "month": month_key(payment_date),
                        "platform": platform,
                        "brand": brand,
                        "campaignName": "Google Cloud",
                        "amount": amount,
                        "paymentDate": payment_date,
                        "paymentReference": str(card_charge.get("descriptionCharge", "")).strip(),
                        "chargeCode": str(card_charge.get("descriptionCharge", "")).strip(),
                        "chargeAmountOriginal": int(card_charge.get("amountOriginal", 0) or 0) if card_charge else None,
                        "chargeAmountUsd": float(card_charge.get("amountUsd", 0.0) or 0.0) if card_charge else None,
                        "chargeAmountValidation": "Coincide" if card_charge else "No aplica",
                        "chargeTcAmount": amount if card_charge else None,
                        "legalEntity": legal_entity,
                        "comuna": comuna,
                        "project": project,
                        "pepCode": pep_code,
                        "referenceId": reference_id,
                        "referenceType": "cartolaReference" if card_charge else "invoiceNumber",
                        "mappingBrand": "GCloud",
                        "splitAssignments": [
                            {
                                "legalEntity": legal_entity,
                                "comuna": comuna,
                                "project": project,
                                "pepCode": pep_code,
                                "amount": amount,
                            }
                        ],
                        "splitCount": 1,
                        "matched": True,
                    }
                )
            continue

        brand_group = normalize_brand_group(brand)
        campaign_lines = extract_campaign_lines(invoice, platform)
        reference_type = campaign_reference_type(platform)

        for campaign_line in campaign_lines:
            campaign_name = str(campaign_line.get("campaignName", "")).strip()
            amount = int(campaign_line.get("amount", 0) or 0)
            reference_id = str(campaign_line.get("referenceId", "")).strip() or str(invoice.get("id", "")).strip()
            payment_date = str(campaign_line.get("paymentDate", "")).strip() or str(invoice.get("invoiceDate", "")).strip()
            payment_reference = str(campaign_line.get("paymentReference", "")).strip().upper()
            if not campaign_name or amount <= 0:
                continue

            card_charge_match = card_charges_by_code.get(payment_reference) if payment_reference else None
            charge_code = str(card_charge_match.get("chargeCode", "")).strip() if card_charge_match else ""
            cartola_date = str(card_charge_match.get("cartolaDate", "")).strip() if card_charge_match else ""
            charge_amount_original = (
                int(card_charge_match.get("amountOriginal", 0) or 0) if card_charge_match else None
            )
            charge_amount_usd = float(card_charge_match.get("amountUsd", 0.0) or 0.0) if card_charge_match else None
            if platform == "Meta":
                charge_amount_validation = "Pendiente" if charge_amount_original is not None else "No aplica"
            else:
                charge_amount_validation = "Sin match"

            campaign_key = normalize_key(campaign_name)
            candidate_pool: list[dict[str, Any]] = []
            for alias in brand_group_aliases(brand_group):
                candidate_pool.extend(by_brand_campaign.get((alias, campaign_key), []))

            # Deduplicate keeping deterministic order.
            seen_candidate_keys: set[tuple[str, str, str, str, str]] = set()
            candidates: list[dict[str, Any]] = []
            for candidate in candidate_pool:
                candidate_key = (
                    str(candidate.get("brandGroup", "")),
                    str(candidate.get("campaignKey", "")),
                    str(candidate.get("legalEntity", "")),
                    str(candidate.get("comuna", "")),
                    str(candidate.get("project", "")),
                )
                if candidate_key in seen_candidate_keys:
                    continue
                seen_candidate_keys.add(candidate_key)
                candidates.append(candidate)

            if brand_group == "socovesa" and len({item["legalEntity"] for item in candidates}) > 1:
                looks_like_sur = any(
                    token in campaign_key
                    for token in (
                        "sur",
                        "centrosur",
                        "suraustral",
                        "austral",
                        "temuco",
                        "valdivia",
                        "puertomontt",
                        "puntaarenas",
                        "chillan",
                        "losangeles",
                    )
                )
                preferred_group = "socovesasur" if looks_like_sur else "socovesasantiago"
                preferred = [item for item in candidates if item.get("brandGroup") == preferred_group]
                if preferred:
                    candidates = preferred

            if not candidates:
                fallback = by_campaign.get(campaign_key, [])
                if len({item["legalEntity"] for item in fallback}) == 1:
                    candidates = fallback

            legal_entity = "Sin asignar"
            comuna = "Sin asignar"
            project = "Sin asignar"
            mapping_brand = ""
            split_assignments: list[dict[str, Any]] = []
            sorted_candidates: list[dict[str, Any]] = []
            if candidates:
                sorted_candidates = sorted(
                    candidates,
                    key=lambda item: (
                        item.get("legalEntity", ""),
                        item.get("comuna", ""),
                        item.get("project", ""),
                        item.get("brand", ""),
                    ),
                )
                legal_entity = sorted_candidates[0]["legalEntity"]
                comuna = str(sorted_candidates[0].get("comuna", "")).strip() or "Sin asignar"
                project = str(sorted_candidates[0].get("project", "")).strip() or "Sin asignar"
                mapping_brand = sorted_candidates[0]["brand"]
            manual_assignment = manual_assignment_by_campaign(campaign_name)
            if manual_assignment and (
                not candidates or legal_entity == "Sin asignar" or project == "Sin asignar" or not pep_code_by_project(project)
            ):
                legal_entity, comuna, project = manual_assignment
                mapping_brand = "Manual"

            desglose_pool: list[dict[str, Any]] = []
            for alias in brand_group_aliases(brand_group):
                desglose_pool.extend(by_brand_campaign_desglose.get((alias, campaign_key), []))
            if not desglose_pool:
                fallback_desglose = by_campaign_desglose.get(campaign_key, [])
                if len({item["brandGroup"] for item in fallback_desglose}) == 1:
                    desglose_pool = fallback_desglose

            split_candidates: list[tuple[str, str]] = []
            seen_split_keys: set[tuple[str, str]] = set()
            for candidate in sorted(
                desglose_pool,
                key=lambda item: (item.get("comuna", ""), item.get("project", ""), item.get("brand", "")),
            ):
                split_comuna = str(candidate.get("comuna", "")).strip() or "Sin asignar"
                split_project = str(candidate.get("project", "")).strip() or "Sin asignar"
                split_key = (split_comuna, split_project)
                if split_key in seen_split_keys:
                    continue
                seen_split_keys.add(split_key)
                split_candidates.append(split_key)

            if not split_candidates and sorted_candidates:
                for candidate in sorted_candidates:
                    split_comuna = str(candidate.get("comuna", "")).strip() or "Sin asignar"
                    split_project = str(candidate.get("project", "")).strip() or "Sin asignar"
                    split_key = (split_comuna, split_project)
                    if split_key in seen_split_keys:
                        continue
                    seen_split_keys.add(split_key)
                    split_candidates.append(split_key)

            if not split_candidates:
                split_candidates = [(comuna, project)]

            split_amounts = split_amount_evenly(amount, len(split_candidates))
            split_assignments = [
                {
                    "legalEntity": legal_entity,
                    "comuna": split_candidates[idx][0],
                    "project": split_candidates[idx][1],
                    "pepCode": pep_code_by_project(split_candidates[idx][1]),
                    "amount": split_amounts[idx],
                }
                for idx in range(len(split_candidates))
            ]

            rows.append(
                {
                    "invoiceId": invoice.get("id", ""),
                    "invoiceDate": invoice.get("invoiceDate", ""),
                    "month": month_key(cartola_date) if cartola_date else invoice.get("month", ""),
                    "platform": platform,
                    "brand": brand,
                    "campaignName": campaign_name,
                    "amount": amount,
                    "paymentDate": cartola_date or payment_date,
                    "paymentReference": payment_reference,
                    "chargeCode": charge_code,
                    "chargeAmountOriginal": charge_amount_original,
                    "chargeAmountUsd": charge_amount_usd,
                    "chargeAmountValidation": charge_amount_validation,
                    "chargeTcAmount": None,
                    "legalEntity": legal_entity,
                    "comuna": comuna,
                    "project": project,
                    "pepCode": pep_code_by_project(project),
                    "referenceId": reference_id,
                    "referenceType": reference_type,
                    "mappingBrand": mapping_brand,
                    "splitAssignments": split_assignments,
                    "splitCount": len(split_assignments),
                    "matched": legal_entity != "Sin asignar",
                }
            )

    brand_top_legal_entity: dict[str, str] = {}
    brand_top_assignment: dict[str, tuple[str, str, str]] = {}
    brand_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    brand_assignment_totals: dict[str, dict[tuple[str, str, str], int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        legal_entity = str(row.get("legalEntity", "")).strip()
        comuna = str(row.get("comuna", "")).strip()
        project = str(row.get("project", "")).strip()
        brand = str(row.get("brand", "")).strip()
        amount = int(row.get("amount", 0) or 0)
        if not brand or not legal_entity or legal_entity == "Sin asignar" or amount <= 0:
            continue
        brand_totals[brand][legal_entity] += amount
        if project and project != "Sin asignar":
            brand_assignment_totals[brand][(legal_entity, comuna or "Sin asignar", project)] += amount

    for brand, totals in brand_totals.items():
        sorted_totals = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        if sorted_totals:
            brand_top_legal_entity[brand] = sorted_totals[0][0]
    for brand, totals in brand_assignment_totals.items():
        sorted_totals = sorted(totals.items(), key=lambda item: (-item[1], item[0][0], item[0][1], item[0][2]))
        if sorted_totals:
            brand_top_assignment[brand] = sorted_totals[0][0]

    for invoice in invoices:
        platform = str(invoice.get("platform", "")).strip()
        if platform not in {"Meta", "Google Ads"}:
            continue

        special_charges = extract_special_charges(invoice)
        if not special_charges:
            continue

        brand = str(invoice.get("brand", "")).strip()
        top_legal_entity = brand_top_legal_entity.get(brand, "Sin asignar")
        top_comuna = "Sin asignar"
        top_project = "Sin asignar"
        if brand in brand_top_assignment:
            _, mapped_comuna, mapped_project = brand_top_assignment[brand]
            top_comuna = mapped_comuna or "Sin asignar"
            top_project = mapped_project or "Sin asignar"
        reference_type = campaign_reference_type(platform)
        reference_id = str(invoice.get("id", "")).strip()
        for charge in special_charges:
            charge_legal_entity = top_legal_entity
            charge_comuna = top_comuna
            charge_project = top_project
            if charge_legal_entity == "Sin asignar":
                manual_assignment = manual_assignment_by_campaign(charge["label"])
                if manual_assignment:
                    charge_legal_entity, charge_comuna, charge_project = manual_assignment

            rows.append(
                {
                    "invoiceId": invoice.get("id", ""),
                    "invoiceDate": invoice.get("invoiceDate", ""),
                    "month": invoice.get("month", ""),
                    "platform": platform,
                    "brand": brand,
                    "campaignName": charge["label"],
                    "amount": charge["amount"],
                    "paymentDate": invoice.get("invoiceDate", ""),
                    "paymentReference": "",
                    "chargeCode": "",
                    "chargeAmountOriginal": None,
                    "chargeAmountUsd": None,
                    "chargeAmountValidation": "No aplica" if platform == "Meta" else "Sin match",
                    "chargeTcAmount": None,
                    "legalEntity": charge_legal_entity,
                    "comuna": charge_comuna,
                    "project": charge_project,
                    "pepCode": pep_code_by_project(charge_project),
                    "referenceId": reference_id,
                    "referenceType": reference_type,
                    "mappingBrand": "",
                    "splitAssignments": [
                        {
                            "legalEntity": charge_legal_entity,
                            "comuna": charge_comuna,
                            "project": charge_project,
                            "pepCode": pep_code_by_project(charge_project),
                            "amount": charge["amount"],
                        }
                    ],
                    "splitCount": 1,
                    "matched": charge_legal_entity != "Sin asignar",
                }
            )

    for row in rows:
        row_project = str(row.get("project", "")).strip()
        row_legal_entity = str(row.get("legalEntity", "")).strip() or "Sin asignar"
        row["legalEntity"] = override_legal_entity_by_project(row_project, row_legal_entity)
        row["pepCode"] = pep_code_by_project(row_project)
        row["matched"] = row["legalEntity"] != "Sin asignar"

        split_assignments = row.get("splitAssignments", [])
        if not isinstance(split_assignments, list):
            continue
        for split in split_assignments:
            split_project = str(split.get("project", "")).strip()
            split_legal_entity = str(split.get("legalEntity", "")).strip() or row["legalEntity"]
            split["legalEntity"] = override_legal_entity_by_project(split_project, split_legal_entity)
            split["pepCode"] = pep_code_by_project(split_project)

    # Meta validation must compare the card statement amount against the total per reference,
    # summing all campaign rows that belong to the same payment reference.
    meta_totals_by_reference: dict[str, int] = defaultdict(int)
    for row in rows:
        if str(row.get("platform", "")).strip() != "Meta":
            continue
        payment_reference = str(row.get("paymentReference", "")).strip().upper()
        if not payment_reference:
            continue
        if row.get("chargeAmountOriginal") is None:
            continue
        meta_totals_by_reference[payment_reference] += int(row.get("amount", 0) or 0)

    for row in rows:
        if str(row.get("platform", "")).strip() != "Meta":
            continue
        payment_reference = str(row.get("paymentReference", "")).strip().upper()
        if not payment_reference:
            row["chargeAmountValidation"] = "No aplica"
            continue
        if row.get("chargeAmountOriginal") is None:
            row["chargeAmountValidation"] = "No aplica"
            continue

        total_by_reference = meta_totals_by_reference.get(payment_reference, 0)
        row["referenceTotalAmount"] = total_by_reference
        row["chargeAmountValidation"] = (
            "Coincide" if total_by_reference == int(row.get("chargeAmountOriginal", 0) or 0) else "No coincide"
        )

    def allocate_proportional_int(total: int, weights: list[int]) -> list[int]:
        if total <= 0 or not weights:
            return [0 for _ in weights]
        safe_weights = [max(int(weight), 0) for weight in weights]
        weight_sum = sum(safe_weights)
        if weight_sum <= 0:
            return [0 for _ in weights]

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

    meta_rows_by_reference: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if str(row.get("platform", "")).strip() != "Meta":
            continue
        payment_reference = str(row.get("paymentReference", "")).strip().upper()
        if not payment_reference:
            continue
        if row.get("chargeAmountOriginal") is None:
            continue
        meta_rows_by_reference[payment_reference].append(idx)

    for payment_reference, row_indexes in meta_rows_by_reference.items():
        if not row_indexes:
            continue
        charge_total = int(rows[row_indexes[0]].get("chargeAmountOriginal", 0) or 0)
        weights = [int(rows[idx].get("amount", 0) or 0) for idx in row_indexes]
        allocated = allocate_proportional_int(charge_total, weights)
        for pos, row_idx in enumerate(row_indexes):
            rows[row_idx]["chargeTcAmount"] = allocated[pos]

    # Ajuste de diferencias por plataforma:
    # si el total de la factura no coincide con la suma de filas asignadas,
    # se descuenta/agrega la diferencia a la razon social con mayor inversion por marca.
    def apply_brand_diff_adjustments(platform_name: str) -> None:
        brand_diffs: dict[str, int] = defaultdict(int)
        for invoice in invoices:
            if str(invoice.get("platform", "")).strip() != platform_name:
                continue
            invoice_id = str(invoice.get("id", "")).strip()
            brand = str(invoice.get("brand", "")).strip()
            if not invoice_id or not brand:
                continue
            invoice_total = int(invoice.get("totalAmount", 0) or 0)
            mapped_total = sum(
                int(row.get("amount", 0) or 0)
                for row in rows
                if str(row.get("platform", "")).strip() == platform_name
                and str(row.get("invoiceId", "")).strip() == invoice_id
            )
            diff = invoice_total - mapped_total
            if diff != 0:
                brand_diffs[brand] += diff

        brand_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            if str(row.get("platform", "")).strip() != platform_name:
                continue
            brand = str(row.get("brand", "")).strip()
            legal_entity = str(row.get("legalEntity", "")).strip()
            amount = int(row.get("amount", 0) or 0)
            if not brand or not legal_entity or legal_entity == "Sin asignar":
                continue
            brand_totals[brand][legal_entity] += amount

        top_legal_entity_by_brand: dict[str, str] = {}
        for brand, totals in brand_totals.items():
            ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
            if ordered:
                top_legal_entity_by_brand[brand] = ordered[0][0]

        for brand, diff in brand_diffs.items():
            if diff == 0:
                continue
            target_legal_entity = top_legal_entity_by_brand.get(brand, "")
            if not target_legal_entity:
                continue

            candidate_indexes = [
                idx
                for idx, row in enumerate(rows)
                if str(row.get("platform", "")).strip() == platform_name
                and str(row.get("brand", "")).strip() == brand
                and str(row.get("legalEntity", "")).strip() == target_legal_entity
                and not is_special_charge_label(str(row.get("campaignName", "")).strip())
            ]
            if not candidate_indexes:
                continue

            target_index = max(candidate_indexes, key=lambda idx: int(rows[idx].get("amount", 0) or 0))
            rows[target_index]["amount"] = int(rows[target_index].get("amount", 0) or 0) + diff

            split_assignments = rows[target_index].get("splitAssignments", [])
            if isinstance(split_assignments, list) and split_assignments:
                matching_splits = [
                    split
                    for split in split_assignments
                    if str(split.get("legalEntity", "")).strip() == target_legal_entity
                ]
                if matching_splits:
                    target_split = max(matching_splits, key=lambda split: int(split.get("amount", 0) or 0))
                else:
                    target_split = split_assignments[0]
                target_split["amount"] = int(target_split.get("amount", 0) or 0) + diff

    apply_brand_diff_adjustments("Google Ads")
    apply_brand_diff_adjustments("Meta")

    def reconcile_invoice_totals(platform_name: str) -> None:
        brand_top_legal_entity: dict[str, str] = {}
        for row in rows:
            if str(row.get("platform", "")).strip() != platform_name:
                continue
            brand = str(row.get("brand", "")).strip()
            legal_entity = str(row.get("legalEntity", "")).strip()
            if not brand or not legal_entity or legal_entity == "Sin asignar":
                continue
            if brand not in brand_top_legal_entity:
                brand_top_legal_entity[brand] = legal_entity

        for invoice in invoices:
            if str(invoice.get("platform", "")).strip() != platform_name:
                continue
            invoice_id = str(invoice.get("id", "")).strip()
            brand = str(invoice.get("brand", "")).strip()
            invoice_total = int(invoice.get("totalAmount", 0) or 0)
            if not invoice_id or not brand:
                continue

            invoice_row_indexes = [
                idx
                for idx, row in enumerate(rows)
                if str(row.get("platform", "")).strip() == platform_name
                and str(row.get("invoiceId", "")).strip() == invoice_id
            ]
            mapped_total = sum(int(rows[idx].get("amount", 0) or 0) for idx in invoice_row_indexes)
            diff = invoice_total - mapped_total
            if diff == 0:
                continue

            if invoice_row_indexes:
                adjustable_indexes = [
                    idx
                    for idx in invoice_row_indexes
                    if not is_special_charge_label(str(rows[idx].get("campaignName", "")).strip())
                ]
                target_pool = adjustable_indexes or invoice_row_indexes
                target_idx = max(target_pool, key=lambda idx: int(rows[idx].get("amount", 0) or 0))
                rows[target_idx]["amount"] = int(rows[target_idx].get("amount", 0) or 0) + diff
                continue

            target_legal_entity = brand_top_legal_entity.get(brand, "Sin asignar")
            rows.append(
                {
                    "invoiceId": invoice_id,
                    "month": str(invoice.get("month", "")).strip(),
                    "platform": platform_name,
                    "brand": brand,
                    "legalEntity": target_legal_entity,
                    "comuna": "",
                    "project": "",
                    "campaignName": "Ajuste de cuadratura",
                    "referenceId": f"{invoice_id}-ajuste",
                    "paymentReference": "",
                    "paymentMethod": "",
                    "status": "Pagado",
                    "chargeCode": "",
                    "amount": diff,
                    "chargeAmountOriginal": None,
                    "chargeTcAmount": None,
                    "chargeAmountValidation": "",
                    "sourceInvoice": str(invoice.get("sourceFile", "")).strip(),
                    "sourceDetail": "",
                    "splitAssignments": [],
                }
            )

    reconcile_invoice_totals("Google Ads")
    reconcile_invoice_totals("Meta")

    return sorted(
        rows,
        key=lambda item: (
            item["month"],
            item["platform"],
            item["brand"],
            item["legalEntity"],
            item["comuna"],
            item["project"],
            item["campaignName"],
            item["referenceId"],
        ),
    )


def parse_zeppelin_excel(path: Path, warnings: list[ParseWarning], document_file: str) -> list[dict[str, Any]]:
    sheet_name, rows = parse_excel_sheet_rows(path)
    month = month_key_from_spanish_name(sheet_name)
    year, month_num = map(int, month.split("-"))
    last_day = monthrange(year, month_num)[1]
    period_start = f"{month}-01"
    period_end = f"{month}-{last_day:02d}"

    concept_cell = rows.get(3, {}).get("B", "")
    if "Zeppelin" not in concept_cell:
        warnings.append(ParseWarning(source=path.name, message="Could not find 'LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de CrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©dito Zeppelin' section."))
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
        investment = int(round(float(amount_raw)))
        fee_amount = int(round(investment * 0.02))
        total_with_fee = investment + fee_amount

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
                "accountName": "LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de CrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©dito Zeppelin",
                "accountId": po_number,
                "totalAmount": total_with_fee,
                "summaryBreakdown": [
                    {"label": "Total", "amount": investment},
                    {"label": "Total + Fee (2%)", "amount": total_with_fee},
                ],
                "details": [
                    {
                        "concept": "LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de CrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©dito Zeppelin",
                        "purchaseOrder": po_number,
                        "supplierInvoice": supplier_invoice,
                        "amount": investment,
                    }
                ],
                "notes": notes,
            }
        )
    return invoices


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    warnings: list[ParseWarning] = []
    existing_data: dict[str, Any] = {}
    if JSON_OUT.exists():
        try:
            existing_data = json.loads(JSON_OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warnings.append(ParseWarning(source=JSON_OUT.name, message=f"Could not parse existing JSON: {exc}"))

    invoices: list[dict[str, Any]] = []
    rs_rules: list[dict[str, Any]] = []
    reason_social_mappings: list[dict[str, Any]] = []
    campaign_desglose_mappings: list[dict[str, Any]] = []
    card_charges_by_code: dict[str, dict[str, Any]] = {}
    google_files_map: dict[str, Path] = {}
    for file in sorted(GOOGLE_INVOICES_DIR.rglob("*.pdf")):
        google_files_map[file.name.lower()] = file
    for file in sorted(PDF_DIR.glob("*GoogleAds.pdf")):
        google_files_map.setdefault(file.name.lower(), file)
    google_files = sorted(google_files_map.values(), key=lambda p: p.as_posix().lower())
    meta_files = sorted(PDF_DIR.glob("*Meta*.pdf"))

    for file in google_files:
        invoices.append(parse_google_invoice(file, warnings))

    meta_receipt_invoices = parse_meta_receipt_folders(META_INVOICES_DIR, warnings)
    if meta_receipt_invoices:
        invoices.extend(meta_receipt_invoices)
        known_meta_references = collect_meta_payment_references(meta_receipt_invoices)
        card_charges_by_code = parse_meta_card_statement_charges(
            META_CARD_STATEMENTS_DIR, warnings, known_references=known_meta_references
        )
    else:
        for file in meta_files:
            invoices.append(parse_meta_invoice(file, warnings))

    excel_files = sorted(ROOT.glob(EXCEL_PATTERN))
    if excel_files:
        for file in excel_files:
            invoices.extend(parse_zeppelin_excel(file, warnings, document_file=file.name))
            rs_rules.extend(parse_rs_excel(file, warnings))
            reason_social_mappings.extend(parse_reason_social_sheet(file, warnings))
            campaign_desglose_mappings.extend(parse_desglose_por_rs_sheet(file, warnings))
    else:
        existing_invoices = existing_data.get("invoices", []) if isinstance(existing_data, dict) else []
        carried_zeppelin = [item for item in existing_invoices if item.get("platform") == "Agencia Zeppelin"]
        invoices.extend(carried_zeppelin)
        rs_rules = existing_data.get("rsRules", []) if isinstance(existing_data.get("rsRules"), list) else []
        reason_social_mappings = (
            existing_data.get("reasonSocialMappings", [])
            if isinstance(existing_data.get("reasonSocialMappings"), list)
            else []
        )
        campaign_desglose_mappings = (
            existing_data.get("campaignDesgloseMappings", [])
            if isinstance(existing_data.get("campaignDesgloseMappings"), list)
            else []
        )

    invoices.sort(key=lambda item: (item["month"], item["platform"], item["brand"], item["invoiceDate"]))
    reason_social_rows = build_reason_social_rows(
        invoices,
        reason_social_mappings,
        campaign_desglose_mappings,
        card_charges_by_code,
    )

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
        "rsRules": rs_rules,
        "reasonSocialMappings": reason_social_mappings,
        "campaignDesgloseMappings": campaign_desglose_mappings,
        "cardChargesByCode": card_charges_by_code,
        "reasonSocialRows": reason_social_rows,
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
