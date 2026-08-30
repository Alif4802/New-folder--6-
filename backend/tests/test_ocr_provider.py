import pytest
from unittest.mock import AsyncMock, patch
from app.services.ocr.base import OCRProvider, OCRExtractionResult, OCRWord
from app.services.ocr.winocr_provider import WinOCRProvider
from app.services.pdf.extractor import PageExtractor
import pymupdf


class MockOCRProvider(OCRProvider):
    def __init__(self, available: bool = True, return_success: bool = True):
        self._available = available
        self._return_success = return_success

    def is_available(self) -> bool:
        return self._available

    async def extract_page(
        self, image_bytes: bytes, target_width_pt: float, target_height_pt: float
    ) -> OCRExtractionResult:
        if not self._return_success:
            return OCRExtractionResult(
                text="",
                words=[],
                confidence=None,
                provider_name="MockOCR",
                is_successful=False,
                error_message="Mock OCR error",
            )
        return OCRExtractionResult(
            text="Unit 1 Lesson 1 Mock OCR Text",
            words=[
                OCRWord(text="Unit", x0=10, y0=20, x1=50, y1=40, confidence=None),
                OCRWord(text="1", x0=60, y0=20, x1=80, y1=40, confidence=None),
                OCRWord(text="Lesson", x0=10, y0=50, x1=60, y1=70, confidence=None),
                OCRWord(text="1", x0=70, y0=50, x1=90, y1=70, confidence=None),
            ],
            confidence=None,
            provider_name="MockOCR",
            is_successful=True,
        )


@pytest.mark.asyncio
async def test_native_quality_skips_ocr():
    # Document with clear native text
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Unit 1: English for Today. This is a high quality native text page.", fontsize=14)

    mock_ocr = MockOCRProvider()
    mock_ocr.extract_page = AsyncMock()

    extractor = PageExtractor(ocr_provider=mock_ocr)
    result = await extractor.extract_page(doc, 0)
    doc.close()

    assert not result.ocr_used
    assert len(result.words) > 0
    # OCR should not have been called because native text is good
    mock_ocr.extract_page.assert_not_called()


@pytest.mark.asyncio
async def test_scanned_page_triggers_ocr():
    # Blank/Scanned page without native text
    doc = pymupdf.open()
    page = doc.new_page()
    # Draw a rectangle so page is not completely blank
    page.draw_rect(pymupdf.Rect(50, 50, 200, 200), color=(0, 0, 0))

    mock_ocr = MockOCRProvider(available=True, return_success=True)
    extractor = PageExtractor(ocr_provider=mock_ocr)
    result = await extractor.extract_page(doc, 0)
    doc.close()

    assert result.ocr_used
    assert len(result.words) == 4
    assert result.words[0].confidence is None  # Check nullable confidence


@pytest.mark.asyncio
async def test_ocr_unavailable_records_truthful_warning():
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 200, 200), color=(0, 0, 0))

    mock_ocr = MockOCRProvider(available=False)
    extractor = PageExtractor(ocr_provider=mock_ocr)
    result = await extractor.extract_page(doc, 0)
    doc.close()

    assert not result.ocr_used
    assert result.warning is not None
    assert "OCR_REQUIRED_BUT_UNAVAILABLE" in result.warning
