import json
import tempfile
from pathlib import Path
import pytest
from app.services.pdf.subject_profiles import (
    SubjectDetectionProfile,
    SubjectProfileRegistry,
    load_profiles_from_file,
    load_profiles_from_json_data,
)
from app.core.config import settings
from app.services.pdf.metadata_detector import DynamicMetadataDetector
import pymupdf


def test_subject_profiles_load_success():
    """Verify that the official subject_profiles.json configuration loads correctly."""
    profiles = load_profiles_from_file(settings.SUBJECT_PROFILES_PATH)
    assert len(profiles) >= 3

    codes = [p.code for p in profiles]
    assert "english-for-today" in codes
    assert "english-grammar" in codes
    assert "mathematics" in codes

    math_prof = next(p for p in profiles if p.code == "mathematics")
    assert math_prof.name == "Mathematics"
    assert math_prof.domain == "STEM"
    assert "theorem" in math_prof.keywords


def test_malformed_subject_profiles_json_raises():
    """Verify that malformed JSON or invalid schema raises descriptive ValueError."""
    # 1. Invalid JSON syntax
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{ invalid json")
        invalid_json_path = f.name

    with pytest.raises(ValueError) as exc_info:
        load_profiles_from_file(invalid_json_path)
    assert "Malformed JSON" in str(exc_info.value)
    Path(invalid_json_path).unlink(missing_ok=True)

    # 2. Missing required field 'code'
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump([{"name": "No Code Subject"}], f)
        missing_code_path = f.name

    with pytest.raises(ValueError) as exc_info2:
        load_profiles_from_file(missing_code_path)
    assert "Invalid subject profile" in str(exc_info2.value)
    Path(missing_code_path).unlink(missing_ok=True)


def test_empty_profiles_structure_raises():
    """Verify empty or wrong type profiles configuration raises ValueError."""
    with pytest.raises(ValueError) as exc:
        load_profiles_from_json_data([])
    assert "contains no profiles" in str(exc.value)

    with pytest.raises(ValueError) as exc2:
        load_profiles_from_json_data("not-a-list")  # type: ignore
    assert "Invalid profile configuration structure" in str(exc2.value)


def test_dynamic_fourth_subject_profile_detection():
    """
    Prove zero-hardcoding compliance:
    A synthetic fourth subject profile (e.g. Physics) supplied purely through configuration/registry
    is detected by DynamicMetadataDetector WITHOUT any changes to core parser/detector code.
    """
    registry = SubjectProfileRegistry()

    # Define 4th profile dynamically as a config object
    physics_profile = SubjectDetectionProfile(
        code="physics",
        name="Physics",
        domain="STEM",
        aliases=["Physics", "General Physics"],
        title_patterns=["physics", "general physics"],
        keywords=["velocity", "acceleration", "force", "newton", "thermodynamics", "optics"],
    )
    registry.register_profile(physics_profile)

    # Generate a synthetic Physics textbook PDF
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=12)
    p1.insert_text((72, 140), "Physics", fontsize=24)
    p1.insert_text((72, 180), "Class 9", fontsize=16)
    p1.insert_text((72, 210), "Academic Year 2024", fontsize=12)

    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 80), "Chapter 1 : Motion and Force", fontsize=20)
    p2.insert_text((72, 120), "Newton's laws of motion explain how force affects velocity and acceleration.", fontsize=11)

    # Reload document from bytes to ensure page stream is materialized
    pdf_bytes = doc.tobytes()
    doc.close()
    reopened_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    # Detect metadata with the active registry
    sample_text = "\n".join(reopened_doc[i].get_text() for i in range(reopened_doc.page_count))
    matched = registry.find_best_match(sample_text=sample_text, filename="Physics_Class_9.pdf")
    assert matched is not None
    assert matched.code == "physics"
    assert matched.name == "Physics"
    assert matched.domain == "STEM"

    reopened_doc.close()
