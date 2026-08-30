import asyncio
import io
import json
import pymupdf
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode
from app.services.reconstruction.config import get_reconstruction_rules
from app.services.reconstruction.layout_extractor import LayoutExtractor
from app.services.reconstruction.reconstructor import ReconstructionEngine
from app.services.reconstruction.math_normalizer import MathNormalizer
from app.services.reconstruction.table_detector import TableDetector
from app.schemas.readable import BlockType



async def audit_blocks():
    print("==================================================")
    print("SOURCE-FIDELITY COMPARISON OF 5 REPRESENTATIVE BLOCKS")
    print("==================================================")

    async with AsyncSessionFactory() as session:
        # Load Class 7 Mathematics version
        v_res = await session.execute(
            select(SubjectVersion).where(SubjectVersion.id == "a0a610c7-1432-4432-919d-63fd45ed9c54")
        )
        version = v_res.scalar_one_or_none()
        if not version:
            print("Class 7 Math not found in DB")
            return

        engine = ReconstructionEngine()

        # BLOCK 1: Explanatory Prose from Lesson 1.1 (Page 6)
        u1_res = await session.execute(select(Unit).where(Unit.subject_version_id == version.id).order_by(Unit.ordinal))
        units = u1_res.scalars().all()
        unit1 = units[0]

        l1_res = await session.execute(select(Lesson).where(Lesson.unit_id == unit1.id).order_by(Lesson.ordinal))
        lessons = l1_res.scalars().all()
        lesson1 = lessons[0]

        doc1 = await engine.get_readable_document(session, version.id, lesson_id=lesson1.id)
        print("\n--- BLOCK 1: Explanatory Prose ---")
        print(f"Scope: Lesson {lesson1.detected_number} (pages {doc1.start_page}-{doc1.end_page})")
        print(f"Layout Source: {doc1.layout_source}")
        print(f"Block 0: type={doc1.blocks[0].block_type}, text={repr(doc1.blocks[0].content_text)}")
        print(f"Source Pages: {doc1.blocks[0].source_pages}")
        print(f"Source Node IDs: {doc1.blocks[0].source_node_ids}")
        print(f"Source Regions: {doc1.blocks[0].source_regions}")

        # BLOCK 2: Heading / Subheading from Lesson 1.2 (Page 7)
        lesson2 = lessons[1]
        doc2 = await engine.get_readable_document(session, version.id, lesson_id=lesson2.id)
        print("\n--- BLOCK 2: Heading & Paragraphs ---")
        print(f"Scope: Lesson {lesson2.detected_number} (pages {doc2.start_page}-{doc2.end_page})")
        print(f"Layout Source: {doc2.layout_source}")
        for b in doc2.blocks[:3]:
            print(f"Block: type={b.block_type}, text={repr(b.content_text[:70])}, spans_count={len(b.spans or [])}")

        # BLOCK 3: Mathematical Geometry & Formula (from synthetic native math PDF)
        # Inspect synthetic math PDF spans
        rules = get_reconstruction_rules()
        norm = MathNormalizer(rules)

        from app.services.reconstruction.layout_extractor import LayoutSpan, LayoutLine
        # Pure geometry superscript
        s_base = LayoutSpan("x", 12.0, "Arial", 0, 72, 88, 80, 100, 72, 100)
        s_sup = LayoutSpan("2", 8.0, "Arial", 0, 81, 80, 87, 94, 81, 94)
        line_math = LayoutLine([s_base, s_sup], "x2", 72, 80, 87, 100, 100, 1, 12.0)
        norm_spans = norm.normalize_line_spans(line_math, 12.0)
        print("\n--- BLOCK 3: Math Geometry Superscript ---")
        print(f"Source raw spans: ['{s_base.text}' size={s_base.size} y={s_base.origin_y}, '{s_sup.text}' size={s_sup.size} y={s_sup.origin_y}]")
        print(f"Reconstructed Span: text='{norm_spans[0].text}', latex='{norm_spans[0].latex}', raw_text='{norm_spans[0].raw_text}'")

        # BLOCK 4: Table Block with Multi-Column Data
        detector = TableDetector(rules)
        t_spans = [
            LayoutSpan("Number", 11.0, "Arial", 0, 72, 100, 120, 112, 72, 112),
            LayoutSpan("Square", 11.0, "Arial", 0, 150, 100, 200, 112, 150, 112),
            LayoutSpan("Formula", 11.0, "Arial", 0, 250, 100, 320, 112, 250, 112),
        ]
        t_line1 = LayoutLine(t_spans, "Number  Square  Formula", 72, 100, 320, 112, 112, 2, 11.0)
        t_spans2 = [
            LayoutSpan("1", 11.0, "Arial", 0, 72, 120, 120, 132, 72, 132),
            LayoutSpan("1", 11.0, "Arial", 0, 150, 120, 200, 132, 150, 132),
            LayoutSpan("1 x 1 = 1", 11.0, "Arial", 0, 250, 120, 320, 132, 250, 132),
        ]
        t_line2 = LayoutLine(t_spans2, "1  1  1 x 1 = 1", 72, 120, 320, 132, 132, 2, 11.0)
        t_spans3 = [
            LayoutSpan("2", 11.0, "Arial", 0, 72, 140, 120, 152, 72, 152),
            LayoutSpan("4", 11.0, "Arial", 0, 150, 140, 200, 152, 150, 152),
            LayoutSpan("2 x 2 = 4", 11.0, "Arial", 0, 250, 140, 320, 152, 250, 152),
        ]
        t_line3 = LayoutLine(t_spans3, "2  4  2 x 2 = 4", 72, 140, 320, 152, 152, 2, 11.0)
        t_res = detector.detect_table_block([t_line1, t_line2, t_line3], drawings=[])
        print("\n--- BLOCK 4: Reconstructed Table ---")
        if t_res:
            t_rows, _, _ = t_res
            print(f"Total Table Rows: {len(t_rows)}")
            for r_idx, row in enumerate(t_rows):
                print(f"  Row {r_idx}: {[c.text for c in row.cells]}")

        # BLOCK 5: Worked Example from Class 7 Lesson 1.4 (Page 14)
        u_digit = units[1] if len(units) > 1 else None
        if u_digit:
            l_digit_res = await session.execute(select(Lesson).where(Lesson.unit_id == u_digit.id).order_by(Lesson.ordinal))
            l_digit = l_digit_res.scalars().all()[0]
            doc5 = await engine.get_readable_document(session, version.id, lesson_id=l_digit.id)
            print("\n--- BLOCK 5: Exercise & Practice Callout from Real Book (p.14) ---")
            ex_blocks = [b for b in doc5.blocks if b.block_type == BlockType.EXERCISE]
            if ex_blocks:
                print(f"Exercise Block: text={repr(ex_blocks[0].content_text[:100])}")
                print(f"Source Node IDs: {ex_blocks[0].source_node_ids}")
                print(f"Source Pages: {ex_blocks[0].source_pages}")


if __name__ == "__main__":
    asyncio.run(audit_blocks())
