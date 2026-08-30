import React, { useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Layers,
  Lightbulb,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { QuestionBankItem } from '../../types/question_bank';
import { MathRenderer } from '../MathRenderer';

interface QuestionInspectorProps {
  question: QuestionBankItem | null;
  onClose: () => void;
}

export const QuestionInspector: React.FC<QuestionInspectorProps> = ({
  question,
  onClose,
}) => {
  const [isAuditExpanded, setIsAuditExpanded] = useState<boolean>(false);

  if (!question) {
    return (
      <div className="w-80 bg-white border-l border-slate-200 flex flex-col items-center justify-center p-6 text-center text-slate-400 flex-shrink-0">
        <Lightbulb className="w-8 h-8 text-slate-300 mb-2" />
        <span className="text-xs font-medium text-slate-600">No question selected</span>
        <span className="text-[11px] text-slate-400 mt-1">
          Click any question card to inspect full explanation, math formulas, and provenance.
        </span>
      </div>
    );
  }

  const prov = question.provenance;
  const primaryScope = question.scopes.length > 0 ? question.scopes[0] : null;

  return (
    <div className="w-96 bg-white border-l border-slate-200 flex flex-col h-full overflow-hidden flex-shrink-0">
      {/* Header */}
      <div className="p-3.5 border-b border-slate-200 flex items-center justify-between bg-slate-50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-lms-blue-600" />
          <span className="font-semibold text-xs text-slate-800 uppercase tracking-wider">Question Inspector</span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-200 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {/* Origin & Grounding Summary */}
        <div className="p-2.5 rounded-lg bg-blue-50/50 border border-blue-100 space-y-1.5">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-500 font-medium flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-purple-600" /> Origin:
            </span>
            <span className="font-semibold text-purple-700">AI Generated</span>
          </div>

          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-500 font-medium flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-600" /> Grounded in:
            </span>
            <span className="font-semibold text-emerald-700">Official NCTB Textbook</span>
          </div>
        </div>

        {/* Question Stem */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
            Question Stem
          </label>
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-slate-900 leading-relaxed font-medium">
            <MathRenderer rawText={question.question_text} latex={question.question_latex} />
          </div>
        </div>

        {/* Options */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
            Options & Correct Answer
          </label>
          <div className="space-y-1.5">
            {question.options.map((opt, idx) => {
              const label = ['A', 'B', 'C', 'D'][idx] || opt.canonical_order;
              const isCorrect = question.correct_option_id === opt.id;

              return (
                <div
                  key={opt.id}
                  className={`p-2 rounded border flex items-center gap-2 text-xs transition-colors ${
                    isCorrect
                      ? 'bg-emerald-50 border-emerald-300 text-emerald-900 font-medium ring-1 ring-emerald-400'
                      : 'bg-slate-50 border-slate-200 text-slate-700'
                  }`}
                >
                  <span
                    className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] flex-shrink-0 ${
                      isCorrect ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'
                    }`}
                  >
                    {label}
                  </span>
                  <span className="flex-1">
                    <MathRenderer rawText={opt.option_text} latex={opt.option_latex} />
                  </span>
                  {isCorrect && (
                    <span className="text-[10px] font-bold text-emerald-700 flex items-center gap-1 bg-emerald-100 px-1.5 py-0.5 rounded">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Correct
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Pedagogical Explanation */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1 flex items-center gap-1 text-amber-700">
            <Lightbulb className="w-3.5 h-3.5 text-amber-500" />
            Pedagogical Solution / Explanation
          </label>
          <div className="p-3 bg-amber-50/50 rounded-lg border border-amber-200 text-slate-800 leading-relaxed">
            <MathRenderer rawText={question.explanation} />
          </div>
        </div>

        {/* Curriculum Hierarchy & Provenance */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <BookOpen className="w-3.5 h-3.5 text-slate-400" />
            Source Grounding
          </label>
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-2">
            <div>
              <div className="text-[10px] text-slate-400 font-semibold uppercase">Textbook</div>
              <div className="font-semibold text-slate-800">{question.subject_title || 'Mathematics — Class 7'}</div>
            </div>

            {primaryScope && (
              <div>
                <div className="text-[10px] text-slate-400 font-semibold uppercase">Curriculum Scope</div>
                <div className="text-slate-700 flex items-center gap-1 mt-0.5">
                  <Layers className="w-3.5 h-3.5 text-lms-blue-600" />
                  <span className="font-medium">{primaryScope.source_label}: {primaryScope.title}</span>
                </div>
              </div>
            )}

            {prov && prov.page_number && (
              <div>
                <div className="text-[10px] text-slate-400 font-semibold uppercase">Textbook Pages</div>
                <div className="text-slate-700 font-mono text-xs">Page {prov.page_number}</div>
              </div>
            )}

            {prov && prov.source_content_snippet && (
              <div>
                <div className="text-[10px] text-slate-400 font-semibold uppercase">Source Excerpt</div>
                <div className="text-[11px] text-slate-600 italic bg-white p-2 rounded border border-slate-200 mt-1">
                  "{prov.source_content_snippet}"
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Metadata */}
        <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
          <span className="flex items-center gap-1">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            Created: {new Date(question.created_at).toLocaleString()}
          </span>
          <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
            {question.status}
          </span>
        </div>

        {/* Collapsible Technical Audit Section */}
        <div className="pt-2 border-t border-slate-100">
          <button
            onClick={() => setIsAuditExpanded(!isAuditExpanded)}
            className="w-full flex items-center justify-between text-[10px] font-semibold text-slate-400 uppercase tracking-wider py-1 hover:text-slate-700"
          >
            <span>Technical Audit Metadata</span>
            {isAuditExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </button>

          {isAuditExpanded && (
            <div className="mt-2 p-2.5 bg-slate-100 rounded text-[11px] font-mono text-slate-600 space-y-1">
              <div><span className="text-slate-400">ID:</span> {question.id}</div>
              <div><span className="text-slate-400">Subject Version:</span> {question.subject_version_id}</div>
              <div><span className="text-slate-400">Question Type:</span> {question.question_type}</div>
              <div><span className="text-slate-400">Language:</span> {question.language}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
