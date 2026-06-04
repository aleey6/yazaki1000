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

_RE_CLIENT_LABEL = r"(?:N[°o©0O]?\s*[-.]?\s*Client|N[°o©0O]?\s*d['\u2019]?Abonnement|Abonnement)"
RE_CLIENT_NUMBER = re.compile(
    r"(?:" + _RE_CLIENT_LABEL + r")\s*:?\s*(\d+\.\d+\.\d+\.\d+\.\d+)"
    r"|(\d+\.\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE
)

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

# REPLACE the entire function:
def _identify_page_kind(text: str) -> Tuple[str, Optional[str]]:
    # Normalize whitespace for fuzzy matching (OCR often adds/removes spaces)
    t = re.sub(r"\s+", " ", text)

    if re.search(r"Forfait\s*Optimi[sz]", t, re.IGNORECASE):
        return "contract", "Forfait Optimis"
    if re.search(r"Illimit[ée]\s*Mobile\s*Plafonn[ée]", t, re.IGNORECASE):
        return "contract", "Illimite Mobile Plafonne"
    if re.search(r"Illimit[ée]\s*Mobile", t, re.IGNORECASE):
        return "contract", "Illimite Mobile"
    # Match TOTAL CONTRAT with flexible spacing (OCR often splits tokens)
    if re.search(r"TOTAL\s*CONTRAT", t, re.IGNORECASE):
        return "contract", "Contrat"
    # OCR signal: page has "Appel" label AND a Moroccan phone number → it's a contract page
    flat = re.sub(r"\s", "", t)
    if re.search(r"[Aa]ppel", t) and re.search(r"0[5-7]\d{8}", flat):
        return "contract", "Contrat"
    if re.search(r"Page\s*globale|R[ée]capitulatif", t, re.IGNORECASE):
        return "global", None
    # Broader fallback: page with Montant TTC is a global summary
    if re.search(r"Montant\s*TTC", t, re.IGNORECASE):
        return "global", None

    return "unknown", None


def _document_page(text: str) -> Optional[str]:
    m = RE_PAGE_NUM.search(text)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _extract_phone_ocr(text: str) -> Optional[str]:
    """
    Phone extractor specifically for OCR text where layout is unpredictable.
    OCR may split 'N° d'Appel' across lines or mangle the degree symbol.
    Four strategies tried in order.
    """
    # Strategy 1: label + number on same line (best-case OCR)
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

    # Strategy 3: strip ALL whitespace/newlines then find "appel" near a number
    flat = re.sub(r"[\s\n]", "", text)
    m = re.search(
        r"[Aa]ppel.{0,10}(0[5-7]\d{8})",
        flat, re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Strategy 4: any line that IS a standalone 10-digit Moroccan mobile number
    for line in lines:
        clean = re.sub(r"[\s\-\.]", "", line.strip())
        if re.match(r"^(0[5-7]\d{8})$", clean):
            return clean

    return None


def _extract_phone_direct(text: str) -> Optional[str]:
    """
    Phone extractor for direct pdfplumber text.
    """
    # Primary: use compiled RE_PHONE
    m = RE_PHONE.search(text)
    if m:
        return re.sub(r"[\s\-]", "", m.group(1))

    # Fallback 1: label with any encoding + nearby number on space-stripped text
    m = re.search(
        r"[Nn][°©o0]?\s*\.?\s*d['\u2019\s]?\s*[Aa]ppel[^0-9]{0,20}(0[5-7]\d{8})",
        text.replace(" ", ""),
        re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Fallback 2: standalone 10-digit number per line
    for line in text.split('\n'):
        clean = re.sub(r"[\s\-]", "", line)
        m = re.search(r"(?<!\d)(0[5-7]\d{8})(?!\d)", clean)
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

    # Phone number
   # Phone number — 3-layer fallback
   # BEFORE (your current code):
    # Phone number
   # Phone number — 3-layer fallback
    m_phone = RE_PHONE.search(text)
    if m_phone:
        raw = m_phone.group(1)
        contract.phone_number = re.sub(r"[\s\-]", "", raw)

    if not contract.phone_number:
        # Layer 2: search for the label with any encoding, then grab the next 10-digit number
        m = re.search(
            r"[Nn]\s*[°©o0]?\s*\.?\s*d['\u2019\s]?\s*[Aa]ppel[^0-9]{0,20}(0[5-7]\d{8})",
            text.replace(" ", ""),
            re.IGNORECASE
        )
        if m:
            contract.phone_number = m.group(1)

    if not contract.phone_number:
        # Layer 3: scan every line for a standalone 10-digit Moroccan mobile number
        for line in text.split('\n'):
            line_clean = re.sub(r"[\s\-]", "", line)
            m = re.search(r"(?<!\d)(0[5-7]\d{8})(?!\d)", line_clean)
            if m:
                contract.phone_number = m.group(1)
                break

# AFTER — route to the right extractor based on OCR heuristic:
    # Phone number — route to OCR-aware or direct extractor
    # Heuristic: OCR text has many very short lines (character-level splits)
    short_lines = sum(1 for l in text.split('\n') if 0 < len(l.strip()) < 5)
    is_ocr_text = short_lines > 4

    if is_ocr_text:
        contract.phone_number = _extract_phone_ocr(text)
    else:
        contract.phone_number = _extract_phone_direct(text)

    # Universal last-resort: search the entire text stripped of all whitespace
    if not contract.phone_number:
        flat = re.sub(r"[\s\-]", "", text)
        m = re.search(r"(?<!\d)(0[5-7]\d{8})(?!\d)", flat)
        if m:
            contract.phone_number = m.group(1)
    # Period
    m_period = RE_PERIOD.search(text)
    if m_period:
        contract.period_start = m_period.group(1)
        contract.period_end   = m_period.group(2)
    else:
        dates = re.findall(r"(\d{2}/\d{2}/\d{4})", text)
        if len(dates) >= 2:
            contract.period_start, contract.period_end = dates[0], dates[1]

    # Total
    m_total = RE_TOTAL_CONTRAT.search(text)
    if m_total:
        contract.total_contrat = _to_float(m_total.group(1))

    # Line items
    section = None
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        lu = line.upper()
        if 'FRAIS MENSUELS'  in lu: section = "mensuel";  continue
        if 'FRAIS PONCTUELS' in lu: section = "ponctuel"; continue
        if 'TOTAL CONTRAT'   in lu: section = None;       continue

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
    
    No automatic detection - OCR is either all or nothing based on whether
    an engine is passed to the function.
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
    total_pages = len(fitz_doc) if fitz_doc else 0

    # Open with pdfplumber for normal extraction
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
        
        for idx in range(total_pages):
            page_no = idx + 1

            if progress_callback:
                progress_callback(page_no, total_pages, f"Page {page_no}/{total_pages}...")

            # Decide extraction method based on ocr_engine parameter
            if use_ocr and fitz_doc:
                # OCR MODE: Use OCR for every page
                text = _ocr_fitz_page(fitz_doc, idx, ocr_engine)
                extraction_method = "OCR (forced)"
                if not text or len(text.strip()) < 10:
                    print(f"   Page {page_no}: OCR minimal output, skipping")
                    continue
            else:
                # DIRECT MODE: Use pdfplumber normal extraction
                text = pdf.pages[idx].extract_text() or ""
                extraction_method = "direct pdfplumber"
                if not text.strip():
                    print(f"   Page {page_no}: no text found, skipping")
                    continue

            # Extract global invoice header fields (first occurrence wins)
            if invoice.invoice_number is None:
                m = RE_INVOICE_NUMBER.search(text)
                if m:
                    invoice.invoice_number = (m.group(1) or m.group(2) or "").strip()
                    print(f"   -> Invoice#: {invoice.invoice_number}")

            if invoice.client_number is None:
                m = RE_CLIENT_NUMBER.search(text)
                if m:
                    invoice.client_number = (m.group(1) or m.group(2) or "").strip()
                    print(f"   -> Client#: {invoice.client_number}")

            if invoice.invoice_date is None:
                m = RE_INVOICE_DATE.search(text)
                if m:
                    invoice.invoice_date = (m.group(1) or m.group(2) or "").strip()

            if invoice.period_start is None:
                m = RE_PERIOD.search(text)
                if m:
                    invoice.period_start = m.group(1) or m.group(3) or ""
                    invoice.period_end   = m.group(2) or m.group(4) or ""

            # Classify page and parse
            kind, contract_type = _identify_page_kind(text)

            if kind == "global":
                invoice.global_summary = _parse_global_page(text)
                invoice.global_summary.page_number = page_no
                print(f"   OK Page {page_no}: global summary [{extraction_method}]")

            elif kind == "contract":
                contract = _parse_contract_page(text, page_no, contract_type or "Contrat")
                if contract.total_contrat > 0 or contract.phone_number:
                    invoice.contracts.append(contract)
                    phone_str = f" Phone: {contract.phone_number}" if contract.phone_number else ""
                    total_str = f" Total: {contract.total_contrat}" if contract.total_contrat else ""
                    print(f"   OK Page {page_no}: contract [{extraction_method}]{phone_str}{total_str}")
                else:
                    print(f"   - Page {page_no}: contract page skipped (no phone/total)")

            else:
                print(f"   - Page {page_no}: unclassified, skipped")

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
    print(f"   Invoice: {invoice.invoice_number}  Client: {invoice.client_number}")

    if progress_callback:
        progress_callback(total_pages, total_pages, "Termine!")

    return invoice