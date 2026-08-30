import asyncio
import io
import logging
import sys
from typing import List, Optional
from PIL import Image
from app.services.ocr.base import OCRProvider, OCRExtractionResult, OCRWord

logger = logging.getLogger("nctb.ocr.winocr")


class WinOCRProvider(OCRProvider):
    """
    Windows Media OCR Provider implementation.
    Operates off the asyncio event loop via asyncio.to_thread and normalizes
    bounding boxes back into standard PDF 72 DPI point coordinate space.
    """

    def __init__(self, language: str = "en-US"):
        self.language = language
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if Windows Media OCR is available with the configured language."""
        if self._available is not None:
            return self._available

        if sys.platform != "win32":
            self._available = False
            return False

        try:
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.globalization import Language

            # Check primary language or fallback to 'en'
            is_supported = OcrEngine.is_language_supported(Language(self.language))
            if not is_supported and self.language != "en":
                is_supported = OcrEngine.is_language_supported(Language("en"))
                if is_supported:
                    self.language = "en"

            self._available = is_supported
            if is_supported:
                logger.info(f"WinOCR initialized successfully with language: {self.language}")
            else:
                logger.warning(f"WinOCR language '{self.language}' is not supported on this Windows installation.")
        except Exception as exc:
            logger.warning(f"WinOCR availability check failed: {exc}")
            self._available = False

        return self._available

    def _sync_recognize(self, img: Image.Image) -> dict:
        """Internal synchronous helper executed inside a worker thread."""
        import winocr
        return winocr.recognize_pil_sync(img, self.language)

    async def extract_page(
        self,
        image_bytes: bytes,
        target_width_pt: float,
        target_height_pt: float,
    ) -> OCRExtractionResult:
        """
        Rendered image OCR extraction. Runs off the main event loop via asyncio.to_thread
        and scales bounding boxes back to PDF page point geometry.
        """
        if not self.is_available():
            return OCRExtractionResult(
                text="",
                words=[],
                confidence=None,
                provider_name="WinOCRProvider",
                is_successful=False,
                error_message="WinOCR is not available on this host or language pack is missing.",
            )

        try:
            # Load image from bytes
            img = Image.open(io.BytesIO(image_bytes))
            img_width, img_height = img.size

            if img_width <= 0 or img_height <= 0:
                return OCRExtractionResult(
                    text="",
                    words=[],
                    confidence=None,
                    provider_name="WinOCRProvider",
                    is_successful=False,
                    error_message="Image dimensions are invalid (0x0).",
                )

            # Compute scaling factors to map image pixels to PDF point space
            scale_x = target_width_pt / float(img_width)
            scale_y = target_height_pt / float(img_height)

            # Execute WinOCR in a worker thread to keep the asyncio event loop unblocked
            raw_result = await asyncio.to_thread(self._sync_recognize, img)

            extracted_words: List[OCRWord] = []
            full_text_lines: List[str] = []

            # Parse lines and words from WinOCR structured response
            lines = raw_result.get("lines", []) if isinstance(raw_result, dict) else []
            for line in lines:
                line_text = line.get("text", "")
                if line_text:
                    full_text_lines.append(line_text)

                for word_dict in line.get("words", []):
                    w_text = word_dict.get("text", "").strip()
                    if not w_text:
                        continue

                    rect = word_dict.get("bounding_rect", {})
                    rx = float(rect.get("x", 0.0))
                    ry = float(rect.get("y", 0.0))
                    rw = float(rect.get("width", 0.0))
                    rh = float(rect.get("height", 0.0))

                    # Normalize to PDF points
                    x0 = rx * scale_x
                    y0 = ry * scale_y
                    x1 = (rx + rw) * scale_x
                    y1 = (ry + rh) * scale_y

                    extracted_words.append(
                        OCRWord(
                            text=w_text,
                            x0=round(x0, 2),
                            y0=round(y0, 2),
                            x1=round(x1, 2),
                            y1=round(y1, 2),
                            confidence=None,  # WinOCR does not report confidence scores
                        )
                    )

            full_text = "\n".join(full_text_lines) if full_text_lines else raw_result.get("text", "")

            return OCRExtractionResult(
                text=full_text,
                words=extracted_words,
                confidence=None,
                provider_name="WinOCRProvider",
                is_successful=True,
            )

        except Exception as exc:
            logger.error(f"WinOCR execution failed: {exc}", exc_info=True)
            return OCRExtractionResult(
                text="",
                words=[],
                confidence=None,
                provider_name="WinOCRProvider",
                is_successful=False,
                error_message=str(exc),
            )
