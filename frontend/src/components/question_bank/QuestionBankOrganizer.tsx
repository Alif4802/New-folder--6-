import React, { useState } from 'react';
import {
  BookOpen,
  Filter,
  Layers,
  RotateCcw,
  Search,
  CheckSquare,
} from 'lucide-react';
import { TextbookVersionSummary, CurriculumScopeNode } from '../../types/api';
import { CurriculumScopeTree } from '../CurriculumScopeTree';

interface QuestionBankOrganizerProps {
  textbooks: TextbookVersionSummary[];
  selectedVersionId: string;
  onSelectVersion: (versionId: string) => void;
  scopeTree: CurriculumScopeNode[];
  selectedScopeNodeId: string | null;
  onSelectScopeNode: (nodeId: string | null) => void;
  statusFilter: string;
  onChangeStatusFilter: (status: string) => void;
  searchQuery: string;
  onChangeSearchQuery: (query: string) => void;
  onResetFilters: () => void;
}

export const QuestionBankOrganizer: React.FC<QuestionBankOrganizerProps> = ({
  textbooks,
  selectedVersionId,
  onSelectVersion,
  scopeTree,
  selectedScopeNodeId,
  onSelectScopeNode,
  statusFilter,
  onChangeStatusFilter,
  searchQuery,
  onChangeSearchQuery,
  onResetFilters,
}) => {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const toggleExpand = (nodeId: string) => {
    const next = new Set(expandedNodes);
    if (next.has(nodeId)) {
      next.delete(nodeId);
    } else {
      next.add(nodeId);
    }
    setExpandedNodes(next);
  };

  return (
    <div className="w-72 bg-white border-r border-slate-200 flex flex-col h-full overflow-hidden flex-shrink-0">
      {/* Header */}
      <div className="p-3.5 border-b border-slate-200 flex items-center justify-between bg-slate-50">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-lms-blue-600" />
          <span className="font-semibold text-xs text-slate-800 uppercase tracking-wider">Filters & Scope</span>
        </div>
        <button
          onClick={onResetFilters}
          title="Reset Filters"
          className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-200 text-xs flex items-center gap-1"
        >
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4 text-xs">
        {/* Textbook Selector */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <BookOpen className="w-3.5 h-3.5 text-slate-400" />
            Textbook
          </label>
          <select
            value={selectedVersionId}
            onChange={(e) => onSelectVersion(e.target.value)}
            className="w-full text-xs bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500 focus:outline-none text-slate-800"
          >
            {textbooks.map((tb) => (
              <option key={tb.id} value={tb.id}>
                {tb.title}
              </option>
            ))}
          </select>
        </div>

        {/* Text Search */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <Search className="w-3.5 h-3.5 text-slate-400" />
            Search Question
          </label>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onChangeSearchQuery(e.target.value)}
              placeholder="Search stem or formula..."
              className="w-full text-xs bg-slate-50 border border-slate-300 rounded pl-7 pr-2.5 py-1.5 focus:ring-1 focus:ring-lms-blue-500 focus:outline-none"
            />
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2" />
          </div>
        </div>

        {/* Status Filter */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
            Status
          </label>
          <div className="flex rounded border border-slate-300 overflow-hidden bg-slate-100 p-0.5">
            <button
              onClick={() => onChangeStatusFilter('ACTIVE')}
              className={`flex-1 py-1 text-center font-medium rounded transition-colors ${
                statusFilter === 'ACTIVE'
                  ? 'bg-white text-lms-blue-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              Active
            </button>
            <button
              onClick={() => onChangeStatusFilter('ARCHIVED')}
              className={`flex-1 py-1 text-center font-medium rounded transition-colors ${
                statusFilter === 'ARCHIVED'
                  ? 'bg-white text-lms-blue-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              Archived
            </button>
          </div>
        </div>

        {/* Question Type */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
            Question Type
          </label>
          <div className="bg-slate-50 border border-slate-200 rounded px-2.5 py-1.5 text-slate-600 flex items-center gap-1.5">
            <CheckSquare className="w-3.5 h-3.5 text-emerald-600" />
            <span>Multiple Choice (MCQ)</span>
          </div>
        </div>

        {/* Curriculum Scope Tree */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              Curriculum Scope
            </label>
            {selectedScopeNodeId && (
              <button
                onClick={() => onSelectScopeNode(null)}
                className="text-[10px] text-lms-blue-600 hover:underline"
              >
                Clear Scope
              </button>
            )}
          </div>

          <div className="border border-slate-200 rounded bg-slate-50 p-1 max-h-64 overflow-y-auto space-y-0.5">
            <CurriculumScopeTree
              nodes={scopeTree}
              mode="filter"
              selectedFilterNodeId={selectedScopeNodeId}
              onSelectFilterNode={onSelectScopeNode}
              expandedNodeIds={expandedNodes}
              onToggleExpand={toggleExpand}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
