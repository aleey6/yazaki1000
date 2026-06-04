import { 
  ConfigResponse, 
  PlantBudgetResponse, 
  TransactionResponse, 
  InvoiceRecord, 
  ProcessInvoiceResponse, 
  DepartmentConfig,
  ClientPlantMapping,
  DepartmentBudgetUpdate
} from './types';

const STORAGE_KEY = 'yazaki_api_base_url_v2';

export function getApiBaseUrl(): string {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) return saved;
  return 'http://localhost:8000';
}

export function setApiBaseUrl(url: string) {
  localStorage.setItem(STORAGE_KEY, url);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const base = getApiBaseUrl();
  const url = `${base}${path}`;
  
  let response;
  try {
    response = await fetch(url, options);
  } catch (netErr: any) {
    throw new Error(`Impossible de contacter le serveur à ${url}. Assurez-vous que votre serveur FastAPI est démarré et que l'URL est correcte.`);
  }

  const contentType = response.headers.get('content-type') || '';
  
  if (!response.ok) {
    let errMsg = `La requête a échoué: ${response.status} ${response.statusText}`;
    if (contentType.includes('application/json')) {
      try {
        const data = await response.json();
        if (data && data.detail) {
          if (typeof data.detail === 'string') {
            errMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errMsg = data.detail.map((err: any) => `${err.loc?.join('.') || 'Error'}: ${err.msg}`).join(', ');
          }
        }
      } catch (e) {
        // ignore
      }
    } else {
      try {
        const text = await response.text();
        if (text.trim().startsWith('<')) {
          errMsg = `Le serveur a retourné une page HTML au lieu d'une réponse d'erreur JSON (Statut: ${response.status}). Veuillez configurer l'Hôte de votre serveur FastAPI (ex: http://localhost:8000) dans la barre latérale.`;
        } else {
          errMsg = `Erreur (${response.status}): ${text.substring(0, 150)}`;
        }
      } catch (e) {
        // ignore
      }
    }
    throw new Error(errMsg);
  }
  
  if (!contentType.includes('application/json')) {
    try {
      const text = await response.text();
      if (text.trim().startsWith('<')) {
        throw new Error(
          `Erreur de configuration : L'adresse de l'API (${base || 'relative'}) a renvoyé du code HTML (index.html) au lieu des données JSON de FastAPI.\n\n` +
          `Veuillez configurer l'URL correcte de votre serveur FastAPI (par exemple : http://localhost:8000) en cliquant sur "Modifier" sous "Hôte de l'API" dans la barre latérale.`
        );
      }
      throw new Error(`Réponse non-JSON reçue de l'API : ${text.substring(0, 100)}`);
    } catch (err: any) {
      throw new Error(err.message || "Format de réponse invalide (attendu: JSON).");
    }
  }
  
  return response.json() as Promise<T>;
}

export const api = {
  // 1. Root API information
  async getRoot(): Promise<any> {
    return request<any>('/');
  },

  // 2. Health check
  async getHealth(): Promise<any> {
    return request<any>('/health');
  },

  // 3. Process invoice (PDF file upload)
  async processInvoice(file: File, useOcr = false, ocrAvailable = true): Promise<ProcessInvoiceResponse> {
    const base = getApiBaseUrl();
    const queryParams = new URLSearchParams({
      use_ocr: useOcr.toString(),
      ocr_available: ocrAvailable.toString()
    });
    
    const url = `${base}/api/invoices/process?${queryParams.toString()}`;
    const formData = new FormData();
    formData.append('file', file);

    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        body: formData
      });
    } catch (netErr: any) {
      throw new Error(`Impossible de contacter le serveur FastAPI lors de l'envoi de la facture. Assurez-vous que le serveur tourne à l'adresse correcte.`);
    }

    const contentType = response.headers.get('content-type') || '';

    if (!response.ok) {
      let errMsg = `L'extraction a échoué: ${response.status} ${response.statusText}`;
      if (contentType.includes('application/json')) {
        try {
          const errJson = await response.json();
          if (errJson && errJson.detail) {
            if (typeof errJson.detail === 'string') {
              errMsg = errJson.detail;
            } else if (Array.isArray(errJson.detail)) {
              errMsg = errJson.detail.map((err: any) => err.msg).join(', ');
            }
          }
        } catch (e) {
          // ignore
        }
      } else {
        try {
          const text = await response.text();
          if (text.trim().startsWith('<')) {
            errMsg = `Le serveur a renvoyé du HTML au lieu d'une réponse JSON (Statut: ${response.status}). Veuillez vérifier la configuration de l'Hôte de l'API FastAPI dans la barre latérale.`;
          } else {
            errMsg = `Erreur (${response.status}): ${text.substring(0, 150)}`;
          }
        } catch (e) {
          // ignore
        }
      }
      throw new Error(errMsg);
    }

    if (!contentType.includes('application/json')) {
      try {
        const text = await response.text();
        if (text.trim().startsWith('<')) {
          throw new Error(
            `Erreur de configuration : Le endpoint de traitement s'est résolu en code HTML (page d'accueil/Vite fallback) au lieu d'une réponse de l'API.\n\n` +
            `Veuillez configurer l'URL correcte de votre serveur FastAPI (ex: http://localhost:8000) dans l'Hôte de l'API répertorié dans la barre latérale.`
          );
        }
        throw new Error(`Réponse non-JSON reçue de l'imputation : ${text.substring(0, 100)}`);
      } catch (err: any) {
        throw new Error(err.message || "Format de réponse invalide.");
      }
    }

    return response.json() as Promise<ProcessInvoiceResponse>;
  },

  // 4. Process multiple batch invoices at once
// 4. Process multiple batch invoices at once
  async processInvoiceBatch(files: File[], useOcr = false): Promise<ProcessInvoiceBatchResponse> {
    const base = getApiBaseUrl();
    const queryParams = new URLSearchParams({
      use_ocr: useOcr.toString(),
      ocr_available: 'true'
    });
    
    const url = `/api/invoices/process-batch?${queryParams.toString()}`;
    const formData = new FormData();
    
    // Append each file inside the multipart sequence form
    files.forEach(file => {
      formData.append('files', file);
    });

    // We pass the formData object as the body parameter of the options payload
    return request<ProcessInvoiceBatchResponse>(url, {
      method: 'POST',
      body: formData
      // Note: Do NOT manually set 'Content-Type' header here; 
      // the browser needs to automatically append the boundary delimiter string.
    });
  },
  // 5. Export invoice to Excel (returns raw Blob object or trigger direct download)
  getExportUrl(invoiceId: number): string {
    const base = getApiBaseUrl();
    return `${base}/api/invoices/export/${invoiceId}`;
  },

  // 6. Get all plants
  async getPlants(): Promise<string[]> {
    return request<string[]>('/api/plants');
  },

  // 7. Get Plant budget details
  async getPlantBudget(plantName: string): Promise<PlantBudgetResponse> {
    const encoded = encodeURIComponent(plantName);
    return request<PlantBudgetResponse>(`/api/plants/${encoded}/budget`);
  },

  // 8. Reset Plant department budget
  async resetBudget(data: DepartmentBudgetUpdate): Promise<any> {
    return request<any>('/api/budget/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
  },

  // 9. Adjust Plant department budget
  async adjustBudget(data: DepartmentBudgetUpdate): Promise<any> {
    return request<any>('/api/budget/adjust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
  },

  // 10. Get Config file representation
  async getConfig(): Promise<ConfigResponse> {
    return request<ConfigResponse>('/api/config');
  },

  // 11. Update the whole configuration
  async updateConfig(config: any): Promise<any> {
    return request<any>('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
  },

  // 12. Add client to plant mapping
  async addClientMapping(mapping: ClientPlantMapping): Promise<any> {
    return request<any>('/api/config/client-mapping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mapping)
    });
  },

  // 13. Add department
  async addDepartment(plantName: string, dept: DepartmentConfig): Promise<any> {
    const encoded = encodeURIComponent(plantName);
    return request<any>(`/api/config/plant-department?plant_name=${encoded}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dept)
    });
  },

  // 14. Get saved Invoices
  async getInvoices(params?: { limit?: number; offset?: number; plant?: string }): Promise<InvoiceRecord[]> {
    const q = new URLSearchParams();
    if (params?.limit !== undefined) q.append('limit', params.limit.toString());
    if (params?.offset !== undefined) q.append('offset', params.offset.toString());
    if (params?.plant) q.append('plant', params.plant);

    const queryString = q.toString() ? `?${q.toString()}` : '';
    // Let's handle return type safely
    const data = await request<any>(`/api/invoices${queryString}`);
    // If backend returns a dictionary container e.g. { invoices: [...] } or direct list
    if (Array.isArray(data)) {
      return data as InvoiceRecord[];
    } else if (data && Array.isArray(data.invoices)) {
      return data.invoices as InvoiceRecord[];
    } else if (data && typeof data === 'object') {
      // Find any array property inside
      const potentialArray = Object.values(data).find(val => Array.isArray(val));
      if (potentialArray) return potentialArray as InvoiceRecord[];
    }
    return [];
  },

  // 15. Clear all saved invoices
  async clearAllInvoices(): Promise<any> {
    return request<any>('/api/invoices', {
      method: 'DELETE'
    });
  },

  // 16. Get transactions audit history
  async getTransactions(params?: { 
    limit?: number; 
    invoice_number?: string; 
    plant_name?: string; 
    department_name?: string;
  }): Promise<TransactionResponse[]> {
    const q = new URLSearchParams();
    if (params?.limit !== undefined) q.append('limit', params.limit.toString());
    if (params?.invoice_number) q.append('invoice_number', params.invoice_number);
    if (params?.plant_name) q.append('plant_name', params.plant_name);
    if (params?.department_name) q.append('department_name', params.department_name);

    const queryString = q.toString() ? `?${q.toString()}` : '';
    return request<TransactionResponse[]>(`/api/transactions${queryString}`);
  },

  // 17. Get plant summaries report
  async getPlantSummaryReport(): Promise<any> {
    return request<any>('/api/reports/plant-summary');
  }
};
