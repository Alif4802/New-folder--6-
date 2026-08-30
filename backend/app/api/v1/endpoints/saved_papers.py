import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.question_bank import (
    QuestionSetDetailResponse,
    QuestionSetListResponse,
    SavePaperRequest,
)
from app.services.question_bank.paper_service import QuestionPaperService

logger = logging.getLogger("nctb.api.saved_papers")

router = APIRouter(prefix="/question-bank", tags=["Saved Question Papers"])


@router.post(
    "/papers",
    response_model=QuestionSetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Transactionally save a question paper with exact presentation arrangement snapshot",
)
async def save_question_paper_endpoint(
    request: SavePaperRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await QuestionPaperService.save_paper(
            session=session,
            request=request,
        )
    except ValueError as ve:
        err_str = str(ve)
        logger.warning(f"Paper validation error: {err_str}")
        if "TEXTBOOK_NOT_FOUND" in err_str or "QUESTION_NOT_FOUND" in err_str or "JOB_NOT_FOUND" in err_str:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "NOT_FOUND", "message": err_str},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "VALIDATION_FAILED", "message": err_str},
        )
    except Exception as e:
        logger.error(f"Error saving question paper: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": f"Failed to save question paper: {e}"},
        )


@router.get(
    "/papers",
    response_model=QuestionSetListResponse,
    summary="List saved question papers with pagination",
)
async def list_question_papers_endpoint(
    subject_version_id: Optional[str] = Query(None, description="Filter by SubjectVersion UUID"),
    status_filter: str = Query("ACTIVE", alias="status", description="Status filter: ACTIVE or ARCHIVED"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await QuestionPaperService.list_papers(
            session=session,
            subject_version_id=subject_version_id,
            status=status_filter,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Error listing question papers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "LIST_PAPERS_FAILED", "message": str(e)},
        )


@router.get(
    "/papers/{paper_id}",
    response_model=QuestionSetDetailResponse,
    summary="Retrieve saved question paper with exact arrangement and dynamic Answer Key",
)
async def get_question_paper_endpoint(
    paper_id: str,
    session: AsyncSession = Depends(get_db),
):
    paper = await QuestionPaperService.get_paper(session, paper_id)
    if not paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PAPER_NOT_FOUND", "message": f"Question paper '{paper_id}' not found."},
        )
    return paper


@router.delete(
    "/papers/{paper_id}",
    summary="Soft-archive a saved question paper without deleting underlying Question Bank items",
)
async def archive_question_paper_endpoint(
    paper_id: str,
    session: AsyncSession = Depends(get_db),
):
    success = await QuestionPaperService.archive_paper(session, paper_id, archive=True)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PAPER_NOT_FOUND", "message": f"Question paper '{paper_id}' not found."},
        )
    return {"message": f"Question paper '{paper_id}' successfully archived."}
