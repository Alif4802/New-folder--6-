import asyncio
import json
import logging
import time
import uuid
import re
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.textbook import CurriculumNode, Lesson, SubjectVersion, Unit
from app.schemas.assessment import (
    CurriculumScopeInfo,
    CurriculumScopeNodeResponse,
    MCQCapabilitiesResponse,
    MCQGenerateRequest,
    MCQGenerationResponse,
    SubjectVersionScopeInfo,
)
from app.schemas.llm_mcq import (
    LLMMCGCandidateResponse,
    LLMMCGItem,
    MCQVerificationResponse,
)
from app.schemas.textbook import LessonScopeResponse, UnitScopeResponse
from app.services.assessment.resolver import (
    ResolvedCoveragePlan,
    ScopeCoverageResolver,
    SourceChunk,
    SourceWindow,
)
import math
from app.services.assessment.validator import MCQValidator, RejectionAccounting
from app.services.llm.base import LLMProvider
from app.services.llm.budget import ProviderBudget, TokenEstimator
from app.services.llm.factory import get_llm_provider
from app.services.llm.groq_provider import GroqProvider

logger = logging.getLogger("nctb.services.assessment.generator")

# Ephemeral in-memory TTL exclusion cache for "Generate Again" variation
# Maps request_id -> (timestamp, List[normalized_stem])
_EPHEMERAL_EXCLUSION_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_CACHE_TTL_SECONDS = 900  # 15 minutes
_MAX_CACHE_ENTRIES = 500


def _clean_expired_cache_entries():
    """Prunes expired entries from the ephemeral exclusion cache."""
    now = time.time()
    expired = [k for k, (ts, _) in _EPHEMERAL_EXCLUSION_CACHE.items() if now - ts > _CACHE_TTL_SECONDS]
    for k in expired:
        _EPHEMERAL_EXCLUSION_CACHE.pop(k, None)
    if len(_EPHEMERAL_EXCLUSION_CACHE) > _MAX_CACHE_ENTRIES:
        sorted_keys = sorted(_EPHEMERAL_EXCLUSION_CACHE.keys(), key=lambda k: _EPHEMERAL_EXCLUSION_CACHE[k][0])
        for k in sorted_keys[: len(_EPHEMERAL_EXCLUSION_CACHE) - _MAX_CACHE_ENTRIES]:
            _EPHEMERAL_EXCLUSION_CACHE.pop(k, None)


class MCQGeneratorService:
    """
    Central orchestrator for LLM-based MCQ generation, source grounding,
    multi-scope hierarchical coverage resolution, token-budgeted context windowing,
    sequential rate-aware batching, duplicate prevention, and Answer Key mapping.
    """

    @classmethod
    def _load_subject_profiles(cls) -> Dict[str, Dict]:
        try:
            if settings.ASSESSMENT_PROFILES_PATH.is_file():
                with open(settings.ASSESSMENT_PROFILES_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("profiles", {})
        except Exception as e:
            logger.warning(f"Could not load assessment profiles: {e}")
        return {}

    @classmethod
    def _build_scope_tree(cls, nodes: List[CurriculumNode]) -> List[CurriculumScopeNodeResponse]:
        """Builds a recursive tree of CurriculumScopeNodeResponse objects from flat nodes."""
        nodes_by_id: Dict[str, CurriculumScopeNodeResponse] = {}
        roots: List[CurriculumScopeNodeResponse] = []

        sorted_nodes = sorted(nodes, key=lambda n: (n.depth, n.ordinal))

        for n in sorted_nodes:
            resp = CurriculumScopeNodeResponse(
                id=n.id,
                node_type=n.node_type,
                source_label=n.source_label,
                title=n.title,
                detected_number=n.detected_number,
                depth=n.depth,
                start_page=n.start_pdf_page,
                end_page=n.end_pdf_page,
                children=[],
            )
            nodes_by_id[n.id] = resp
            if n.parent_id and n.parent_id in nodes_by_id:
                nodes_by_id[n.parent_id].children.append(resp)
            else:
                roots.append(resp)

        return roots

    @classmethod
    async def get_capabilities(
        cls,
        session: AsyncSession,
        subject_version_id: str,
    ) -> MCQCapabilitiesResponse:
        """
        Evaluate and return capabilities for the given textbook version.
        Routes eligibility using configuration-driven assessment profiles.
        Builds source-faithful generic scope tree.
        """
        profiles = cls._load_subject_profiles()

        stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == subject_version_id)
            .options(
                selectinload(SubjectVersion.grade),
                selectinload(SubjectVersion.subject),
                selectinload(SubjectVersion.curriculum_nodes),
                selectinload(SubjectVersion.units).selectinload(Unit.lessons),
            )
        )
        res = await session.execute(stmt)
        version = res.scalar_one_or_none()

        if not version:
            raise ValueError(f"TEXTBOOK_NOT_FOUND: Textbook version '{subject_version_id}' was not found.")

        from app.services.assessment.readiness import AssessmentReadinessService
        readiness = AssessmentReadinessService.evaluate(version)
        generation_supported = readiness.is_ready
        unsupported_reason = None
        if not generation_supported:
            reason_labels = {
                "TEXTBOOK_DELETED": "This textbook has been deleted.",
                "INGESTION_INCOMPLETE": "Textbook ingestion is still processing or incomplete.",
                "GRADE_NOT_ASSIGNED": "Class / Grade has not been assigned to this textbook.",
                "SUBJECT_NOT_RESOLVED": "Academic Subject has not been resolved. Please edit metadata.",
                "SUBJECT_NOT_SUPPORTED": "MCQ assessment generation is not currently supported for this subject.",
                "STRUCTURE_NEEDS_REFRESH": "Curriculum structure needs to be refreshed.",
                "PDF_NOT_AVAILABLE": "The textbook PDF file is not available.",
            }
            unsupported_reason = "; ".join([reason_labels.get(r, r) for r in readiness.reasons])

        active_provider = get_llm_provider()
        llm_configured = active_provider.is_configured if hasattr(active_provider, "is_configured") else True
        if settings.LLM_PROVIDER == "mock":
            llm_configured = True

        scope_tree: List[CurriculumScopeNodeResponse] = []
        if version.curriculum_nodes:
            scope_tree = cls._build_scope_tree(version.curriculum_nodes)

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

        max_total = settings.MCQ_MAX_TOTAL_QUESTIONS

        return MCQCapabilitiesResponse(
            subject_version_id=version.id,
            title=version.title,
            subject=version.subject.name if version.subject else None,
            subject_code=version.subject.code if version.subject else None,
            grade=version.grade.name if version.grade else None,
            grade_id=version.grade.id if version.grade else None,
            generation_supported=generation_supported,
            unsupported_reason=unsupported_reason,
            llm_configured=llm_configured,
            min_question_count=1,
            max_question_count=max_total,
            max_total_questions=max_total,
            default_question_count=5,
            generation_batch_size=5,
            supported_types=["MCQ"],
            scope_tree=scope_tree,
            units=units_scope,
        )

    @classmethod
    def _render_template(cls, template_str: str, **kwargs) -> str:
        res = template_str
        for k, v in kwargs.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(k) + r"\s*\}\}")
            val_str = str(v)
            res = pattern.sub(lambda _: val_str, res)

        def replace_conditional(match):
            var_name = match.group(1).strip()
            content = match.group(2)
            if kwargs.get(var_name):
                return content
            return ""

        res = re.sub(r"\{%\s*if\s+([a-zA-Z0-9_]+)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}", replace_conditional, res)
        return res

    @classmethod
    def _read_prompt(cls, filename: str) -> str:
        prompt_file = settings.PROMPTS_DIR / filename
        if not prompt_file.is_file():
            return ""
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()

    @classmethod
    async def generate_mcqs(
        cls,
        session: AsyncSession,
        request: MCQGenerateRequest,
        provider: Optional[LLMProvider] = None,
    ) -> MCQGenerationResponse:
        """
        Orchestrates multi-scope, token-budgeted, sequential MCQ generation:
        1. Normalizes multi-scope input (`scope_node_ids`).
        2. Resolves coverage into token-budgeted source windows.
        3. Generates MCQs across source windows in sequential rate-aware batches.
        4. Performs verification with cited-only chunk context.
        5. Enforces global duplicate prevention and exact count contract.
        """
        _clean_expired_cache_entries()

        # 1. Check capabilities
        capabilities = await cls.get_capabilities(session, request.subject_version_id)
        if not capabilities.generation_supported:
            raise ValueError(f"UNSUPPORTED_SUBJECT: {capabilities.unsupported_reason}")

        # Cross-grade check
        if request.grade_id is not None and capabilities.grade_id is not None and request.grade_id != capabilities.grade_id:
            raise ValueError("GRADE_MISMATCH: The selected textbook does not belong to the selected Class / Grade.")

        llm = provider or get_llm_provider()
        is_provider_configured = llm.is_configured if hasattr(llm, "is_configured") else True
        if not is_provider_configured and settings.LLM_PROVIDER != "mock":
            raise ValueError("LLM_NOT_CONFIGURED: No LLM provider is configured. Please set GROQ_API_KEY or OPENROUTER_API_KEY in backend .env.")

        # 2. Normalize scope_node_ids
        target_scope_ids: List[str] = []
        if request.scope_node_ids:
            target_scope_ids = [s for s in request.scope_node_ids if s]
        elif request.scope_node_id:
            target_scope_ids = [request.scope_node_id]
        elif request.unit_id is not None:
            # Fallback to finding curriculum nodes matching unit
            stmt_nodes = select(CurriculumNode).where(
                CurriculumNode.subject_version_id == request.subject_version_id
            )
            res_nodes = await session.execute(stmt_nodes)
            c_nodes = res_nodes.scalars().all()
            if c_nodes:
                target_scope_ids = [c_nodes[0].id]
            else:
                target_scope_ids = [f"unit_{request.unit_id}"]

        if not target_scope_ids:
            stmt_nodes = select(CurriculumNode).where(
                CurriculumNode.subject_version_id == request.subject_version_id
            )
            res_nodes = await session.execute(stmt_nodes)
            c_nodes = res_nodes.scalars().all()
            if c_nodes:
                target_scope_ids = [c_nodes[0].id]
            else:
                target_scope_ids = ["default_scope"]

        budget = ProviderBudget.get_default_budget()

        # 3. Resolve Multi-Scope Coverage into Token-Safe Source Windows
        plan: ResolvedCoveragePlan = await ScopeCoverageResolver.resolve_coverage(
            session=session,
            subject_version_id=request.subject_version_id,
            scope_node_ids=target_scope_ids,
            requested_count=request.count,
            budget=budget,
        )

        logger.info(
            f"Resolved coverage for {len(plan.normalized_scope_node_ids)} scope(s) into "
            f"{len(plan.source_windows)} source window(s), total estimated input tokens: {plan.total_estimated_tokens}"
        )

        # 4. Load Prompts & Profiles
        base_sys_prompt = cls._read_prompt("mcq_generation_system.md")
        profile_filename = f"mcq_profile_{plan.subject_code}.md"
        profile_prompt = cls._read_prompt(profile_filename)
        full_sys_prompt = f"{base_sys_prompt}\n\n{profile_prompt}" if profile_prompt else base_sys_prompt

        user_prompt_template = cls._read_prompt("mcq_generation_user.md")
        verify_sys_prompt = cls._read_prompt("mcq_verification_system.md")
        verify_user_template = cls._read_prompt("mcq_verification_user.md")

        # 5. Initialize Exclusion Ledger
        seen_stems: List[str] = []
        if request.previous_job_id and request.previous_job_id in GenerationJobService._JOBS:
            prev_job = GenerationJobService._JOBS[request.previous_job_id]
            if prev_job.accepted_raw_items:
                for q in prev_job.accepted_raw_items:
                    if q.stem and q.stem not in seen_stems:
                        seen_stems.append(q.stem)
            elif prev_job.questions:
                for q in prev_job.questions:
                    if q.question_text and q.question_text not in seen_stems:
                        seen_stems.append(q.question_text)
            logger.info(f"Loaded {len(seen_stems)} previous stems from previous_job_id '{request.previous_job_id}' into exclusion ledger.")

        if request.previous_request_id and request.previous_request_id in _EPHEMERAL_EXCLUSION_CACHE:
            _, prev_stems = _EPHEMERAL_EXCLUSION_CACHE[request.previous_request_id]
            for s in prev_stems:
                if s not in seen_stems:
                    seen_stems.append(s)
            logger.info(f"Loaded {len(prev_stems)} previous stems from previous_request_id '{request.previous_request_id}' into exclusion ledger.")

        accepted_items: List[LLMMCGItem] = []
        cfg_max_rounds = getattr(settings, "MCQ_MAX_GENERATION_ROUNDS", 6)
        max_rounds = min(max(len(plan.source_windows), 4), cfg_max_rounds)
        max_provider_calls = getattr(settings, "MCQ_MAX_PROVIDER_CALLS_PER_JOB", 12)
        provider_calls = 0
        round_count = 0
        window_idx = 0

        # If generating a new set with previous exclusion history, start at a different window if multiple exist
        if seen_stems and len(plan.source_windows) > 1:
            window_idx = 1 % len(plan.source_windows)

        accounting = RejectionAccounting()
        oversample_ratio = getattr(settings, "MCQ_CANDIDATE_OVERSAMPLE_RATIO", 1.25)
        accepted_per_window: Dict[str, int] = {w.window_id: 0 for w in plan.source_windows}
        num_windows = len(plan.source_windows)

        # 6. Sequential, Token-Budgeted Generation Loop Across Source Windows
        while (
            len(accepted_items) < request.count
            and round_count < max_rounds
            and provider_calls < max_provider_calls
        ):
            round_count += 1
            needed = request.count - len(accepted_items)
            is_pass_1 = round_count <= num_windows

            # In Pass 1, prioritize windows that haven't met their quota yet
            if is_pass_1 and num_windows > 1:
                candidate_window = plan.source_windows[window_idx % num_windows]
                quota = max(1, candidate_window.target_question_count)
                if accepted_per_window.get(candidate_window.window_id, 0) >= quota:
                    for offset in range(1, num_windows):
                        alt_win = plan.source_windows[(window_idx + offset) % num_windows]
                        alt_quota = max(1, alt_win.target_question_count)
                        if accepted_per_window.get(alt_win.window_id, 0) < alt_quota:
                            window_idx = (window_idx + offset) % num_windows
                            break

            active_window: SourceWindow = plan.source_windows[window_idx % num_windows]
            window_idx += 1

            quota = max(1, active_window.target_question_count)
            window_deficit = max(0, quota - accepted_per_window.get(active_window.window_id, 0))

            if is_pass_1 and num_windows > 1 and window_deficit > 0:
                batch_target = min(window_deficit, needed)
            else:
                batch_target = min(5, needed)

            oversample_extra = 1 if (is_pass_1 and num_windows > 1) else 2
            oversampled_candidates = min(math.ceil(batch_target * oversample_ratio), needed + oversample_extra)

            logger.info(
                f"Generation Round {round_count}/{max_rounds} (call {provider_calls + 1}/{max_provider_calls}): "
                f"generating {batch_target} MCQs (oversampled to {oversampled_candidates}) "
                f"from window '{active_window.scope_label}', progress: {len(accepted_items)}/{request.count}..."
            )

            exclusion_text = ""
            if seen_stems:
                exclusion_text = "\n".join(f"- {s}" for s in seen_stems[-20:])

            def render_user_prompt(chunk_list):
                formatted_chunks = "\n\n".join(
                    f'<SOURCE id="{c.chunk_id}" page="{c.page_number}">\n{c.content}\n</SOURCE>'
                    for c in chunk_list
                )
                return cls._render_template(
                    user_prompt_template,
                    textbook_title=plan.subject_title,
                    grade_name=plan.grade_name,
                    subject_name=plan.subject_name,
                    scope_description=active_window.scope_label,
                    requested_count=oversampled_candidates,
                    exclusion_ledger_text=exclusion_text,
                    source_chunks_text=formatted_chunks,
                )

            # Authoritatively enforce token budget <= 2800
            fitted_chunks, user_prompt, est_prompt_tokens = TokenEstimator.enforce_prompt_token_budget(
                chunks=active_window.chunks,
                render_user_prompt_fn=render_user_prompt,
                system_prompt=full_sys_prompt,
                max_target_tokens=budget.request_token_target,
                schema_name="LLMMCGCandidateResponse",
            )
            logger.info(f"Budget Check: Estimated prompt tokens = {est_prompt_tokens} (Target <= {budget.request_token_target})")

            try:
                provider_calls += 1
                candidate: LLMMCGCandidateResponse = await llm.generate_structured(
                    system_instruction=full_sys_prompt,
                    user_prompt=user_prompt,
                    response_schema=LLMMCGCandidateResponse,
                )
            except Exception as e:
                err_str = str(e)
                logger.error(f"LLM Generation call failed in round {round_count}: {err_str}")
                if (
                    "LLM_TEMPORARILY_UNAVAILABLE" in err_str
                    or "temporarily unavailable" in err_str.lower()
                    or "all llm providers" in err_str.lower()
                ):
                    break
                if "LLM_RATE_LIMIT" in err_str or "LLM_REQUEST_TOO_LARGE" in err_str:
                    logger.info("Encountered provider rate/size limit. Backing off 2.0s before next window...")
                    await asyncio.sleep(2.0)
                if round_count >= max_rounds or provider_calls >= max_provider_calls:
                    break
                continue

            accounting.candidates_returned += len(candidate.questions) if candidate.questions else 0

            if candidate.insufficient_context:
                logger.warning(f"Window '{active_window.scope_label}' reported insufficient context: {candidate.insufficient_reason}")
                continue

            if not candidate.questions:
                continue

            # Validate each candidate item in the batch against structural & duplicate rules
            valid_batch_candidates: List[LLMMCGItem] = []
            valid_cids = set(c.chunk_id for c in fitted_chunks)

            for q in candidate.questions:
                issues = MCQValidator.validate_single_item(
                    q=q,
                    valid_chunk_ids=valid_cids,
                    existing_stems=seen_stems,
                    near_duplicate_threshold=0.82,
                )
                if issues:
                    cat = issues[0].category
                    if hasattr(accounting, cat):
                        setattr(accounting, cat, getattr(accounting, cat) + 1)
                    else:
                        accounting.other_rejected += 1
                    logger.warning(f"Candidate question rejected ({cat}): {issues}")
                else:
                    # Assign collision-resistant full UUID transient identities
                    q_stable_id = f"gen_q_{uuid.uuid4().hex}"
                    opt_id_map: Dict[str, str] = {}
                    for opt in q.options:
                        stable_opt_id = f"gen_opt_{uuid.uuid4().hex}"
                        opt_id_map[opt.id] = stable_opt_id
                        opt.id = stable_opt_id
                    if q.correct_option_id in opt_id_map:
                        q.correct_option_id = opt_id_map[q.correct_option_id]
                    q.question_id = q_stable_id
                    valid_batch_candidates.append(q)
                    seen_stems.append(q.stem)

            if not valid_batch_candidates:
                accounting.check_invariant(f"Round {round_count}")
                continue

            # Build Cited-Only Verification Context with full chunk content
            cited_chunk_ids: Set[str] = set()
            for q in valid_batch_candidates:
                if q.source_chunk_ids:
                    cited_chunk_ids.update(q.source_chunk_ids)

            cited_chunks = [c for c in fitted_chunks if c.chunk_id in cited_chunk_ids][:4]
            if not cited_chunks:
                cited_chunks = fitted_chunks[:3]

            verify_blocks = [
                f'<SOURCE id="{c.chunk_id}" page="{c.page_number}">\n{c.content}\n</SOURCE>'
                for c in cited_chunks
            ]
            verify_source_text = "\n\n".join(verify_blocks)

            candidate_payload = LLMMCGCandidateResponse(questions=valid_batch_candidates)
            candidate_json = json.dumps(candidate_payload.model_dump(), indent=2)
            verify_user_prompt = cls._render_template(
                verify_user_template,
                candidate_questions_json=candidate_json,
                source_chunks_text=verify_source_text,
            )

            # Safe pace between generation and verification
            await asyncio.sleep(0.8)

            try:
                provider_calls += 1
                verification: MCQVerificationResponse = await llm.generate_structured(
                    system_instruction=verify_sys_prompt,
                    user_prompt=verify_user_prompt,
                    response_schema=MCQVerificationResponse,
                )
            except Exception as ve_err:
                logger.warning(f"Verification pass notice ({ve_err}). Accepting candidate on structural pass.")
                verification = MCQVerificationResponse(all_valid=True, evaluations=[])

            # Filter verified items
            verified_q_ids = set()
            if verification.all_valid:
                verified_q_ids = {q.question_id for q in valid_batch_candidates}
            else:
                for ev in verification.evaluations:
                    if ev.is_valid and ev.is_grounded_in_source and ev.is_single_correct_answer:
                        verified_q_ids.add(ev.question_id)
                    else:
                        accounting.llm_verification_rejected += 1

            # Add verified items up to requested count with quota bounding for intra-set diversity
            max_accept_this_round = min(window_deficit, needed) if (is_pass_1 and num_windows > 1 and window_deficit > 0) else needed
            accepted_this_round = 0

            for q in valid_batch_candidates:
                if q.question_id in verified_q_ids or not verification.evaluations:
                    if len(accepted_items) < request.count and accepted_this_round < max_accept_this_round:
                        accepted_items.append(q)
                        accepted_per_window[active_window.window_id] = accepted_per_window.get(active_window.window_id, 0) + 1
                        accepted_this_round += 1
                        accounting.final_accepted += 1
                    else:
                        accounting.surplus_not_needed += 1

            accounting.check_invariant(f"Round {round_count}")

            # Safe pace between successive calls
            if len(accepted_items) < request.count:
                await asyncio.sleep(0.4)

        accounting.log_summary(logger, context_str="Sync MCQ Generation")

        # 7. Exact Count Contract Check
        if len(accepted_items) < request.count:
            logger.error(f"Insufficient unique source coverage: requested {request.count}, accepted {len(accepted_items)} after {round_count} rounds.")
            raise ValueError(
                f"INSUFFICIENT_UNIQUE_SOURCE_COVERAGE: Only {len(accepted_items)} sufficiently distinct grounded MCQs could be produced from the selected scopes (requested {request.count}). Select broader coverage or request fewer questions."
            )

        # 8. Assign labels (A, B, C, D) preserving LLM ordering
        questions_out, answer_key_out = MCQValidator.assign_labels_and_build_answer_key_for_items(accepted_items)

        # 9. Record in ephemeral exclusion cache
        request_id = f"mcq_{uuid.uuid4().hex[:12]}"
        _EPHEMERAL_EXCLUSION_CACHE[request_id] = (time.time(), [q.stem for q in accepted_items])

        # 10. Build Scope Info Response
        scope_info = CurriculumScopeInfo(
            scope_node_ids=plan.normalized_scope_node_ids,
            scope_title=plan.combined_scope_description,
        )

        return MCQGenerationResponse(
            request_id=request_id,
            subject_version=SubjectVersionScopeInfo(
                id=capabilities.subject_version_id,
                title=capabilities.title,
                grade=capabilities.grade,
                grade_id=capabilities.grade_id,
                subject=capabilities.subject,
            ),
            scope=scope_info,
            requested_count=request.count,
            generated_count=len(questions_out),
            questions=questions_out,
            answer_key=answer_key_out,
            warnings=[],
        )
