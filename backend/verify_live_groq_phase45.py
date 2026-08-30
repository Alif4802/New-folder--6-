import asyncio
import logging
import time
from sqlalchemy import select
from app.core.database import AsyncSessionFactory
from app.models.textbook import CurriculumNode, SubjectVersion
from app.schemas.assessment import MCQGenerateRequest
from app.services.assessment.generator import MCQGeneratorService
from app.services.llm.groq_provider import GroqProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def run_live_groq_suite():
    print("=== LIVE GROQ GENERATION VERIFICATION SUITE ===", flush=True)
    provider = GroqProvider()
    print(f"Groq Provider Model: {provider.model}", flush=True)
    print(f"Groq Provider Configured: {provider.is_configured}", flush=True)

    async with AsyncSessionFactory() as session:
        # 1. Fetch Class 7 Math textbook
        v = (await session.execute(
            select(SubjectVersion).where(SubjectVersion.page_count == 198)
        )).scalar_one()
        print(f"Loaded Textbook: {v.title} (ID: {v.id})", flush=True)

        nodes = (await session.execute(
            select(CurriculumNode).where(CurriculumNode.subject_version_id == v.id).order_by(CurriculumNode.ordinal)
        )).scalars().all()
        node_map = {n.source_label: n for n in nodes}

        sec11 = next((n for n in nodes if n.source_label == "1.1"), None)
        ch1 = next((n for n in nodes if n.source_label == "Chapter 1"), None)
        ch3 = next((n for n in nodes if n.source_label == "Chapter 3"), None)
        ch4 = next((n for n in nodes if n.source_label == "Chapter 4"), None)

        results = {}

        # -------------------------------------------------------------
        # TEST A: Single Small Subsection (5 MCQs from Section 1.1)
        # -------------------------------------------------------------
        print("\n--- RUNNING TEST A: Single Small Subsection (Section 1.1, 5 MCQs) ---", flush=True)
        t0 = time.time()
        req_a = MCQGenerateRequest(
            subject_version_id=v.id,
            scope_node_ids=[sec11.id],
            count=5,
        )
        try:
            res_a = await MCQGeneratorService.generate_mcqs(session, req_a, provider=provider)
            dur_a = time.time() - t0
            print(f"TEST A SUCCESS in {dur_a:.2f}s!", flush=True)
            print(f"Requested: 5 | Generated: {res_a.generated_count}", flush=True)
            print(f"Scope Title: {res_a.scope.scope_title}", flush=True)
            print(f"Q1: {res_a.questions[0].question_text}", flush=True)
            print(f"A1: Option {res_a.answer_key[0].correct_letter} - {res_a.answer_key[0].correct_text}", flush=True)
            results["TEST_A"] = {"status": "PASS", "count": res_a.generated_count, "time": dur_a}
        except Exception as e:
            print(f"TEST A FAILED: {e}", flush=True)
            results["TEST_A"] = {"status": "FAIL", "error": str(e)}

        # Safe rate spacing
        await asyncio.sleep(2.0)

        # -------------------------------------------------------------
        # TEST B: Whole Chapter 4 (5 MCQs - 22-page Chapter!)
        # -------------------------------------------------------------
        print("\n--- RUNNING TEST B: Whole Chapter 4 (22 Pages, 5 MCQs - Windowed) ---", flush=True)
        t0 = time.time()
        req_b = MCQGenerateRequest(
            subject_version_id=v.id,
            scope_node_ids=[ch4.id],
            count=5,
        )
        try:
            res_b = await MCQGeneratorService.generate_mcqs(session, req_b, provider=provider)
            dur_b = time.time() - t0
            print(f"TEST B SUCCESS in {dur_b:.2f}s!", flush=True)
            print(f"Requested: 5 | Generated: {res_b.generated_count}", flush=True)
            print(f"Scope Title: {res_b.scope.scope_title}", flush=True)
            print(f"Q1: {res_b.questions[0].question_text}", flush=True)
            print(f"A1: Option {res_b.answer_key[0].correct_letter} - {res_b.answer_key[0].correct_text}", flush=True)
            results["TEST_B"] = {"status": "PASS", "count": res_b.generated_count, "time": dur_b}
        except Exception as e:
            print(f"TEST B FAILED: {e}", flush=True)
            results["TEST_B"] = {"status": "FAIL", "error": str(e)}

        await asyncio.sleep(2.0)

        # -------------------------------------------------------------
        # TEST C: Multi-Scope (Chapter 1 + Chapter 3, 5 MCQs)
        # -------------------------------------------------------------
        print("\n--- RUNNING TEST C: Multi-Scope (Chapter 1 + Chapter 3, 5 MCQs) ---", flush=True)
        t0 = time.time()
        req_c = MCQGenerateRequest(
            subject_version_id=v.id,
            scope_node_ids=[ch1.id, ch3.id],
            count=5,
        )
        try:
            res_c = await MCQGeneratorService.generate_mcqs(session, req_c, provider=provider)
            dur_c = time.time() - t0
            print(f"TEST C SUCCESS in {dur_c:.2f}s!", flush=True)
            print(f"Requested: 5 | Generated: {res_c.generated_count}", flush=True)
            print(f"Scope Title: {res_c.scope.scope_title}", flush=True)
            print(f"Q1: {res_c.questions[0].question_text}", flush=True)
            print(f"A1: Option {res_c.answer_key[0].correct_letter} - {res_c.answer_key[0].correct_text}", flush=True)
            results["TEST_C"] = {"status": "PASS", "count": res_c.generated_count, "time": dur_c}
        except Exception as e:
            print(f"TEST C FAILED: {e}", flush=True)
            results["TEST_C"] = {"status": "FAIL", "error": str(e)}

        await asyncio.sleep(2.0)

        # -------------------------------------------------------------
        # TEST D: 12 MCQs from Multi-Chapter Scope
        # -------------------------------------------------------------
        print("\n--- RUNNING TEST D: 12 MCQs from Multi-Chapter Scope (Chapter 1, 4, 5) ---", flush=True)
        ch5 = next((n for n in nodes if n.source_label == "Chapter 5"), None)
        t0 = time.time()
        req_d = MCQGenerateRequest(
            subject_version_id=v.id,
            scope_node_ids=[ch1.id, ch4.id, ch5.id],
            count=12,
        )
        try:
            res_d = await MCQGeneratorService.generate_mcqs(session, req_d, provider=provider)
            dur_d = time.time() - t0
            print(f"TEST D SUCCESS in {dur_d:.2f}s!", flush=True)
            print(f"Requested: 12 | Generated: {res_d.generated_count}", flush=True)
            print(f"Scope Title: {res_d.scope.scope_title}", flush=True)
            results["TEST_D"] = {"status": "PASS", "count": res_d.generated_count, "time": dur_d}
        except Exception as e:
            print(f"TEST D FAILED: {e}", flush=True)
            results["TEST_D"] = {"status": "FAIL", "error": str(e)}

        await asyncio.sleep(2.0)

        # -------------------------------------------------------------
        # TEST E: 20 MCQs from Broad Multi-Chapter Scope
        # -------------------------------------------------------------
        print("\n--- RUNNING TEST E: 20 MCQs from Broad Multi-Chapter Scope ---", flush=True)
        ch2 = next((n for n in nodes if n.source_label == "Chapter 2"), None)
        ch6 = next((n for n in nodes if n.source_label == "Chapter 6"), None)
        t0 = time.time()
        req_e = MCQGenerateRequest(
            subject_version_id=v.id,
            scope_node_ids=[ch1.id, ch2.id, ch3.id, ch4.id, ch5.id, ch6.id],
            count=20,
        )
        try:
            res_e = await MCQGeneratorService.generate_mcqs(session, req_e, provider=provider)
            dur_e = time.time() - t0
            print(f"TEST E SUCCESS in {dur_e:.2f}s!", flush=True)
            print(f"Requested: 20 | Generated: {res_e.generated_count}", flush=True)
            print(f"Scope Title: {res_e.scope.scope_title}", flush=True)
            results["TEST_E"] = {"status": "PASS", "count": res_e.generated_count, "time": dur_e}
        except Exception as e:
            print(f"TEST E FAILED: {e}", flush=True)
            results["TEST_E"] = {"status": "FAIL", "error": str(e)}

        print("\n=== SUMMARY OF LIVE GROQ TESTS ===", flush=True)
        for k, v in results.items():
            print(f"{k}: {v}", flush=True)

if __name__ == "__main__":
    asyncio.run(run_live_groq_suite())
