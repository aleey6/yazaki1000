"""IAM (Maroc Telecom) multi-page invoice parser.

OCR strategy:
  - OCR is ONLY used when explicitly forced via use_ocr=True flag
  - When use_ocr=False, always use direct pdfplumber extraction
  - No automatic detection or fallback to OCR
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple, List

import pdfplumber
import fitz  # PyMuPDF — needed for OCR page rendering


# ──────────────────────────── Amount / Date helpers ──────────────────────────

_AMOUNT = r"-?\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d+)?"
_DATE   = r"\d{2}/\d{2}/\d{4}"


# ──────────────────────────── Regex patterns ─────────────────────────────────
_RE_INVOICE_LABEL = r"(?:N[°o©0O]?\s*[-.]?\s*Facture|Facture\s*N[°o©0O]?)"
RE_INVOICE_NUMBER = re.compile(
    r"(?:" + _RE_INVOICE_LABEL + r")\s*:?\s*(\d{16})"
    r"|(\d{16})",
    re.IGNORECASE
)

_RE_CLIENT_LABEL = r"(?:N[°o©0O]?\s*[-.]?\s*Client|N[°o©0O]?\s*d['\u2019]?Abonnement|Abonnement|Client\s+N[°o©0O]?)"

RE_CLIENT_NUMBER = re.compile(
    r"(?:" + _RE_CLIENT_LABEL + r")\s*:?\s*([0-9\.\s]+)"
    r"|([0-9\.\s]{15,30})",
    re.IGNORECASE
)

# Pattern exact pour le numéro client complet
EXACT_CLIENT_PATTERN = re.compile(r'(\d{1}\.\d{6}\.\d{2}\.\d{2}\.\d{6})')

RE_INVOICE_DATE = re.compile(
    r"Date\s*[Ff]acture\s*[©:]?\s*(\d{2}[/\-]\d{2}[/\-]\d{4})"
    r"|Date\s*[Ff]acture[^0-9]*(\d{2}[/\-]\d{2}[/\-]\d{4})",
    re.IGNORECASE
)

_RE_PHONE_LABEL = r"N[°o©0O]?\s*d['\u2019]?\s*Appel"
RE_PHONE = re.compile(
    r"N[°©o0]?\s*\.?\s*d['\u2019\s]?\s*[Aa]ppel\s*:?\s*(0[5-7]\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})",
    re.IGNORECASE
)

RE_PAGE_NUM = re.compile(r"Page\s+(\d+)/(\d+)", re.IGNORECASE)

RE_TOTAL_CONTRAT = re.compile(
    r"TOTAL\s+CONTRAT\s*[:\s]+([\d\s]+[\.,]\d{2})",
    re.IGNORECASE
)

RE_PERIOD = re.compile(
    r"P[ée]riode\s+factur[ée]e\s*:?\s*(\d{2}[/\-]\d{2}[/\-]\d{4})\s*[-à]\s*(\d{2}[/\-]\d{2}[/\-]\d{4})"
    r"|P[ée]riode[^0-9]*(\d{2}/\d{2}/\d{4})[^0-9]*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE
)

# Pattern spécifique pour la période au format "Date début : 01/03/2026 Date Fin : 31/03/2026"
PERIOD_PATTERN = re.compile(
    r"Date\s+d[ée]but\s*:\s*(\d{2}/\d{2}/\d{4})\s*Date\s+Fin\s*:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE
)

# Pattern spécifique pour la date facture
DATE_PATTERN = re.compile(
    r"Date\s+Facture\s*:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE
)

# Pattern spécifique pour le numéro d'appel
PHONE_PATTERN = re.compile(
    r"N°\s*d['\u2019]?\s*Appel\s*:\s*(0[5-7][\d\s]{8,12})",
    re.IGNORECASE
)

RE_TABLE_ROW = re.compile(
    r"^(?P<desc>.+?)\s+(?P<start>" + _DATE + r")\s+(?P<end>" + _DATE + r")\s+(?P<amount>" + _AMOUNT + r")\s*$"
)
RE_PONCTUAL_ROW = re.compile(r"^(?P<desc>.+?)\s+(?P<amount>" + _AMOUNT + r")\s*$")


# ──────────────────────────── Data models ────────────────────────────────────

def _to_float(value: str) -> float:
    if not value:
        return 0.0
    cleaned = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(match.group(1)) if match else 0.0


@dataclass
class LineItem:
    description: str
    amount: float
    date_start: Optional[str] = None
    date_end: Optional[str] = None


@dataclass
class Contract:
    page_number: int
    document_page: Optional[str] = None
    contract_type: str = ""
    phone_number: Optional[str] = None
    invoice_date: Optional[str] = None 
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    articles_mensuels: int = 0
    articles_ponctuels: int = 0
    frais_mensuels: List[LineItem] = field(default_factory=list)
    frais_ponctuels: List[LineItem] = field(default_factory=list)
    total_contrat: float = 0.0


@dataclass
class GlobalSummary:
    page_number: int = 1
    document_page: Optional[str] = None
    frais_abonnement_services: float = 0.0
    frais_ponctuels: float = 0.0
    montant_ht: float = 0.0
    montant_tva: float = 0.0
    montant_ttc: float = 0.0
    montant_du: float = 0.0


@dataclass
class InvoiceData:
    source_file: str
    client_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    global_summary: GlobalSummary = field(default_factory=GlobalSummary)
    contracts: List[Contract] = field(default_factory=list)
    total: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────── OCR helpers ────────────────────────────────────

def _ocr_fitz_page(fitz_doc: fitz.Document, page_idx: int, ocr_engine, dpi: int = 150) -> str:
    """Run OCR on a single page via the provided OCREngine."""
    try:
        fitz_page = fitz_doc[page_idx]
        text = ocr_engine.ocr_page(fitz_page, dpi=dpi)
        return text or ""
    except Exception as e:
        print(f"   [OCR] page {page_idx+1} error: {e}")
        return ""


# ──────────────────────────── Page-type helpers ───────────────────────────────

def _identify_page_kind(text: str) -> Tuple[str, Optional[str]]:
    t = re.sub(r"\s+", " ", text)

    # Détection page contrat - priorité absolue
    if re.search(r"N°\s*d['\u2019]?\s*Appel", t, re.IGNORECASE):
        return "contract", "Contrat"
    if re.search(r"Forfait\s*Optimi[sz]|Illimit[ée]\s*Mobile", t, re.IGNORECASE):
        return "contract", "Forfait"
    if re.search(r"TOTAL\s+CONTRAT", t, re.IGNORECASE):
        return "contract", "Contrat"
    if re.search(r"FRAIS\s+(MENSUELS|PONCTUELS)", t, re.IGNORECASE):
        return "contract", "Contrat"
    
    # Détection page globale
    if re.search(r"Page\s*globale|R[ée]capitulatif", t, re.IGNORECASE):
        return "global", None
    if re.search(r"Montant\s*TTC", t, re.IGNORECASE) and re.search(r"YAZAKI", t, re.IGNORECASE):
        return "global", None

    return "unknown", None


def _document_page(text: str) -> Optional[str]:
    m = RE_PAGE_NUM.search(text)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _extract_phone_ocr(text: str) -> Optional[str]:
    """
    Phone extractor specifically for OCR text where layout is unpredictable.
    """
    # Strategy 1: label + number on same line
    m = re.search(
        r"[Nn]\s*[°©o0]?\s*\.?\s*d['\u2019\s]?\s*[Aa]ppel[^0-9]{0,30}"
        r"(0[5-7]\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})",
        text, re.IGNORECASE
    )
    if m:
        return re.sub(r"[\s\-]", "", m.group(1))

    # Strategy 2: label on one line, number on next 1-3 lines
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if re.search(r"[Nn]\s*[°©o0]?\s*d['\u2019\s]?\s*[Aa]ppel", line, re.IGNORECASE):
            for j in range(i, min(i + 4, len(lines))):
                clean = re.sub(r"[\s\-]", "", lines[j])
                m2 = re.search(r"(?<!\d)(0[5-7]\d{8})(?!\d)", clean)
                if m2:
                    return m2.group(1)

    # Strategy 3: strip ALL whitespace
    flat = re.sub(r"[\s\n]", "", text)
    m = re.search(r"[Aa]ppel.{0,10}(0[5-7]\d{8})", flat, re.IGNORECASE)
    if m:
        return m.group(1)

    return None


def _extract_phone_direct(text: str) -> Optional[str]:
    """
    Phone extractor for direct pdfplumber text.
    """
    m = RE_PHONE.search(text)
    if m:
        return re.sub(r"[\s\-]", "", m.group(1))

    m = re.search(
        r"[Nn][°©o0]?\s*\.?\s*d['\u2019\s]?\s*[Aa]ppel[^0-9]{0,20}(0[5-7]\d{8})",
        text.replace(" ", ""),
        re.IGNORECASE
    )
    if m:
        return m.group(1)

    return None


# ──────────────────────────── Page parsers ───────────────────────────────────

def _parse_global_page(text: str) -> GlobalSummary:
    g = GlobalSummary()
    g.document_page = _document_page(text)
    patterns = {
        'frais_abonnement_services': [
            r"Frais\s+d['\u2019]abonnement\s+et\s+services\s*:?\s*(" + _AMOUNT + ")",
            r"Abonnement\s+et\s+services\s*:?\s*(" + _AMOUNT + ")",
        ],
        'frais_ponctuels': [
            r"Frais\s+ponctuels\s+li[ee]s\s+au\s+contrat\s*:?\s*(" + _AMOUNT + ")",
            r"Frais\s+ponctuels\s*:?\s*(" + _AMOUNT + ")",
        ],
        'montant_ht':  [r"Montant\s+HT\s*:?\s*(" + _AMOUNT + ")", r"Total\s+HT\s*:?\s*(" + _AMOUNT + ")"],
        'montant_tva': [r"Montant\s+TVA[^:\n]*:?\s*(" + _AMOUNT + ")", r"TVA\s*:?\s*(" + _AMOUNT + ")"],
        'montant_ttc': [r"Montant\s+TTC\s*:?\s*(" + _AMOUNT + ")", r"Total\s+TTC\s*:?\s*(" + _AMOUNT + ")"],
        'montant_du':  [r"Montant\s+d[uu]\s*:?\s*(" + _AMOUNT + ")", r"Net\s+[aa]\s+payer\s*:?\s*(" + _AMOUNT + ")"],
    }
    for attr, plist in patterns.items():
        for pat in plist:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                setattr(g, attr, _to_float(m.group(1)))
                break
    return g


def _parse_contract_page(text: str, page_no: int, contract_type: str) -> Contract:
    contract = Contract(
        page_number=page_no,
        document_page=_document_page(text),
        contract_type=contract_type,
    )

    # ==================== DEBUG: Afficher le texte OCR ====================
    print(f"\n   🔍 === OCR PAGE {page_no} (lignes clés) ===")
    for line in text.split('\n'):
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in ['appel', 'date', 'période', 'facture', 'client', 'contrat']):
            print(f"      {line[:150]}")
    print(f"   🔍 ========================================\n")

    # ==================== 1. PHONE NUMBER ====================
    phone_match = re.search(r"N°\s*d['\u2019]?\s*Appel\s*:\s*(0[5-7][\d\s]{8,12})", text, re.IGNORECASE)
    if phone_match:
        contract.phone_number = re.sub(r'[\s\-]', '', phone_match.group(1))
        print(f"   📞 Phone (pattern1): {contract.phone_number}")
    
    if not contract.phone_number:
        phone_match = re.search(r"N°\s+d['\u2019]?\s*Appel\s*:?\s*(0[5-7][\d\s]{8,12})", text, re.IGNORECASE)
        if phone_match:
            contract.phone_number = re.sub(r'[\s\-]', '', phone_match.group(1))
            print(f"   📞 Phone (pattern2): {contract.phone_number}")
    
    if not contract.phone_number:
        for line in text.split('\n'):
            if 'Appel' in line:
                nums = re.findall(r'0[5-7][\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}', line)
                if nums:
                    contract.phone_number = re.sub(r'[\s\-]', '', nums[0])
                    print(f"   📞 Phone (line): {contract.phone_number}")
                    break

    # ==================== 2. DATE FACTURE & PERIOD ====================
    # ⚠️ CE BLOC DOIT ÊTRE ICI, PAS À L'INTÉRIEUR D'UN AUTRE BLOC
    lines = text.split('\n')
    
    for line in lines:
        line_lower = line.lower()
        
        # Date Facture
        if 'date facture' in line_lower:
            match = re.search(r'(\d{2}/\d{2}/\d{4})', line)
            if match:
                contract.invoice_date = match.group(1)
                print(f"   📅 Date Facture: {contract.invoice_date}")
        
        # Début Période
        if ('début' in line_lower or 'debut' in line_lower) and not contract.period_start:
            match = re.search(r'(\d{2}/\d{2}/\d{4})', line)
            if match:
                contract.period_start = match.group(1)
                print(f"   📅 Period start: {contract.period_start}")
        
        # Fin Période
        if 'fin' in line_lower and not contract.period_end:
            match = re.search(r'(\d{2}/\d{2}/\d{4})', line)
            if match:
                contract.period_end = match.group(1)
                print(f"   📅 Period end: {contract.period_end}")

    # Fallback: chercher "Période facturée"
    if not contract.period_start or not contract.period_end:
        period_match = re.search(r"P[ée]riode\s+factur[ée]e\s*:?\s*(\d{2}/\d{2}/\d{4})\s*[-à]\s*(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if period_match:
            contract.period_start = period_match.group(1)
            contract.period_end = period_match.group(2)
            print(f"   📅 Period (fallback): {contract.period_start} → {contract.period_end}")

    # ==================== 3. TOTAL ====================
    m_total = RE_TOTAL_CONTRAT.search(text)
    if m_total:
        contract.total_contrat = _to_float(m_total.group(1))
        print(f"   💰 Total: {contract.total_contrat}")

    # ==================== 4. LINE ITEMS ====================
    section = None
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        lu = line.upper()
        if 'FRAIS MENSUELS' in lu:
            section = "mensuel"
            continue
        if 'FRAIS PONCTUELS' in lu:
            section = "ponctuel"
            continue
        if 'TOTAL CONTRAT' in lu:
            section = None
            continue

        if section == "mensuel":
            m = RE_TABLE_ROW.match(line)
            if m:
                contract.frais_mensuels.append(LineItem(
                    description=m.group("desc").strip(),
                    date_start=m.group("start"),
                    date_end=m.group("end"),
                    amount=_to_float(m.group("amount")),
                ))
                contract.articles_mensuels += 1
        elif section == "ponctuel":
            m = RE_PONCTUAL_ROW.match(line)
            if m:
                desc = m.group("desc").strip()
                if not desc.upper().startswith(('FRAIS', 'DESCRIPTION', 'DATE', 'MONTANT', 'N', 'TOTAL')):
                    contract.frais_ponctuels.append(LineItem(
                        description=desc,
                        amount=_to_float(m.group("amount")),
                    ))
                    contract.articles_ponctuels += 1

    return contract


# ──────────────────────────── Public entry point ─────────────────────────────

def parse_invoice(
    pdf_source,
    ocr_engine=None,
    progress_callback=None,
) -> InvoiceData:
    """
    Parse an IAM PDF invoice.

    OCR behavior:
      - If ocr_engine is None: use direct pdfplumber extraction only (no OCR)
      - If ocr_engine is provided: use OCR for EVERY page (forced OCR mode)
    """
    source_label = str(pdf_source) if isinstance(pdf_source, (str, Path)) else "<uploaded>"
    invoice = InvoiceData(source_file=source_label)

    # Determine extraction mode
    use_ocr = ocr_engine is not None
    mode_str = "OCR FORCED" if use_ocr else "DIRECT EXTRACTION (no OCR)"
    print(f"\nPDF Analysis: {source_label}")
    print(f"   Mode: {mode_str}")

    # Read bytes once
    if isinstance(pdf_source, (str, Path)):
        pdf_bytes = Path(pdf_source).read_bytes()
    else:
        pdf_bytes = pdf_source.read()
        if hasattr(pdf_source, 'seek'):
            pdf_source.seek(0)

    # Open with fitz for OCR rendering (if needed)
    fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf") if use_ocr else None

    # Open with pdfplumber for normal extraction
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
        
        for idx in range(total_pages):
            page_no = idx + 1

            if progress_callback:
                progress_callback(page_no, total_pages, f"Page {page_no}/{total_pages}...")

            # Decide extraction method
            if use_ocr and fitz_doc:
                text = _ocr_fitz_page(fitz_doc, idx, ocr_engine)
                extraction_method = "OCR (forced)"
                if not text or len(text.strip()) < 10:
                    print(f"   Page {page_no}: OCR minimal output, skipping")
                    continue
            else:
                text = pdf.pages[idx].extract_text() or ""
                extraction_method = "direct pdfplumber"
                if not text.strip():
                    print(f"   Page {page_no}: no text found, skipping")
                    continue

            # ==================== EXTRACT INVOICE NUMBER ====================
            if invoice.invoice_number is None:
                m = RE_INVOICE_NUMBER.search(text)
                if m:
                    invoice.invoice_number = (m.group(1) or m.group(2) or "").strip()
                    print(f"   -> Invoice#: {invoice.invoice_number}")

            # ==================== EXTRACT CLIENT NUMBER ====================
            if invoice.client_number is None:
                # Essayer d'abord avec le pattern exact
                m = EXACT_CLIENT_PATTERN.search(text)
                if m:
                    invoice.client_number = m.group(1)
                    print(f"   -> Client# (exact): {invoice.client_number}")
                else:
                    m = RE_CLIENT_NUMBER.search(text)
                    if m:
                        raw_client = (m.group(1) or m.group(2) or "").strip()
                        raw_client = re.sub(r'\s+', '', raw_client)
                        # Enlever le '2' final si présent
                        raw_client = re.sub(r'2$', '', raw_client)
                        invoice.client_number = raw_client
                        print(f"   -> Client#: {invoice.client_number}")

            # ==================== EXTRACT INVOICE DATE ====================
            if invoice.invoice_date is None:
                m = DATE_PATTERN.search(text)
                if m:
                    invoice.invoice_date = m.group(1)
                    print(f"   -> Date Facture: {invoice.invoice_date}")
                else:
                    m = RE_INVOICE_DATE.search(text)
                    if m:
                        invoice.invoice_date = (m.group(1) or m.group(2) or "").strip()
                        print(f"   -> Date Facture (fallback): {invoice.invoice_date}")

            # ==================== EXTRACT PERIOD ====================
            if invoice.period_start is None:
                m = PERIOD_PATTERN.search(text)
                if m:
                    invoice.period_start = m.group(1)
                    invoice.period_end = m.group(2)
                    print(f"   -> Period: {invoice.period_start} → {invoice.period_end}")
                else:
                    m = RE_PERIOD.search(text)
                    if m:
                        invoice.period_start = m.group(1) or m.group(3) or ""
                        invoice.period_end = m.group(2) or m.group(4) or ""
                        print(f"   -> Period (fallback): {invoice.period_start} → {invoice.period_end}")

            # ==================== CLASSIFY AND PARSE PAGE ====================
            kind, contract_type = _identify_page_kind(text)

            if kind == "global":
                invoice.global_summary = _parse_global_page(text)
                invoice.global_summary.page_number = page_no
                print(f"   OK Page {page_no}: global summary [{extraction_method}]")

            elif kind == "contract":
                contract = _parse_contract_page(text, page_no, contract_type or "Contrat")
                
                # ==================== TRANSFERT DES DONNEES VERS L'INVOICE ====================
                # Transférer la date facture du contrat vers l'invoice
                if hasattr(contract, 'invoice_date') and contract.invoice_date:
                    if invoice.invoice_date is None:
                        invoice.invoice_date = contract.invoice_date
                        print(f"   -> Date Facture (transférée): {invoice.invoice_date}")
                    elif invoice.invoice_date != contract.invoice_date:
                        print(f"   -> Date Facture: {invoice.invoice_date} (déjà définie)")
                
                # Transférer la période du contrat vers l'invoice
                if contract.period_start and contract.period_end:
                    if invoice.period_start is None:
                        invoice.period_start = contract.period_start
                        invoice.period_end = contract.period_end
                        print(f"   -> Period (transférée): {invoice.period_start} → {invoice.period_end}")
                    elif invoice.period_start != contract.period_start:
                        print(f"   -> Period: {invoice.period_start} → {invoice.period_end} (déjà définie)")
                
                # Transférer le numéro de téléphone si nécessaire
                if contract.phone_number:
                    print(f"   -> Phone (dans contrat): {contract.phone_number}")
                
                if contract.total_contrat > 0 or contract.phone_number:
                    invoice.contracts.append(contract)
                    phone_str = f" Phone: {contract.phone_number}" if contract.phone_number else ""
                    total_str = f" Total: {contract.total_contrat}" if contract.total_contrat else ""
                    print(f"   OK Page {page_no}: contract [{extraction_method}]{phone_str}{total_str}")
                else:
                    print(f"   - Page {page_no}: contract page skipped (no phone/total)")
    # Clean up
    if fitz_doc:
        fitz_doc.close()

    # Post-processing
    invoice.total = round(sum(c.total_contrat for c in invoice.contracts), 2)

    # Fallback: no contracts found but global summary has a total
    if not invoice.contracts and invoice.global_summary.montant_ttc > 0:
        default_contract = Contract(
            page_number=1,
            contract_type="Standard",
            total_contrat=invoice.global_summary.montant_ttc,
        )
        invoice.contracts.append(default_contract)
        invoice.total = invoice.global_summary.montant_ttc

    # Summary log
    print(f"\nExtraction complete: {len(invoice.contracts)} contract(s), total={invoice.total}")
    if invoice.contracts:
        unique_phones = {c.phone_number for c in invoice.contracts if c.phone_number}
        print(f"   Unique phones: {len(unique_phones)}")
    print(f"   Invoice: {invoice.invoice_number}  Client: {invoice.client_number}  Date: {invoice.invoice_date}")

    if progress_callback:
        progress_callback(total_pages, total_pages, "Termine!")

    return invoice