import pymupdf
import json
import asyncio
from pathlib import Path
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode
from app.services.reconstruction.config import get_reconstruction_rules
from app.services.reconstruction.layout_extractor import LayoutExtractor
from app.services.reconstruction.reconstructor import ReconstructionEngine


async def audit_stored_book():
    print("==================================================")
    print("REAL NCTB 198-PAGE MATHEMATICS TEXTBOOK AUDIT")
    print("==================================================")

    pdf_path = settings.STORAGE_ROOT / "pdfs/a0a610c7-1432-4432-919d-63fd45ed9c54.pdf"
    if not pdf_path.exists():
        print(f"ERROR: PDF file not found at {pdf_path}")
        return

    doc = pymupdf.open(str(pdf_path))
    print(f"PDF Source: {pdf_path.name}")
    print(f"Total Pages: {len(doc)}")
    print(f"PDF Metadata: {doc.metadata}")

    # Inspect all pages for native text vs scanned pages
    native_text_pages = []
    scanned_pages = []
    for p_num in range(1, len(doc) + 1):
        p = doc[p_num - 1]
        t = p.get_text().strip()
        if len(t) > 20:
            native_text_pages.append(p_num)
        else:
            scanned_pages.append(p_num)

    print(f"Native text pages count: {len(native_text_pages)}")
    print(f"Scanned / image-only pages count: {len(scanned_pages)}")
    if native_text_pages:
        print(f"Sample native text pages: {native_text_pages[:10]}")
    if scanned_pages:
        print(f"Sample scanned pages: {scanned_pages[:10]}")

    # Inspect DB records
    async with AsyncSessionFactory() as session:
        v_res = await session.execute(
            select(SubjectVersion).where(SubjectVersion.id == "a0a610c7-1432-4432-919d-63fd45ed9c54")
        )
        version = v_res.scalar_one_or_none()
        if not version:
            print("SubjectVersion a0a610c7-1432-4432-919d-63fd45ed9c54 not found in DB")
            return

        print(f"\nDB SubjectVersion Title: {version.title}")
        print(f"DB Ingestion Status: {version.ingestion_status}")
        print(f"DB Page Count: {version.page_count}")
        print(f"DB OCR Pages Count: {version.ocr_pages_count}")

        # Fetch units and lessons
        units_res = await session.execute(
            select(Unit).where(Unit.subject_version_id == version.id).order_by(Unit.ordinal)
        )
        units = units_res.scalars().all()
        print(f"\nTotal Units in DB: {len(units)}")
        for u in units[:5]:
            l_res = await session.execute(select(Lesson).where(Lesson.unit_id == u.id).order_by(Lesson.ordinal))
            lessons = l_res.scalars().all()
            print(f"  Unit {u.detected_number}: {u.title} (pages {u.start_page}-{u.end_page}) - {len(lessons)} lessons")
            for l in lessons[:3]:
                print(f"    Lesson {l.detected_number}: {l.title} (pages {l.start_page}-{l.end_page})")

        # Now test reconstruction for multiple lessons/units
        engine = ReconstructionEngine()

        for u in units[:3]:
            l_res = await session.execute(select(Lesson).where(Lesson.unit_id == u.id).order_by(Lesson.ordinal))
            lessons = l_res.scalars().all()
            for l in lessons[:2]:
                doc_res = await engine.get_readable_document(session, version.id, lesson_id=l.id)
                print(f"\n--- Readable Document for Lesson {l.detected_number}: '{l.title}' (p.{l.start_page}-{l.end_page}) ---")
                print(f"Layout Source: {doc_res.layout_source}")
                print(f"Warnings: {doc_res.warnings}")
                print(f"Total Blocks: {len(doc_res.blocks)}")
                for b in doc_res.blocks[:5]:
                    print(f"  [{b.block_type}] p.{b.source_pages}: {b.content_text[:80]}")
                    if b.spans:
                        math_spans = [s for s in b.spans if s.is_math]
                        if math_spans:
                            print(f"    -> Math spans ({len(math_spans)}): {[s.latex or s.raw_text for s in math_spans]}")

    doc.close()


if __name__ == "__main__":
    asyncio.run(audit_stored_book())
