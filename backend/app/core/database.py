import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, select
from app.core.config import settings

logger = logging.getLogger("nctb.database")


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base for model entities."""
    pass


# Global engine and session factory
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns a sessionmaker dynamically bound to current settings.DATABASE_URL."""
    eng = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        future=True,
    )
    return async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


async def init_db_schema() -> None:
    """Create all database tables defined in Base.metadata."""
    # Import models here to guarantee registration before table creation
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

        # Safe SQLite column migration: ensure curriculum_node_id exists on activity_nodes
        if settings.DATABASE_URL.startswith("sqlite"):
            try:
                res = await conn.execute(text("PRAGMA table_info(activity_nodes);"))
                cols = [row[1] for row in res.fetchall()]
                if "curriculum_node_id" not in cols:
                    await conn.execute(text("ALTER TABLE activity_nodes ADD COLUMN curriculum_node_id VARCHAR(64) REFERENCES curriculum_nodes(id);"))
                    logger.info("Migrated column 'curriculum_node_id' onto table 'activity_nodes'.")
            except Exception as e:
                logger.debug(f"Table info / column migration check for activity_nodes: {e}")

            try:
                res = await conn.execute(text("PRAGMA table_info(grades);"))
                cols = [row[1] for row in res.fetchall()]
                if "is_active" not in cols:
                    await conn.execute(text("ALTER TABLE grades ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL;"))
                    logger.info("Migrated column 'is_active' onto table 'grades'.")
            except Exception as e:
                logger.debug(f"Table info / column migration check for grades: {e}")

            try:
                res = await conn.execute(text("PRAGMA table_info(subject_versions);"))
                sv_cols = [row[1] for row in res.fetchall()]
                if "is_deleted" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN is_deleted BOOLEAN DEFAULT 0 NOT NULL;"))
                    logger.info("Migrated column 'is_deleted' onto table 'subject_versions'.")
                if "deleted_at" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN deleted_at DATETIME;"))
                if "curriculum_parser_version" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN curriculum_parser_version VARCHAR(50);"))
                if "curriculum_built_at" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN curriculum_built_at DATETIME;"))
                if "curriculum_quality_status" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN curriculum_quality_status VARCHAR(50) DEFAULT 'UNASSESSED' NOT NULL;"))
                if "metadata_status" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN metadata_status VARCHAR(50) DEFAULT 'UNASSESSED' NOT NULL;"))
                if "metadata_resolver_version" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN metadata_resolver_version VARCHAR(50);"))
                if "edition_label" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN edition_label VARCHAR(100);"))
                if "publication_year" not in sv_cols:
                    await conn.execute(text("ALTER TABLE subject_versions ADD COLUMN publication_year INTEGER;"))

                # Ensure legacy global UNIQUE index on checksum_sha256 is migrated to non-unique index
                idx_res = await conn.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_subject_versions_checksum_sha256';"))
                idx_row = idx_res.fetchone()
                if idx_row and "UNIQUE" in (idx_row[0] or "").upper():
                    await conn.execute(text("DROP INDEX IF EXISTS ix_subject_versions_checksum_sha256;"))
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_subject_versions_checksum_sha256 ON subject_versions (checksum_sha256);"))
                    logger.info("Migrated legacy global UNIQUE index on checksum_sha256 to non-unique index.")
                else:
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_subject_versions_checksum_sha256 ON subject_versions (checksum_sha256);"))

                # Partial unique index for active textbook checksum uniqueness
                await conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_textbook_checksum ON subject_versions(checksum_sha256) WHERE is_deleted = 0;"
                ))
                logger.info("Created / verified partial unique index 'uq_active_textbook_checksum'.")
            except Exception as e:
                logger.debug(f"Table info / column migration check for subject_versions: {e}")

    logger.info("Database schema initialized.")


async def _backfill_legacy_textbook_grades(session: AsyncSession, curriculum_id: int) -> None:
    """
    Generic, curriculum-aware legacy backfill for unassigned SubjectVersions:
    1. Reads authoritative Grade catalog for the curriculum.
    2. Inspects structured metadata (detected_metadata) first.
    3. Checks filename/title against the Grade catalog dynamically.
    4. Backfills unambiguous matches; leaves ambiguous as unassigned (None).
    """
    import re
    from app.models.curriculum import Grade
    from app.models.textbook import SubjectVersion

    grades_stmt = select(Grade).where(Grade.curriculum_id == curriculum_id)
    grades_res = await session.execute(grades_stmt)
    grades = grades_res.scalars().all()
    if not grades:
        return

    unassigned_stmt = select(SubjectVersion).where(
        SubjectVersion.curriculum_id == curriculum_id,
        SubjectVersion.grade_id.is_(None),
    )
    unassigned_res = await session.execute(unassigned_stmt)
    unassigned_versions = unassigned_res.scalars().all()

    for version in unassigned_versions:
        matched_grade = None

        # 1. Check structured detected metadata
        if version.detected_metadata and isinstance(version.detected_metadata, dict):
            grade_code = version.detected_metadata.get("grade_code")
            grade_level = version.detected_metadata.get("grade_level")
            if grade_code:
                matched_grade = next((g for g in grades if g.code.lower() == grade_code.lower()), None)
            if not matched_grade and grade_level is not None:
                matched_grade = next((g for g in grades if g.level_number == grade_level), None)

        # 2. Generic match against Grade catalog
        if not matched_grade:
            search_text = f"{version.title} {version.source_filename}".lower()
            matching_grades = []
            for g in grades:
                patterns = [
                    rf"\b{re.escape(g.name.lower())}\b",
                    rf"\b{re.escape(g.code.lower())}\b",
                ]
                if g.level_number is not None:
                    patterns.append(rf"\bclass\s*[-:]?\s*{g.level_number}\b")
                    patterns.append(rf"\bgrade\s*[-:]?\s*{g.level_number}\b")

                for pat in patterns:
                    if re.search(pat, search_text, re.IGNORECASE):
                        matching_grades.append(g)
                        break

            unique_matches = list({g.id: g for g in matching_grades}.values())
            if len(unique_matches) == 1:
                matched_grade = unique_matches[0]

        if matched_grade:
            version.grade_id = matched_grade.id
            logger.info(
                f"One-time legacy backfill: Linked grade '{matched_grade.name}' (id={matched_grade.id}) "
                f"to SubjectVersion '{version.id}' ('{version.title}')"
            )

    await session.commit()


async def _audit_legacy_curriculum_quality(session: AsyncSession, curriculum_id: int) -> None:
    """
    Lightweight, generic quality audit of unassessed SubjectVersions without re-processing PDFs:
    - Calculates duplicate title ratio across CurriculumNodes
    - Calculates root density relative to page_count
    - Checks for page-like suffix patterns in node titles
    Classifies into VALID or NEEDS_REFRESH.
    """
    from app.models.textbook import SubjectVersion, CurriculumNode
    import re
    from sqlalchemy.orm import selectinload

    stmt = select(SubjectVersion).where(
        SubjectVersion.curriculum_id == curriculum_id,
        SubjectVersion.curriculum_quality_status == "UNASSESSED",
    ).options(selectinload(SubjectVersion.curriculum_nodes))
    res = await session.execute(stmt)
    unassessed = res.scalars().all()

    for v in unassessed:
        nodes = v.curriculum_nodes
        if not nodes:
            v.curriculum_quality_status = "NEEDS_REFRESH"
            continue

        roots = [n for n in nodes if n.parent_id is None]
        total_nodes = len(nodes)
        page_count = max(v.page_count, 1)

        # Metric 1: Duplicate normalized title ratio across roots
        root_titles = [re.sub(r"\s+", " ", n.title.strip().lower()) for n in roots if n.title]
        unique_root_titles = set(root_titles)
        dup_title_ratio = 1.0 - (len(unique_root_titles) / len(root_titles)) if root_titles else 0.0

        # Metric 2: Root density relative to page count (e.g. > 0.40 roots per page)
        root_density = len(roots) / page_count

        # Metric 3: Page suffix pattern (titles ending in 1-4 digit page numbers like 'Real Numbers 15')
        page_suffix_count = sum(1 for n in nodes if re.search(r"\b[A-Za-z\s]+\s+\d{1,4}$", n.title or ""))
        page_suffix_ratio = page_suffix_count / total_nodes if total_nodes > 0 else 0.0

        if dup_title_ratio > 0.25 or root_density > 0.40 or page_suffix_ratio > 0.30:
            v.curriculum_quality_status = "NEEDS_REFRESH"
            logger.info(
                f"Legacy curriculum quality audit: SubjectVersion '{v.id}' marked NEEDS_REFRESH "
                f"(dup_ratio={dup_title_ratio:.2f}, root_density={root_density:.2f}, suffix_ratio={page_suffix_ratio:.2f})."
            )
        else:
            v.curriculum_quality_status = "VALID"
            logger.info(f"Legacy curriculum quality audit: SubjectVersion '{v.id}' marked VALID.")

    await session.commit()


async def bootstrap_default_curriculum(session: AsyncSession):
    """Ensure default curriculum configured in settings exists in the database with master grades and subjects."""
    from app.models.curriculum import Curriculum, Grade, Subject

    stmt = select(Curriculum).where(Curriculum.code == settings.DEFAULT_CURRICULUM_CODE)
    result = await session.execute(stmt)
    curriculum = result.scalar_one_or_none()

    if not curriculum:
        curriculum = Curriculum(
            code=settings.DEFAULT_CURRICULUM_CODE,
            name=settings.DEFAULT_CURRICULUM_NAME,
            country=settings.DEFAULT_CURRICULUM_COUNTRY,
            authority=settings.DEFAULT_CURRICULUM_AUTHORITY,
            is_active=True,
        )
        session.add(curriculum)
        await session.commit()
        await session.refresh(curriculum)
        logger.info(f"Bootstrapped default curriculum: {curriculum.code}")

    # Centralized, idempotent master data seed for default curriculum Grades (Class 1 to 12)
    for level in range(1, 13):
        code = f"class-{level}"
        name = f"Class {level}"
        g_stmt = select(Grade).where(
            Grade.curriculum_id == curriculum.id,
            Grade.code == code,
        )
        g_res = await session.execute(g_stmt)
        grade_record = g_res.scalar_one_or_none()
        if not grade_record:
            grade_record = Grade(
                curriculum_id=curriculum.id,
                code=code,
                name=name,
                level_number=level,
                is_active=True,
            )
            session.add(grade_record)
    await session.commit()

    # Centralized, idempotent master data seed for canonical Subjects from subject profiles
    try:
        from app.services.pdf.subject_profiles import subject_registry
        for profile in subject_registry.list_profiles():
            s_stmt = select(Subject).where(
                Subject.curriculum_id == curriculum.id,
                Subject.code == profile.code,
            )
            s_res = await session.execute(s_stmt)
            subj_record = s_res.scalar_one_or_none()
            if not subj_record:
                subj_record = Subject(
                    curriculum_id=curriculum.id,
                    code=profile.code,
                    name=profile.name,
                    domain=profile.domain,
                )
                session.add(subj_record)
        await session.commit()
    except Exception as e:
        logger.warning(f"Subject master data seeding warning: {e}")

    # Generic one-time legacy backfill for textbooks lacking grade_id
    try:
        await _backfill_legacy_textbook_grades(session, curriculum.id)
    except Exception as e:
        logger.warning(f"Legacy grade backfill warning: {e}")

    # Generic legacy quality audit for unassessed curriculum structures
    try:
        await _audit_legacy_curriculum_quality(session, curriculum.id)
    except Exception as e:
        logger.warning(f"Legacy quality audit warning: {e}")

    return curriculum


async def init_db() -> bool:
    """Safely initialize and verify database connectivity on startup."""
    try:
        # Ensure parent directory of database file exists if using sqlite
        if settings.DATABASE_URL.startswith("sqlite"):
            settings.data_dir.mkdir(parents=True, exist_ok=True)

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established successfully.")

        # Create tables and bootstrap
        await init_db_schema()
        async with AsyncSessionFactory() as session:
            await bootstrap_default_curriculum(session)
            # Non-destructively ensure generic curriculum nodes are populated
            try:
                from app.services.pdf.curriculum_migration import auto_migrate_all_textbooks
                await auto_migrate_all_textbooks(session)
            except Exception as e:
                logger.warning(f"Curriculum auto-migration warning: {e}")

        return True
    except Exception as exc:
        logger.error(f"Database initialization failed: {exc}", exc_info=True)
        return False


async def close_db() -> None:
    """Cleanly dispose of database engine on application shutdown."""
    logger.info("Closing database engine...")
    await engine.dispose()
    logger.info("Database engine closed.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency helper to yield an asynchronous database session."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
