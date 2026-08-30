from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QuestionBankItem(Base):
    """
    Persistent canonical Question Bank item.
    Stores validated, reusable assessment questions independent of presentation arrangement.
    """

    __tablename__ = "question_bank_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Prefix ID: e.g. "qbi_..."
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_type: Mapped[str] = mapped_column(
        String(50), default="MCQ", nullable=False, index=True
    )  # MCQ, future extensibility
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_latex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # EASY, MEDIUM, HARD
    marks: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    origin_type: Mapped[str] = mapped_column(
        String(50), default="AI_GENERATED", nullable=False
    )  # AI_GENERATED, TEACHER_AUTHORED
    grounding_source: Mapped[str] = mapped_column(
        String(50), default="OFFICIAL_NCTB", nullable=False
    )  # OFFICIAL_NCTB, BANGLADESH_BOARD, SCHOOL_SUMMATIVE, MODEL_TEST, TEACHER_AUTHORED, LICENSED_REFERENCE, OTHER_AUTHORIZED
    status: Mapped[str] = mapped_column(
        String(50), default="ACTIVE", nullable=False, index=True
    )  # ACTIVE, ARCHIVED
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    correct_option_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("question_bank_options.id", name="fk_qbi_correct_option_id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    generation_request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    generation_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    generation_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_profile_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("subject_version_id", "question_type", "content_hash", name="uq_question_bank_items_hash"),
    )

    # Relationships
    subject_version = relationship("SubjectVersion")
    options: Mapped[List["QuestionBankOption"]] = relationship(
        "QuestionBankOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionBankOption.canonical_order",
        foreign_keys="QuestionBankOption.question_id",
    )
    scopes: Mapped[List["QuestionBankItemScope"]] = relationship(
        "QuestionBankItemScope",
        back_populates="question_bank_item",
        cascade="all, delete-orphan",
    )
    provenances: Mapped[List["QuestionBankItemProvenance"]] = relationship(
        "QuestionBankItemProvenance",
        back_populates="question_bank_item",
        cascade="all, delete-orphan",
    )
    set_items: Mapped[List["QuestionSetItem"]] = relationship(
        "QuestionSetItem",
        back_populates="question_bank_item",
    )


class QuestionBankOption(Base):
    """
    Normalized option entity with stable persistent identity.
    Canonical order preserves normalized storage, while presentation order is managed in question sets.
    """

    __tablename__ = "question_bank_options"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Prefix ID: e.g. "opt_..."
    question_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("question_bank_items.id", name="fk_qbo_question_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_latex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical_order: Mapped[int] = mapped_column(Integer, nullable=False)  # 0, 1, 2, 3
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("question_id", "canonical_order", name="uq_question_bank_options_canonical_order"),
    )

    # Relationships
    question: Mapped["QuestionBankItem"] = relationship(
        "QuestionBankItem",
        back_populates="options",
        foreign_keys=[question_id],
    )


class QuestionBankItemScope(Base):
    """Many-to-many relationship linking a QuestionBankItem to generic CurriculumNodes."""

    __tablename__ = "question_bank_item_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_bank_item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("question_bank_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    curriculum_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint("question_bank_item_id", "curriculum_node_id", name="uq_qbi_scopes_item_node"),
    )

    # Relationships
    question_bank_item: Mapped["QuestionBankItem"] = relationship(
        "QuestionBankItem",
        back_populates="scopes",
    )
    curriculum_node = relationship("CurriculumNode")


class QuestionBankItemProvenance(Base):
    """
    Stable provenance record for a QuestionBankItem.
    Stores translated internal references (SubjectVersion, CurriculumNode, ActivityNode, pages)
    without persisting ephemeral request-local identifiers like SRC-001.
    """

    __tablename__ = "question_bank_item_provenances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_bank_item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("question_bank_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    curriculum_node_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("curriculum_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activity_node_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("activity_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_content_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    question_bank_item: Mapped["QuestionBankItem"] = relationship(
        "QuestionBankItem",
        back_populates="provenances",
    )
    curriculum_node = relationship("CurriculumNode")
    activity_node = relationship("ActivityNode")


class QuestionSet(Base):
    """
    Persistent Saved Paper / Question Set entity.
    Stores ordered collections of QuestionBankItems with paper metadata.
    """

    __tablename__ = "question_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Prefix ID: e.g. "qset_..."
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subject_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subject_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    set_type: Mapped[str] = mapped_column(
        String(50), default="QUESTION_PAPER", nullable=False
    )  # QUESTION_PAPER, EXAM_PAPER, CUSTOM_COLLECTION, CHAPTER_BUNDLE
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paper_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="ACTIVE", nullable=False, index=True
    )  # ACTIVE, ARCHIVED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    subject_version = relationship("SubjectVersion")
    items: Mapped[List["QuestionSetItem"]] = relationship(
        "QuestionSetItem",
        back_populates="question_set",
        cascade="all, delete-orphan",
        order_by="QuestionSetItem.question_order",
    )
    scopes: Mapped[List["QuestionSetScope"]] = relationship(
        "QuestionSetScope",
        back_populates="question_set",
        cascade="all, delete-orphan",
    )


class QuestionSetItem(Base):
    """
    Ordered question reference within a QuestionSet.
    Maintains presentation option order snapshot so papers reopen in exact saved arrangement.
    """

    __tablename__ = "question_set_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Prefix ID: e.g. "qsi_..."
    set_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_bank_item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("question_bank_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    question_order: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..N
    option_order: Mapped[List[str]] = mapped_column(JSON, nullable=False)  # e.g. ["opt_3", "opt_1", "opt_4", "opt_2"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("set_id", "question_order", name="uq_question_set_items_order"),
        UniqueConstraint("set_id", "question_bank_item_id", name="uq_question_set_items_item"),
    )

    # Relationships
    question_set: Mapped["QuestionSet"] = relationship(
        "QuestionSet",
        back_populates="items",
    )
    question_bank_item: Mapped["QuestionBankItem"] = relationship(
        "QuestionBankItem",
        back_populates="set_items",
    )


class QuestionSetScope(Base):
    """Many-to-many relationship linking a QuestionSet to its selected CurriculumNodes."""

    __tablename__ = "question_set_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    curriculum_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint("set_id", "curriculum_node_id", name="uq_question_set_scopes_set_node"),
    )

    # Relationships
    question_set: Mapped["QuestionSet"] = relationship(
        "QuestionSet",
        back_populates="scopes",
    )
    curriculum_node = relationship("CurriculumNode")
