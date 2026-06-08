import React, { useState, useEffect, useRef } from 'react';
import { 
  BarChart3, 
  FileSearch, 
  Sliders, 
  BookOpen, 
  History, 
  UploadCloud, 
  CheckCircle, 
  AlertTriangle, 
  Download, 
  Trash2, 
  Plus, 
  X, 
  ChevronDown, 
  ChevronUp, 
  RefreshCw, 
  Info,
  Calendar,
  Layers,
  Search,
  Check,
  Building,
  DollarSign,
  PhoneCall,
  Activity,
  ArrowRightLeft,
  FileText
} from 'lucide-react';
import { api } from './api';
import { 
  ConfigResponse, 
  PlantBudgetResponse, 
  InvoiceRecord, 
  TransactionResponse, 
  DepartmentBudget, 
  ProcessInvoiceResponse,
  DepartmentConfig,
  ClientPlantMapping
} from './types';
import NavigationSidebar from './components/NavigationSidebar';
import TopNavbar from './components/TopNavbar';

// Recharts for data visualization
import { 
  ResponsiveContainer, 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  Legend, 
  PieChart, 
  Pie, 
  Cell 
} from 'recharts';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [apiBaseUrl, setApiBaseUrl] = useState(() => {
    return localStorage.getItem('yazaki_api_base_url_v2') || '';
  });

  // State loaded from FastAPI
  const [plants, setPlants] = useState<string[]>([]);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [transactions, setTransactions] = useState<TransactionResponse[]>([]);
  
  // Budget status of all loaded plants
  const [plantDetailBudgets, setPlantDetailBudgets] = useState<Record<string, PlantBudgetResponse>>({});

  // Loading & error state
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Tab - Analyze States
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [useOcr, setUseOcr] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<ProcessInvoiceResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [batchFiles, setBatchFiles] = useState<{ filename: string; file_contents: string }[]>([]);

  // Tab - Config Editor States
  const [newClientNum, setNewClientNum] = useState('');
  const [newClientPlant, setNewClientPlant] = useState('');
  const [editingConfigJson, setEditingConfigJson] = useState('');
  const [isJsonView, setIsJsonView] = useState(false);
  const [selectedConfigPlant, setSelectedConfigPlant] = useState('');
  const [newDeptName, setNewDeptName] = useState('');
  const [newDeptCostCenter, setNewDeptCostCenter] = useState('');
  const [newDeptBudget, setNewDeptBudget] = useState(25000);
  const [selectedPhoneDept, setSelectedPhoneDept] = useState('');
  const [phoneText, setPhoneText] = useState('');

  // Tab - Budget Adjustment States
  const [adjPlant, setAdjPlant] = useState('');
  const [adjDept, setAdjDept] = useState('');
  const [resetAmount, setResetAmount] = useState<number>(25000);
  const [adjustAmount, setAdjustAmount] = useState<number>(0);

  // Tab - Reports States
  const [reportStartDate, setReportStartDate] = useState(() => {
    const d = new Date();
    d.setDate(1); // First day of current month
    return d.toISOString().substring(0, 10);
  });
  const [reportEndDate, setReportEndDate] = useState(() => {
    return new Date().toISOString().substring(0, 10);
  });
  const [reportPlant, setReportPlant] = useState('');

  // Tab - History States
  const [txInvoiceFilter, setTxInvoiceFilter] = useState('');
  const [txLimit, setTxLimit] = useState(100);

  // UI accordion state for plant breakdowns on dashboard
  const [expandedPlant, setExpandedPlant] = useState<string | null>(null);

  // File Input Ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Helper to update local API base URL settings
  const handleSetApiBaseUrl = (newUrl: string) => {
    setApiBaseUrl(newUrl);
    localStorage.setItem('yazaki_api_base_url_v2', newUrl);
    showNotice('Hôte API mis à jour avec succès.', 'success');
  };

  // Toast notices displayers
  const showNotice = (msg: string, type: 'success' | 'err') => {
    if (type === 'success') {
      setSuccessMsg(msg);
      setTimeout(() => setSuccessMsg(null), 6000);
    } else {
      setErrorMsg(msg);
      setTimeout(() => setErrorMsg(null), 8000);
    }
  };

  // Primary bootstrapper fetching all live backend details
// Primary bootstrapper fetching all live backend details
const fetchAllData = async () => {
  setLoading(true);
  try {
    // 1. Fetch plants
    const plantList = await api.getPlants();
    setPlants(plantList);

    if (plantList.length > 0) {
      if (!selectedConfigPlant) setSelectedConfigPlant(plantList[0]);
      if (!adjPlant) setAdjPlant(plantList[0]);
      if (!reportPlant) setReportPlant(plantList[0]);
      
      // Fetch budget details for each plant
      const budgetsMap: Record<string, PlantBudgetResponse> = {};
      for (const p of plantList) {
        try {
          const data = await api.getPlantBudget(p);
          budgetsMap[p] = data;
        } catch (budgetErr) {
          console.error(`Error loading budget for plant ${p}:`, budgetErr);
        }
      }
      setPlantDetailBudgets(budgetsMap);
    }

    // 2. Fetch full config
    const appConfig = await api.getConfig();
    setConfig(appConfig);
    setEditingConfigJson(JSON.stringify(appConfig, null, 2));

    // 3. Fetch history
    const savedInvoices = await api.getInvoices({ limit: 100 });
    setInvoices(savedInvoices);

    // ✅ AJOUT : Mettre à jour les dates du filtre avec la dernière facture
    if (savedInvoices.length > 0) {
      const lastInvoice = savedInvoices[0];
      
      // Utiliser la période de la facture si disponible
      let startDate = lastInvoice.period_start;
      let endDate = lastInvoice.period_end;
      
      // Si pas de période, essayer de la calculer depuis la date de facture
      if (!startDate && lastInvoice.invoice_date) {
        const parts = lastInvoice.invoice_date.split('/');
        if (parts.length === 3) {
          const day = parseInt(parts[0]);
          const month = parseInt(parts[1]);
          const year = parseInt(parts[2]);
          
          // La période est le mois précédent la date de facture
          let periodMonth = month - 1;
          let periodYear = year;
          if (periodMonth === 0) {
            periodMonth = 12;
            periodYear = year - 1;
          }
          
          // Premier jour du mois
          startDate = `01/${periodMonth.toString().padStart(2, '0')}/${periodYear}`;
          
          // Dernier jour du mois
          const lastDay = new Date(periodYear, periodMonth, 0).getDate();
          endDate = `${lastDay.toString().padStart(2, '0')}/${periodMonth.toString().padStart(2, '0')}/${periodYear}`;
        }
      }
      
      // Appliquer les dates au filtre (convertir DD/MM/YYYY → YYYY-MM-DD pour input date)
      if (startDate && endDate) {
        const startParts = startDate.split('/');
        const endParts = endDate.split('/');
        if (startParts.length === 3 && endParts.length === 3) {
          setReportStartDate(`${startParts[2]}-${startParts[1]}-${startParts[0]}`);
          setReportEndDate(`${endParts[2]}-${endParts[1]}-${endParts[0]}`);
          console.log(`📅 Filtre automatique: ${startDate} → ${endDate}`);
        }
      }
    }

    // 4. Fetch transactions log
    const historyTransactions = await api.getTransactions({ limit: txLimit });
    setTransactions(historyTransactions);

  } catch (err: any) {
    console.error(err);
    showNotice(
      `Connexion au serveur FastAPI impossible: ${err.message || err}. Assurez-vous que le serveur est démarré et renseignez l'Hôte correct dans la barre latérale.`, 
      'err'
    );
  } finally {
    setLoading(false);
  }
};

  useEffect(() => {
    fetchAllData();
  }, [apiBaseUrl]);

  // Handle transaction limits
  useEffect(() => {
    const reloadTx = async () => {
      try {
        const historyTransactions = await api.getTransactions({ 
          limit: txLimit,
          invoice_number: txInvoiceFilter.trim() || undefined
        });
        setTransactions(historyTransactions);
      } catch (e) {
        // ignore
      }
    };
    reloadTx();
  }, [txLimit, txInvoiceFilter]);

  // Form helpers to handle mapping additions
  const handleAddMappingSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newClientNum || !newClientPlant) {
      showNotice("Veuillez remplir le N° Client et l'Usine.", 'err');
      return;
    }
    try {
      setLoading(true);
      await api.addClientMapping({
        client_number: newClientNum.trim(),
        plant_name: newClientPlant.trim()
      });
      showNotice(`Mapping client ${newClientNum} -> ${newClientPlant} ajouté avec succès.`, 'success');
      setNewClientNum('');
      setNewClientPlant('');
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Erreur d'ajout du mapping.", 'err');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteMapping = async (clientNumToDelete: string) => {
    if (!config) return;
    try {
      setLoading(true);
      const updatedMapping = { ...config.client_plant_mapping };
      delete updatedMapping[clientNumToDelete];
      
      const newConfig = {
        ...config,
        client_plant_mapping: updatedMapping
      };
      
      await api.updateConfig(newConfig);
      showNotice(`Mapping pour le client ${clientNumToDelete} a été supprimé.`, 'success');
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Échec de suppression du mapping.", 'err');
    } finally {
      setLoading(false);
    }
  };

  // Configure department form
  const handleAddDepartmentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedConfigPlant) {
      showNotice("Veuillez sélectionner une Usine.", 'err');
      return;
    }
    if (!newDeptName || !newDeptCostCenter) {
      showNotice("Veuillez remplir le nom et le code analytique (Cost Center ID).", 'err');
      return;
    }
    try {
      setLoading(true);
      const deptConf: DepartmentConfig = {
        name: newDeptName.trim(),
        cost_center_id: newDeptCostCenter.trim(),
        budget: Number(newDeptBudget),
        phone_numbers: []
      };
      await api.addDepartment(selectedConfigPlant, deptConf);
      showNotice(`Département ${newDeptName} ajouté à l'usine ${selectedConfigPlant}.`, 'success');
      setNewDeptName('');
      setNewDeptCostCenter('');
      setNewDeptBudget(25000);
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Erreur création département.", 'err');
    } finally {
      setLoading(false);
    }
  };

  // Select phone numbers config helper
  useEffect(() => {
    if (config && selectedConfigPlant && selectedPhoneDept) {
      const pInfo = config.plants[selectedConfigPlant]?.departments[selectedPhoneDept];
      if (pInfo) {
        setPhoneText(pInfo.phone_numbers?.join('\n') || '');
      } else {
        setPhoneText('');
      }
    } else {
      setPhoneText('');
    }
  }, [selectedConfigPlant, selectedPhoneDept, config]);

  const handleSavePhones = async () => {
    if (!config || !selectedConfigPlant || !selectedPhoneDept) {
      showNotice("Veuillez sélectionner l'usine et le département.", 'err');
      return;
    }
    try {
      setLoading(true);
      const lines = phoneText
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      const dConf = config.plants[selectedConfigPlant].departments[selectedPhoneDept];
      const updatedDept: DepartmentConfig = {
        ...dConf,
        phone_numbers: lines
      };

      // Put into config state
      const newConfigObj = JSON.parse(JSON.stringify(config)) as ConfigResponse;
      newConfigObj.plants[selectedConfigPlant].departments[selectedPhoneDept] = updatedDept;

      await api.updateConfig(newConfigObj);
      showNotice(`Affectations des numéros sauvegardées pour ${selectedPhoneDept}.`, 'success');
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Erreur d'enregistrement des numéros d'appel.", 'err');
    } finally {
      setLoading(false);
    }
  };

  // Reset & Adjust Budgets Form handlers
  const handleResetBudgetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adjPlant || !adjDept) {
      showNotice("Veuillez séléctionner l'usine et le département à modifier.", 'err');
      return;
    }
    try {
      setLoading(true);
      await api.resetBudget({
        plant_name: adjPlant,
        department_name: adjDept,
        new_budget: resetAmount
      });
      showNotice(`Budget de ${adjDept} réinitialisé avec succès à ${resetAmount} MAD!`, 'success');
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Échec de réinitialisation budgétaire.", 'err');
    } finally {
      setLoading(false);
    }
  };

  const handleAdjustBudgetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adjPlant || !adjDept) {
      showNotice("Veuillez séléctionner l'usine et le département à ajuster.", 'err');
      return;
    }
    try {
      setLoading(true);
      await api.adjustBudget({
        plant_name: adjPlant,
        department_name: adjDept,
        adjustment_amount: adjustAmount
      });
      showNotice(`Ajustement de ${adjustAmount} MAD appliqué avec succès sur le département ${adjDept}`, 'success');
      setAdjustAmount(0);
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Échec d'application d'ajustement.", 'err');
    } finally {
      setLoading(false);
    }
  };

  // Full Raw JSON Config save
  const handleSaveRawJson = async () => {
    try {
      setLoading(true);
      const parsed = JSON.parse(editingConfigJson);
      await api.updateConfig(parsed);
      showNotice("Fichier de configuration global mis à jour !", "success");
      setIsJsonView(false);
      await fetchAllData();
    } catch (err: any) {
      showNotice(`JSON invalide: ${err.message}`, "err");
    } finally {
      setLoading(false);
    }
  };

  // Clear invoices handler
  const handleClearInvoices = async () => {
    if (!window.confirm("Êtes-vous sûr de vouloir supprimer définitivement l'historique complet de toutes les factures ? Cette action videra les de dépenses de vos budgets.")) {
      return;
    }
    try {
      setLoading(true);
      await api.clearAllInvoices();
      showNotice("Base de données des factures réinitialisée avec succès !", "success");
      setAnalysisResult(null);
      await fetchAllData();
    } catch (err: any) {
      showNotice(err.message || "Erreur de purge.", "err");
    } finally {
      setLoading(false);
    }
  };

  // File drag states handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files) {
      // .toLowerCase() allows both '.pdf' and '.PDF' extensions
      const incoming = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      if (incoming.length > 0) {
        setSelectedFiles(prev => [...prev, ...incoming]);
      } else {
        showNotice("Seuls les fichiers PDF d'extraction de factures IAM sont acceptés.", "err");
      }
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      // .toLowerCase() allows both '.pdf' and '.PDF' extensions
      const incoming = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      if (incoming.length > 0) {
        setSelectedFiles(prev => [...prev, ...incoming]);
      } else {
        showNotice("Seuls les fichiers PDF sont acceptés.", "err");
      }
    }
  };

  // Execute extraction endpoint
  const handleAnalyzeInvoiceSubmit = async () => {
    if (selectedFiles.length === 0) {
      showNotice("Veuillez d'abord sélectionner au moins un fichier PDF.", 'err');
      return;
    }
    setIsAnalyzing(true);
    setBatchFiles([]); // Clear previous runs
    try {
      const response = await api.processInvoiceBatch(selectedFiles, useOcr);
      
      // Save the Base64 files to state instead of downloading them immediately
      setBatchFiles(response.files);

      // Create a comprehensive analysis result object for the header summary banner
      setAnalysisResult({
        success: true,
        message: `Traitement par lot terminé avec succès !`,
        contracts_processed: response.files.length, // Tracks number of documents processed
        departments_affected: [],
        unassigned_contracts: [],
        duplicate: false
      });

      showNotice(`Imputation réussie. ${response.files.length} rapports individuels sont prêts.`, "success");
      setSelectedFiles([]); 
      await fetchAllData(); 
      
    } catch (err: any) {
      console.error(err);
      showNotice(`Échec lors du traitement groupé: ${err.message || err}`, "err");
    } finally {
      setIsAnalyzing(false);
    }
  };


  const downloadBatchFile = (file_contents: string, filename: string) => {
    const byteCharacters = atob(file_contents);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const excelBlob = new Blob([byteArray], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    const blobUrl = window.URL.createObjectURL(excelBlob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  };

  // CSV Generator on client-side for tab reports
  const exportReportToCsv = () => {
    if (!reportPlant || !plantDetailBudgets[reportPlant]) return;
    const items = plantDetailBudgets[reportPlant].departments;
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Departement,Cost Center ID,Budget Initial (MAD),Total Depense (MAD),Reste Disponible (MAD),Utilisation (%)\n";
    
    items.forEach(d => {
      csvContent += `"${d.department_name}","${d.cost_center_id}",${d.initial_budget},${d.total_spent},${d.remaining_budget},${d.percentage_used.toFixed(1)}%\n`;
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `Yazaki_Rapport_${reportPlant.replace(/\s+/g, "_")}_${new Date().toISOString().substring(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Grouped Calculations for Dashboard KPI Blocks
  const computeGlobalKpis = () => {
    let totalBudget = 0;
    let totalSpent = 0;
    let totalRemaining = 0;

    (Object.values(plantDetailBudgets) as PlantBudgetResponse[]).forEach(detail => {
      totalBudget += detail.total_budget;
      totalSpent += detail.total_spent;
      totalRemaining += detail.total_remaining;
    });

    const usagePct = totalBudget > 0 ? (totalSpent / totalBudget) * 100 : 0;

    return {
      totalBudget,
      totalSpent,
      totalRemaining,
      usagePct
    };
  };

  const globalKpis = computeGlobalKpis();

  // Color mappings for budget status styling
  const getStatusColor = (status: string, pct: number) => {
    if (status === 'over-budget' || pct >= 100) return { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', textBadge: '🔴 Dépassement' };
    if (status === 'critical' || pct > 85) return { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', textBadge: '🟠 Critique' };
    if (pct > 50) return { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700', textBadge: '🟡 Attention' };
    return { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', textBadge: '🟢 Budget OK' };
  };

  // Prepare custom formatting for display
  const fmtMoney = (amount: number | undefined) => {
    if (amount === undefined) return '0,00 MAD';
    return new Intl.NumberFormat('fr-MA', { style: 'currency', currency: 'MAD' }).format(amount);
  };

  const fmtDate = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString('fr-FR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (e) {
      return isoString;
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 text-slate-800 font-sans overflow-hidden">
      
      {/* 1. BRANDED SIDEBAR NAVIGATION WITH FASTAPI STATUS DETECTOR */}
      <NavigationSidebar 
        activeTab={activeTab} 
        setActiveTab={(tab) => {
          setActiveTab(tab);
          // Auto fill states
          if (config && plants.length > 0) {
            if (!selectedPhoneDept && config.plants[selectedConfigPlant]) {
              setSelectedPhoneDept(Object.keys(config.plants[selectedConfigPlant].departments)[0] || '');
            }
          }
        }}
        apiBaseUrl={apiBaseUrl}
        setApiBaseUrl={handleSetApiBaseUrl}
      />

      {/* 2. MAIN APPLICATION CONTENT VIEW */}
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto h-screen relative">
        <TopNavbar activeTab={activeTab} loading={loading} onRefreshAll={fetchAllData} />
        {/* FEEDBACK BANNER ALERTS */}
        {errorMsg && (
          <div className="mx-8 mt-6 p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm flex items-start gap-3 shadow-sm animate-fadeIn">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="font-semibold">Une erreur est survenue</h4>
              <p className="text-red-700/90 mt-0.5">{errorMsg}</p>
            </div>
            <button onClick={() => setErrorMsg(null)} className="text-red-400 hover:text-red-700">
              <X className="h-5 w-5" />
            </button>
          </div>
        )}

        {successMsg && (
          <div className="mx-8 mt-6 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-start gap-3 shadow-sm animate-fadeIn">
            <CheckCircle className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
            <p className="flex-1 font-medium">{successMsg}</p>
            <button onClick={() => setSuccessMsg(null)} className="text-emerald-400 hover:text-emerald-700">
              <X className="h-5 w-5" />
            </button>
          </div>
        )}

        <div className="p-8 flex-1">
          
          {/* ==================== TAB 1 STATE: DASHBOARD ==================== */}
          {activeTab === 'dashboard' && (
            <div className="space-y-8">
              {plants.length === 0 ? (
                <div className="bg-white border border-slate-200 rounded-2xl p-12 text-center max-w-2xl mx-auto shadow-sm my-12">
                  <div className="h-16 w-16 rounded-full bg-rose-50 flex items-center justify-center text-rose-500 mx-auto mb-4">
                    <Building className="h-8 w-8" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-900">Aucune usine configurée sur FastAPI</h3>
                  <p className="text-slate-500 text-sm mt-2 max-w-md mx-auto">
                    Le serveur de base n'a pas encore de configuration budgétaire active. Accédez dès maintenant à la configuration pour configurer vos usines, départements et budgets.
                  </p>
                  <button 
                    onClick={() => setActiveTab('config')}
                    className="mt-6 inline-flex items-center gap-2 bg-rose-600 hover:bg-rose-500 text-white font-semibold px-5 py-2.5 rounded-xl transition-all shadow-sm focus:outline-none cursor-pointer"
                  >
                    <Sliders className="h-4 w-4" />
                    Configurer les Usines
                  </button>
                </div>
              ) : (
                <>
                  {/* Row 1: KPI Metrics Panels */}
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs relative overflow-hidden">
                      <div className="absolute right-0 top-0 h-24 w-24 bg-rose-500/5 rounded-full translate-x-12 -translate-y-12" />
                      <span className="text-xs font-mono font-bold text-slate-400 uppercase tracking-wide">💰 Budget Consolidé</span>
                      <h3 className="text-2xl font-black text-slate-900 mt-2 font-mono">
                        {fmtMoney(globalKpis.totalBudget)}
                      </h3>
                      <p className="text-xs text-slate-400 mt-1">Totalité des enveloppes allouées</p>
                    </div>

                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs relative overflow-hidden">
                      <div className="absolute right-0 top-0 h-24 w-24 bg-amber-500/5 rounded-full translate-x-12 -translate-y-12" />
                      <span className="text-xs font-mono font-bold text-slate-400 uppercase tracking-wide">💸 Dépenses Engagées</span>
                      <h3 className="text-2xl font-black text-rose-600 mt-2 font-mono">
                        {fmtMoney(globalKpis.totalSpent)}
                      </h3>
                      <p className="text-xs text-rose-600/70 mt-1 font-semibold flex items-center gap-1">
                        Consommé sur factures IAM
                      </p>
                    </div>

                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs relative overflow-hidden">
                      <div className="absolute right-0 top-0 h-24 w-24 bg-emerald-500/5 rounded-full translate-x-12 -translate-y-12" />
                      <span className="text-xs font-mono font-bold text-slate-400 uppercase tracking-wide">🟢 Reste Disponible</span>
                      <h3 className="text-2xl font-black text-emerald-600 mt-2 font-mono">
                        {fmtMoney(globalKpis.totalRemaining)}
                      </h3>
                      <p className="text-xs text-slate-400 mt-1">Fonds non déduits restants</p>
                    </div>

                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs relative overflow-hidden">
                      <div className="absolute right-0 top-0 h-24 w-24 bg-blue-500/5 rounded-full translate-x-12 -translate-y-12" />
                      <span className="text-xs font-mono font-bold text-slate-400 uppercase tracking-wide">📈 Taux d'Utilisation Consolidé</span>
                      <h3 className="text-2xl font-black text-slate-800 mt-2 font-mono">
                        {globalKpis.usagePct.toFixed(1)}%
                      </h3>
                      <div className="w-full bg-slate-100 rounded-full h-1.5 mt-2.5 overflow-hidden">
                        <div 
                          className="bg-rose-600 h-1.5 rounded-full" 
                          style={{ width: `${Math.min(100, globalKpis.usagePct)}%` }} 
                        />
                      </div>
                    </div>
                  </div>

                  {/* Row 2: Analytical Visual Recharts */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    {/* Visual 1: Grouped Budget Comparison */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                      <h3 className="text-md font-bold text-slate-900 mb-1">🏆 Budget vs Dépenses par Usine</h3>
                      <p className="text-xs text-slate-400 mb-6">Comparatif global de consommation budgétaire consolidé</p>

                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={plants.map(p => ({
                              name: p.replace('YAZAKI ', ''),
                              'Budget Alloué': plantDetailBudgets[p]?.total_budget || 0,
                              'Dépenses Réelles': plantDetailBudgets[p]?.total_spent || 0
                            }))}
                            margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                            <XAxis dataKey="name" stroke="#64748b" fontSize={12} tickLine={false} />
                            <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v) => `${v/1000}k`} tickLine={false} />
                            <Tooltip 
                              formatter={(v: any) => [`${fmtMoney(Number(v))}`, '']}
                              contentStyle={{ background: '#0f172a', borderRadius: '12px', border: 'none', color: '#f8fafc' }}
                            />
                            <Legend iconType="circle" wrapperStyle={{ paddingTop: '15px', fontSize: '12px' }} />
                            <Bar dataKey="Budget Alloué" fill="#3b82f6" radius={[4, 4, 0, 0]} barSize={24} />
                            <Bar dataKey="Dépenses Réelles" fill="#f43f5e" radius={[4, 4, 0, 0]} barSize={24} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    {/* Visual 2: Top Departments breakdown */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                      <h3 className="text-md font-bold text-slate-900 mb-1">📊 Top Départements par Dépenses Consommées</h3>
                      <p className="text-xs text-slate-400 mb-6">Classement des 8 départements les plus coûteux</p>

                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            layout="vertical"
                            data={(Object.values(plantDetailBudgets) as PlantBudgetResponse[])
                              .flatMap(detail => detail.departments.map(d => ({
                                name: `${d.department_name.split(' (')[0]} [${detail.plant_name.replace('YAZAKI ', '')}]`,
                                'Consommé': d.total_spent
                              })))
                              .sort((a, b) => b['Consommé'] - a['Consommé'])
                              .slice(0, 8)
                            }
                            margin={{ top: 10, right: 10, left: 40, bottom: 0 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                            <XAxis type="number" stroke="#64748b" fontSize={11} tickFormatter={(v) => `${v}`} tickLine={false} />
                            <YAxis type="category" dataKey="name" stroke="#64748b" fontSize={11} width={130} tickLine={false} />
                            <Tooltip 
                              formatter={(v: any) => [`${fmtMoney(Number(v))}`, 'Dépenses']}
                              contentStyle={{ background: '#0f172a', borderRadius: '12px', border: 'none', color: '#f8fafc' }}
                            />
                            <Bar dataKey="Consommé" fill="#e11d48" radius={[0, 4, 4, 0]} barSize={14} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>

                  {/* Row 3: Accordions detailing plants budget breakdowns */}
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-bold text-slate-900 tracking-tight">🏭 Détail Général par Usine</h3>
                      <span className="text-xs text-slate-500 font-medium">Cliquez sur une usine pour ouvrir ou masquer son relevé</span>
                    </div>

                    <div className="space-y-3">
                      {plants.map((plantName) => {
                        const detail = plantDetailBudgets[plantName];
                        if (!detail) return null;

                        const isExpanded = expandedPlant === plantName;

                        return (
                          <div 
                            key={plantName} 
                            className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm"
                          >
                            {/* Accordion header block */}
                            <button
                              onClick={() => setExpandedPlant(isExpanded ? null : plantName)}
                              className="w-full flex items-center justify-between p-6 hover:bg-slate-50/50 transition-colors text-left outline-none cursor-pointer"
                            >
                              <div className="flex items-center gap-4">
                                <div className="h-10 w-10 rounded-xl bg-slate-950 text-white flex items-center justify-center font-bold">
                                  {plantName.substring(7, 9) || 'YZ'}
                                </div>
                                <div>
                                  <h4 className="font-bold text-slate-900 text-md">{plantName}</h4>
                                  <span className="text-xs font-mono font-bold text-slate-400">
                                    {detail.departments.length} Dépts Configurés
                                  </span>
                                </div>
                              </div>

                              <div className="flex items-center gap-8">
                                <div className="hidden md:flex items-center gap-6 text-sm text-right">
                                  <div>
                                    <span className="text-[10px] text-slate-400 uppercase font-mono tracking-wider">BUDGET TOTAL</span>
                                    <p className="font-mono font-bold text-slate-800">{fmtMoney(detail.total_budget)}</p>
                                  </div>
                                  <div>
                                    <span className="text-[10px] text-slate-400 uppercase font-mono tracking-wider">CONSO (MAD)</span>
                                    <p className="font-mono font-bold text-rose-600">{fmtMoney(detail.total_spent)}</p>
                                  </div>
                                  <div>
                                    <span className="text-[10px] text-slate-400 uppercase font-mono tracking-wider">RESTE DISPO</span>
                                    <p className="font-mono font-bold text-emerald-600">{fmtMoney(detail.total_remaining)}</p>
                                  </div>
                                </div>

                                <div className="flex items-center gap-3">
                                  <div className="px-3 py-1 rounded-full text-xs font-bold bg-slate-900 text-slate-100 font-mono">
                                    {detail.usage_percentage.toFixed(1)}% Utilisé
                                  </div>
                                  {isExpanded ? <ChevronUp className="h-5 w-5 text-slate-500" /> : <ChevronDown className="h-5 w-5 text-slate-500" />}
                                </div>
                              </div>
                            </button>

                            {/* Accordion content block */}
                            {isExpanded && (
                              <div className="border-t border-slate-100 p-6 bg-slate-50/20">
                                {detail.departments.length === 0 ? (
                                  <p className="text-sm text-slate-500 text-center py-4">Aucun département configuré pour {plantName}.</p>
                                ) : (
                                  <div className="space-y-6">
                                    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
                                      <table className="w-full text-left text-sm border-collapse">
                                        <thead>
                                          <tr className="bg-slate-50/85 text-slate-500 text-xs font-mono border-b border-slate-200">
                                            <th className="p-4 font-bold">DÉPARTEMENT</th>
                                            <th className="p-4 font-bold">CODE ANALYTIQUE (COST CENTER)</th>
                                            <th className="p-4 font-bold text-right">BUDGET ALLOUÉ</th>
                                            <th className="p-4 font-bold text-right">DÉPENSÉ (IAM)</th>
                                            <th className="p-4 font-bold text-right">RESTE DISPONIBLE</th>
                                            <th className="p-4 font-bold">% UTILISÉ</th>
                                            <th className="p-4 font-bold text-center">STATUT</th>
                                          </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-100">
                                          {detail.departments.map((dept) => {
                                            const statusStyle = getStatusColor(dept.budget_status, dept.percentage_used);
                                            return (
                                              <tr key={dept.department_name} className="hover:bg-slate-50/50 transition-colors">
                                                <td className="p-4 font-bold text-slate-800">{dept.department_name}</td>
                                                <td className="p-4 font-mono text-xs font-semibold text-slate-500">{dept.cost_center_id}</td>
                                                <td className="p-4 text-right font-mono text-slate-600">{fmtMoney(dept.initial_budget)}</td>
                                                <td className="p-4 text-right font-mono font-bold text-slate-800">{fmtMoney(dept.total_spent)}</td>
                                                <td className="p-4 text-right font-mono">
                                                  <span className={dept.remaining_budget < 0 ? 'text-red-600 font-bold' : 'text-emerald-600 font-bold'}>
                                                    {fmtMoney(dept.remaining_budget)}
                                                  </span>
                                                </td>
                                                <td className="p-4">
                                                  <div className="flex items-center gap-2">
                                                    <span className="font-mono text-xs font-bold text-slate-600">{dept.percentage_used.toFixed(1)}%</span>
                                                    <div className="w-16 bg-slate-100 rounded-full h-1 overflow-hidden shrink-0">
                                                      <div 
                                                        className={`h-1 rounded-full ${dept.percentage_used > 85 ? 'bg-rose-500' : 'bg-emerald-500'}`} 
                                                        style={{ width: `${Math.min(100, dept.percentage_used)}%` }}
                                                      />
                                                    </div>
                                                  </div>
                                                </td>
                                                <td className="p-4 text-center">
                                                  <span className={`inline-flex px-2.5 py-1 rounded-full text-[11px] font-bold border ${statusStyle.bg} ${statusStyle.border} ${statusStyle.text}`}>
                                                    {statusStyle.textBadge}
                                                  </span>
                                                </td>
                                              </tr>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ==================== TAB 2 STATE: ANALYZE INVOICE ==================== */}
          {activeTab === 'analyze' && (
            <div className="space-y-6">
              <div className="bg-white rounded-2xl border border-slate-100 p-6 shadow-xs">
                
                {/* Header Info Block */}
                <div className="mb-5">
                  <h2 className="text-base font-bold text-slate-800 mb-1">
                    Extraction & Imputation Budgétaire Multiple
                  </h2>
                  <p className="text-xs text-slate-400">
                    Déposez une ou plusieurs factures PDF IAM pour extraire les contrats et imputer automatiquement les centres de coûts.
                  </p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
                  
                  {/* Left/Main Column: Upload Zone & Selected Queue (3/5 layout space) */}
                  <div className="lg:col-span-3 space-y-4">
                    
                    {/* PERSISTENT CLICKABLE DROP ZONE (Always visible, adjusts height reactively) */}
                    <div 
                      onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                      onDragLeave={() => setDragActive(false)}
                      onDrop={handleDrop}
                      onClick={() => fileInputRef.current?.click()}
                      className={`border-2 border-dashed rounded-xl text-center transition-all flex flex-col items-center justify-center cursor-pointer group select-none ${
                        selectedFiles.length === 0 ? 'py-10 min-h-[180px]' : 'py-5'
                      } ${
                        dragActive 
                          ? 'border-rose-500 bg-rose-50/30' 
                          : 'border-slate-200 bg-slate-50/30 hover:border-slate-300 hover:bg-slate-50/80'
                      }`}
                    >
                      <input 
                        type="file" 
                        ref={fileInputRef}
                        onChange={handleFileInputChange}
                        accept=".pdf,.PDF"
                        multiple
                        className="hidden" 
                      />
                      
                      <UploadCloud className={`h-7 w-7 mb-2 transition-transform group-hover:-translate-y-0.5 ${
                        dragActive ? 'text-rose-600 scale-110' : 'text-slate-400 group-hover:text-rose-500'
                      }`} />
                      
                      <p className="text-xs font-semibold text-slate-700">
                        {selectedFiles.length > 0 ? "Glissez d'autres factures ici" : "Glissez-déposez vos factures IAM ici"}
                      </p>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        Fichiers PDF multiples autorisés
                      </p>
                    </div>

                    {/* QUEUE LIST CONTAINER (Maintains a clean frame when items are added) */}
                    {selectedFiles.length > 0 && (
                      <div className="border border-slate-100 rounded-xl p-4 bg-white shadow-xs space-y-3 animate-in fade-in duration-200">
                        <div className="flex items-center justify-between border-b border-slate-50 pb-2">
                          <h4 className="text-[11px] font-bold font-mono uppercase text-slate-400 tracking-wider">
                            File Queue ({selectedFiles.length})
                          </h4>
                          <button 
                            type="button"
                            onClick={() => setSelectedFiles([])} 
                            className="text-[10px] text-slate-400 hover:text-rose-500 font-bold transition-colors cursor-pointer"
                          >
                            Tout vider
                          </button>
                        </div>

                        <div className="max-h-52 overflow-y-auto space-y-1.5 pr-1 custom-scrollbar">
                          {selectedFiles.map((f, index) => (
                            <div 
                              key={index} 
                              className="flex items-center justify-between p-2.5 bg-slate-50 border border-slate-100 rounded-lg text-xs hover:border-slate-200 transition-colors"
                            >
                              <div className="flex items-center gap-2.5 truncate max-w-[80%]">
                                {/* Interactive Micro-status per file row */}
                                {isAnalyzing ? (
                                  <RefreshCw className="h-3 w-3 text-rose-500 animate-spin flex-shrink-0" />
                                ) : (
                                  <div className="h-1.5 w-1.5 rounded-full bg-amber-400 flex-shrink-0" title="En attente" />
                                )}
                                <span className="font-medium text-slate-700 truncate">{f.name}</span>
                              </div>
                              
                              <button 
                                type="button"
                                disabled={isAnalyzing}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedFiles(prev => prev.filter((_, idx) => idx !== index));
                                }}
                                className="text-slate-400 hover:text-rose-600 p-1 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                ✕
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Right Column: Output Results Box (2/5 layout space) */}
                  <div className="lg:col-span-2 flex flex-col justify-between border border-slate-100 rounded-xl p-4 bg-slate-50/50">
                    <div className="space-y-3 h-full flex flex-col">
                      <h3 className="text-[11px] font-mono font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100 pb-2">
                        Rapports Excel Générés
                      </h3>
                      
                      {batchFiles.length === 0 ? (
                        /* Balanced Empty State placeholder to ensure visual layout consistency */
                        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 opacity-60 my-auto">
                          <div className="h-9 w-9 rounded-xl bg-slate-100 flex items-center justify-center text-slate-400 font-mono font-bold text-xs mb-2">
                            XL
                          </div>
                          <p className="text-xs font-medium text-slate-500">Aucun rapport généré</p>
                          <p className="text-[10px] text-slate-400 mt-0.5">Lancez l'extraction pour compiler les données</p>
                        </div>
                      ) : (
                        /* Populated Output Document Queue */
                        <div className="max-h-64 overflow-y-auto space-y-2 pr-1 flex-1">
                          {batchFiles.map((file, idx) => (
                            <div 
                              key={idx} 
                              className="bg-white border border-slate-200 rounded-xl p-3 shadow-xs flex items-center justify-between hover:border-emerald-200 transition-all animate-in slide-in-from-bottom-2 duration-200"
                            >
                              <div className="flex items-center gap-2.5 truncate max-w-[60%]">
                                <div className="h-7 w-7 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center text-xs font-mono font-black flex-shrink-0">
                                  XL
                                </div>
                                <div className="truncate">
                                  <h4 className="font-bold text-slate-800 text-xs truncate" title={file.filename}>
                                    {file.filename}
                                  </h4>
                                  <span className="text-[9px] font-mono text-slate-400 block">Microsoft Excel</span>
                                </div>
                              </div>

                              <button
                                type="button"
                                onClick={() => downloadBatchFile(file.file_contents, file.filename)}
                                className="p-1.5 px-3 bg-emerald-50 text-emerald-600 hover:bg-emerald-600 hover:text-white rounded-lg border border-emerald-100 text-[11px] font-bold shadow-xs flex items-center gap-1.5 cursor-pointer transition-all focus:outline-none"
                              >
                                <Download className="h-3.5 w-3.5" />
                                Télécharger
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* --- RUN ACTION BOTTOM ACTIONS BAR --- */}
                <div className="mt-6 pt-5 border-t border-slate-100 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <label className="flex items-center gap-3 cursor-pointer select-none group">
                    <input 
                      type="checkbox" 
                      checked={useOcr}
                      disabled={isAnalyzing}
                      onChange={(e) => setUseOcr(e.target.checked)}
                      className="rounded border-slate-300 text-rose-600 focus:ring-rose-500 h-4 w-4 cursor-pointer disabled:opacity-50"
                    />
                    <div className="text-left">
                      <span className="text-xs font-semibold text-slate-700 block group-hover:text-slate-900 transition-colors">
                        Forcer le mode OCR
                      </span>
                      <span className="text-[10px] text-slate-400 block">
                        Utile si le document est un scan de mauvaise qualité
                      </span>
                    </div>
                  </label>

                  <button
                    type="button"
                    disabled={selectedFiles.length === 0 || isAnalyzing}
                    onClick={handleAnalyzeInvoiceSubmit}
                    className={`w-full sm:w-auto px-6 py-2.5 rounded-xl font-bold text-xs flex items-center justify-center gap-2 shadow-sm transition-all transform active:scale-[0.99] ${
                      selectedFiles.length === 0 || isAnalyzing
                        ? 'bg-slate-100 text-slate-400 cursor-not-allowed shadow-none'
                        : 'bg-rose-600 hover:bg-rose-700 text-white cursor-pointer'
                    }`}
                  >
                    {isAnalyzing ? (
                      <>
                        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        <span>Traitement & Imputation...</span>
                      </>
                    ) : (
                      <>
                        <FileText className="h-3.5 w-3.5" />
                        <span>Lancer l'imputation ({selectedFiles.length} PDF)</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}
          {/* ==================== TAB 3 STATE: CONFIGURATION ==================== */}
          {activeTab === 'config' && (
            <div className="space-y-8 max-w-5xl mx-auto">
              
              {/* Json config view switch */}
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setIsJsonView(!isJsonView)}
                  className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 hover:text-slate-800 text-xs font-semibold shadow-xs flex items-center gap-2 cursor-pointer focus:outline-none"
                >
                  <Layers className="h-4 w-4" />
                  {isJsonView ? "🗂️ Vue Formulaires Standard" : "🛠️ Éditeur de Code JSON"}
                </button>
              </div>

              {isJsonView ? (
                <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="text-md font-bold text-slate-900">Éditeur Config JSON Brut</h3>
                      <p className="text-xs text-slate-400 mt-0.5">Modifiez directement la configuration globale</p>
                    </div>
                    <button 
                      onClick={handleSaveRawJson}
                      className="px-4 py-2 bg-slate-900 text-slate-100 hover:bg-slate-800 text-xs font-semibold rounded-lg shadow-sm cursor-pointer"
                    >
                      Sauvegarder JSON Configuration
                    </button>
                  </div>
                  <textarea
                    value={editingConfigJson}
                    onChange={(e) => setEditingConfigJson(e.target.value)}
                    className="w-full h-[500px] bg-slate-900 text-slate-100 font-mono text-xs p-4 rounded-xl border border-slate-800 outline-none focus:border-rose-500 shadow-inner"
                  />
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                  
                  {/* Grid Left Elements Column */}
                  <div className="space-y-8">
                    {/* Panel 1: Clients Mappages */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                      <h3 className="text-md font-bold text-slate-900 mb-1">🗂️ Mapping N° Client ➔ Usine</h3>
                      <p className="text-xs text-slate-400 mb-6 font-semibold">Associe chaque N° abonnement client unique à une usine YAZAKI</p>

                      <form onSubmit={handleAddMappingSubmit} className="grid grid-cols-3 gap-3 mb-6">
                        <input 
                          type="text" 
                          placeholder="Ex: 1028374" 
                          value={newClientNum}
                          onChange={(e) => setNewClientNum(e.target.value)}
                          className="col-span-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-mono font-bold"
                        />
                        <input 
                          type="text" 
                          placeholder="Ex: YAZAKI Tangier 1" 
                          value={newClientPlant}
                          onChange={(e) => setNewClientPlant(e.target.value)}
                          className="col-span-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-bold"
                        />
                        <button 
                          type="submit"
                          className="col-span-1 bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs rounded-lg flex items-center justify-center gap-1 cursor-pointer focus:outline-none"
                        >
                          <Plus className="h-4 w-4" />
                          Ajouter
                        </button>
                      </form>

                      {config && Object.keys(config.client_plant_mapping).length > 0 ? (
                        <div className="border border-slate-150 rounded-xl overflow-hidden max-h-[220px] overflow-y-auto">
                          <table className="w-full text-left text-xs">
                            <thead>
                              <tr className="bg-slate-50 text-slate-500 font-mono border-b border-slate-150">
                                <th className="p-3">N° CLIENT IAM</th>
                                <th className="p-3">USINE APPARENTÉE</th>
                                <th className="p-3 text-center">OPTIONS</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {Object.entries(config.client_plant_mapping).map(([clientNum, plant]) => (
                                <tr key={clientNum} className="hover:bg-slate-50/40">
                                  <td className="p-3 font-mono font-bold text-slate-800">{clientNum}</td>
                                  <td className="p-3 font-semibold text-slate-600">{plant}</td>
                                  <td className="p-3 text-center">
                                    <button 
                                      onClick={() => handleDeleteMapping(clientNum)}
                                      className="text-rose-600 hover:text-rose-800 focus:outline-none cursor-pointer"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </button>
                                   </td>
                                 </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 text-center py-4 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                          Aucun mapping configuré. Saisissez des données d'enveloppes budget pour démarrer.
                        </p>
                      )}
                    </div>

                    {/* Panel 2: Register/Add department */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                      <h3 className="text-md font-bold text-slate-900 mb-1">🏭 Ajouter un Département</h3>
                      <p className="text-xs text-slate-400 mb-6 font-semibold">Crée une nouvelle enveloppe budgétaire rattachée à une usine</p>

                      <form onSubmit={handleAddDepartmentSubmit} className="space-y-4">
                        <div>
                          <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Sélectionner l'Usine</label>
                          <select
                            value={selectedConfigPlant}
                            onChange={(e) => setSelectedConfigPlant(e.target.value)}
                            className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-semibold"
                          >
                            <option value="">-- Choisir une usine --</option>
                            {plants.map(p => (
                              <option key={p} value={p}>{p}</option>
                            ))}
                          </select>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Nom Département</label>
                            <input 
                              type="text" 
                              placeholder="Ex: IT Infrastructure" 
                              value={newDeptName}
                              onChange={(e) => setNewDeptName(e.target.value)}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-semibold"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Cost Center ID (Code)</label>
                            <input 
                              type="text" 
                              placeholder="Ex: CC-IT-01" 
                              value={newDeptCostCenter}
                              onChange={(e) => setNewDeptCostCenter(e.target.value)}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-mono font-bold"
                            />
                          </div>
                        </div>

                        <div>
                          <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Budget Initial (MAD)</label>
                          <input 
                            type="number" 
                            value={newDeptBudget}
                            onChange={(e) => setNewDeptBudget(Number(e.target.value))}
                            className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-mono font-bold animate-pulse"
                          />
                        </div>

                        <button 
                          type="submit"
                          className="w-full py-2.5 px-4 bg-slate-900 border border-slate-800 hover:bg-slate-800 text-white font-semibold text-xs rounded-lg transition-colors flex items-center justify-center gap-1 focus:outline-none cursor-pointer"
                        >
                          <Plus className="h-4 w-4" />
                          Ajouter le Département
                        </button>
                      </form>
                    </div>

                  </div>

                  {/* Grid Right Elements Column */}
                  <div className="space-y-8">
                    {/* Panel 3: Phone numbers mappings configuration */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                      <h3 className="text-md font-bold text-slate-900 mb-1">📱 Affectation des Numéros d'Appel</h3>
                      <p className="text-xs text-slate-400 mb-6 font-semibold">Associez les cartes sim/numéros de l'annexe à un département pour imputation</p>

                      <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Choisir l'Usine</label>
                            <select
                              value={selectedConfigPlant}
                              onChange={(e) => {
                                setSelectedConfigPlant(e.target.value);
                                setSelectedPhoneDept('');
                              }}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none"
                            >
                              <option value="">-- Usine --</option>
                              {plants.map(p => (
                                <option key={p} value={p}>{p}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Département d'Imputation</label>
                            <select
                              value={selectedPhoneDept}
                              onChange={(e) => setSelectedPhoneDept(e.target.value)}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-semibold"
                            >
                              <option value="">-- Choisir Département --</option>
                              {config && selectedConfigPlant && config.plants[selectedConfigPlant] && 
                                Object.keys(config.plants[selectedConfigPlant].departments).map(deptKey => (
                                  <option key={deptKey} value={deptKey}>{deptKey}</option>
                                ))
                              }
                            </select>
                          </div>
                        </div>

                        <div>
                          <div className="flex items-center justify-between">
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Numéros Affectés (1 format par ligne)</label>
                            <span className="text-[10px] text-slate-400 font-mono font-semibold">Ex: 0661223344</span>
                          </div>
                          <textarea
                            value={phoneText}
                            onChange={(e) => setPhoneText(e.target.value)}
                            placeholder="Entrez vos numéros ici (ex: 0661001122)..."
                            rows={8}
                            className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 font-mono outline-none focus:border-rose-500 shadow-inner"
                          />
                        </div>

                        <button 
                          onClick={handleSavePhones}
                          className="w-full py-2.5 px-4 bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs rounded-lg transition-colors flex items-center justify-center gap-1 focus:outline-none cursor-pointer shadow-xs"
                        >
                          <Check className="h-4 w-4" />
                          Enregistrer les numéros affectés
                        </button>
                      </div>
                    </div>

                    {/* Panel 4: Budget modifications resets and adjustments */}
                    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs border-l-rose-500 border-l-4">
                      <h3 className="text-md font-bold text-slate-900 mb-1">💰 Actions sur Crédits & Enveloppes</h3>
                      <p className="text-xs text-slate-400 mb-6 font-semibold">Modifiez ou ajustez en temps réel l'état budgétaire d'un Cost Center</p>

                      <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Usine</label>
                            <select
                              value={adjPlant}
                              onChange={(e) => {
                                setAdjPlant(e.target.value);
                                setAdjDept('');
                              }}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none"
                            >
                              <option value="">-- Choisir Usine --</option>
                              {plants.map(p => (
                                <option key={p} value={p}>{p}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Cost Center</label>
                            <select
                              value={adjDept}
                              onChange={(e) => setAdjDept(e.target.value)}
                              className="w-full mt-1 bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:border-rose-500 font-semibold"
                            >
                              <option value="">-- Choisir Centre --</option>
                              {config && adjPlant && config.plants[adjPlant] && 
                                Object.keys(config.plants[adjPlant].departments).map(deptKey => (
                                  <option key={deptKey} value={deptKey}>{deptKey}</option>
                                ))
                              }
                            </select>
                          </div>
                        </div>

                        {adjPlant && adjDept && plantDetailBudgets[adjPlant]?.departments.find(d => d.department_name === adjDept) && (
                          <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 flex items-center justify-between text-xs font-semibold">
                            <div>
                              <span className="text-slate-400 font-mono text-[10px] block uppercase font-bold">RESTE DISPO ACTUEL</span>
                              <span className="font-mono text-slate-800">
                                {fmtMoney(plantDetailBudgets[adjPlant]?.departments.find(d => d.department_name === adjDept)?.remaining_budget)}
                              </span>
                            </div>
                            <div className="text-right">
                              <span className="text-slate-400 font-mono text-[10px] block uppercase font-bold">BUDGET BASE</span>
                              <span className="font-mono text-slate-600">
                                {fmtMoney(plantDetailBudgets[adjPlant]?.departments.find(d => d.department_name === adjDept)?.initial_budget)}
                              </span>
                            </div>
                          </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                          {/* Left Reset form */}
                          <div className="p-4 rounded-xl bg-slate-50 border border-slate-100 space-y-3 shadow-xs">
                            <span className="text-xs font-bold text-slate-900 block flex items-center gap-1">
                              <RefreshCw className="h-4 w-4 text-rose-500" />
                              🔄 Réinitialiser
                            </span>
                            <div className="space-y-2">
                              <label className="text-[10px] text-slate-400 font-mono">Nouveau Budget (MAD)</label>
                              <input 
                                type="number" 
                                value={resetAmount}
                                onChange={(e) => setResetAmount(Number(e.target.value))}
                                className="w-full bg-white border border-slate-200 rounded p-2 text-xs font-mono font-bold"
                              />
                              <button
                                onClick={handleResetBudgetSubmit}
                                className="w-full py-1.5 bg-rose-600 text-white text-xs font-semibold rounded cursor-pointer hover:bg-rose-500"
                              >
                                Réinitialiser le Budget
                              </button>
                            </div>
                          </div>

                          {/* Right Adjust form */}
                          <div className="p-4 rounded-xl bg-slate-50 border border-slate-100 space-y-3 shadow-xs">
                            <span className="text-xs font-bold text-slate-900 block flex items-center gap-1">
                              <ArrowRightLeft className="h-4 w-4 text-emerald-500" />
                              📝 Ajuster (+/-)
                            </span>
                            <div className="space-y-2">
                              <label className="text-[10px] text-slate-400 font-mono">Montant Ajustement (MAD)</label>
                              <input 
                                type="number" 
                                value={adjustAmount}
                                onChange={(e) => setAdjustAmount(Number(e.target.value))}
                                className="w-full bg-white border border-slate-200 rounded p-2 text-xs font-mono font-bold"
                                placeholder="+/- 500.00"
                              />
                              <button
                                onClick={handleAdjustBudgetSubmit}
                                className="w-full py-1.5 bg-slate-900 text-white text-xs font-semibold rounded cursor-pointer hover:bg-slate-800"
                              >
                                Appliquer l'Ajustement
                              </button>
                            </div>
                          </div>
                        </div>

                      </div>
                    </div>

                  </div>

                </div>
              )}
            </div>
          )}


          {/* ==================== TAB 4 STATE: REPORTS ==================== */}
          {activeTab === 'reports' && (
            <div className="space-y-8 max-w-5xl mx-auto">
              
              {/* Report Configuration Search header */}
              <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                <h3 className="text-md font-bold text-slate-900 mb-1">📅 Sélectionner les paramètres du Rapport</h3>
                <p className="text-xs text-slate-400 mb-6 font-semibold">Filtrez l'audit par plage de date et établissements YAZAKI</p>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Date Début</label>
                    <div className="relative mt-1">
                      <Calendar className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                      <input 
                        type="date" 
                        value={reportStartDate}
                        onChange={(e) => setReportStartDate(e.target.value)}
                        className="w-full pl-10 bg-slate-50 border border-slate-200 p-2.5 rounded-lg text-xs font-semibold focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Date Fin</label>
                    <div className="relative mt-1">
                      <Calendar className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                      <input 
                        type="date" 
                        value={reportEndDate}
                        onChange={(e) => setReportEndDate(e.target.value)}
                        className="w-full pl-10 bg-slate-50 border border-slate-200 p-2.5 rounded-lg text-xs font-semibold focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] text-slate-500 font-bold uppercase font-mono tracking-wider">Usine Analysée</label>
                    <select
                      value={reportPlant}
                      onChange={(e) => setReportPlant(e.target.value)}
                      className="w-full mt-1 bg-slate-50 border border-slate-200 p-2.5 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none"
                    >
                      <option value="">-- Choisir une usine --</option>
                      {plants.map(p => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Report KPIs */}
              {reportPlant && plantDetailBudgets[reportPlant] ? (
                <>
                  {/* Highlights widgets */}
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                    <div className="bg-white border border-slate-200 p-5 rounded-2xl shadow-xs">
                      <span className="text-[10px] font-mono text-slate-400 block font-bold">BUDGET INITIAL USINE</span>
                      <h4 className="text-lg font-black font-mono text-slate-800 mt-1">
                        {fmtMoney(plantDetailBudgets[reportPlant].total_budget)}
                      </h4>
                    </div>
                    <div className="bg-white border border-slate-200 p-5 rounded-2xl shadow-xs">
                      <span className="text-[10px] font-mono text-rose-500 block font-bold">COMMUNICATIONS LOGUÉES</span>
                      <h4 className="text-lg font-black font-mono text-rose-600 mt-1">
                        {fmtMoney(plantDetailBudgets[reportPlant].total_spent)}
                      </h4>
                    </div>
                    <div className="bg-white border border-slate-200 p-5 rounded-2xl shadow-xs">
                      <span className="text-[10px] font-mono text-emerald-600 block font-bold">TRÉSORERIE DISPONIBLE</span>
                      <h4 className="text-lg font-black font-mono text-emerald-600 mt-1">
                        {fmtMoney(plantDetailBudgets[reportPlant].total_remaining)}
                      </h4>
                    </div>
                    <div className="bg-white border border-slate-200 p-5 rounded-2xl shadow-xs">
                      <span className="text-[10px] font-mono text-slate-400 block font-bold">RENDEMENT UTILISATION</span>
                      <h4 className="text-lg font-black font-mono text-slate-800 mt-1">
                        {plantDetailBudgets[reportPlant].usage_percentage.toFixed(1)}%
                      </h4>
                    </div>
                  </div>

                  {/* Visual graphs */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    {/* Visual 1: Plant internal Departments */}
                    <div className="bg-white border border-slate-200 p-6 rounded-2xl shadow-xs">
                      <h4 className="text-sm font-bold text-slate-900 mb-6">Enveloppe vs Dépenses par Département</h4>
                      <div className="h-72">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={plantDetailBudgets[reportPlant].departments}
                            margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                            <XAxis dataKey="department_name" tickFormatter={(v) => v.split(' (')[0].substring(0, 10)} stroke="#64748b" fontSize={11} />
                            <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v) => `${v}`} />
                            <Tooltip formatter={(v: any) => [`${fmtMoney(Number(v))}`, '']} />
                            <Bar dataKey="initial_budget" fill="#2563eb" radius={[4, 4, 0, 0]} name="Budget" barSize={16} />
                            <Bar dataKey="total_spent" fill="#f43f5e" radius={[4, 4, 0, 0]} name="Dépenses" barSize={16} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    {/* Visual 2: Pie distribution */}
                    <div className="bg-white border border-slate-200 p-6 rounded-2xl shadow-xs">
                      <h4 className="text-sm font-bold text-slate-900 mb-6">Répartition Consommation Budgétaire</h4>
                      <div className="h-72 flex items-center justify-center">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={plantDetailBudgets[reportPlant].departments.filter(d => d.total_spent > 0)}
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={80}
                              paddingAngle={4}
                              dataKey="total_spent"
                              nameKey="department_name"
                            >
                              {plantDetailBudgets[reportPlant].departments.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={['#e11d48', '#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'][index % 6]} />
                              ))}
                            </Pie>
                            <Tooltip formatter={(v: any) => [`${fmtMoney(Number(v))}`, 'Consommé']} />
                            <Legend layout="horizontal" align="center" verticalAlign="bottom" wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>

                  {/* Summary grid list */}
                  <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h4 className="text-sm font-bold text-slate-900">Relevé de Clôture Budgétaire</h4>
                        <p className="text-[11px] text-slate-400 mt-0.5">Données générées pour l'usine {reportPlant}</p>
                      </div>

                      <button
                        onClick={exportReportToCsv}
                        className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs rounded-lg flex items-center gap-1.5 focus:outline-none cursor-pointer"
                      >
                        <Download className="h-4 w-4" />
                        Exporter Rapport CSV
                      </button>
                    </div>

                    <div className="overflow-x-auto rounded-xl border border-slate-150">
                      <table className="w-full text-left text-xs border-collapse">
                        <thead>
                          <tr className="bg-slate-50 text-slate-500 font-mono border-b border-slate-150">
                            <th className="p-3">DÉPARTEMENT</th>
                            <th className="p-3">COST CENTER ID</th>
                            <th className="p-3 text-right">BUDGET INITIAL</th>
                            <th className="p-3 text-right">DÉPENSES engagées</th>
                            <th className="p-3 text-right">RESTE DISPO</th>
                            <th className="p-3">% UTILISATION</th>
                            <th className="p-3 text-center">ANALYSE</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {plantDetailBudgets[reportPlant].departments.map((d) => (
                            <tr key={d.department_name} className="hover:bg-slate-50/40 font-medium">
                              <td className="p-3 text-slate-800">{d.department_name}</td>
                              <td className="p-3 font-mono text-slate-500">{d.cost_center_id}</td>
                              <td className="p-3 text-right font-mono text-slate-600">{fmtMoney(d.initial_budget)}</td>
                              <td className="p-3 text-right font-mono text-slate-800">{fmtMoney(d.total_spent)}</td>
                              <td className="p-3 text-right font-mono">
                                <span className={d.remaining_budget < 0 ? 'text-red-600 font-bold' : 'text-emerald-700 font-bold'}>
                                  {fmtMoney(d.remaining_budget)}
                                </span>
                              </td>
                              <td className="p-3 font-mono font-bold text-slate-600">{d.percentage_used.toFixed(1)}%</td>
                              <td className="p-3 text-center">
                                <span className={`inline-block h-2.5 w-2.5 rounded-full ${d.remaining_budget < 0 ? 'bg-red-500' : 'bg-emerald-500'}`} />
                               </td>
                             </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="bg-white border border-slate-200 rounded-2xl p-12 text-center text-slate-400 shadow-xs">
                  Veuillez spécifier une Usine configurée pour afficher et compiler les rapports financiers.
                </div>
              )}
            </div>
          )}


          {/* ==================== TAB 5 STATE: HISTORY ==================== */}
          {activeTab === 'history' && (
            <div className="space-y-8 max-w-5xl mx-auto">
              
              <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                <div className="border-b border-slate-150 pb-4 mb-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                  <div>
                    <h3 className="text-md font-bold text-slate-900">📚 Journal d'Extraction des Factures</h3>
                    <p className="text-xs text-slate-400 mt-0.5">Registre complet de toutes les factures IAM enregistrées</p>
                  </div>
                  <button
                    onClick={handleClearInvoices}
                    className="px-4 py-2 bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 font-bold text-xs rounded-xl flex items-center gap-1.5 focus:outline-none cursor-pointer"
                  >
                    <Trash2 className="h-4 w-4" />
                    Purger l'Historique de la Base
                  </button>
                </div>

                {invoices.length === 0 ? (
                  <p className="text-xs text-slate-400 text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                    Aucune facture enregistrée dans le registre SQLite de FastAPI. Importez une facture pour démarrer.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-slate-155">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-50 text-slate-500 font-mono border-b border-slate-155">
                          <th className="p-3">ID SAVED</th>
                          <th className="p-3">DATE SAUVEGARDE</th>
                          <th className="p-3">USINE APPARTEMENT</th>
                          <th className="p-3">N° FACTURE</th>
                          <th className="p-3">DATE EMISSION</th>
                          <th className="p-3 text-right">TOTAL (HT)</th>
                          <th className="p-3 text-right">TOTAL TTC (MAD)</th>
                          <th className="p-3 text-center">CONTRATS</th>
                          <th className="p-3 text-center">EXCEL</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 font-medium">
                        {invoices.map((inv) => (
                          <tr key={inv.id} className="hover:bg-slate-50/40">
                            <td className="p-3 font-mono font-bold text-slate-400">#{inv.id}</td>
                            <td className="p-3 text-slate-500">{fmtDate(inv.saved_at)}</td>
                            <td className="p-3 text-slate-800 font-bold">{inv.plant}</td>
                            <td className="p-3 font-mono text-xs">{inv.invoice_number}</td>
                            <td className="p-3 text-slate-600 font-mono">{inv.invoice_date}</td>
                            <td className="p-3 text-right font-mono text-slate-500">{fmtMoney(inv.montant_ht)}</td>
                            <td className="p-3 text-right font-mono font-black text-slate-900">{fmtMoney(inv.total)}</td>
                            <td className="p-3 text-center font-mono font-bold">{inv.contracts_count || 0} lines</td>
                            <td className="p-3 text-center">
                              <a 
                                href={api.getExportUrl(inv.id)}
                                target="_blank"
                                rel="noreferrer"
                                className="p-1 px-2 hover:bg-emerald-50 text-emerald-600 hover:text-emerald-700 rounded border border-transparent hover:border-emerald-200 shadow-xs cursor-pointer focus:outline-none"
                              >
                                📥 Télécharger
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Transactions logs audit */}
              <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs">
                <div className="border-b border-slate-150 pb-4 mb-6">
                  <h3 className="text-md font-bold text-slate-900">📒 Registre des Transactions Budgétaires</h3>
                  <p className="text-xs text-slate-400 mt-0.5">Audit log et traçabilité de de tous les débits, crédits et modifications budgétaires</p>
                </div>

                <div className="flex flex-col md:flex-row gap-4 mb-6">
                  <div className="flex-1 relative">
                    <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                    <input 
                      type="text" 
                      placeholder="Filtrer l'historique par N° de Facture..." 
                      value={txInvoiceFilter}
                      onChange={(e) => setTxInvoiceFilter(e.target.value)}
                      className="w-full pl-10 bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs focus:outline-none focus:border-rose-500"
                    />
                  </div>
                  
                  <div className="w-56">
                    <select
                      value={txLimit}
                      onChange={(e) => setTxLimit(Number(e.target.value))}
                      className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs focus:outline-none"
                    >
                      <option value="10">Afficher 10 transactions</option>
                      <option value="50">Afficher 50 transactions</option>
                      <option value="100">Afficher 100 transactions</option>
                      <option value="250">Afficher 250 transactions</option>
                      <option value="500">Afficher 500 transactions</option>
                    </select>
                  </div>
                </div>

                {transactions.length === 0 ? (
                  <p className="text-xs text-slate-400 text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                    Aucune transaction de débit ou d'initialisation enregistrée pour ces filtres.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-slate-150">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-50 text-slate-500 font-mono border-b border-slate-150">
                          <th className="p-3">DATE TRANSACTION</th>
                          <th className="p-3">USINE</th>
                          <th className="p-3">DÉPARTEMENT</th>
                          <th className="p-3">N° FACTURE</th>
                          <th className="p-3 text-center">TYPE D'OPÉRATION</th>
                          <th className="p-3 text-right">ANCIEN RESTE</th>
                          <th className="p-3 text-right">IMPUTATION (+/-)</th>
                          <th className="p-3 text-right">NOUVEAU SOLDE</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 font-medium">
                        {transactions.map((tx) => {
                          const isDebit = tx.transaction_type === "INVOICE_DEDUCTION";
                          const isAdjust = tx.transaction_type === "ADJUST";
                          const isReset = tx.transaction_type === "RESET";

                          return (
                            <tr key={tx.id} className="hover:bg-slate-50/40">
                              <td className="p-3 text-slate-400 font-mono">{fmtDate(tx.created_at)}</td>
                              <td className="p-3 text-slate-900 font-bold">{tx.plant_name}</td>
                              <td className="p-3 text-slate-700">{tx.department_name}</td>
                              <td className="p-3 font-mono text-slate-500 text-[11px]">
                                {tx.invoice_number || <span className="text-slate-300">—</span>}
                              </td>
                              <td className="p-3 text-center">
                                <span className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-mono font-bold uppercase border ${
                                  isDebit 
                                    ? 'bg-rose-50 text-rose-700 border-rose-200' 
                                    : isAdjust 
                                      ? 'bg-amber-50 text-amber-700 border-amber-200' 
                                      : 'bg-indigo-50 text-indigo-700 border-indigo-200'
                                }`}>
                                  {tx.transaction_type}
                                </span>
                              </td>
                              <td className="p-3 text-right font-mono text-slate-500">{fmtMoney(tx.old_budget)}</td>
                              <td className="p-3 text-right font-mono font-bold">
                                <span className={isDebit ? 'text-rose-600' : 'text-emerald-600'}>
                                  {isDebit ? '-' : '+'}{fmtMoney(tx.amount)}
                                </span>
                              </td>
                              <td className="p-3 text-right font-mono font-black text-slate-900">{fmtMoney(tx.new_budget)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

            </div>
          )}

        </div>
      </main>

    </div>
  );
}