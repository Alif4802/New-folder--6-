import pymupdf
import pytest
from app.services.pdf.extractor import PageExtractor
from app.services.pdf.structure_parser import DynamicStructureParser
from tests.utils import (
    create_synthetic_english_today_pdf,
    create_synthetic_english_grammar_pdf,
    create_synthetic_mathematics_pdf,
)


@pytest.mark.asyncio
async def test_structure_parser_english_today():
    pdf_bytes = create_synthetic_english_today_pdf()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    extractor = PageExtractor()
    page_results = [await extractor.extract_page(doc, i) for i in range(doc.page_count)]
    doc.close()

    structure = DynamicStructureParser.parse_document(page_results, domain="LANGUAGE")

    # Front matter pages before Unit 1 should be recorded
    assert len(structure.unresolved_front_matter_pages) == 2  # Pages 1 and 2
    assert len(structure.units) == 1

    unit1 = structure.units[0]
    assert unit1.detected_number == "1"
    assert "Father of the Nation" in unit1.title
    assert len(unit1.lessons) == 1

    lesson1 = unit1.lessons[0]
    assert lesson1.detected_number == "1"
    assert "Bangabandhu's Family in 1971" in lesson1.title
    assert len(lesson1.nodes) >= 3

    # Verify node classification
    node_types = [n.node_type for n in lesson1.nodes]
    assert "dialogue" in node_types or "instruction" in node_types
    assert "reading_passage" in node_types or "exercise" in node_types


@pytest.mark.asyncio
async def test_structure_parser_mathematics():
    pdf_bytes = create_synthetic_mathematics_pdf()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    extractor = PageExtractor()
    page_results = [await extractor.extract_page(doc, i) for i in range(doc.page_count)]
    doc.close()

    structure = DynamicStructureParser.parse_document(page_results, domain="STEM")

    assert len(structure.unresolved_front_matter_pages) == 1  # Page 1 (Title page)
    assert len(structure.units) == 1

    chapter1 = structure.units[0]
    assert chapter1.label_type == "Chapter"
    assert chapter1.detected_number == "1"
    assert "Real Numbers" in chapter1.title

    # Nodes can be in lesson or direct
    all_nodes = chapter1.direct_nodes + [n for l in chapter1.lessons for n in l.nodes]
    node_types = [n.node_type for n in all_nodes]
    assert "definition" in node_types or "theorem" in node_types
    assert "worked_example" in node_types or "exercise" in node_types
