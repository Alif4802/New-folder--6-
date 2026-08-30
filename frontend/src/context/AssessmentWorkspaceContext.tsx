import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import {
  MCQCapabilitiesResponse,
  MCQGenerationResponse,
  MCQQuestion,
  MCQAnswerKeyItem,
} from '../types/api';
import { apiService } from '../services/api';

const SESSION_STORAGE_KEY = 'nctb_assessment_workspace_v1';

export interface PendingNewSetState {
  isGenerating: boolean;
  jobId: string | null;
  readyCount: number;
  requestedCount: number;
  questions: MCQQuestion[];
  answer_key: MCQAnswerKeyItem[];
  error: string | null;
  isComplete: boolean;
  status: string;
}

export interface AssessmentWorkspaceContextType {
  // Target Class / Grade & Textbook
  selectedGradeId: number | null;
  setSelectedGradeId: (gradeId: number | null) => void;
  selectedVersionId: string | null;
  setSelectedVersionId: (versionId: string | null, forceReset?: boolean) => void;
  capabilities: MCQCapabilitiesResponse | null;
  isLoadingCapabilities: boolean;
  capabilitiesError: string | null;

  // Selected curriculum scope configuration for NEXT generation
  selectedScopeNodeIds: Set<string>;
  setSelectedScopeNodeIds: (nodeIds: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  expandedNodeIds: Set<string>;
  setExpandedNodeIds: (nodeIds: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  questionCount: number;
  setQuestionCount: (count: number) => void;

  // Active Paper State (Immutable snapshot of generated paper)
  activePaper: MCQGenerationResponse | null;
  setActivePaper: (paper: MCQGenerationResponse | null | ((prev: MCQGenerationResponse | null) => MCQGenerationResponse | null)) => void;

  // Generation Job State
  activeJobId: string | null;
  jobStatus: string;
  jobStageMessage: string;
  isGenerating: boolean;
  generationError: string | null;
  previousJobId: string | null;

  // Pending New Set Generation State (Separated from Active Paper)
  pendingNewSet: PendingNewSetState | null;

  // Actions
  startGeneration: (isNewSet?: boolean) => Promise<void>;
  cancelGeneration: () => Promise<void>;
  retryRemaining: () => Promise<void>;
  applyPendingNewSet: () => void;
  dismissPendingNewSet: () => void;
  clearWorkspace: () => void;
}

const AssessmentWorkspaceContext = createContext<AssessmentWorkspaceContextType | undefined>(undefined);

export const AssessmentWorkspaceProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Try to load initial state from sessionStorage safely
  const getInitialState = () => {
    try {
      const saved = sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        return {
          gradeId: parsed.selectedGradeId ? Number(parsed.selectedGradeId) : null,
          versionId: parsed.selectedVersionId || null,
          scopeNodeIds: new Set<string>(parsed.selectedScopeNodeIds || []),
          expandedNodeIds: new Set<string>(parsed.expandedNodeIds || []),
          questionCount: parsed.questionCount || 5,
          activePaper: parsed.activePaper || null,
          activeJobId: parsed.activeJobId || null,
          previousJobId: parsed.previousJobId || null,
        };
      }
    } catch (e) {
      console.warn('Failed to load assessment workspace from sessionStorage:', e);
    }
    return {
      gradeId: null,
      versionId: null,
      scopeNodeIds: new Set<string>(),
      expandedNodeIds: new Set<string>(),
      questionCount: 5,
      activePaper: null,
      activeJobId: null,
      previousJobId: null,
    };
  };

  const initial = getInitialState();

  const [selectedGradeId, _setSelectedGradeId] = useState<number | null>(initial.gradeId);
  const [selectedVersionId, _setSelectedVersionId] = useState<string | null>(initial.versionId);
  const [capabilities, setCapabilities] = useState<MCQCapabilitiesResponse | null>(null);
  const [isLoadingCapabilities, setIsLoadingCapabilities] = useState<boolean>(false);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);

  const [selectedScopeNodeIds, setSelectedScopeNodeIds] = useState<Set<string>>(initial.scopeNodeIds);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(initial.expandedNodeIds);
  const [questionCount, setQuestionCount] = useState<number>(initial.questionCount);

  const [activePaper, setActivePaper] = useState<MCQGenerationResponse | null>(initial.activePaper);
  const [activeJobId, setActiveJobId] = useState<string | null>(initial.activeJobId);
  const [jobStatus, setJobStatus] = useState<string>('idle');
  const [jobStageMessage, setJobStageMessage] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [previousJobId, setPreviousJobId] = useState<string | null>(initial.previousJobId);

  const [pendingNewSet, setPendingNewSet] = useState<PendingNewSetState | null>(null);

  const pollTimerRef = useRef<number | null>(null);

  // Sync state to sessionStorage whenever key properties change
  useEffect(() => {
    try {
      const dataToSave = {
        selectedGradeId,
        selectedVersionId,
        selectedScopeNodeIds: Array.from(selectedScopeNodeIds),
        expandedNodeIds: Array.from(expandedNodeIds),
        questionCount,
        activePaper,
        activeJobId: isGenerating ? activeJobId : null,
        previousJobId,
      };
      sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(dataToSave));
    } catch (e) {
      console.warn('Failed to sync assessment workspace to sessionStorage:', e);
    }
  }, [selectedGradeId, selectedVersionId, selectedScopeNodeIds, expandedNodeIds, questionCount, activePaper, activeJobId, isGenerating, previousJobId]);

  // Load capabilities when selectedVersionId changes
  useEffect(() => {
    if (!selectedVersionId) {
      setCapabilities(null);
      setCapabilitiesError(null);
      return;
    }

    let isCancelled = false;
    setIsLoadingCapabilities(true);
    setCapabilitiesError(null);

    apiService.getMCQCapabilities(selectedVersionId).then((res) => {
      if (isCancelled) return;
      setIsLoadingCapabilities(false);
      if (res.ok && res.data) {
        setCapabilities(res.data);
        // Sync selectedGradeId to match the active textbook's authoritative grade
        if (res.data.grade_id && res.data.grade_id !== selectedGradeId) {
          _setSelectedGradeId(res.data.grade_id);
        }
      } else {
        setCapabilitiesError(res.error || 'Failed to load curriculum scopes.');
        if (res.error?.toLowerCase().includes('not found') || res.error?.includes('404')) {
          _setSelectedVersionId(null);
          setSelectedScopeNodeIds(new Set());
          setExpandedNodeIds(new Set());
        }
      }
    });

    return () => {
      isCancelled = true;
    };
  }, [selectedVersionId]);

  const setSelectedGradeId = (newGradeId: number | null) => {
    if (newGradeId === selectedGradeId) return;
    _setSelectedGradeId(newGradeId);

    // If active textbook does not belong to newly selected grade, clear textbook and scopes
    if (capabilities && capabilities.grade_id && newGradeId !== capabilities.grade_id) {
      _setSelectedVersionId(null);
      setSelectedScopeNodeIds(new Set());
      setExpandedNodeIds(new Set());
      setCapabilities(null);
      // NOTE: activePaper remains separate and immutable!
    }
  };

  const setSelectedVersionId = (newVersionId: string | null, forceReset: boolean = false) => {
    if (newVersionId === selectedVersionId && !forceReset) return;

    if (newVersionId !== selectedVersionId) {
      // Textbook changed: reset scopes cleanly
      setSelectedScopeNodeIds(new Set());
      setExpandedNodeIds(new Set());
      setActiveJobId(null);
      setPendingNewSet(null);
      setGenerationError(null);
      setPreviousJobId(null);
    }
    _setSelectedVersionId(newVersionId);
  };

  const startPollingJob = useCallback((jobId: string, isNewSet: boolean, targetCount?: number) => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
    }

    pollTimerRef.current = window.setInterval(async () => {
      const res = await apiService.getMCQJobStatus(jobId);
      if (!res.ok || !res.data) {
        return;
      }

      const data = res.data;
      setJobStatus(data.status);
      setJobStageMessage(data.stage_message || '');

      if (isNewSet) {
        setPendingNewSet({
          isGenerating: !data.complete,
          jobId: data.job_id,
          readyCount: data.generated_count,
          requestedCount: data.requested_count || targetCount || 5,
          questions: data.questions || [],
          answer_key: data.answer_key || [],
          error: data.error || null,
          isComplete: data.complete,
          status: data.status,
        });
      } else {
        if (data.questions && data.questions.length > 0) {
          setActivePaper({
            request_id: data.job_id,
            subject_version: {
              id: selectedVersionId || '',
              title: capabilities?.title || 'Textbook Assessment',
              subject: capabilities?.subject,
              grade: capabilities?.grade,
              grade_id: capabilities?.grade_id,
            },
            scope: {
              scope_node_ids: Array.from(selectedScopeNodeIds),
              scope_title: `${selectedScopeNodeIds.size} Section(s) Selected`,
            },
            requested_count: data.requested_count || targetCount || 5,
            generated_count: data.generated_count,
            questions: data.questions,
            answer_key: data.answer_key,
            warnings: data.warnings || [],
          });
        }
      }

      if (data.complete) {
        if (pollTimerRef.current) {
          clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
        setIsGenerating(false);

        if (isNewSet) {
          if (data.status === 'completed') {
            setPreviousJobId(jobId);
          }
        } else {
          if (data.status === 'completed') {
            setPreviousJobId(jobId);
          } else if (data.status === 'incomplete') {
            setGenerationError(`Generated ${data.generated_count} of ${data.requested_count} questions.`);
          } else if (data.status === 'failed') {
            setGenerationError(data.error || 'Generation failed.');
          }
        }
      }
    }, 1000);
  }, [selectedVersionId, capabilities, selectedScopeNodeIds]);

  // Resume active job polling on initial mount / remount if a job was running
  useEffect(() => {
    if (activeJobId && !pollTimerRef.current) {
      apiService.getMCQJobStatus(activeJobId).then((res) => {
        if (res.ok && res.data && !res.data.complete) {
          startPollingJob(activeJobId, false, res.data.requested_count);
        } else if (res.ok && res.data && res.data.complete) {
          setIsGenerating(false);
          setJobStatus(res.data.status);
          if (res.data.questions && res.data.questions.length > 0 && !activePaper) {
            setActivePaper({
              request_id: activeJobId,
              subject_version: {
                id: selectedVersionId || '',
                title: capabilities?.title || 'Textbook Assessment',
                subject: capabilities?.subject,
                grade: capabilities?.grade,
                grade_id: capabilities?.grade_id,
              },
              scope: {
                scope_node_ids: Array.from(selectedScopeNodeIds),
                scope_title: `${selectedScopeNodeIds.size} Section(s) Selected`,
              },
              requested_count: res.data.requested_count,
              generated_count: res.data.generated_count,
              questions: res.data.questions,
              answer_key: res.data.answer_key,
              warnings: res.data.warnings || [],
            });
          }
        }
      });
    }
  }, [activeJobId, startPollingJob, selectedVersionId, capabilities, selectedScopeNodeIds, activePaper]);

  // Clean up polling timer on unmount without cancelling backend job
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  const startGeneration = async (isNewSet: boolean = false) => {
    if (!selectedVersionId || selectedScopeNodeIds.size === 0) return;

    setIsGenerating(true);
    setGenerationError(null);
    setJobStatus('processing');
    setJobStageMessage('Starting assessment generation job...');

    const targetCount = questionCount;
    const reqScopeIds = Array.from(selectedScopeNodeIds);
    const prevJobRef = isNewSet ? (previousJobId || activeJobId) : null;

    if (isNewSet) {
      setPendingNewSet({
        isGenerating: true,
        jobId: null,
        readyCount: 0,
        requestedCount: targetCount,
        questions: [],
        answer_key: [],
        error: null,
        isComplete: false,
        status: 'processing',
      });
    } else {
      setActivePaper(null);
    }

    const res = await apiService.startMCQJob({
      subject_version_id: selectedVersionId,
      grade_id: selectedGradeId || undefined,
      scope_node_ids: reqScopeIds,
      count: targetCount,
      previous_job_id: prevJobRef || undefined,
      previous_request_id: prevJobRef || undefined,
    });

    if (!res.ok || !res.data) {
      setIsGenerating(false);
      setGenerationError(res.error || 'Failed to start generation job.');
      if (isNewSet) {
        setPendingNewSet(null);
      }
      return;
    }

    const newJobId = res.data.job_id;
    setActiveJobId(newJobId);
    if (isNewSet) {
      setPendingNewSet((prev) => (prev ? { ...prev, jobId: newJobId } : null));
    }
    startPollingJob(newJobId, isNewSet, targetCount);
  };

  const cancelGeneration = async () => {
    if (!activeJobId) return;
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    await apiService.cancelMCQJob(activeJobId);
    setIsGenerating(false);
    setJobStatus('cancelled');
    setJobStageMessage('Generation cancelled.');
    if (pendingNewSet) {
      setPendingNewSet(null);
    }
  };

  const retryRemaining = async () => {
    if (!activeJobId) return;
    setIsGenerating(true);
    setJobStatus('processing');
    setGenerationError(null);
    setJobStageMessage('Resuming generation for remaining questions...');

    const res = await apiService.retryMCQJob(activeJobId);
    if (!res.ok || !res.data) {
      setIsGenerating(false);
      setGenerationError(res.error || 'Failed to resume generation.');
      return;
    }

    const continuationJobId = res.data.job_id;
    setActiveJobId(continuationJobId);
    startPollingJob(continuationJobId, false);
  };

  const applyPendingNewSet = () => {
    if (!pendingNewSet || pendingNewSet.questions.length === 0) return;
    setActivePaper({
      request_id: pendingNewSet.jobId || `new_set_${Date.now()}`,
      subject_version: {
        id: selectedVersionId || '',
        title: capabilities?.title || 'Textbook Assessment',
        subject: capabilities?.subject,
        grade: capabilities?.grade,
        grade_id: capabilities?.grade_id,
      },
      scope: {
        scope_node_ids: Array.from(selectedScopeNodeIds),
        scope_title: `${selectedScopeNodeIds.size} Section(s) Selected`,
      },
      requested_count: pendingNewSet.requestedCount,
      generated_count: pendingNewSet.readyCount,
      questions: pendingNewSet.questions,
      answer_key: pendingNewSet.answer_key,
      warnings: [],
    });
    setPendingNewSet(null);
  };

  const dismissPendingNewSet = () => {
    setPendingNewSet(null);
  };

  const clearWorkspace = () => {
    _setSelectedGradeId(null);
    _setSelectedVersionId(null);
    setSelectedScopeNodeIds(new Set());
    setExpandedNodeIds(new Set());
    setActivePaper(null);
    setActiveJobId(null);
    setPendingNewSet(null);
    setGenerationError(null);
    setPreviousJobId(null);
  };

  return (
    <AssessmentWorkspaceContext.Provider
      value={{
        selectedGradeId,
        setSelectedGradeId,
        selectedVersionId,
        setSelectedVersionId,
        capabilities,
        isLoadingCapabilities,
        capabilitiesError,
        selectedScopeNodeIds,
        setSelectedScopeNodeIds,
        expandedNodeIds,
        setExpandedNodeIds,
        questionCount,
        setQuestionCount,
        activePaper,
        setActivePaper,
        activeJobId,
        jobStatus,
        jobStageMessage,
        isGenerating,
        generationError,
        previousJobId,
        pendingNewSet,
        startGeneration,
        cancelGeneration,
        retryRemaining,
        applyPendingNewSet,
        dismissPendingNewSet,
        clearWorkspace,
      }}
    >
      {children}
    </AssessmentWorkspaceContext.Provider>
  );
};

export const useAssessmentWorkspace = (): AssessmentWorkspaceContextType => {
  const context = useContext(AssessmentWorkspaceContext);
  if (!context) {
    throw new Error('useAssessmentWorkspace must be used within an AssessmentWorkspaceProvider');
  }
  return context;
};
