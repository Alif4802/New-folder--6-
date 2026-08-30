import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Sparkles,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Eye,
  EyeOff,
  Layers,
  Shuffle,
  XCircle,
  RotateCw,
  Printer,
  Save,
  BookPlus,
} from 'lucide-react';
import { apiService } from '../services/api';
import { questionBankApi } from '../services/questionBankApi';
import { buildTreeMaps, getEffectiveTopLevelScopeCount } from '../utils/treeSelection';
import {
  GradeResponse,
  TextbookVersionSummary,
  MCQGenerationResponse,
  MCQQuestion,
  MCQAnswerKeyItem,
  MCQOption,
} from '../types/api';
import { MathRenderer } from '../components/MathRenderer';
import { PaperPrintView } from '../components/question_bank/PaperPrintView';
import { PaperComposer } from '../components/question_bank/PaperComposer';
import { CurriculumScopeTree } from '../components/CurriculumScopeTree';
import { useAssessmentWorkspace } from '../context/AssessmentWorkspaceContext';

interface AssessmentGeneratorPageProps {
  selectedVersionId?: string | null;
  onClearSelectedVersion?: () => void;
}

// Pure helper: Fisher-Yates array shuffle
function shuffleArray<T>(array: T[]): T[] {
  const arr = [...array];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// Pure helper: instant zero-LLM assessment paper randomizer
function randomizeAssessmentPaper(data: MCQGenerationResponse): MCQGenerationResponse {
  if (!data || !data.questions || data.questions.length === 0) return data;

  const displayLabels = ['A', 'B', 'C', 'D'];
  const shuffledQuestions = shuffleArray(data.questions);

  const newQuestions: MCQQuestion[] = [];
  const newAnswerKey: MCQAnswerKeyItem[] = [];

  shuffledQuestions.forEach((q, qIdx) => {
    const qNum = qIdx + 1;
    const origAk = data.answer_key.find(
      (ak) => ak.question_number === q.question_number || (ak.question_id && ak.question_id === q.id)
    );
    const targetCorrectText = origAk?.correct_text || '';
    const targetCorrectId = q.correct_option_id;

    const shuffledOptions = shuffleArray(q.options);
    const newOptions: MCQOption[] = [];
    let newCorrectLetter = 'A';
    let newCorrectText = '';
    let newCorrectLatex: string | null = null;

    shuffledOptions.slice(0, 4).forEach((opt, optIdx) => {
      const lbl = displayLabels[optIdx];
      newOptions.push({
        id: opt.id,
        label: lbl,
        text: opt.text,
        latex: opt.latex,
      });

      let isCorrect = false;
      if (targetCorrectId && opt.id && opt.id === targetCorrectId) {
        isCorrect = true;
      } else if (targetCorrectText && opt.text.trim().toLowerCase() === targetCorrectText.trim().toLowerCase()) {
        isCorrect = true;
      }

      if (isCorrect) {
        newCorrectLetter = lbl;
        newCorrectText = opt.text;
        newCorrectLatex = opt.latex || null;
      }
    });

    newQuestions.push({
      ...q,
      id: q.id,
      question_number: qNum,
      options: newOptions,
      correct_option_id: targetCorrectId,
    });

    newAnswerKey.push({
      question_number: qNum,
      question_id: q.id,
      correct_letter: newCorrectLetter,
      correct_text: newCorrectText,
      correct_latex: newCorrectLatex,
      explanation: origAk?.explanation || q.explanation || '',
    });
  });

  return {
    ...data,
    questions: newQuestions,
    answer_key: newAnswerKey,
  };
}

// Format human-friendly error messages
function formatTeacherErrorMessage(errorStr: string | null): string {
  if (!errorStr) return '';
  if (errorStr.includes('INSUFFICIENT_UNIQUE_SOURCE_COVERAGE')) {
    return 'Only a limited number of unique grounded questions could be produced from the selected sections. Please expand your curriculum coverage or request fewer questions.';
  }
  if (errorStr.includes('LLM_NOT_CONFIGURED')) {
    return 'The AI generation provider is not configured. Please ensure your API key is provided.';
  }
  if (errorStr.includes('GRADE_MISMATCH')) {
    return 'The selected textbook does not belong to the selected Class / Grade. Please re-select the textbook.';
  }
  if (errorStr.includes('LLM_TEMPORARILY_UNAVAILABLE') || errorStr.toLowerCase().includes('all llm providers')) {
    return 'All AI generation providers are temporarily unavailable. Please retry in a few moments.';
  }
  return errorStr;
}

export const AssessmentGeneratorPage: React.FC<AssessmentGeneratorPageProps> = ({
  selectedVersionId: propSelectedVersionId,
  onClearSelectedVersion,
}) => {
  // Access global Assessment Workspace Context (survives tab navigation)
  const {
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
    pendingNewSet,
    startGeneration,
    cancelGeneration,
    retryRemaining,
    applyPendingNewSet,
    dismissPendingNewSet,
  } = useAssessmentWorkspace();

  // Local UI State
  const [availableGrades, setAvailableGrades] = useState<GradeResponse[]>([]);
  const [loadingGrades, setLoadingGrades] = useState<boolean>(false);
  const [textbooks, setTextbooks] = useState<TextbookVersionSummary[]>([]);
  const [loadingFilteredTextbooks, setLoadingFilteredTextbooks] = useState<boolean>(false);
  const [randomizeToast, setRandomizeToast] = useState<string | null>(null);
  const [showAnswerKey, setShowAnswerKey] = useState<boolean>(false);
  const [isSavingToBank, setIsSavingToBank] = useState<boolean>(false);
  const [bankSaveFeedback, setBankSaveFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isPrintViewing, setIsPrintViewing] = useState<boolean>(false);
  const [isComposing, setIsComposing] = useState<boolean>(false);

  const fetchAvailableGrades = useCallback(async () => {
    setLoadingGrades(true);
    const res = await apiService.getGrades({ onlyWithTextbooks: true });
    setLoadingGrades(false);
    if (res.ok && res.data) {
      setAvailableGrades(res.data);
    }
  }, []);

  // Load available grades on mount / tab activation
  useEffect(() => {
    fetchAvailableGrades();
  }, [fetchAvailableGrades]);

  // Re-sync available grades if selectedGradeId is set from handoff but not present in cached list
  useEffect(() => {
    if (selectedGradeId && availableGrades.length > 0 && !availableGrades.some((g) => g.id === selectedGradeId)) {
      fetchAvailableGrades();
    }
  }, [selectedGradeId, availableGrades, fetchAvailableGrades]);

  // Dynamically load textbooks whenever selectedGradeId changes
  useEffect(() => {
    let isCancelled = false;
    if (!selectedGradeId) {
      setTextbooks([]);
      return;
    }

    setLoadingFilteredTextbooks(true);
    apiService.getTextbookVersions({ gradeId: selectedGradeId, assessmentEligibleOnly: true }).then((res) => {
      if (!isCancelled) {
        setLoadingFilteredTextbooks(false);
        if (res.ok && res.data) {
          setTextbooks(res.data);
        }
      }
    });
    return () => {
      isCancelled = true;
    };
  }, [selectedGradeId]);

  // Sync propSelectedVersionId if provided from handoff
  useEffect(() => {
    if (propSelectedVersionId && propSelectedVersionId !== selectedVersionId) {
      setSelectedVersionId(propSelectedVersionId);
    }
  }, [propSelectedVersionId, selectedVersionId, setSelectedVersionId]);

  // Precompute tree lookup maps for hierarchical cascade & effective count
  const treeMaps = useMemo(() => {
    return capabilities?.scope_tree ? buildTreeMaps(capabilities.scope_tree) : null;
  }, [capabilities?.scope_tree]);

  const effectiveSelectedCount = useMemo(() => {
    if (!treeMaps) return selectedScopeNodeIds.size;
    return getEffectiveTopLevelScopeCount(selectedScopeNodeIds, treeMaps);
  }, [selectedScopeNodeIds, treeMaps]);

  // Handle tree checkbox toggle with cascade support
  const handleToggleNodeSelect = (nodeId: string, nextSelected?: Set<string>) => {
    if (nextSelected) {
      setSelectedScopeNodeIds(nextSelected);
    } else {
      setSelectedScopeNodeIds((prev) => {
        const next = new Set(prev);
        if (next.has(nodeId)) {
          next.delete(nodeId);
        } else {
          next.add(nodeId);
        }
        return next;
      });
    }
  };

  // Handle tree expand toggle
  const handleToggleExpand = (nodeId: string) => {
    setExpandedNodeIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (!capabilities?.scope_tree) return;
    if (treeMaps) {
      setSelectedScopeNodeIds(new Set(treeMaps.allNodeIds));
    } else {
      const allIds = new Set<string>();
      const traverse = (nodes: any[]) => {
        nodes.forEach((n) => {
          allIds.add(n.id);
          if (n.children) traverse(n.children);
        });
      };
      traverse(capabilities.scope_tree);
      setSelectedScopeNodeIds(allIds);
    }
  };

  const handleClearSelection = () => {
    setSelectedScopeNodeIds(new Set());
  };

  const handleExpandAll = () => {
    if (!capabilities?.scope_tree) return;
    const allIds = new Set<string>();
    const traverse = (nodes: any[]) => {
      nodes.forEach((n) => {
        allIds.add(n.id);
        if (n.children) traverse(n.children);
      });
    };
    traverse(capabilities.scope_tree);
    setExpandedNodeIds(allIds);
  };

  const handleCollapseAll = () => {
    setExpandedNodeIds(new Set());
  };

  // Check if live scope differs from active paper snapshot
  const isScopeModified = useMemo(() => {
    if (!activePaper?.scope?.scope_node_ids) return false;
    const paperSet = new Set(activePaper.scope.scope_node_ids);
    if (paperSet.size !== selectedScopeNodeIds.size) return true;
    for (const id of selectedScopeNodeIds) {
      if (!paperSet.has(id)) return true;
    }
    return false;
  }, [activePaper, selectedScopeNodeIds]);

  // Instant Zero-LLM Randomizer
  const handleRandomizePaper = () => {
    if (!activePaper || isGenerating) return;
    const randomized = randomizeAssessmentPaper(activePaper);
    setActivePaper(randomized);

    setRandomizeToast('Paper randomized (0 AI calls)');
    setTimeout(() => {
      setRandomizeToast(null);
    }, 2500);
  };

  // Save questions to bank
  const handleSaveQuestionsToBank = async () => {
    const targetJobId = activeJobId || activePaper?.request_id;
    if (!targetJobId) {
      setBankSaveFeedback({ type: 'error', text: 'No active generation job reference found.' });
      return;
    }
    setIsSavingToBank(true);
    setBankSaveFeedback(null);
    const res = await questionBankApi.saveGeneratedQuestions(targetJobId);
    setIsSavingToBank(false);

    if (res.ok && res.data) {
      setBankSaveFeedback({ type: 'success', text: res.data.message });
    } else {
      setBankSaveFeedback({ type: 'error', text: res.error || 'Failed to save questions to bank.' });
    }
  };

  // Dedicated Print Preview Surface
  if (isPrintViewing && activePaper) {
    return (
      <PaperPrintView
        paperTitle={activePaper.subject_version.title}
        metadata={{
          institution_name: '',
          exam_title: `${activePaper.subject_version.title} Assessment`,
          subject_name: activePaper.subject_version.subject || '',
          grade_name: activePaper.subject_version.grade || '',
          duration_minutes: 30,
          total_marks: activePaper.questions.length,
          instructions: 'Choose the best answer for each question. All questions carry equal marks.',
        }}
        questions={activePaper.questions}
        answerKey={activePaper.answer_key}
        onBack={() => setIsPrintViewing(false)}
      />
    );
  }

  // Dedicated Paper Composer Surface
  if (isComposing && activePaper) {
    return (
      <PaperComposer
        initialSubjectVersionId={activePaper.subject_version.id}
        initialTitle={`${activePaper.subject_version.title} MCQ Paper`}
        initialMetadata={{
          institution_name: '',
          exam_title: `${activePaper.subject_version.title} MCQ Paper`,
          subject_name: activePaper.subject_version.subject || '',
          grade_name: activePaper.subject_version.grade || '',
          duration_minutes: 30,
          total_marks: activePaper.questions.length,
          instructions: 'Choose the best answer for each question. All questions carry equal marks.',
        }}
        initialQuestions={activePaper.questions}
        initialAnswerKey={activePaper.answer_key}
        jobId={activeJobId || activePaper.request_id}
        scopeNodeIds={activePaper.scope.scope_node_ids}
        onBack={() => setIsComposing(false)}
        onSavedSuccess={() => setIsComposing(false)}
      />
    );
  }

  const minCount = capabilities?.min_question_count || 1;
  const maxCount = capabilities?.max_total_questions || capabilities?.max_question_count || null;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-lms-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-lms-blue-600" />
              <span>MCQ Assessment Generator</span>
            </h1>
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-blue-100 text-lms-blue-800 border border-blue-200">
              Source-Grounded AI
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Generate verifiable multiple-choice questions grounded directly in textbook chapters and sections.
          </p>
        </div>

        {/* Global Toast for Instant Randomize */}
        {randomizeToast && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold shadow-md animate-fade-in">
            <CheckCircle2 className="w-4 h-4" />
            <span>{randomizeToast}</span>
          </div>
        )}
      </div>

      {/* Main Configuration Card */}
      <div className="bg-white border border-lms-border rounded-xl shadow-sm p-6 space-y-6">
        {/* Dynamic Class/Grade & Target Textbook Dual Selectors */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="grade-select" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
              Class / Grade
            </label>
            <select
              id="grade-select"
              value={selectedGradeId || ''}
              onChange={(e) => {
                const val = e.target.value ? Number(e.target.value) : null;
                setSelectedGradeId(val);
              }}
              disabled={isGenerating || loadingGrades}
              className="w-full text-xs font-medium bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-800 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none transition-colors"
            >
              <option value="">
                {loadingGrades ? 'Loading grades...' : '-- Choose Class / Grade --'}
              </option>
              {availableGrades.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.display_name || g.name} ({g.textbook_count} {g.textbook_count === 1 ? 'book' : 'books'})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="textbook-select" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
              Target Textbook
            </label>
            <select
              id="textbook-select"
              value={selectedVersionId || ''}
              onChange={(e) => {
                const newId = e.target.value || null;
                setSelectedVersionId(newId);
                if (onClearSelectedVersion && !newId) onClearSelectedVersion();
              }}
              disabled={isGenerating || !selectedGradeId || loadingFilteredTextbooks}
              className="w-full text-xs font-medium bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-800 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none transition-colors disabled:opacity-60"
            >
              <option value="">
                {!selectedGradeId
                  ? '-- First Select a Class / Grade --'
                  : loadingFilteredTextbooks
                  ? 'Loading textbooks...'
                  : '-- Choose an Ingested Textbook --'}
              </option>
              {textbooks.map((tb) => (
                <option key={tb.id} value={tb.id}>
                  {tb.title} ({tb.page_count} pages)
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Empty grade notification if no textbooks exist for this grade */}
        {selectedGradeId && !loadingFilteredTextbooks && textbooks.length === 0 && (
          <div className="p-3 bg-amber-50 rounded-lg border border-amber-200 text-amber-800 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span>No ingested textbooks are available for this class/grade. Please ingest a textbook in Textbook Intelligence.</span>
          </div>
        )}

        {/* Capabilities Loading / Error */}
        {isLoadingCapabilities && (
          <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 text-slate-600 text-xs flex items-center gap-3">
            <RefreshCw className="w-4 h-4 animate-spin text-lms-blue-600 flex-shrink-0" />
            <span>Loading curriculum hierarchy...</span>
          </div>
        )}

        {capabilitiesError && (
          <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-800 text-xs flex items-center gap-3">
            <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0" />
            <span>{capabilitiesError}</span>
          </div>
        )}

        {/* Multi-Scope Selection Area */}
        {capabilities && !isLoadingCapabilities && (
          <div className="space-y-4 pt-2 border-t border-slate-100">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Curriculum Coverage ({effectiveSelectedCount} {effectiveSelectedCount === 1 ? 'scope' : 'scopes'} selected)
                </label>
                <p className="text-[11px] text-slate-500">
                  Select one or multiple chapters, units, or sections to bound the source context.
                </p>
              </div>

              {/* Tree Actions Toolbar */}
              <div className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  onClick={handleSelectAll}
                  disabled={isGenerating}
                  className="px-2.5 py-1 text-slate-600 hover:text-lms-blue-700 hover:bg-slate-100 rounded font-medium transition-colors"
                >
                  Select All
                </button>
                <span className="text-slate-300">|</span>
                <button
                  type="button"
                  onClick={handleClearSelection}
                  disabled={isGenerating}
                  className="px-2.5 py-1 text-slate-600 hover:text-red-700 hover:bg-slate-100 rounded font-medium transition-colors"
                >
                  Clear Selection
                </button>
                <span className="text-slate-300">|</span>
                <button
                  type="button"
                  onClick={handleExpandAll}
                  disabled={isGenerating}
                  className="px-2 py-1 text-slate-500 hover:text-slate-800 rounded transition-colors"
                  title="Expand All"
                >
                  Expand
                </button>
                <button
                  type="button"
                  onClick={handleCollapseAll}
                  disabled={isGenerating}
                  className="px-2 py-1 text-slate-500 hover:text-slate-800 rounded transition-colors"
                  title="Collapse All"
                >
                  Collapse
                </button>
              </div>
            </div>

            {/* Canonical Curriculum Scope Tree */}
            <div className="border border-slate-200 rounded-lg p-3 bg-slate-50/50 max-h-72 overflow-y-auto space-y-1">
              <CurriculumScopeTree
                nodes={capabilities.scope_tree}
                mode="checkbox"
                selectedNodeIds={selectedScopeNodeIds}
                onToggleNodeSelect={handleToggleNodeSelect}
                expandedNodeIds={expandedNodeIds}
                onToggleExpand={handleToggleExpand}
              />
            </div>
          </div>
        )}

        {/* Count Selector & Primary Generate Button */}
        {capabilities && !isLoadingCapabilities && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-4 border-t border-slate-100">
            <div className="flex items-center gap-3">
              <label htmlFor="question-count-input" className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                Question Count:
              </label>
              <div className="flex items-center gap-1.5">
                {[5, 10, 15, 20].map((num) => (
                  <button
                    key={num}
                    type="button"
                    disabled={isGenerating}
                    onClick={() => setQuestionCount(num)}
                    className={`text-xs px-2.5 py-1.5 rounded-md font-semibold border transition-all ${
                      questionCount === num
                        ? 'bg-lms-blue-600 text-white border-lms-blue-600 shadow-2xs'
                        : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    {num}
                  </button>
                ))}
              </div>
              <input
                id="question-count-input"
                type="number"
                min={minCount}
                max={maxCount || 100}
                value={questionCount}
                disabled={isGenerating}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  const safeVal = Math.max(minCount, maxCount ? Math.min(maxCount, val) : val);
                  setQuestionCount(safeVal);
                }}
                className="w-16 text-xs text-center font-bold bg-slate-50 border border-slate-300 rounded-md py-1 px-1 text-slate-800 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
              />
              <span className="text-[11px] text-slate-400 font-medium">
                {maxCount ? `(Max ${maxCount})` : '(Dynamic Batching)'}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {isGenerating ? (
                <button
                  id="cancel-generation-button"
                  type="button"
                  onClick={cancelGeneration}
                  className="inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold text-xs shadow-sm transition-all"
                >
                  <XCircle className="w-4 h-4" />
                  <span>Cancel Generation</span>
                </button>
              ) : (
                <button
                  id="generate-mcqs-button"
                  type="button"
                  disabled={!capabilities.llm_configured || selectedScopeNodeIds.size === 0 || !selectedVersionId}
                  onClick={() => startGeneration(false)}
                  className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-lms-blue-600 hover:bg-lms-blue-700 text-white font-semibold text-xs shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>Generate {questionCount} MCQs</span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Generation Error Alert */}
      {generationError && (
        <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-3 shadow-2xs">
          <AlertCircle className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <h4 className="font-bold text-sm">Assessment Generation Notice</h4>
            <p className="mt-1 text-amber-800 leading-relaxed">
              {formatTeacherErrorMessage(generationError)}
            </p>
            {jobStatus === 'incomplete' && (
              <button
                onClick={retryRemaining}
                className="mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded bg-amber-200 text-amber-900 font-semibold hover:bg-amber-300 transition-colors"
              >
                <RotateCw className="w-3.5 h-3.5" />
                <span>Retry Remaining Questions</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Progressive Generation Progress Banner (Shown while generating first paper from scratch) */}
      {isGenerating && !pendingNewSet && (
        <div className="p-5 rounded-xl bg-blue-50/80 border border-blue-200 text-slate-800 space-y-3 shadow-sm animate-pulse">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <RefreshCw className="w-5 h-5 animate-spin text-lms-blue-600" />
              <h4 className="text-sm font-bold text-slate-900">
                {jobStageMessage || 'Generating Assessment...'}
              </h4>
            </div>
          </div>
          <div className="w-full bg-blue-200/60 rounded-full h-2 overflow-hidden">
            <div
              className="bg-lms-blue-600 h-2 rounded-full transition-all duration-500"
              style={{
                width: `${Math.max(10, Math.min(100, ((activePaper?.generated_count || 0) / questionCount) * 100))}%`,
              }}
            />
          </div>
          <p className="text-[11px] text-slate-500">
            Validated questions are rendered progressively below as each batch finishes pedagogical verification.
          </p>
        </div>
      )}

      {/* Pending New Set Banner (Visible while Set A remains on screen) */}
      {pendingNewSet && (
        <div className="p-4 rounded-xl bg-blue-50 border border-blue-200 text-slate-900 shadow-sm flex items-center justify-between">
          <div className="flex items-center gap-3">
            {pendingNewSet.isGenerating ? (
              <RefreshCw className="w-5 h-5 animate-spin text-lms-blue-600 flex-shrink-0" />
            ) : (
              <Sparkles className="w-5 h-5 text-lms-blue-600 flex-shrink-0" />
            )}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-lms-blue-900">
                {pendingNewSet.isGenerating ? 'Generating New Question Set...' : 'New Question Set Ready'}
              </h4>
              <p className="text-xs text-slate-600 mt-0.5">
                {pendingNewSet.readyCount} of {pendingNewSet.requestedCount} fresh questions verified. Your current paper remains active below.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {pendingNewSet.isGenerating ? (
              <button
                onClick={cancelGeneration}
                className="text-xs text-red-600 hover:text-red-800 font-semibold px-3 py-1.5 rounded border border-red-200 bg-white"
              >
                Cancel
              </button>
            ) : (
              <>
                <button
                  onClick={applyPendingNewSet}
                  className="text-xs font-semibold px-3 py-1.5 rounded bg-lms-blue-600 text-white hover:bg-lms-blue-700 shadow-xs"
                >
                  Apply New Set
                </button>
                <button
                  onClick={dismissPendingNewSet}
                  className="text-xs font-semibold px-3 py-1.5 rounded bg-white text-slate-700 border border-slate-300 hover:bg-slate-50"
                >
                  Keep Current Set
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Generated Paper Workspace (Immutable scope snapshot) */}
      {activePaper && activePaper.questions && activePaper.questions.length > 0 && (
        <div
          id="generated-assessment-paper"
          className="bg-white border border-lms-border rounded-xl shadow-sm overflow-hidden"
        >
          {/* Paper Top Toolbar */}
          <div className="p-5 bg-slate-50 border-b border-lms-border flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-blue-100 text-lms-blue-800 font-mono">
                  MCQ Question Paper
                </span>
                <span className="text-xs text-slate-600 font-semibold">
                  {activePaper.generated_count} of {activePaper.requested_count} Questions Ready
                </span>
              </div>
              <h3 className="text-base font-bold text-slate-900 mt-1">
                {activePaper.subject_version.title}
              </h3>
              <p className="text-xs text-slate-600 mt-0.5 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-lms-blue-600 flex-shrink-0" />
                <span className="font-semibold text-slate-700">{activePaper.scope.scope_title}</span>
                {isScopeModified && (
                  <span className="text-[10px] text-amber-600 font-medium italic">
                    (Current checkbox selection differs from this paper's generation scope)
                  </span>
                )}
              </p>
            </div>

            {/* SIX ACTIONS: Show Answer Key | Randomize Paper | Save to Bank | Save Paper | Print / Save PDF | Generate New Set */}
            <div className="flex items-center flex-wrap gap-2">
              <button
                id="toggle-answer-key-button"
                type="button"
                onClick={() => setShowAnswerKey(!showAnswerKey)}
                className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                  showAnswerKey
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                    : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {showAnswerKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                <span>{showAnswerKey ? 'Hide Answer Key' : 'Show Answer Key'}</span>
              </button>

              <button
                id="randomize-paper-button"
                type="button"
                disabled={isGenerating}
                onClick={handleRandomizePaper}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
                title="Instantly shuffles question sequence and ABCD option labels (0 AI calls)"
              >
                <Shuffle className="w-3.5 h-3.5 text-lms-blue-600" />
                <span>Randomize Paper</span>
              </button>

              <button
                id="save-questions-to-bank-button"
                type="button"
                disabled={isSavingToBank || isGenerating}
                onClick={handleSaveQuestionsToBank}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
                title="Save verified questions to the persistent Question Bank"
              >
                {isSavingToBank ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-lms-blue-600" />
                ) : (
                  <BookPlus className="w-3.5 h-3.5 text-lms-blue-600" />
                )}
                <span>Save to Bank</span>
              </button>

              <button
                id="save-paper-button"
                type="button"
                disabled={isGenerating}
                onClick={() => setIsComposing(true)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
                title="Open Paper Composer to edit header and save this paper arrangement"
              >
                <Save className="w-3.5 h-3.5 text-lms-blue-600" />
                <span>Save Paper</span>
              </button>

              <button
                id="print-save-pdf-button"
                type="button"
                disabled={isGenerating}
                onClick={() => setIsPrintViewing(true)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
                title="Open clean print preview and browser Print / Save as PDF"
              >
                <Printer className="w-3.5 h-3.5" />
                <span>Print / Save PDF</span>
              </button>

              <button
                id="generate-new-set-button"
                type="button"
                disabled={isGenerating}
                onClick={() => startGeneration(true)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-lms-blue-600 text-white hover:bg-lms-blue-700 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
                title="Generate a completely new set of questions using LLM"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Generate New Set</span>
              </button>
            </div>
          </div>

          {/* Bank Save Feedback Alert */}
          {bankSaveFeedback && (
            <div
              className={`mx-5 mt-4 p-3 rounded-lg text-xs font-medium flex items-center justify-between ${
                bankSaveFeedback.type === 'success'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                  : 'bg-rose-50 text-rose-800 border border-rose-200'
              }`}
            >
              <span>{bankSaveFeedback.text}</span>
              <button
                onClick={() => setBankSaveFeedback(null)}
                className="text-slate-400 hover:text-slate-700 font-bold px-1"
              >
                ×
              </button>
            </div>
          )}

          {/* Question Items List */}
          <div className="p-6 space-y-8 divide-y divide-slate-100">
            {activePaper.questions.map((q) => (
              <div key={q.question_number} className="pt-6 first:pt-0 space-y-3.5">
                {/* Question Stem */}
                <div className="flex items-start gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-slate-100 text-slate-800 font-bold text-xs flex items-center justify-center border border-slate-200">
                    {q.question_number}
                  </span>
                  <div className="text-sm font-semibold text-slate-900 leading-relaxed pt-0.5">
                    <MathRenderer rawText={q.question_text} latex={q.question_latex} inline={true} />
                  </div>
                </div>

                {/* 4 Options Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pl-9">
                  {q.options.map((opt) => (
                    <div
                      key={opt.label}
                      className="flex items-center gap-2.5 p-3 rounded-lg border border-slate-200 bg-slate-50/50 hover:bg-slate-50 text-xs font-medium text-slate-800 transition-colors"
                    >
                      <span className="w-5 h-5 rounded font-bold text-[11px] bg-white border border-slate-300 text-slate-700 flex items-center justify-center flex-shrink-0">
                        {opt.label}
                      </span>
                      <div className="flex-1">
                        <MathRenderer rawText={opt.text} latex={opt.latex} inline={true} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Collapsible Answer Key Section (Answers ONLY, Zero Explanations) */}
          {showAnswerKey && (
            <div
              id="answer-key-section"
              className="m-6 p-6 rounded-xl bg-emerald-50/70 border border-emerald-200 space-y-4"
            >
              <div className="flex items-center justify-between border-b border-emerald-200 pb-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <h4 className="text-sm font-bold text-emerald-950">
                    Answer Key
                  </h4>
                </div>
                <span className="text-[11px] font-semibold text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded">
                  Answers Only
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {activePaper.answer_key.map((ak) => (
                  <div
                    key={ak.question_number}
                    className="p-2.5 rounded-lg bg-white/80 border border-emerald-200/80 flex items-center gap-2.5 text-xs shadow-2xs"
                  >
                    <span className="font-bold text-emerald-950 w-7 text-right">Q{ak.question_number}:</span>
                    <span className="font-bold px-2 py-0.5 rounded bg-emerald-600 text-white text-[11px] flex-shrink-0">
                      Option {ak.correct_letter}
                    </span>
                    <span className="font-semibold text-slate-800 truncate flex-1">
                      <MathRenderer rawText={ak.correct_text} latex={ak.correct_latex} inline={true} />
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bottom Action Footer */}
          <div className="p-4 bg-slate-50 border-t border-lms-border flex items-center justify-between">
            <span className="text-xs text-slate-500">
              Ephemeral question set • Grounded in {capabilities?.subject || 'textbook'} source
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={isGenerating}
                onClick={handleRandomizePaper}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-700 hover:bg-slate-100 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
              >
                <Shuffle className="w-3.5 h-3.5 text-lms-blue-600" />
                <span>Randomize Paper</span>
              </button>
              <button
                type="button"
                disabled={isGenerating}
                onClick={() => startGeneration(true)}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-lms-blue-600 text-white hover:bg-lms-blue-700 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Generate New Set</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
