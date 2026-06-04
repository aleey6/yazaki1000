"""Data transfer objects and exceptions for the budget tracking system.

Design principle
----------------
Plant budget is NEVER stored as a fixed value.
It is always computed as SUM(department.initial_budget) for that plant.
Expenses are always tracked at the DEPARTMENT level, never at the plant level.

Invoice processing flow
-----------------------
1. PDF page → client_number  →  identifies the Plant
2. PDF page → phone_number   →  identifies the Department (via phone_numbers list)
3. PDF page → Total Contrat  →  deducted from that Department's remaining_budget
4. Plant remaining = SUM(dept.remaining_budget) for all its departments
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════════════


class BudgetProcessingError(Exception):
    """Base exception for budget processing failures."""

    def __init__(self, message: str, error_code: str = "BUDGET_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class DuplicateInvoiceError(BudgetProcessingError):
    """Raised when an invoice has already been processed."""

    def __init__(self, invoice_number: str):
        super().__init__(
            message=f"Facture {invoice_number} déjà traitée",
            error_code="DUPLICATE_INVOICE",
        )
        self.invoice_number = invoice_number


class ValidationError(BudgetProcessingError):
    """Raised for invalid input data."""

    def __init__(self, message: str):
        super().__init__(message=message, error_code="VALIDATION_ERROR")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Transfer Objects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ProcessingResult:
    """Result of invoice processing."""

    success: bool
    invoice_number: str
    contracts_processed: int
    total_deducted: float
    departments_affected: dict[str, float] = field(default_factory=dict)
    unassigned_contracts: list[dict] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class DepartmentStatus:
    """Department budget status for dashboard.

    All monetary values are tracked at the department level.
    The plant-level budget is the sum of all its departments.
    """

    id: int
    plant_name: str
    department_name: str
    cost_center_id: str
    initial_budget: float      # Budget set at start of period (from config)
    remaining_budget: float    # = initial_budget - total_spent (cumulative across invoices)
    total_spent: float         # Sum of all Total Contrat deductions for this dept
    budget_status: str         # "healthy" | "critical" | "over-budget"


@dataclass
class PlantSummary:
    """Aggregated plant-level budget summary.

    These values are ALWAYS derived by summing department rows in the DB.
    There is no plant-level budget stored anywhere — it is always computed.

    Formula:
        total_initial_budget  = SUM(dept.initial_budget)
        total_spent           = SUM(dept.total_spent)
        total_remaining       = SUM(dept.remaining_budget)
    """

    plant_name: str
    total_initial_budget: float   # SUM of all dept initial_budgets
    total_spent: float            # SUM of all dept total_spent (cumulative)
    total_remaining: float        # SUM of all dept remaining_budgets
    department_count: int

    @property
    def utilization_pct(self) -> float:
        """Percentage of plant budget consumed (0–100+)."""
        if self.total_initial_budget <= 0:
            return 0.0
        return round(self.total_spent / self.total_initial_budget * 100, 2)