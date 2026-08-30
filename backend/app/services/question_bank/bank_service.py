import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question_bank import (
    QuestionBankItem,
    QuestionBankOption,
    QuestionBankItemScope,
    QuestionBankItemProvenance,
)
from app.models.textbook import CurriculumNode, SubjectVersion
from app.schemas.question_bank import (
    BatchArchiveQuestionsRequest,
    QuestionBankItemDetailResponse,
    QuestionBankItemListResponse,
    QuestionBankOptionSchema,
    QuestionBankProvenanceSchema,
    QuestionBankScopeSchema,
    SavedQuestionBankItemMapping,
    SaveGeneratedQuestionsRequest,
    SaveGeneratedQuestionsResponse,
)
from app.services.assessment.job_service import GenerationJobService

logger = logging.getLogger("nctb.services.question_bank.bank")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text_for_hash(text: str) -> str:
    """Normalizes whitespace and casing for canonical content hash calculation."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def calculate_canonical_content_hash(
    stem: str,
    options: List[str],
    correct_text: str,
    question_type: str = "MCQ",
) -> str:
    """
    Calculates a SHA-256 hash of the question content that is invariant to:
    - Presentation order of options (options are sorted before hashing)
    - Whitespace and casing nuances
    - Database auto-increment / UUID keys
    """
    normalized_stem = normalize_text_for_hash(stem)
    normalized_correct = normalize_text_for_hash(correct_text)
    normalized_options = sorted([normalize_text_for_hash(opt) for opt in options if opt])

    payload = {
        "type": question_type.upper(),
        "stem": normalized_stem,
        "options": normalized_options,
        "correct": normalized_correct,
    }
    raw_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


class QuestionBankService:
    """Core domain service for persistent Question Bank operations."""

    @classmethod
    async def save_generated_questions(
        cls,
        session: AsyncSession,
        request: SaveGeneratedQuestionsRequest,
    ) -> SaveGeneratedQuestionsResponse:
        """
        Server-authoritative persistence of validated generated MCQs:
        1. Loads accepted questions from in-memory GenerationJob.
        2. Calculates canonical content hash ignoring presentation order.
        3. Reuses existing QuestionBankItem if content_hash already exists in database.
        4. Otherwise creates QuestionBankItem, QuestionBankOption records, scopes, and stable provenance.
        5. Returns exact count of new saved vs reused questions and explicit transient->persistent mappings.
        """
        job = GenerationJobService.get_raw_job(request.job_id)
        if not job:
            raise ValueError(f"JOB_NOT_FOUND: Generation job '{request.job_id}' not found or expired from cache.")

        if not job.accepted_raw_items:
            raise ValueError(f"NO_QUESTIONS: Generation job '{request.job_id}' has no accepted validated questions.")

        # Fetch SubjectVersion metadata for provenance derivation
        sv_stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == job.subject_version_id)
            .options(selectinload(SubjectVersion.subject), selectinload(SubjectVersion.grade))
        )
        sv_res = await session.execute(sv_stmt)
        version = sv_res.scalar_one_or_none()
        if not version:
            raise ValueError(f"TEXTBOOK_NOT_FOUND: SubjectVersion '{job.subject_version_id}' not found.")

        # Determine target questions to save
        candidate_items = job.accepted_raw_items
        if request.question_ids:
            requested_set = set(request.question_ids)
            candidate_items = [q for q in candidate_items if q.question_id in requested_set]

        if not candidate_items:
            raise ValueError("NO_MATCHING_QUESTIONS: No questions matched the specified question_ids.")

        new_saved_count = 0
        reused_count = 0
        saved_qbi_list: List[QuestionBankItem] = []
        saved_mappings: List[SavedQuestionBankItemMapping] = []

        chunk_map = job.chunk_map or {}

        for item in candidate_items:
            # 1. Extract option texts and find correct option text
            opt_texts = [opt.text for opt in item.options[:4]]
            correct_opt = next((o for o in item.options if o.id == item.correct_option_id), None)
            correct_text = correct_opt.text if correct_opt else ""

            # 2. Compute canonical content hash
            content_hash = calculate_canonical_content_hash(
                stem=item.stem,
                options=opt_texts,
                correct_text=correct_text,
                question_type="MCQ",
            )

            # 3. Check for existing question bank item in this subject version
            check_stmt = select(QuestionBankItem).where(
                QuestionBankItem.subject_version_id == job.subject_version_id,
                QuestionBankItem.question_type == "MCQ",
                QuestionBankItem.content_hash == content_hash,
            ).options(
                selectinload(QuestionBankItem.options),
                selectinload(QuestionBankItem.scopes).selectinload(QuestionBankItemScope.curriculum_node),
                selectinload(QuestionBankItem.provenances),
            )
            check_res = await session.execute(check_stmt)
            existing_qbi = check_res.scalar_one_or_none()

            if existing_qbi:
                reused_count += 1
                saved_qbi_list.append(existing_qbi)
                opt_map: Dict[str, str] = {}
                existing_opts_sorted = sorted(existing_qbi.options, key=lambda x: x.canonical_order)
                for opt_idx, opt in enumerate(item.options[:4]):
                    if opt_idx < len(existing_opts_sorted):
                        opt_map[opt.id] = existing_opts_sorted[opt_idx].id
                saved_mappings.append(
                    SavedQuestionBankItemMapping(
                        generated_question_id=item.question_id,
                        question_bank_item_id=existing_qbi.id,
                        option_id_map=opt_map,
                        is_created=False,
                    )
                )
                continue

            # 4. Create new QuestionBankItem
            qbi_id = f"qbi_{uuid.uuid4().hex[:12]}"
            new_qbi = QuestionBankItem(
                id=qbi_id,
                subject_version_id=job.subject_version_id,
                question_type="MCQ",
                language="en",
                question_text=item.stem.strip(),
                question_latex=item.stem_latex,
                explanation=item.explanation.strip(),
                content_hash=content_hash,
                origin_type="AI_GENERATED",
                grounding_source="OFFICIAL_NCTB",
                status="ACTIVE",
                generation_request_id=job.request_id,
                generation_provider=job.sticky_provider or "primary",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(new_qbi)
            await session.flush()

            # 5. Create normalized QuestionBankOption records with stable IDs
            option_id_map: Dict[str, str] = {}  # item.option.id -> new option DB id
            created_options: List[QuestionBankOption] = []
            target_correct_db_id = None

            for opt_idx, opt in enumerate(item.options[:4]):
                opt_db_id = f"opt_{uuid.uuid4().hex[:12]}"
                db_opt = QuestionBankOption(
                    id=opt_db_id,
                    question_id=qbi_id,
                    option_text=opt.text.strip(),
                    option_latex=opt.latex,
                    canonical_order=opt_idx,
                    created_at=utc_now(),
                )
                session.add(db_opt)
                created_options.append(db_opt)
                option_id_map[opt.id] = opt_db_id
                if opt.id == item.correct_option_id:
                    target_correct_db_id = opt_db_id

            await session.flush()

            # 6. Set correct_option_id with referential integrity
            new_qbi.correct_option_id = target_correct_db_id
            await session.flush()

            # 7. Create generic CurriculumNode scope links
            resolved_scope_ids = set(job.scope_node_ids or [])
            for cid in item.source_chunk_ids:
                chunk = chunk_map.get(cid)
                if chunk and chunk.curriculum_node_id:
                    resolved_scope_ids.add(chunk.curriculum_node_id)

            for sn_id in resolved_scope_ids:
                scope_link = QuestionBankItemScope(
                    question_bank_item_id=qbi_id,
                    curriculum_node_id=sn_id,
                )
                session.add(scope_link)

            # 8. Create stable source provenance records (no request-local SRC-* IDs!)
            cited_chunks = [chunk_map.get(cid) for cid in item.source_chunk_ids if chunk_map.get(cid)]
            if not cited_chunks and chunk_map:
                cited_chunks = list(chunk_map.values())[:1]

            for chunk in cited_chunks:
                snippet = (chunk.content[:200] + "...") if len(chunk.content) > 200 else chunk.content
                s_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
                prov = QuestionBankItemProvenance(
                    question_bank_item_id=qbi_id,
                    subject_version_id=job.subject_version_id,
                    curriculum_node_id=chunk.curriculum_node_id,
                    activity_node_id=chunk.activity_node_id,
                    page_number=chunk.page_number,
                    source_hash=s_hash,
                    source_content_snippet=snippet,
                    created_at=utc_now(),
                )
                session.add(prov)

            new_saved_count += 1
            saved_qbi_list.append(new_qbi)
            saved_mappings.append(
                SavedQuestionBankItemMapping(
                    generated_question_id=item.question_id,
                    question_bank_item_id=qbi_id,
                    option_id_map=option_id_map,
                    is_created=True,
                )
            )

        await session.commit()

        # Re-fetch full details for response
        response_items: List[QuestionBankItemDetailResponse] = []
        for qbi in saved_qbi_list:
            detail = await cls.get_question(session, qbi.id)
            if detail:
                response_items.append(detail)

        msg = f"{new_saved_count} new question(s) saved to bank"
        if reused_count > 0:
            msg += f", {reused_count} already existed in bank"

        return SaveGeneratedQuestionsResponse(
            new_questions_saved=new_saved_count,
            existing_questions_reused=reused_count,
            saved_items=response_items,
            saved_items_map=saved_mappings,
            message=msg,
        )

    @classmethod
    async def get_question(
        cls,
        session: AsyncSession,
        question_id: str,
    ) -> Optional[QuestionBankItemDetailResponse]:
        """Loads a single QuestionBankItem with options, scopes, and provenance."""
        stmt = (
            select(QuestionBankItem)
            .where(QuestionBankItem.id == question_id)
            .options(
                selectinload(QuestionBankItem.subject_version).selectinload(SubjectVersion.subject),
                selectinload(QuestionBankItem.subject_version).selectinload(SubjectVersion.grade),
                selectinload(QuestionBankItem.options),
                selectinload(QuestionBankItem.scopes).selectinload(QuestionBankItemScope.curriculum_node),
                selectinload(QuestionBankItem.provenances).selectinload(QuestionBankItemProvenance.curriculum_node),
            )
        )
        res = await session.execute(stmt)
        qbi = res.scalar_one_or_none()
        if not qbi:
            return None

        sv = qbi.subject_version
        subj_name = sv.subject.name if sv and sv.subject else "Mathematics"
        grd_name = sv.grade.name if sv and sv.grade else None

        opts = [
            QuestionBankOptionSchema(
                id=o.id,
                option_text=o.option_text,
                option_latex=o.option_latex,
                canonical_order=o.canonical_order,
            )
            for o in sorted(qbi.options, key=lambda x: x.canonical_order)
        ]

        scopes_out: List[QuestionBankScopeSchema] = []
        for s in qbi.scopes:
            cn = s.curriculum_node
            if cn:
                scopes_out.append(
                    QuestionBankScopeSchema(
                        id=cn.id,
                        node_type=cn.node_type,
                        source_label=cn.source_label,
                        title=cn.title,
                        detected_number=cn.detected_number,
                    )
                )

        prov_out = None
        if qbi.provenances:
            p = qbi.provenances[0]
            scope_label = p.curriculum_node.source_label if p.curriculum_node else None
            prov_out = QuestionBankProvenanceSchema(
                subject_version_id=p.subject_version_id,
                curriculum_node_id=p.curriculum_node_id,
                scope_label=scope_label,
                page_number=p.page_number,
                source_content_snippet=p.source_content_snippet,
                origin_type=qbi.origin_type,
                grounding_source=qbi.grounding_source,
            )

        return QuestionBankItemDetailResponse(
            id=qbi.id,
            subject_version_id=qbi.subject_version_id,
            subject_title=sv.title if sv else "Textbook",
            grade_name=grd_name,
            subject_name=subj_name,
            question_type=qbi.question_type,
            language=qbi.language,
            question_text=qbi.question_text,
            question_latex=qbi.question_latex,
            options=opts,
            correct_option_id=qbi.correct_option_id,
            explanation=qbi.explanation,
            difficulty=qbi.difficulty,
            marks=qbi.marks,
            origin_type=qbi.origin_type,
            grounding_source=qbi.grounding_source,
            status=qbi.status,
            scopes=scopes_out,
            provenance=prov_out,
            created_at=qbi.created_at.isoformat(),
            updated_at=qbi.updated_at.isoformat(),
        )

    @classmethod
    async def list_questions(
        cls,
        session: AsyncSession,
        subject_version_id: Optional[str] = None,
        scope_node_id: Optional[str] = None,
        status: str = "ACTIVE",
        search: Optional[str] = None,
        origin_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionBankItemListResponse:
        """
        Lists Question Bank items with dynamic relational filtering, recursive scope matching,
        text search, and pagination.
        """
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        # Base query
        query = select(QuestionBankItem)

        if subject_version_id:
            query = query.where(QuestionBankItem.subject_version_id == subject_version_id)

        if status:
            query = query.where(QuestionBankItem.status == status)

        if origin_type:
            query = query.where(QuestionBankItem.origin_type == origin_type)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    QuestionBankItem.question_text.ilike(term),
                    QuestionBankItem.explanation.ilike(term),
                )
            )

        if scope_node_id:
            # Match questions associated with this node or any of its descendants
            child_stmt = select(CurriculumNode.id).where(
                or_(
                    CurriculumNode.id == scope_node_id,
                    CurriculumNode.parent_id == scope_node_id,
                )
            )
            node_ids_res = await session.execute(child_stmt)
            target_node_ids = [r[0] for r in node_ids_res.fetchall()]

            query = query.join(QuestionBankItem.scopes).where(
                QuestionBankItemScope.curriculum_node_id.in_(target_node_ids)
            ).distinct()

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_res = await session.execute(count_query)
        total_count = total_res.scalar() or 0

        # Fetch page items
        query = (
            query.order_by(QuestionBankItem.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .options(
                selectinload(QuestionBankItem.subject_version).selectinload(SubjectVersion.subject),
                selectinload(QuestionBankItem.subject_version).selectinload(SubjectVersion.grade),
                selectinload(QuestionBankItem.options),
                selectinload(QuestionBankItem.scopes).selectinload(QuestionBankItemScope.curriculum_node),
                selectinload(QuestionBankItem.provenances).selectinload(QuestionBankItemProvenance.curriculum_node),
            )
        )
        res = await session.execute(query)
        items = res.scalars().all()

        details: List[QuestionBankItemDetailResponse] = []
        for qbi in items:
            sv = qbi.subject_version
            subj_name = sv.subject.name if sv and sv.subject else "Mathematics"
            grd_name = sv.grade.name if sv and sv.grade else None

            opts = [
                QuestionBankOptionSchema(
                    id=o.id,
                    option_text=o.option_text,
                    option_latex=o.option_latex,
                    canonical_order=o.canonical_order,
                )
                for o in sorted(qbi.options, key=lambda x: x.canonical_order)
            ]

            scopes_out: List[QuestionBankScopeSchema] = []
            for s in qbi.scopes:
                cn = s.curriculum_node
                if cn:
                    scopes_out.append(
                        QuestionBankScopeSchema(
                            id=cn.id,
                            node_type=cn.node_type,
                            source_label=cn.source_label,
                            title=cn.title,
                            detected_number=cn.detected_number,
                        )
                    )

            prov_out = None
            if qbi.provenances:
                p = qbi.provenances[0]
                scope_label = p.curriculum_node.source_label if p.curriculum_node else None
                prov_out = QuestionBankProvenanceSchema(
                    subject_version_id=p.subject_version_id,
                    curriculum_node_id=p.curriculum_node_id,
                    scope_label=scope_label,
                    page_number=p.page_number,
                    source_content_snippet=p.source_content_snippet,
                    origin_type=qbi.origin_type,
                    grounding_source=qbi.grounding_source,
                )

            details.append(
                QuestionBankItemDetailResponse(
                    id=qbi.id,
                    subject_version_id=qbi.subject_version_id,
                    subject_title=sv.title if sv else "Textbook",
                    grade_name=grd_name,
                    subject_name=subj_name,
                    question_type=qbi.question_type,
                    language=qbi.language,
                    question_text=qbi.question_text,
                    question_latex=qbi.question_latex,
                    options=opts,
                    correct_option_id=qbi.correct_option_id,
                    explanation=qbi.explanation,
                    difficulty=qbi.difficulty,
                    marks=qbi.marks,
                    origin_type=qbi.origin_type,
                    grounding_source=qbi.grounding_source,
                    status=qbi.status,
                    scopes=scopes_out,
                    provenance=prov_out,
                    created_at=qbi.created_at.isoformat(),
                    updated_at=qbi.updated_at.isoformat(),
                )
            )

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return QuestionBankItemListResponse(
            items=details,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @classmethod
    async def batch_archive_questions(
        cls,
        session: AsyncSession,
        request: BatchArchiveQuestionsRequest,
    ) -> int:
        """Sets status of selected QuestionBankItems to ARCHIVED or ACTIVE."""
        if not request.question_ids:
            return 0

        target_status = "ARCHIVED" if request.archive else "ACTIVE"
        target_archived_at = utc_now() if request.archive else None

        stmt = (
            select(QuestionBankItem)
            .where(QuestionBankItem.id.in_(request.question_ids))
        )
        res = await session.execute(stmt)
        items = res.scalars().all()

        for item in items:
            item.status = target_status
            item.archived_at = target_archived_at
            item.updated_at = utc_now()

        await session.commit()
        return len(items)
