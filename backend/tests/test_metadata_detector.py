import pymupdf
import pytest
from app.services.pdf.metadata_detector import DynamicMetadataDetector
from tests.utils import (
    create_synthetic_english_today_pdf,
    create_synthetic_english_grammar_pdf,
    create_synthetic_mathematics_pdf,
)


def test_detect_metadata_english_today():
    pdf_bytes = create_synthetic_english_today_pdf()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    meta = DynamicMetadataDetector.detect_metadata(doc, "English_For_Today_Class_9.pdf")
    doc.close()

    assert meta.grade_code == "class-9"
    assert meta.grade_name == "Class 9"
    assert meta.grade_level == 9
    assert meta.subject_code == "english-for-today"
    assert meta.subject_name == "English for Today"
    assert meta.domain == "LANGUAGE"
    assert meta.publication_year == 2024
    assert meta.diagnostic_signals is not None
    assert meta.diagnostic_signals["grade"]["source"] == "content"
    assert meta.diagnostic_signals["publication_year"]["source"] == "content"


def test_detect_metadata_english_grammar():
    pdf_bytes = create_synthetic_english_grammar_pdf()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    meta = DynamicMetadataDetector.detect_metadata(doc, "English_Grammar_Class_9.pdf")
    doc.close()

    assert meta.grade_code == "class-9"
    assert meta.grade_name == "Class 9"
    assert meta.grade_level == 9
    assert meta.subject_code == "english-grammar"
    assert meta.subject_name == "English Grammar and Composition"
    assert meta.domain == "LANGUAGE"
    assert meta.edition_year == 2024
    assert meta.diagnostic_signals["grade"]["source"] == "content"


def test_detect_metadata_mathematics():
    pdf_bytes = create_synthetic_mathematics_pdf()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    meta = DynamicMetadataDetector.detect_metadata(doc, "Mathematics_Class_9.pdf")
    doc.close()

    assert meta.grade_code == "class-9"
    assert meta.grade_name == "Class 9"
    assert meta.grade_level == 9
    assert meta.subject_code == "mathematics"
    assert meta.subject_name == "Mathematics"
    assert meta.domain == "STEM"
    assert meta.edition_year == 2024
    assert meta.diagnostic_signals["grade"]["source"] == "content"
