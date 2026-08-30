import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/api';
import { questionBankApi } from '../services/questionBankApi';
import {
  TextbookVersionSummary,
  CurriculumScopeNode,
} from '../types/api';
import {
  QuestionBankItem,
  PaperItemQuestion,
  PaperAnswerKeyItem,
} from '../types/question_bank';
import { QuestionBankOrganizer } from '../components/question_bank/QuestionBankOrganizer';
import { QuestionStream } from '../components/question_bank/QuestionStream';
import { QuestionInspector } from '../components/question_bank/QuestionInspector';
import { PaperComposer } from '../components/question_bank/PaperComposer';
import { useAssessmentWorkspace } from '../context/AssessmentWorkspaceContext';

export const QuestionBankPage: React.FC = () => {
  const workspace = useAssessmentWorkspace();
  const [textbooks, setTextbooks] = useState<TextbookVersionSummary[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>(workspace.selectedVersionId || '');
  const [scopeTree, setScopeTree] = useState<CurriculumScopeNode[]>([]);
  const [selectedScopeNodeId, setSelectedScopeNodeId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('ACTIVE');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [questions, setQuestions] = useState<QuestionBankItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize] = useState<number>(15);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const [selectedQuestionIds, setSelectedQuestionIds] = useState<Set<string>>(new Set());
  const [inspectingQuestion, setInspectingQuestion] = useState<QuestionBankItem | null>(null);

  // Composer state
  const [isComposing, setIsComposing] = useState<boolean>(false);
  const [composerQuestions, setComposerQuestions] = useState<PaperItemQuestion[]>([]);
  const [composerAnswerKey, setComposerAnswerKey] = useState<PaperAnswerKeyItem[]>([]);

  // 1. Fetch available textbooks on load
  useEffect(() => {
    async function loadTextbooks() {
      const res = await apiService.getTextbookVersions();
      if (res.ok && res.data && res.data.length > 0) {
        setTextbooks(res.data);
        // Prefer active workspace selectedVersionId if present in list, otherwise first item
        const preferredId = (workspace.selectedVersionId && res.data.some(d => d.id === workspace.selectedVersionId))
          ? workspace.selectedVersionId
          : res.data[0].id;
        setSelectedVersionId(preferredId);
      }
    }
    loadTextbooks();
  }, [workspace.selectedVersionId]);

  // 2. Fetch capabilities / scope tree when selected version changes
  useEffect(() => {
    async function loadCapabilities() {
      if (!selectedVersionId) return;
      const res = await apiService.getMCQCapabilities(selectedVersionId);
      if (res.ok && res.data) {
        setScopeTree(res.data.scope_tree || []);
      }
    }
    loadCapabilities();
  }, [selectedVersionId]);

  // 3. Fetch questions with filters
  const fetchQuestions = useCallback(async () => {
    if (!selectedVersionId) return;
    setIsLoading(true);
    const res = await questionBankApi.listQuestions({
      subject_version_id: selectedVersionId,
      scope_node_id: selectedScopeNodeId || undefined,
      status: statusFilter,
      search: searchQuery || undefined,
      page: currentPage,
      page_size: pageSize,
    });
    setIsLoading(false);

    if (res.ok && res.data) {
      setQuestions(res.data.items);
      setTotalCount(res.data.total_count);
      setTotalPages(res.data.total_pages);
      if (res.data.items.length > 0 && !inspectingQuestion) {
        setInspectingQuestion(res.data.items[0]);
      }
    }
  }, [selectedVersionId, selectedScopeNodeId, statusFilter, searchQuery, currentPage, pageSize]);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  const handleToggleSelectQuestion = (questionId: string) => {
    const next = new Set(selectedQuestionIds);
    if (next.has(questionId)) {
      next.delete(questionId);
    } else {
      next.add(questionId);
    }
    setSelectedQuestionIds(next);
  };

  const handleToggleSelectAll = () => {
    if (questions.every((q) => selectedQuestionIds.has(q.id))) {
      // Deselect all on this page
      const next = new Set(selectedQuestionIds);
      questions.forEach((q) => next.delete(q.id));
      setSelectedQuestionIds(next);
    } else {
      // Select all on this page
      const next = new Set(selectedQuestionIds);
      questions.forEach((q) => next.add(q.id));
      setSelectedQuestionIds(next);
    }
  };

  const handleBatchArchive = async (archive: boolean) => {
    if (selectedQuestionIds.size === 0) return;
    const ids = Array.from(selectedQuestionIds);
    await questionBankApi.batchArchiveQuestions(ids, archive);
    setSelectedQuestionIds(new Set());
    fetchQuestions();
  };

  const handleResetFilters = () => {
    setSelectedScopeNodeId(null);
    setStatusFilter('ACTIVE');
    setSearchQuery('');
    setCurrentPage(1);
  };

  const handleCreatePaperFromSelected = () => {
    const selectedItems = questions.filter((q) => selectedQuestionIds.has(q.id));
    if (selectedItems.length === 0) return;

    const displayLabels = ['A', 'B', 'C', 'D'];
    const compQ: PaperItemQuestion[] = [];
    const compAk: PaperAnswerKeyItem[] = [];

    selectedItems.forEach((q, idx) => {
      const qNum = idx + 1;
      let correctLetter = 'A';
      let correctText = '';
      let correctLatex: string | null = null;

      const opts = q.options.map((opt, optIdx) => {
        const lbl = displayLabels[optIdx];
        if (opt.id === q.correct_option_id) {
          correctLetter = lbl;
          correctText = opt.option_text;
          correctLatex = opt.option_latex || null;
        }
        return {
          id: opt.id,
          label: lbl,
          text: opt.option_text,
          latex: opt.option_latex,
        };
      });

      compQ.push({
        id: q.id,
        question_number: qNum,
        question_text: q.question_text,
        question_latex: q.question_latex,
        options: opts,
        correct_option_id: q.correct_option_id,
        explanation: q.explanation,
      });

      compAk.push({
        question_number: qNum,
        question_id: q.id,
        correct_letter: correctLetter,
        correct_text: correctText,
        correct_latex: correctLatex,
        explanation: q.explanation,
      });
    });

    setComposerQuestions(compQ);
    setComposerAnswerKey(compAk);
    setIsComposing(true);
  };

  if (isComposing) {
    const selectedTb = textbooks.find((t) => t.id === selectedVersionId);
    return (
      <PaperComposer
        initialSubjectVersionId={selectedVersionId}
        initialTitle={`${selectedTb?.title || 'Mathematics'} Paper`}
        initialQuestions={composerQuestions}
        initialAnswerKey={composerAnswerKey}
        onBack={() => setIsComposing(false)}
        onSavedSuccess={() => setIsComposing(false)}
      />
    );
  }

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Left Organizer Panel */}
      <QuestionBankOrganizer
        textbooks={textbooks}
        selectedVersionId={selectedVersionId}
        onSelectVersion={(vId) => {
          setSelectedVersionId(vId);
          workspace.setSelectedVersionId(vId);
          setSelectedScopeNodeId(null);
          setCurrentPage(1);
          setSelectedQuestionIds(new Set());
        }}
        scopeTree={scopeTree}
        selectedScopeNodeId={selectedScopeNodeId}
        onSelectScopeNode={(sId) => {
          setSelectedScopeNodeId(sId);
          setCurrentPage(1);
        }}
        statusFilter={statusFilter}
        onChangeStatusFilter={(st) => {
          setStatusFilter(st);
          setCurrentPage(1);
        }}
        searchQuery={searchQuery}
        onChangeSearchQuery={(q) => {
          setSearchQuery(q);
          setCurrentPage(1);
        }}
        onResetFilters={handleResetFilters}
      />

      {/* Center Question Stream */}
      <QuestionStream
        questions={questions}
        totalCount={totalCount}
        currentPage={currentPage}
        pageSize={pageSize}
        totalPages={totalPages}
        onPageChange={setCurrentPage}
        selectedQuestionIds={selectedQuestionIds}
        onToggleSelectQuestion={handleToggleSelectQuestion}
        onToggleSelectAll={handleToggleSelectAll}
        inspectingQuestionId={inspectingQuestion ? inspectingQuestion.id : null}
        onSelectForInspection={setInspectingQuestion}
        onCreatePaperFromSelected={handleCreatePaperFromSelected}
        onBatchArchiveSelected={handleBatchArchive}
        isLoading={isLoading}
        statusFilter={statusFilter}
      />

      {/* Right Question Inspector */}
      <QuestionInspector
        question={inspectingQuestion}
        onClose={() => setInspectingQuestion(null)}
      />
    </div>
  );
};
