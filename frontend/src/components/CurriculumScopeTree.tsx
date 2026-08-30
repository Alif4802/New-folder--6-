import React, { useMemo, useEffect, useRef } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FileText,
  BookOpen,
} from 'lucide-react';
import { CurriculumScopeNode } from '../types/api';
import {
  buildTreeMaps,
  getNodeCheckState,
  toggleNodeCascade,
  TreeMaps,
} from '../utils/treeSelection';

interface TriStateCheckboxProps {
  checked: boolean;
  indeterminate: boolean;
  disabled?: boolean;
  onClick: (e: React.MouseEvent<HTMLInputElement>) => void;
  className?: string;
}

const TriStateCheckbox: React.FC<TriStateCheckboxProps> = ({
  checked,
  indeterminate,
  disabled = false,
  onClick,
  className = '',
}) => {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);

  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onClick={onClick}
      onChange={() => {}} // Controlled via onClick + state
      className={`rounded text-lms-blue-600 focus:ring-lms-blue-500 w-3.5 h-3.5 cursor-pointer mr-1 ${className}`}
    />
  );
};

interface CurriculumScopeTreeProps {
  nodes: CurriculumScopeNode[];
  mode?: 'checkbox' | 'filter';
  cascadeSelection?: boolean;
  // Checkbox multi-select mode props
  selectedNodeIds?: Set<string>;
  onToggleNodeSelect?: (nodeId: string, nextSelected?: Set<string>) => void;
  // Filter single-select mode props
  selectedFilterNodeId?: string | null;
  onSelectFilterNode?: (nodeId: string | null) => void;
  // Expansion state
  expandedNodeIds: Set<string>;
  onToggleExpand: (nodeId: string) => void;
}

export const CurriculumScopeTree: React.FC<CurriculumScopeTreeProps> = ({
  nodes,
  mode = 'checkbox',
  cascadeSelection = true,
  selectedNodeIds = new Set(),
  onToggleNodeSelect,
  selectedFilterNodeId,
  onSelectFilterNode,
  expandedNodeIds,
  onToggleExpand,
}) => {
  const treeMaps: TreeMaps = useMemo(() => buildTreeMaps(nodes || []), [nodes]);

  const getNodeIcon = (nodeType: string, hasChildren: boolean) => {
    const t = nodeType.toLowerCase();
    if (t.includes('chapter') || t.includes('unit')) {
      return <BookOpen className="w-3.5 h-3.5 text-lms-blue-600 flex-shrink-0" />;
    }
    if (hasChildren || t.includes('section') || t.includes('lesson')) {
      return <Folder className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />;
    }
    return <FileText className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />;
  };

  const renderNode = (node: CurriculumScopeNode, level: number = 0) => {
    const hasChildren = Boolean(node.children && node.children.length > 0);
    const isExpanded = expandedNodeIds.has(node.id);
    const isFilterSelected = selectedFilterNodeId === node.id;

    // Determine Tri-State Check status
    let isChecked = false;
    let isIndeterminate = false;

    if (mode === 'checkbox') {
      if (cascadeSelection) {
        const state = getNodeCheckState(node.id, selectedNodeIds, treeMaps.descendantsMap);
        isChecked = state === 'checked';
        isIndeterminate = state === 'indeterminate';
      } else {
        isChecked = selectedNodeIds.has(node.id);
      }
    }

    const handleCheckboxClick = (e: React.MouseEvent<HTMLInputElement>) => {
      e.stopPropagation();
      if (!onToggleNodeSelect) return;

      if (cascadeSelection) {
        const nextSelected = toggleNodeCascade(node.id, selectedNodeIds, treeMaps);
        onToggleNodeSelect(node.id, nextSelected);
      } else {
        const nextSelected = new Set(selectedNodeIds);
        if (nextSelected.has(node.id)) {
          nextSelected.delete(node.id);
        } else {
          nextSelected.add(node.id);
        }
        onToggleNodeSelect(node.id, nextSelected);
      }
    };

    return (
      <div key={node.id} className="select-none">
        <div
          className={`flex items-center gap-1.5 py-1 px-2 rounded cursor-pointer text-xs transition-colors ${
            mode === 'filter' && isFilterSelected
              ? 'bg-lms-blue-50 text-lms-blue-700 font-semibold border-l-2 border-lms-blue-600'
              : 'text-slate-700 hover:bg-slate-100'
          }`}
          style={{ paddingLeft: `${Math.max(8, level * 14 + 8)}px` }}
          onClick={() => {
            if (mode === 'filter' && onSelectFilterNode) {
              onSelectFilterNode(isFilterSelected ? null : node.id);
            }
          }}
        >
          {/* Expand/Collapse Chevron */}
          {hasChildren ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand(node.id);
              }}
              className="p-0.5 text-slate-400 hover:text-slate-700 rounded transition-colors"
            >
              {isExpanded ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
            </button>
          ) : (
            <span className="w-3.5 h-3.5 flex-shrink-0" />
          )}

          {/* Tri-State Checkbox (in checkbox mode) */}
          {mode === 'checkbox' && (
            <TriStateCheckbox
              checked={isChecked}
              indeterminate={isIndeterminate}
              onClick={handleCheckboxClick}
            />
          )}

          {/* Node Icon */}
          {getNodeIcon(node.node_type, hasChildren)}

          {/* Label and Title */}
          <span
            className="truncate flex-1"
            title={`${node.source_label}: ${node.title} (Page ${node.start_page}${node.end_page ? `-${node.end_page}` : ''})`}
          >
            <span className="text-slate-500 font-semibold text-[11px] mr-1">{node.source_label}:</span>
            <span className="text-slate-800">{node.title}</span>
          </span>
        </div>

        {/* Child Subtree */}
        {hasChildren && isExpanded && (
          <div className="border-l border-slate-200 ml-3">
            {node.children!.map((child) => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  if (!nodes || nodes.length === 0) {
    return (
      <div className="text-slate-400 text-center py-4 text-xs italic">
        No curriculum nodes available.
      </div>
    );
  }

  return <div className="space-y-0.5">{nodes.map((root) => renderNode(root, 0))}</div>;
};
