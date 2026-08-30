import React, { useState } from 'react';
import { TextbookVersionSummary, GradeResponse, SubjectSummary, TextbookDependencySummary } from '../types/api';
import { apiService } from '../services/api';
import {
  BookOpen,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  FileText,
  Sparkles,
  Eye,
  Trash2,
  Edit2,
  Layers,
  Check,
  X,
} from 'lucide-react';

interface IngestedTextbooksTableProps {
  textbooks: TextbookVersionSummary[];
  loading: boolean;
  onRefresh: () => void;
  onSelect: (versionId: string) => void;
  onGenerateMCQs?: (versionId: string) => void;
  selectedId: string | null;
}

export const IngestedTextbooksTable: React.FC<IngestedTextbooksTableProps> = ({
  textbooks,
  loading,
  onRefresh,
  onSelect,
  onGenerateMCQs,
  selectedId,
}) => {
  // Edit Metadata Modal State
  const [editingTb, setEditingTb] = useState<TextbookVersionSummary | null>(null);
  const [grades, setGrades] = useState<GradeResponse[]>([]);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [editGradeId, setEditGradeId] = useState<number | null>(null);
  const [editSubjectId, setEditSubjectId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState<string>('');
  const [editEditionLabel, setEditEditionLabel] = useState<string>('');
  const [editPubYear, setEditPubYear] = useState<string>('');
  const [isSavingMetadata, setIsSavingMetadata] = useState<boolean>(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete Modal State
  const [deletingTb, setDeletingTb] = useState<TextbookVersionSummary | null>(null);
  const [depSummary, setDepSummary] = useState<TextbookDependencySummary | null>(null);
  const [loadingDeps, setLoadingDeps] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Structure Refresh State
  const [refreshingStructureId, setRefreshingStructureId] = useState<string | null>(null);
  const [actionSuccessMessage, setActionSuccessMessage] = useState<string | null>(null);

  const openEditModal = async (tb: TextbookVersionSummary) => {
    setEditingTb(tb);
    setEditTitle(tb.title);
    setEditGradeId(tb.grade_id || null);
    setEditSubjectId(tb.subject_id || null);
    setEditEditionLabel(tb.edition_label || (tb.edition_year ? `${tb.edition_year}` : ''));
    setEditPubYear(tb.publication_year ? `${tb.publication_year}` : '');
    setEditError(null);

    // Fetch grades and subjects
    const [gRes, sRes] = await Promise.all([apiService.getGrades(), apiService.getSubjects()]);
    if (gRes.ok && gRes.data) setGrades(gRes.data);
    if (sRes.ok && sRes.data) setSubjects(sRes.data.subjects);
  };

  const handleSaveMetadata = async () => {
    if (!editingTb) return;
    setIsSavingMetadata(true);
    setEditError(null);

    const pubYearNum = editPubYear.trim() ? parseInt(editPubYear.trim(), 10) : null;

    const res = await apiService.updateTextbookMetadata(editingTb.id, {
      title: editTitle.trim(),
      grade_id: editGradeId,
      subject_id: editSubjectId,
      edition_label: editEditionLabel.trim() || null,
      publication_year: isNaN(pubYearNum as number) ? null : pubYearNum,
    });

    setIsSavingMetadata(false);
    if (res.ok) {
      setEditingTb(null);
      setActionSuccessMessage(`Updated metadata for "${editTitle}".`);
      setTimeout(() => setActionSuccessMessage(null), 4000);
      onRefresh();
    } else {
      setEditError(res.error || 'Failed to update metadata.');
    }
  };

  const openDeleteModal = async (tb: TextbookVersionSummary) => {
    setDeletingTb(tb);
    setLoadingDeps(true);
    setDeleteError(null);
    const res = await apiService.getTextbookDependencies(tb.id);
    setLoadingDeps(false);
    if (res.ok && res.data) {
      setDepSummary(res.data);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deletingTb) return;
    setIsDeleting(true);
    setDeleteError(null);

    const res = await apiService.deleteTextbook(deletingTb.id);
    setIsDeleting(false);
    if (res.ok) {
      setDeletingTb(null);
      setDepSummary(null);
      setActionSuccessMessage(`Textbook "${deletingTb.title}" was soft-deleted.`);
      setTimeout(() => setActionSuccessMessage(null), 4000);
      onRefresh();
    } else {
      setDeleteError(res.error || 'Failed to delete textbook.');
    }
  };

  const handleRefreshStructure = async (versionId: string, title: string) => {
    setRefreshingStructureId(versionId);
    const res = await apiService.refreshTextbookStructure(versionId);
    setRefreshingStructureId(null);

    if (res.ok) {
      setActionSuccessMessage(`Refreshed curriculum structure for "${title}" (${res.data?.nodes_created || 0} nodes).`);
      setTimeout(() => setActionSuccessMessage(null), 4000);
      onRefresh();
    } else {
      alert(`Structure refresh failed: ${res.error || 'Unknown error'}`);
    }
  };

  return (
    <div className="bg-white border border-lms-border rounded-lg shadow-sm overflow-hidden">
      {/* Toast Notification */}
      {actionSuccessMessage && (
        <div className="bg-emerald-50 border-b border-emerald-200 px-6 py-2.5 text-xs text-emerald-800 font-medium flex items-center gap-2">
          <Check className="w-4 h-4 text-emerald-600" />
          <span>{actionSuccessMessage}</span>
        </div>
      )}

      {/* Table Header Bar */}
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-lms-text-primary">
            Ingested NCTB Textbooks
          </h3>
          <p className="text-xs text-lms-text-secondary mt-0.5">
            Dynamic repository loaded directly from the database ({textbooks.length} active records)
          </p>
        </div>

        <button
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-md border border-slate-200 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Table Content */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200 uppercase tracking-wider text-[11px]">
            <tr>
              <th className="px-6 py-3">Book Title</th>
              <th className="px-4 py-3">Class / Grade</th>
              <th className="px-4 py-3">Subject</th>
              <th className="px-4 py-3">Domain</th>
              <th className="px-4 py-3">Edition</th>
              <th className="px-4 py-3">Pages</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-6 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {textbooks.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-6 py-10 text-center text-slate-400">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <BookOpen className="w-8 h-8 text-slate-300 stroke-[1.5]" />
                    <p className="text-xs font-medium">No active NCTB textbooks found.</p>
                    <p className="text-[11px] text-slate-400">Upload a textbook PDF above to inspect the document.</p>
                  </div>
                </td>
              </tr>
            ) : (
              textbooks.map((tb) => {
                const isSelected = tb.id === selectedId;
                const isSuccess = tb.ingestion_status === 'COMPLETED';
                const isPartial = tb.ingestion_status === 'PARTIAL';
                const isReady = !!tb.assessment_ready;
                
                const REASON_LABELS: Record<string, string> = {
                  TEXTBOOK_DELETED: 'This textbook has been deleted.',
                  INGESTION_INCOMPLETE: 'Textbook ingestion is incomplete.',
                  GRADE_NOT_ASSIGNED: 'Assign Class / Grade first.',
                  SUBJECT_NOT_RESOLVED: 'Assign a subject first.',
                  SUBJECT_NOT_SUPPORTED: 'Assessment generation is not supported for this subject domain.',
                  STRUCTURE_NEEDS_REFRESH: 'Textbook structure needs refresh.',
                  PDF_NOT_AVAILABLE: 'The textbook PDF file is not available.',
                };

                const formattedReasons = (tb.assessment_readiness_reasons || [])
                  .map((r) => REASON_LABELS[r] || r)
                  .join(' • ');

                const readinessTooltip = isReady
                  ? 'Eligible for dynamic assessment & MCQ generation'
                  : (formattedReasons || 'Textbook is missing required metadata or valid structure');

                return (
                  <tr
                    key={tb.id}
                    className={`hover:bg-slate-50/80 transition-colors ${
                      isSelected ? 'bg-blue-50/60 font-medium' : ''
                    }`}
                  >
                    <td className="px-6 py-3.5 text-slate-900 font-semibold flex items-center gap-2">
                      <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                      <span className="truncate max-w-[200px]" title={tb.title}>
                        {tb.title}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-slate-700">
                      {tb.grade_info?.display_name || tb.grade || (
                        <span className="text-amber-600 italic flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" />
                          Unassigned
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-slate-700">
                      {tb.subject || <span className="text-slate-400 italic">Unassigned</span>}
                    </td>
                    <td className="px-4 py-3.5">
                      {tb.domain ? (
                        <span className="px-2 py-0.5 text-[10px] font-semibold rounded bg-slate-100 text-slate-700 border border-slate-200">
                          {tb.domain}
                        </span>
                      ) : (
                        <span className="text-slate-400 italic">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-slate-600">
                      {tb.edition_label || (tb.edition_year ? `${tb.edition_year}` : <span className="text-slate-400 italic">—</span>)}
                    </td>
                    <td className="px-4 py-3.5 text-slate-700 font-mono">
                      {tb.page_count}
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium border ${
                          isSuccess
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : isPartial
                            ? 'bg-amber-50 text-amber-700 border-amber-200'
                            : 'bg-rose-50 text-rose-700 border-rose-200'
                        }`}
                      >
                        {isSuccess && <CheckCircle2 className="w-3 h-3" />}
                        {isPartial && <AlertTriangle className="w-3 h-3" />}
                        {!isSuccess && !isPartial && <XCircle className="w-3 h-3" />}
                        <span>{tb.ingestion_status}</span>
                      </span>
                    </td>
                    <td className="px-6 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => onSelect(tb.id)}
                          className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition-colors ${
                            isSelected
                              ? 'bg-slate-800 text-white'
                              : 'bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200'
                          }`}
                          title="Inspect PDF Structure & Content"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>{isSelected ? 'Viewing' : 'Inspect'}</span>
                        </button>

                        <button
                          onClick={() => isReady && onGenerateMCQs && onGenerateMCQs(tb.id)}
                          disabled={!isReady}
                          title={readinessTooltip}
                          className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition-colors ${
                            isReady
                              ? 'bg-lms-blue-600 text-white hover:bg-lms-blue-700 shadow-2xs'
                              : 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                          }`}
                        >
                          <Sparkles className="w-3 h-3" />
                          <span>MCQs</span>
                        </button>

                        <button
                          onClick={() => openEditModal(tb)}
                          className="p-1 rounded text-slate-500 hover:text-slate-800 hover:bg-slate-100 border border-transparent hover:border-slate-200 transition-colors"
                          title="Edit Metadata (Grade, Subject, Edition)"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>

                        <button
                          onClick={() => handleRefreshStructure(tb.id, tb.title)}
                          disabled={refreshingStructureId === tb.id}
                          className="p-1 rounded text-slate-500 hover:text-indigo-700 hover:bg-indigo-50 border border-transparent hover:border-indigo-200 transition-colors"
                          title="Refresh Derived Curriculum Tree from PDF"
                        >
                          <Layers className={`w-3.5 h-3.5 ${refreshingStructureId === tb.id ? 'animate-spin text-indigo-600' : ''}`} />
                        </button>

                        <button
                          onClick={() => openDeleteModal(tb)}
                          className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 border border-transparent hover:border-rose-200 transition-colors"
                          title="Delete Textbook"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Edit Metadata Modal */}
      {editingTb && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl border border-slate-200 max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <Edit2 className="w-4 h-4 text-lms-blue-600" />
                <span>Edit Textbook Metadata</span>
              </h3>
              <button
                onClick={() => setEditingTb(null)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {editError && (
              <div className="bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 rounded-lg flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{editError}</span>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                  Book Title
                </label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                  Class / Grade <span className="text-rose-500">*</span>
                </label>
                <select
                  value={editGradeId || ''}
                  onChange={(e) => setEditGradeId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
                >
                  <option value="">-- Select Class / Grade --</option>
                  {grades.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.display_name || g.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                  Subject
                </label>
                <select
                  value={editSubjectId || ''}
                  onChange={(e) => setEditSubjectId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
                >
                  <option value="">-- Select Subject --</option>
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.domain})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Edition Label
                  </label>
                  <input
                    type="text"
                    value={editEditionLabel}
                    onChange={(e) => setEditEditionLabel(e.target.value)}
                    placeholder="e.g. First Edition"
                    className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                    Publication Year
                  </label>
                  <input
                    type="number"
                    value={editPubYear}
                    onChange={(e) => setEditPubYear(e.target.value)}
                    placeholder="e.g. 2024"
                    className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setEditingTb(null)}
                disabled={isSavingMetadata}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveMetadata}
                disabled={isSavingMetadata}
                className="px-4 py-1.5 text-xs font-semibold bg-lms-blue-600 text-white rounded-lg hover:bg-lms-blue-700 transition-colors disabled:opacity-50"
              >
                {isSavingMetadata ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deletingTb && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl border border-slate-200 max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-rose-600 flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                <span>Delete Textbook Version</span>
              </h3>
              <button
                onClick={() => {
                  setDeletingTb(null);
                  setDepSummary(null);
                }}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {deleteError && (
              <div className="bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 rounded-lg flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to soft-delete <span className="font-bold text-slate-800">"{deletingTb.title}"</span>?
            </p>

            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-1.5">
              <p className="font-semibold text-slate-700">Dependency Impact:</p>
              {loadingDeps ? (
                <p className="text-slate-400 italic">Analyzing dependencies...</p>
              ) : depSummary ? (
                <ul className="text-slate-600 space-y-1 text-[11px]">
                  <li>• Curriculum Nodes: <span className="font-semibold">{depSummary.curriculum_nodes_count}</span></li>
                  <li>• Activity Nodes: <span className="font-semibold">{depSummary.activity_nodes_count}</span></li>
                  <li>• Question Bank Items: <span className="font-semibold">{depSummary.question_bank_items_count}</span> (preserved)</li>
                  <li>• Saved Papers: <span className="font-semibold">{depSummary.question_sets_count}</span> (preserved)</li>
                </ul>
              ) : null}
              <p className="text-[11px] text-slate-500 pt-1">
                Soft-deleting removes this version from active assessment listings while preserving historical saved papers and allowing re-ingestion of this exact PDF later.
              </p>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => {
                  setDeletingTb(null);
                  setDepSummary(null);
                }}
                disabled={isDeleting}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                className="px-4 py-1.5 text-xs font-semibold bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors disabled:opacity-50"
              >
                {isDeleting ? 'Deleting...' : 'Confirm Soft Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

