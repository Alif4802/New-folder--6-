import React from 'react';
import {
  Archive,
  BookPlus,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Layers,
  Sparkles,
  Inbox,
} from 'lucide-react';
import { QuestionBankItem } from '../../types/question_bank';
import { MathRenderer } from '../MathRenderer';

interface QuestionStreamProps {
  questions: QuestionBankItem[];
  totalCount: number;
  currentPage: number;
  pageSize: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  selectedQuestionIds: Set<string>;
  onToggleSelectQuestion: (questionId: string) => void;
  onToggleSelectAll: () => void;
  inspectingQuestionId: string | null;
  onSelectForInspection: (question: QuestionBankItem) => void;
  onCreatePaperFromSelected: () => void;
  onBatchArchiveSelected: (archive: boolean) => void;
  isLoading: boolean;
  statusFilter: string;
}

export const QuestionStream: React.FC<QuestionStreamProps> = ({
  questions,
  totalCount,
  currentPage,
  totalPages,
  onPageChange,
  selectedQuestionIds,
  onToggleSelectQuestion,
  onToggleSelectAll,
  inspectingQuestionId,
  onSelectForInspection,
  onCreatePaperFromSelected,
  onBatchArchiveSelected,
  isLoading,
  statusFilter,
}) => {
  const isAllSelected = questions.length > 0 && questions.every((q) => selectedQuestionIds.has(q.id));
  const hasSelected = selectedQuestionIds.size > 0;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-100">
      {/* Stream Action Toolbar */}
      <div className="h-12 bg-white border-b border-slate-200 px-4 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer select-none text-xs text-slate-700 font-medium">
            <input
              type="checkbox"
              checked={isAllSelected}
              onChange={onToggleSelectAll}
              disabled={questions.length === 0}
              className="rounded text-lms-blue-600 focus:ring-lms-blue-500 w-3.5 h-3.5"
            />
            <span>Select Page ({selectedQuestionIds.size} selected)</span>
          </label>
        </div>

        <div className="flex items-center gap-2">
          {hasSelected && (
            <>
              <button
                onClick={onCreatePaperFromSelected}
                className="px-2.5 py-1 bg-lms-blue-600 hover:bg-lms-blue-700 text-white rounded text-xs font-medium shadow-sm flex items-center gap-1.5 transition-colors"
              >
                <BookPlus className="w-3.5 h-3.5" />
                Create Paper ({selectedQuestionIds.size})
              </button>

              <button
                onClick={() => onBatchArchiveSelected(statusFilter === 'ACTIVE')}
                className="px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 rounded text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <Archive className="w-3.5 h-3.5 text-slate-500" />
                {statusFilter === 'ACTIVE' ? 'Archive' : 'Restore'}
              </button>
            </>
          )}

          <div className="text-xs text-slate-500 border-l border-slate-200 pl-3">
            Total: <span className="font-semibold text-slate-800">{totalCount}</span> questions
          </div>
        </div>
      </div>

      {/* Questions Scrollable Stream */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-400 space-y-2">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-lms-blue-600" />
            <span className="text-xs">Loading Question Bank...</span>
          </div>
        ) : questions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-80 text-center p-6 bg-white rounded-lg border border-dashed border-slate-300 shadow-sm">
            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
              <Inbox className="w-6 h-6" />
            </div>
            <h3 className="font-semibold text-sm text-slate-800 mb-1">No questions found</h3>
            <p className="text-xs text-slate-500 max-w-sm">
              {statusFilter === 'ACTIVE'
                ? 'Generate an assessment or save questions from a paper to build your persistent Question Bank.'
                : 'No archived questions in this view.'}
            </p>
          </div>
        ) : (
          questions.map((q) => {
            const isSelected = selectedQuestionIds.has(q.id);
            const isInspecting = inspectingQuestionId === q.id;
            const scopeLabel = q.scopes.length > 0 ? q.scopes[0].source_label : null;
            const scopeTitle = q.scopes.length > 0 ? q.scopes[0].title : null;

            return (
              <div
                key={q.id}
                onClick={() => onSelectForInspection(q)}
                className={`bg-white rounded-lg border transition-all cursor-pointer p-3.5 shadow-sm hover:shadow ${
                  isInspecting
                    ? 'border-lms-blue-600 ring-1 ring-lms-blue-500'
                    : isSelected
                    ? 'border-lms-blue-300 bg-blue-50/20'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* Checkbox */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleSelectQuestion(q.id);
                    }}
                    className="pt-0.5"
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {}}
                      className="rounded text-lms-blue-600 focus:ring-lms-blue-500 w-3.5 h-3.5 cursor-pointer"
                    />
                  </div>

                  {/* Card Content */}
                  <div className="flex-1 min-w-0">
                    {/* Header Badges */}
                    <div className="flex flex-wrap items-center gap-1.5 mb-2">
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                        {q.subject_name || 'Mathematics'} {q.grade_name ? `• ${q.grade_name}` : ''}
                      </span>

                      {scopeLabel && (
                        <span className="text-[10px] px-2 py-0.5 rounded bg-blue-50 text-lms-blue-700 border border-blue-100 flex items-center gap-1">
                          <Layers className="w-3 h-3 text-lms-blue-500" />
                          <span className="truncate max-w-[180px]">{scopeLabel}: {scopeTitle}</span>
                        </span>
                      )}

                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-100 flex items-center gap-1">
                        <Sparkles className="w-2.5 h-2.5 text-purple-500" />
                        AI Generated
                      </span>

                      {q.status === 'ARCHIVED' && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                          Archived
                        </span>
                      )}
                    </div>

                    {/* Question Stem */}
                    <div className="text-xs font-semibold text-slate-900 mb-2 leading-relaxed">
                      <MathRenderer rawText={q.question_text} latex={q.question_latex} />
                    </div>

                    {/* 4 Options Preview */}
                    <div className="grid grid-cols-2 gap-2 mt-2">
                      {q.options.map((opt, optIdx) => {
                        const label = ['A', 'B', 'C', 'D'][optIdx] || opt.canonical_order;
                        const isCorrect = q.correct_option_id === opt.id;

                        return (
                          <div
                            key={opt.id}
                            className={`px-2.5 py-1.5 rounded border text-[11px] flex items-center gap-2 ${
                              isCorrect
                                ? 'bg-emerald-50/80 border-emerald-300 text-emerald-900 font-medium'
                                : 'bg-slate-50 border-slate-200 text-slate-700'
                            }`}
                          >
                            <span
                              className={`w-4 h-4 rounded-full flex items-center justify-center font-bold text-[9px] flex-shrink-0 ${
                                isCorrect ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'
                              }`}
                            >
                              {label}
                            </span>
                            <span className="truncate flex-1">
                              <MathRenderer rawText={opt.option_text} latex={opt.option_latex} />
                            </span>
                            {isCorrect && <CheckCircle2 className="w-3 h-3 text-emerald-600 flex-shrink-0" />}
                          </div>
                        );
                      })}
                    </div>

                    {/* Footer timestamp */}
                    <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-[10px] text-slate-400">
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3 h-3 text-slate-300" />
                        Saved: {new Date(q.created_at).toLocaleDateString()}
                      </span>
                      <span className="text-lms-blue-600 font-medium hover:underline">
                        View Solution & Provenance →
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="h-12 bg-white border-t border-slate-200 px-4 flex items-center justify-between flex-shrink-0 text-xs text-slate-600">
          <div>
            Page <span className="font-semibold text-slate-800">{currentPage}</span> of{' '}
            <span className="font-semibold text-slate-800">{totalPages}</span>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => onPageChange(currentPage - 1)}
              disabled={currentPage <= 1}
              className="p-1 rounded border border-slate-200 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => onPageChange(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="p-1 rounded border border-slate-200 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
