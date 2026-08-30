import React, { useState, useEffect } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  Info,
  Printer,
} from 'lucide-react';
import { PaperMetadata, PaperItemQuestion, PaperAnswerKeyItem } from '../../types/question_bank';
import { MathRenderer } from '../MathRenderer';

interface PaperPrintViewProps {
  paperTitle: string;
  metadata?: PaperMetadata | null;
  questions: PaperItemQuestion[];
  answerKey: PaperAnswerKeyItem[];
  onBack: () => void;
}

export const PaperPrintView: React.FC<PaperPrintViewProps> = ({
  paperTitle,
  metadata,
  questions,
  answerKey,
  onBack,
}) => {
  const [printMode, setPrintMode] = useState<'STUDENT' | 'TEACHER'>('STUDENT');

  const institutionName = metadata?.institution_name || '';
  const examTitle = metadata?.exam_title || paperTitle || 'MCQ Examination';
  const subjectName = metadata?.subject_name || 'Mathematics';
  const gradeName = metadata?.grade_name || '';
  const duration = metadata?.duration_minutes ? `${metadata.duration_minutes} Minutes` : '';
  const totalMarks = metadata?.total_marks || questions.length;
  const instructions = metadata?.instructions || 'Choose the single best answer for each question. All questions carry equal marks.';

  // Dynamically set document title for print preview / browser Save as PDF
  useEffect(() => {
    const originalTitle = document.title;
    const dynamicTitle = `${examTitle}${gradeName ? ` — ${gradeName}` : ''}`.trim();
    if (dynamicTitle) {
      document.title = dynamicTitle;
    }
    return () => {
      document.title = originalTitle;
    };
  }, [examTitle, gradeName]);

  const handleTriggerPrint = () => {
    window.print();
  };

  return (
    <div className="paper-print-root min-h-screen bg-slate-200 print:bg-white text-slate-900 flex flex-col">
      {/* Non-printed Top Toolbar */}
      <div className="bg-lms-navy-950 text-white px-6 py-3 flex flex-wrap items-center justify-between gap-3 shadow-md print:hidden flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center gap-1.5 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Workspace
          </button>
          <div className="h-5 w-px bg-slate-700 hidden sm:block" />
          <span className="font-semibold text-sm hidden sm:inline">Print Preview & PDF Export</span>
        </div>

        {/* Clean PDF Browser Hint (Non-printed) */}
        <div className="text-[11px] text-amber-200 bg-amber-950/60 px-3 py-1 rounded border border-amber-500/30 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
          <span>For a clean PDF, turn off <strong>"Headers and footers"</strong> in the browser print dialog.</span>
        </div>

        <div className="flex items-center gap-4">
          {/* Mode Switcher */}
          <div className="flex rounded bg-slate-800 p-0.5 border border-slate-700 text-xs">
            <button
              onClick={() => setPrintMode('STUDENT')}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                printMode === 'STUDENT' ? 'bg-lms-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
            >
              Student Copy
            </button>
            <button
              onClick={() => setPrintMode('TEACHER')}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                printMode === 'TEACHER' ? 'bg-lms-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
            >
              Teacher Copy
            </button>
          </div>

          <button
            onClick={handleTriggerPrint}
            className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-semibold shadow flex items-center gap-1.5 transition-colors"
          >
            <Printer className="w-4 h-4" />
            Print / Save PDF
          </button>
        </div>
      </div>

      {/* A4 Document Surface */}
      <div className="flex-1 overflow-y-auto print:overflow-visible print:h-auto print:max-h-none print:min-h-0 p-8 print:p-0 flex justify-center">
        <div className="a4-sheet bg-white max-w-[210mm] w-full min-h-[297mm] p-[15mm] shadow-lg print:shadow-none print:w-full print:max-w-none print:min-h-0 print:h-auto print:p-0">
          {/* Header */}
          <div className="text-center border-b-2 border-slate-900 pb-4 mb-4">
            {institutionName && (
              <h1 className="text-xl font-bold uppercase tracking-wide text-slate-900 mb-1">
                {institutionName}
              </h1>
            )}
            <h2 className="text-base font-bold text-slate-800 uppercase tracking-normal">
              {examTitle}
            </h2>

            <div className="flex justify-between items-center text-xs font-semibold text-slate-700 mt-2.5 px-2">
              <span>Subject: {subjectName}</span>
              {gradeName && <span>Class: {gradeName}</span>}
              {duration && <span>Time: {duration}</span>}
              <span>Total Marks: {totalMarks}</span>
            </div>

            {/* Candidate Box on Student Copy */}
            {printMode === 'STUDENT' && (
              <div className="mt-3 pt-2 border-t border-dashed border-slate-400 grid grid-cols-3 gap-3 text-left text-xs text-slate-700">
                <div>
                  <span className="font-semibold">Student Name:</span> ___________________
                </div>
                <div>
                  <span className="font-semibold">Roll No:</span> _____________
                </div>
                <div>
                  <span className="font-semibold">Section / Date:</span> _________
                </div>
              </div>
            )}
          </div>

          {/* Instructions */}
          <div className="mb-5 px-1 text-xs italic text-slate-600">
            <strong>Instructions:</strong> {instructions}
          </div>

          {/* Questions Stream */}
          <div className="space-y-4">
            {questions.map((q) => {
              return (
                <div
                  key={q.id || q.question_number}
                  className="paper-question-block pb-3 border-b border-slate-100 last:border-b-0"
                >
                  {/* Stem */}
                  <div className="paper-stem-header text-xs font-semibold text-slate-900 leading-relaxed mb-2 flex items-start gap-1.5">
                    <span className="font-bold">{q.question_number}.</span>
                    <div className="flex-1">
                      <MathRenderer rawText={q.question_text} latex={q.question_latex} />
                    </div>
                  </div>

                  {/* 4 Options Grid (Content-safe 2-column wrapping) */}
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pl-4 text-xs">
                    {q.options.map((opt) => {
                      return (
                        <div key={opt.id} className="paper-option-item flex items-start gap-1.5 text-slate-800 min-w-0">
                          <span className="font-bold text-slate-900 flex-shrink-0">({opt.label})</span>
                          <span className="flex-1 leading-snug break-words min-w-0">
                            <MathRenderer rawText={opt.text} latex={opt.latex} />
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Teacher Copy Answer Key Section (Answers ONLY, Zero Explanations) */}
          {printMode === 'TEACHER' && (
            <div className="mt-8 pt-6 border-t-2 border-slate-900">
              <div className="flex items-center justify-between mb-3 paper-stem-header">
                <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-700" />
                  Answer Key (Teacher Copy)
                </h3>
                <span className="text-[10px] text-slate-500 font-mono">Dynamic Paper Key</span>
              </div>

              <table className="w-full text-xs border-collapse border border-slate-300 mb-4">
                <thead>
                  <tr className="bg-slate-100 text-slate-800 font-bold text-left">
                    <th className="border border-slate-300 px-3 py-1.5 w-14 text-center">Q #</th>
                    <th className="border border-slate-300 px-3 py-1.5 w-16 text-center">Answer</th>
                    <th className="border border-slate-300 px-3 py-1.5">Correct Option Text</th>
                  </tr>
                </thead>
                <tbody>
                  {answerKey.map((ak) => (
                    <tr key={ak.question_number} className="paper-ak-row hover:bg-slate-50">
                      <td className="border border-slate-300 px-3 py-1 text-center font-bold">{ak.question_number}</td>
                      <td className="border border-slate-300 px-3 py-1 text-center font-bold text-emerald-800 bg-emerald-50/50">
                        {ak.correct_letter}
                      </td>
                      <td className="border border-slate-300 px-3 py-1 min-w-0 break-words">
                        <MathRenderer rawText={ak.correct_text} latex={ak.correct_latex} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
