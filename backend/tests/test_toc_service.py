import pytest
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode
from app.services.pdf.toc_service import (
    clean_heading_text,
    is_valid_unit_number,
    is_valid_unit_title,
    is_valid_lesson_title,
    extract_confident_exercise_label,
    extract_usable_pdf_bookmarks,
    build_textbook_toc,
)


def test_clean_heading_text():
    # 1. Cleans corrupt tokens, replacement chars, normalizes spaces
    dirty = "Chapter  1 \ufffd\ufffd  Rational   Numbers \u2013 Part   I "
    cleaned = clean_heading_text(dirty)
    assert cleaned == "Chapter 1 Rational Numbers — Part I"


def test_malformed_unit_number_rejected():
    # 2. Rejects common words/verbs or duplicate label types as unit numbers
    assert is_valid_unit_number("part", "Part") is False
    assert is_valid_unit_number("is", "Part") is False
    assert is_valid_unit_number("digit", "Unit") is False
    assert is_valid_unit_number("and", "Chapter") is False
    assert is_valid_unit_number("the", "Chapter") is False

    # Valid unit numbers
    assert is_valid_unit_number("1", "Chapter") is True
    assert is_valid_unit_number("12", "Unit") is True
    assert is_valid_unit_number("IV", "Chapter") is True
    assert is_valid_unit_number("B", "Part") is True


def test_sentence_like_body_text_rejected_as_unit_title():
    # 3. Sentence fragments and instructional text rejected
    assert is_valid_unit_title("and moving left, the number of dots will be equal to the number") is False
    assert is_valid_unit_title("filled in 1 minute") is False
    assert is_valid_unit_title("which is the ratio of two numbers") is False
    assert is_valid_unit_title("A=x2 + 2xy + y2") is False

    # Valid headings accepted
    assert is_valid_unit_title("Rational and Irrational Numbers") is True
    assert is_valid_unit_title("Proportion, Profit and Loss") is True
    assert is_valid_unit_title("Multiplication and Division of Algebraic Expressions") is True


def test_malformed_lesson_title_rejected():
    # 4. Math formula or instructional text rejected as lesson title
    assert is_valid_lesson_title("A=x2 - xy+Y2, B=x2 + xy+Y and C 4", "10.1") is False
    assert is_valid_lesson_title("and we will solve the problem", "2.1") is False

    # Valid lesson title accepted
    assert is_valid_lesson_title("Multiplication of Algebraic Expressions", "4.1") is True
    assert is_valid_lesson_title("Squares and square roots", "1.1") is True


def test_confident_numbered_exercise_preserved():
    # 5. Numbered exercise headings preserved with high confidence
    node = ActivityNode(
        id=1,
        subject_version_id="test",
        title="Exercise",
        content_text="Exercise 1.1\n1. Solve the following fractions\n(a) 1/2 + 1/3",
        page_number=14,
        node_type="exercise",
        ordinal=1,
    )
    label = extract_confident_exercise_label(node, parent_unit_num="1")
    assert label == "Exercise 1.1"


def test_cross_chapter_exercise_reference_rejected():
    # 6. Exercise 10.3 referenced in text under Chapter 11 rejected
    node = ActivityNode(
        id=2,
        subject_version_id="test",
        title="Exercise",
        content_text="Exercise 10.3\n3. (d)",
        page_number=197,
        node_type="exercise",
        ordinal=2,
    )
    label = extract_confident_exercise_label(node, parent_unit_num="11")
    assert label is None


def test_body_questions_not_promoted_to_exercise():
    # 7. Internal questions/prompts not promoted to exercise TOC items
    node1 = ActivityNode(
        id=3,
        subject_version_id="test",
        title="Exercise",
        content_text="Creative Question:\n5. Find the value of x when...",
        page_number=82,
        node_type="exercise",
        ordinal=3,
    )
    assert extract_confident_exercise_label(node1, parent_unit_num="4") is None

    node2 = ActivityNode(
        id=4,
        subject_version_id="test",
        title="Exercise",
        content_text="Which is the twice divided ratio of 4:9?",
        page_number=45,
        node_type="exercise",
        ordinal=4,
    )
    assert extract_confident_exercise_label(node2, parent_unit_num="2") is None


def test_no_exercise_numbering_invented():
    # 8. Genuine standalone Exercise heading kept as "Exercise" without inventing a number
    node = ActivityNode(
        id=5,
        subject_version_id="test",
        title="Exercise",
        content_text="Exercise\nDivide the first expression by the second expression",
        page_number=76,
        node_type="exercise",
        ordinal=5,
    )
    label = extract_confident_exercise_label(node, parent_unit_num="4")
    assert label == "Exercise"
    assert "1" not in label and "4." not in label


def test_build_textbook_toc_quality_gate_integration():
    # 9. Full hierarchy building with quality gate and deduplication
    v = SubjectVersion(
        id="test-version",
        curriculum_id=1,
        title="Mathematics Class 7",
        source_filename="math.pdf",
        page_count=50,
        ingestion_status="COMPLETED",
    )

    # Valid Chapter 1
    u1 = Unit(
        id=1, subject_version_id="test-version", ordinal=1,
        label_type="Chapter", detected_number="1", title="Rational Numbers",
        start_page=5, end_page=20
    )
    l1 = Lesson(
        id=1, unit_id=1, ordinal=1, detected_number="1.1",
        title="Square Roots", start_page=5, end_page=10
    )
    ex1 = ActivityNode(
        id=10, subject_version_id="test-version", lesson_id=1, unit_id=1,
        node_type="exercise", title="Exercise",
        content_text="Exercise 1.1\n1. Find square root",
        page_number=8, ordinal=1
    )
    # Duplicate exercise on same page
    ex1_dup = ActivityNode(
        id=11, subject_version_id="test-version", lesson_id=1, unit_id=1,
        node_type="exercise", title="Exercise",
        content_text="Exercise 1.1\n2. Continue",
        page_number=8, ordinal=2
    )
    l1.activity_nodes = [ex1, ex1_dup]
    u1.lessons = [l1]
    u1.activity_nodes = []

    # Malformed Unit (e.g. Part part - 15)
    u2_bad = Unit(
        id=2, subject_version_id="test-version", ordinal=2,
        label_type="Part", detected_number="part", title="15",
        start_page=21, end_page=22
    )
    u2_bad.lessons = []
    u2_bad.activity_nodes = []

    # Valid Chapter 2
    u3 = Unit(
        id=3, subject_version_id="test-version", ordinal=3,
        label_type="Chapter", detected_number="2", title="Algebra",
        start_page=25, end_page=45
    )
    u3.lessons = []
    u3.activity_nodes = []

    v.units = [u1, u2_bad, u3]

    toc_items, source = build_textbook_toc(v)
    assert source == "PARSED_CURRICULUM"
    # Malformed Unit 2 must be excluded
    assert len(toc_items) == 2
    assert toc_items[0].label == "Chapter 1 — Rational Numbers"
    assert toc_items[0].page_number == 5
    assert toc_items[1].label == "Chapter 2 — Algebra"
    assert toc_items[1].page_number == 25

    # Check child lesson and deduplicated exercise
    u1_children = toc_items[0].children
    assert len(u1_children) == 1
    assert u1_children[0].type == "lesson"
    assert u1_children[0].label == "1.1 Square Roots"

    l1_children = u1_children[0].children
    assert len(l1_children) == 1  # Deduplicated from 2 to 1!
    assert l1_children[0].type == "exercise"
    assert l1_children[0].label == "Exercise 1.1"
    assert l1_children[0].page_number == 8


def test_exercise_label_fidelity_from_ocr_dot_artifact():
    # 10. Exercise 501 / Exercise 5·1 artifact recovered accurately as Exercise 5.1
    node = ActivityNode(
        id=20,
        subject_version_id="test",
        title="Exercise",
        content_text="Exercise 501\nDetermine the square with formulae",
        page_number=90,
        node_type="exercise",
        ordinal=1,
    )
    label = extract_confident_exercise_label(node, parent_unit_num="5")
    assert label == "Exercise 5.1"


def test_exercise_number_never_inferred_from_sequence():
    # 11. If the node literally says "Exercise" and has no numbered heading evidence,
    # it remains "Exercise" and NEVER infers e.g. "Exercise 5.2" or "Exercise 2"
    node = ActivityNode(
        id=21,
        subject_version_id="test",
        title="Exercise",
        content_text="Exercise\nFind the factors:\n1. x + xy + zx + yz",
        page_number=96,
        node_type="exercise",
        ordinal=1,
    )
    label = extract_confident_exercise_label(node, parent_unit_num="5")
    assert label == "Exercise"
    assert "5.2" not in label and "2" not in label


def test_section_gap_never_synthesizes_missing_sections():
    # 12. Valid sections 4.1, 4.2, 4.3, 4.7 are preserved as-is without inventing 4.4, 4.5, 4.6
    v = SubjectVersion(
        id="math-gaps",
        curriculum_id=1,
        title="Mathematics",
        page_count=100,
        ingestion_status="COMPLETED",
    )
    u = Unit(
        id=1, subject_version_id="math-gaps", ordinal=1,
        label_type="Chapter", detected_number="4",
        title="Multiplication and Division", start_page=61, end_page=82
    )
    l1 = Lesson(id=1, unit_id=1, ordinal=1, detected_number="4.1", title="Multiplication", start_page=61, end_page=62)
    l2 = Lesson(id=2, unit_id=1, ordinal=2, detected_number="4.2", title="Expressions with signs", start_page=63, end_page=63)
    l3 = Lesson(id=3, unit_id=1, ordinal=3, detected_number="4.3", title="Monomial Multiplied", start_page=64, end_page=69)
    l4 = Lesson(id=4, unit_id=1, ordinal=4, detected_number="4.7", title="Division of expressions", start_page=70, end_page=70)
    
    l1.activity_nodes = []
    l2.activity_nodes = []
    l3.activity_nodes = []
    l4.activity_nodes = []
    
    u.lessons = [l1, l2, l3, l4]
    u.activity_nodes = []
    v.units = [u]

    toc_items, source = build_textbook_toc(v)
    assert len(toc_items) == 1
    chapter = toc_items[0]
    lesson_labels = [c.label for c in chapter.children]
    
    # Verify exact lessons preserved without synthesizing 4.4, 4.5, 4.6
    assert len(lesson_labels) == 4
    assert lesson_labels == [
        "4.1 Multiplication",
        "4.2 Expressions with signs",
        "4.3 Monomial Multiplied",
        "4.7 Division of expressions"
    ]
    assert not any("4.4" in l or "4.5" in l or "4.6" in l for l in lesson_labels)


def test_pdf_page_and_book_page_separation():
    # 13. Physical PDF page number and printed book page label separation
    v = SubjectVersion(
        id="book-labels-test",
        curriculum_id=1,
        title="Mathematics",
        page_count=50,
        ingestion_status="COMPLETED",
    )
    u = Unit(
        id=1, subject_version_id="book-labels-test", ordinal=1,
        label_type="Chapter", detected_number="2",
        title="Proportion, Profit and Loss", start_page=25, end_page=45
    )
    # Header on page 32 says "Mathematics 27"
    node_header = ActivityNode(
        id=30, subject_version_id="book-labels-test", unit_id=1,
        node_type="generic_text", title=None,
        content_text="Mathematics 27\nProportion and Profit",
        page_number=32, ordinal=1
    )
    ex_node = ActivityNode(
        id=31, subject_version_id="book-labels-test", unit_id=1,
        node_type="exercise", title="Exercise",
        content_text="Exercise 2.1\n1. If a shopkeeper...",
        page_number=32, ordinal=2
    )
    # Neighbor header on page 33 confirms sequence ("28 Proportion")
    node_neighbor = ActivityNode(
        id=32, subject_version_id="book-labels-test", unit_id=1,
        node_type="generic_text", title=None,
        content_text="28 Proportion, Profit and Loss\nExample 5",
        page_number=33, ordinal=1
    )
    u.lessons = []
    u.activity_nodes = [node_header, ex_node, node_neighbor]
    v.units = [u]

    toc_items, source = build_textbook_toc(v)
    assert len(toc_items) == 1
    ch2 = toc_items[0]
    assert ch2.children is not None
    ex_item = next(c for c in ch2.children if c.label == "Exercise 2.1")

    # Verify physical PDF page is 32 (used by browser for #page=32)
    assert ex_item.pdf_page_number == 32
    assert ex_item.page_number == 32

    # Verify human-visible book page label is "27"
    assert ex_item.book_page_label == "27"


def test_body_question_numbers_rejected_as_page_labels():
    # 14. Body question numbers like "27. Solve..." are not misclassified as page numbers
    from app.services.pdf.toc_service import build_book_page_map
    
    question_node = ActivityNode(
        id=40, subject_version_id="test", unit_id=1,
        node_type="exercise", title="Exercise",
        content_text="27. What is the number if 5 is added?\n28. Find the value of x.",
        page_number=35, ordinal=1
    )
    page_map = build_book_page_map({35: [question_node]}, total_pages=50)
    # Without running headers, question numbers 27/28 should not create a fake page label
    assert page_map.get(35) is None

