import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.curriculum import Curriculum, Subject
from app.schemas.textbook import SubjectResponse, SubjectSummary
from app.services.pdf.subject_profiles import subject_registry

logger = logging.getLogger("nctb.api.subjects")
router = APIRouter()


@router.get("", response_model=SubjectResponse, summary="List canonical subjects for a curriculum")
async def list_subjects(
    curriculum_id: Optional[int] = Query(None, description="Curriculum authority ID. Defaults to active curriculum."),
    session: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    """
    Returns canonical educational subjects scoped to a curriculum authority.
    Subject definitions are authoritative and curriculum-scoped.
    """
    # 1. Resolve target curriculum
    if curriculum_id is None:
        curr_stmt = select(Curriculum.id).where(Curriculum.is_active == True).limit(1)
        curr_res = await session.execute(curr_stmt)
        curriculum_id = curr_res.scalar_one_or_none() or 1

    # 2. Fetch canonical subjects from database
    stmt = (
        select(Subject)
        .where(Subject.curriculum_id == curriculum_id)
        .order_by(Subject.name.asc())
    )
    res = await session.execute(stmt)
    subjects_db = res.scalars().all()

    # Determine generation support based on profiles/domain
    supported_codes = {p.code for p in subject_registry.list_profiles() if p.domain in ["STEM", "LANGUAGE"]}
    summaries = []
    for s in subjects_db:
        is_supported = s.domain in ["STEM", "LANGUAGE"] or s.code in supported_codes
        summaries.append(
            SubjectSummary(
                id=s.id,
                curriculum_id=s.curriculum_id,
                code=s.code,
                name=s.name,
                domain=s.domain,
                is_supported_for_generation=is_supported,
            )
        )

    return SubjectResponse(subjects=summaries, total=len(summaries))
