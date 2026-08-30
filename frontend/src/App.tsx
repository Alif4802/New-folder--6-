import { useState, useEffect, useCallback } from 'react';
import { AppLayout } from './layout/AppLayout';
import { TextbookIntelligencePage } from './pages/TextbookIntelligencePage';
import { AssessmentGeneratorPage } from './pages/AssessmentGeneratorPage';
import { QuestionBankPage } from './pages/QuestionBankPage';
import { SavedPapersPage } from './pages/SavedPapersPage';
import { apiService } from './services/api';
import { ConnectionStatus, HealthResponse, WorkspaceTab } from './types/api';

import { AssessmentWorkspaceProvider } from './context/AssessmentWorkspaceContext';

export function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('textbook');
  const [selectedAssessmentVersionId, setSelectedAssessmentVersionId] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [healthData, setHealthData] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | undefined>(undefined);
  const [isLoadingHealth, setIsLoadingHealth] = useState<boolean>(false);

  const fetchHealth = useCallback(async () => {
    setIsLoadingHealth(true);
    const result = await apiService.checkHealth();
    setIsLoadingHealth(false);

    if (result.ok && result.data) {
      setHealthData(result.data);
      setHealthError(undefined);
      setConnectionStatus('connected');
    } else if (result.data && result.data.status === 'degraded') {
      setHealthData(result.data);
      setHealthError(undefined);
      setConnectionStatus('degraded');
    } else {
      setHealthData(null);
      setHealthError(result.error || 'Failed to connect to backend');
      setConnectionStatus('unavailable');
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    // Recheck health periodically every 30 seconds
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const handleNavigateToAssessment = (versionId: string) => {
    setSelectedAssessmentVersionId(versionId);
    setActiveTab('assessment');
  };

  return (
    <AssessmentWorkspaceProvider>
      <AppLayout
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        status={connectionStatus}
        healthData={healthData}
        error={healthError}
        onRefreshHealth={fetchHealth}
        isLoadingHealth={isLoadingHealth}
      >
        {activeTab === 'textbook' && (
          <TextbookIntelligencePage onNavigateToAssessment={handleNavigateToAssessment} />
        )}
        {activeTab === 'assessment' && (
          <AssessmentGeneratorPage
            selectedVersionId={selectedAssessmentVersionId}
            onClearSelectedVersion={() => setSelectedAssessmentVersionId(null)}
          />
        )}
        {activeTab === 'question_bank' && <QuestionBankPage />}
        {activeTab === 'saved_papers' && <SavedPapersPage />}
      </AppLayout>
    </AssessmentWorkspaceProvider>
  );
}

export default App;

