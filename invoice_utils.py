"""Utilitaires pour la gestion des factures."""

from __future__ import annotations

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from config import DATA_DIR, MASTER_FILE, safe_filename
from models import InvoiceData

def contracts_dataframe(invoice: InvoiceData) -> pd.DataFrame:
    """Convertit les contrats en DataFrame pandas."""
    rows = []
    for c in invoice.contracts:
        rows.append(
            {
                "Page PDF": c.page_number,
                "Page Doc.": c.document_page or "—",
                "Type de contrat": c.contract_type,
                "N° d'Appel": c.phone_number or "—",
                "Articles (Mensuels)": len(c.frais_mensuels),
                "Articles (Ponctuels)": len(c.frais_ponctuels),
                "Total Contrat (MAD)": c.total_contrat,
            }
        )
    return pd.DataFrame(rows)

def append_to_master(entry: dict) -> Path:
    """Ajoute une entrée au fichier master invoices.json."""
    DATA_DIR.mkdir(exist_ok=True)
    if MASTER_FILE.exists():
        try:
            master = json.loads(MASTER_FILE.read_text(encoding="utf-8"))
            if not isinstance(master, list):
                master = []
        except json.JSONDecodeError:
            master = []
    else:
        master = []
    master.append(entry)
    MASTER_FILE.write_text(
        json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return MASTER_FILE

def list_saved_invoices() -> list[Path]:
    """Liste les fichiers JSON sauvegardés (exclut master)."""
    if not DATA_DIR.exists():
        return []
    return sorted(
        [p for p in DATA_DIR.glob("*.json") if p.name != "invoices.json"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
def save_invoice_record(invoice: InvoiceData, plant: str, dept: str, project: str) -> dict:
    """Crée un enregistrement de facture profondément sérialisé pour SQLite."""
    # Convertit manuellement les sous-objets pour éviter les pertes d'objets complexes
    contracts_serialized = []
    for c in invoice.contracts:
        contracts_serialized.append({
            "page_number": c.page_number,
            "document_page": c.document_page or str(c.page_number),
            "contract_type": c.contract_type or "FORFAIT",
            "phone_number": c.phone_number,
            "period_start": c.period_start or invoice.period_start,
            "period_end": c.period_end or invoice.period_end,
            "total_contrat": float(c.total_contrat or 0.0),
            "frais_mensuels": [
                {"description": li.description, "amount": float(li.amount or 0)} 
                for li in getattr(c, "frais_mensuels", [])
            ],
            "frais_ponctuels": [
                {"description": li.description, "amount": float(li.amount or 0)} 
                for li in getattr(c, "frais_ponctuels", [])
            ]
        })

    return {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "plant": plant,
        "department": dept,
        "project": project,
        "client_number": invoice.client_number,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "total": float(invoice.total or 0.0),
        "global_summary": {
            "montant_ht": float(invoice.global_summary.montant_ht or 0.0),
            "montant_ttc": float(invoice.global_summary.montant_ttc or 0.0),
            "montant_tva": float(invoice.global_summary.montant_tva or 0.0),
        },
        "contracts": contracts_serialized
    }

def load_ocr_engine():
    """Charge l'OCR engine (sans cache Streamlit)."""
    try:
        from ocr_engine import OCREngine
        return OCREngine(), None
    except Exception as e:
        return None, str(e)