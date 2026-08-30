from fastapi import APIRouter
from app.api.v1.endpoints import health, textbooks, assessments, question_bank, saved_papers, grades, subjects

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(grades.router)
api_router.include_router(subjects.router, prefix="/subjects", tags=["Subjects"])
api_router.include_router(textbooks.router)
api_router.include_router(assessments.router)
api_router.include_router(question_bank.router)
api_router.include_router(saved_papers.router)
