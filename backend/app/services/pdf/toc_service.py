import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict
import pymupdf

from app.core.config import settings
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode
from app.schemas.textbook import TOCItemResponse

logger = logging.getLogger("nctb.toc")


def clean_heading_text(text: str) -> str:
    """Clean corrupt tokens, unicode replacement characters, and normalize spaces and dashes."""
    if not text:
        return ""
    # Normalize special whitespace and hyphens
    s = text.replace("\u00a0", " ").replace("\u2013", " — ").replace("\u2014", " — ")
    # Remove unicode replacement char and control characters
    s = re.sub(r"[\ufffd\x00-\x1f\x7f-\x9f]", "", s)
    # Normalize multiple spaces and repeated punctuation
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"—\s*—+", "—", s)
    return s.strip()


def is_valid_unit_number(num_str: Optional[str], label_type: Optional[str]) -> bool:
    """Validate that unit number is a genuine structural identifier, not a malformed word/token."""
    if not num_str:
        return True
    s = num_str.strip().lower()
    lt = (label_type or "").strip().lower()
    if s == lt or s in ["part", "unit", "chapter", "section"]:
        return False

    invalid_words = {
        "is", "the", "and", "of", "to", "in", "for", "on", "with", "by", "from",
        "digit", "part", "unit", "chapter", "a", "an", "as", "at", "be", "this",
        "that", "which", "are", "was", "were", "or", "not", "equal", "dots", "filled"
    }
    if s in invalid_words:
        return False

    # Valid structural number forms: digits (1, 2, 12), roman (I, II, IV, V, X), single letter (A, B, C)
    if re.match(r"^(?:\d+|[IVXLCDM]+|[A-Za-z])$", num_str.strip(), re.IGNORECASE):
        return True

    return False


def is_valid_unit_title(title: str) -> bool:
    """Validate that unit title is a concise heading, not an instructional body sentence, number, or formula."""
    if not title:
        return False
    t = clean_heading_text(title)
    # Reject pure numbers or single words that are just digits
    if re.match(r"^\d+$", t.strip()):
        return False
    # Reject sentence fragments starting with conjunctions or prepositions
    if re.match(r"(?i)^(?:and|or|but|which|that|filled in|equal to|moving left|is|are)\b", t):
        return False
    if len(t) > 100:
        return False
    # Reject math formulas as unit titles
    if any(op in t for op in ["=", "+", "−", "*", "/"]) and re.search(r"[a-z]\s*=\s*[a-z0-9]", t, re.I):
        return False
    if len(t) <= 2:
        return False
    return True


def is_valid_lesson_title(title: str, num_str: Optional[str]) -> bool:
    """Validate that lesson title is a valid section heading, not a math equation or body question."""
    if not title:
        return False
    t = clean_heading_text(title)
    if re.match(r"(?i)^(?:and|or|but|which|that|is|are)\b", t):
        return False
    # Reject math equations detected as lesson titles (e.g. A=x2 + ...)
    if re.search(r"^[A-Za-z]\s*=\s*", t) or (any(c in t for c in ["=", "−"]) and len(t) < 30 and re.search(r"\d", t)):
        return False
    if len(t) > 120:
        return False
    return True


def extract_confident_exercise_label(
    node: ActivityNode,
    parent_unit_num: Optional[str] = None,
    doc: Optional[pymupdf.Document] = None,
) -> Optional[str]:
    """
    Extract exercise label with source fidelity.
    1. Check persisted node text/title for explicit numbered exercise (e.g. Exercise 1.1, Exercise 3).
    2. Check persisted node text for OCR centered dot patterns (e.g. Exercise 501 -> Exercise 5.1, Exercise 1002 -> Exercise 10.2).
    3. If generic 'Exercise' and doc is available, inspect source PDF page to recover exact numbered heading if present.
    4. Genuinely generic 'Exercise' preserved if heading is literally 'Exercise'.
    Never infers or synthesizes numbers.
    """
    raw_title = clean_heading_text(node.title or "")
    first_line = clean_heading_text(node.content_text.splitlines()[0] if node.content_text else "")

    # Reject raw question items or body questions incorrectly classified as exercises
    question_starters = [
        "creative question", "sample question", "short answer",
        "answer to the", "based on the", "in the figure", "find the value",
        "which is the", "what is the", "reducing a fraction", "secondary data",
        "if the", "when is it", "the lengths of", "simplify (", "evaluate",
        "condition hypotenuse", "show that", "estimate the value", "a stick of",
        "which one is", "what is the h.c.f", "what is the l.c.m", "the statistics of",
        "the weights", "dybisects", "similar triangles", "prove that", "solve :"
    ]
    if any(first_line.lower().startswith(q) for q in question_starters):
        if not re.match(r"(?i)^Exercise\b", first_line):
            return None

    # 1. Match specific standard numbered exercise (e.g. Exercise 1.1, Exercise 1, Exercise 10.2, Practice 2.1)
    m = re.search(
        r"(?i)\b(Exercise\s+\d{1,2}\.\d{1,2}|Practice\s+\d{1,2}\.\d{1,2}|Exercise\s+[A-Za-z]|Practice\s+Problems?\s*\d*)\b",
        first_line,
    )
    if not m:
        m = re.search(
            r"(?i)\b(Exercise\s+\d{1,2}\.\d{1,2}|Practice\s+\d{1,2}\.\d{1,2}|Exercise\s+[A-Za-z]|Practice\s+Problems?\s*\d*)\b",
            raw_title,
        )

    if m:
        cleaned = clean_heading_text(m.group(0))
        # Validate chapter prefix consistency if parent unit number is a digit
        ex_num_match = re.search(r"(\d+)(?:\.(\d+))?", cleaned)
        if ex_num_match and parent_unit_num and parent_unit_num.isdigit():
            ex_ch = ex_num_match.group(1)
            # If exercise has dot (e.g. 10.3) and chapter is 11, reject
            if ex_num_match.group(2) and ex_ch != parent_unit_num:
                return None
            if not ex_num_match.group(2) and ex_ch != parent_unit_num and abs(int(ex_ch) - int(parent_unit_num)) > 1:
                return None

        return cleaned

    # 2. Check for OCR centered dot separator artifact in persisted text (e.g. Exercise 501 -> Exercise 5.1, Exercise 1002 -> Exercise 10.2)
    content_sample = (node.content_text or "")[:400]
    for line in content_sample.splitlines():
        line_clean = line.strip()
        if "exercise" in line_clean.lower():
            m_ocr = re.search(r"(?i)\bExercise\s+(\d{1,2})[0.\-·•°\ufffd\s]+(\d{1,2})\b", line_clean)
            if m_ocr:
                ch, sub = m_ocr.group(1), m_ocr.group(2)
                if int(sub) <= 20:
                    if not parent_unit_num or not parent_unit_num.isdigit() or ch == parent_unit_num:
                        return f"Exercise {ch}.{sub}"

            # 3. Match single number Exercise N (e.g. Exercise 3, Exercise 8)
            m_single = re.search(r"(?i)\bExercise\s+(\d{1,2})\b", line_clean)
            if m_single:
                ch = m_single.group(1)
                if not parent_unit_num or not parent_unit_num.isdigit() or abs(int(ch) - int(parent_unit_num)) <= 1:
                    return f"Exercise {ch}"

    # 4. Genuinely unnumbered "Exercise" only if first line is explicitly a standalone heading
    if re.match(r"(?i)^Exercise\s*[:.\-—]?$", first_line) or raw_title.lower() in ["exercise", "exercises"]:
        if len(first_line) <= 15:
            return "Exercise"

    return None


def build_book_page_map(nodes_by_page: Dict[int, List[ActivityNode]], total_pages: int) -> Dict[int, str]:
    """
    Build a complete, verified mapping from physical PDF page number (1-indexed)
    to printed textbook page label string (e.g. "27", "125", "1").
    Enforces sequential consistency and neighbor evidence with zero fixed offsets.
    """
    raw_detected: Dict[int, int] = {}

    for p in range(1, total_pages + 1):
        p_nodes = nodes_by_page.get(p, [])
        if not p_nodes:
            continue

        header_lines = []
        for n in p_nodes[:2]:
            if n.content_text:
                lines = [l.strip() for l in n.content_text.splitlines() if l.strip()]
                header_lines.extend(lines[:3])

        for line in header_lines:
            # Match "Mathematics 27" or "Algebraic Fractions 106"
            m1 = re.search(r"(?i)\b(?:[A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})\s+(\d{1,3})\b", line)
            if m1:
                val = int(m1.group(1))
                if not re.search(r"(?i)\b(example|question|exercise|figure|forma|class|part|unit|chapter|activity|step)\b", line):
                    if 1 <= val <= total_pages:
                        raw_detected[p] = val
                        break

            # Match "28 Proportion, Profit and Loss" or "2 Mathematics"
            m2 = re.search(r"^(\d{1,3})\s+[A-Z][a-z]+", line)
            if m2:
                val = int(m2.group(1))
                if not re.search(r"(?i)\b(example|question|exercise|figure|forma|class|part|unit|chapter|activity|step)\b", line):
                    if 1 <= val <= total_pages:
                        raw_detected[p] = val
                        break

    # Pass 1: Keep only points that are sequentially verified with neighbors
    confirmed: Dict[int, int] = {}
    for p, val in raw_detected.items():
        is_valid = any(
            (p + delta in raw_detected and raw_detected[p + delta] == val + delta)
            for delta in [-3, -2, -1, 1, 2, 3]
        )
        if is_valid:
            confirmed[p] = val

    # Pass 2: Iterative neighbor propagation for chapter start pages and unnumbered pages
    for _ in range(4):
        for p in range(1, total_pages + 1):
            if p not in confirmed:
                if p + 1 in confirmed and p + 2 in confirmed and confirmed[p + 2] == confirmed[p + 1] + 1:
                    val = confirmed[p + 1] - 1
                    if val >= 1:
                        confirmed[p] = val
                elif p - 1 in confirmed and p - 2 in confirmed and confirmed[p - 1] == confirmed[p - 2] + 1:
                    val = confirmed[p - 1] + 1
                    if val <= total_pages:
                        confirmed[p] = val

    return {p: str(v) for p, v in confirmed.items()}


def extract_usable_pdf_bookmarks(
    stored_pdf_path: Optional[str], page_count: int
) -> Optional[List[TOCItemResponse]]:
    """
    Inspect embedded PDF bookmarks/outline using PyMuPDF (doc.get_toc()).
    Returns a client-safe TOC hierarchy if the PDF outline is genuine and usable.
    Rejects print press signature sheets (e.g. Forma-1, Cover, Inner).
    """
    if not stored_pdf_path:
        return None

    pdf_path = Path(stored_pdf_path)
    if not pdf_path.is_absolute():
        pdf_path = settings.STORAGE_ROOT / pdf_path

    if not pdf_path.exists():
        return None

    doc = None
    try:
        doc = pymupdf.open(pdf_path)
        raw_toc = doc.get_toc()
    except Exception as e:
        logger.warning(f"Could not read PDF outline from {pdf_path}: {e}")
        return None

    if not raw_toc or len(raw_toc) < 2:
        if doc:
            doc.close()
        return None

    # Filter out print vendor form signatures (e.g. Forma-1, Forma-2, Cover, Plates)
    forma_matches = sum(
        1 for item in raw_toc if re.search(r"(?i)\b(forma|cover|inner|plate|blank)\b", item[1])
    )
    if forma_matches / len(raw_toc) > 0.4:
        logger.info(
            f"PDF outline contains print press signature sheets ({forma_matches}/{len(raw_toc)}), falling back to parsed curriculum."
        )
        if doc:
            doc.close()
        return None

    # Process valid outline tree
    max_pages = page_count if page_count > 0 else 9999
    root_items: List[TOCItemResponse] = []
    level_map = {}

    page_labels = []
    try:
        if doc and hasattr(doc, "get_page_labels"):
            page_labels = doc.get_page_labels() or []
    except Exception:
        pass

    for entry in raw_toc:
        lvl, title, page_num = entry[0], clean_heading_text(entry[1]), entry[2]
        if not (1 <= page_num <= max_pages) or not title:
            continue

        item_type = "unit" if lvl == 1 else "lesson"
        if re.search(r"(?i)\b(exercise|practice)\b", title):
            item_type = "exercise"

        book_label = None
        if page_labels and 1 <= page_num <= len(page_labels):
            book_label = page_labels[page_num - 1]

        item = TOCItemResponse(
            type=item_type,
            label=title,
            number=None,
            page_number=page_num,
            pdf_page_number=page_num,
            book_page_label=book_label,
            children=None,
        )

        if lvl == 1:
            root_items.append(item)
            level_map[1] = item
        elif lvl == 2 and 1 in level_map:
            parent = level_map[1]
            if parent.children is None:
                parent.children = []
            parent.children.append(item)
            level_map[2] = item
        elif lvl == 3 and 2 in level_map:
            parent = level_map[2]
            if parent.children is None:
                parent.children = []
            parent.children.append(item)
            level_map[3] = item

    if doc:
        doc.close()

    if root_items:
        return root_items

    return None


def build_textbook_toc(version: SubjectVersion) -> Tuple[List[TOCItemResponse], str]:
    """
    Build clean, high-confidence Table of Contents for dynamic PDF navigation.
    Source priority:
    1. Valid embedded PDF outline/bookmarks (if structurally useful)
    2. High-confidence persisted curriculum structure (Units, Lessons, Exercises)
    """
    # 1. Attempt embedded PDF bookmarks
    pdf_toc = extract_usable_pdf_bookmarks(version.stored_pdf_path, version.page_count)
    if pdf_toc:
        logger.info(f"Using EMBEDDED_PDF bookmarks for textbook version {version.id}")
        return pdf_toc, "EMBEDDED_PDF"

    # 2. Fall back to parsed curriculum hierarchy with Quality Gate
    logger.info(f"Using PARSED_CURRICULUM with Quality Gate for textbook version {version.id}")
    max_pages = version.page_count if version.page_count > 0 else 9999
    valid_units: List[Unit] = []
    orphaned_lessons: List[Lesson] = []

    # Optional PyMuPDF doc handle for source fidelity checks
    doc = None
    if version.stored_pdf_path:
        pdf_path = Path(version.stored_pdf_path)
        if not pdf_path.is_absolute():
            pdf_path = settings.STORAGE_ROOT / pdf_path
        if pdf_path.exists():
            try:
                doc = pymupdf.open(pdf_path)
            except Exception as e:
                logger.debug(f"Could not open PDF for source heading recovery: {e}")

    try:
        # Build printed textbook page mapping from page node headers
        nodes_by_page: Dict[int, List[ActivityNode]] = {}
        for u in version.units:
            for node in u.activity_nodes:
                nodes_by_page.setdefault(node.page_number, []).append(node)
            for l in u.lessons:
                for node in l.activity_nodes:
                    nodes_by_page.setdefault(node.page_number, []).append(node)

        book_page_map = build_book_page_map(nodes_by_page, max_pages)

        # Pass 1: Filter units with Quality Gate
        for u in sorted(version.units, key=lambda x: x.ordinal):
            if not (1 <= u.start_page <= max_pages):
                continue

            if not is_valid_unit_number(u.detected_number, u.label_type):
                logger.debug(f"Rejecting malformed unit number '{u.detected_number}' ('{u.title}')")
                # Collect any child lessons for possible adoption
                orphaned_lessons.extend(u.lessons)
                continue

            if not is_valid_unit_title(u.title):
                logger.debug(f"Rejecting malformed unit title '{u.title}'")
                orphaned_lessons.extend(u.lessons)
                continue

            valid_units.append(u)

        toc_items: List[TOCItemResponse] = []

        # Pass 2: Assemble Chapters, Lessons, and Exercises
        for u in valid_units:
            unit_label = clean_heading_text(u.title)
            if u.detected_number:
                prefix_check = f"{u.detected_number}".lower()
                if not u.title.lower().startswith(f"chapter {prefix_check}") and not u.title.lower().startswith(f"unit {prefix_check}"):
                    unit_label = f"{u.label_type or 'Chapter'} {u.detected_number} — {clean_heading_text(u.title)}"

            unit_children: List[TOCItemResponse] = []

            # Combine unit's own lessons and any valid adopted lessons
            combined_lessons = list(u.lessons)
            # Adopt orphaned lessons if their detected_number or page range matches this unit
            for o_less in orphaned_lessons:
                if 1 <= o_less.start_page <= max_pages:
                    if u.detected_number and o_less.detected_number and o_less.detected_number.startswith(f"{u.detected_number}."):
                        if o_less not in combined_lessons:
                            combined_lessons.append(o_less)

            for l in sorted(combined_lessons, key=lambda x: (x.start_page, x.ordinal)):
                if not (1 <= l.start_page <= max_pages):
                    continue

                if not is_valid_lesson_title(l.title, l.detected_number):
                    logger.debug(f"Rejecting malformed lesson title '{l.title}'")
                    continue

                lesson_label = clean_heading_text(l.title)
                if l.detected_number and not l.title.startswith(str(l.detected_number)):
                    lesson_label = f"{l.detected_number} {clean_heading_text(l.title)}"

                lesson_children: List[TOCItemResponse] = []
                seen_exercises: Set[Tuple[str, int]] = set()

                for node in sorted(l.activity_nodes, key=lambda x: (x.page_number, x.ordinal)):
                    if 1 <= node.page_number <= max_pages:
                        ex_label = extract_confident_exercise_label(node, u.detected_number, doc=doc)
                        if ex_label:
                            key = (ex_label.lower(), node.page_number)
                            if key not in seen_exercises:
                                seen_exercises.add(key)
                                lesson_children.append(
                                    TOCItemResponse(
                                        type="exercise",
                                        label=ex_label,
                                        number=None,
                                        page_number=node.page_number,
                                        pdf_page_number=node.page_number,
                                        book_page_label=book_page_map.get(node.page_number),
                                        children=None,
                                    )
                                )

                unit_children.append(
                    TOCItemResponse(
                        type="lesson",
                        label=lesson_label,
                        number=l.detected_number,
                        page_number=l.start_page,
                        pdf_page_number=l.start_page,
                        book_page_label=book_page_map.get(l.start_page),
                        children=lesson_children if lesson_children else None,
                    )
                )

            # Direct unit-level exercises
            seen_unit_exercises: Set[Tuple[str, int]] = set()
            for node in sorted(u.activity_nodes, key=lambda x: (x.page_number, x.ordinal)):
                if node.lesson_id is None and 1 <= node.page_number <= max_pages:
                    ex_label = extract_confident_exercise_label(node, u.detected_number, doc=doc)
                    if ex_label:
                        key = (ex_label.lower(), node.page_number)
                        if key not in seen_unit_exercises:
                            seen_unit_exercises.add(key)
                            unit_children.append(
                                TOCItemResponse(
                                    type="exercise",
                                    label=ex_label,
                                    number=None,
                                    page_number=node.page_number,
                                    pdf_page_number=node.page_number,
                                    book_page_label=book_page_map.get(node.page_number),
                                    children=None,
                                )
                            )

            # Sort unit children by page_number deterministically
            unit_children.sort(key=lambda item: item.page_number)

            toc_items.append(
                TOCItemResponse(
                    type="unit",
                    label=unit_label,
                    number=u.detected_number,
                    page_number=u.start_page,
                    pdf_page_number=u.start_page,
                    book_page_label=book_page_map.get(u.start_page),
                    children=unit_children if unit_children else None,
                )
            )

        # Sort root TOC items by page_number
        toc_items.sort(key=lambda item: item.page_number)
        return toc_items, "PARSED_CURRICULUM"
    finally:
        if doc:
            try:
                doc.close()
            except Exception:
                pass
