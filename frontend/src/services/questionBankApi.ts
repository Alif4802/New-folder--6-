import {
  QuestionBankItem,
  QuestionBankListResponse,
  SaveGeneratedQuestionsResponse,
  QuestionSetDetail,
  QuestionSetListResponse,
  SavePaperRequest,
} from '../types/question_bank';

const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

const BASE_URL = `${API_BASE_URL}/api/v1/question-bank`;

export interface ApiResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
  statusCode?: number;
}

export const questionBankApi = {
  /**
   * List questions in the Question Bank with filtering and pagination.
   */
  async listQuestions(params: {
    subject_version_id?: string;
    scope_node_id?: string;
    status?: string;
    search?: string;
    origin_type?: string;
    page?: number;
    page_size?: number;
  }): Promise<ApiResponse<QuestionBankListResponse>> {
    try {
      const searchParams = new URLSearchParams();
      if (params.subject_version_id) searchParams.append('subject_version_id', params.subject_version_id);
      if (params.scope_node_id) searchParams.append('scope_node_id', params.scope_node_id);
      if (params.status) searchParams.append('status', params.status);
      if (params.search) searchParams.append('search', params.search);
      if (params.origin_type) searchParams.append('origin_type', params.origin_type);
      if (params.page) searchParams.append('page', params.page.toString());
      if (params.page_size) searchParams.append('page_size', params.page_size.toString());

      const url = `${BASE_URL}/questions?${searchParams.toString()}`;
      const res = await fetch(url);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to fetch questions', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error fetching questions' };
    }
  },

  /**
   * Retrieve single question item detail.
   */
  async getQuestion(questionId: string): Promise<ApiResponse<QuestionBankItem>> {
    try {
      const res = await fetch(`${BASE_URL}/questions/${questionId}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to fetch question', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error fetching question detail' };
    }
  },

  /**
   * Save validated generated questions from an in-memory GenerationJob into the Question Bank.
   */
  async saveGeneratedQuestions(jobId: string, questionIds?: string[]): Promise<ApiResponse<SaveGeneratedQuestionsResponse>> {
    try {
      const res = await fetch(`${BASE_URL}/questions/save-generated`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
          question_ids: questionIds,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to save questions to bank', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error saving questions' };
    }
  },

  /**
   * Batch archive or restore questions in the Question Bank.
   */
  async batchArchiveQuestions(questionIds: string[], archive: boolean = true): Promise<ApiResponse<{ updated_count: number; message: string }>> {
    try {
      const res = await fetch(`${BASE_URL}/questions/batch-archive`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_ids: questionIds,
          archive,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to archive questions', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error archiving questions' };
    }
  },

  /**
   * Save a question paper with exact arrangement snapshot.
   */
  async savePaper(payload: SavePaperRequest): Promise<ApiResponse<QuestionSetDetail>> {
    try {
      const res = await fetch(`${BASE_URL}/papers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to save question paper', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error saving question paper' };
    }
  },

  /**
   * List saved question papers with pagination.
   */
  async listPapers(params: {
    subject_version_id?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }): Promise<ApiResponse<QuestionSetListResponse>> {
    try {
      const searchParams = new URLSearchParams();
      if (params.subject_version_id) searchParams.append('subject_version_id', params.subject_version_id);
      if (params.status) searchParams.append('status', params.status);
      if (params.page) searchParams.append('page', params.page.toString());
      if (params.page_size) searchParams.append('page_size', params.page_size.toString());

      const res = await fetch(`${BASE_URL}/papers?${searchParams.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to list question papers', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error listing question papers' };
    }
  },

  /**
   * Get single saved question paper with exact arrangement and dynamic Answer Key.
   */
  async getPaper(paperId: string): Promise<ApiResponse<QuestionSetDetail>> {
    try {
      const res = await fetch(`${BASE_URL}/papers/${paperId}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to fetch question paper', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error fetching question paper' };
    }
  },

  /**
   * Soft-archive a saved question paper without deleting underlying Question Bank items.
   */
  async archivePaper(paperId: string): Promise<ApiResponse<{ message: string }>> {
    try {
      const res = await fetch(`${BASE_URL}/papers/${paperId}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { ok: false, error: err.detail?.message || err.detail || 'Failed to archive question paper', statusCode: res.status };
      }
      const data = await res.json();
      return { ok: true, data, statusCode: res.status };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Network error archiving question paper' };
    }
  },
};
