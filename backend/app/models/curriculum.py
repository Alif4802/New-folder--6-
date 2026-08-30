from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Curriculum(Base):
    """Represents a regional or national educational curriculum authority."""

    __tablename__ = "curriculums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    authority: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    grades: Mapped[List["Grade"]] = relationship(
        "Grade", back_populates="curriculum", cascade="all, delete-orphan"
    )
    subjects: Mapped[List["Subject"]] = relationship(
        "Subject", back_populates="curriculum", cascade="all, delete-orphan"
    )
    subject_versions: Mapped[List["SubjectVersion"]] = relationship(
        "SubjectVersion", back_populates="curriculum"
    )


class Grade(Base):
    """Represents a discovered or defined class/grade level scoped to a curriculum."""

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    curriculum_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("curriculums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Unique constraint per curriculum
    __table_args__ = (
        UniqueConstraint("curriculum_id", "code", name="uq_grades_curriculum_code"),
    )

    # Relationships
    curriculum: Mapped["Curriculum"] = relationship("Curriculum", back_populates="grades")
    subject_versions: Mapped[List["SubjectVersion"]] = relationship(
        "SubjectVersion", back_populates="grade"
    )


class Subject(Base):
    """Represents an academic subject entity scoped to a curriculum."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    curriculum_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("curriculums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), default="GENERAL", nullable=False)  # LANGUAGE, STEM, GENERAL
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Unique constraint per curriculum
    __table_args__ = (
        UniqueConstraint("curriculum_id", "code", name="uq_subjects_curriculum_code"),
    )

    # Relationships
    curriculum: Mapped["Curriculum"] = relationship("Curriculum", back_populates="subjects")
    subject_versions: Mapped[List["SubjectVersion"]] = relationship(
        "SubjectVersion", back_populates="subject"
    )
