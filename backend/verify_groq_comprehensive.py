import asyncio
import logging
import time
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionFactory
from app.models.textbook import SubjectVersion, CurriculumNode
from app.schemas.assessment import MCQGenerateRequest
from app.services.assessment.generator import MCQGeneratorService
from app.services.assessment.resolver import ScopeCoverageResolver
from app.services.llm.groq_provider import GroqProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nctb.verify.groq")


async def run_comprehensive_groq_verification():
    print("==================================================", flush=True)
    print("PHASE 4.5 REAL GROQ VERIFICATION TEST SUITE", flush=True)
    print("==================================================", flush=True)

    provider = GroqProvider()
    print(f"Provider: GroqProvider | Model: {provider.model}", flush=True)
    print(f"Provider Configured: {provider.is_configured}", flush=True)

    # 1. Load Mathematics Class 7 SubjectVersion and its CurriculumNodes
    async with AsyncSessionFactory() as db:
        q = (
            select(SubjectVersion)
            .where(SubjectVersion.title.contains("Mathematics"), SubjectVersion.title.contains("Class 7"))
            .options(selectinload(SubjectVersion.curriculum_nodes))
        )
        res = await db.execute(q)
        version = res.scalar_one_or_none()
        if not version:
            print("ERROR: Mathematics Class 7 textbook not found in database!", flush=True)
            return

        print(f"Loaded Textbook: {version.title} (ID: {version.id})", flush=True)
        nodes_by_title = {n.title.strip(): n for n in version.curriculum_nodes}
        nodes_by_label = {n.source_label.strip() if n.source_label else "": n for n in version.curriculum_nodes}

        # ----------------------------------------------------
        # TEST A: Single Small Subsection (Section 1.1, 5 MCQs)
        # ----------------------------------------------------
        print("\n--- TEST A: Single Small Subsection (Section 1.1, 5 MCQs) ---", flush=True)
        sec_1_1 = None
        for n in version.curriculum_nodes:
            if "1.1" in (n.source_label or ""):
                sec_1_1 = n
                break

        if not sec_1_1:
            print("ERROR: Section 1.1 not found!", flush=True)
            return

        print(f"Target Scope: {sec_1_1.source_label}: {sec_1_1.title} (ID: {sec_1_1.id})", flush=True)

        req_a = MCQGenerateRequest(
            subject_version_id=version.id,
            scope_node_ids=[sec_1_1.id],
            count=5,
        )

        t0 = time.time()
        res_a = await MCQGeneratorService.generate_mcqs(db, req_a)
        t1 = time.time()

        if res_a.error:
            print(f"TEST A ERROR: {res_a.error}", flush=True)
        else:
            data_a = res_a.data
            print(f"TEST A RESULT: PASS in {t1 - t0:.2f}s", flush=True)
            print(f"  Requested: 5 | Generated: {data_a.generated_count}", flush=True)
            print(f"  Scope: {data_a.scope.scope_title}", flush=True)
            for i, q in enumerate(data_a.questions, 1):
                ak = next((a for a in data_a.answer_key if a.question_number == q.question_number), None)
                corr = f"Option {ak.correct_letter} ({ak.correct_text})" if ak else "Unknown"
                print(f"  Q{i}: {q.question_text[:80]}...")
                print(f"       -> Correct: {corr}")

        # ----------------------------------------------------
        # TEST B: Whole Chapter 4 (22 Pages, 5 MCQs - Windowed)
        # ----------------------------------------------------
        print("\n--- TEST B: Whole Chapter 4 (22 Pages, 5 MCQs - Windowed) ---", flush=True)
        ch_4 = None
        for n in version.curriculum_nodes:
            if "Chapter 4" in (n.source_label or "") or "Algebraic Expressions" in n.title:
                ch_4 = n
                break

        if not ch_4:
            print("ERROR: Chapter 4 not found!", flush=True)
            return

        print(f"Target Scope: {ch_4.source_label}: {ch_4.title} (Pages {ch_4.start_pdf_page}-{ch_4.end_pdf_page})", flush=True)

        req_b = MCQGenerateRequest(
            subject_version_id=version.id,
            scope_node_ids=[ch_4.id],
            count=5,
        )

        t0 = time.time()
        res_b = await MCQGeneratorService.generate_mcqs(db, req_b)
        t1 = time.time()

        if res_b.error:
            print(f"TEST B ERROR: {res_b.error}", flush=True)
        else:
            data_b = res_b.data
            print(f"TEST B RESULT: PASS in {t1 - t0:.2f}s", flush=True)
            print(f"  Requested: 5 | Generated: {data_b.generated_count}", flush=True)
            print(f"  Scope: {data_b.scope.scope_title}", flush=True)
            for i, q in enumerate(data_b.questions, 1):
                ak = next((a for a in data_b.answer_key if a.question_number == q.question_number), None)
                corr = f"Option {ak.correct_letter} ({ak.correct_text})" if ak else "Unknown"
                print(f"  Q{i}: {q.question_text[:80]}...")
                print(f"       -> Correct: {corr}")

        # ----------------------------------------------------
        # TEST C: Multi-Scope (Chapter 1 + Chapter 3, 5 MCQs)
        # ----------------------------------------------------
        print("\n--- TEST C: Multi-Scope (Chapter 1 + Chapter 3, 5 MCQs) ---", flush=True)
        ch_1 = next((n for n in version.curriculum_nodes if "Chapter 1" in (n.source_label or "")), None)
        ch_3 = next((n for n in version.curriculum_nodes if "Chapter 3" in (n.source_label or "")), None)

        if ch_1 and ch_3:
            print(f"Target Scopes: {ch_1.source_label} + {ch_3.source_label}", flush=True)
            req_c = MCQGenerateRequest(
                subject_version_id=version.id,
                scope_node_ids=[ch_1.id, ch_3.id],
                count=5,
            )

            t0 = time.time()
            res_c = await MCQGeneratorService.generate_mcqs(db, req_c)
            t1 = time.time()

            if res_c.error:
                print(f"TEST C ERROR: {res_c.error}", flush=True)
            else:
                data_c = res_c.data
                print(f"TEST C RESULT: PASS in {t1 - t0:.2f}s", flush=True)
                print(f"  Requested: 5 | Generated: {data_c.generated_count}", flush=True)
                print(f"  Scope: {data_c.scope.scope_title}", flush=True)
                for i, q in enumerate(data_c.questions, 1):
                    ak = next((a for a in data_c.answer_key if a.question_number == q.question_number), None)
                    corr = f"Option {ak.correct_letter} ({ak.correct_text})" if ak else "Unknown"
                    print(f"  Q{i}: {q.question_text[:80]}...")
                    print(f"       -> Correct: {corr}")


if __name__ == "__main__":
    asyncio.run(run_comprehensive_groq_verification())
