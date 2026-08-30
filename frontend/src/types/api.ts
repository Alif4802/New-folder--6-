export type WorkspaceTab = 'textbook' | 'assessment' | 'question_bank' | 'saved_papers';

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error' | 'degraded' | 'unavailable';

export interface HealthResponse {
  status: string;
  database: string;
  timestamp?: string;
  version?: string;
  api_version?: string;
}

export interface Curriculum {
  id: number;
  code: string;
  name: string;
  country: string;
  authority: string;
  is_active: boolean;
}

export interface GradeSummary {
  id: number;
  code: string;
  name: string;
  display_name: string;
  level_number?: number | null;
  is_active: boolean;
}

export interface GradeResponse {
  id: number;
  curriculum_id: number;
  code: string;
  name: string;
  display_name: string;
  level_number?: number | null;
  is_active: boolean;
  textbook_count: number;
}

export interface SubjectSummary {
  id: number;
  curriculum_id: number;
  code: string;
  name: string;
  domain: string;
  is_supported_for_generation: boolean;
}

export interface SubjectResponse {
  subjects: SubjectSummary[];
  total: number;
}

export interface SubjectVersionSummary {
  id: string;
  title: string;
  grade_code?: string;
  grade_name?: string;
  subject_code?: string;
  subject_name?: string;
  edition_year?: number;
  edition_label?: string;
  publication_year?: number;
  version_label?: string;
  page_count: number;
  ingestion_status: string;
  warnings?: string[];
}

export interface TextbookVersionSummary {
  id: string;
  title: string;
  grade?: string;
  grade_id?: number | null;
  grade_info?: GradeSummary | null;
  subject?: string;
  subject_id?: number | null;
  domain?: string;
  edition_year?: number;
  edition_label?: string | null;
  publication_year?: number | null;
  version_label?: string;
  page_count: number;
  ocr_pages_count?: number;
  ingestion_status: string;
  curriculum_quality_status?: string;
  metadata_status?: string;
  assessment_ready?: boolean;
  assessment_readiness_reasons?: string[];
  is_deleted?: boolean;
  warnings?: string[];
  created_at?: string;
}

export interface TextbookDependencySummary {
  version_id: string;
  title: string;
  curriculum_nodes_count: number;
  activity_nodes_count: number;
  question_bank_items_count: number;
  question_sets_count: number;
  can_soft_delete: boolean;
}

export interface UpdateTextbookMetadataRequest {
  title?: string;
  grade_id?: number | null;
  subject_id?: number | null;
  edition_label?: string | null;
  publication_year?: number | null;
}

export interface IngestionResponse {
  version_id: string;
  title: string;
  grade_id?: number | null;
  grade_name?: string | null;
  detected_grade?: string;
  detected_subject?: string;
  detected_domain?: string;
  page_count: number;
  unit_count: number;
  lesson_count: number;
  activity_node_count: number;
  ocr_pages_count: number;
  ingestion_status: string;
  warnings?: string[];
}

export interface PDFMetadataResponse {
  version_id: string;
  title: string;
  edition_year?: number;
  version_label?: string;
  source_filename?: string;
  grade?: string;
  subject?: string;
  domain?: string;
  page_count: number;
  file_size_bytes: number;
  checksum_sha256: string;
  ingestion_status: string;
  ocr_pages_count: number;
  pdf_available?: boolean;
  warnings?: string[];
  error_message?: string | null;
  detected_metadata?: Record<string, any>;
  diagnostic_signals?: Record<string, any>;
  created_at: string;
}

export interface ActivityNodeDetail {
  id: number;
  subject_version_id: string;
  unit_id: number;
  lesson_id?: number | null;
  curriculum_node_id?: string | null;
  ordinal: number;
  node_type: string;
  title?: string | null;
  content_text: string;
  structured_payload?: any;
  page_number: number;
  bounding_box?: Record<string, number> | null;
  content_hash: string;
  parser_metadata?: Record<string, any> | null;
  created_at: string;
}

export interface TOCItem {
  type: string;
  label: string;
  number?: string | null;
  page_number: number;
  pdf_page_number: number;
  book_page_label?: string | null;
  children?: TOCItem[] | null;
}

export interface TextbookTOCResponse {
  version_id: string;
  items: TOCItem[];
}

// --- Assessment Generator Types ---

export interface MCQOption {
  id?: string | null;
  label: string;
  text: string;
  latex?: string | null;
}

export interface MCQQuestion {
  id?: string | null;
  question_number: number;
  question_text: string;
  question_latex?: string | null;
  options: MCQOption[];
  correct_option_id?: string | null;
  explanation: string;
}

export interface MCQAnswerKeyItem {
  question_number: number;
  question_id?: string | null;
  correct_letter: string;
  correct_text: string;
  correct_latex?: string | null;
  explanation: string;
}

export interface LessonScope {
  id: number;
  detected_number?: string | null;
  title: string;
}

export interface UnitScope {
  id: number;
  detected_number?: string | null;
  title: string;
  lessons: LessonScope[];
}

export interface SubjectVersionScopeInfo {
  id: string;
  title: string;
  grade?: string | null;
  grade_id?: number | null;
  subject?: string | null;
}

export interface CurriculumScopeNode {
  id: string;
  node_type: string;
  source_label: string;
  title: string;
  detected_number?: string | null;
  depth: number;
  start_page: number;
  end_page?: number | null;
  children?: CurriculumScopeNode[];
}

export type CurriculumScopeResponse = CurriculumScopeNode;

export interface CurriculumScopeInfo {
  scope_node_ids?: string[];
  scope_node_id?: string | null;
  scope_type?: string | null;
  scope_label?: string | null;
  scope_title: string;
  unit_id?: number | null;
  unit_title?: string | null;
  lesson_id?: number | null;
  lesson_title?: string | null;
}

export interface MCQGenerationResponse {
  request_id: string;
  subject_version: SubjectVersionScopeInfo;
  scope: CurriculumScopeInfo;
  requested_count: number;
  generated_count: number;
  questions: MCQQuestion[];
  answer_key: MCQAnswerKeyItem[];
  warnings: string[];
}

export interface MCQGenerateRequest {
  subject_version_id: string;
  grade_id?: number | null;
  scope_node_ids?: string[];
  scope_node_id?: string | null;
  unit_id?: number | null;
  lesson_id?: number | null;
  count: number;
  previous_request_id?: string | null;
  previous_job_id?: string | null;
}

export interface MCQCapabilitiesResponse {
  subject_version_id: string;
  title: string;
  subject?: string | null;
  subject_code?: string | null;
  grade?: string | null;
  grade_id?: number | null;
  generation_supported: boolean;
  unsupported_reason?: string | null;
  llm_configured: boolean;
  min_question_count: number;
  max_question_count?: number | null;
  max_total_questions?: number | null;
  default_question_count: number;
  generation_batch_size?: number;
  supported_types: string[];
  scope_tree: CurriculumScopeNode[];
  units?: UnitScope[];
}

export interface MCQJobCreateResponse {
  job_id: string;
  status: string;
  requested_count: number;
  generated_count: number;
}

export interface MCQJobStatusResponse {
  job_id: string;
  status: string;
  stage: string;
  stage_message: string;
  requested_count: number;
  generated_count: number;
  questions: MCQQuestion[];
  answer_key: MCQAnswerKeyItem[];
  complete: boolean;
  error?: string | null;
  warnings?: string[];
}

export interface MCQJobCancelResponse {
  job_id: string;
  status: string;
  message: string;
}
