# models.py
from pydantic import BaseModel
from typing import List, Optional

class ContractInfo(BaseModel):
    phone_number: Optional[str] = None
    contract_type: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    total_contrat: float = 0.0
    page_number: Optional[int] = None
    document_page: Optional[str] = None
    articles_mensuels: int = 0
    articles_ponctuels: int = 0

class InvoiceData(BaseModel):
    invoice_number: str
    invoice_date: Optional[str] = None
    client_number: Optional[str] = None
    client_name: Optional[str] = None
    total: float = 0.0
    total_ht: Optional[float] = None
    total_ttc: Optional[float] = None
    contracts: List[ContractInfo] = []
    source_file: Optional[str] = None
    period_start: Optional[str] = None  # AJOUTÉ
    period_end: Optional[str] = None    # AJOUTÉ