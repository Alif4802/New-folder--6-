import React, { useState, useEffect, useCallback } from 'react';
import {
  Archive,
  BookOpen,
  Calendar,
  FileCheck,
  FileText,
  Inbox,
  Printer,
} from 'lucide-react';
import { questionBankApi } from '../services/questionBankApi';
import {
  QuestionSetSummary,
  QuestionSetDetail,
} from '../types/question_bank';
import { PaperComposer } from '../components/question_bank/PaperComposer';
import { PaperPrintView } from '../components/question_bank/PaperPrintView';

export const SavedPapersPage: React.FC = () => {
  const [papers, setPapers] = useState<QuestionSetSummary[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [currentPage] = useState<number>(1);
  const [pageSize] = useState<number>(20);
  const [statusFilter, setStatusFilter] = useState<string>('ACTIVE');
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Active viewing/editing paper state
  const [activePaperDetail, setActivePaperDetail] = useState<QuestionSetDetail | null>(null);
  const [isEditingInComposer, setIsEditingInComposer] = useState<boolean>(false);
  const [isPrintViewing, setIsPrintViewing] = useState<boolean>(false);

  const fetchPapers = useCallback(async () => {
    setIsLoading(true);
    const res = await questionBankApi.listPapers({
      status: statusFilter,
      page: currentPage,
      page_size: pageSize,
    });
    setIsLoading(false);

    if (res.ok && res.data) {
      setPapers(res.data.items);
      setTotalCount(res.data.total_count);
    }
  }, [statusFilter, currentPage, pageSize]);

  useEffect(() => {
    fetchPapers();
  }, [fetchPapers]);

  const handleOpenComposer = async (paperId: string) => {
    const res = await questionBankApi.getPaper(paperId);
    if (res.ok && res.data) {
      setActivePaperDetail(res.data);
      setIsEditingInComposer(true);
      setIsPrintViewing(false);
    }
  };

  const handleOpenPrintView = async (paperId: string) => {
    const res = await questionBankApi.getPaper(paperId);
    if (res.ok && res.data) {
      setActivePaperDetail(res.data);
      setIsPrintViewing(true);
      setIsEditingInComposer(false);
    }
  };

  const handleArchivePaper = async (paperId: string) => {
    await questionBankApi.archivePaper(paperId);
    fetchPapers();
  };

  if (isEditingInComposer && activePaperDetail) {
    return (
      <PaperComposer
        initialSubjectVersionId={activePaperDetail.subject_version_id}
        initialTitle={activePaperDetail.title}
        initialMetadata={activePaperDetail.paper_metadata}
        initialQuestions={activePaperDetail.questions}
        initialAnswerKey={activePaperDetail.answer_key}
        scopeNodeIds={activePaperDetail.scope_node_ids}
        onBack={() => {
          setIsEditingInComposer(false);
          setActivePaperDetail(null);
          fetchPapers();
        }}
        onSavedSuccess={() => {
          fetchPapers();
        }}
      />
    );
  }

  if (isPrintViewing && activePaperDetail) {
    return (
      <PaperPrintView
        paperTitle={activePaperDetail.title}
        metadata={activePaperDetail.paper_metadata}
        questions={activePaperDetail.questions}
        answerKey={activePaperDetail.answer_key}
        onBack={() => {
          setIsPrintViewing(false);
          setActivePaperDetail(null);
        }}
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-50">
      {/* Header */}
      <div className="h-16 bg-white border-b border-slate-200 px-6 flex items-center justify-between flex-shrink-0 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-lms-blue-50 text-lms-blue-600 flex items-center justify-center font-bold">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-semibold text-sm text-slate-900">Saved Question Papers</h1>
            <p className="text-[11px] text-slate-400">
              Reusable assessment sets with exact presentation option order snapshots
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Status filter tabs */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">
              Total: <span className="font-semibold text-slate-800">{totalCount}</span> papers
            </span>
            <div className="flex rounded border border-slate-200 bg-slate-100 p-0.5 text-xs">
              <button
                onClick={() => setStatusFilter('ACTIVE')}
                className={`px-3 py-1 rounded font-medium transition-colors ${
                  statusFilter === 'ACTIVE' ? 'bg-white text-lms-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Active Papers
              </button>
              <button
                onClick={() => setStatusFilter('ARCHIVED')}
                className={`px-3 py-1 rounded font-medium transition-colors ${
                  statusFilter === 'ARCHIVED' ? 'bg-white text-lms-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Archived
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Papers List Content */}
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl w-full mx-auto space-y-4">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-400 space-y-2">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-lms-blue-600" />
            <span className="text-xs">Loading saved papers...</span>
          </div>
        ) : papers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-80 text-center p-8 bg-white rounded-lg border border-dashed border-slate-300 shadow-sm">
            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
              <Inbox className="w-6 h-6" />
            </div>
            <h3 className="font-semibold text-sm text-slate-800 mb-1">No saved question papers found</h3>
            <p className="text-xs text-slate-500 max-w-sm">
              Generate an assessment or build a paper from the Question Bank and click "Save Paper" to save your arrangement.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {papers.map((p) => (
              <div
                key={p.id}
                className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm hover:shadow transition-shadow flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <h3 className="font-bold text-sm text-slate-900 leading-snug">{p.title}</h3>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-blue-50 text-lms-blue-700 font-semibold border border-blue-100">
                      {p.question_count} MCQs
                    </span>
                  </div>

                  {p.description && (
                    <p className="text-xs text-slate-500 mb-3 line-clamp-2">{p.description}</p>
                  )}

                  <div className="space-y-1 text-xs text-slate-600 mb-4">
                    <div className="flex items-center gap-1.5 text-slate-700">
                      <BookOpen className="w-3.5 h-3.5 text-slate-400" />
                      <span>{p.subject_title || 'Mathematics — Class 7'}</span>
                    </div>

                    <div className="flex items-center gap-1.5 text-slate-400 text-[11px]">
                      <Calendar className="w-3.5 h-3.5 text-slate-300" />
                      <span>Saved on {new Date(p.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                </div>

                {/* Card Actions */}
                <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleOpenComposer(p.id)}
                      className="px-3 py-1.5 rounded bg-lms-blue-50 hover:bg-lms-blue-100 text-lms-blue-700 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <FileCheck className="w-3.5 h-3.5" />
                      Open in Composer
                    </button>

                    <button
                      onClick={() => handleOpenPrintView(p.id)}
                      className="px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <Printer className="w-3.5 h-3.5 text-slate-500" />
                      Print / PDF
                    </button>
                  </div>

                  {statusFilter === 'ACTIVE' && (
                    <button
                      onClick={() => handleArchivePaper(p.id)}
                      className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                      title="Archive Paper"
                    >
                      <Archive className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
