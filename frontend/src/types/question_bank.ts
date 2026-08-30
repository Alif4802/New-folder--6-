export interface QuestionBankOption {
  id: string;
  option_text: string;
  option_latex?: string | null;
  canonical_order: number;
}

export interface QuestionBankScope {
  id: string;
  node_type: string;
  source_label: string;
  title: string;
  detected_number?: string | null;
}

export interface QuestionBankProvenance {
  subject_version_id: string;
  curriculum_node_id?: string | null;
  scope_label?: string | null;
  page_number?: number | null;
  source_content_snippet?: string | null;
  origin_type: string;
  grounding_source: string;
}

export interface QuestionBankItem {
  id: string;
  subject_version_id: string;
  subject_title?: string | null;
  grade_name?: string | null;
  subject_name?: string | null;
  question_type: string;
  language: string;
  question_text: string;
  question_latex?: string | null;
  options: QuestionBankOption[];
  correct_option_id?: string | null;
  explanation: string;
  difficulty?: string | null;
  marks?: number | null;
  origin_type: string;
  grounding_source: string;
  status: string;
  scopes: QuestionBankScope[];
  provenance?: QuestionBankProvenance | null;
  created_at: string;
  updated_at: string;
}

export interface QuestionBankListResponse {
  items: QuestionBankItem[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SaveGeneratedQuestionsResponse {
  new_questions_saved: number;
  existing_questions_reused: number;
  saved_items: QuestionBankItem[];
  message: string;
}

export interface PaperMetadata {
  institution_name?: string;
  exam_title?: string;
  subject_name?: string;
  grade_name?: string;
  date?: string;
  duration_minutes?: number;
  marks_per_question?: number;
  total_marks?: number | null;
  instructions?: string;
}

export interface QuestionArrangement {
  question_id: string;
  question_order: number;
  option_order: string[];
}

export interface SavePaperRequest {
  source_type?: 'GENERATED_JOB' | 'QUESTION_BANK';
  job_id?: string | null;
  subject_version_id: string;
  title: string;
  description?: string | null;
  paper_metadata?: PaperMetadata | null;
  arrangements: QuestionArrangement[];
  scope_node_ids?: string[] | null;
}

export interface PaperItemOption {
  id?: string | null;
  label: string;
  text: string;
  latex?: string | null;
}

export interface PaperItemQuestion {
  id?: string | null;
  question_number: number;
  question_text: string;
  question_latex?: string | null;
  options: PaperItemOption[];
  correct_option_id?: string | null;
  explanation: string;
}

export interface PaperAnswerKeyItem {
  question_number: number;
  question_id?: string | null;
  correct_letter: string;
  correct_text: string;
  correct_latex?: string | null;
  explanation: string;
}

export interface QuestionSetDetail {
  id: string;
  title: string;
  description?: string | null;
  subject_version_id: string;
  subject_title?: string | null;
  grade_name?: string | null;
  subject_name?: string | null;
  set_type: string;
  question_count: number;
  paper_metadata?: PaperMetadata | null;
  status: string;
  questions: PaperItemQuestion[];
  answer_key: PaperAnswerKeyItem[];
  scope_node_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface QuestionSetSummary {
  id: string;
  title: string;
  description?: string | null;
  subject_version_id: string;
  subject_title?: string | null;
  grade_name?: string | null;
  subject_name?: string | null;
  set_type: string;
  question_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface QuestionSetListResponse {
  items: QuestionSetSummary[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
}
