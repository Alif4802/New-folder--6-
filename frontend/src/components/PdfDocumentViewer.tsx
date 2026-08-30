import React, { useState } from 'react';
import {
  FileText,
  ExternalLink,
  AlertTriangle,
  RefreshCw,
  Info,
  Loader2,
} from 'lucide-react';
import { apiService } from '../services/api';

interface PdfDocumentViewerProps {
  versionId: string;
  targetPdfPage?: number;
  targetBookPageLabel?: string | null;
  isNavigating?: boolean;
  pdfAvailable: boolean;
  title?: string;
  onIframeLoaded?: () => void;
  onReload?: () => void;
}

export const PdfDocumentViewer: React.FC<PdfDocumentViewerProps> = ({
  versionId,
  targetPdfPage = 1,
  targetBookPageLabel,
  isNavigating = false,
  pdfAvailable,
  title,
  onIframeLoaded,
  onReload,
}) => {
  const [loadError, setLoadError] = useState<boolean>(false);

  const basePdfUrl = apiService.getTextbookPdfUrl(versionId);
  const pdfUrlWithPage = `${basePdfUrl}#page=${targetPdfPage}`;
  const humanPageText = targetBookPageLabel ? `Book page ${targetBookPageLabel}` : `Page ${targetPdfPage}`;
  const targetLabel = targetBookPageLabel || targetPdfPage;

  return (
    <div className="bg-white border border-lms-border rounded-lg shadow-sm flex flex-col h-full overflow-hidden">
      {/* Viewer Toolbar Header */}
      <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded bg-blue-100/80 text-lms-blue-700">
            <FileText className="w-4 h-4" />
          </div>
          <div className="truncate flex items-center gap-2">
            <span className="text-xs font-bold text-slate-800 truncate" title={title || 'Original Textbook PDF'}>
              {title || 'Original NCTB Textbook PDF'}
            </span>
            <span className="px-1.5 py-0.5 rounded bg-blue-50 text-lms-blue-700 font-mono text-[10px] font-semibold border border-blue-200">
              {humanPageText}
            </span>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* Open in New Tab Action */}
          <a
            href={pdfUrlWithPage}
            target="_blank"
            rel="noopener noreferrer"
            title="Open PDF in a new browser tab"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white hover:bg-slate-100 rounded border border-slate-200 transition-colors shadow-2xs"
          >
            <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
            <span>Open in New Tab</span>
          </a>

          {/* Reload Button */}
          {onReload && (
            <button
              onClick={() => {
                setLoadError(false);
                onReload();
              }}
              title="Reload PDF stream"
              className="p-1.5 text-slate-500 hover:text-slate-700 hover:bg-slate-200/60 rounded border border-transparent transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* PDF Viewport Shell */}
      <div className="pdf-viewer-shell flex-1 relative bg-slate-50 min-h-[650px] lg:min-h-[750px] flex flex-col overflow-hidden">
        {/* Solid Opaque Sibling Loading Overlay during TOC Jumps */}
        {isNavigating && (
          <div
            id="pdf-navigation-overlay"
            className="pdf-navigation-overlay absolute inset-0 bg-slate-50 z-30 flex flex-col items-center justify-center p-8 transition-opacity duration-300 pointer-events-none"
            style={{ zIndex: 30 }}
          >
            <div className="bg-white px-6 py-5 rounded-2xl shadow-md border border-slate-200/90 flex flex-col items-center gap-3 text-center max-w-xs">
              <div className="p-3 bg-blue-50 text-lms-blue-600 rounded-full border border-blue-100">
                <Loader2 className="w-6 h-6 animate-spin text-lms-blue-600" />
              </div>
              <div className="space-y-1">
                <h4 id="loading-overlay-message" className="text-sm font-bold text-slate-800 tracking-tight">
                  Opening page {targetLabel}...
                </h4>
                <p className="text-xs text-slate-500 font-medium leading-normal">
                  Loading original textbook page in native PDF viewer
                </p>
              </div>
            </div>
          </div>
        )}

        {!pdfAvailable || loadError ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-slate-50">
            <div className="max-w-md p-6 bg-white rounded-lg border border-slate-200 shadow-sm space-y-3">
              <div className="w-10 h-10 mx-auto rounded-full bg-rose-50 text-rose-600 flex items-center justify-center border border-rose-200">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-bold text-slate-800">
                PDF Document Unavailable
              </h4>
              <p className="text-xs text-slate-600 leading-relaxed">
                The original PDF file could not be located on the server filesystem.
              </p>
              <div className="pt-2 flex justify-center gap-2">
                <a
                  href={basePdfUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-lms-blue-600 hover:bg-lms-blue-700 rounded-md transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>Try Direct Stream URL</span>
                </a>
              </div>
            </div>
          </div>
        ) : (
          <iframe
            key={`${versionId}-p${targetPdfPage}`}
            id="nctb-pdf-iframe"
            src={pdfUrlWithPage}
            title="NCTB Original PDF Viewer"
            className="w-full h-full min-h-[650px] lg:min-h-[750px] border-0 rounded-b-md bg-white flex-1"
            onLoad={onIframeLoaded}
            onError={() => setLoadError(true)}
          />


        )}
      </div>

      {/* Footer Info Notice */}
      <div className="px-4 py-1.5 bg-slate-50 border-t border-slate-200 text-[11px] text-slate-500 flex items-center justify-between">
        <span className="flex items-center gap-1">
          <Info className="w-3 h-3 text-slate-400" />
          Native browser PDF stream
        </span>
        <span className="text-slate-400">PDF Document Inspection</span>
      </div>
    </div>
  );
};
