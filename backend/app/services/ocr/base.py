from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel


class OCRWord(BaseModel):
    """Represents a recognized word with normalized PDF-space bounding coordinates."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: Optional[float] = None  # Nullable when not provided by OCR engine


class OCRExtractionResult(BaseModel):
    """Result of page-level OCR processing."""
    text: str
    words: List[OCRWord]
    confidence: Optional[float] = None  # Nullable when not provided by OCR engine
    provider_name: str
    is_successful: bool
    error_message: Optional[str] = None


class OCRProvider(ABC):
    """Abstract interface for pluggable page-level OCR providers."""

    @abstractmethod
    async def extract_page(
        self,
        image_bytes: bytes,
        target_width_pt: float,
        target_height_pt: float,
    ) -> OCRExtractionResult:
        """
        Extract text and word bounding boxes from rendered page image.
        Bounding boxes must be normalized back to the PDF page point space
        (target_width_pt x target_height_pt).
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Verify whether the OCR provider runtime is functional on the current system."""
        pass
