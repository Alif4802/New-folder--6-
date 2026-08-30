import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question_bank import (
    QuestionBankItem,
    QuestionBankOption,
    QuestionSet,
    QuestionSetItem,
    QuestionSetScope,
)
from app.models.textbook import CurriculumNode, SubjectVersion
from app.schemas.question_bank import (
    PaperAnswerKeyItemResponse,
    PaperItemOptionResponse,
    PaperItemQuestionResponse,
    PaperMetadataSchema,
    PaperSourceType,
    QuestionArrangementRequest,
    QuestionSetDetailResponse,
    QuestionSetListResponse,
    QuestionSetSummaryResponse,
    SaveGeneratedQuestionsRequest,
    SavePaperRequest,
)
from app.services.assessment.job_service import GenerationJobService
from app.services.question_bank.bank_service import QuestionBankService

logger = logging.getLogger("nctb.services.question_bank.paper")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QuestionPaperService:
    """
    Service for managing Saved Question Papers (QuestionSets) with exact question/option
    arrangement snapshots, dynamic Answer Key computation, and zero-LLM persistence.
    """

    @classmethod
    async def save_paper(
        cls,
        session: AsyncSession,
        request: SavePaperRequest,
    ) -> QuestionSetDetailResponse:
        """
        Transactional paper persistence:
        1. If saving from a generation job, ensures all questions are saved to the Question Bank first.
        2. Validates question existence, SubjectVersion ownership, and option integrity.
        3. Enforces uniqueness on question_order and option_order.
        4. Creates QuestionSet, QuestionSetItems, and QuestionSetScopes atomically.
        """
        if not request.arrangements:
            raise ValueError("EMPTY_ARRANGEMENTS: At least one question arrangement must be provided.")

        # 1. Fetch SubjectVersion
        sv_stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == request.subject_version_id)
            .options(selectinload(SubjectVersion.subject), selectinload(SubjectVersion.grade))
        )
        sv_res = await session.execute(sv_stmt)
        version = sv_res.scalar_one_or_none()
        if not version:
            raise ValueError(f"TEXTBOOK_NOT_FOUND: SubjectVersion '{request.subject_version_id}' not found.")

        # 2. Server-authoritative persistence and explicit mapping
        gen_mapping_by_id: Dict[str, Any] = {}
        qbi_entities_by_id: Dict[str, QuestionBankItem] = {}

        if request.source_type == PaperSourceType.GENERATED_JOB:
            job = GenerationJobService.get_raw_job(request.job_id)  # type: ignore[arg-type]
            if not job:
                raise ValueError(f"JOB_NOT_FOUND: Generation job '{request.job_id}' not found or expired.")

            save_gen_resp = await QuestionBankService.save_generated_questions(
                session=session,
                request=SaveGeneratedQuestionsRequest(job_id=request.job_id),  # type: ignore[arg-type]
            )

            for m in save_gen_resp.saved_items_map:
                gen_mapping_by_id[m.generated_question_id] = m

            all_target_qbi_ids = [m.question_bank_item_id for m in save_gen_resp.saved_items_map]
            if all_target_qbi_ids:
                qbis_stmt = (
                    select(QuestionBankItem)
                    .where(QuestionBankItem.id.in_(all_target_qbi_ids))
                    .options(selectinload(QuestionBankItem.options))
                )
                qbis_res = await session.execute(qbis_stmt)
                for q_ent in qbis_res.scalars().all():
                    qbi_entities_by_id[q_ent.id] = q_ent

        # 3. Validate arrangements and collect target QuestionBankItems
        validated_items: List[Tuple[QuestionBankItem, int, List[str]]] = []
        seen_orders: Set[int] = set()
        seen_qbi_ids: Set[str] = set()

        for arr in request.arrangements:
            # Check question order uniqueness
            if arr.question_order in seen_orders:
                raise ValueError(f"DUPLICATE_QUESTION_ORDER: Question order {arr.question_order} is specified more than once.")
            if arr.question_order < 1:
                raise ValueError(f"INVALID_QUESTION_ORDER: Question order must be >= 1 (got {arr.question_order}).")
            seen_orders.add(arr.question_order)

            # Resolve QuestionBankItem entity
            qbi: Optional[QuestionBankItem] = None
            opt_id_translation: Dict[str, str] = {}

            if request.source_type == PaperSourceType.GENERATED_JOB:
                m = gen_mapping_by_id.get(arr.question_id)
                if m:
                    qbi = qbi_entities_by_id.get(m.question_bank_item_id)
                    opt_id_translation = m.option_id_map
                else:
                    # Fallback lookup in case direct QBI ID was passed
                    if arr.question_id in qbi_entities_by_id:
                        qbi = qbi_entities_by_id[arr.question_id]
            else:
                # Direct lookup by QuestionBankItem.id for QUESTION_BANK source
                stmt = (
                    select(QuestionBankItem)
                    .where(QuestionBankItem.id == arr.question_id)
                    .options(selectinload(QuestionBankItem.options))
                )
                res = await session.execute(stmt)
                qbi = res.scalar_one_or_none()

            if not qbi:
                raise ValueError(f"QUESTION_NOT_FOUND: Question '{arr.question_id}' does not exist in Question Bank.")

            # Validate subject version ownership (Anti-tampering: prevent cross-subject contamination)
            if qbi.subject_version_id != request.subject_version_id:
                raise ValueError(
                    f"FOREIGN_SUBJECT_QUESTION: Question '{qbi.id}' belongs to SubjectVersion '{qbi.subject_version_id}', not '{request.subject_version_id}'."
                )

            if qbi.id in seen_qbi_ids:
                raise ValueError(f"DUPLICATE_QUESTION_IN_PAPER: Question '{qbi.id}' is added more than once to this paper.")
            seen_qbi_ids.add(qbi.id)

            # Validate options integrity
            valid_opt_ids = {opt.id for opt in qbi.options}
            client_opt_ids = arr.option_order

            # Translate transient generated option IDs using the mapping
            if opt_id_translation:
                translated_opts = [opt_id_translation.get(oid, oid) for oid in client_opt_ids]
                if all(to in valid_opt_ids for to in translated_opts):
                    client_opt_ids = translated_opts

            # If client passed raw candidate option IDs or letter labels fallback
            if len(client_opt_ids) == 4 and not all(oid in valid_opt_ids for oid in client_opt_ids):
                db_opts_sorted = sorted(qbi.options, key=lambda x: x.canonical_order)
                letter_idx_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'a': 0, 'b': 1, 'c': 2, 'd': 3}
                translated_opt_ids: List[str] = []
                for cid in client_opt_ids:
                    num_match = cid.replace("opt_", "").replace("opt", "").strip()
                    if num_match.isdigit():
                        idx = int(num_match) - 1
                        if 0 <= idx < len(db_opts_sorted):
                            translated_opt_ids.append(db_opts_sorted[idx].id)
                    elif cid in letter_idx_map:
                        idx = letter_idx_map[cid]
                        if 0 <= idx < len(db_opts_sorted):
                            translated_opt_ids.append(db_opts_sorted[idx].id)
                    elif cid in valid_opt_ids:
                        translated_opt_ids.append(cid)

                if len(translated_opt_ids) == 4:
                    client_opt_ids = translated_opt_ids

            if len(client_opt_ids) != 4:
                raise ValueError(f"INVALID_OPTION_COUNT: Question '{qbi.id}' must have exactly 4 option IDs in option_order (got {len(client_opt_ids)}).")

            if len(set(client_opt_ids)) != 4:
                raise ValueError(f"DUPLICATE_OPTION_IDS: Question '{qbi.id}' has duplicate option IDs in option_order: {client_opt_ids}.")

            if not all(oid in valid_opt_ids for oid in client_opt_ids):
                invalid_ids = [oid for oid in client_opt_ids if oid not in valid_opt_ids]
                raise ValueError(f"FOREIGN_OPTION_ID: Option IDs {invalid_ids} do not belong to Question '{qbi.id}'.")

            if qbi.correct_option_id and qbi.correct_option_id not in client_opt_ids:
                raise ValueError(f"CORRECT_OPTION_MISSING: Correct option '{qbi.correct_option_id}' is missing from option_order for Question '{qbi.id}'.")

            validated_items.append((qbi, arr.question_order, client_opt_ids))

        # 4. Create QuestionSet entity
        set_id = f"qset_{uuid.uuid4().hex[:12]}"
        meta_dict = request.paper_metadata.model_dump() if request.paper_metadata else {}

        # Default header settings from subject version if missing
        subj_display = version.subject.name if version.subject else "Mathematics"
        grd_display = version.grade.name if version.grade else ""
        if not meta_dict.get("subject_name"):
            meta_dict["subject_name"] = subj_display
        if not meta_dict.get("grade_name") and grd_display:
            meta_dict["grade_name"] = grd_display
        if not meta_dict.get("total_marks"):
            meta_dict["total_marks"] = len(validated_items) * meta_dict.get("marks_per_question", 1.0)

        qset = QuestionSet(
            id=set_id,
            title=request.title.strip(),
            description=request.description.strip() if request.description else None,
            subject_version_id=request.subject_version_id,
            set_type="QUESTION_PAPER",
            question_count=len(validated_items),
            paper_metadata=meta_dict,
            status="ACTIVE",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(qset)
        await session.flush()

        # 5. Create QuestionSetItem records with exact presentation order and option snapshot
        for qbi, q_order, opt_order in validated_items:
            qsi_id = f"qsi_{uuid.uuid4().hex[:12]}"
            qsi = QuestionSetItem(
                id=qsi_id,
                set_id=set_id,
                question_bank_item_id=qbi.id,
                question_order=q_order,
                option_order=opt_order,
                created_at=utc_now(),
            )
            session.add(qsi)

        # 6. Create QuestionSetScope records
        if request.scope_node_ids:
            for node_id in set(request.scope_node_ids):
                qss = QuestionSetScope(
                    set_id=set_id,
                    curriculum_node_id=node_id,
                )
                session.add(qss)

        await session.commit()

        # 7. Re-fetch and return complete paper detail
        detail = await cls.get_paper(session, set_id)
        if not detail:
            raise RuntimeError(f"FAILED_TO_RELOAD_SAVED_PAPER: QuestionSet '{set_id}' could not be reloaded.")
        return detail

    @classmethod
    async def get_paper(
        cls,
        session: AsyncSession,
        set_id: str,
    ) -> Optional[QuestionSetDetailResponse]:
        """
        Loads a saved QuestionSet and reconstructs its exact question order, option order,
        and dynamically calculated Answer Key with zero LLM calls.
        """
        stmt = (
            select(QuestionSet)
            .where(QuestionSet.id == set_id)
            .options(
                selectinload(QuestionSet.subject_version).selectinload(SubjectVersion.subject),
                selectinload(QuestionSet.subject_version).selectinload(SubjectVersion.grade),
                selectinload(QuestionSet.items).selectinload(QuestionSetItem.question_bank_item).selectinload(QuestionBankItem.options),
                selectinload(QuestionSet.scopes),
            )
        )
        res = await session.execute(stmt)
        qset = res.scalar_one_or_none()
        if not qset:
            return None

        sv = qset.subject_version
        subj_name = sv.subject.name if sv and sv.subject else "Mathematics"
        grd_name = sv.grade.name if sv and sv.grade else None

        display_labels = ["A", "B", "C", "D"]
        questions_out: List[PaperItemQuestionResponse] = []
        answer_key_out: List[PaperAnswerKeyItemResponse] = []

        # Sort items by question_order
        sorted_items = sorted(qset.items, key=lambda x: x.question_order)

        for item in sorted_items:
            qbi = item.question_bank_item
            if not qbi:
                continue

            options_by_id = {opt.id: opt for opt in qbi.options}

            # Reconstruct options in exact snapshot order
            options_out: List[PaperItemOptionResponse] = []
            correct_letter = "A"
            correct_text = ""
            correct_latex = None

            for opt_idx, opt_id in enumerate(item.option_order[:4]):
                lbl = display_labels[opt_idx]
                db_opt = options_by_id.get(opt_id)
                if db_opt:
                    options_out.append(
                        PaperItemOptionResponse(
                            id=db_opt.id,
                            label=lbl,
                            text=db_opt.option_text,
                            latex=db_opt.option_latex,
                        )
                    )
                    if qbi.correct_option_id and db_opt.id == qbi.correct_option_id:
                        correct_letter = lbl
                        correct_text = db_opt.option_text
                        correct_latex = db_opt.option_latex

            questions_out.append(
                PaperItemQuestionResponse(
                    id=qbi.id,
                    question_number=item.question_order,
                    question_text=qbi.question_text,
                    question_latex=qbi.question_latex,
                    options=options_out,
                    correct_option_id=qbi.correct_option_id,
                    explanation=qbi.explanation,
                )
            )

            answer_key_out.append(
                PaperAnswerKeyItemResponse(
                    question_number=item.question_order,
                    question_id=qbi.id,
                    correct_letter=correct_letter,
                    correct_text=correct_text,
                    correct_latex=correct_latex,
                    explanation=qbi.explanation,
                )
            )

        meta_obj = PaperMetadataSchema(**qset.paper_metadata) if qset.paper_metadata else None
        scope_ids = [s.curriculum_node_id for s in qset.scopes]

        return QuestionSetDetailResponse(
            id=qset.id,
            title=qset.title,
            description=qset.description,
            subject_version_id=qset.subject_version_id,
            subject_title=sv.title if sv else "Textbook",
            grade_name=grd_name,
            subject_name=subj_name,
            set_type=qset.set_type,
            question_count=qset.question_count,
            paper_metadata=meta_obj,
            status=qset.status,
            questions=questions_out,
            answer_key=answer_key_out,
            scope_node_ids=scope_ids,
            created_at=qset.created_at.isoformat(),
            updated_at=qset.updated_at.isoformat(),
        )

    @classmethod
    async def list_papers(
        cls,
        session: AsyncSession,
        subject_version_id: Optional[str] = None,
        status: str = "ACTIVE",
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionSetListResponse:
        """Paginates saved QuestionSets."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        query = select(QuestionSet)
        if subject_version_id:
            query = query.where(QuestionSet.subject_version_id == subject_version_id)
        if status:
            query = query.where(QuestionSet.status == status)

        count_query = select(func.count()).select_from(query.subquery())
        total_res = await session.execute(count_query)
        total_count = total_res.scalar() or 0

        query = (
            query.order_by(QuestionSet.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .options(
                selectinload(QuestionSet.subject_version).selectinload(SubjectVersion.subject),
                selectinload(QuestionSet.subject_version).selectinload(SubjectVersion.grade),
            )
        )
        res = await session.execute(query)
        sets = res.scalars().all()

        summaries: List[QuestionSetSummaryResponse] = []
        for qs in sets:
            sv = qs.subject_version
            subj_name = sv.subject.name if sv and sv.subject else "Mathematics"
            grd_name = sv.grade.name if sv and sv.grade else None

            summaries.append(
                QuestionSetSummaryResponse(
                    id=qs.id,
                    title=qs.title,
                    description=qs.description,
                    subject_version_id=qs.subject_version_id,
                    subject_title=sv.title if sv else "Textbook",
                    grade_name=grd_name,
                    subject_name=subj_name,
                    set_type=qs.set_type,
                    question_count=qs.question_count,
                    status=qs.status,
                    created_at=qs.created_at.isoformat(),
                    updated_at=qs.updated_at.isoformat(),
                )
            )

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return QuestionSetListResponse(
            items=summaries,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @classmethod
    async def archive_paper(
        cls,
        session: AsyncSession,
        set_id: str,
        archive: bool = True,
    ) -> bool:
        """
        Soft-archives a QuestionSet.
        CRITICAL: Does NOT delete, mutate, or cascade to QuestionBankItem records.
        """
        stmt = select(QuestionSet).where(QuestionSet.id == set_id)
        res = await session.execute(stmt)
        qs = res.scalar_one_or_none()
        if not qs:
            return False

        qs.status = "ARCHIVED" if archive else "ACTIVE"
        qs.archived_at = utc_now() if archive else None
        qs.updated_at = utc_now()
        await session.commit()
        return True
