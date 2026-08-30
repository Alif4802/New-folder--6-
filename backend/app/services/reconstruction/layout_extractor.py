import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pymupdf
from app.services.reconstruction.config import ReconstructionRules

logger = logging.getLogger("nctb.reconstruction.layout_extractor")


@dataclass
class LayoutSpan:
    text: str
    size: float
    font: str
    flags: int
    x0: float
    y0: float
    x1: float
    y1: float
    origin_x: float
    origin_y: float

    @property
    def is_bold(self) -> bool:
        # PyMuPDF font flags: bit 4 (value 16) is bold, or font name contains bold/black
        return bool(self.flags & 16) or ("bold" in self.font.lower()) or ("black" in self.font.lower())

    @property
    def is_italic(self) -> bool:
        # bit 1 (value 2) is italic
        return bool(self.flags & 2) or ("italic" in self.font.lower()) or ("oblique" in self.font.lower())

    @property
    def bbox_dict(self) -> Dict[str, float]:
        return {
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
        }


@dataclass
class LayoutLine:
    spans: List[LayoutSpan]
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    baseline_y: float
    page_number: int
    median_font_size: float

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def bbox_dict(self) -> Dict[str, float]:
        return {
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
        }


@dataclass
class VectorDrawing:
    rect: Tuple[float, float, float, float]
    is_horizontal_line: bool
    is_vertical_line: bool


@dataclass
class PageLayout:
    page_number: int
    width: float
    height: float
    lines: List[LayoutLine] = field(default_factory=list)
    drawings: List[VectorDrawing] = field(default_factory=list)
    median_body_font_size: float = 11.0


class LayoutExtractor:
    """
    Extracts high-fidelity span, line, baseline, and vector drawing metadata from PDF pages.
    """

    def __init__(self, rules: ReconstructionRules):
        self.rules = rules

    def extract_page_layout(self, page: pymupdf.Page, page_number: int) -> PageLayout:
        p_width = float(page.rect.width)
        p_height = float(page.rect.height)

        text_dict = page.get_text("dict")
        lines: List[LayoutLine] = []
        all_font_sizes: List[float] = []

        # 1. Parse text blocks, lines, and spans
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue

            for b_line in block["lines"]:
                spans: List[LayoutSpan] = []
                for s in b_line.get("spans", []):
                    s_text = s.get("text", "")
                    if not s_text:
                        continue

                    s_sz = float(s.get("size", 11.0))
                    all_font_sizes.append(s_sz)

                    origin = s.get("origin", (s["bbox"][0], s["bbox"][3]))
                    span_obj = LayoutSpan(
                        text=s_text,
                        size=s_sz,
                        font=s.get("font", ""),
                        flags=int(s.get("flags", 0)),
                        x0=float(s["bbox"][0]),
                        y0=float(s["bbox"][1]),
                        x1=float(s["bbox"][2]),
                        y1=float(s["bbox"][3]),
                        origin_x=float(origin[0]),
                        origin_y=float(origin[1]),
                    )
                    spans.append(span_obj)

                if not spans:
                    continue

                line_text = "".join(s.text for s in spans).strip()
                if not line_text:
                    continue

                lx0 = min(s.x0 for s in spans)
                ly0 = min(s.y0 for s in spans)
                lx1 = max(s.x1 for s in spans)
                ly1 = max(s.y1 for s in spans)
                avg_baseline = sum(s.origin_y for s in spans) / len(spans)
                line_font_sizes = [s.size for s in spans]
                med_sz = sorted(line_font_sizes)[len(line_font_sizes) // 2] if line_font_sizes else 11.0

                lines.append(
                    LayoutLine(
                        spans=spans,
                        text=line_text,
                        x0=round(lx0, 2),
                        y0=round(ly0, 2),
                        x1=round(lx1, 2),
                        y1=round(ly1, 2),
                        baseline_y=round(avg_baseline, 2),
                        page_number=page_number,
                        median_font_size=med_sz,
                    )
                )

        # Sort lines strictly top to bottom
        lines.sort(key=lambda l: (l.y0, l.x0))

        # Calculate median body font size of the page
        if all_font_sizes:
            sorted_sizes = sorted(all_font_sizes)
            page_body_size = sorted_sizes[len(sorted_sizes) // 2]
        else:
            page_body_size = 11.0

        # 2. Extract vector drawing lines
        drawings: List[VectorDrawing] = []
        try:
            raw_drawings = page.get_drawings()
            for d in raw_drawings:
                rect = d.get("rect")
                if not rect:
                    continue
                r_w = rect.width
                r_h = rect.height
                # A horizontal line has small height (< 3 pt) and substantial width (> 20 pt)
                is_h_line = r_h <= 3.0 and r_w >= 20.0
                # A vertical line has small width (< 3 pt) and substantial height (> 20 pt)
                is_v_line = r_w <= 3.0 and r_h >= 20.0

                if is_h_line or is_v_line:
                    drawings.append(
                        VectorDrawing(
                            rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                            is_horizontal_line=is_h_line,
                            is_vertical_line=is_v_line,
                        )
                    )
        except Exception as exc:
            logger.debug(f"Drawings extraction skipped on page {page_number}: {exc}")

        return PageLayout(
            page_number=page_number,
            width=p_width,
            height=p_height,
            lines=lines,
            drawings=drawings,
            median_body_font_size=page_body_size,
        )
