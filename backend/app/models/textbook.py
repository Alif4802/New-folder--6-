from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubjectVersion(Base):
    """Represents a specific edition or version of an ingested textbook."""

    __tablename__ = "subject_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID4 string
    curriculum_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("curriculums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    grade_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("grades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    edition_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    edition_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    publication_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_pdf_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ingestion_status: Mapped[str] = mapped_column(
        String(50), default="PENDING", nullable=False, index=True
    )  # PENDING, PROCESSING, COMPLETED, PARTIAL, FAILED
    ocr_pages_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    curriculum_parser_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    curriculum_built_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    curriculum_quality_status: Mapped[str] = mapped_column(
        String(50), default="UNASSESSED", nullable=False, index=True
    )  # UNASSESSED, VALID, NEEDS_REFRESH, BUILDING, FAILED
    metadata_status: Mapped[str] = mapped_column(
        String(50), default="UNASSESSED", nullable=False, index=True
    )  # UNASSESSED, VALID, NEEDS_REVIEW, USER_CONFIRMED
    metadata_resolver_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    detected_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    warnings: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    curriculum: Mapped["Curriculum"] = relationship("Curriculum", back_populates="subject_versions")
    subject: Mapped[Optional["Subject"]] = relationship("Subject", back_populates="subject_versions")
    grade: Mapped[Optional["Grade"]] = relationship("Grade", back_populates="subject_versions")
    units: Mapped[List["Unit"]] = relationship(
        "Unit", back_populates="subject_version", cascade="all, delete-orphan", order_by="Unit.ordinal"
    )
    curriculum_nodes: Mapped[List["CurriculumNode"]] = relationship(
        "CurriculumNode", back_populates="subject_version", cascade="all, delete-orphan", order_by="CurriculumNode.ordinal"
    )
    activity_nodes: Mapped[List["ActivityNode"]] = relationship(
        "ActivityNode", back_populates="subject_version", cascade="all, delete-orphan", order_by="ActivityNode.ordinal"
    )


class CurriculumNode(Base):
    """
    Generic, source-defined curriculum hierarchy node supporting arbitrary depths
    (e.g. Chapter -> Section -> Exercise, Unit -> Lesson -> Activity -> Task, Part -> Chapter...).
    """

    __tablename__ = "curriculum_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Prefix ID: e.g. "cnode_..."
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    node_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # chapter, unit, lesson, section, topic, exercise, activity, task, part, practice, other
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "Chapter 1", "Unit 1", "Lesson 1.1"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_pdf_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_pdf_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    subject_version: Mapped["SubjectVersion"] = relationship("SubjectVersion", back_populates="curriculum_nodes")
    parent: Mapped[Optional["CurriculumNode"]] = relationship(
        "CurriculumNode", remote_side=[id], back_populates="children"
    )
    children: Mapped[List["CurriculumNode"]] = relationship(
        "CurriculumNode", back_populates="parent", cascade="all, delete-orphan", order_by="CurriculumNode.ordinal"
    )
    activity_nodes: Mapped[List["ActivityNode"]] = relationship(
        "ActivityNode", back_populates="curriculum_node"
    )


class Unit(Base):
    """Legacy Unit table preserved for database backward compatibility."""

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_number: Mapped[str] = mapped_column(String(50), nullable=False)
    label_type: Mapped[str] = mapped_column(String(50), default="Unit", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    subject_version: Mapped["SubjectVersion"] = relationship("SubjectVersion", back_populates="units")
    lessons: Mapped[List["Lesson"]] = relationship(
        "Lesson", back_populates="unit", cascade="all, delete-orphan", order_by="Lesson.ordinal"
    )
    activity_nodes: Mapped[List["ActivityNode"]] = relationship(
        "ActivityNode", back_populates="unit", cascade="all, delete-orphan", order_by="ActivityNode.ordinal"
    )


class Lesson(Base):
    """Legacy Lesson table preserved for database backward compatibility."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    unit: Mapped["Unit"] = relationship("Unit", back_populates="lessons")
    activity_nodes: Mapped[List["ActivityNode"]] = relationship(
        "ActivityNode", back_populates="lesson", cascade="all, delete-orphan", order_by="ActivityNode.ordinal"
    )


class ActivityNode(Base):
    """Atomic structured textbook content element with source traceability."""

    __tablename__ = "activity_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True, index=True
    )
    curriculum_node_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("curriculum_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bounding_box: Mapped[Optional[Dict[str, float]]] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    parser_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    subject_version: Mapped["SubjectVersion"] = relationship("SubjectVersion", back_populates="activity_nodes")
    unit: Mapped["Unit"] = relationship("Unit", back_populates="activity_nodes")
    lesson: Mapped[Optional["Lesson"]] = relationship("Lesson", back_populates="activity_nodes")
    curriculum_node: Mapped[Optional["CurriculumNode"]] = relationship("CurriculumNode", back_populates="activity_nodes")
