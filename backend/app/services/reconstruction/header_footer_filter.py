import logging
import re
from collections import defaultdict
from typing import Dict, List, Set, Tuple
import pymupdf
from app.services.reconstruction.config import ReconstructionRules

logger = logging.getLogger("nctb.reconstruction.header_footer")


class HeaderFooterFilter:
    """
    Detects and filters out repeated running headers and footers across textbook pages.
    Caches detected pattern sets in-memory keyed by version_id.
    """

    def __init__(self, rules: ReconstructionRules):
        self.rules = rules
        # In-memory cache: version_id -> Set of normalized header/footer string patterns
        self._cache: Dict[str, Set[str]] = {}

    @staticmethod
    def _normalize_text(text: str) -> str:
        # Normalize whitespace and strip leading/trailing digits to catch '4 Mathematics' and '6 Mathematics'
        t = re.sub(r"\s+", " ", text).strip().lower()
        # Strip solitary numbers from start or end
        t = re.sub(r"^\d+\s*", "", t)
        t = re.sub(r"\s*\d+$", "", t)
        return t.strip()

    @staticmethod
    def is_standalone_page_number(text: str) -> bool:
        stripped = text.strip()
        if re.match(r"^\d+$", stripped):
            return True
        if re.match(r"^page\s+\d+$", stripped, re.IGNORECASE):
            return True
        if re.match(r"^\d+\s*[-/]\s*\d+$", stripped):
            return True
        return False

    def build_version_patterns(self, version_id: str, doc: pymupdf.Document) -> Set[str]:
        """
        Samples up to sample_pages_max pages once for the textbook version and computes repeated header/footer text.
        """
        if version_id in self._cache:
            return self._cache[version_id]

        total_pages = doc.page_count
        if total_pages == 0:
            self._cache[version_id] = set()
            return self._cache[version_id]

        max_samples = min(self.rules.layout.header_footer_sample_pages_max, total_pages)
        # Sample evenly across the book
        step = max(1, total_pages // max_samples)
        sample_indices = [i for i in range(0, total_pages, step)][:max_samples]

        header_counts: Dict[str, int] = defaultdict(int)
        footer_counts: Dict[str, int] = defaultdict(int)

        for p_idx in sample_indices:
            page = doc[p_idx]
            h = float(page.rect.height)
            top_bound = h * self.rules.layout.header_zone_ratio
            bottom_bound = h * (1.0 - self.rules.layout.footer_zone_ratio)

            blocks = page.get_text("blocks")
            seen_on_page: Set[str] = set()

            for b in blocks:
                b_y0 = float(b[1])
                b_y1 = float(b[3])
                b_text = str(b[4]).strip()
                if not b_text:
                    continue

                norm = self._normalize_text(b_text)
                if not norm or norm in seen_on_page:
                    continue

                if b_y1 <= top_bound:
                    header_counts[norm] += 1
                    seen_on_page.add(norm)
                elif b_y0 >= bottom_bound:
                    footer_counts[norm] += 1
                    seen_on_page.add(norm)

        repeated_patterns: Set[str] = set()
        min_occ = self.rules.layout.header_footer_min_page_occurrences

        for text, count in header_counts.items():
            if count >= min_occ and len(text) >= 3:
                repeated_patterns.add(text)

        for text, count in footer_counts.items():
            if count >= min_occ and len(text) >= 3:
                repeated_patterns.add(text)

        self._cache[version_id] = repeated_patterns
        return repeated_patterns

    def is_header_or_footer(
        self,
        text: str,
        y0: float,
        y1: float,
        page_height: float,
        version_patterns: Set[str],
    ) -> bool:
        """
        Determines whether a line or block is a running header or footer.
        """
        stripped = text.strip()
        if not stripped:
            return False

        top_bound = page_height * self.rules.layout.header_zone_ratio
        bottom_bound = page_height * (1.0 - self.rules.layout.footer_zone_ratio)

        # 1. Standalone page numbers in header or footer zones
        if (y1 <= top_bound or y0 >= bottom_bound) and self.is_standalone_page_number(stripped):
            return True

        # 2. Repeated string match in header or footer zones
        if y1 <= top_bound or y0 >= bottom_bound:
            norm = self._normalize_text(stripped)
            if norm in version_patterns:
                return True

        return False
