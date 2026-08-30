import asyncio
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionFactory, get_async_session_factory
from app.schemas.assessment import (
    CurriculumScopeInfo,
    MCQAnswerKeyItemResponse,
    MCQGenerateRequest,
    MCQJobCancelResponse,
    MCQJobCreateResponse,
    MCQJobStatusResponse,
    MCQQuestionResponse,
    SubjectVersionScopeInfo,
)
from app.schemas.llm_mcq import (
    LLMMCGItem,
    LLMMCGCandidateResponse,
    MCQVerificationResponse,
)
from app.services.assessment.resolver import (
    ResolvedCoveragePlan,
    ScopeCoverageResolver,
    SourceWindow,
)
from app.services.assessment.validator import MCQValidator, RejectionAccounting
from app.services.llm.base import LLMProvider
from app.services.llm.budget import ProviderBudget, TokenEstimator
from app.services.llm.exceptions import (
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.llm.factory import get_llm_provider
from app.services.assessment.generator import MCQGeneratorService, _EPHEMERAL_EXCLUSION_CACHE

logger = logging.getLogger("nctb.services.assessment.jobs")


@dataclass
class GenerationJob:
    job_id: str
    subject_version_id: str
    scope_node_ids: List[str]
    requested_count: int
    generated_count: int = 0
    status: str = "processing"  # processing, completed, incomplete, failed, cancelled
    stage: str = "preparing_content"  # preparing_content, generating, validating, completed
    stage_message: str = "Preparing selected textbook content..."
    questions: List[MCQQuestionResponse] = field(default_factory=list)
    answer_key: List[MCQAnswerKeyItemResponse] = field(default_factory=list)
    accepted_raw_items: List[LLMMCGItem] = field(default_factory=list)
    seen_stems: List[str] = field(default_factory=list)
    error: Optional[str] = None
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 7200.0)
    sticky_provider: Optional[str] = None
    task: Optional[asyncio.Task] = None
    accounting: RejectionAccounting = field(default_factory=RejectionAccounting)
    request_id: Optional[str] = None
    chunk_map: Dict[str, Any] = field(default_factory=dict)


class GenerationJobService:
    """
    Ephemeral in-memory job service for progressive MCQ assessment generation.
    Stores job state in memory with TTL. No database table.
    """

    _JOBS: Dict[str, GenerationJob] = {}
    _COVERAGE_PLAN_CACHE: Dict[str, Tuple[float, ResolvedCoveragePlan]] = {}

    @classmethod
    def _clean_expired(cls):
        now = time.time()
        expired_ids = [jid for jid, j in cls._JOBS.items() if now > j.expires_at]
        for jid in expired_ids:
            job = cls._JOBS.pop(jid, None)
            if job and job.task and not job.task.done():
                job.task.cancel()

        # Clean plan cache older than 10 minutes
        expired_plans = [k for k, (t, _) in cls._COVERAGE_PLAN_CACHE.items() if now - t > 600.0]
        for k in expired_plans:
            cls._COVERAGE_PLAN_CACHE.pop(k, None)

    @classmethod
    def start_job(
        cls,
        request: MCQGenerateRequest,
        provider: Optional[LLMProvider] = None,
        session_factory: Optional[Any] = None,
    ) -> MCQJobCreateResponse:
        """Initializes and dispatches an asynchronous progressive MCQ generation job."""
        cls._clean_expired()
        job_id = f"job_{uuid.uuid4().hex[:12]}"

        target_scope_ids: List[str] = []
        if request.scope_node_ids:
            target_scope_ids = [s for s in request.scope_node_ids if s]
        elif request.scope_node_id:
            target_scope_ids = [request.scope_node_id]
        elif request.unit_id is not None:
            target_scope_ids = [f"unit_{request.unit_id}"]

        seen_stems: List[str] = []
        if request.previous_job_id and request.previous_job_id in cls._JOBS:
            prev_job = cls._JOBS[request.previous_job_id]
            if prev_job.accepted_raw_items:
                for q in prev_job.accepted_raw_items:
                    if q.stem and q.stem not in seen_stems:
                        seen_stems.append(q.stem)
            elif prev_job.questions:
                for q in prev_job.questions:
                    if q.question_text and q.question_text not in seen_stems:
                        seen_stems.append(q.question_text)
            logger.info(f"Job {job_id}: loaded {len(seen_stems)} previous stems from previous_job_id '{request.previous_job_id}'.")

        if request.previous_request_id and request.previous_request_id in _EPHEMERAL_EXCLUSION_CACHE:
            _, prev_stems = _EPHEMERAL_EXCLUSION_CACHE[request.previous_request_id]
            for s in prev_stems:
                if s not in seen_stems:
                    seen_stems.append(s)
            logger.info(f"Job {job_id}: loaded {len(prev_stems)} previous stems from previous_request_id '{request.previous_request_id}'.")

        job = GenerationJob(
            job_id=job_id,
            subject_version_id=request.subject_version_id,
            scope_node_ids=target_scope_ids,
            requested_count=request.count,
            seen_stems=seen_stems,
        )

        # Launch background execution task
        task = asyncio.create_task(
            cls._execute_job(
                job_id=job_id,
                request=request,
                provider=provider,
                session_factory=session_factory,
            )
        )
        job.task = task
        cls._JOBS[job_id] = job

        return MCQJobCreateResponse(
            job_id=job_id,
            status="processing",
            requested_count=request.count,
            generated_count=0,
        )

    @classmethod
    def get_job_status(cls, job_id: str) -> Optional[MCQJobStatusResponse]:
        cls._clean_expired()
        job = cls._JOBS.get(job_id)
        if not job:
            return None

        is_complete = job.status in ["completed", "failed", "incomplete", "cancelled"]

        return MCQJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            stage=job.stage,
            stage_message=job.stage_message,
            requested_count=job.requested_count,
            generated_count=job.generated_count,
            questions=job.questions,
            answer_key=job.answer_key,
            complete=is_complete,
            error=job.error,
        )

    @classmethod
    def get_raw_job(cls, job_id: str) -> Optional[GenerationJob]:
        cls._clean_expired()
        return cls._JOBS.get(job_id)

    @classmethod
    def cancel_job(cls, job_id: str) -> MCQJobCancelResponse:
        cls._clean_expired()
        job = cls._JOBS.get(job_id)
        if not job:
            return MCQJobCancelResponse(job_id=job_id, status="not_found", message="Job not found.")

        job.cancelled = True
        job.status = "cancelled"
        job.stage_message = "Generation cancelled by user."
        if job.task and not job.task.done():
            job.task.cancel()

        return MCQJobCancelResponse(job_id=job_id, status="cancelled", message="Generation job cancelled.")

    @classmethod
    def retry_remaining(
        cls,
        job_id: str,
        provider: Optional[LLMProvider] = None,
    ) -> Optional[MCQJobCreateResponse]:
        """Creates a continuation job to finish remaining questions from an incomplete job."""
        cls._clean_expired()
        parent_job = cls._JOBS.get(job_id)
        if not parent_job or parent_job.status != "incomplete":
            return None

        new_job_id = f"job_{uuid.uuid4().hex[:12]}"
        new_job = GenerationJob(
            job_id=new_job_id,
            subject_version_id=parent_job.subject_version_id,
            scope_node_ids=parent_job.scope_node_ids,
            requested_count=parent_job.requested_count,
            generated_count=len(parent_job.accepted_raw_items),
            accepted_raw_items=list(parent_job.accepted_raw_items),
            seen_stems=list(parent_job.seen_stems),
            questions=list(parent_job.questions),
            answer_key=list(parent_job.answer_key),
            stage="generating",
            stage_message=f"Resuming generation... {len(parent_job.accepted_raw_items)} of {parent_job.requested_count} ready",
        )

        req = MCQGenerateRequest(
            subject_version_id=parent_job.subject_version_id,
            scope_node_ids=parent_job.scope_node_ids,
            count=parent_job.requested_count,
        )

        task = asyncio.create_task(cls._execute_job(job_id=new_job_id, request=req, provider=provider, resume_existing=True))
        new_job.task = task
        cls._JOBS[new_job_id] = new_job

        return MCQJobCreateResponse(
            job_id=new_job_id,
            status="processing",
            requested_count=parent_job.requested_count,
            generated_count=len(parent_job.accepted_raw_items),
        )

    @classmethod
    async def _execute_job(
        cls,
        job_id: str,
        request: MCQGenerateRequest,
        provider: Optional[LLMProvider] = None,
        resume_existing: bool = False,
        session_factory: Optional[Any] = None,
    ):
        job = cls._JOBS.get(job_id)
        if not job:
            return

        start_time = time.time()
        llm = provider or get_llm_provider()

        factory = session_factory or get_async_session_factory()
        async with factory() as session:
            try:
                # 1. Resolve Coverage Plan (with cache)
                plan_cache_key = f"{request.subject_version_id}_{','.join(sorted(job.scope_node_ids or []))}"
                plan: Optional[ResolvedCoveragePlan] = None
                now = time.time()

                if plan_cache_key in cls._COVERAGE_PLAN_CACHE:
                    cache_ts, cached_plan = cls._COVERAGE_PLAN_CACHE[plan_cache_key]
                    if now - cache_ts < 300.0:
                        plan = cached_plan
                        logger.info(f"Job {job_id}: Reusing cached coverage plan ({len(plan.source_windows)} windows).")

                if not plan:
                    job.stage = "preparing_content"
                    job.stage_message = "Preparing selected textbook content..."
                    budget = ProviderBudget.get_default_budget()
                    plan = await ScopeCoverageResolver.resolve_coverage(
                        session=session,
                        subject_version_id=request.subject_version_id,
                        scope_node_ids=job.scope_node_ids,
                        requested_count=job.requested_count,
                        budget=budget,
                    )
                    cls._COVERAGE_PLAN_CACHE[plan_cache_key] = (now, plan)

                # Populate stable chunk map for source provenance translation
                if plan and plan.source_windows:
                    job.chunk_map = {c.chunk_id: c for w in plan.source_windows for c in w.chunks}

                if job.cancelled:
                    return

                # Load prompt templates
                base_sys_prompt = MCQGeneratorService._read_prompt("mcq_generation_system.md")
                profile_filename = f"mcq_profile_{plan.subject_code}.md"
                profile_prompt = MCQGeneratorService._read_prompt(profile_filename)
                full_sys_prompt = f"{base_sys_prompt}\n\n{profile_prompt}" if profile_prompt else base_sys_prompt

                user_prompt_template = MCQGeneratorService._read_prompt("mcq_generation_user.md")
                verify_sys_prompt = MCQGeneratorService._read_prompt("mcq_verification_system.md")
                verify_user_template = MCQGeneratorService._read_prompt("mcq_verification_user.md")

                cfg_max_rounds = getattr(settings, "MCQ_MAX_GENERATION_ROUNDS", 6)
                max_rounds = min(max(len(plan.source_windows), 4), cfg_max_rounds)
                max_provider_calls = getattr(settings, "MCQ_MAX_PROVIDER_CALLS_PER_JOB", 12)
                provider_calls = 0
                round_count = 0
                window_idx = 0
                # If generating a new set with previous exclusion history, start at a different window if multiple exist
                if job.seen_stems and len(plan.source_windows) > 1:
                    window_idx = 1 % len(plan.source_windows)

                # Track accepted count per window for fair intra-set diversity
                accepted_per_window: Dict[str, int] = {w.window_id: 0 for w in plan.source_windows}
                num_windows = len(plan.source_windows)
                oversample_ratio = getattr(settings, "MCQ_CANDIDATE_OVERSAMPLE_RATIO", 1.25)

                while (
                    len(job.accepted_raw_items) < job.requested_count
                    and round_count < max_rounds
                    and provider_calls < max_provider_calls
                ):
                    if job.cancelled:
                        return

                    round_count += 1
                    deficit = job.requested_count - len(job.accepted_raw_items)
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
                        batch_target = min(window_deficit, deficit)
                    else:
                        batch_target = min(5, deficit)

                    oversample_extra = 1 if (is_pass_1 and num_windows > 1) else 2
                    oversampled_candidates = min(math.ceil(batch_target * oversample_ratio), deficit + oversample_extra)

                    job.stage = "generating"
                    job.stage_message = f"Generating questions... {len(job.accepted_raw_items)} of {job.requested_count} ready"

                    exclusion_text = ""
                    if job.seen_stems:
                        exclusion_text = "\n".join(f"- {s}" for s in job.seen_stems[-20:])

                    # Render prompt builder function for token budgeting
                    def render_user_prompt(chunk_list):
                        formatted_chunks = "\n\n".join(
                            f'<SOURCE id="{c.chunk_id}" page="{c.page_number}">\n{c.content}\n</SOURCE>'
                            for c in chunk_list
                        )
                        return MCQGeneratorService._render_template(
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
                    budget = ProviderBudget.get_default_budget()
                    fitted_chunks, user_prompt, total_est_tokens = TokenEstimator.enforce_prompt_token_budget(
                        chunks=active_window.chunks,
                        render_user_prompt_fn=render_user_prompt,
                        system_prompt=full_sys_prompt,
                        max_target_tokens=budget.request_token_target,
                        schema_name="LLMMCGCandidateResponse",
                    )

                    logger.info(
                        f"Job {job_id} Round {round_count}/{max_rounds} (call {provider_calls + 1}/{max_provider_calls}): "
                        f"generating target {batch_target} (oversampled to {oversampled_candidates}) "
                        f"from '{active_window.scope_label}', budget={total_est_tokens}/{budget.request_token_target}..."
                    )

                    # Generation call
                    try:
                        active_llm = llm if not job.sticky_provider else get_llm_provider(job.sticky_provider)
                        provider_calls += 1
                        candidate: LLMMCGCandidateResponse = await active_llm.generate_structured(
                            system_instruction=full_sys_prompt,
                            user_prompt=user_prompt,
                            response_schema=LLMMCGCandidateResponse,
                        )
                    except Exception as e:
                        err_str = str(e)
                        logger.error(f"Job {job_id} Round {round_count} LLM error: {err_str}")
                        if (
                            "LLM_TEMPORARILY_UNAVAILABLE" in err_str
                            or "temporarily unavailable" in err_str.lower()
                            or "all llm providers" in err_str.lower()
                        ):
                            break
                        if "LLM_RATE_LIMIT" in err_str or "LLM_REQUEST_TOO_LARGE" in err_str:
                            await asyncio.sleep(2.0)
                        if round_count >= max_rounds or provider_calls >= max_provider_calls:
                            break
                        continue

                    job.accounting.candidates_returned += len(candidate.questions) if candidate.questions else 0

                    if candidate.insufficient_context:
                        logger.warning(f"Job {job_id} window '{active_window.scope_label}' reported insufficient context.")
                        continue

                    if not candidate.questions:
                        continue

                    # Validate single items
                    valid_batch_candidates: List[LLMMCGItem] = []
                    valid_cids = set(c.chunk_id for c in fitted_chunks)

                    for q in candidate.questions:
                        issues = MCQValidator.validate_single_item(
                            q=q,
                            valid_chunk_ids=valid_cids,
                            existing_stems=job.seen_stems,
                            near_duplicate_threshold=0.82,
                        )
                        if issues:
                            cat = issues[0].category
                            if hasattr(job.accounting, cat):
                                setattr(job.accounting, cat, getattr(job.accounting, cat) + 1)
                            else:
                                job.accounting.other_rejected += 1
                            logger.warning(f"Job {job_id} candidate rejected ({cat}): {issues}")
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
                            job.seen_stems.append(q.stem)

                    if not valid_batch_candidates:
                        job.accounting.check_invariant(f"Job {job_id} Round {round_count}")
                        continue

                    # Cited-only verification context
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
                    verify_user_prompt = MCQGeneratorService._render_template(
                        verify_user_template,
                        candidate_questions_json=candidate_json,
                        source_chunks_text=verify_source_text,
                    )

                    await asyncio.sleep(0.8)

                    try:
                        active_llm = llm if not job.sticky_provider else get_llm_provider(job.sticky_provider)
                        provider_calls += 1
                        verification: MCQVerificationResponse = await active_llm.generate_structured(
                            system_instruction=verify_sys_prompt,
                            user_prompt=verify_user_prompt,
                            response_schema=MCQVerificationResponse,
                        )
                    except Exception as ve_err:
                        logger.warning(f"Job {job_id} verification notice ({ve_err}). Accepting on structural pass.")
                        verification = MCQVerificationResponse(all_valid=True, evaluations=[])

                    verified_q_ids = set()
                    if verification.all_valid:
                        verified_q_ids = {q.question_id for q in valid_batch_candidates}
                    else:
                        for ev in verification.evaluations:
                            if ev.is_valid and ev.is_grounded_in_source and ev.is_single_correct_answer:
                                verified_q_ids.add(ev.question_id)
                            else:
                                job.accounting.llm_verification_rejected += 1

                    # Add verified items up to requested count with quota bounding for intra-set diversity
                    max_accept_this_round = min(window_deficit, deficit) if (is_pass_1 and num_windows > 1 and window_deficit > 0) else deficit
                    accepted_this_round = 0

                    for q in valid_batch_candidates:
                        if q.question_id in verified_q_ids or not verification.evaluations:
                            if len(job.accepted_raw_items) < job.requested_count and accepted_this_round < max_accept_this_round:
                                job.accepted_raw_items.append(q)
                                accepted_per_window[active_window.window_id] = accepted_per_window.get(active_window.window_id, 0) + 1
                                accepted_this_round += 1
                                job.accounting.final_accepted += 1
                            else:
                                job.accounting.surplus_not_needed += 1

                    job.accounting.check_invariant(f"Job {job_id} Round {round_count}")

                    # PROGRESSIVE UPDATE: Expose validated questions immediately
                    q_out, ak_out = MCQValidator.assign_labels_and_build_answer_key_for_items(job.accepted_raw_items)
                    job.questions = q_out
                    job.answer_key = ak_out
                    job.generated_count = len(q_out)
                    logger.info(f"Job {job_id} progress updated: {job.generated_count}/{job.requested_count} ready.")

                    if len(job.accepted_raw_items) >= job.requested_count:
                        break

                    await asyncio.sleep(0.4)

                # Finalize Job State
                duration_ms = round((time.time() - start_time) * 1000, 2)
                job.accounting.log_summary(logger, context_str=f"Job {job_id}")

                if len(job.accepted_raw_items) >= job.requested_count:
                    job.status = "completed"
                    job.stage = "completed"
                    job.stage_message = "Finishing assessment..."

                    # Cache exclusion ledger
                    req_id = f"mcq_{uuid.uuid4().hex[:12]}"
                    job.request_id = req_id
                    _EPHEMERAL_EXCLUSION_CACHE[req_id] = (time.time(), [q.stem for q in job.accepted_raw_items])

                    logger.info(
                        f"Job {job_id} Completed: generated {job.generated_count}/{job.requested_count} "
                        f"in {duration_ms}ms."
                    )
                elif len(job.accepted_raw_items) > 0:
                    job.status = "incomplete"
                    job.stage = "completed"
                    job.stage_message = f"{len(job.accepted_raw_items)} of {job.requested_count} questions generated. Remaining could not be completed."
                    logger.warning(f"Job {job_id} Incomplete: {len(job.accepted_raw_items)}/{job.requested_count} after {round_count} rounds.")
                else:
                    job.status = "failed"
                    job.stage = "completed"
                    job.error = "INSUFFICIENT_UNIQUE_SOURCE_COVERAGE: Could not generate sufficient distinct grounded MCQs."
                    job.stage_message = "Generation failed."

            except Exception as ex:
                logger.error(f"Job {job_id} unhandled exception: {ex}", exc_info=True)
                if len(job.accepted_raw_items) > 0:
                    job.status = "incomplete"
                    job.stage_message = f"{len(job.accepted_raw_items)} of {job.requested_count} questions generated."
                else:
                    job.status = "failed"
                    job.error = str(ex)
                    job.stage_message = "Generation failed."
