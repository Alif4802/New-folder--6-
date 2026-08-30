import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.assessment import (
    MCQAnswerKeyItemResponse,
    MCQCapabilitiesResponse,
    MCQGenerateRequest,
    MCQGenerationResponse,
    MCQJobCancelResponse,
    MCQJobCreateResponse,
    MCQJobStatusResponse,
    MCQQuestionResponse,
)
from app.services.assessment.generator import MCQGeneratorService
from app.services.assessment.job_service import GenerationJobService
from app.services.assessment.validator import MCQValidator

logger = logging.getLogger("nctb.api.assessments")

router = APIRouter(prefix="/assessments/mcq", tags=["Assessments"])


@router.get(
    "/capabilities",
    response_model=MCQCapabilitiesResponse,
    summary="Retrieve MCQ assessment generation capabilities and scope hierarchy for a textbook",
)
async def get_assessment_capabilities(
    subject_version_id: str = Query(..., description="Ingested textbook SubjectVersion UUID"),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await MCQGeneratorService.get_capabilities(
            session=session,
            subject_version_id=subject_version_id,
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "TEXTBOOK_NOT_FOUND" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": err_msg},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "BAD_REQUEST", "message": err_msg},
        )
    except Exception as e:
        logger.error(f"Error fetching MCQ capabilities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Failed to retrieve assessment capabilities."},
        )


from sqlalchemy import select
from app.models.textbook import SubjectVersion

@router.post(
    "/jobs",
    response_model=MCQJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an asynchronous progressive MCQ generation job",
)
async def start_generation_job(
    request: MCQGenerateRequest,
    session: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    from app.services.assessment.readiness import AssessmentReadinessService

    sv_stmt = (
        select(SubjectVersion)
        .where(SubjectVersion.id == request.subject_version_id)
        .options(selectinload(SubjectVersion.subject))
    )
    sv_res = await session.execute(sv_stmt)
    version = sv_res.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": f"Textbook '{request.subject_version_id}' not found."},
        )

    # Authoritative cross-grade consistency check
    if request.grade_id is not None:
        if version.grade_id is not None and version.grade_id != request.grade_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "GRADE_MISMATCH",
                    "message": "The selected textbook does not belong to the selected Class / Grade.",
                },
            )

    # Authoritative Assessment Readiness check
    readiness = AssessmentReadinessService.evaluate(version)
    if not readiness.is_ready:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "TEXTBOOK_NOT_ASSESSMENT_READY",
                "message": f"Textbook '{version.title}' is not ready for assessment generation: {', '.join(readiness.reasons)}",
                "reasons": readiness.reasons,
            },
        )

    try:
        return GenerationJobService.start_job(request=request)
    except Exception as e:
        logger.error(f"Error starting generation job: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "JOB_START_FAILED", "message": str(e)},
        )


@router.get(
    "/jobs/{job_id}",
    response_model=MCQJobStatusResponse,
    summary="Poll status and progressive verified questions for an active generation job",
)
async def get_generation_job_status(
    job_id: str,
):
    job_status = GenerationJobService.get_job_status(job_id)
    if not job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "JOB_NOT_FOUND", "message": f"Generation job '{job_id}' not found."},
        )
    return job_status


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=MCQJobCancelResponse,
    summary="Cancel an in-progress generation job",
)
async def cancel_generation_job(
    job_id: str,
):
    return GenerationJobService.cancel_job(job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=MCQJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry generating remaining questions for an incomplete job",
)
async def retry_remaining_job(
    job_id: str,
):
    continuation = GenerationJobService.retry_remaining(job_id)
    if not continuation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "CANNOT_RETRY", "message": "Job is not eligible for retry."},
        )
    return continuation


class RandomizePaperRequest(BaseModel):
    questions: List[MCQQuestionResponse]
    answer_key: List[MCQAnswerKeyItemResponse]


class RandomizePaperResponse(BaseModel):
    questions: List[MCQQuestionResponse]
    answer_key: List[MCQAnswerKeyItemResponse]


@router.post(
    "/randomize",
    response_model=RandomizePaperResponse,
    summary="Instant, zero-LLM randomization of questions and options with dynamic Answer Key remapping",
)
async def randomize_paper_endpoint(
    req: RandomizePaperRequest,
):
    shuffled_q, shuffled_ak = MCQValidator.randomize_paper(req.questions, req.answer_key)
    return RandomizePaperResponse(questions=shuffled_q, answer_key=shuffled_ak)


@router.post(
    "/generate",
    response_model=MCQGenerationResponse,
    summary="Generate grounded MCQ assessment paper synchronously",
)
async def generate_mcq_assessment(
    request: MCQGenerateRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        return await MCQGeneratorService.generate_mcqs(
            session=session,
            request=request,
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "LLM_NOT_CONFIGURED" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_code": "LLM_NOT_CONFIGURED", "message": err_msg},
            )
        elif "UNSUPPORTED_SUBJECT" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "UNSUPPORTED_SUBJECT", "message": err_msg},
            )
        elif "INVALID_CURRICULUM_SCOPE" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "INVALID_CURRICULUM_SCOPE", "message": err_msg},
            )
        elif "INSUFFICIENT_SOURCE_CONTENT" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INSUFFICIENT_SOURCE_CONTENT", "message": err_msg},
            )
        elif "TEXTBOOK_NOT_FOUND" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "TEXTBOOK_NOT_FOUND", "message": err_msg},
            )
        elif "GENERATION_FAILED" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error_code": "GENERATION_FAILED", "message": err_msg},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "BAD_REQUEST", "message": err_msg},
            )
    except TimeoutError as te:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"error_code": "LLM_TIMEOUT", "message": str(te)},
        )
    except RuntimeError as re:
        err_msg = str(re)
        if "LLM_TEMPORARILY_UNAVAILABLE" in err_msg or "LLM_QUOTA_EXHAUSTED" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_code": "LLM_TEMPORARILY_UNAVAILABLE", "message": err_msg},
            )
        elif "LLM_RATE_LIMIT" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error_code": "LLM_RATE_LIMIT", "message": err_msg},
            )
        elif "LLM_PROVIDER_ERROR" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error_code": "LLM_PROVIDER_ERROR", "message": err_msg},
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "RUNTIME_ERROR", "message": err_msg},
        )
    except Exception as e:
        logger.error(f"Unhandled MCQ generation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred during MCQ generation."},
        )
