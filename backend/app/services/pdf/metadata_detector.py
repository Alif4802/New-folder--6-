from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re
import pymupdf

from app.core.config import settings
from app.services.pdf.number_parser import NumberTokenParser
from app.services.pdf.subject_profiles import SubjectDetectionProfile, subject_registry


@dataclass
class DetectedDocumentMetadata:
    """Discovered textbook metadata with full diagnostic signals and provenance."""
    title: str
    grade_code: Optional[str] = None
    grade_name: Optional[str] = None
    grade_level: Optional[int] = None
    subject_code: Optional[str] = None
    subject_name: Optional[str] = None
    domain: Optional[str] = None  # None / null when subject is unresolved
    edition_year: Optional[int] = None
    edition_label: Optional[str] = None
    publication_year: Optional[int] = None
    version_label: Optional[str] = None
    diagnostic_signals: Optional[Dict[str, Any]] = None


class DynamicMetadataDetector:
    """
    Analyzes front-matter text, docinfo metadata, and filenames using dynamic heuristics
    and the configuration-driven subject profile registry.
    """

    # Dynamic Grade patterns matching: Class 9, Grade IX, For Classes 9-10, Class Nine, etc.
    GRADE_PATTERNS = [
        r"(?i)\b(?:Class|Grade|Classes|Grades)\s*[-:]?\s*([A-Za-z0-9IVXLCDM]+(?:\s*-\s*[A-Za-z0-9IVXLCDM]+)?)\b",
        r"(?i)\bFor\s+Classes?\s+([A-Za-z0-9IVXLCDM]+)\b",
    ]

    # Dynamic Edition patterns: First Edition 2024, Revised Edition 2023, Reprint 2025, etc.
    EDITION_LABEL_PATTERNS = [
        r"(?i)\b((?:First|Second|Third|Fourth|Fifth|Revised|Special|National)\s+Edition(?:\s+\d{4})?)\b",
        r"(?i)\b(Edition\s*[:\-—]?\s*\d{4})\b",
        r"(?i)\b(Academic\s+Year\s*[:\-—]?\s*\d{4})\b",
        r"(?i)\b(Reprint\s*[:\-—]?\s*\d{4})\b",
    ]

    # Dynamic Year patterns matching: Academic Year 2024, Published in 2023, standalone 4-digit years
    YEAR_CONTEXT_PATTERNS = [
        r"(?i)\b(?:academic\s+year|edition|published\s+in|revised\s+edition|prescribed\s+for|copyright)\s*[:\-—]?\s*(?:in\s*)?(\d{4})\b",
        r"\b(19\d{2}|20\d{2}|21\d{2})\b",
    ]

    @classmethod
    def detect_grade(
        cls, text: str, filename: str = ""
    ) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str], Optional[str]]:
        """
        Detect Grade/Class prioritizing internal text over filename.
        Returns (grade_code, grade_name, grade_level, source, matched_text).
        """
        if text.strip():
            for pat in cls.GRADE_PATTERNS:
                match = re.search(pat, text)
                if match:
                    raw_grade_token = match.group(1).strip()
                    primary_token = raw_grade_token.split("-")[0].strip()
                    parsed_num = NumberTokenParser.parse_token(primary_token)
                    int_level = NumberTokenParser.to_int(primary_token)

                    if parsed_num:
                        code = f"class-{parsed_num.lower()}"
                        name = f"Class {parsed_num}"
                        return code, name, int_level, "content", match.group(0)
                    elif raw_grade_token.isalnum():
                        code = f"class-{raw_grade_token.lower()}"
                        name = f"Class {raw_grade_token}"
                        return code, name, None, "content", match.group(0)

        if filename.strip():
            for pat in cls.GRADE_PATTERNS:
                match = re.search(pat, filename)
                if match:
                    raw_grade_token = match.group(1).strip()
                    primary_token = raw_grade_token.split("-")[0].strip()
                    parsed_num = NumberTokenParser.parse_token(primary_token)
                    int_level = NumberTokenParser.to_int(primary_token)

                    if parsed_num:
                        code = f"class-{parsed_num.lower()}"
                        name = f"Class {parsed_num}"
                        return code, name, int_level, "filename", match.group(0)
                    elif raw_grade_token.isalnum():
                        code = f"class-{raw_grade_token.lower()}"
                        name = f"Class {raw_grade_token}"
                        return code, name, None, "filename", match.group(0)

        return None, None, None, None, None

    @classmethod
    def detect_edition(
        cls, text: str, filename: str = ""
    ) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[str]]:
        """
        Detect edition label and publication year separately.
        Returns (edition_label, publication_year, source, matched_text).
        """
        current_year = datetime.now().year
        detected_label: Optional[str] = None
        detected_year: Optional[int] = None
        source: Optional[str] = None
        matched_text: Optional[str] = None

        # 1. Search for explicit edition label in text
        if text.strip():
            for pat in cls.EDITION_LABEL_PATTERNS:
                match = re.search(pat, text)
                if match:
                    detected_label = match.group(1).strip()
                    source = "content"
                    matched_text = match.group(0)
                    # Extract 4-digit year if present in label
                    yr_match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", detected_label)
                    if yr_match:
                        detected_year = int(yr_match.group(1))
                    break

        # 2. Search for publication / academic year
        if text.strip() and not detected_year:
            for pat in cls.YEAR_CONTEXT_PATTERNS:
                for match in re.finditer(pat, text):
                    yr = int(match.group(1))
                    if 1971 <= yr <= current_year + 2:
                        detected_year = yr
                        if not source:
                            source = "content"
                            matched_text = match.group(0)
                        break
                if detected_year:
                    break

        # 3. Fallback to filename
        if filename.strip() and not detected_year:
            for pat in cls.YEAR_CONTEXT_PATTERNS:
                for match in re.finditer(pat, filename):
                    yr = int(match.group(1))
                    if 1971 <= yr <= current_year + 2:
                        detected_year = yr
                        source = "filename"
                        matched_text = match.group(0)
                        break

        return detected_label, detected_year, source, matched_text

    @classmethod
    def detect_metadata(
        cls,
        doc: pymupdf.Document,
        filename: str = "",
    ) -> DetectedDocumentMetadata:
        """
        Extract diagnostic metadata from configured front-matter pages and PDF docinfo.
        """
        max_inspect_pages = min(settings.METADATA_FRONT_MATTER_MAX_PAGES, doc.page_count)
        sample_pages_text: List[str] = []

        for p_idx in range(max_inspect_pages):
            page_text = doc[p_idx].get_text()
            if page_text:
                sample_pages_text.append(page_text)

        combined_text = "\n".join(sample_pages_text)

        # 1. Detect Grade with full provenance
        grade_code, grade_name, grade_level, grade_src, grade_match = cls.detect_grade(combined_text, filename)

        # 2. Detect Subject via Configurable Profiles
        profile: Optional[SubjectDetectionProfile] = subject_registry.find_best_match(
            sample_text=combined_text,
            filename=filename,
        )

        subject_code = profile.code if profile else None
        subject_name = profile.name if profile else None
        domain = profile.domain if profile else None

        # 3. Detect Edition Label and Publication Year
        edition_label, pub_year, year_src, year_match = cls.detect_edition(combined_text, filename)

        # 4. Detect Book Title
        title = None
        meta_title = doc.metadata.get("title", "") if doc.metadata else ""
        if meta_title and len(meta_title.strip()) > 3:
            title = meta_title.strip()
        elif subject_name and grade_name:
            title = f"{subject_name} ({grade_name})"
        elif subject_name:
            title = subject_name
        else:
            clean_name = re.sub(r"[_\-]+", " ", Path(filename).stem)
            title = clean_name.title() if clean_name else "NCTB Textbook"

        version_label = edition_label or (f"{pub_year} Edition" if pub_year else None)

        diagnostics = {
            "inspected_pages": max_inspect_pages,
            "detected_profile": profile.code if profile else None,
            "pdf_docinfo": {k: v for k, v in (doc.metadata or {}).items() if v},
            "grade": {
                "value": grade_name,
                "code": grade_code,
                "level": grade_level,
                "source": grade_src,
                "matched_text": grade_match,
            } if grade_name else None,
            "edition": {
                "label": edition_label,
                "year": pub_year,
                "source": year_src,
                "matched_text": year_match,
            } if (edition_label or pub_year) else None,
            "edition_year": {
                "value": pub_year,
                "source": year_src,
                "matched_text": year_match,
            } if pub_year else None,
            "publication_year": {
                "value": pub_year,
                "source": year_src,
                "matched_text": year_match,
            } if pub_year else None,
        }

        return DetectedDocumentMetadata(
            title=title,
            grade_code=grade_code,
            grade_name=grade_name,
            grade_level=grade_level,
            subject_code=subject_code,
            subject_name=subject_name,
            domain=domain,
            edition_year=pub_year,
            edition_label=edition_label,
            publication_year=pub_year,
            version_label=version_label,
            diagnostic_signals=diagnostics,
        )
