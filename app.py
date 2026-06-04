"""FastAPI API — Extracteur de factures IAM YAZAKI.
Auto-routing : N° Client → Usine → Départements → Budget.
Endpoints pour l'extraction et la gestion des factures.
"""

from __future__ import annotations
import string
import traceback

import io
import base64
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fastapi import BackgroundTasks
import asyncio
from concurrent.futures import ThreadPoolExecutor

# ─── Imports internes ─────────────────────────────────────────────────────────
from config import load_config, safe_filename, fmt_money, DATA_DIR, ROOT_DIR
from invoice_utils import contracts_dataframe, save_invoice_record, load_ocr_engine
from invoice_parser import parse_invoice
from budget_tracker import BudgetTracker
from budget_models import DuplicateInvoiceError, ValidationError, BudgetProcessingError
import database as db
from excel_export import contracts_to_excel  
from models import ContractInfo, InvoiceData

# Create a thread pool for parallel extraction tasks
batch_executor = ThreadPoolExecutor(max_workers=4)


# ─── Configuration ───────────────────────────────────────────────────────────
CONFIG_PATH = ROOT_DIR / "config.json"

# ─── Models Pydantic ─────────────────────────────────────────────────────────



class ProcessInvoiceResponse(BaseModel):
    success: bool
    message: str
    plant: Optional[str] = None
    contracts_processed: int = 0
    total_deducted: float = 0
    departments_affected: List[str] = []
    unassigned_contracts: List[dict] = []
    duplicate: bool = False
    validation_error: Optional[str] = None
    budget_error: Optional[str] = None

class DepartmentBudget(BaseModel):
    department_name: str
    cost_center_id: str
    initial_budget: float
    total_spent: float
    remaining_budget: float
    budget_status: str
    percentage_used: float

class PlantBudgetResponse(BaseModel):
    plant_name: str
    total_budget: float
    total_spent: float
    total_remaining: float
    usage_percentage: float
    departments: List[DepartmentBudget]

class DepartmentBudgetUpdate(BaseModel):
    plant_name: str
    department_name: str
    new_budget: Optional[float] = None
    adjustment_amount: Optional[float] = None

class ClientPlantMapping(BaseModel):
    client_number: str
    plant_name: str

class DepartmentConfig(BaseModel):
    name: str
    cost_center_id: str
    budget: float
    phone_numbers: List[str] = []

class PlantConfig(BaseModel):
    name: str
    departments: List[DepartmentConfig] = []

class ConfigResponse(BaseModel):
    client_plant_mapping: dict
    plants: dict

class TransactionResponse(BaseModel):
    id: int
    created_at: str
    plant_name: str
    department_name: str
    invoice_number: Optional[str] = None
    transaction_type: str
    old_budget: float
    amount: float
    new_budget: float

# ─── Global State ─────────────────────────────────────────────────────────────

class AppState:
    def __init__(self):
        self.budget_tracker: Optional[BudgetTracker] = None
        self.config = {}
    
    def init_budget_tracker(self):
        self.budget_tracker = BudgetTracker()
        self.budget_tracker.init_departments(self.config)

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app."""
    # Startup
    db.init_db()
    state.config = load_full_config()
    state.init_budget_tracker()
    print("✅ Application démarrée avec succès")
    yield
    # Shutdown
    print("👋 Application arrêtée")
# ─── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="YAZAKI IAM Invoice Extractor API",
    description="API pour l'extraction et la gestion des factures IAM YAZAKI",
    version="2.0",
    lifespan=lifespan
)

# ─── CORS Middleware ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ─── Helpers de mapping ──────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-_/]+", "", s)

def load_full_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"client_plant_mapping": {}, "plants": {}}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def save_full_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

def find_plant_for_client(cfg: dict, client_number: str) -> str | None:
    """Retourne le nom de l'usine associée à ce N° Client."""
    mapping = cfg.get("client_plant_mapping", {})
    # Correspondance exacte d'abord
    if client_number in mapping:
        return mapping[client_number]
    # Correspondance normalisée
    cn = _norm(client_number)
    for k, v in mapping.items():
        if _norm(k) == cn:
            return v
    return None

def find_dept_for_phone(cfg: dict, plant: str, phone: str) -> tuple[str | None, dict]:
    """Retourne (nom_dept, info_dept) pour un numéro d'appel dans une usine."""
    phone_norm = re.sub(r"\s+", "", phone)
    plant_cfg = cfg.get("plants", {}).get(plant, {})
    for dept_name, dept_info in plant_cfg.get("departments", {}).items():
        for p in dept_info.get("phone_numbers", []):
            if re.sub(r"\s+", "", p) == phone_norm:
                return dept_name, dept_info
    return None, {}

def compute_dept_breakdown(cfg: dict, plant: str, contracts: list) -> dict:
    """
    Regroupe les TOTAL CONTRAT par département.
    Retourne {dept_name: {cost_center_id, budget, spent, contracts:[...]}}
    """
    plant_cfg = cfg.get("plants", {}).get(plant, {})
    result: dict[str, dict] = {}

    # Initialiser tous les départements
    for dept_name, dept_info in plant_cfg.get("departments", {}).items():
        result[dept_name] = {
            "cost_center_id": dept_info.get("cost_center_id", "—"),
            "budget": float(dept_info.get("budget", 0)),
            "spent": 0.0,
            "contracts": [],
        }

    # Répartir les contrats
    unassigned = []
    for c in contracts:
        phone = getattr(c, 'phone_number', None) or ""
        dept_name, _ = find_dept_for_phone(cfg, plant, phone)
        if dept_name and dept_name in result:
            result[dept_name]["spent"] += c.total_contrat
            result[dept_name]["contracts"].append(c)
        else:
            unassigned.append(c)

    if unassigned:
        result["⚠️ Non assigné"] = {
            "cost_center_id": "—",
            "budget": 0.0,
            "spent": sum(c.total_contrat for c in unassigned),
            "contracts": unassigned,
        }

    return result

# ─── API Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "YAZAKI IAM Invoice Extractor API",
        "version": "2.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "process_invoice": "/api/invoices/process (POST)",
            "get_plants": "/api/plants",
            "get_plant_budget": "/api/plants/{plant_name}/budget",
            "get_config": "/api/config",
            "update_config": "/api/config (POST)",
            "get_invoices": "/api/invoices",
            "get_transactions": "/api/transactions"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/invoices/process", response_model=ProcessInvoiceResponse)
async def process_invoice(
    file: UploadFile = File(...),
    use_ocr: bool = Query(False, description="Forcer l'utilisation de l'OCR"),
    ocr_available: bool = Query(True, description="Indique si l'OCR est disponible")
):
    """
    Traite une facture IAM (PDF) et applique les déductions budgétaires.
    
    - use_ocr=False (default): Extraction normale sans OCR
    - use_ocr=True: Force l'utilisation de l'OCR pour toutes les pages
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    try:
        # Load OCR engine ONLY if forced
        ocr_engine = None
        if use_ocr:
            if not ocr_available:
                return ProcessInvoiceResponse(
                    success=False,
                    message="OCR demandé mais non disponible",
                    validation_error="Modules OCR manquants"
                )
            ocr_engine, ocr_err = load_ocr_engine()
            if ocr_engine is None:
                return ProcessInvoiceResponse(
                    success=False,
                    message=f"Erreur OCR : {ocr_err}",
                    validation_error=ocr_err
                )
        
        # Lire le fichier
        contents = await file.read()
        buf = io.BytesIO(contents)
        
        # Parser la facture - OCR engine sera None si use_ocr=False
        inv = parse_invoice(buf, ocr_engine=ocr_engine, progress_callback=None)
        
        # Rest of your code remains the same...

        print("INVOICE =", type(inv))
        print("NB CONTRACTS PARSED =", len(getattr(inv, "contracts", [])))

        inv.source_file = file.filename
        # Générer un numéro de facture de secours uniquement si le parser n'en a pas trouvé
        if not inv.invoice_number:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            clean = re.sub(r"[^A-Za-z0-9_-]", "_", file.filename.rsplit(".", 1)[0])
            inv.invoice_number = f"{clean}_{ts}"
        
        # Trouver l'usine
        cfg = state.config
        client_num = inv.client_number or ""
        plant = find_plant_for_client(cfg, client_num)
        
        if not plant:
            return ProcessInvoiceResponse(
                success=False,
                message=f"N° Client '{client_num}' non mappé à une usine",
                plant=None
            )
        
        # Traiter la facture avec le budget tracker
        is_duplicate = False
        try:
            result = state.budget_tracker.process_invoice(inv, plant, cfg)
            
            # Sauvegarder dans la base de données
            dept_statuses = state.budget_tracker.get_department_status(plant)
            depts_active = [d.department_name for d in dept_statuses if d.total_spent > 0]
            dept_label = ", ".join(depts_active[:3]) + ("…" if len(depts_active) > 3 else "")
            record = save_invoice_record(inv, plant, dept_label or "Multi-depts", "IAM")
            
            try:
                print("DEBUG contracts =", len(record["contracts"]))
                invoice_id = db.save_invoice(record)
            except Exception as exc:
                print(f"⚠️ SQLite : {exc}")
            
            return ProcessInvoiceResponse(
                success=True,
                message=f"Facture traitée avec succès : {result.contracts_processed} contrat(s), {fmt_money(result.total_deducted)} déduit(s)",
                plant=plant,
                contracts_processed=result.contracts_processed,
                total_deducted=result.total_deducted,
                departments_affected=list(result.departments_affected),
                unassigned_contracts=[],
            )
            
        except DuplicateInvoiceError as e:
            return ProcessInvoiceResponse(
                success=False,
                message=e.message,
                plant=plant,
                duplicate=True
            )
        except ValidationError as e:
            return ProcessInvoiceResponse(
                success=False,
                message=f"Erreur de validation : {e.message}",
                plant=plant,
                validation_error=e.message
            )
        except BudgetProcessingError as e:
            return ProcessInvoiceResponse(
                success=False,
                message=f"Erreur budgétaire : {e.message}",
                plant=plant,
                budget_error=e.message
            )
            
    except Exception as e:
        # Log the full error
        error_details = traceback.format_exc()
        print(f"ERROR processing invoice: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
@app.post("/api/invoices/debug")
async def debug_invoice(file: UploadFile = File(...)):
    """Endpoint de debug pour voir ce que le parser extrait."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    try:
        contents = await file.read()
        buf = io.BytesIO(contents)
        
        inv = parse_invoice(buf, ocr_engine=None, progress_callback=None)
        
        return {
            "success": True,
            "invoice_number": inv.invoice_number,
            "client_number": inv.client_number,
            "invoice_date": inv.invoice_date,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "total": inv.total,
            "contracts_count": len(inv.contracts),
            "global_summary": {
                "montant_ht": inv.global_summary.montant_ht,
                "montant_ttc": inv.global_summary.montant_ttc,
                "montant_tva": inv.global_summary.montant_tva,
            },
            "contracts": [
                {
                    "phone_number": c.phone_number,
                    "contract_type": c.contract_type,
                    "total_contrat": c.total_contrat,
                    "period_start": c.period_start,
                    "period_end": c.period_end,
                    "articles_mensuels": c.articles_mensuels,
                    "articles_ponctuels": c.articles_ponctuels,
                }
                for c in inv.contracts
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    
@app.post("/api/invoices/debug")
async def debug_invoice(file: UploadFile = File(...)):
    """Endpoint de debug pour voir ce que le parser extrait."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    try:
        contents = await file.read()
        buf = io.BytesIO(contents)
        
        inv = parse_invoice(buf, ocr_engine=None, progress_callback=None)
        
        return {
            "success": True,
            "invoice_number": inv.invoice_number,
            "client_number": inv.client_number,
            "invoice_date": inv.invoice_date,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "total": inv.total,
            "contracts_count": len(inv.contracts),
            "global_summary": {
                "montant_ht": inv.global_summary.montant_ht,
                "montant_ttc": inv.global_summary.montant_ttc,
                "montant_tva": inv.global_summary.montant_tva,
            },
            "contracts": [
                {
                    "phone_number": c.phone_number,
                    "contract_type": c.contract_type,
                    "total_contrat": c.total_contrat,
                    "period_start": c.period_start,
                    "period_end": c.period_end,
                    "articles_mensuels": c.articles_mensuels,
                    "articles_ponctuels": c.articles_ponctuels,
                }
                for c in inv.contracts
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/invoices/debug-full")
async def debug_full_invoice(file: UploadFile = File(...)):
    """Debug complet - montre tout ce que le parser extrait."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    try:
        contents = await file.read()
        buf = io.BytesIO(contents)
        
        inv = parse_invoice(buf, ocr_engine=None, progress_callback=None)
        
        # Extraire les premières lignes du PDF pour voir le texte brut
        from pdfplumber import open as pdf_open
        buf.seek(0)
        first_page_text = ""
        with pdf_open(buf) as pdf:
            if len(pdf.pages) > 0:
                first_page_text = pdf.pages[0].extract_text()[:2000]
        
        return {
            "success": True,
            "extracted_data": {
                "invoice_number": inv.invoice_number,
                "client_number": inv.client_number,
                "invoice_date": inv.invoice_date,
                "period_start": inv.period_start,
                "period_end": inv.period_end,
                "total": inv.total,
                "contracts_count": len(inv.contracts),
            },
            "first_page_text": first_page_text,
            "all_phone_numbers": list(set([c.phone_number for c in inv.contracts if c.phone_number]))[:10]
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

@app.delete("/api/invoices/clear-all")
async def clear_all_invoices_data():
    """Supprime TOUTES les factures et transactions."""
    try:
        # Vider la table des factures
        db.clear_all_invoices()
        
        # Vider les transactions budgétaires
        with db.get_conn() as conn:
            conn.execute("DELETE FROM budget_transactions")
            conn.execute("DELETE FROM departments")
        
        # Réinitialiser la configuration
        state.budget_tracker.init_departments(state.config)
        
        return {"success": True, "message": "Toutes les données ont été effacées"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/api/invoices/export/{invoice_id}")
async def export_invoice_excel(invoice_id: int):
    """
    Exporte une facture au format Excel en corrigeant et réalignant 
    les décalages de dates de périodes (Maroc Telecom).
    """
    try:
        invoice_data = db.get_invoice_raw(invoice_id)
        if not invoice_data:
            invoices = db.list_invoices()
            invoice_data = next((i for i in invoices if i.get('id') == invoice_id), None)
            
        if not invoice_data:
            raise HTTPException(status_code=404, detail="Facture non trouvée")
        
        # 1. Extraction des métadonnées globales de la facture
        inv_date_str = invoice_data.get('invoice_date') or '—'
        
        # Correction intelligente de la période globale (Ex: Facture du 14/04/2026 -> Période de Mars 2026)
        global_start = invoice_data.get('period_start')
        global_end = invoice_data.get('period_end')
        
        if (not global_start or global_start == inv_date_str) and '/' in inv_date_str:
            try:
                day, month, year = map(int, inv_date_str.split('/'))
                # Reculer d'un mois pour trouver la période de consommation réelle
                target_month = month - 1 if month > 1 else 12
                target_year = year if month > 1 else year - 1
                global_start = f"01/{target_month:02d}/{target_year}"
                
                # Trouver le dernier jour du mois de consommation
                if target_month in [4, 6, 9, 11]:
                    last_day = 30
                elif target_month == 2:
                    last_day = 29 if (target_year % 4 == 0 and (target_year % 100 != 0 or target_year % 400 == 0)) else 28
                else:
                    last_day = 31
                global_end = f"{last_day:02d}/{target_month:02d}/{target_year}"
            except Exception:
                global_start = global_start or "—"
                global_end = global_end or "—"

        # 2. Correction et reconstruction de la liste des contrats
        contracts = []
        raw_contracts = invoice_data.get('contracts', [])
        
        for idx, c in enumerate(raw_contracts, start=1):
            phone = c.get('phone_number') or c.get('N dAppel') or "—"
            c_type = c.get('contract_type') or c.get('Extraction_Method') or "FORFAIT IAM"
            
            total_val = c.get('total_contrat') or c.get('Total Contrat') or 0.0
            total_float = float(str(total_val).replace(" ", "").replace(",", ".")) if isinstance(total_val, str) else float(total_val)
            
            # --- ALGORITHME DE RÉALIGNEMENT DES DATES DÉCALÉES ---
            raw_start = c.get('period_start')
            raw_end = c.get('period_end')
            
            # Si le parser a copié la date de facture dans le début de période
            if raw_start == inv_date_str or raw_start == invoice_data.get('invoice_date'):
                # Alors la vraie date de début est descendue dans la case de fin !
                p_start = raw_end if raw_end else global_start
                # Et la vraie date de fin est déduite globalement ou via le mois du début
                p_end = global_end
            else:
                p_start = raw_start or global_start or "—"
                p_end = raw_end or global_end or "—"
                
            # Double sécurité : si les champs restent vides, appliquer la période globale corrigée
            if not p_start or p_start == "—": p_start = global_start
            if not p_end or p_end == "—": p_end = global_end

            page_num = c.get('page_number') or c.get('Page') or idx

            contract = ContractInfo(
                phone_number=str(phone).strip(),
                contract_type=str(c_type).strip(),
                period_start=str(p_start).strip(),
                period_end=str(p_end).strip(),
                total_contrat=total_float,
                page_number=page_num,
                document_page=str(page_num),
                articles_mensuels=len(c.get('frais_mensuels', [])) or int(c.get('articles_mensuels', 0)),
                articles_ponctuels=len(c.get('frais_ponctuels', [])) or int(c.get('articles_ponctuels', 0))
            )
            contracts.append(contract)
        
        # 3. Assembler l'objet InvoiceData complet pour excel_export.py
        invoice_obj = InvoiceData(
            invoice_number=str(invoice_data.get('invoice_number') or '—'),
            invoice_date=inv_date_str,
            client_number=invoice_data.get('client_number') or '—',
            client_name=invoice_data.get('client_name') or "YAZAKI MOROCCO",
            total=float(invoice_data.get('total') or 0.0),
            total_ht=invoice_data.get('total_ht'),
            total_ttc=invoice_data.get('total_ttc'),
            contracts=contracts,
            source_file=invoice_data.get('source_file'),
            period_start=global_start,
            period_end=global_end
        )
        
        # 4. Générer l'Excel via openpyxl
        plant = invoice_data.get('plant', 'YAZAKI ZONE AGROPOLIS')
        departments = invoice_data.get('departments') or invoice_data.get('department') or 'Multi-départements'
        
        excel_bytes = contracts_to_excel(
            invoice=invoice_obj,
            plant=plant,
            dept=departments,
            project=""
        )
        
        # 5. Stream de téléchargement vers le navigateur web
        filename = f"Rapport_Yazaki_{invoice_obj.invoice_number.split(' ')[0]}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        import traceback
        print(f"❌ ERROR in Excel export reconstruction: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    





@app.post("/api/invoices/process-batch")
async def process_multiple_invoices(
    files: List[UploadFile] = File(..., description="PDF files to process"),
    use_ocr: bool = Query(default=False, description="Forcer l'utilisation de l'OCR pour tous les fichiers")
):
    """
    Processes multiple IAM invoices.
    
    - use_ocr=False: Normal extraction without OCR
    - use_ocr=True: Force OCR for all pages of all files
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")
        
    cfg = state.config
    
    # Load OCR engine ONLY if forced
    ocr_engine = None
    if use_ocr:
        ocr_engine, _ = load_ocr_engine()
        if ocr_engine is None:
            print("WARNING: OCR requested but unavailable")
    
    # Rest of your batch code remains the same...

    processed_invoices_models = []
    messages = []
    
    # 1. Helper function to process a single file inside the thread pool
    def process_single_file(file_bytes: bytes, filename: str):
        buf = io.BytesIO(file_bytes)
        inv = parse_invoice(buf, ocr_engine=ocr_engine, progress_callback=None)
        inv.source_file = filename
        
        if not inv.invoice_number:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            inv.invoice_number = f"{filename.rsplit('.', 1)[0]}_{ts}"
            
        return inv

    # 2. Execute parallel extraction jobs using asyncio
    loop = asyncio.get_running_loop()
    tasks = []
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            continue
        file_contents = await file.read()
        tasks.append(
            loop.run_in_executor(batch_executor, process_single_file, file_contents, file.filename)
        )
    
    extracted_invoices = await asyncio.gather(*tasks)

    # 3. Apply atomic budget tracking and save database logs
    from excel_export import contracts_to_excel_batch

    for inv in extracted_invoices:
        client_num = inv.client_number or ""
        plant = find_plant_for_client(cfg, client_num)
        
        if not plant:
            messages.append(f"⚠️ {inv.source_file}: N° Client '{client_num}' non mappé.")
            continue
            
        try:
            result = state.budget_tracker.process_invoice(inv, plant, cfg)
            
            dept_statuses = state.budget_tracker.get_department_status(plant)
            depts_active = [d.department_name for d in dept_statuses if d.total_spent > 0]
            dept_label = ", ".join(depts_active[:3]) + ("…" if len(depts_active) > 3 else "")
            
            record = save_invoice_record(inv, plant, dept_label or "Multi-depts", "IAM")
            db.save_invoice(record)
            
            # --- CALCULATE TRUE END OF MONTH FROM INVOICE DATE ---
            global_start = "—"
            global_end = "—"
            inv_date_str = inv.invoice_date or '—'
            
            if '/' in inv_date_str:
                try:
                    day, month, year = map(int, inv_date_str.split('/'))
                    # Shift back 1 month to determine consumption period
                    target_month = month - 1 if month > 1 else 12
                    target_year = year if month > 1 else year - 1
                    global_start = f"01/{target_month:02d}/{target_year}"
                    
                    # Compute accurate final day of consumption month
                    if target_month in [4, 6, 9, 11]:
                        last_day = 30
                    elif target_month == 2:
                        last_day = 29 if (target_year % 4 == 0 and (target_year % 100 != 0 or target_year % 400 == 0)) else 28
                    else:
                        last_day = 31
                    global_end = f"{last_day:02d}/{target_month:02d}/{target_year}"
                except Exception:
                    global_start = inv.period_start or "—"
                    global_end = inv.period_end or "—"

            # Inject the true calculated calendar dates into the data objects
            inv.period_start = global_start
            inv.period_end = global_end

            contracts = []
            for idx, c in enumerate(inv.contracts, start=1):
                contracts.append(ContractInfo(
                    phone_number=c.phone_number or "—",
                    contract_type=c.contract_type or "FORFAIT IAM",
                    period_start=global_start,
                    period_end=global_end,  # Forces 31/03/2026 for a March bill
                    total_contrat=float(c.total_contrat or 0.0),
                    page_number=c.page_number or idx,
                    document_page=str(c.page_number or idx),
                    articles_mensuels=getattr(c, 'articles_mensuels', 0),
                    articles_ponctuels=getattr(c, 'articles_ponctuels', 0)
                ))
            
            inv.contracts = contracts
            processed_invoices_models.append(inv)
            messages.append(f"✅ {inv.source_file} traité.")

        except DuplicateInvoiceError:
            messages.append(f"ℹ️ {inv.source_file} ignoré (déjà imputé).")
        except Exception as e:
            messages.append(f"❌ Erreur sur {inv.source_file}: {str(e)}")

    if not processed_invoices_models:
        raise HTTPException(status_code=422, detail=f"Aucune facture n'a pu être imputée. Statut: {'; '.join(messages)}")

    # 4. Call your modified core batch generator script (now returning list[bytes])
    excel_files_list = contracts_to_excel_batch(
        invoices=processed_invoices_models,
        plant=processed_invoices_models[0].client_number or "YAZAKI MOROCCO", 
        dept="Multi-départements",
        project="BATCH_RUN"
    )

    # 5. Build response mapping each file buffer to its file name
    response_payload = {
        "success": True,
        "summary": messages,
        "files": []
    }

    for inv_model, excel_bytes in zip(processed_invoices_models, excel_files_list):
        invoice_num_clean = str(inv_model.invoice_number).split(" ")[0].strip()
        filename = f"Rapport_Yazaki_{invoice_num_clean}.xlsx"
        
        b64_encoded_str = base64.b64encode(excel_bytes).decode("utf-8")
        
        response_payload["files"].append({
            "filename": filename,
            "file_contents": b64_encoded_str
        })

    return JSONResponse(content=response_payload)

@app.get("/api/plants", response_model=List[str])
async def get_plants():
    """Retourne la liste de toutes les usines configurées."""
    cfg = state.config
    plants = list(cfg.get("plants", {}).keys())
    return plants
@app.get("/api/plants/{plant_name}/budget", response_model=PlantBudgetResponse)
async def get_plant_budget(plant_name: str):
    """
    Retourne les informations budgétaires pour une usine spécifique.
    """
    try:
        cfg = state.config
        print(f"DEBUG: Looking for plant '{plant_name}' in config: {list(cfg.get('plants', {}).keys())}")
        
        if plant_name not in cfg.get("plants", {}):
            raise HTTPException(status_code=404, detail=f"Usine '{plant_name}' non trouvée. Available plants: {list(cfg.get('plants', {}).keys())}")
        
        dept_statuses = state.budget_tracker.get_department_status(plant_name)
        
        if not dept_statuses:
            raise HTTPException(status_code=404, detail=f"Aucun département configuré pour l'usine '{plant_name}'")
        
        total_budget = sum(d.initial_budget for d in dept_statuses)
        total_spent = sum(d.total_spent for d in dept_statuses)
        total_remaining = sum(d.remaining_budget for d in dept_statuses)
        usage_percentage = (total_spent / total_budget * 100) if total_budget > 0 else 0
        
        departments = []
        for d in dept_statuses:
            pct_used = (d.total_spent / d.initial_budget * 100) if d.initial_budget > 0 else 0
            departments.append(DepartmentBudget(
                department_name=d.department_name,
                cost_center_id=d.cost_center_id,
                initial_budget=d.initial_budget,
                total_spent=d.total_spent,
                remaining_budget=d.remaining_budget,
                budget_status=d.budget_status,
                percentage_used=pct_used
            ))
        
        return PlantBudgetResponse(
            plant_name=plant_name,
            total_budget=total_budget,
            total_spent=total_spent,
            total_remaining=total_remaining,
            usage_percentage=usage_percentage,
            departments=departments
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"ERROR in get_plant_budget: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/budget/reset")
async def reset_budget(update: DepartmentBudgetUpdate):
    """
    Réinitialise le budget d'un département.
    """
    if update.new_budget is None:
        raise HTTPException(status_code=400, detail="new_budget est requis")
    
    if update.new_budget <= 0:
        raise HTTPException(status_code=400, detail="Le budget doit être supérieur à 0")
    
    try:
        state.budget_tracker.reset_budget(
            update.plant_name,
            update.department_name,
            update.new_budget
        )
        return {"success": True, "message": f"Budget réinitialisé à {fmt_money(update.new_budget)}"}
    except (ValidationError, BudgetProcessingError) as e:
        raise HTTPException(status_code=400, detail=e.message)

@app.post("/api/budget/adjust")
async def adjust_budget(update: DepartmentBudgetUpdate):
    """
    Ajuste le budget d'un département (positif ou négatif).
    """
    if update.adjustment_amount is None:
        raise HTTPException(status_code=400, detail="adjustment_amount est requis")
    
    try:
        state.budget_tracker.adjust_budget(
            update.plant_name,
            update.department_name,
            update.adjustment_amount
        )
        return {"success": True, "message": f"Ajustement de {fmt_money(update.adjustment_amount)} appliqué"}
    except (ValidationError, BudgetProcessingError) as e:
        raise HTTPException(status_code=400, detail=e.message)

@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Retourne la configuration complète."""
    return ConfigResponse(
        client_plant_mapping=state.config.get("client_plant_mapping", {}),
        plants=state.config.get("plants", {})
    )

@app.post("/api/config")
async def update_config(config: dict):
    """
    Met à jour la configuration complète.
    """
    try:
        print(f"DEBUG: Received config update: {config}")
        
        # Validate config structure
        if "plants" not in config:
            config["plants"] = {}
        if "client_plant_mapping" not in config:
            config["client_plant_mapping"] = {}
        
        # Validate plant data
        for plant_name, plant_data in config["plants"].items():
            if "departments" not in plant_data:
                plant_data["departments"] = {}
            print(f"DEBUG: Plant '{plant_name}' has departments: {list(plant_data['departments'].keys())}")
        
        save_full_config(config)
        state.config = config
        state.budget_tracker.init_departments(config)
        
        # Verify the update worked
        print(f"DEBUG: Config updated successfully. Plants: {list(state.config.get('plants', {}).keys())}")
        
        return {"success": True, "message": "Configuration sauvegardée avec succès"}
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"ERROR updating config: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/api/debug/state")
async def debug_state():
    """
    Debug endpoint to inspect current application state.
    """
    return {
        "config_plants": list(state.config.get("plants", {}).keys()),
        "budget_tracker_plants": list(state.budget_tracker.departments.keys()) if state.budget_tracker else [],
        "has_budget_tracker": state.budget_tracker is not None,
        "config_path_exists": CONFIG_PATH.exists(),
        "config_content": state.config
    }

@app.post("/api/config/client-mapping")
async def add_client_mapping(mapping: ClientPlantMapping):
    """
    Ajoute ou met à jour un mapping N° Client → Usine.
    """
    try:
        cfg = state.config
        if "client_plant_mapping" not in cfg:
            cfg["client_plant_mapping"] = {}
        
        cfg["client_plant_mapping"][mapping.client_number] = mapping.plant_name
        
        # S'assurer que l'usine existe dans plants
        if mapping.plant_name not in cfg.get("plants", {}):
            if "plants" not in cfg:
                cfg["plants"] = {}
            cfg["plants"][mapping.plant_name] = {"departments": {}}
        
        save_full_config(cfg)
        state.config = cfg
        state.budget_tracker.init_departments(cfg)
        
        return {"success": True, "message": f"Mapping ajouté: {mapping.client_number} → {mapping.plant_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/plant-department")
async def add_department(plant_name: str, department: DepartmentConfig):
    """
    Ajoute ou met à jour un département pour une usine.
    """
    try:
        cfg = state.config
        
        if plant_name not in cfg.get("plants", {}):
            cfg["plants"][plant_name] = {"departments": {}}
        
        cfg["plants"][plant_name]["departments"][department.name] = {
            "cost_center_id": department.cost_center_id,
            "budget": department.budget,
            "phone_numbers": department.phone_numbers
        }
        
        save_full_config(cfg)
        state.config = cfg
        state.budget_tracker.init_departments(cfg)
        
        return {"success": True, "message": f"Département {department.name} ajouté à {plant_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/invoices")
async def get_invoices(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    plant: Optional[str] = None
):
    """
    Retourne la liste des factures enregistrées.
    """
    try:
        records = db.list_invoices()
        
        # Filtrer par usine si spécifié
        if plant:
            records = [r for r in records if r.get('plant') == plant]
        
        # Pagination
        total = len(records)
        records = records[offset:offset + limit]
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "invoices": records
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/invoices")
async def clear_invoices():
    """
    Supprime toutes les factures enregistrées.
    """
    try:
        db.clear_all_invoices()
        return {"success": True, "message": "Historique des factures vidé"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/transactions", response_model=List[TransactionResponse])
async def get_transactions(
    limit: int = Query(100, ge=1, le=1000),
    invoice_number: Optional[str] = None,
    plant_name: Optional[str] = None,
    department_name: Optional[str] = None
):
    """
    Retourne l'historique des transactions budgétaires.
    """
    try:
        if invoice_number:
            transactions = state.budget_tracker.get_transactions(
                invoice_number=invoice_number,
                limit=limit
            )
        else:
            transactions = state.budget_tracker.get_transactions(limit=limit)
        
        # Filtrer supplémentaire
        if plant_name:
            transactions = [t for t in transactions if t.get('plant_name') == plant_name]
        if department_name:
            transactions = [t for t in transactions if t.get('department_name') == department_name]
        
        # Convertir en modèles Pydantic
        result = []
        for t in transactions[:limit]:
            result.append(TransactionResponse(
                id=t.get('id', 0),
                created_at=str(t.get('created_at', '')),
                plant_name=t.get('plant_name', ''),
                department_name=t.get('department_name', ''),
                invoice_number=t.get('invoice_number'),
                transaction_type=t.get('transaction_type', ''),
                old_budget=t.get('old_budget', 0.0),
                amount=t.get('amount', 0.0),
                new_budget=t.get('new_budget', 0.0)
            ))
        
        return result
    except Exception as e:
        # Log the full traceback
        error_details = traceback.format_exc()
        print(f"ERROR in /api/transactions: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        raise HTTPException(status_code=500, detail=f"{str(e)} - Check server logs for details")



@app.get("/api/reports/plant-summary")
async def get_plant_summary():
    """
    Retourne un résumé budgétaire pour toutes les usines.
    """
    cfg = state.config
    plants = list(cfg.get("plants", {}).keys())
    
    summary = []
    for plant in plants:
        try:
            dept_statuses = state.budget_tracker.get_department_status(plant)
            if dept_statuses:
                total_budget = sum(d.initial_budget for d in dept_statuses)
                total_spent = sum(d.total_spent for d in dept_statuses)
                summary.append({
                    "plant_name": plant,
                    "total_budget": total_budget,
                    "total_spent": total_spent,
                    "total_remaining": total_budget - total_spent,
                    "usage_percentage": (total_spent / total_budget * 100) if total_budget > 0 else 0
                })
        except Exception as e:
            print(f"Erreur pour {plant}: {e}")
    
    return {"plants": summary, "total_plants": len(summary)}

# ─── Pour exécuter l'application ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)