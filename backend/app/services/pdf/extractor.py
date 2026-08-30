import logging
from dataclasses import dataclass
from typing import List, Optional
import pymupdf
from app.services.ocr.base import OCRProvider
from app.services.pdf.reading_order import (
    WordBox,
    TextLine,
    TextBlock,
    cluster_words_into_lines,
    group_lines_into_blocks,
)

logger = logging.getLogger("nctb.pdf.extractor")


@dataclass
class PageExtractionResult:
    """Extraction output for a single PDF page."""
    page_number: int
    words: List[WordBox]
    lines: List[TextLine]
    blocks: List[TextBlock]
    ocr_used: bool
    warning: Optional[str] = None
    width_pt: float = 0.0
    height_pt: float = 0.0


class PageExtractor:
    """
    Handles native PyMuPDF extraction, evaluates text quality,
    and executes WinOCR fallback when native text is insufficient or corrupted.
    """

    def __init__(self, ocr_provider: Optional[OCRProvider] = None):
        self.ocr_provider = ocr_provider

    def _evaluate_text_quality(self, text: str, word_count: int) -> bool:
        """
        Heuristic: determine if extracted native text is clean and substantial.
        """
        stripped = text.strip()
        char_count = len(stripped)
        if char_count < 40 or word_count < 8:
            return False

        alpha_count = sum(1 for c in stripped if c.isalpha())
        alpha_ratio = alpha_count / float(max(1, char_count))

        # Check for corrupted encoding or heavy non-alphabetic noise
        if alpha_ratio < 0.50:
            return False

        return True

    async def extract_page(
        self,
        doc: pymupdf.Document,
        page_idx: int,
    ) -> PageExtractionResult:
        """
        Extract page words and lines using native text or OCR fallback.
        """
        page = doc[page_idx]
        page_number = page_idx + 1
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)

        # 1. Native PyMuPDF word extraction
        # page.get_text("words") returns tuples: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
        raw_words = page.get_text("words")
        native_word_boxes: List[WordBox] = []
        for w in raw_words:
            w_text = str(w[4]).strip()
            if w_text:
                native_word_boxes.append(
                    WordBox(
                        text=w_text,
                        x0=round(float(w[0]), 2),
                        y0=round(float(w[1]), 2),
                        x1=round(float(w[2]), 2),
                        y1=round(float(w[3]), 2),
                    )
                )

        native_text = page.get_text().strip()
        is_native_good = self._evaluate_text_quality(native_text, len(native_word_boxes))

        # If native text is clean and sufficient, reconstruct reading order and return
        if is_native_good:
            lines = cluster_words_into_lines(native_word_boxes)
            blocks = group_lines_into_blocks(lines, page_number)
            return PageExtractionResult(
                page_number=page_number,
                words=native_word_boxes,
                lines=lines,
                blocks=blocks,
                ocr_used=False,
                warning=None,
                width_pt=page_width,
                height_pt=page_height,
            )

        # 2. Native text is insufficient; check if OCR can be executed
        # Check if page has visual content (images / drawings) or is non-blank
        has_drawings = len(page.get_drawings()) > 0
        has_images = len(page.get_images()) > 0
        is_likely_scanned = has_images or has_drawings or len(native_word_boxes) == 0

        if not is_likely_scanned and len(native_word_boxes) > 0:
            # Short text page (e.g. blank page or minimal copyright note) that is not scanned
            lines = cluster_words_into_lines(native_word_boxes)
            blocks = group_lines_into_blocks(lines, page_number)
            return PageExtractionResult(
                page_number=page_number,
                words=native_word_boxes,
                lines=lines,
                blocks=blocks,
                ocr_used=False,
                warning=None,
                width_pt=page_width,
                height_pt=page_height,
            )

        # 3. Trigger OCR Fallback
        if self.ocr_provider and self.ocr_provider.is_available():
            try:
                # Render page pixmap at 200 DPI
                pix = page.get_pixmap(dpi=200)
                png_bytes = pix.tobytes("png")

                ocr_result = await self.ocr_provider.extract_page(
                    image_bytes=png_bytes,
                    target_width_pt=page_width,
                    target_height_pt=page_height,
                )

                if ocr_result.is_successful and ocr_result.words:
                    ocr_word_boxes = [
                        WordBox(
                            text=w.text,
                            x0=w.x0,
                            y0=w.y0,
                            x1=w.x1,
                            y1=w.y1,
                            confidence=w.confidence,
                        )
                        for w in ocr_result.words
                    ]
                    lines = cluster_words_into_lines(ocr_word_boxes)
                    blocks = group_lines_into_blocks(lines, page_number)
                    return PageExtractionResult(
                        page_number=page_number,
                        words=ocr_word_boxes,
                        lines=lines,
                        blocks=blocks,
                        ocr_used=True,
                        warning=None,
                        width_pt=page_width,
                        height_pt=page_height,
                    )
                else:
                    warning_msg = f"OCR was executed on Page {page_number} but returned no text."
                    logger.warning(warning_msg)
            except Exception as exc:
                warning_msg = f"OCR failed on Page {page_number}: {exc}"
                logger.error(warning_msg, exc_info=True)
        else:
            warning_msg = f"OCR_REQUIRED_BUT_UNAVAILABLE (Page {page_number}): Native text insufficient and OCR provider unavailable."
            logger.warning(warning_msg)

        # Fallback to best-effort native words with recorded warning
        lines = cluster_words_into_lines(native_word_boxes)
        blocks = group_lines_into_blocks(lines, page_number)
        return PageExtractionResult(
            page_number=page_number,
            words=native_word_boxes,
            lines=lines,
            blocks=blocks,
            ocr_used=False,
            warning=warning_msg,
            width_pt=page_width,
            height_pt=page_height,
        )
