import React from 'react';
import { Sidebar } from './Sidebar';
import { TopHeader } from './TopHeader';
import { Breadcrumb } from './Breadcrumb';
import { ConnectionStatus, HealthResponse, WorkspaceTab } from '../types/api';

interface AppLayoutProps {
  activeTab: WorkspaceTab;
  onSelectTab: (tab: WorkspaceTab) => void;
  status: ConnectionStatus;
  healthData: HealthResponse | null;
  error?: string;
  onRefreshHealth: () => void;
  isLoadingHealth: boolean;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  activeTab,
  onSelectTab,
  status,
  healthData,
  error,
  onRefreshHealth,
  isLoadingHealth,
  children,
}) => {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-lms-canvas">
      {/* Dark Navy Sidebar */}
      <Sidebar activeTab={activeTab} onSelectTab={onSelectTab} />

      {/* Main Administrative Workspace */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header */}
        <TopHeader
          status={status}
          healthData={healthData}
          error={error}
          onRefreshHealth={onRefreshHealth}
          isLoading={isLoadingHealth}
        />

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          <div className="max-w-6xl mx-auto">
            <Breadcrumb activeTab={activeTab} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};
