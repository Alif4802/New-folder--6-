import {
  HealthResponse,
  IngestionResponse,
  TextbookVersionSummary,
  PDFMetadataResponse,
  CurriculumScopeResponse,
  TextbookTOCResponse,
  MCQCapabilitiesResponse,
  MCQGenerateRequest,
  MCQGenerationResponse,
  MCQJobCreateResponse,
  MCQJobStatusResponse,
  MCQJobCancelResponse,
} from '../types/api';

/**
 * Resolve the API base URL from environment configuration.
 * Never hardcode API URLs directly in components.
 */
const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

export interface ApiResult<T> {
  ok: boolean;
  data: T | null;
  error?: string;
  errorCode?: string;
}

export const apiService = {
  getBaseUrl(): string {
    return API_BASE_URL;
  },

  async checkHealth(): Promise<{ ok: boolean; data: HealthResponse | null; error?: string }> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }

      const data: HealthResponse = await response.json();
      return {
        ok: data.status === 'ok' && data.database === 'ok',
        data,
      };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return {
        ok: false,
        data: null,
        error: errorMessage,
      };
    }
  },

  async getGrades(params?: {
    curriculumId?: number;
    onlyWithTextbooks?: boolean;
  }): Promise<ApiResult<import('../types/api').GradeResponse[]>> {
    try {
      const query = new URLSearchParams();
      if (params?.curriculumId) query.append('curriculum_id', params.curriculumId.toString());
      if (params?.onlyWithTextbooks) query.append('only_with_textbooks', 'true');

      const queryString = query.toString() ? `?${query.toString()}` : '';
      const response = await fetch(`${API_BASE_URL}/api/v1/grades${queryString}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }

      const data = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getSubjects(curriculumId?: number): Promise<ApiResult<import('../types/api').SubjectResponse>> {
    try {
      const query = new URLSearchParams();
      if (curriculumId) query.append('curriculum_id', curriculumId.toString());

      const queryString = query.toString() ? `?${query.toString()}` : '';
      const response = await fetch(`${API_BASE_URL}/api/v1/subjects${queryString}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }

      const data = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async ingestTextbook(file: File, gradeId: number, subjectId?: number | null): Promise<ApiResult<IngestionResponse>> {
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('grade_id', gradeId.toString());
      if (subjectId) {
        formData.append('subject_id', subjectId.toString());
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/ingest`, {
        method: 'POST',
        body: formData,
      });

      const json = await response.json();

      if (!response.ok) {
        const errorDetail = json.detail || {};
        return {
          ok: false,
          data: null,
          error: typeof errorDetail === 'string' ? errorDetail : (errorDetail.message || 'Ingestion failed'),
          errorCode: typeof errorDetail === 'object' ? errorDetail.error_code : undefined,
        };
      }

      return {
        ok: true,
        data: json as IngestionResponse,
      };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Upload connection error';
      return {
        ok: false,
        data: null,
        error: errorMessage,
      };
    }
  },

  async deleteTextbook(versionId: string): Promise<ApiResult<{ version_id: string; title: string; message: string }>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}`, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' },
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
          errorCode: json.detail?.error_code,
        };
      }

      return { ok: true, data: json };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getTextbookDependencies(versionId: string): Promise<ApiResult<import('../types/api').TextbookDependencySummary>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/dependencies`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }

      return { ok: true, data: json };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async updateTextbookMetadata(
    versionId: string,
    req: import('../types/api').UpdateTextbookMetadataRequest
  ): Promise<ApiResult<TextbookVersionSummary>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/metadata`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(req),
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
          errorCode: json.detail?.error_code,
        };
      }

      return { ok: true, data: json as TextbookVersionSummary };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async refreshTextbookMetadata(versionId: string): Promise<ApiResult<TextbookVersionSummary>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/refresh-metadata`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }

      return { ok: true, data: json as TextbookVersionSummary };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async refreshTextbookStructure(versionId: string): Promise<ApiResult<any>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/refresh-structure`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
          errorCode: json.detail?.error_code,
        };
      }

      return { ok: true, data: json };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async assignTextbookGrade(versionId: string, gradeId: number): Promise<ApiResult<TextbookVersionSummary>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/grade`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ grade_id: gradeId }),
      });

      const json = await response.json();
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
          errorCode: json.detail?.error_code,
        };
      }

      return { ok: true, data: json as TextbookVersionSummary };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getTextbookVersions(params?: {
    gradeId?: number | null;
    assessmentEligibleOnly?: boolean;
  }): Promise<ApiResult<TextbookVersionSummary[]>> {
    try {
      const query = new URLSearchParams();
      if (params?.gradeId) query.append('grade_id', params.gradeId.toString());
      if (params?.assessmentEligibleOnly) query.append('assessment_eligible_only', 'true');

      const queryString = query.toString() ? `?${query.toString()}` : '';
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/versions${queryString}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }

      const data: TextbookVersionSummary[] = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getCurriculumScope(versionId: string): Promise<ApiResult<CurriculumScopeResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/curriculum`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        const json = await response.json().catch(() => ({}));
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }

      const data: CurriculumScopeResponse = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getPDFMetadata(versionId: string): Promise<ApiResult<PDFMetadataResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/pdf-metadata`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: `HTTP ${response.status}`,
        };
      }

      const data: PDFMetadataResponse = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getTextbookTOC(versionId: string): Promise<ApiResult<TextbookTOCResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/textbooks/${versionId}/toc`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        const json = await response.json().catch(() => ({}));
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }

      const data: TextbookTOCResponse = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getMCQCapabilities(versionId: string): Promise<ApiResult<MCQCapabilitiesResponse>> {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/assessments/mcq/capabilities?subject_version_id=${encodeURIComponent(versionId)}`,
        {
          method: 'GET',
          headers: { 'Accept': 'application/json' },
        }
      );

      if (!response.ok) {
        const json = await response.json().catch(() => ({}));
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
          errorCode: json.detail?.error_code,
        };
      }

      const data: MCQCapabilitiesResponse = await response.json();
      return { ok: true, data };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async generateMCQs(payload: MCQGenerateRequest): Promise<ApiResult<MCQGenerationResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/assessments/mcq/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const json = await response.json().catch(() => ({}));

      if (!response.ok) {
        const errorDetail = json.detail || {};
        return {
          ok: false,
          data: null,
          error: typeof errorDetail === 'string' ? errorDetail : (errorDetail.message || `HTTP ${response.status}: MCQ generation failed`),
          errorCode: typeof errorDetail === 'object' ? errorDetail.error_code : undefined,
        };
      }

      return { ok: true, data: json as MCQGenerationResponse };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network connection error during MCQ generation';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async startMCQJob(payload: MCQGenerateRequest): Promise<ApiResult<MCQJobCreateResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/assessments/mcq/jobs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const json = await response.json().catch(() => ({}));
      if (!response.ok) {
        const errorDetail = json.detail || {};
        return {
          ok: false,
          data: null,
          error: typeof errorDetail === 'string' ? errorDetail : (errorDetail.message || `HTTP ${response.status}`),
          errorCode: typeof errorDetail === 'object' ? errorDetail.error_code : undefined,
        };
      }
      return { ok: true, data: json as MCQJobCreateResponse };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error starting generation job';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async getMCQJobStatus(jobId: string): Promise<ApiResult<MCQJobStatusResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/assessments/mcq/jobs/${jobId}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      const json = await response.json().catch(() => ({}));
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }
      return { ok: true, data: json as MCQJobStatusResponse };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Network error polling generation job';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async cancelMCQJob(jobId: string): Promise<ApiResult<MCQJobCancelResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/assessments/mcq/jobs/${jobId}/cancel`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const json = await response.json().catch(() => ({}));
      return { ok: true, data: json as MCQJobCancelResponse };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Error cancelling job';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  async retryMCQJob(jobId: string): Promise<ApiResult<MCQJobCreateResponse>> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/assessments/mcq/jobs/${jobId}/retry`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) {
        return {
          ok: false,
          data: null,
          error: json.detail?.message || `HTTP ${response.status}`,
        };
      }
      return { ok: true, data: json as MCQJobCreateResponse };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Error retrying job';
      return { ok: false, data: null, error: errorMessage };
    }
  },

  getPDFStreamUrl(versionId: string): string {
    return `${API_BASE_URL}/api/v1/textbooks/${versionId}/pdf`;
  },

  getTextbookPdfUrl(versionId: string): string {
    return `${API_BASE_URL}/api/v1/textbooks/${versionId}/pdf`;
  },
};


