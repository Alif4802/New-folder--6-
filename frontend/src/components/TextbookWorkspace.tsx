import React, { useState, useEffect, useRef } from 'react';
import {
  PDFMetadataResponse,
  TextbookVersionSummary,
} from '../types/api';
import { apiService } from '../services/api';
import { PdfDocumentViewer } from './PdfDocumentViewer';
import { TableOfContentsViewer } from './TableOfContentsViewer';
import { TextbookMetadataModal } from './TextbookMetadataModal';
import {
  ArrowLeft,
  BookOpen,
  AlertTriangle,
  FileCheck,
  ExternalLink,
  Loader2,
  XCircle,
  Calendar,
  Layers,
  GraduationCap,
  Sparkles,
  Scan,
} from 'lucide-react';

interface TextbookWorkspaceProps {
  versionId: string;
  onBack: () => void;
  onGenerateMCQs?: (versionId: string) => void;
}

export const TextbookWorkspace: React.FC<TextbookWorkspaceProps> = ({
  versionId,
  onBack,
  onGenerateMCQs,
}) => {
  const [metadata, setMetadata] = useState<PDFMetadataResponse | null>(null);
  const [versionSummary, setVersionSummary] = useState<TextbookVersionSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Timing constants for smooth native PDF transition
  // Chrome's PDFium plugin initialization on page remount takes ~1.3-1.8s
  const PDF_NAV_VISUAL_READY_GRACE_MS = 1800; // Visual-readiness grace period to mask plugin initialization
  const PDF_NAV_MAX_TIMEOUT_MS = 3800; // Upper bound safety fallback


  // Synchronized target PDF page, book page label, and active TOC navigation item
  const [targetPdfPage, setTargetPdfPage] = useState<number>(1);
  const [targetBookPageLabel, setTargetBookPageLabel] = useState<string | null>(null);
  const [activeTocKey, setActiveTocKey] = useState<string | null>(null);
  const [isNavigating, setIsNavigating] = useState<boolean>(false);

  // Navigation tokens & start time to guarantee rapid clicks resolve cleanly to the latest request
  const navTokenRef = useRef<number>(0);
  const navStartTimeRef = useRef<number>(0);
  const navTimeoutRef = useRef<any>(null);

  // Processing details modal visibility
  const [isMetadataModalOpen, setIsMetadataModalOpen] = useState<boolean>(false);

  useEffect(() => {
    setTargetPdfPage(1);
    setTargetBookPageLabel(null);
    setActiveTocKey(null);
    setIsNavigating(false);
    loadWorkspaceData(versionId);

    return () => {
      if (navTimeoutRef.current) {
        clearTimeout(navTimeoutRef.current);
      }
    };
  }, [versionId]);

  const loadWorkspaceData = async (vid: string) => {
    setLoading(true);
    setLoadError(null);

    const [metaRes, versionsRes] = await Promise.all([
      apiService.getPDFMetadata(vid),
      apiService.getTextbookVersions(),
    ]);

    setLoading(false);

    if (metaRes.ok && metaRes.data) {
      setMetadata(metaRes.data);
    } else {
      setLoadError(metaRes.error || 'Failed to retrieve textbook metadata.');
    }

    if (versionsRes.ok && versionsRes.data) {
      const match = versionsRes.data.find((v) => v.id === vid);
      if (match) {
        setVersionSummary(match);
      }
    }
  };

  const handleSelectPage = (pdfPage: number, itemKey: string, bookLabel?: string | null) => {
    // 1. Immediately update active TOC selection
    setActiveTocKey(itemKey);

    // 2. Increment request token to discard stale iframe load events
    const token = ++navTokenRef.current;
    navStartTimeRef.current = Date.now();
    setTargetPdfPage(pdfPage);
    setTargetBookPageLabel(bookLabel || null);
    setIsNavigating(true);

    // 3. Centralized fallback timeout in case browser PDF plugin suppresses onLoad
    if (navTimeoutRef.current) {
      clearTimeout(navTimeoutRef.current);
    }
    navTimeoutRef.current = setTimeout(() => {
      if (navTokenRef.current === token) {
        setIsNavigating(false);
      }
    }, PDF_NAV_MAX_TIMEOUT_MS);
  };

  const handleIframeLoaded = () => {
    const token = navTokenRef.current;
    const elapsed = Date.now() - navStartTimeRef.current;
    // Chrome's native PDF plugin fires iframe onLoad before rendering the PDF canvas.
    // Maintain overlay for minimum grace period to smoothly cover the plugin initialization.
    const remainingGrace = Math.max(0, PDF_NAV_VISUAL_READY_GRACE_MS - elapsed);

    if (navTimeoutRef.current) {
      clearTimeout(navTimeoutRef.current);
    }

    navTimeoutRef.current = setTimeout(() => {
      if (navTokenRef.current === token) {
        setIsNavigating(false);
      }
    }, remainingGrace);
  };



  if (loading) {
    return (
      <div className="bg-white border border-lms-border rounded-lg p-16 text-center flex flex-col items-center justify-center gap-3 shadow-sm">
        <Loader2 className="w-8 h-8 animate-spin text-lms-blue-600" />
        <p className="text-xs font-semibold text-slate-700">Loading Textbook Workspace...</p>
        <p className="text-[11px] text-slate-400">Loading textbook metadata, navigation TOC, and PDF stream...</p>
      </div>
    );
  }

  if (loadError || !metadata) {
    return (
      <div className="bg-white border border-rose-200 rounded-lg p-10 shadow-sm space-y-4">
        <div className="flex items-center gap-3 text-rose-700">
          <XCircle className="w-6 h-6 flex-shrink-0" />
          <div>
            <h3 className="text-sm font-bold">Failed to Load Textbook Workspace</h3>
            <p className="text-xs text-rose-600 mt-0.5">{loadError || 'Textbook record not found.'}</p>
          </div>
        </div>

        <div className="pt-2 flex items-center gap-3">
          <button
            onClick={onBack}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-md transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Return to Textbooks List</span>
          </button>
          <button
            onClick={() => loadWorkspaceData(versionId)}
            className="px-3 py-1.5 text-xs font-medium text-white bg-lms-blue-600 hover:bg-lms-blue-700 rounded-md transition-colors"
          >
            Retry Loading
          </button>
        </div>
      </div>
    );
  }

  const detectedTitle =
    versionSummary?.title ||
    (metadata.detected_metadata?.title as string) ||
    metadata.source_filename ||
    'NCTB Textbook';

  const detectedGrade =
    versionSummary?.grade ||
    (metadata.detected_metadata?.grade as string) ||
    'Class Not Detected';

  const detectedSubject =
    versionSummary?.subject ||
    (metadata.detected_metadata?.subject as string) ||
    'Subject Not Detected';

  const detectedYear =
    versionSummary?.edition_year ||
    (metadata.detected_metadata?.edition_year as number) ||
    null;

  const isPartial = metadata.ingestion_status === 'PARTIAL';
  const isFailed = metadata.ingestion_status === 'FAILED';
  const directPdfUrl = apiService.getTextbookPdfUrl(versionId);

  return (
    <div className="space-y-4 max-w-7xl mx-auto">
      {/* Top Workspace Header Bar */}
      <div className="bg-white border border-lms-border rounded-lg shadow-sm p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-lms-blue-700 hover:underline transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Textbooks</span>
            </button>
            <span className="text-slate-300">•</span>
            <span
              className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${
                metadata.ingestion_status === 'COMPLETED'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : isPartial
                  ? 'bg-amber-50 text-amber-700 border-amber-200'
                  : 'bg-rose-50 text-rose-700 border-rose-200'
              }`}
            >
              {metadata.ingestion_status}
            </span>
          </div>

          <h2 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
            {detectedTitle}
          </h2>

          {/* Clean Metadata Chips Bar */}
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
            <span className="flex items-center gap-1">
              <GraduationCap className="w-3.5 h-3.5 text-slate-400" />
              <span>{detectedGrade}</span>
            </span>
            <span className="text-slate-300">•</span>
            <span className="flex items-center gap-1">
              <BookOpen className="w-3.5 h-3.5 text-slate-400" />
              <span>{detectedSubject}</span>
            </span>
            {detectedYear && (
              <>
                <span className="text-slate-300">•</span>
                <span className="flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5 text-slate-400" />
                  <span>Edition {detectedYear}</span>
                </span>
              </>
            )}
            <span className="text-slate-300">•</span>
            <span className="flex items-center gap-1 font-mono text-[11px]">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <span>{metadata.page_count} pages</span>
            </span>
            <span className="text-slate-300">•</span>
            <span className="flex items-center gap-1 font-mono text-[11px] text-slate-500">
              <Scan className="w-3.5 h-3.5 text-slate-400" />
              <span>OCR: {metadata.ocr_pages_count} pages</span>
            </span>
          </div>
        </div>

        {/* Header Action Buttons */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setIsMetadataModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-50 hover:bg-slate-100 rounded-md border border-slate-200 transition-colors shadow-2xs"
          >
            <FileCheck className="w-3.5 h-3.5 text-slate-500" />
            <span>Processing Details</span>
          </button>

          <a
            href={directPdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-200 rounded-md transition-colors shadow-2xs"
          >
            <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
            <span>Open PDF in Tab</span>
          </a>

          <button
            onClick={() => onGenerateMCQs && onGenerateMCQs(versionId)}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-bold text-white bg-lms-blue-600 hover:bg-lms-blue-700 rounded-md transition-colors shadow-sm"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Generate MCQs</span>
          </button>
        </div>
      </div>

      {/* Partial Ingestion Warning Banner */}
      {isPartial && (
        <div className="p-3.5 rounded-md bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2.5 shadow-2xs">
          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-bold">Partial Ingestion Notice</p>
            <p className="leading-relaxed text-[11px]">
              This textbook was partially processed. Some pages could not be fully extracted by native text parsing or OCR.
            </p>
          </div>
        </div>
      )}

      {/* Failed Ingestion Safe Alert */}
      {isFailed && (
        <div className="p-3.5 rounded-md bg-rose-50 border border-rose-200 text-rose-900 text-xs flex items-start gap-2.5 shadow-2xs">
          <XCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-bold">Textbook Ingestion Status: FAILED</p>
            <p className="leading-relaxed text-[11px]">
              {metadata.error_message || 'The ingestion engine encountered an issue while parsing this textbook PDF.'}
            </p>
          </div>
        </div>
      )}

      {/* Main Workspace Layout (~25% TOC Sidebar, ~75% PDF Viewer) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
        {/* Left: Clean Table of Contents Navigator */}
        <div className="lg:col-span-3 lg:sticky lg:top-4">
          <TableOfContentsViewer
            versionId={versionId}
            activePage={targetPdfPage}
            activeKey={activeTocKey}
            onSelectPage={handleSelectPage}
          />
        </div>

        {/* Right: Dominant Native PDF Viewer */}
        <div className="lg:col-span-9">
          <PdfDocumentViewer
            versionId={versionId}
            targetPdfPage={targetPdfPage}
            targetBookPageLabel={targetBookPageLabel}
            isNavigating={isNavigating}
            pdfAvailable={metadata.pdf_available ?? true}
            title={detectedTitle}
            onIframeLoaded={handleIframeLoaded}
            onReload={() => loadWorkspaceData(versionId)}
          />
        </div>
      </div>

      {/* Processing Details Modal */}
      <TextbookMetadataModal
        metadata={metadata}
        title={detectedTitle}
        grade={detectedGrade}
        subject={detectedSubject}
        editionYear={detectedYear}
        isOpen={isMetadataModalOpen}
        onClose={() => setIsMetadataModalOpen(false)}
      />
    </div>
  );
};
