import React from 'react';
import { IngestionResponse } from '../types/api';
import { CheckCircle2, AlertTriangle, XCircle, BookOpen, Layers, FileText, Scan, Eye } from 'lucide-react';

interface IngestionSummaryCardProps {
  result: IngestionResponse;
  onInspect: (versionId: string) => void;
}

export const IngestionSummaryCard: React.FC<IngestionSummaryCardProps> = ({ result, onInspect }) => {
  const isSuccess = result.ingestion_status === 'COMPLETED';
  const isPartial = result.ingestion_status === 'PARTIAL';
  const isFailed = result.ingestion_status === 'FAILED';

  return (
    <div className="bg-white border border-lms-border rounded-lg shadow-sm p-6 space-y-5">
      {/* Top Status Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          {isSuccess && <CheckCircle2 className="w-6 h-6 text-emerald-600 flex-shrink-0" />}
          {isPartial && <AlertTriangle className="w-6 h-6 text-amber-600 flex-shrink-0" />}
          {isFailed && <XCircle className="w-6 h-6 text-rose-600 flex-shrink-0" />}
          <div>
            <h3 className="text-base font-bold text-lms-text-primary">
              {result.title}
            </h3>
            <p className="text-xs text-lms-text-secondary mt-0.5">
              {result.detected_subject || 'Subject Undetected'} • {result.detected_grade || 'Grade Undetected'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`text-xs px-2.5 py-1 rounded-full font-semibold border ${
              isSuccess
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : isPartial
                ? 'bg-amber-50 text-amber-700 border-amber-200'
                : 'bg-rose-50 text-rose-700 border-rose-200'
            }`}
          >
            {result.ingestion_status}
          </span>
          {result.detected_domain && (
            <span className="text-xs px-2.5 py-1 rounded-full font-medium bg-blue-50 text-lms-blue-600 border border-blue-200">
              {result.detected_domain}
            </span>
          )}
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3 bg-slate-50 border border-slate-100 rounded-md">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <FileText className="w-3.5 h-3.5" />
            <span>Total Pages</span>
          </div>
          <div className="text-lg font-bold text-slate-800">{result.page_count}</div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-100 rounded-md">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <BookOpen className="w-3.5 h-3.5" />
            <span>Units / Chapters</span>
          </div>
          <div className="text-lg font-bold text-slate-800">{result.unit_count}</div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-100 rounded-md">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <Layers className="w-3.5 h-3.5" />
            <span>Lessons</span>
          </div>
          <div className="text-lg font-bold text-slate-800">{result.lesson_count}</div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-100 rounded-md">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <Scan className="w-3.5 h-3.5" />
            <span>OCR Pages</span>
          </div>
          <div className="text-lg font-bold text-slate-800">
            {result.ocr_pages_count} {result.ocr_pages_count === 1 ? 'page' : 'pages'}
          </div>
        </div>
      </div>

      {/* Warnings List */}
      {result.warnings && result.warnings.length > 0 && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-md space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-amber-900">
            <AlertTriangle className="w-4 h-4 text-amber-700 flex-shrink-0" />
            <span>Processing Warnings ({result.warnings.length})</span>
          </div>
          <ul className="text-xs text-amber-800 list-disc list-inside space-y-0.5 pl-1">
            {result.warnings.map((warn, i) => (
              <li key={i}>{warn}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Action Footer */}
      <div className="flex justify-end pt-2">
        <button
          onClick={() => onInspect(result.version_id)}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-lms-blue-600 hover:bg-lms-blue-700 rounded-md transition-colors shadow-sm"
        >
          <Eye className="w-4 h-4" />
          <span>Inspect PDF</span>
        </button>
      </div>
    </div>
  );
};

