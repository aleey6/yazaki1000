/**
 * Types mapping to the YAZAKI IAM FastAPI OpenAPI specs.
 */

export interface DepartmentBudget {
  department_name: string;
  cost_center_id: string;
  initial_budget: number;
  total_spent: number;
  remaining_budget: number;
  budget_status: 'ok' | 'critical' | 'over-budget' | string;
  percentage_used: number;
}

export interface PlantBudgetResponse {
  plant_name: string;
  total_budget: number;
  total_spent: number;
  total_remaining: number;
  usage_percentage: number;
  departments: DepartmentBudget[];
}

export interface DepartmentConfig {
  name: string;
  cost_center_id: string;
  budget: number;
  phone_numbers: string[];
}

export interface ConfigResponse {
  client_plant_mapping: Record<string, string>;
  plants: Record<string, {
    departments: Record<string, DepartmentConfig>;
  }>;
}

export interface UnassignedContract {
  phone_number?: string;
  contract_type?: string;
  total_contrat?: number;
  period_start?: string;
  period_end?: string;
  [key: string]: any;
}

export interface ProcessInvoiceResponse {
  success: boolean;
  message: string;
  plant: string | null;
  contracts_processed?: number;
  total_deducted?: number;
  departments_affected?: string[];
  unassigned_contracts?: UnassignedContract[];
  duplicate?: boolean;
  validation_error?: string | null;
  budget_error?: string | null;
}

export interface TransactionResponse {
  id: number;
  created_at: string;
  plant_name: string;
  department_name: string;
  invoice_number: string | null;
  transaction_type: string;
  old_budget: number;
  amount: number;
  new_budget: number;
}

export interface InvoiceRecord {
  id: number;
  saved_at: string;
  plant: string;
  department: string;
  invoice_number: string;
  invoice_date: string;
  total: number;
  montant_ht?: number;
  montant_ttc?: number;
  contracts_count?: number;
  source_file?: string;
}

export interface ClientPlantMapping {
  client_number: string;
  plant_name: string;
}

export interface DepartmentBudgetUpdate {
  plant_name: string;
  department_name: string;
  new_budget?: number | null;
  adjustment_amount?: number | null;
}


export interface BatchFilePayload {
  filename: string;
  file_contents: string; // Base64 encoded string
}

export interface ProcessInvoiceBatchResponse {
  success: boolean;
  summary: string[];
  files: BatchFilePayload[];
}