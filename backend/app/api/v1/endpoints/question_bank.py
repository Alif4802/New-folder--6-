import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.question_bank import (
    BatchArchiveQuestionsRequest,
    QuestionBankItemDetailResponse,
    QuestionBankItemListResponse,
    SaveGeneratedQuestionsRequest,
    SaveGeneratedQuestionsResponse,
)
from app.services.question_bank.bank_service import QuestionBankService

logger = logging.getLogger("nctb.api.question_bank")

router = APIRouter(prefix="/question-bank", tags=["Question Bank"])


@router.get(
    "/questions",
    response_model=QuestionBankItemListResponse,
    summary="List persistent Question Bank items with filtering and pagination",
)
async def list_question_bank_items(
    subject_version_id: Optional[str] = Query(None, description="Filter by SubjectVersion UUID"),
    scope_node_id: Optional[str] = Query(None, description="Filter by CurriculumNode ID (including descendants)"),
    status_filter: str = Query("ACTIVE", alias="status", description="Status filter: ACTIVE or ARCHIVED"),
    search: Optional[str] = Query(None, description="Search query string"),
    origin_type: Optional[str] = Query(None, description="Origin filter: AI_GENERATED, TEACHER_AUTHORED"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await QuestionBankService.list_questions(
            session=session,
            subject_version_id=subject_version_id,
            scope_node_id=scope_node_id,
            status=status_filter,
            search=search,
            origin_type=origin_type,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Error listing question bank items: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "LIST_QUESTIONS_FAILED", "message": str(e)},
        )


@router.get(
    "/questions/{question_id}",
    response_model=QuestionBankItemDetailResponse,
    summary="Retrieve single Question Bank item with full options and provenance",
)
async def get_question_bank_item(
    question_id: str,
    session: AsyncSession = Depends(get_db),
):
    item = await QuestionBankService.get_question(session, question_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "QUESTION_NOT_FOUND", "message": f"Question '{question_id}' not found in Question Bank."},
        )
    return item


@router.post(
    "/questions/save-generated",
    response_model=SaveGeneratedQuestionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Server-authoritative persistence of validated generated MCQs into the Question Bank",
)
async def save_generated_questions_endpoint(
    request: SaveGeneratedQuestionsRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await QuestionBankService.save_generated_questions(
            session=session,
            request=request,
        )
    except ValueError as ve:
        err_str = str(ve)
        if "JOB_NOT_FOUND" in err_str:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "JOB_NOT_FOUND", "message": err_str},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "SAVE_FAILED", "message": err_str},
        )
    except Exception as e:
        logger.error(f"Error saving generated questions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Failed to save generated questions to Question Bank."},
        )


@router.patch(
    "/questions/batch-archive",
    summary="Archive or restore multiple Question Bank items",
)
async def batch_archive_questions_endpoint(
    request: BatchArchiveQuestionsRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        updated_count = await QuestionBankService.batch_archive_questions(session, request)
        action_str = "archived" if request.archive else "restored"
        return {"updated_count": updated_count, "message": f"{updated_count} question(s) successfully {action_str}."}
    except Exception as e:
        logger.error(f"Error batch archiving questions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "ARCHIVE_FAILED", "message": str(e)},
        )
