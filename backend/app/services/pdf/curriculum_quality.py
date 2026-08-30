import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from app.models.textbook import CurriculumNode

logger = logging.getLogger("nctb.curriculum.quality")


@dataclass
class CurriculumQualityResult:
    is_valid: bool
    status: str  # "VALID" | "NEEDS_REFRESH"
    reasons: List[str]
    metrics: dict


class CurriculumQualityGate:
    """
    Config-driven generic structural quality gate for textbook CurriculumNode trees.
    Zero hardcoded textbook IDs or titles.
    """

    MAX_DUPLICATE_TITLE_RATIO: float = 0.25
    MAX_ROOT_DENSITY: float = 0.40
    MAX_PAGE_SUFFIX_RATIO: float = 0.30

    @classmethod
    def evaluate_tree(
        cls,
        nodes: List[CurriculumNode],
        page_count: int,
    ) -> CurriculumQualityResult:
        reasons: List[str] = []
        metrics: dict = {}

        if not nodes:
            return CurriculumQualityResult(
                is_valid=False,
                status="NEEDS_REFRESH",
                reasons=["EMPTY_CURRICULUM_TREE: No curriculum nodes found."],
                metrics={"node_count": 0},
            )

        roots = [n for n in nodes if n.parent_id is None]
        total_nodes = len(nodes)
        p_count = max(page_count, 1)

        # 1. Duplicate normalized title ratio on root nodes
        root_titles = [re.sub(r"\s+", " ", n.title.strip().lower()) for n in roots if n.title]
        unique_roots = set(root_titles)
        dup_ratio = 1.0 - (len(unique_roots) / len(root_titles)) if root_titles else 0.0
        metrics["duplicate_title_ratio"] = round(dup_ratio, 3)

        if dup_ratio > cls.MAX_DUPLICATE_TITLE_RATIO:
            reasons.append(
                f"EXCESSIVE_DUPLICATE_TITLES: {dup_ratio:.1%} of root titles are duplicates (limit {cls.MAX_DUPLICATE_TITLE_RATIO:.1%})."
            )

        # 2. Root density relative to page count
        root_density = len(roots) / p_count
        metrics["root_density"] = round(root_density, 3)

        if root_density > cls.MAX_ROOT_DENSITY and len(roots) > 15:
            reasons.append(
                f"ABNORMAL_ROOT_DENSITY: Root density is {root_density:.2f} nodes/page ({len(roots)} roots for {p_count} pages, limit {cls.MAX_ROOT_DENSITY:.2f})."
            )

        # 3. Page suffix signal
        page_suffix_count = sum(1 for n in nodes if re.search(r"\b[A-Za-z\s]+\s+\d{1,4}$", (n.title or "").strip()))
        suffix_ratio = page_suffix_count / total_nodes if total_nodes > 0 else 0.0
        metrics["page_suffix_ratio"] = round(suffix_ratio, 3)

        if suffix_ratio > cls.MAX_PAGE_SUFFIX_RATIO:
            reasons.append(
                f"PAGE_NUMBER_TITLE_FRAGMENTS: {suffix_ratio:.1%} of node titles end in stray page numbers."
            )

        # 4. Page range sanity
        invalid_ranges = [
            n.id for n in nodes
            if (n.start_pdf_page is not None and n.end_pdf_page is not None and n.start_pdf_page > n.end_pdf_page)
        ]
        if invalid_ranges:
            reasons.append(f"INVALID_PAGE_RANGES: {len(invalid_ranges)} nodes have start_page > end_page.")

        # 5. Empty titles
        empty_titles = [n.id for n in nodes if not (n.title or "").strip()]
        if empty_titles:
            reasons.append(f"EMPTY_NODE_TITLES: {len(empty_titles)} nodes have empty or whitespace titles.")

        is_valid = len(reasons) == 0
        status = "VALID" if is_valid else "NEEDS_REFRESH"

        return CurriculumQualityResult(
            is_valid=is_valid,
            status=status,
            reasons=reasons,
            metrics=metrics,
        )
