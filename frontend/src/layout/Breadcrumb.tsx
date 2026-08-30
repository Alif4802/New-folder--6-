import React from 'react';
import { ChevronRight } from 'lucide-react';
import { WorkspaceTab } from '../types/api';

interface BreadcrumbProps {
  activeTab: WorkspaceTab;
}

export const Breadcrumb: React.FC<BreadcrumbProps> = ({ activeTab }) => {
  const getTabLabel = (tab: WorkspaceTab): string => {
    switch (tab) {
      case 'textbook':
        return 'Textbook Intelligence';
      case 'assessment':
        return 'Assessment Generator';
      case 'question_bank':
        return 'Question Bank';
      case 'saved_papers':
        return 'Saved Question Papers';
      default:
        return 'Assessment Generator';
    }
  };

  return (
    <nav aria-label="Breadcrumb" className="flex items-center text-xs text-lms-text-muted mb-2">
      <span>Home</span>
      <ChevronRight className="w-3.5 h-3.5 mx-1.5 text-slate-400" />
      <span>NCTB Intelligence</span>
      <ChevronRight className="w-3.5 h-3.5 mx-1.5 text-slate-400" />
      <span className="font-medium text-lms-text-primary">{getTabLabel(activeTab)}</span>
    </nav>
  );
};
