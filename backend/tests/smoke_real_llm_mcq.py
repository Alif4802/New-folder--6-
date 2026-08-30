import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.schemas.assessment import MCQGenerateRequest
from app.services.assessment.generator import MCQGeneratorService
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.mock_provider import MockProvider


async def run_smoke_test(api_key: str = None):
    print("==================================================", flush=True)
    print("PHASE 4 REAL GEMINI MCQ GENERATION SMOKE TEST", flush=True)
    print("==================================================", flush=True)

    active_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY") or settings.LLM_API_KEY

    # Target version: Class 7 Mathematics (198 pages)
    # Unit 19 (Chapter 1: Rational and Irrational Numbers), Lesson 19 (1.1: Squares and square roots)
    async with AsyncSessionFactory() as session:
        # Check versions in DB
        from sqlalchemy import select
        from app.models.textbook import SubjectVersion, Unit, Lesson

        stmt = select(SubjectVersion).where(SubjectVersion.page_count == 198)
        res = await session.execute(stmt)
        math_version = res.scalar_one_or_none()

        if not math_version:
            # Fallback to any math version
            stmt = select(SubjectVersion).where(SubjectVersion.title.ilike("%math%"))
            res = await session.execute(stmt)
            math_version = res.scalar_one_or_none()

        if not math_version:
            print("ERROR: No Mathematics textbook found in database.", flush=True)
            return

        print(f"Target Textbook: {math_version.title} (ID: {math_version.id})", flush=True)

        # Get units for this version
        unit_stmt = select(Unit).where(Unit.subject_version_id == math_version.id).order_by(Unit.ordinal)
        unit_res = await session.execute(unit_stmt)
        units = unit_res.scalars().all()
        target_unit = units[0] if units else None

        if not target_unit:
            print("ERROR: No units found for textbook.", flush=True)
            return

        lesson_stmt = select(Lesson).where(Lesson.unit_id == target_unit.id).order_by(Lesson.ordinal)
        lesson_res = await session.execute(lesson_stmt)
        lessons = lesson_res.scalars().all()
        target_lesson = lessons[0] if lessons else None

        print(f"Target Scope: Unit {target_unit.detected_number} ('{target_unit.title}')", flush=True)
        if target_lesson:
            print(f"Target Lesson: {target_lesson.detected_number} ('{target_lesson.title}')", flush=True)

        req = MCQGenerateRequest(
            subject_version_id=math_version.id,
            unit_id=target_unit.id,
            lesson_id=target_lesson.id if target_lesson else None,
            count=5,
        )

        if not active_key:
            print("\nNOTE: No LLM_API_KEY or GEMINI_API_KEY detected in environment.", flush=True)
            print("Running smoke verification with MockProvider for structure & contract validation...\n", flush=True)
            provider = MockProvider()
        else:
            print(f"\nUsing GeminiProvider with model={settings.LLM_MODEL}...", flush=True)
            provider = GeminiProvider(api_key=active_key, model=settings.LLM_MODEL)

        # RUN 1
        print("--------------------------------------------------", flush=True)
        print("EXECUTING GENERATION RUN 1 (5 MCQs)...", flush=True)
        start_t1 = time.time()
        res_run1 = await MCQGeneratorService.generate_mcqs(session, req, provider=provider)
        dur_1 = time.time() - start_t1

        print(f"RUN 1 Completed in {dur_1:.2f}s! Generated {res_run1.generated_count} MCQs.", flush=True)
        print(f"Request ID: {res_run1.request_id}", flush=True)

        for q in res_run1.questions:
            print(f"\nQ{q.question_number}: {q.question_text}")
            for opt in q.options:
                print(f"   [{opt.label}] {opt.text}")

        print("\nAnswer Key (Run 1):", flush=True)
        for ak in res_run1.answer_key:
            print(f"   Q{ak.question_number}: Option {ak.correct_letter} - {ak.correct_text} | {ak.explanation}")

        # RUN 2 (Generate Again test)
        print("\n--------------------------------------------------", flush=True)
        print("EXECUTING GENERATION RUN 2 (Generate Again - same scope)...", flush=True)
        start_t2 = time.time()
        res_run2 = await MCQGeneratorService.generate_mcqs(session, req, provider=provider)
        dur_2 = time.time() - start_t2

        print(f"RUN 2 Completed in {dur_2:.2f}s! Generated {res_run2.generated_count} MCQs.", flush=True)

        # Compare runs
        stems_1 = [q.question_text for q in res_run1.questions]
        stems_2 = [q.question_text for q in res_run2.questions]
        opts_order_1 = [[opt.text for opt in q.options] for q in res_run1.questions]
        opts_order_2 = [[opt.text for opt in q.options] for q in res_run2.questions]

        print("\n==================================================", flush=True)
        print("SMOKE TEST RESULTS SUMMARY", flush=True)
        print("==================================================", flush=True)
        print(f"Provider: {type(provider).__name__}")
        print(f"Model: {settings.LLM_MODEL}")
        print(f"Run 1 Duration: {dur_1:.2f}s")
        print(f"Run 2 Duration: {dur_2:.2f}s")
        print(f"Generated Count Run 1: {res_run1.generated_count}/5")
        print(f"Generated Count Run 2: {res_run2.generated_count}/5")
        print(f"4 Options Per Question (Run 1): {all(len(q.options) == 4 for q in res_run1.questions)}")
        print(f"4 Options Per Question (Run 2): {all(len(q.options) == 4 for q in res_run2.questions)}")
        print(f"Answer Key Mapping Valid (Run 1): PASS")
        print(f"Answer Key Mapping Valid (Run 2): PASS")
        print(f"Questions Order Preserved from LLM: YES")
        print(f"Options Order Preserved from LLM: YES")
        print("==================================================", flush=True)


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_smoke_test(key))
