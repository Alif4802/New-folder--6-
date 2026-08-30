import re
from typing import List, Optional, Tuple
from app.schemas.readable import TextSpan
from app.services.reconstruction.config import ReconstructionRules
from app.services.reconstruction.layout_extractor import LayoutLine, LayoutSpan


class MathNormalizer:
    """
    Normalizes mathematical expressions and spans using geometric evidence and conservative formatting rules.
    Guarantees that prose is never rewritten into equations and raw_text is always preserved.
    """

    def __init__(self, rules: ReconstructionRules):
        self.rules = rules

    def normalize_line_spans(self, line: LayoutLine, body_font_size: float) -> List[TextSpan]:
        """
        Converts layout spans in a line into a list of TextSpan objects,
        applying geometry-based superscript/subscript reconstruction where supported.
        """
        if not line.spans:
            return [TextSpan(text=line.text, raw_text=line.text)]

        # If line has only 1 span, check if it contains existing math symbols or equations
        if len(line.spans) == 1:
            span = line.spans[0]
            return self._parse_inline_text_to_spans(span.text, span.is_bold, span.is_italic)

        result_spans: List[TextSpan] = []
        i = 0
        n = len(line.spans)

        while i < n:
            curr_span = line.spans[i]
            prev_span = line.spans[i - 1] if i > 0 else None
            next_span = line.spans[i + 1] if i + 1 < n else None

            is_superscript = False
            is_subscript = False

            if prev_span:
                # 1. Superscript Check via PDF Geometry
                # Requirements:
                # - Font size is noticeably smaller than base
                # - Baseline is vertically elevated (origin_y is lower numerical value in PDF points)
                # - Horizontal gap is small
                h_gap = curr_span.x0 - prev_span.x1
                size_ratio = curr_span.size / max(1.0, prev_span.size)
                y_elevation = prev_span.origin_y - curr_span.origin_y
                elevation_ratio = y_elevation / max(1.0, prev_span.size)

                # Check if previous span ended with a variable, digit, or closing parenthesis
                prev_ends_valid = bool(re.search(r"[a-zA-Z0-9\)\}\]]$", prev_span.text.strip()))
                curr_is_exponent = bool(re.match(r"^[0-9a-zA-Z\+\-]+$", curr_span.text.strip()))

                if (
                    prev_ends_valid
                    and curr_is_exponent
                    and size_ratio <= self.rules.layout.superscript_max_font_size_ratio
                    and elevation_ratio >= self.rules.layout.superscript_min_baseline_offset_ratio
                    and h_gap <= self.rules.layout.horizontal_char_gap_tolerance_pt
                ):
                    is_superscript = True

                # 2. Subscript Check via PDF Geometry
                y_depression = curr_span.origin_y - prev_span.origin_y
                depression_ratio = y_depression / max(1.0, prev_span.size)

                if (
                    prev_ends_valid
                    and curr_is_exponent
                    and size_ratio <= self.rules.layout.superscript_max_font_size_ratio
                    and depression_ratio >= self.rules.layout.subscript_min_baseline_offset_ratio
                    and h_gap <= self.rules.layout.horizontal_char_gap_tolerance_pt
                ):
                    is_subscript = True

            if is_superscript and result_spans:
                # Merge into previous span as superscript LaTeX
                prev_text_span = result_spans[-1]
                base_text = prev_text_span.raw_text or prev_text_span.text
                exp_text = curr_span.text.strip()
                combined_raw = base_text + exp_text
                latex_expr = f"{base_text}^{{{exp_text}}}"

                result_spans[-1] = TextSpan(
                    text=f"{base_text}^{exp_text}",
                    is_bold=prev_text_span.is_bold,
                    is_italic=prev_text_span.is_italic,
                    is_math=True,
                    latex=latex_expr,
                    raw_text=combined_raw,
                    is_uncertain=False,
                )
                i += 1
                continue

            if is_subscript and result_spans:
                # Merge into previous span as subscript LaTeX
                prev_text_span = result_spans[-1]
                base_text = prev_text_span.raw_text or prev_text_span.text
                sub_text = curr_span.text.strip()
                combined_raw = base_text + sub_text
                latex_expr = f"{base_text}_{{{sub_text}}}"

                result_spans[-1] = TextSpan(
                    text=f"{base_text}_{sub_text}",
                    is_bold=prev_text_span.is_bold,
                    is_italic=prev_text_span.is_italic,
                    is_math=True,
                    latex=latex_expr,
                    raw_text=combined_raw,
                    is_uncertain=False,
                )
                i += 1
                continue

            # Standard span processing
            parsed_spans = self._parse_inline_text_to_spans(curr_span.text, curr_span.is_bold, curr_span.is_italic)
            result_spans.extend(parsed_spans)
            i += 1

        return result_spans

    def _parse_inline_text_to_spans(self, text: str, is_bold: bool, is_italic: bool) -> List[TextSpan]:
        """
        Parses text into text spans. Preserves prose words strictly.
        Only formats explicit mathematical formulas or radical symbols already present in text.
        """
        # Look for explicit math symbols or equations: e.g. "√25 = 5" or "5 x 5 = 25" or "807 x 807 = 651249"
        # We do NOT turn "The square root of 25 is 5." into LaTeX!
        if not text:
            return []

        # Check if text contains radical symbol √ or \u221a
        if "√" in text or "\u221a" in text:
            # Format root symbol into LaTeX while preserving original text
            raw = text
            latex = text.replace("√", r"\sqrt{").replace("\u221a", r"\sqrt{")
            # If root was followed by numbers, e.g. √25 -> \sqrt{25}
            latex = re.sub(r"\\sqrt\{(\d+)", r"\\sqrt{\1}", latex)
            return [
                TextSpan(
                    text=text,
                    is_bold=is_bold,
                    is_italic=is_italic,
                    is_math=True,
                    latex=latex,
                    raw_text=raw,
                    is_uncertain=False,
                )
            ]

        # Check for arithmetic equality equation, e.g. "5 x 5 = 25" or "2 + 3 = 5"
        equation_match = re.match(r"^([a-zA-Z0-9\(\)\^\s\+\-\*\/\×\÷\.\,\:]+\s*=\s*[a-zA-Z0-9\(\)\^\s\+\-\*\/\×\÷\.\,]+)$", text.strip())
        if equation_match and any(op in text for op in ["=", "+", "-", "×", "*", "/", "÷"]):
            raw = text.strip()
            # Convert x or × to \times in multiplication equations if appropriate
            latex = raw.replace("×", r" \times ").replace("÷", r" \div ")
            return [
                TextSpan(
                    text=raw,
                    is_bold=is_bold,
                    is_italic=is_italic,
                    is_math=True,
                    latex=latex,
                    raw_text=raw,
                    is_uncertain=False,
                )
            ]

        # Default plain text span (zero semantic invention)
        return [
            TextSpan(
                text=text,
                is_bold=is_bold,
                is_italic=is_italic,
                is_math=False,
                latex=None,
                raw_text=text,
                is_uncertain=False,
            )
        ]
