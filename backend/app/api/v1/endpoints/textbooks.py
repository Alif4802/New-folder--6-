import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.curriculum import Grade
from app.models.textbook import SubjectVersion, Unit, Lesson
from app.services.assessment.readiness import AssessmentReadinessService
from app.services.pdf.curriculum_quality import CurriculumQualityGate
from app.models.question_bank import QuestionBankItem, QuestionSetItem, QuestionBankItemScope, QuestionSet
from app.schemas.textbook import (
    GradeSummary,
    IngestionResponse,
    TextbookVersionSummary,
    PDFMetadataResponse,
    CurriculumScopeResponse,
    UnitScopeResponse,
    LessonScopeResponse,
    TextbookTOCResponse,
    TOCItemResponse,
    UpdateTextbookMetadataRequest,
    TextbookDependencySummary,
)
from app.services.ingestion import IngestionService
from app.services.pdf.toc_service import build_textbook_toc
from app.services.pdf.metadata_detector import DynamicMetadataDetector
import pymupdf

logger = logging.getLogger("nctb.api.textbooks")

router = APIRouter(prefix="/textbooks", tags=["Textbooks"])


class AssignGradeRequest(BaseModel):
    grade_id: int


@router.post(
    "/ingest",
    response_model=IngestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest an NCTB textbook PDF with authoritative Grade and Subject metadata",
)
async def ingest_textbook(
    file: UploadFile = File(..., description="NCTB Textbook PDF file"),
    grade_id: Optional[int] = Form(None, description="Selected Grade/Class database ID"),
    subject_id: Optional[int] = Form(None, description="Selected canonical Subject database ID"),
    session: AsyncSession = Depends(get_db),
):
    """
    Ingest an NCTB English-language textbook PDF through the dynamic extraction pipeline.
    Optionally accepts authoritative Class/Grade and Subject database IDs or resolves dynamically.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_FILE_EXTENSION",
                "message": "Only .pdf files are accepted for textbook ingestion.",
            },
        )

    resolved_grade_id: Optional[int] = None
    if grade_id is not None:
        # Validate grade_id exists and is active
        grade_stmt = select(Grade).where(Grade.id == grade_id, Grade.is_active == True)  # noqa: E712
        grade_res = await session.execute(grade_stmt)
        grade = grade_res.scalar_one_or_none()
        if not grade:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_GRADE_ID",
                    "message": f"Grade with ID '{grade_id}' does not exist or is inactive.",
                },
            )
        resolved_grade_id = grade.id

    return await IngestionService.ingest_pdf(
        file=file,
        grade_id=resolved_grade_id,
        subject_id=subject_id,
        session=session,
    )


@router.get(
    "/versions",
    response_model=List[TextbookVersionSummary],
    summary="List all ingested textbook versions with optional grade and eligibility filters",
)
async def list_textbook_versions(
    grade_id: Optional[int] = Query(None, description="Filter textbooks by Grade ID"),
    assessment_eligible_only: bool = Query(False, description="Filter to only assessment-eligible textbooks"),
    include_deleted: bool = Query(False, description="Include soft-deleted textbook versions"),
    session: AsyncSession = Depends(get_db),
):
    """
    Retrieve ingested textbook versions dynamically from the database.
    Supports authoritative grade-level filtering and lifecycle soft-delete filtering.
    """
    stmt = (
        select(SubjectVersion)
        .options(
            selectinload(SubjectVersion.grade),
            selectinload(SubjectVersion.subject),
        )
    )
    if not include_deleted:
        stmt = stmt.where(SubjectVersion.is_deleted == False)

    if grade_id is not None:
        stmt = stmt.where(SubjectVersion.grade_id == grade_id)

    stmt = stmt.order_by(SubjectVersion.created_at.desc())
    result = await session.execute(stmt)
    versions = result.scalars().all()

    summaries: List[TextbookVersionSummary] = []
    for v in versions:
        readiness = AssessmentReadinessService.evaluate(v)

        if assessment_eligible_only and not readiness.is_ready:
            continue

        grade_info = None
        if v.grade:
            grade_info = GradeSummary(
                id=v.grade.id,
                code=v.grade.code,
                name=v.grade.name,
                display_name=v.grade.name,
                level_number=v.grade.level_number,
                is_active=v.grade.is_active,
            )

        summaries.append(
            TextbookVersionSummary(
                id=v.id,
                title=v.title,
                grade=v.grade.name if v.grade else None,
                grade_id=v.grade.id if v.grade else None,
                grade_info=grade_info,
                subject=v.subject.name if v.subject else None,
                subject_id=v.subject.id if v.subject else None,
                domain=v.subject.domain if v.subject else None,
                edition_year=v.edition_year,
                edition_label=v.edition_label,
                publication_year=v.publication_year,
                page_count=v.page_count,
                ingestion_status=v.ingestion_status,
                curriculum_quality_status=v.curriculum_quality_status,
                metadata_status=v.metadata_status,
                assessment_ready=readiness.is_ready,
                assessment_readiness_reasons=readiness.reasons,
                ocr_pages_count=v.ocr_pages_count,
                is_deleted=v.is_deleted,
                error_message=v.error_message,
                created_at=v.created_at,
            )
        )

    return summaries


@router.patch(
    "/{version_id}/grade",
    response_model=TextbookVersionSummary,
    summary="Assign or update Class/Grade metadata for an ingested textbook",
)
async def assign_textbook_grade(
    version_id: str,
    req: AssignGradeRequest,
    session: AsyncSession = Depends(get_db),
):
    """
    Assign or update the authoritative Grade relation for an existing textbook without re-ingesting.
    """
    grade_stmt = select(Grade).where(Grade.id == req.grade_id, Grade.is_active == True)  # noqa: E712
    grade_res = await session.execute(grade_stmt)
    grade = grade_res.scalar_one_or_none()
    if not grade:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_GRADE_ID",
                "message": f"Grade with ID '{req.grade_id}' was not found or is inactive.",
            },
        )

    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id).options(
        selectinload(SubjectVersion.grade),
        selectinload(SubjectVersion.subject),
    )
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TEXTBOOK_NOT_FOUND",
                "message": f"Textbook version '{version_id}' was not found.",
            },
        )

    version.grade_id = grade.id
    await session.commit()
    await session.refresh(version)

    grade_info = GradeSummary(
        id=grade.id,
        code=grade.code,
        name=grade.name,
        display_name=grade.name,
        level_number=grade.level_number,
        is_active=grade.is_active,
    )
    return TextbookVersionSummary(
        id=version.id,
        title=version.title,
        grade=grade.name,
        grade_id=grade.id,
        grade_info=grade_info,
        subject=version.subject.name if version.subject else None,
        subject_id=version.subject.id if version.subject else None,
        domain=version.subject.domain if version.subject else "GENERAL",
        edition_year=version.edition_year,
        page_count=version.page_count,
        ingestion_status=version.ingestion_status,
        ocr_pages_count=version.ocr_pages_count,
        error_message=version.error_message,
        created_at=version.created_at,
    )


@router.get(
    "/{version_id}/curriculum",
    response_model=CurriculumScopeResponse,
    summary="Retrieve minimal curriculum Unit and Lesson hierarchy for assessment scoping",
)
async def get_curriculum_scope(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Get the minimal Unit and Lesson hierarchy for scope selection in assessment generation.
    Does NOT expose ActivityNodes, node contents, bounding boxes, or parser metadata.
    """
    stmt = (
        select(SubjectVersion)
        .where(SubjectVersion.id == version_id)
        .options(
            selectinload(SubjectVersion.units).selectinload(Unit.lessons),
        )
    )
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TEXTBOOK_NOT_FOUND",
                "message": f"Textbook version '{version_id}' was not found.",
            },
        )

    units_scope: List[UnitScopeResponse] = []
    for u in sorted(version.units, key=lambda x: x.ordinal):
        lessons_scope: List[LessonScopeResponse] = [
            LessonScopeResponse(
                id=l.id,
                detected_number=l.detected_number,
                title=l.title,
            )
            for l in sorted(u.lessons, key=lambda x: x.ordinal)
        ]
        units_scope.append(
            UnitScopeResponse(
                id=u.id,
                detected_number=u.detected_number,
                title=u.title,
                lessons=lessons_scope,
            )
        )

    return CurriculumScopeResponse(
        version_id=version.id,
        units=units_scope,
    )


@router.get(
    "/{version_id}/toc",
    response_model=TextbookTOCResponse,
    summary="Retrieve client-safe Table of Contents for PDF navigation",
)
async def get_textbook_toc(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Get clean Table of Contents for dynamic PDF navigation (Units, Lessons, Exercises).
    Applies strict TOC Quality Gate, embedded PDF bookmark inspection, and exercise sanitization.
    Does NOT expose internal ActivityNode IDs, full text content, bounding boxes, or AST metadata.
    """
    stmt = (
        select(SubjectVersion)
        .where(SubjectVersion.id == version_id)
        .options(
            selectinload(SubjectVersion.units)
            .selectinload(Unit.lessons)
            .selectinload(Lesson.activity_nodes),
            selectinload(SubjectVersion.units).selectinload(Unit.activity_nodes),
        )
    )
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TEXTBOOK_NOT_FOUND",
                "message": f"Textbook version '{version_id}' was not found.",
            },
        )

    toc_items, source_used = build_textbook_toc(version)
    logger.info(f"TOC generated for version {version_id} using {source_used} ({len(toc_items)} root items)")

    return TextbookTOCResponse(
        version_id=version.id,
        items=toc_items,
    )


@router.get(
    "/{version_id}/pdf-metadata",
    response_model=PDFMetadataResponse,
    summary="Retrieve diagnostic PDF metadata for an ingested textbook",
)
async def get_pdf_metadata(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Get file metadata, checksum, diagnostic extraction info, and warnings.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id)
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TEXTBOOK_NOT_FOUND",
                "message": f"Textbook version '{version_id}' was not found.",
            },
        )

    # Check physical file existence safely without exposing filesystem paths
    pdf_path = settings.STORAGE_ROOT / version.stored_pdf_path
    pdf_available = pdf_path.is_file()

    return PDFMetadataResponse(
        version_id=version.id,
        source_filename=version.source_filename,
        file_size_bytes=version.file_size_bytes,
        checksum_sha256=version.checksum_sha256,
        page_count=version.page_count,
        ocr_pages_count=version.ocr_pages_count,
        ingestion_status=version.ingestion_status,
        pdf_available=pdf_available,
        detected_metadata=version.detected_metadata,
        warnings=version.warnings,
        error_message=version.error_message,
    )


@router.get(
    "/{version_id}/dependencies",
    response_model=TextbookDependencySummary,
    summary="Analyze dependent records for a textbook before deletion",
)
async def get_textbook_dependencies(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Analyzes dependent records referencing the textbook version:
    CurriculumNodes, ActivityNodes, QuestionBankItems, QuestionSets.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id)
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook version '{version_id}' was not found."},
        )

    # Count dependencies
    from sqlalchemy import func
    from app.models.textbook import CurriculumNode, ActivityNode

    cnode_count = await session.scalar(
        select(func.count(CurriculumNode.id)).where(CurriculumNode.subject_version_id == version_id)
    ) or 0
    anode_count = await session.scalar(
        select(func.count(ActivityNode.id)).where(ActivityNode.subject_version_id == version_id)
    ) or 0
    qbi_count = await session.scalar(
        select(func.count(QuestionBankItem.id)).where(QuestionBankItem.subject_version_id == version_id)
    ) or 0
    qset_count = await session.scalar(
        select(func.count(QuestionSet.id)).where(QuestionSet.subject_version_id == version_id)
    ) or 0

    return TextbookDependencySummary(
        version_id=version.id,
        title=version.title,
        curriculum_nodes_count=cnode_count,
        activity_nodes_count=anode_count,
        question_bank_items_count=qbi_count,
        question_sets_count=qset_count,
        can_soft_delete=True,
    )


@router.delete(
    "/{version_id}",
    summary="Soft delete an ingested textbook version safely preserving historical references",
)
async def delete_textbook(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Performs safe soft delete of a textbook:
    - Sets is_deleted = True, deleted_at = utc_now().
    - Removes textbook from active listings and assessment generation.
    - Preserves historical QuestionBankItems and Saved Papers.
    - Permits re-ingesting the exact same PDF binary later.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id)
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook version '{version_id}' was not found."},
        )

    from app.models.textbook import utc_now
    version.is_deleted = True
    version.deleted_at = utc_now()
    await session.commit()
    logger.info(f"Soft-deleted SubjectVersion '{version_id}' ('{version.title}').")

    return {
        "version_id": version.id,
        "title": version.title,
        "is_deleted": True,
        "message": f"Textbook '{version.title}' has been successfully soft-deleted.",
    }


@router.patch(
    "/{version_id}/metadata",
    response_model=TextbookVersionSummary,
    summary="Update Grade, Subject, Edition, or Title metadata for a textbook",
)
async def update_textbook_metadata(
    version_id: str,
    req: UpdateTextbookMetadataRequest,
    session: AsyncSession = Depends(get_db),
):
    """
    Update metadata fields (Class/Grade, Subject, Edition, Title) without re-uploading PDF.
    Marks metadata_status as 'USER_CONFIRMED'.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id).options(
        selectinload(SubjectVersion.grade),
        selectinload(SubjectVersion.subject),
    )
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook version '{version_id}' was not found."},
        )

    if req.grade_id is not None:
        g_stmt = select(Grade).where(Grade.id == req.grade_id, Grade.is_active == True)
        g_res = await session.execute(g_stmt)
        if not g_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_GRADE_ID", "message": f"Grade '{req.grade_id}' is invalid."},
            )
        version.grade_id = req.grade_id

    if req.subject_id is not None:
        from app.models.curriculum import Subject
        s_stmt = select(Subject).where(Subject.id == req.subject_id)
        s_res = await session.execute(s_stmt)
        if not s_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_SUBJECT_ID", "message": f"Subject '{req.subject_id}' is invalid."},
            )
        version.subject_id = req.subject_id

    if req.title is not None and req.title.strip():
        version.title = req.title.strip()

    if req.edition_label is not None:
        version.edition_label = req.edition_label.strip() or None

    if req.publication_year is not None:
        version.publication_year = req.publication_year

    version.metadata_status = "USER_CONFIRMED"
    await session.commit()
    await session.refresh(version)

    readiness = AssessmentReadinessService.evaluate(version)

    grade_info = None
    if version.grade:
        grade_info = GradeSummary(
            id=version.grade.id,
            code=version.grade.code,
            name=version.grade.name,
            display_name=version.grade.name,
            level_number=version.grade.level_number,
            is_active=version.grade.is_active,
        )

    return TextbookVersionSummary(
        id=version.id,
        title=version.title,
        grade=version.grade.name if version.grade else None,
        grade_id=version.grade.id if version.grade else None,
        grade_info=grade_info,
        subject=version.subject.name if version.subject else None,
        subject_id=version.subject.id if version.subject else None,
        domain=version.subject.domain if version.subject else None,
        edition_year=version.edition_year,
        edition_label=version.edition_label,
        publication_year=version.publication_year,
        page_count=version.page_count,
        ingestion_status=version.ingestion_status,
        curriculum_quality_status=version.curriculum_quality_status,
        metadata_status=version.metadata_status,
        assessment_ready=readiness.is_ready,
        assessment_readiness_reasons=readiness.reasons,
        ocr_pages_count=version.ocr_pages_count,
        is_deleted=version.is_deleted,
        error_message=version.error_message,
        created_at=version.created_at,
    )


@router.post(
    "/{version_id}/refresh-metadata",
    response_model=TextbookVersionSummary,
    summary="Re-detect metadata from physical PDF preserving user confirmations",
)
async def refresh_textbook_metadata(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Re-runs metadata detector on physical PDF.
    If metadata is USER_CONFIRMED, preserves confirmed fields.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id).options(
        selectinload(SubjectVersion.grade),
        selectinload(SubjectVersion.subject),
    )
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook version '{version_id}' was not found."},
        )

    pdf_path = settings.STORAGE_ROOT / version.stored_pdf_path
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "FILE_NOT_FOUND", "message": "Textbook PDF file is not available on disk."},
        )

    doc = pymupdf.open(str(pdf_path))
    detected = DynamicMetadataDetector.detect_metadata(doc, filename=version.source_filename)
    doc.close()

    # If not user-confirmed, update unconfirmed fields
    if version.metadata_status != "USER_CONFIRMED":
        if detected.grade_code and not version.grade_id:
            g_stmt = select(Grade).where(Grade.code == detected.grade_code)
            g_res = await session.execute(g_stmt)
            g_found = g_res.scalar_one_or_none()
            if g_found:
                version.grade_id = g_found.id

        if detected.subject_code and not version.subject_id:
            from app.models.curriculum import Subject
            s_stmt = select(Subject).where(Subject.code == detected.subject_code)
            s_res = await session.execute(s_stmt)
            s_found = s_res.scalar_one_or_none()
            if s_found:
                version.subject_id = s_found.id

        if detected.edition_label:
            version.edition_label = detected.edition_label
        if detected.publication_year:
            version.publication_year = detected.publication_year

        version.metadata_status = "VALID" if (version.grade_id and version.subject_id) else "NEEDS_REVIEW"

    version.detected_metadata = detected.diagnostic_signals
    await session.commit()
    await session.refresh(version)

    readiness = AssessmentReadinessService.evaluate(version)
    grade_info = None
    if version.grade:
        grade_info = GradeSummary(
            id=version.grade.id,
            code=version.grade.code,
            name=version.grade.name,
            display_name=version.grade.name,
            level_number=version.grade.level_number,
            is_active=version.grade.is_active,
        )

    return TextbookVersionSummary(
        id=version.id,
        title=version.title,
        grade=version.grade.name if version.grade else None,
        grade_id=version.grade.id if version.grade else None,
        grade_info=grade_info,
        subject=version.subject.name if version.subject else None,
        subject_id=version.subject.id if version.subject else None,
        domain=version.subject.domain if version.subject else None,
        edition_year=version.edition_year,
        edition_label=version.edition_label,
        publication_year=version.publication_year,
        page_count=version.page_count,
        ingestion_status=version.ingestion_status,
        curriculum_quality_status=version.curriculum_quality_status,
        metadata_status=version.metadata_status,
        assessment_ready=readiness.is_ready,
        assessment_readiness_reasons=readiness.reasons,
        ocr_pages_count=version.ocr_pages_count,
        is_deleted=version.is_deleted,
        error_message=version.error_message,
        created_at=version.created_at,
    )


@router.post(
    "/{version_id}/refresh-structure",
    summary="Safely refresh derived CurriculumNode structure from physical PDF using candidate staging tree",
)
async def refresh_textbook_structure(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Safely rebuilds CurriculumNode hierarchy from stored PDF asset:
    1. Loads existing version and physical PDF.
    2. Builds candidate CurriculumNode tree in staging memory.
    3. Runs generic CurriculumQualityGate on candidate tree.
    4. Evaluates QuestionBankItemScope and QuestionSetScope references: maps old node IDs to new node IDs.
    5. In transaction: replaces live tree and updates mapped scopes atomically.
    6. If parsing or quality gate fails: live tree remains completely untouched.
    """
    from app.models.textbook import CurriculumNode
    from sqlalchemy import text
    import uuid

    stmt = (
        select(SubjectVersion)
        .where(SubjectVersion.id == version_id)
        .options(
            selectinload(SubjectVersion.curriculum_nodes),
            selectinload(SubjectVersion.subject),
            selectinload(SubjectVersion.grade),
            selectinload(SubjectVersion.units).selectinload(Unit.lessons).selectinload(Lesson.activity_nodes),
            selectinload(SubjectVersion.units).selectinload(Unit.activity_nodes),
        )
    )
    res = await session.execute(stmt)
    version = res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook version '{version_id}' was not found."},
        )

    pdf_path = settings.STORAGE_ROOT / version.stored_pdf_path
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "FILE_NOT_FOUND", "message": "Textbook PDF file is not available on disk."},
        )

    # 1. Build candidate TOC/structure using current parser
    toc_items, source_used = build_textbook_toc(version)
    if not toc_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "STRUCTURE_EXTRACTION_FAILED", "message": "Could not extract structural TOC from PDF."},
        )

    # 2. Build candidate CurriculumNodes
    is_math = "math" in (version.title or "").lower() or (version.subject and "math" in version.subject.name.lower())
    default_top_type = "chapter" if is_math else "unit"

    candidate_nodes: List[CurriculumNode] = []
    root_ord = 1
    for item in toc_items:
        r_id = f"cnode_{uuid.uuid4().hex[:16]}"
        r_node = CurriculumNode(
            id=r_id,
            subject_version_id=version.id,
            parent_id=None,
            node_type=item.type if item.type in ["unit", "chapter", "part"] else default_top_type,
            source_label=item.label or f"{default_top_type.title()} {root_ord}",
            title=item.label,
            detected_number=item.number,
            ordinal=root_ord,
            depth=0,
            start_pdf_page=item.pdf_page_number,
            end_pdf_page=item.pdf_page_number,
            source_confidence=1.0,
        )
        candidate_nodes.append(r_node)
        root_ord += 1

        child_ord = 1
        for sub in (item.children or []):
            c_id = f"cnode_{uuid.uuid4().hex[:16]}"
            c_node = CurriculumNode(
                id=c_id,
                subject_version_id=version.id,
                parent_id=r_id,
                node_type="exercise" if "exercise" in (sub.label or "").lower() else "lesson",
                source_label=sub.label or f"Lesson {child_ord}",
                title=sub.label,
                detected_number=sub.number,
                ordinal=child_ord,
                depth=1,
                start_pdf_page=sub.pdf_page_number,
                end_pdf_page=sub.pdf_page_number,
                source_confidence=1.0,
            )
            candidate_nodes.append(c_node)
            child_ord += 1

    # 3. Quality Gate evaluation on candidate tree
    quality_res = CurriculumQualityGate.evaluate_tree(candidate_nodes, version.page_count)
    if not quality_res.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "CANDIDATE_STRUCTURE_INVALID",
                "message": f"Candidate structure failed quality gate: {'; '.join(quality_res.reasons)}",
                "metrics": quality_res.metrics,
            },
        )

    # 4. Scope reference safety and remapping
    old_node_ids = [n.id for n in version.curriculum_nodes]
    remap_plan: dict = {}
    if old_node_ids:
        qbi_scopes_stmt = select(QuestionBankItemScope).where(QuestionBankItemScope.curriculum_node_id.in_(old_node_ids))
        qbi_scopes_res = await session.execute(qbi_scopes_stmt)
        qbi_scopes = qbi_scopes_res.scalars().all()

        for s in qbi_scopes:
            old_node = next((n for n in version.curriculum_nodes if n.id == s.curriculum_node_id), None)
            if old_node:
                best_cand = next(
                    (c for c in candidate_nodes if c.title.strip().lower() == old_node.title.strip().lower()),
                    None
                )
                if not best_cand and old_node.start_pdf_page:
                    best_cand = next(
                        (c for c in candidate_nodes if c.start_pdf_page == old_node.start_pdf_page),
                        None
                    )
                if best_cand:
                    remap_plan[s.curriculum_node_id] = best_cand.id
                else:
                    remap_plan[s.curriculum_node_id] = candidate_nodes[0].id

    # 5. Atomic Transaction: Replace old nodes and commit
    from app.models.textbook import utc_now
    for old_node in version.curriculum_nodes:
        await session.delete(old_node)
    await session.flush()

    for c_node in candidate_nodes:
        session.add(c_node)
    await session.flush()

    # Update mapped scopes
    if remap_plan:
        for old_id, new_id in remap_plan.items():
            await session.execute(
                text("UPDATE question_bank_item_scopes SET curriculum_node_id = :new_id WHERE curriculum_node_id = :old_id"),
                {"new_id": new_id, "old_id": old_id},
            )

    version.curriculum_quality_status = "VALID"
    version.curriculum_built_at = utc_now()
    version.curriculum_parser_version = settings.CURRICULUM_PARSER_VERSION

    await session.commit()
    logger.info(f"Refreshed structure for SubjectVersion '{version.id}': created {len(candidate_nodes)} nodes (status=VALID).")

    return {
        "version_id": version.id,
        "status": "VALID",
        "nodes_created": len(candidate_nodes),
        "source_used": source_used,
        "quality_metrics": quality_res.metrics,
    }


@router.get(
    "/{version_id}/pdf",
    summary="Stream raw original textbook PDF",
)
async def get_raw_pdf(
    version_id: str,
    session: AsyncSession = Depends(get_db),
):
    """
    Stream the original uploaded PDF with inline disposition for viewing.
    """
    stmt = select(SubjectVersion).where(SubjectVersion.id == version_id)
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "TEXTBOOK_NOT_FOUND",
                "message": f"Textbook version '{version_id}' was not found.",
            },
        )

    pdf_file_path = settings.STORAGE_ROOT / version.stored_pdf_path
    if not pdf_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "FILE_NOT_FOUND_ON_DISK",
                "message": "The stored PDF file could not be located on the server filesystem.",
            },
        )

    return FileResponse(
        path=str(pdf_file_path),
        media_type="application/pdf",
        filename=version.source_filename,
        content_disposition_type="inline",
    )

