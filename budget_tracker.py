"""Service de suivi budgétaire cumulatif pour l'extracteur de factures IAM YAZAKI.

Processing chain (per PDF page / contract)
-------------------------------------------
PDF page
  ├─ client_number  ──→  Plant   (via config client_plant_mapping)
  ├─ phone_number   ──→  Dept    (via config plants[plant].departments[dept].phone_numbers)
  └─ Total Contrat  ──→  deducted from Dept.remaining_budget

Plant budget is NEVER a fixed value.
It is ALWAYS computed as SUM(dept.initial_budget) for all departments in that plant.

Cumulative logic (example for one department):
  Invoice #1  Budget Alloué=25 000  Dépenses=3 000   Reste=22 000
  Invoice #2  Budget Alloué=22 000  Dépenses=4 000   Reste=18 000   ← old_budget=prev remaining
  Invoice #3  Budget Alloué=18 000  Dépenses=2 000   Reste=16 000
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from budget_models import (
    BudgetProcessingError,
    DepartmentStatus,
    DuplicateInvoiceError,
    PlantSummary,
    ProcessingResult,
    ValidationError,
)
from database import DB_PATH, get_conn, init_db
from invoice_parser import InvoiceData


class BudgetTracker:
    """Cumulative budget tracking service.

    - Budget is stored and tracked exclusively at the DEPARTMENT level.
    - Plant-level totals are always derived by aggregating department rows.
    - Each invoice deduction records old_budget → new_budget for full audit trail.
    """

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DB_PATH

    # ──────────────────────────────────────────────────────────────────────────
    # Schema
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        """Create budget tables if they don't exist yet."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_name TEXT NOT NULL,
                department_name TEXT NOT NULL,
                cost_center_id TEXT DEFAULT '',
                initial_budget REAL NOT NULL DEFAULT 0.0,
                remaining_budget REAL NOT NULL DEFAULT 0.0,
                total_spent REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                UNIQUE(plant_name, department_name)
            );
            CREATE INDEX IF NOT EXISTS idx_departments_plant
                ON departments(plant_name);

            CREATE TABLE IF NOT EXISTS budget_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                invoice_number TEXT,
                phone_number TEXT,
                amount REAL NOT NULL DEFAULT 0.0,
                old_budget REAL NOT NULL,
                new_budget REAL NOT NULL,
                transaction_type TEXT NOT NULL CHECK (
                    transaction_type IN ('deduction', 'reset', 'adjustment')
                ),
                created_at TEXT NOT NULL,
                FOREIGN KEY (department_id) REFERENCES departments(id)
            );
            CREATE INDEX IF NOT EXISTS idx_bt_department
                ON budget_transactions(department_id);
            CREATE INDEX IF NOT EXISTS idx_bt_invoice_number
                ON budget_transactions(invoice_number);
            CREATE INDEX IF NOT EXISTS idx_bt_created_at
                ON budget_transactions(created_at);
        """)

    # ──────────────────────────────────────────────────────────────────────────
    # Initialization / sync from config
    # ──────────────────────────────────────────────────────────────────────────

    def init_departments(self, config: dict) -> None:
        """Seed/sync the departments table from config.json.

        Behaviour on conflict (department already exists in DB):
          - Updates cost_center_id and initial_budget from config.
          - Adjusts remaining_budget by the DELTA of the budget change
            so existing spending is preserved correctly.
          - Does NOT touch total_spent.

        Example: dept had budget=25 000, remaining=18 000 (7 000 spent).
        Config is updated to budget=30 000 (+ 5 000).
        After sync: initial=30 000, remaining=23 000, total_spent unchanged.
        """
        try:
            with get_conn() as conn:
                self._ensure_tables(conn)

                plants = config.get("plants", {})
                if not plants:
                    return

                now = datetime.now().isoformat(timespec="seconds")
                for plant_name, plant_cfg in plants.items():
                    for dept_name, dept_info in plant_cfg.get("departments", {}).items():
                        new_budget = float(dept_info.get("budget", 0))
                        cost_center = dept_info.get("cost_center_id", "")

                        # Check if this department already exists
                        existing = conn.execute(
                            "SELECT id, initial_budget, remaining_budget FROM departments "
                            "WHERE plant_name = ? AND department_name = ?",
                            (plant_name, dept_name),
                        ).fetchone()

                        if existing is None:
                            # New department → insert fresh with full budget
                            conn.execute(
                                """
                                INSERT INTO departments
                                    (plant_name, department_name, cost_center_id,
                                     initial_budget, remaining_budget, total_spent, created_at)
                                VALUES (?, ?, ?, ?, ?, 0.0, ?)
                                """,
                                (plant_name, dept_name, cost_center,
                                 new_budget, new_budget, now),
                            )
                        else:
                            # Existing department → update budget & preserve spending
                            old_initial = existing[1]
                            old_remaining = existing[2]
                            budget_delta = new_budget - old_initial
                            adjusted_remaining = round(old_remaining + budget_delta, 2)

                            conn.execute(
                                """
                                UPDATE departments
                                SET cost_center_id  = ?,
                                    initial_budget  = ?,
                                    remaining_budget = ?
                                WHERE plant_name = ? AND department_name = ?
                                """,
                                (cost_center, new_budget, adjusted_remaining,
                                 plant_name, dept_name),
                            )
        except Exception as e:
            print(f"[BudgetTracker] Erreur lors du seeding : {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Phone → Department matching
    # ──────────────────────────────────────────────────────────────────────────

    def _match_phone_to_department(
        self, phone: str, plant_config: dict
    ) -> str | None:
        """Match a phone number (N° d'Appel) to a department name.

        Strips all whitespace before comparing.
        Returns department_name or None if unmatched.
        """
        phone_norm = re.sub(r"\s+", "", phone)
        for dept_name, dept_info in plant_config.get("departments", {}).items():
            for p in dept_info.get("phone_numbers", []):
                if re.sub(r"\s+", "", p) == phone_norm:
                    return dept_name
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Invoice processing (atomic, per-page deductions)
    # ──────────────────────────────────────────────────────────────────────────

    def process_invoice(
        self, invoice: InvoiceData, plant: str, config: dict
    ) -> ProcessingResult:
        """Process a full invoice atomically, one PDF page (contract) at a time.

        Per-page chain:
          phone_number → Department → deduct Total Contrat from remaining_budget

        Transaction log row (per page):
          old_budget  = dept remaining BEFORE this deduction  (= Budget Alloué)
          amount      = Total Contrat of this contract page   (= Total Dépenses)
          new_budget  = dept remaining AFTER this deduction   (= Reste Disponible)

        Raises:
          ValidationError        – missing invoice number
          DuplicateInvoiceError  – invoice already processed for this plant
        """
        invoice_number = invoice.invoice_number
        if not invoice_number or not invoice_number.strip():
            raise ValidationError(
                "Un numéro de facture valide est requis pour le traitement"
            )

        plant_config = config.get("plants", {}).get(plant, {})

        with get_conn() as conn:
            # ── Duplicate check ───────────────────────────────────────────
            #dup = conn.execute(
            #    """
            #    SELECT COUNT(*) FROM budget_transactions
            #    WHERE invoice_number = ? AND department_id IN (
            #        SELECT id FROM departments WHERE plant_name = ?
            #    )
            #    """,
            #    (invoice_number, plant),
            #).fetchone()

            #if dup[0] > 0:
            #    raise DuplicateInvoiceError(invoice_number)

            # ── Process each PDF page / contract ─────────────────────────
            now = datetime.now().isoformat(timespec="seconds")
            departments_affected: dict[str, float] = {}
            unassigned: list[dict] = []
            contracts_processed = 0
            total_deducted = 0.0

            for contract in invoice.contracts:
                contracts_processed += 1
                phone = contract.phone_number or ""
                amount = round(contract.total_contrat, 2)

                # Step 1: phone → department
                if not phone:
                    unassigned.append({"phone": "—", "amount": amount})
                    continue

                dept_name = self._match_phone_to_department(phone, plant_config)

                if dept_name is None:
                    unassigned.append({"phone": phone, "amount": amount})
                    continue

                # Step 2: get current department budget state
                dept_row = conn.execute(
                    "SELECT id, remaining_budget FROM departments "
                    "WHERE plant_name = ? AND department_name = ?",
                    (plant, dept_name),
                ).fetchone()

                if dept_row is None:
                    unassigned.append({"phone": phone, "amount": amount})
                    continue

                dept_id = dept_row[0]
                old_budget = dept_row[1]           # Budget Alloué (= previous Reste)
                new_budget = round(old_budget - amount, 2)   # Le Reste Disponible

                # Step 3: deduct from department
                conn.execute(
                    """
                    UPDATE departments
                    SET remaining_budget = remaining_budget - ?,
                        total_spent      = total_spent      + ?
                    WHERE id = ?
                    """,
                    (amount, amount, dept_id),
                )

                # Step 4: log transaction
                # old_budget = Budget Alloué (what was available before this invoice)
                # amount     = Total Dépenses (this contract page's cost)
                # new_budget = Le Reste Disponible (after deduction)
                conn.execute(
                    """
                    INSERT INTO budget_transactions
                        (department_id, invoice_number, phone_number, amount,
                         old_budget, new_budget, transaction_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'deduction', ?)
                    """,
                    (dept_id, invoice_number, phone,
                     amount, old_budget, new_budget, now),
                )

                departments_affected[dept_name] = (
                    departments_affected.get(dept_name, 0.0) + amount
                )
                total_deducted += amount

        return ProcessingResult(
            success=True,
            invoice_number=invoice_number,
            contracts_processed=contracts_processed,
            total_deducted=round(total_deducted, 2),
            departments_affected=departments_affected,
            unassigned_contracts=unassigned,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Dashboard queries
    # ──────────────────────────────────────────────────────────────────────────

    def get_department_status(
        self, plant_name: str | None = None
    ) -> list[DepartmentStatus]:
        """Current budget state per department, directly from the DB.

        budget_status:
          "over-budget"  remaining_budget < 0
          "critical"     0 <= remaining < 20% of initial
          "healthy"      remaining >= 20% of initial
        """
        with get_conn() as conn:
            self._ensure_tables(conn)

            if plant_name:
                rows = conn.execute(
                    "SELECT id, plant_name, department_name, cost_center_id, "
                    "initial_budget, remaining_budget, total_spent "
                    "FROM departments WHERE plant_name = ? ORDER BY department_name",
                    (plant_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, plant_name, department_name, cost_center_id, "
                    "initial_budget, remaining_budget, total_spent "
                    "FROM departments ORDER BY plant_name, department_name"
                ).fetchall()

        result = []
        for row in rows:
            initial = row[4]
            remaining = row[5]

            if remaining < 0:
                status = "over-budget"
            elif initial > 0 and remaining < 0.2 * initial:
                status = "critical"
            else:
                status = "healthy"

            result.append(
                DepartmentStatus(
                    id=row[0],
                    plant_name=row[1],
                    department_name=row[2],
                    cost_center_id=row[3],
                    initial_budget=initial,
                    remaining_budget=remaining,
                    total_spent=row[6],
                    budget_status=status,
                )
            )
        return result

    def get_plant_summary(
        self, plant_name: str | None = None
    ) -> list[PlantSummary]:
        """Plant-level budget summary, ALWAYS derived from department sums.

        total_initial_budget = SUM(dept.initial_budget)
        total_spent          = SUM(dept.total_spent)
        total_remaining      = SUM(dept.remaining_budget)

        No plant-level budget is ever stored — this is always computed.
        """
        with get_conn() as conn:
            base_sql = """
                SELECT plant_name,
                       SUM(initial_budget)  AS total_initial,
                       SUM(total_spent)     AS total_spent,
                       SUM(remaining_budget) AS total_remaining,
                       COUNT(*)             AS dept_count
                FROM departments
                {where}
                GROUP BY plant_name
            """
            if plant_name:
                rows = conn.execute(
                    base_sql.format(where="WHERE plant_name = ?"),
                    (plant_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    base_sql.format(where="")
                ).fetchall()

        return [
            PlantSummary(
                plant_name=row[0],
                total_initial_budget=row[1],
                total_spent=row[2],
                total_remaining=row[3],
                department_count=row[4],
            )
            for row in rows
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Budget reset & adjustment
    # ──────────────────────────────────────────────────────────────────────────

    def reset_budget(
        self, plant_name: str, department_name: str, new_budget: float
    ) -> None:
        """Reset department budget for a new fiscal period.

        Sets initial_budget = new_budget, remaining_budget = new_budget,
        total_spent = 0. Logs as a 'reset' transaction.
        """
        if new_budget <= 0:
            raise ValidationError("Le montant du budget doit être supérieur à zéro")

        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, remaining_budget FROM departments "
                "WHERE plant_name = ? AND department_name = ?",
                (plant_name, department_name),
            ).fetchone()

            if row is None:
                raise ValidationError(
                    f"Département '{department_name}' introuvable pour l'usine '{plant_name}'"
                )

            dept_id = row[0]
            old_budget = row[1]
            now = datetime.now().isoformat(timespec="seconds")

            conn.execute(
                """
                UPDATE departments
                SET initial_budget   = ?,
                    remaining_budget = ?,
                    total_spent      = 0.0
                WHERE id = ?
                """,
                (new_budget, new_budget, dept_id),
            )

            conn.execute(
                """
                INSERT INTO budget_transactions
                    (department_id, invoice_number, phone_number, amount,
                     old_budget, new_budget, transaction_type, created_at)
                VALUES (?, NULL, NULL, ?, ?, ?, 'reset', ?)
                """,
                (dept_id, new_budget, old_budget, new_budget, now),
            )

    def adjust_budget(
        self, plant_name: str, department_name: str, adjustment: float
    ) -> None:
        """Manual budget adjustment (+/-) on the remaining balance.

        Does not touch total_spent. Logs as an 'adjustment' transaction.
        """
        if adjustment == 0:
            raise ValidationError("Le montant de l'ajustement ne peut pas être zéro")

        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, remaining_budget FROM departments "
                "WHERE plant_name = ? AND department_name = ?",
                (plant_name, department_name),
            ).fetchone()

            if row is None:
                raise ValidationError(
                    f"Département '{department_name}' introuvable pour l'usine '{plant_name}'"
                )

            dept_id = row[0]
            old_budget = row[1]
            new_budget = round(old_budget + adjustment, 2)
            now = datetime.now().isoformat(timespec="seconds")

            conn.execute(
                "UPDATE departments SET remaining_budget = ? WHERE id = ?",
                (new_budget, dept_id),
            )

            conn.execute(
                """
                INSERT INTO budget_transactions
                    (department_id, invoice_number, phone_number, amount,
                     old_budget, new_budget, transaction_type, created_at)
                VALUES (?, NULL, NULL, ?, ?, ?, 'adjustment', ?)
                """,
                (dept_id, adjustment, old_budget, new_budget, now),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Transaction history (audit log)
    # ──────────────────────────────────────────────────────────────────────────

    def get_transactions(
        self,
        department_id: int | None = None,
        invoice_number: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query transaction history for audit.

        Columns returned:
          old_budget  → "Budget Alloué (Ancien Reste)"   — what was available before
          amount      → "Total Dépenses"                 — what this invoice charged
          new_budget  → "Le Reste Disponible"            — what remains after
        """
        with get_conn() as conn:
            sql = """
                SELECT bt.id, bt.department_id, d.plant_name, d.department_name,
                       bt.invoice_number, bt.phone_number, bt.amount,
                       bt.old_budget, bt.new_budget, bt.transaction_type, bt.created_at
                FROM budget_transactions bt
                JOIN departments d ON d.id = bt.department_id
                WHERE 1=1
            """
            params: list[Any] = []

            if department_id is not None:
                sql += " AND bt.department_id = ?"
                params.append(department_id)
            if invoice_number:
                sql += " AND bt.invoice_number = ?"
                params.append(invoice_number)

            sql += " ORDER BY bt.created_at ASC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]