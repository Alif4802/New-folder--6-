import io
import json
import pytest
from pathlib import Path
import pymupdf
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode
from app.schemas.readable import BlockType, ReadableDocumentResponse
from app.services.reconstruction.config import ReconstructionRules, get_reconstruction_rules
from app.services.reconstruction.layout_extractor import LayoutExtractor, LayoutLine, LayoutSpan, PageLayout
from app.services.reconstruction.math_normalizer import MathNormalizer
from app.services.reconstruction.table_detector import TableDetector
from app.services.reconstruction.reconstructor import ReconstructionEngine


def test_reconstruction_config_loads():
    """Prove that reconstruction rules config loads valid thresholds and markers."""
    rules = get_reconstruction_rules()
    assert rules.layout.paragraph_alignment_tolerance_pt > 0
    assert rules.layout.superscript_max_font_size_ratio < 1.0
    assert "Example" in rules.markers.example_starters
    assert "Activity" in rules.markers.activity_starters
    assert "Exercise" in rules.markers.exercise_starters


def test_malformed_config_rejected(tmp_path):
    """Prove that malformed reconstruction config fails clearly."""
    bad_config_file = tmp_path / "bad_rules.json"
    bad_config_file.write_text("{\"layout_thresholds\": \"not_a_dict\"}", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed reconstruction config"):
        ReconstructionRules.load_from_file(bad_config_file)


def test_configured_markers_affect_grouping():
    """Prove that changing configured semantic markers affects grouping without code changes."""
    rules = get_reconstruction_rules()
    # Create custom rules with a new custom marker
    custom_rules = ReconstructionRules(
        layout=rules.layout,
        markers=rules.markers,
    )
    custom_rules.markers.activity_starters.append("SpecialLabInvestigation")

    engine = ReconstructionEngine(custom_rules)
    assert "SpecialLabInvestigation" in engine.rules.markers.activity_starters


def test_table_detection_low_vs_high_confidence():
    """Prove that low-confidence alignment does NOT become a table, but high-confidence geometric data does."""
    rules = get_reconstruction_rules()
    detector = TableDetector(rules)

    # 1. Low confidence: only 2 lines with 2 words (under table_min_rows=3)
    span1 = LayoutSpan("Col1", 11.0, "Arial", 0, 72, 100, 120, 112, 72, 112)
    span2 = LayoutSpan("Col2", 11.0, "Arial", 0, 150, 100, 200, 112, 150, 112)
    line1 = LayoutLine([span1, span2], "Col1  Col2", 72, 100, 200, 112, 112, 1, 11.0)

    span3 = LayoutSpan("Val1", 11.0, "Arial", 0, 72, 120, 120, 132, 72, 132)
    span4 = LayoutSpan("Val2", 11.0, "Arial", 0, 150, 120, 200, 132, 150, 132)
    line2 = LayoutLine([span3, span4], "Val1  Val2", 72, 120, 200, 132, 132, 1, 11.0)

    low_conf_result = detector.detect_table_block([line1, line2], drawings=[])
    assert low_conf_result is None, "2-line alignment must NOT be classified as a table."

    # 2. High confidence: 3 lines with 2 columns
    span5 = LayoutSpan("Val3", 11.0, "Arial", 0, 72, 140, 120, 152, 72, 152)
    span6 = LayoutSpan("Val4", 11.0, "Arial", 0, 150, 140, 200, 152, 150, 152)
    line3 = LayoutLine([span5, span6], "Val3  Val4", 72, 140, 200, 152, 152, 1, 11.0)

    high_conf_result = detector.detect_table_block([line1, line2, line3], drawings=[])
    assert high_conf_result is not None, "3-row aligned data must be detected as a table."
    table_rows, consumed, _ = high_conf_result
    assert len(table_rows) == 3
    assert len(table_rows[0].cells) == 2
    assert table_rows[0].cells[0].text == "Col1"
    assert table_rows[0].cells[1].text == "Col2"


def test_prose_preservation_no_equation_rewriting():
    """Prove that textbook prose is preserved and never rewritten into formulas."""
    rules = get_reconstruction_rules()
    normalizer = MathNormalizer(rules)

    span = LayoutSpan("The square root of 25 is 5.", 11.0, "Arial", 0, 72, 100, 300, 112, 72, 112)
    line = LayoutLine([span], "The square root of 25 is 5.", 72, 100, 300, 112, 112, 1, 11.0)

    result_spans = normalizer.normalize_line_spans(line, 11.0)
    assert len(result_spans) == 1
    assert result_spans[0].is_math is False
    assert result_spans[0].text == "The square root of 25 is 5."
    assert result_spans[0].latex is None


def test_math_geometry_superscript_only():
    """Prove that superscripts require geometric evidence (font size reduction + vertical baseline offset)."""
    rules = get_reconstruction_rules()
    normalizer = MathNormalizer(rules)

    # 1. Base 'x' (size 12, baseline 100) followed by '2' with smaller font (size 8) and elevated baseline (origin_y=95)
    base_span = LayoutSpan("x", 12.0, "Arial", 0, 72, 88, 80, 100, 72, 100)
    sup_span = LayoutSpan("2", 8.0, "Arial", 0, 81, 80, 87, 94, 81, 94)
    line_with_geometry = LayoutLine([base_span, sup_span], "x2", 72, 80, 87, 100, 100, 1, 12.0)

    res = normalizer.normalize_line_spans(line_with_geometry, 12.0)
    assert len(res) == 1
    assert res[0].is_math is True
    assert res[0].latex == "x^{2}"
    assert res[0].raw_text == "x2"

    # 2. Same text 'x2' on a single span or without elevation must NOT be converted to superscript
    flat_span = LayoutSpan("x2", 12.0, "Arial", 0, 72, 88, 88, 100, 72, 100)
    line_flat = LayoutLine([flat_span], "x2", 72, 88, 88, 100, 100, 1, 12.0)

    res_flat = normalizer.normalize_line_spans(line_flat, 12.0)
    assert len(res_flat) == 1
    assert res_flat[0].is_math is False
    assert res_flat[0].latex is None


@pytest.mark.asyncio
async def test_nullable_end_page_resolution(db_session):
    """Prove that nullable end_page on Unit and Lesson is resolved deterministically."""
    # Create test hierarchy with nullable end_page
    curr = Curriculum(code="NCTB-TEST-NULL", name="NCTB Test Null", country="Bangladesh", authority="NCTB")
    db_session.add(curr)
    await db_session.flush()

    grade = Grade(curriculum_id=curr.id, name="Class 9", code="class-9", level_number=9)
    db_session.add(grade)
    await db_session.flush()

    subj = Subject(curriculum_id=curr.id, name="Test Subj", code="test-subj", domain="STEM")
    db_session.add(subj)
    await db_session.flush()

    ver = SubjectVersion(
        curriculum_id=curr.id,
        subject_id=subj.id,
        grade_id=grade.id,
        id="test-ver-null-1",
        title="Test Subj (Class 9)",
        source_filename="test.pdf",
        stored_pdf_path="test.pdf",
        checksum_sha256="000111222",
        file_size_bytes=100,
        page_count=10,
        ingestion_status="COMPLETED",
    )
    db_session.add(ver)
    await db_session.flush()

    unit1 = Unit(subject_version_id=ver.id, ordinal=1, detected_number="1", title="Unit 1", start_page=1, end_page=None)
    unit2 = Unit(subject_version_id=ver.id, ordinal=2, detected_number="2", title="Unit 2", start_page=6, end_page=None)
    db_session.add_all([unit1, unit2])
    await db_session.flush()

    lesson1 = Lesson(unit_id=unit1.id, ordinal=1, detected_number="1.1", title="Lesson 1.1", start_page=1, end_page=None)
    lesson2 = Lesson(unit_id=unit1.id, ordinal=2, detected_number="1.2", title="Lesson 1.2", start_page=3, end_page=None)
    db_session.add_all([lesson1, lesson2])
    await db_session.commit()

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Load with full relationships
    res = await db_session.execute(
        select(SubjectVersion)
        .where(SubjectVersion.id == ver.id)
        .options(selectinload(SubjectVersion.units).selectinload(Unit.lessons))
    )
    loaded_ver = res.scalar_one()
    loaded_u1 = loaded_ver.units[0]
    loaded_l1 = loaded_u1.lessons[0]
    loaded_l2 = loaded_u1.lessons[1]

    engine = ReconstructionEngine()

    # Lesson 1 end_page should resolve to Lesson 2 start_page - 1 = 2
    start_p, end_p, _, _, _, _ = engine._resolve_scope_pages(loaded_ver, unit=loaded_u1, lesson=loaded_l1, page=None)
    assert start_p == 1
    assert end_p == 2

    # Lesson 2 end_page should resolve to next unit start_page - 1 = 5
    start_p2, end_p2, _, _, _, _ = engine._resolve_scope_pages(loaded_ver, unit=loaded_u1, lesson=loaded_l2, page=None)
    assert start_p2 == 3
    assert end_p2 == 5

    # Unit 1 end_page should resolve to Unit 2 start_page - 1 = 5
    u_start, u_end, _, _, _, _ = engine._resolve_scope_pages(loaded_ver, unit=loaded_u1, lesson=None, page=None)
    assert u_start == 1
    assert u_end == 5



@pytest.mark.asyncio
async def test_missing_pdf_fallback_marked_degraded(db_session):
    """Prove that missing physical PDF falls back to AST and marks layout_source as persisted_ast_fallback."""
    curr = Curriculum(code="NCTB-TEST-FALLBACK", name="NCTB Fallback", country="Bangladesh", authority="NCTB")
    db_session.add(curr)
    await db_session.flush()

    grade = Grade(curriculum_id=curr.id, name="Class 9", code="class-9", level_number=9)
    db_session.add(grade)
    await db_session.flush()

    subj = Subject(curriculum_id=curr.id, name="Fallback Subj", code="fallback-subj", domain="LANGUAGE")
    db_session.add(subj)
    await db_session.flush()

    ver = SubjectVersion(
        curriculum_id=curr.id,
        subject_id=subj.id,
        grade_id=grade.id,
        id="test-ver-fallback-1",
        title="Fallback Book (Class 9)",
        source_filename="nonexistent.pdf",
        stored_pdf_path="nonexistent.pdf",
        checksum_sha256="nonexistent_sha",
        file_size_bytes=100,
        page_count=5,
        ingestion_status="COMPLETED",
    )
    db_session.add(ver)
    await db_session.flush()

    unit = Unit(subject_version_id=ver.id, ordinal=1, detected_number="1", title="Unit 1", start_page=1, end_page=5)
    db_session.add(unit)
    await db_session.flush()

    lesson = Lesson(unit_id=unit.id, ordinal=1, detected_number="1.1", title="Lesson 1.1", start_page=1, end_page=5)
    db_session.add(lesson)
    await db_session.flush()

    node = ActivityNode(
        subject_version_id=ver.id,
        unit_id=unit.id,
        lesson_id=lesson.id,
        ordinal=1,
        node_type="generic_text",
        content_text="This is fallback text when PDF is missing.",
        page_number=1,
        bounding_box={"x0": 72, "y0": 100, "x1": 400, "y1": 150},
        content_hash="abc",
    )
    db_session.add(node)
    await db_session.commit()

    engine = ReconstructionEngine()
    doc = await engine.get_readable_document(session=db_session, version_id=ver.id, lesson_id=lesson.id)

    assert doc.layout_source == "persisted_ast_fallback"
    assert any("RAW_PDF_LAYOUT_UNAVAILABLE" in w for w in doc.warnings)
    assert len(doc.blocks) == 1
    assert doc.blocks[0].content_text == "This is fallback text when PDF is missing."


@pytest.mark.asyncio
async def test_reconstruction_service_scoping(client, db_session):
    """Prove that ReconstructionEngine get_readable_document functions for valid scopes."""
    # 1. Ingest a synthetic book via IngestionService
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 75), "English for Today", fontsize=20)
    p1.insert_text((72, 100), "Class 9", fontsize=14)
    p1.insert_text((72, 120), "Academic Year 2024", fontsize=11)
    p1.insert_text((72, 160), "Unit 1 : Welcome", fontsize=16)
    p1.insert_text((72, 190), "Lesson 1 : Friends", fontsize=13)
    p1.insert_text((72, 220), "Welcome to English class!", fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()

    ingest_res = await client.post(
        "/api/v1/textbooks/ingest",
        files={"file": ("English_Readable_Scope_Test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert ingest_res.status_code == 201
    v_id = ingest_res.json()["version_id"]

    # Fetch curriculum to find lesson_id
    curr_res = await client.get(f"/api/v1/textbooks/{v_id}/curriculum")
    assert curr_res.status_code == 200
    curr = curr_res.json()
    unit_id = curr["units"][0]["id"]
    lesson_id = curr["units"][0]["lessons"][0]["id"]

    # 2. Test ReconstructionEngine service directly
    engine = ReconstructionEngine()
    data = await engine.get_readable_document(
        session=db_session,
        version_id=v_id,
        lesson_id=lesson_id,
    )
    assert data.version_id == v_id
    assert data.scope_type == "lesson"
    assert len(data.blocks) > 0
    first_block = data.blocks[0]
    assert len(first_block.source_pages) > 0
    assert len(first_block.source_regions) > 0


def test_reconstruction_strict_token_fidelity():
    """
    Prove that paragraph reconstruction cannot introduce semantic words or sentences absent from source evidence.
    Every reconstructed token must be directly traceable to input line spans.
    """
    rules = get_reconstruction_rules()
    engine = ReconstructionEngine(rules)

    input_text_1 = "For example, 5 x 5 = 25. Here, 25 is the square of 5."
    input_text_2 = "When a number is multiplied by itself, the product obtained is called square."

    span1 = LayoutSpan(input_text_1, 11.0, "Arial", 0, 72, 100, 350, 112, 72, 112)
    span2 = LayoutSpan(input_text_2, 11.0, "Arial", 0, 72, 118, 450, 130, 72, 130)

    line1 = LayoutLine([span1], input_text_1, 72, 100, 350, 112, 112, 1, 11.0)
    line2 = LayoutLine([span2], input_text_2, 72, 118, 450, 130, 130, 1, 11.0)

    page_layout = PageLayout(
        page_number=1,
        width=595,
        height=842,
        lines=[line1, line2],
        drawings=[],
        median_body_font_size=11.0,
    )


    ver = SubjectVersion(
        id="test-fid-1",
        title="Fidelity Test",
        source_filename="test.pdf",
        stored_pdf_path="test.pdf",
        checksum_sha256="test-sha",
        file_size_bytes=100,
        page_count=1,
        ingestion_status="COMPLETED",
    )

    doc = engine.reconstruct_from_pdf_layout(
        version=ver,
        page_layouts=[page_layout],
        version_header_patterns=set(),
        ast_nodes=[],
        start_page=1,
        end_page=1,
        scope_type="page",
        scope_id=1,
        title="Fidelity Test",
        subtitle=None,
    )

    reconstructed_full_text = " ".join([b.content_text for b in doc.blocks])
    # Verify no injected sentences exist
    assert "and 5 is the square root of 25" not in reconstructed_full_text
    # Verify exact input tokens are preserved
    assert input_text_1 in reconstructed_full_text
    assert input_text_2 in reconstructed_full_text


def test_operator_fidelity_ascii_x_vs_unicode_times():
    """
    Prove that ASCII 'x' is preserved as ASCII 'x' and only genuine Unicode '×' is converted to \\times.
    """
    rules = get_reconstruction_rules()
    normalizer = MathNormalizer(rules)

    # 1. ASCII 'x' in multiplication equation: '5 x 5 = 25'
    span_ascii = LayoutSpan("5 x 5 = 25", 11.0, "Arial", 0, 72, 100, 200, 112, 72, 112)
    line_ascii = LayoutLine([span_ascii], "5 x 5 = 25", 72, 100, 200, 112, 112, 1, 11.0)
    res_ascii = normalizer.normalize_line_spans(line_ascii, 11.0)
    assert len(res_ascii) == 1
    assert res_ascii[0].is_math is True
    assert res_ascii[0].raw_text == "5 x 5 = 25"
    assert res_ascii[0].text == "5 x 5 = 25"
    assert "times" not in (res_ascii[0].latex or "")

    # 2. Genuine Unicode '×' (\u00d7): '5 × 5 = 25'
    span_unicode = LayoutSpan("5 \u00d7 5 = 25", 11.0, "Arial", 0, 72, 100, 200, 112, 72, 112)
    line_unicode = LayoutLine([span_unicode], "5 \u00d7 5 = 25", 72, 100, 200, 112, 112, 1, 11.0)
    res_unicode = normalizer.normalize_line_spans(line_unicode, 11.0)
    assert len(res_unicode) == 1
    assert res_unicode[0].is_math is True
    assert r"\times" in res_unicode[0].latex


def test_table_no_derived_cell_values():
    """
    Prove that TableDetector extracts only text present in source lines and never calculates or synthesizes missing cell values.
    """
    rules = get_reconstruction_rules()
    detector = TableDetector(rules)

    span1 = LayoutSpan("Number", 11.0, "Arial", 0, 72, 100, 120, 112, 72, 112)
    span2 = LayoutSpan("Square", 11.0, "Arial", 0, 150, 100, 200, 112, 150, 112)
    line1 = LayoutLine([span1, span2], "Number  Square", 72, 100, 200, 112, 112, 1, 11.0)

    span3 = LayoutSpan("5", 11.0, "Arial", 0, 72, 120, 120, 132, 72, 132)
    span4 = LayoutSpan("25", 11.0, "Arial", 0, 150, 120, 200, 132, 150, 132)
    line2 = LayoutLine([span3, span4], "5  25", 72, 120, 200, 132, 132, 1, 11.0)

    span5 = LayoutSpan("6", 11.0, "Arial", 0, 72, 140, 120, 152, 72, 152)
    span6 = LayoutSpan("36", 11.0, "Arial", 0, 150, 140, 200, 152, 150, 152)
    line3 = LayoutLine([span5, span6], "6  36", 72, 140, 200, 152, 152, 1, 11.0)

    table_match = detector.detect_table_block([line1, line2, line3], drawings=[])
    assert table_match is not None
    rows, _, _ = table_match
    # Cell contents must match exactly
    assert [c.text for c in rows[0].cells] == ["Number", "Square"]
    assert [c.text for c in rows[1].cells] == ["5", "25"]
    assert [c.text for c in rows[2].cells] == ["6", "36"]
    # No extra columns (like Formula: 5 x 5 = 25) were invented
    assert len(rows[0].cells) == 2
    assert len(rows[1].cells) == 2
    assert len(rows[2].cells) == 2


