import logging
import re
from typing import Dict, List, Optional, Tuple
from app.schemas.readable import TableCell, TableRow
from app.services.reconstruction.config import ReconstructionRules
from app.services.reconstruction.layout_extractor import LayoutLine, VectorDrawing

logger = logging.getLogger("nctb.reconstruction.table_detector")


class TableDetector:
    """
    Detects and reconstructs tabular data using geometric evidence (column alignment clusters and vector ruling lines).
    Does NOT rely on textbook-specific text keywords.
    """

    def __init__(self, rules: ReconstructionRules):
        self.rules = rules

    def detect_table_block(
        self,
        lines: List[LayoutLine],
        drawings: List[VectorDrawing],
    ) -> Optional[Tuple[List[TableRow], List[LayoutLine], List[LayoutLine]]]:
        """
        Attempts to detect a table within a sequence of lines.
        Returns:
            (rows, consumed_lines, remaining_lines) if a high-confidence table is found,
            else None.
        """
        min_rows = self.rules.layout.table_min_rows
        min_cols = self.rules.layout.table_min_cols
        col_tol = self.rules.layout.table_column_alignment_tolerance_pt

        if len(lines) < min_rows:
            return None

        # Check for vector ruling lines in the region
        has_table_drawings = False
        if drawings:
            # Check if there are multiple horizontal ruling lines overlapping the lines' vertical extent
            y_start = lines[0].y0
            y_end = lines[-1].y1
            h_lines = [d for d in drawings if d.is_horizontal_line and y_start - 5 <= d.rect[1] <= y_end + 5]
            if len(h_lines) >= 2:
                has_table_drawings = True

        # Analyze token x-positions across lines to detect stable column clusters
        # Split line into space-separated or span-separated tokens with their bounding boxes
        candidate_rows: List[List[str]] = []
        consumed_lines: List[LayoutLine] = []

        for line in lines:
            # If line contains spans with distinct x-positions, extract cells from spans
            if len(line.spans) >= min_cols:
                cells = [s.text.strip() for s in line.spans if s.text.strip()]
            else:
                # Split text by multiple spaces or tabs
                raw_parts = re.split(r"\s{2,}|\t+", line.text.strip())
                cells = [p.strip() for p in raw_parts if p.strip()]

            if len(cells) >= min_cols:
                candidate_rows.append(cells)
                consumed_lines.append(line)
            else:
                # If we already have accumulated enough rows, break and check
                if len(candidate_rows) >= min_rows:
                    break
                else:
                    # Reset candidate rows
                    candidate_rows = []
                    consumed_lines = []

        if len(candidate_rows) < min_rows:
            return None

        # Validate column count consistency across candidate rows
        # Mode column count:
        col_counts = [len(r) for r in candidate_rows]
        mode_cols = max(set(col_counts), key=col_counts.count)

        if mode_cols < min_cols:
            return None

        # Filter to rows matching mode_cols or close
        valid_rows: List[List[str]] = []
        final_consumed: List[LayoutLine] = []

        for r, l in zip(candidate_rows, consumed_lines):
            if len(r) == mode_cols:
                valid_rows.append(r)
                final_consumed.append(l)

        if len(valid_rows) < min_rows and not has_table_drawings:
            # Insufficient confidence
            return None

        # Construct TableRow list
        table_rows: List[TableRow] = []
        for row_idx, row_cells in enumerate(valid_rows):
            is_header_row = (row_idx == 0)
            cell_objs = [
                TableCell(
                    text=cell_text,
                    is_header=is_header_row,
                    raw_text=cell_text,
                )
                for cell_text in row_cells
            ]
            table_rows.append(TableRow(cells=cell_objs))

        # Remaining lines after the consumed table lines
        last_consumed_idx = lines.index(final_consumed[-1])
        remaining_lines = lines[last_consumed_idx + 1 :]

        return table_rows, final_consumed, remaining_lines
