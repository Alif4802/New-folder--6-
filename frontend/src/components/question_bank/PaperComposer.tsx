import React, { useState } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  Printer,
  Save,
  Settings,
  Shuffle,
  Trash2,
} from 'lucide-react';
import {
  PaperMetadata,
  PaperItemQuestion,
  PaperAnswerKeyItem,
  SavePaperRequest,
} from '../../types/question_bank';
import { MathRenderer } from '../MathRenderer';
import { PaperPrintView } from './PaperPrintView';
import { questionBankApi } from '../../services/questionBankApi';

interface PaperComposerProps {
  initialSubjectVersionId: string;
  initialTitle?: string;
  initialMetadata?: PaperMetadata | null;
  initialQuestions: PaperItemQuestion[];
  initialAnswerKey: PaperAnswerKeyItem[];
  jobId?: string | null;
  scopeNodeIds?: string[] | null;
  onBack: () => void;
  onSavedSuccess?: (paperId: string) => void;
}

// Pure zero-LLM array shuffle helper
function shuffleArray<T>(array: T[]): T[] {
  const arr = [...array];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export const PaperComposer: React.FC<PaperComposerProps> = ({
  initialSubjectVersionId,
  initialTitle = 'MCQ Question Paper',
  initialMetadata,
  initialQuestions,
  initialAnswerKey,
  jobId,
  scopeNodeIds,
  onBack,
  onSavedSuccess,
}) => {
  const [title, setTitle] = useState<string>(initialTitle);
  const [questions, setQuestions] = useState<PaperItemQuestion[]>(initialQuestions);
  const [answerKey, setAnswerKey] = useState<PaperAnswerKeyItem[]>(initialAnswerKey);
  const [metadata, setMetadata] = useState<PaperMetadata>(
    initialMetadata || {
      institution_name: '',
      exam_title: initialTitle,
      subject_name: '',
      grade_name: '',
      duration_minutes: 30,
      marks_per_question: 1.0,
      total_marks: initialQuestions.length,
      instructions: 'Answer all questions. Each question carries 1 mark.',
    }
  );

  const [showAnswerKey, setShowAnswerKey] = useState<boolean>(false);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [isPrintPreview, setIsPrintPreview] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Zero-LLM instant paper randomizer
  const handleRandomizePaper = () => {
    if (questions.length === 0) return;

    const displayLabels = ['A', 'B', 'C', 'D'];
    const shuffledQuestions = shuffleArray(questions);

    const newQuestions: PaperItemQuestion[] = [];
    const newAnswerKey: PaperAnswerKeyItem[] = [];

    shuffledQuestions.forEach((q, qIdx) => {
      const qNum = qIdx + 1;
      const origAk = answerKey.find(
        (ak) => ak.question_number === q.question_number || (ak.question_id && ak.question_id === q.id)
      );
      const targetCorrectText = origAk?.correct_text || '';
      const targetCorrectId = q.correct_option_id;

      const shuffledOptions = shuffleArray(q.options);
      const newOptions: typeof q.options = [];
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
        explanation: q.explanation,
      });
    });

    setQuestions(newQuestions);
    setAnswerKey(newAnswerKey);
    setSaveMessage({ type: 'success', text: 'Paper randomized successfully (Zero-LLM).' });
  };

  const handleRemoveQuestion = (idxToRemove: number) => {
    const nextQ = questions
      .filter((_, idx) => idx !== idxToRemove)
      .map((q, idx) => ({ ...q, question_number: idx + 1 }));

    // Re-sync answer key
    const nextAk = answerKey
      .filter((_, idx) => idx !== idxToRemove)
      .map((ak, idx) => ({ ...ak, question_number: idx + 1 }));

    setQuestions(nextQ);
    setAnswerKey(nextAk);
    setMetadata({ ...metadata, total_marks: nextQ.length * (metadata.marks_per_question || 1.0) });
  };

  const handleSavePaper = async () => {
    if (!title.trim()) {
      setSaveMessage({ type: 'error', text: 'Please provide a title for the paper.' });
      return;
    }

    if (questions.length === 0) {
      setSaveMessage({ type: 'error', text: 'Cannot save an empty paper.' });
      return;
    }

    setIsSaving(true);
    setSaveMessage(null);

    const arrangements = questions.map((q) => ({
      question_id: q.id || '',
      question_order: q.question_number,
      option_order: q.options.map((o) => o.id || ''),
    }));

    const payload: SavePaperRequest = {
      source_type: jobId ? 'GENERATED_JOB' : 'QUESTION_BANK',
      job_id: jobId || null,
      subject_version_id: initialSubjectVersionId,
      title: title.trim(),
      paper_metadata: {
        ...metadata,
        exam_title: title.trim(),
        total_marks: questions.length * (metadata.marks_per_question || 1.0),
      },
      arrangements,
      scope_node_ids: scopeNodeIds,
    };

    const res = await questionBankApi.savePaper(payload);
    setIsSaving(false);

    if (res.ok && res.data) {
      setSaveMessage({ type: 'success', text: `Paper "${res.data.title}" saved successfully!` });
      if (onSavedSuccess) {
        onSavedSuccess(res.data.id);
      }
    } else {
      setSaveMessage({ type: 'error', text: res.error || 'Failed to save paper.' });
    }
  };

  if (isPrintPreview) {
    return (
      <PaperPrintView
        paperTitle={title}
        metadata={metadata}
        questions={questions}
        answerKey={answerKey}
        onBack={() => setIsPrintPreview(false)}
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-100">
      {/* Top Header */}
      <div className="h-14 bg-white border-b border-slate-200 px-6 flex items-center justify-between flex-shrink-0 shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-800 transition-colors"
            title="Back"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="font-bold text-sm text-slate-800 border-b border-transparent hover:border-slate-300 focus:border-lms-blue-500 focus:outline-none px-1 py-0.5"
            />
            <div className="text-[11px] text-slate-400">
              {questions.length} questions • {questions.length * (metadata.marks_per_question || 1.0)} Total Marks
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`px-3 py-1.5 rounded text-xs font-medium border flex items-center gap-1.5 transition-colors ${
              showSettings ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
            Header Settings
          </button>

          <button
            onClick={() => setShowAnswerKey(!showAnswerKey)}
            className={`px-3 py-1.5 rounded text-xs font-medium border flex items-center gap-1.5 transition-colors ${
              showAnswerKey ? 'bg-amber-600 text-white border-amber-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
            }`}
          >
            {showAnswerKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            {showAnswerKey ? 'Hide Answer Key' : 'Show Answer Key'}
          </button>

          <button
            onClick={handleRandomizePaper}
            className="px-3 py-1.5 bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 rounded text-xs font-medium flex items-center gap-1.5 shadow-sm transition-colors"
            title="Instant Zero-LLM shuffle"
          >
            <Shuffle className="w-3.5 h-3.5 text-lms-blue-600" />
            Randomize Paper
          </button>

          <button
            onClick={handleSavePaper}
            disabled={isSaving}
            className="px-3.5 py-1.5 bg-lms-blue-600 hover:bg-lms-blue-700 disabled:opacity-50 text-white rounded text-xs font-semibold shadow flex items-center gap-1.5 transition-colors"
          >
            <Save className="w-3.5 h-3.5" />
            {isSaving ? 'Saving...' : 'Save Paper'}
          </button>

          <button
            onClick={() => setIsPrintPreview(true)}
            className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-semibold shadow flex items-center gap-1.5 transition-colors"
          >
            <Printer className="w-3.5 h-3.5" />
            Print / Save PDF
          </button>
        </div>
      </div>

      {/* Save feedback banner */}
      {saveMessage && (
        <div
          className={`px-6 py-2 text-xs font-medium flex items-center justify-between ${
            saveMessage.type === 'success' ? 'bg-emerald-50 text-emerald-800 border-b border-emerald-200' : 'bg-rose-50 text-rose-800 border-b border-rose-200'
          }`}
        >
          <span>{saveMessage.text}</span>
          <button onClick={() => setSaveMessage(null)} className="text-slate-400 hover:text-slate-700">
            ×
          </button>
        </div>
      )}

      {/* Main Workspace */}
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl w-full mx-auto space-y-4">
        {/* Collapsible Header Settings Panel */}
        {showSettings && (
          <div className="bg-white rounded-lg border border-slate-300 p-4 shadow-sm text-xs space-y-3">
            <h3 className="font-semibold text-slate-800 uppercase tracking-wider text-[11px] border-b border-slate-100 pb-2">
              Paper Header & Exam Settings
            </h3>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Institution Name</label>
                <input
                  type="text"
                  value={metadata.institution_name || ''}
                  onChange={(e) => setMetadata({ ...metadata, institution_name: e.target.value })}
                  placeholder="e.g. Model High School"
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Subject</label>
                <input
                  type="text"
                  value={metadata.subject_name || ''}
                  onChange={(e) => setMetadata({ ...metadata, subject_name: e.target.value })}
                  placeholder="e.g. Mathematics"
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Class / Grade</label>
                <input
                  type="text"
                  value={metadata.grade_name || ''}
                  onChange={(e) => setMetadata({ ...metadata, grade_name: e.target.value })}
                  placeholder="e.g. Class 7"
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Duration (Minutes)</label>
                <input
                  type="number"
                  value={metadata.duration_minutes || 30}
                  onChange={(e) => setMetadata({ ...metadata, duration_minutes: parseInt(e.target.value) || 30 })}
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Marks per Question</label>
                <input
                  type="number"
                  step="0.5"
                  value={metadata.marks_per_question || 1.0}
                  onChange={(e) => {
                    const mpq = parseFloat(e.target.value) || 1.0;
                    setMetadata({ ...metadata, marks_per_question: mpq, total_marks: questions.length * mpq });
                  }}
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 mb-1">Instructions</label>
                <input
                  type="text"
                  value={metadata.instructions || ''}
                  onChange={(e) => setMetadata({ ...metadata, instructions: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500"
                />
              </div>
            </div>
          </div>
        )}

        {/* Question Cards List */}
        <div className="space-y-3">
          {questions.map((q, idx) => {
            const ak = answerKey.find((item) => item.question_number === q.question_number);

            return (
              <div key={q.id || idx} className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-start gap-2 flex-1">
                    <span className="w-6 h-6 rounded-full bg-lms-blue-100 text-lms-blue-800 font-bold text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                      {q.question_number}
                    </span>
                    <div className="text-xs font-semibold text-slate-900 leading-relaxed">
                      <MathRenderer rawText={q.question_text} latex={q.question_latex} />
                    </div>
                  </div>

                  <button
                    onClick={() => handleRemoveQuestion(idx)}
                    className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    title="Remove from paper"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Options */}
                <div className="grid grid-cols-2 gap-2 mt-3 pl-8">
                  {q.options.map((opt) => {
                    const isCorrect = showAnswerKey && ak && ak.correct_letter === opt.label;

                    return (
                      <div
                        key={opt.id}
                        className={`p-2 rounded border text-xs flex items-center gap-2 ${
                          isCorrect
                            ? 'bg-emerald-50 border-emerald-300 text-emerald-900 font-medium ring-1 ring-emerald-400'
                            : 'bg-slate-50 border-slate-200 text-slate-700'
                        }`}
                      >
                        <span
                          className={`w-4 h-4 rounded-full flex items-center justify-center font-bold text-[10px] flex-shrink-0 ${
                            isCorrect ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'
                          }`}
                        >
                          {opt.label}
                        </span>
                        <span className="flex-1 truncate">
                          <MathRenderer rawText={opt.text} latex={opt.latex} />
                        </span>
                        {isCorrect && <CheckCircle2 className="w-3 h-3 text-emerald-600 flex-shrink-0" />}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
