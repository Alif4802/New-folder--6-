import React from 'react';
import { PDFMetadataResponse } from '../types/api';
import {
  X,
  FileCheck,
  AlertTriangle,
} from 'lucide-react';

interface TextbookMetadataModalProps {
  metadata: PDFMetadataResponse | null;
  title?: string;
  grade?: string | null;
  subject?: string | null;
  editionYear?: number | null;
  isOpen: boolean;
  onClose: () => void;
}

export const TextbookMetadataModal: React.FC<TextbookMetadataModalProps> = ({
  metadata,
  title,
  grade,
  subject,
  editionYear,
  isOpen,
  onClose,
}) => {
  if (!isOpen || !metadata) return null;

  const detectedTitle = title || (metadata.detected_metadata?.title as string) || 'NCTB Textbook';
  const detectedGrade = grade || (metadata.detected_metadata?.grade as string) || 'Not specified';
  const detectedSubject = subject || (metadata.detected_metadata?.subject as string) || 'General';
  const detectedYear = editionYear || (metadata.detected_metadata?.edition_year as number) || null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[85vh] flex flex-col overflow-hidden border border-slate-200">
        {/* Modal Header */}
        <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-blue-100 text-lms-blue-700">
              <FileCheck className="w-4 h-4" />
            </div>
            <div>
              <h4 className="text-sm font-bold text-slate-800">
                Processing Details
              </h4>
              <p className="text-[11px] text-slate-500">
                Textbook ingestion, page extraction, and detection summary
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto space-y-4 text-xs">
          {/* File & Metadata Properties Card */}
          <div className="grid grid-cols-2 gap-3 p-3.5 bg-slate-50 rounded-md border border-slate-200">
            <div className="col-span-2">
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Detected Title</span>
              <p className="font-bold text-slate-900">{detectedTitle}</p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Class / Grade</span>
              <p className="font-semibold text-slate-800">{detectedGrade}</p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Subject</span>
              <p className="font-semibold text-slate-800">{detectedSubject}</p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Edition / Year</span>
              <p className="font-semibold text-slate-800">
                {detectedYear ? `Edition ${detectedYear}` : 'Not specified'}
              </p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Original Filename</span>
              <p className="font-semibold text-slate-800 truncate" title={metadata.source_filename}>
                {metadata.source_filename}
              </p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Total Pages</span>
              <p className="font-semibold text-slate-800 font-mono">{metadata.page_count} pages</p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">OCR Pages</span>
              <p className="font-semibold text-slate-800 font-mono">
                {metadata.ocr_pages_count} pages
              </p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">Ingestion Status</span>
              <p className="font-semibold text-slate-800 flex items-center gap-1.5 mt-0.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    metadata.ingestion_status === 'COMPLETED'
                      ? 'bg-emerald-500'
                      : metadata.ingestion_status === 'PARTIAL'
                      ? 'bg-amber-500'
                      : 'bg-rose-500'
                  }`}
                />
                <span>{metadata.ingestion_status}</span>
              </p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 uppercase font-semibold">PDF File Stream</span>
              <p className="font-semibold text-slate-800">
                {metadata.pdf_available ? (
                  <span className="text-emerald-700">Available</span>
                ) : (
                  <span className="text-rose-700">Not Found</span>
                )}
              </p>
            </div>
          </div>

          {/* Recorded Warnings */}
          {metadata.warnings && metadata.warnings.length > 0 && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-md space-y-1.5 text-amber-900">
              <div className="flex items-center gap-1.5 text-xs font-bold">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                <span>Processing Warnings ({metadata.warnings.length})</span>
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-[11px]">
                {metadata.warnings.map((w: string, idx: number) => (
                  <li key={idx} className="leading-relaxed">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Error Message */}
          {metadata.error_message && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-md space-y-1 text-rose-900">
              <span className="text-[10px] uppercase font-bold text-rose-700">Recorded Error</span>
              <p className="text-xs leading-relaxed">{metadata.error_message}</p>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-3 border-t border-slate-200 bg-slate-50 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-100 rounded border border-slate-200 transition-colors shadow-2xs"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

