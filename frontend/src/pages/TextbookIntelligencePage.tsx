import React, { useState, useEffect, useRef } from 'react';
import {
  Upload,
  FileText,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { apiService } from '../services/api';
import {
  GradeResponse,
  IngestionResponse,
  SubjectSummary,
  TextbookVersionSummary,
} from '../types/api';
import { IngestionSummaryCard } from '../components/IngestionSummaryCard';
import { IngestedTextbooksTable } from '../components/IngestedTextbooksTable';
import { TextbookWorkspace } from '../components/TextbookWorkspace';

interface TextbookIntelligencePageProps {
  onNavigateToAssessment?: (versionId: string) => void;
}

export const TextbookIntelligencePage: React.FC<TextbookIntelligencePageProps> = ({
  onNavigateToAssessment,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [grades, setGrades] = useState<GradeResponse[]>([]);
  const [loadingGrades, setLoadingGrades] = useState<boolean>(false);
  const [selectedGradeId, setSelectedGradeId] = useState<number | null>(null);

  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [loadingSubjects, setLoadingSubjects] = useState<boolean>(false);
  const [selectedSubjectId, setSelectedSubjectId] = useState<number | null>(null);

  const [uploading, setUploading] = useState<boolean>(false);
  const [uploadStepMessage, setUploadStepMessage] = useState<string>('');
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [recentIngestion, setRecentIngestion] = useState<IngestionResponse | null>(null);
  const [textbooks, setTextbooks] = useState<TextbookVersionSummary[]>([]);
  const [loadingTextbooks, setLoadingTextbooks] = useState<boolean>(false);

  // Selected version driving the dedicated Textbook Inspection Workspace
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load available textbooks, grades, and subjects on mount
  useEffect(() => {
    loadTextbooks();
    loadGrades();
    loadSubjects();
  }, []);

  const loadGrades = async () => {
    setLoadingGrades(true);
    const res = await apiService.getGrades();
    setLoadingGrades(false);
    if (res.ok && res.data) {
      setGrades(res.data);
    }
  };

  const loadSubjects = async () => {
    setLoadingSubjects(true);
    const res = await apiService.getSubjects();
    setLoadingSubjects(false);
    if (res.ok && res.data) {
      setSubjects(res.data.subjects);
    }
  };

  const loadTextbooks = async () => {
    setLoadingTextbooks(true);
    const res = await apiService.getTextbookVersions();
    setLoadingTextbooks(false);
    if (res.ok && res.data) {
      setTextbooks(res.data);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setUploadError('Only PDF files (.pdf) are supported.');
        setSelectedFile(null);
        return;
      }
      setSelectedFile(file);
      setUploadError(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setUploadError('Only PDF files (.pdf) are supported.');
        setSelectedFile(null);
        return;
      }
      setSelectedFile(file);
      setUploadError(null);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    if (!selectedGradeId) {
      setUploadError('Please select a Class / Grade before ingesting the textbook.');
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadStepMessage('Uploading PDF stream to backend...');

    const stepTimer = setTimeout(() => {
      setUploadStepMessage('Extracting native PDF text, geometry & evaluating quality...');
    }, 1200);

    const stepTimer2 = setTimeout(() => {
      setUploadStepMessage('Executing WinOCR fallback & discovering curriculum hierarchy...');
    }, 3000);

    const res = await apiService.ingestTextbook(selectedFile, selectedGradeId, selectedSubjectId);

    clearTimeout(stepTimer);
    clearTimeout(stepTimer2);
    setUploading(false);
    setUploadStepMessage('');

    if (res.ok && res.data) {
      setRecentIngestion(res.data);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      // Refresh textbooks list and automatically open workspace
      await loadTextbooks();
      await loadGrades();
      setSelectedVersionId(res.data.version_id);
    } else {
      let displayError = res.error || 'Ingestion could not be completed. Please try again or check the server logs.';
      if (res.errorCode === 'DUPLICATE_PDF') {
        displayError = 'This exact textbook PDF has already been ingested.';
        loadTextbooks();
      } else if (
        displayError.includes('sqlite') ||
        displayError.includes('SQLAlchemy') ||
        displayError.includes('SELECT') ||
        displayError.includes('INSERT') ||
        displayError.includes('Traceback') ||
        displayError.includes('File ') ||
        displayError.includes('IntegrityError')
      ) {
        displayError = 'Ingestion could not be completed. Please try again or check the server logs.';
      }
      setUploadError(displayError);
    }
  };

  // If a textbook is selected, render the dedicated Textbook Inspection Workspace
  if (selectedVersionId) {
    return (
      <TextbookWorkspace
        versionId={selectedVersionId}
        onBack={() => {
          setSelectedVersionId(null);
          loadTextbooks();
        }}
        onGenerateMCQs={onNavigateToAssessment}
      />
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Title Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-lms-border pb-4">
        <div>
          <h2 className="text-xl font-bold text-lms-text-primary tracking-tight">
            Textbook Intelligence
          </h2>
          <p className="text-xs text-lms-text-secondary mt-1">
            Upload, Ingestion, OCR & Original PDF Preview
          </p>
        </div>
      </div>

      {/* Upload Zone */}
      <div className="bg-white border border-lms-border rounded-lg shadow-sm p-6">
        <div className="max-w-3xl">
          <h3 className="text-sm font-bold text-lms-text-primary mb-1 flex items-center gap-2">
            <Upload className="w-4 h-4 text-lms-blue-600" />
            <span>Ingest NCTB Textbook PDF</span>
          </h3>
          <p className="text-xs text-lms-text-secondary mb-4 leading-relaxed">
            Upload an English-language NCTB textbook PDF. The engine automatically processes text extraction,
            metadata resolution, OCR fallback, and canonical curriculum parsing.
          </p>

          {/* Authoritative Class / Grade & Subject Selectors */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label htmlFor="ingest-grade-select" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                Class / Grade <span className="text-rose-500">*</span>
              </label>
              <select
                id="ingest-grade-select"
                value={selectedGradeId || ''}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : null;
                  setSelectedGradeId(val);
                  if (val) setUploadError(null);
                }}
                disabled={uploading || loadingGrades}
                className="w-full text-xs font-medium bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-800 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none transition-colors"
              >
                <option value="">{loadingGrades ? 'Loading grades...' : '-- Select Authoritative Class / Grade --'}</option>
                {grades.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.display_name || g.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="ingest-subject-select" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                Subject <span className="text-slate-400 font-normal">(Optional Override)</span>
              </label>
              <select
                id="ingest-subject-select"
                value={selectedSubjectId || ''}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : null;
                  setSelectedSubjectId(val);
                }}
                disabled={uploading || loadingSubjects}
                className="w-full text-xs font-medium bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-800 focus:ring-2 focus:ring-lms-blue-500 focus:outline-none transition-colors"
              >
                <option value="">Auto Detect (Recommended)</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.domain})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Drag & Drop Area */}
          <div
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all ${
              selectedFile
                ? 'border-lms-blue-500 bg-blue-50/40'
                : 'border-slate-300 hover:border-lms-blue-400 bg-slate-50/50 hover:bg-slate-50'
            } ${uploading ? 'opacity-60 pointer-events-none' : ''}`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
              className="hidden"
            />

            <div className="flex flex-col items-center justify-center gap-2">
              <div className="p-3 bg-white rounded-full shadow-xs border border-slate-200 text-lms-blue-600">
                <FileText className="w-6 h-6" />
              </div>
              {selectedFile ? (
                <div>
                  <p className="text-xs font-bold text-slate-800">{selectedFile.name}</p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB • Ready for Ingestion
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-xs font-semibold text-slate-700">
                    Click to browse or drag and drop NCTB PDF here
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    Supports arbitrary editions & grades (PDF format, max 100MB)
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Upload Progress Indeterminate State */}
          {uploading && (
            <div className="mt-4 p-4 rounded-md bg-blue-50 border border-blue-200 space-y-2">
              <div className="flex items-center gap-2.5 text-xs font-semibold text-lms-blue-900">
                <Loader2 className="w-4 h-4 animate-spin text-lms-blue-600" />
                <span>{uploadStepMessage || 'Processing textbook ingestion...'}</span>
              </div>
              <div className="w-full bg-blue-200/60 rounded-full h-1.5 overflow-hidden">
                <div className="bg-lms-blue-600 h-1.5 rounded-full animate-pulse w-full" />
              </div>
              <p className="text-[11px] text-blue-700">
                Running stream hashing, native extraction, and OCR fallback in background thread...
              </p>
            </div>
          )}

          {/* Error Banner */}
          {uploadError && (
            <div className="mt-4 p-3.5 rounded-md bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold">Ingestion Failed</p>
                <p className="leading-relaxed">{uploadError}</p>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              className="inline-flex items-center gap-2 px-5 py-2 text-xs font-bold text-white bg-lms-blue-600 hover:bg-lms-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-md transition-colors shadow-sm"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Ingesting PDF...</span>
                </>
              ) : (
                <>
                  <Upload className="w-3.5 h-3.5" />
                  <span>Start Ingestion</span>
                </>
              )}
            </button>

            {selectedFile && !uploading && (
              <button
                onClick={() => {
                  setSelectedFile(null);
                  setUploadError(null);
                  if (fileInputRef.current) fileInputRef.current.value = '';
                }}
                className="px-3 py-2 text-xs font-medium text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-md transition-colors"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Live Ingestion Results */}
      {recentIngestion && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Latest Ingestion Result
          </h3>
          <IngestionSummaryCard
            result={recentIngestion}
            onInspect={(id) => setSelectedVersionId(id)}
          />
        </div>
      )}

      {/* Ingested Textbooks Dynamic Table */}
      <IngestedTextbooksTable
        textbooks={textbooks}
        loading={loadingTextbooks}
        onRefresh={loadTextbooks}
        onSelect={(id) => setSelectedVersionId(id)}
        onGenerateMCQs={onNavigateToAssessment}
        selectedId={selectedVersionId}
      />
    </div>
  );
};

