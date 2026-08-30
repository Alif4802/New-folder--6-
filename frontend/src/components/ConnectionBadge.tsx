import React from 'react';
import { RefreshCw, Activity, AlertTriangle, XCircle, CheckCircle2 } from 'lucide-react';
import { ConnectionStatus, HealthResponse } from '../types/api';

interface ConnectionBadgeProps {
  status: ConnectionStatus;
  healthData: HealthResponse | null;
  error?: string;
  onRefresh: () => void;
  isLoading: boolean;
}

export const ConnectionBadge: React.FC<ConnectionBadgeProps> = ({
  status,
  healthData,
  error,
  onRefresh,
  isLoading,
}) => {
  let badgeClasses = 'bg-slate-100 text-slate-700 border-slate-200';
  let dotColor = 'bg-slate-400';
  let label = 'Checking backend...';
  let Icon = Activity;

  if (status === 'connected' && healthData) {
    badgeClasses = 'bg-emerald-50 text-emerald-800 border-emerald-200';
    dotColor = 'bg-emerald-500';
    label = `Backend Connected (${healthData.api_version})`;
    Icon = CheckCircle2;
  } else if (status === 'degraded' && healthData) {
    badgeClasses = 'bg-amber-50 text-amber-800 border-amber-200';
    dotColor = 'bg-amber-500';
    label = `Degraded (DB: ${healthData.database})`;
    Icon = AlertTriangle;
  } else if (status === 'unavailable') {
    badgeClasses = 'bg-rose-50 text-rose-800 border-rose-200';
    dotColor = 'bg-rose-500';
    label = error ? `Backend unavailable` : 'Backend unavailable';
    Icon = XCircle;
  }

  return (
    <div className="flex items-center gap-2">
      <div
        className={`inline-flex items-center gap-2 px-3 py-1 text-xs font-medium rounded-full border shadow-sm transition-colors ${badgeClasses}`}
        title={error ? `Error: ${error}` : healthData ? `Status: ${healthData.status}, DB: ${healthData.database}` : undefined}
      >
        <span className={`w-2 h-2 rounded-full ${dotColor} ${status === 'connected' ? 'animate-pulse' : ''}`} />
        <Icon className="w-3.5 h-3.5" />
        <span>{label}</span>
      </div>

      <button
        onClick={onRefresh}
        disabled={isLoading}
        aria-label="Refresh connection status"
        title="Check backend health"
        className="p-1 text-lms-text-muted hover:text-lms-text-secondary hover:bg-slate-100 rounded transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
      </button>
    </div>
  );
};
