import React, { useState, useEffect } from 'react';
import { TextbookTOCResponse } from '../types/api';
import { apiService } from '../services/api';
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileText,
  HelpCircle,
  Loader2,
  ListOrdered,
} from 'lucide-react';

interface TableOfContentsViewerProps {
  versionId: string;
  activePage?: number;
  activeKey?: string | null;
  onSelectPage: (pdfPageNumber: number, itemKey: string, bookPageLabel?: string | null) => void;
}

export const TableOfContentsViewer: React.FC<TableOfContentsViewerProps> = ({
  versionId,
  activePage = 1,
  activeKey,
  onSelectPage,
}) => {
  const [toc, setToc] = useState<TextbookTOCResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedUnits, setExpandedUnits] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadTOC(versionId);
  }, [versionId]);

  const loadTOC = async (vid: string) => {
    setLoading(true);
    setError(null);
    const res = await apiService.getTextbookTOC(vid);
    setLoading(false);

    if (res.ok && res.data) {
      setToc(res.data);
      // Collapsed by default for a clean, compact overview
      setExpandedUnits({});
    } else {
      setError(res.error || 'Failed to load Table of Contents.');
    }
  };

  const toggleUnit = (unitKey: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedUnits((prev) => ({
      ...prev,
      [unitKey]: !prev[unitKey],
    }));
  };

  const handleSelectUnit = (pdfPage: number, unitKey: string, bookLabel?: string | null) => {
    // Auto-expand on selection for smooth child navigation
    setExpandedUnits((prev) => ({
      ...prev,
      [unitKey]: true,
    }));
    onSelectPage(pdfPage, unitKey, bookLabel);
  };

  if (loading) {
    return (
      <div className="bg-white border border-lms-border rounded-lg shadow-sm p-6 text-center space-y-2">
        <Loader2 className="w-5 h-5 animate-spin text-lms-blue-600 mx-auto" />
        <p className="text-xs text-slate-500 font-medium">Loading Table of Contents...</p>
      </div>
    );
  }

  if (error || !toc || toc.items.length === 0) {
    return (
      <div className="bg-white border border-lms-border rounded-lg shadow-sm p-4 text-xs text-slate-500">
        <div className="flex items-center gap-2 font-bold text-slate-700 mb-1">
          <ListOrdered className="w-4 h-4 text-slate-400" />
          <span>Contents</span>
        </div>
        <p className="text-[11px] text-slate-400 mt-1">
          {error || 'No structured navigation items detected for this textbook.'}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-lms-border rounded-lg shadow-sm overflow-hidden flex flex-col">
      {/* Clean TOC Header without misleading unit counts */}
      <div className="px-3.5 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ListOrdered className="w-4 h-4 text-lms-blue-600" />
          <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
            Contents
          </h3>
        </div>
      </div>

      {/* TOC Items Tree */}
      <div className="p-2 space-y-1 overflow-y-auto max-h-[680px] lg:max-h-[750px] text-xs">
        {toc.items.map((unit, uIdx) => {
          const unitKey = `unit-${uIdx}`;
          const unitPdfPage = unit.pdf_page_number || unit.page_number;
          const unitDisplayPage = unit.book_page_label || unitPdfPage;
          const isExpanded = !!expandedUnits[unitKey];
          const isUnitActive = activeKey === unitKey || (!activeKey && activePage === unitPdfPage);

          return (
            <div key={unitKey} className="rounded-md overflow-hidden">
              {/* Unit / Chapter Row */}
              <div
                onClick={() => handleSelectUnit(unitPdfPage, unitKey, unit.book_page_label)}
                title={unit.label}
                className={`group flex items-center justify-between gap-1.5 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                  isUnitActive
                    ? 'bg-blue-50 text-lms-blue-800 font-bold border-l-2 border-lms-blue-600'
                    : 'text-slate-700 hover:bg-slate-50 hover:text-slate-900 font-semibold'
                }`}
              >
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  {unit.children && unit.children.length > 0 ? (
                    <button
                      onClick={(e) => toggleUnit(unitKey, e)}
                      className="p-0.5 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors flex-shrink-0"
                      title={isExpanded ? 'Collapse unit' : 'Expand unit'}
                    >
                      {isExpanded ? (
                        <ChevronDown className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5" />
                      )}
                    </button>
                  ) : (
                    <BookOpen className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                  )}

                  <span className="truncate text-xs" title={unit.label}>
                    {unit.label}
                  </span>
                </div>

                <span
                  className={`text-[10px] font-mono flex-shrink-0 px-1.5 py-0.2 rounded ${
                    isUnitActive
                      ? 'bg-blue-100/70 text-lms-blue-700'
                      : 'text-slate-400 group-hover:text-slate-600'
                  }`}
                >
                  p.{unitDisplayPage}
                </span>
              </div>

              {/* Children: Lessons & Exercises */}
              {isExpanded && unit.children && unit.children.length > 0 && (
                <div className="pl-3.5 mt-0.5 space-y-0.5 border-l border-slate-200/80 ml-2.5">
                  {unit.children.map((child, cIdx) => {
                    const childKey = `child-${uIdx}-${cIdx}`;
                    const childPdfPage = child.pdf_page_number || child.page_number;
                    const childDisplayPage = child.book_page_label || childPdfPage;
                    const isChildActive = activeKey === childKey || (!activeKey && activePage === childPdfPage);

                    if (child.type === 'exercise') {
                      return (
                        <div
                          key={childKey}
                          onClick={() => onSelectPage(childPdfPage, childKey, child.book_page_label)}
                          className={`group flex items-center justify-between gap-1.5 px-2 py-1 rounded cursor-pointer transition-colors ${
                            isChildActive
                              ? 'bg-emerald-50 text-emerald-800 font-semibold border-l-2 border-emerald-600'
                              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 min-w-0 flex-1">
                            <HelpCircle className="w-3 h-3 text-emerald-600 flex-shrink-0" />
                            <span className="truncate text-[11px]" title={child.label}>
                              {child.label}
                            </span>
                          </div>
                          <span
                            className={`text-[10px] font-mono flex-shrink-0 px-1.5 py-0.2 rounded ${
                              isChildActive
                                ? 'bg-emerald-100/70 text-emerald-700'
                                : 'text-slate-400 group-hover:text-slate-600'
                            }`}
                          >
                            p.{childDisplayPage}
                          </span>
                        </div>
                      );
                    }

                    // Lesson Item
                    return (
                      <div key={childKey} className="space-y-0.5">
                        <div
                          onClick={() => onSelectPage(childPdfPage, childKey, child.book_page_label)}
                          className={`group flex items-center justify-between gap-1.5 px-2 py-1 rounded cursor-pointer transition-colors ${
                            isChildActive
                              ? 'bg-blue-50 text-lms-blue-800 font-semibold border-l-2 border-lms-blue-600'
                              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 min-w-0 flex-1">
                            <FileText className="w-3 h-3 text-slate-400 flex-shrink-0" />
                            <span className="truncate text-[11px]" title={child.label}>
                              {child.label}
                            </span>
                          </div>
                          <span
                            className={`text-[10px] font-mono flex-shrink-0 px-1.5 py-0.2 rounded ${
                              isChildActive
                                ? 'bg-blue-100/70 text-lms-blue-700'
                                : 'text-slate-400 group-hover:text-slate-600'
                            }`}
                          >
                            p.{childDisplayPage}
                          </span>
                        </div>

                        {/* Exercises inside Lesson */}
                        {child.children && child.children.length > 0 && (
                          <div className="pl-3 space-y-0.5 border-l border-slate-100 ml-2">
                            {child.children.map((ex, eIdx) => {
                              const exKey = `ex-${uIdx}-${cIdx}-${eIdx}`;
                              const exPdfPage = ex.pdf_page_number || ex.page_number;
                              const exDisplayPage = ex.book_page_label || exPdfPage;
                              const isExActive = activeKey === exKey || (!activeKey && activePage === exPdfPage);

                              return (
                                <div
                                  key={exKey}
                                  onClick={() => onSelectPage(exPdfPage, exKey, ex.book_page_label)}
                                  className={`group flex items-center justify-between gap-1.5 px-1.5 py-0.5 rounded cursor-pointer transition-colors ${
                                    isExActive
                                      ? 'bg-emerald-50 text-emerald-800 font-semibold border-l-2 border-emerald-600'
                                      : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                                  }`}
                                >
                                  <div className="flex items-center gap-1 min-w-0 flex-1">
                                    <HelpCircle className="w-3 h-3 text-emerald-600 flex-shrink-0" />
                                    <span className="truncate text-[11px]" title={ex.label}>
                                      {ex.label}
                                    </span>
                                  </div>
                                  <span
                                    className={`text-[10px] font-mono flex-shrink-0 px-1 py-0.2 rounded ${
                                      isExActive
                                        ? 'bg-emerald-100/70 text-emerald-700'
                                        : 'text-slate-400 group-hover:text-slate-600'
                                    }`}
                                  >
                                    p.{exDisplayPage}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
