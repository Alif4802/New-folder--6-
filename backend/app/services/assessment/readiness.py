import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.models.textbook import SubjectVersion
from app.services.pdf.subject_profiles import subject_registry

logger = logging.getLogger("nctb.assessment.readiness")


@dataclass
class AssessmentReadinessResult:
    is_ready: bool
    reasons: List[str]


class AssessmentReadinessService:
    """
    Centralized, authoritative evaluation of textbook assessment eligibility.
    Reused identically across:
    - GET /api/v1/textbooks (version summaries)
    - GET /api/v1/grades (active textbook counts)
    - GET /api/v1/assessments/capabilities
    - POST /api/v1/assessments/jobs (job creation validation)
    - POST /api/v1/assessments/generate (synchronous generation validation)
    """

    SUPPORTED_DOMAINS = {"STEM", "LANGUAGE"}

    FRIENDLY_REASON_MAP = {
        "TEXTBOOK_DELETED": "This textbook has been deleted.",
        "INGESTION_INCOMPLETE": "Textbook ingestion is incomplete.",
        "GRADE_NOT_ASSIGNED": "Assign Class / Grade first.",
        "SUBJECT_NOT_RESOLVED": "Assign a subject first.",
        "SUBJECT_NOT_SUPPORTED": "Assessment generation is not supported for this subject domain.",
        "STRUCTURE_NEEDS_REFRESH": "Textbook structure needs refresh.",
        "PDF_NOT_AVAILABLE": "The textbook PDF file is not available.",
    }

    @classmethod
    def get_friendly_reason(cls, reason_code: str) -> str:
        return cls.FRIENDLY_REASON_MAP.get(reason_code, reason_code)

    @classmethod
    def evaluate(cls, version: SubjectVersion) -> AssessmentReadinessResult:
        reasons: List[str] = []

        # 1. Deletion check
        if getattr(version, "is_deleted", False):
            reasons.append("TEXTBOOK_DELETED")

        # 2. Ingestion status check
        if version.ingestion_status not in ["COMPLETED", "PARTIAL"]:
            reasons.append("INGESTION_INCOMPLETE")

        # 3. Grade assignment check
        if version.grade_id is None:
            reasons.append("GRADE_NOT_ASSIGNED")

        # 4. Subject resolution check
        if version.subject_id is None:
            reasons.append("SUBJECT_NOT_RESOLVED")
        else:
            # 5. Subject domain / profile generation support check
            subject = version.subject
            if subject:
                # Check domain
                if subject.domain not in cls.SUPPORTED_DOMAINS:
                    # Also check if registered in subject_profiles
                    matching_profile = next((p for p in subject_registry.list_profiles() if p.code == subject.code), None)
                    if not matching_profile or matching_profile.domain not in cls.SUPPORTED_DOMAINS:
                        reasons.append("SUBJECT_NOT_SUPPORTED")

        # 6. Curriculum structure quality status check
        # UNASSESSED is treated as legacy-compatible (not blocked) unless explicitly marked NEEDS_REFRESH / FAILED / BUILDING
        quality_status = getattr(version, "curriculum_quality_status", "UNASSESSED")
        if quality_status in ["NEEDS_REFRESH", "FAILED", "BUILDING"]:
            reasons.append("STRUCTURE_NEEDS_REFRESH")

        # 7. Physical PDF asset availability check
        if version.stored_pdf_path:
            full_pdf_path = settings.STORAGE_ROOT / version.stored_pdf_path
            if not full_pdf_path.exists():
                reasons.append("PDF_NOT_AVAILABLE")
        else:
            reasons.append("PDF_NOT_AVAILABLE")

        is_ready = len(reasons) == 0
        return AssessmentReadinessResult(is_ready=is_ready, reasons=reasons)
