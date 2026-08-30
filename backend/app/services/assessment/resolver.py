import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.textbook import ActivityNode, CurriculumNode, SubjectVersion
from app.services.llm.budget import ProviderBudget, TokenEstimator

logger = logging.getLogger("nctb.services.assessment.resolver")


@dataclass
class SourceChunk:
    chunk_id: str  # e.g. "SRC-001"
    page_number: int
    title: Optional[str]
    content: str
    scope_label: str
    sub_label: Optional[str] = None
    activity_node_id: Optional[int] = None
    curriculum_node_id: Optional[str] = None


@dataclass
class SourceWindow:
    window_id: str
    scope_label: str
    chunks: List[SourceChunk]
    formatted_xml: str
    valid_chunk_ids: Set[str]
    estimated_tokens: int
    target_question_count: int = 1


@dataclass
class ResolvedCoveragePlan:
    subject_version_id: str
    subject_title: str
    grade_name: str
    subject_name: str
    subject_code: str
    combined_scope_description: str
    normalized_scope_node_ids: List[str]
    source_windows: List[SourceWindow]
    total_chunks: int
    total_estimated_tokens: int


class ScopeCoverageResolver:
    """
    Resolves multi-scope selections into normalized, non-overlapping coverage,
    validates ownership against the target SubjectVersion, and creates bounded,
    token-safe source windows.
    """

    @classmethod
    def normalize_selected_nodes(
        cls,
        nodes: List[CurriculumNode],
    ) -> List[CurriculumNode]:
        """
        Removes redundant descendant nodes when their ancestor is already selected.
        e.g., if Chapter 4 (parent) is selected, child 4.1 is omitted from root resolution
        so content is not duplicated.
        """
        node_ids = {n.id for n in nodes}
        node_map = {n.id: n for n in nodes}
        normalized: List[CurriculumNode] = []

        for node in nodes:
            # Check if any ancestor is in node_ids
            curr_parent_id = node.parent_id
            has_selected_ancestor = False
            while curr_parent_id:
                if curr_parent_id in node_ids:
                    has_selected_ancestor = True
                    break
                # Walk up tree if parent is in map
                parent_node = node_map.get(curr_parent_id)
                curr_parent_id = parent_node.parent_id if parent_node else None

            if not has_selected_ancestor:
                normalized.append(node)

        return sorted(normalized, key=lambda x: (x.depth, x.ordinal))

    @classmethod
    async def resolve_coverage(
        cls,
        session: AsyncSession,
        subject_version_id: str,
        scope_node_ids: List[str],
        requested_count: int = 5,
        budget: Optional[ProviderBudget] = None,
    ) -> ResolvedCoveragePlan:
        if not scope_node_ids:
            raise ValueError("INVALID_CURRICULUM_SCOPE: At least one curriculum scope must be selected.")

        prov_budget = budget or ProviderBudget.get_default_budget()
        target_token_window = prov_budget.request_token_target

        # 1. Fetch SubjectVersion with curriculum nodes
        stmt = (
            select(SubjectVersion)
            .where(SubjectVersion.id == subject_version_id)
            .options(
                selectinload(SubjectVersion.grade),
                selectinload(SubjectVersion.subject),
                selectinload(SubjectVersion.curriculum_nodes),
            )
        )
        res = await session.execute(stmt)
        version = res.scalar_one_or_none()
        if not version:
            raise ValueError(f"TEXTBOOK_NOT_FOUND: SubjectVersion '{subject_version_id}' does not exist.")

        # Determine subject code & names
        subject_name = version.subject.name if version.subject else "Curriculum"
        subject_code = version.subject.code.lower() if (version.subject and version.subject.code) else "mathematics"
        v_title_lower = (version.title or "").lower()
        if "grammar" in v_title_lower:
            subject_code = "english_grammar"
        elif "english for today" in v_title_lower:
            subject_code = "english_for_today"
        elif "math" in v_title_lower:
            subject_code = "mathematics"

        grade_name = version.grade.name if version.grade else "NCTB Grade"

        # 2. Validate scope_node_ids belong to version or map from legacy
        all_version_nodes_map = {n.id: n for n in (version.curriculum_nodes or [])}
        selected_nodes: List[CurriculumNode] = []

        # If curriculum_nodes is empty (legacy fixture), check units
        if not all_version_nodes_map and version.units:
            # Synthetic resolution from units/lessons
            source_windows: List[SourceWindow] = []
            global_chunk_idx = 1

            stmt_nodes = select(ActivityNode).where(
                ActivityNode.subject_version_id == subject_version_id
            ).order_by(ActivityNode.ordinal)
            res_nodes = await session.execute(stmt_nodes)
            all_acts = res_nodes.scalars().all()

            if not all_acts:
                raise ValueError(f"EMPTY_CURRICULUM_SCOPE: No textbook content found for version '{subject_version_id}'.")

            # Batch activity nodes into bounded windows
            batch_size = 12
            for i in range(0, len(all_acts), batch_size):
                batch_acts = all_acts[i : i + batch_size]
                lbl = f"{version.title} (Section {i//batch_size + 1})"
                win = cls._build_window_from_nodes(
                    act_nodes=batch_acts,
                    scope_label=lbl,
                    start_chunk_idx=global_chunk_idx,
                )
                if win and win.chunks:
                    source_windows.append(win)
                    global_chunk_idx += len(win.chunks)

            cls._allocate_question_counts(source_windows, requested_count)
            total_chunks = sum(len(w.chunks) for w in source_windows)
            total_tokens = sum(w.estimated_tokens for w in source_windows)

            return ResolvedCoveragePlan(
                subject_version_id=version.id,
                subject_title=version.title,
                grade_name=grade_name,
                subject_name=subject_name,
                subject_code=subject_code,
                combined_scope_description=version.title,
                normalized_scope_node_ids=["legacy_all"],
                source_windows=source_windows,
                total_chunks=total_chunks,
                total_estimated_tokens=total_tokens,
            )

        for sid in scope_node_ids:
            if sid not in all_version_nodes_map:
                raise ValueError(
                    f"INVALID_CURRICULUM_SCOPE: Selected scope ID '{sid}' does not belong to textbook version '{subject_version_id}'."
                )
            selected_nodes.append(all_version_nodes_map[sid])

        # 3. Normalize overlapping scopes
        normalized_nodes = cls.normalize_selected_nodes(selected_nodes)
        normalized_ids = [n.id for n in normalized_nodes]

        # Build combined scope description
        scope_descs = [f"{n.source_label or n.node_type.title()}: {n.title}" for n in normalized_nodes]
        if len(scope_descs) == 1:
            combined_desc = scope_descs[0]
        elif len(scope_descs) <= 3:
            combined_desc = " + ".join(scope_descs)
        else:
            combined_desc = f"{len(scope_descs)} Selected Curriculum Scopes ({scope_descs[0]} and others)"

        # 4. Fetch Activity Nodes for all normalized scopes
        # For each normalized node, find its descendant IDs and page ranges
        source_windows: List[SourceWindow] = []
        global_chunk_idx = 1

        for node in normalized_nodes:
            # Find all descendant nodes under this node
            descendant_ids = {node.id}
            for n in version.curriculum_nodes or []:
                if n.parent_id == node.id or (n.parent_id and n.parent_id in descendant_ids):
                    descendant_ids.add(n.id)

            start_p = node.start_pdf_page
            end_p = node.end_pdf_page or (start_p + 15)

            # Query ActivityNodes matching either page range or curriculum_node_id
            stmt_nodes = (
                select(ActivityNode)
                .where(
                    ActivityNode.subject_version_id == subject_version_id,
                    ActivityNode.page_number >= start_p,
                    ActivityNode.page_number <= end_p,
                )
                .order_by(ActivityNode.page_number, ActivityNode.ordinal)
            )
            res_nodes = await session.execute(stmt_nodes)
            act_nodes = res_nodes.scalars().all()

            if not act_nodes:
                continue

            # Check if this node has sub-sections to create distinct windows
            child_sections = [
                n for n in (version.curriculum_nodes or [])
                if n.parent_id == node.id and n.node_type in ["section", "lesson", "exercise", "activity", "topic"]
            ]

            if child_sections and len(act_nodes) > 10:
                # Partition by child sections
                for csec in sorted(child_sections, key=lambda x: x.ordinal):
                    c_start = csec.start_pdf_page
                    c_end = csec.end_pdf_page or c_start
                    c_acts = [a for a in act_nodes if c_start <= a.page_number <= c_end]
                    if not c_acts:
                        continue

                    win = cls._build_window_from_nodes(
                        act_nodes=c_acts,
                        scope_label=f"{node.source_label or ''} > {csec.source_label or ''}: {csec.title}",
                        start_chunk_idx=global_chunk_idx,
                    )
                    if win and win.chunks:
                        source_windows.append(win)
                        global_chunk_idx += len(win.chunks)
            else:
                # Single or naturally bounded window
                # If very large (> 20 activity nodes), chunk into bounded batches
                batch_size = 12
                for i in range(0, len(act_nodes), batch_size):
                    batch_acts = act_nodes[i : i + batch_size]
                    sub_label = f"Part {i//batch_size + 1}" if len(act_nodes) > batch_size else ""
                    lbl = f"{node.source_label}: {node.title}" + (f" ({sub_label})" if sub_label else "")

                    win = cls._build_window_from_nodes(
                        act_nodes=batch_acts,
                        scope_label=lbl,
                        start_chunk_idx=global_chunk_idx,
                    )
                    if win and win.chunks:
                        source_windows.append(win)
                        global_chunk_idx += len(win.chunks)

        if not source_windows:
            raise ValueError(f"EMPTY_CURRICULUM_SCOPE: No textbook content found for selected scopes ({combined_desc}).")

        # 5. Allocate requested question counts across source windows
        cls._allocate_question_counts(source_windows, requested_count)

        total_chunks = sum(len(w.chunks) for w in source_windows)
        total_tokens = sum(w.estimated_tokens for w in source_windows)

        return ResolvedCoveragePlan(
            subject_version_id=version.id,
            subject_title=version.title,
            grade_name=grade_name,
            subject_name=subject_name,
            subject_code=subject_code,
            combined_scope_description=combined_desc,
            normalized_scope_node_ids=normalized_ids,
            source_windows=source_windows,
            total_chunks=total_chunks,
            total_estimated_tokens=total_tokens,
        )

    @classmethod
    def _build_window_from_nodes(
        cls,
        act_nodes: List[ActivityNode],
        scope_label: str,
        start_chunk_idx: int,
    ) -> Optional[SourceWindow]:
        chunks: List[SourceChunk] = []
        valid_ids: Set[str] = set()
        c_idx = start_chunk_idx

        formatted_blocks: List[str] = []
        accumulated_chars = 0
        max_window_chars = 2200  # ~550 tokens

        for node in act_nodes:
            content = (node.content_text or "").strip()
            if not content:
                continue
            if len(content) < 10 and node.node_type in ["header", "footer", "page_number"]:
                continue

            if accumulated_chars + len(content) > max_window_chars and len(chunks) >= 3:
                break

            cid = f"SRC-{c_idx:03d}"
            chunk = SourceChunk(
                chunk_id=cid,
                page_number=node.page_number,
                title=node.title,
                content=content,
                scope_label=scope_label,
                activity_node_id=node.id,
                curriculum_node_id=node.curriculum_node_id,
            )
            chunks.append(chunk)
            valid_ids.add(cid)
            accumulated_chars += len(content)

            title_attr = f' title="{node.title}"' if node.title else ""
            block = (
                f'<SOURCE id="{cid}" page="{node.page_number}" scope="{scope_label}"{title_attr}>\n'
                f"{content}\n"
                f"</SOURCE>"
            )
            formatted_blocks.append(block)
            c_idx += 1

        if not chunks:
            return None

        formatted_xml = "\n\n".join(formatted_blocks)
        token_est = TokenEstimator.estimate_text_tokens(formatted_xml).estimated_tokens

        return SourceWindow(
            window_id=f"win_{chunks[0].chunk_id}_{chunks[-1].chunk_id}",
            scope_label=scope_label,
            chunks=chunks,
            formatted_xml=formatted_xml,
            valid_chunk_ids=valid_ids,
            estimated_tokens=token_est,
            target_question_count=1,
        )

    @classmethod
    def _allocate_question_counts(
        cls,
        windows: List[SourceWindow],
        total_requested: int,
    ) -> None:
        """
        Distributes question target count across windows proportionally with fair representation.
        """
        num_windows = len(windows)
        if num_windows == 0:
            return

        if total_requested <= num_windows:
            # 1 question per window for first N windows
            for i, w in enumerate(windows):
                w.target_question_count = 1 if i < total_requested else 0
            return

        # Distribute base allocation
        base_per_window = total_requested // num_windows
        remainder = total_requested % num_windows

        for i, w in enumerate(windows):
            w.target_question_count = base_per_window + (1 if i < remainder else 0)
