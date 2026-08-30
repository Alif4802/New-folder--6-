import React from 'react';
import { ConnectionBadge } from '../components/ConnectionBadge';
import { ConnectionStatus, HealthResponse } from '../types/api';

interface TopHeaderProps {
  status: ConnectionStatus;
  healthData: HealthResponse | null;
  error?: string;
  onRefreshHealth: () => void;
  isLoading: boolean;
}

export const TopHeader: React.FC<TopHeaderProps> = ({
  status,
  healthData,
  error,
  onRefreshHealth,
  isLoading,
}) => {
  return (
    <header className="h-16 bg-lms-panel border-b border-lms-border px-6 flex items-center justify-between flex-shrink-0">
      <div className="flex items-center gap-3">
        <span className="font-semibold text-sm text-lms-text-primary tracking-tight">
          NCTB Standalone Intelligence Suite
        </span>
        <span className="hidden sm:inline-block text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          Institutional Demo
        </span>
      </div>

      <div className="flex items-center gap-4">
        <ConnectionBadge
          status={status}
          healthData={healthData}
          error={error}
          onRefresh={onRefreshHealth}
          isLoading={isLoading}
        />
      </div>
    </header>
  );
};
