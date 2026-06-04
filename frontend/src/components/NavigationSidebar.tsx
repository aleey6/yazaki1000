import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  FileSearch, 
  Sliders, 
  BookOpen, 
  History, 
  Server, 
  Wifi, 
  WifiOff,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { api } from '../api';

interface NavigationSidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
}

export default function NavigationSidebar({
  activeTab,
  setActiveTab,
  apiBaseUrl,
  setApiBaseUrl
}: NavigationSidebarProps) {
  const [showConfigBase, setShowConfigBase] = useState(false);
  const [inputUrl, setInputUrl] = useState(apiBaseUrl);
  const [isOnline, setIsOnline] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(true);

  // Checks backend connection
  const checkConnection = async () => {
    setChecking(true);
    try {
      // Test either health or root endpoint
      await api.getHealth();
      setIsOnline(true);
    } catch (e) {
      try {
        await api.getRoot();
        setIsOnline(true);
      } catch (innerErr) {
        setIsOnline(false);
      }
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 15000); // Poll every 15s to keep status accurate
    return () => clearInterval(interval);
  }, [apiBaseUrl]);

  const menuItems = [
    { id: 'dashboard', label: 'Dashboard', icon: BarChart3, desc: 'Aperçu global des usines' },
    { id: 'analyze', label: 'Analyser Facture', icon: FileSearch, desc: 'Traitement automatique de PDF' },
    { id: 'config', label: 'Configuration', icon: Sliders, desc: 'Mappings clients et départements' },
    { id: 'reports', label: 'Rapports', icon: BookOpen, desc: 'Rapports budgétaires détaillés' },
    { id: 'history', label: 'Historique', icon: History, desc: 'Journaux et audit transactions' }
  ];

  const handleUrlSave = (e: React.FormEvent) => {
    e.preventDefault();
    setApiBaseUrl(inputUrl.trim());
    setShowConfigBase(false);
  };

  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
  };

  return (
    <aside 
      className={`bg-slate-900 text-slate-100 flex flex-col justify-between border-r border-slate-800 shrink-0 h-screen select-none sticky top-0 overflow-y-auto transition-all duration-300 z-50 ${
        isCollapsed ? 'w-20' : 'w-80'
      }`}
    >
      <div className="p-6">
        {/* Yazaki Brand Header */}
        <div className={`flex items-center gap-3 mb-8 ${isCollapsed ? 'justify-center' : ''}`}>
          <button
            onClick={toggleCollapse}
            className="h-10 w-10 bg-rose-600 rounded-lg flex items-center justify-center font-extrabold text-xl shadow-lg border border-rose-500 text-white select-none shrink-0 hover:bg-rose-700 transition-colors cursor-pointer"
            aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            Y
          </button>
          {!isCollapsed && (
            <div>
              <h1 className="font-sans font-bold text-lg tracking-tight select-none text-slate-100">YAZAKI IAM</h1>
              <p className="text-xs text-rose-400 font-mono tracking-wider font-bold">FACTURATIONS TELECOM</p>
            </div>
          )}
        </div>

        {/* Navigation Options */}
        {!isCollapsed && (
          <p className="text-slate-500 text-[10px] font-mono font-bold tracking-widest uppercase mb-4">
            MENU PRINCIPAL
          </p>
        )}
        
        <nav className="space-y-1.5 relative">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <div key={item.id} className="relative group">
                <button
                  id={`nav-${item.id}`}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center transition-all duration-200 outline-none text-left rounded-xl cursor-pointer ${
                    isCollapsed ? 'justify-center p-3' : 'gap-3.5 p-3'
                  } ${
                    isActive 
                      ? 'bg-rose-500/10 border-rose-500/30 text-rose-400 shadow-md shadow-rose-950/20' 
                      : 'bg-transparent text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                  }`}
                >
                  <Icon className={`h-5 w-5 shrink-0 ${isActive ? 'text-rose-400' : 'text-slate-500'}`} />
                  {!isCollapsed && (
                    <div className="flex-1 animate-fadeIn">
                      <div className="text-sm font-semibold">{item.label}</div>
                      <div className="text-[11px] opacity-75 mt-0.5 leading-normal">{item.desc}</div>
                    </div>
                  )}
                </button>
                
                {/* Cleaned Fixed Popover Label Element */}
                {isCollapsed && (
                  <div 
                    className="fixed left-20 ml-2 px-3 py-1.5 bg-slate-950 text-slate-100 text-xs font-semibold rounded-lg whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-150 shadow-2xl border border-slate-850 z-[99999] invisible group-hover:visible"
                    style={{
                      marginTop: '-2rem'
                    }}
                  >
                    {item.label}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </div>
      
      {/* Footer */}
      {!isCollapsed && (
        <div className="text-center pt-2 pb-4">
          <p className="text-[11px] font-sans text-slate-500">© 2026 YAZAKI Corporation</p>
          <p className="text-[10px] font-mono text-slate-600 mt-0.5">YAZAKI IAM Extractor v2.0</p>
        </div>
      )}
    </aside>
  );
}