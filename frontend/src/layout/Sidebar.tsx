import React from 'react';
import { BookOpen, FileCheck, GraduationCap, Layers, FileText } from 'lucide-react';
import { WorkspaceTab } from '../types/api';

interface SidebarProps {
  activeTab: WorkspaceTab;
  onSelectTab: (tab: WorkspaceTab) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onSelectTab }) => {
  const menuItems = [
    {
      id: 'textbook' as WorkspaceTab,
      label: 'Textbook Intelligence',
      icon: BookOpen,
    },
    {
      id: 'assessment' as WorkspaceTab,
      label: 'Assessment Generator',
      icon: FileCheck,
    },
    {
      id: 'question_bank' as WorkspaceTab,
      label: 'Question Bank',
      icon: Layers,
    },
    {
      id: 'saved_papers' as WorkspaceTab,
      label: 'Saved Question Papers',
      icon: FileText,
    },
  ];

  return (
    <aside className="w-64 bg-lms-navy-900 text-lms-text-light flex flex-col flex-shrink-0 border-r border-lms-navy-800 select-none">
      {/* Institutional Module Header */}
      <div className="h-16 flex items-center gap-3 px-5 border-b border-lms-navy-800 bg-lms-navy-950">
        <div className="w-8 h-8 rounded bg-lms-blue-600 flex items-center justify-center text-white shadow-sm">
          <GraduationCap className="w-5 h-5" />
        </div>
        <div>
          <h1 className="font-semibold text-sm tracking-wide text-white">NCTB Intelligence</h1>
          <p className="text-[11px] text-lms-text-dim">Bangladesh Curriculum Engine</p>
        </div>
      </div>

      {/* Navigation Section */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        <div className="px-3 pb-2 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
          Workspaces
        </div>

        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;

          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-all ${
                isActive
                  ? 'bg-lms-blue-600 text-white shadow-sm ring-1 ring-lms-blue-500'
                  : 'text-slate-300 hover:bg-lms-navy-800 hover:text-white'
              }`}
            >
              <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-white' : 'text-slate-400'}`} />
              <span className="flex-1 text-left">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Sidebar Footer info */}
      <div className="p-4 border-t border-lms-navy-800 bg-lms-navy-950 text-[11px] text-slate-400">
        <div className="flex items-center justify-between">
          <span>LMS Integration</span>
          <span className="font-mono text-slate-300 text-[10px]">v1.0.0</span>
        </div>
      </div>
    </aside>
  );
};
