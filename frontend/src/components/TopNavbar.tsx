import React, { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';

interface TopNavbarProps {
  activeTab: string;
  loading: boolean;
  onRefreshAll: () => Promise<void>;
}

export default function TopNavbar({ activeTab, loading, onRefreshAll }: TopNavbarProps) {
  // State to hold the current live date and time
  const [currentDateTime, setCurrentDateTime] = useState(new Date());

  // Effect to update the time every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentDateTime(new Date());
    }, 1000);

    // Cleanup the interval on component unmount
    return () => clearInterval(timer);
  }, []);

  // Compute header titles dynamic strings mapping
  const getHeaderTitle = () => {
    switch (activeTab) {
      case 'dashboard':
        return 'Dashboard YAZAKI';
      case 'analyze':
        return 'Analyse de Factures IAM';
      case 'config':
        return 'Configuration Budgétaire';
      case 'reports':
        return 'Rapports et Analyses';
      case 'history':
        return "Historique d'Audit";
      default:
        return 'YAZAKI E-Hub';
    }
  };

  // Format the date and time cleanly in French locale (UTC alignment as per your label)
  const formattedDateTime = currentDateTime.toLocaleString('fr-FR', {
    timeZone: 'UTC',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <header className="bg-white border-b border-slate-200 px-8 py-4 flex items-center justify-between sticky top-0 z-10 shrink-0 shadow-xs">
      <div>
        <span className="text-xs font-mono font-bold uppercase tracking-widest text-slate-400">
          YAZAKI AUTOMOTIVE IAM HUB
        </span>
        <div className="flex items-center gap-2 mt-0.5">
          <h2 className="text-xl font-bold tracking-tight text-slate-900">
            {getHeaderTitle()}
          </h2>
          {loading && <RefreshCw className="h-4 w-4 animate-spin text-rose-600" />}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={onRefreshAll}
          className="p-2.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 transition-all text-slate-600 hover:text-rose-600 flex items-center gap-2 text-xs font-semibold shadow-xs cursor-pointer focus:outline-none"
        >
          <RefreshCw className="h-4 w-4" />
          Actualiser Tout
        </button>

        <div className="text-right text-xs">
          <span className="text-slate-400">Date et Heure Actuelles (UTC)</span>
          <p className="font-mono font-semibold text-slate-700 mt-0.5">
            {formattedDateTime}
          </p>
        </div>
      </div>
    </header>
  );
}