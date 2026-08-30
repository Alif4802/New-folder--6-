import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import pymupdf

from app.core.config import settings
from app.core.database import bootstrap_default_curriculum
from app.models.curriculum import Curriculum, Grade, Subject
from app.models.textbook import SubjectVersion, Unit, Lesson, ActivityNode, CurriculumNode
from app.schemas.textbook import IngestionResponse
from app.services.ocr.winocr_provider import WinOCRProvider
from app.services.pdf.validator import stream_and_stage_upload, validate_staged_pdf
from app.services.pdf.metadata_detector import DynamicMetadataDetector
from app.services.pdf.extractor import PageExtractor, PageExtractionResult
from app.services.pdf.structure_parser import DynamicStructureParser

logger = logging.getLogger("nctb.ingestion")


class IngestionService:
    """
    Orchestrates the dynamic NCTB textbook ingestion pipeline following
    the approved lifecycle specifications.
    """

    @classmethod
    async def ingest_pdf(
        cls,
        file: UploadFile,
        session: AsyncSession,
        grade_id: Optional[int] = None,
        subject_id: Optional[int] = None,
    ) -> IngestionResponse:
        """
        Execute the end-to-end ingestion pipeline with authoritative Grade and Subject assignment.
        """
        staging_path: Optional[Path] = None
        final_pdf_path: Optional[Path] = None
        version_id = str(uuid.uuid4())

        # 1. Chunked Stream Upload & SHA-256 Hashing
        staging_path, checksum_sha256, file_size_bytes = await stream_and_stage_upload(file)

        try:
            # 2. Duplicate Detection (DB-enforced for ACTIVE versions)
            stmt = select(SubjectVersion).where(
                SubjectVersion.checksum_sha256 == checksum_sha256,
                SubjectVersion.is_deleted == False,
            )
            result = await session.execute(stmt)
            active_version = result.scalar_one_or_none()

            if active_version:
                if active_version.ingestion_status in ["COMPLETED", "PARTIAL", "PROCESSING"]:
                    if staging_path.exists():
                        staging_path.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error_code": "DUPLICATE_PDF",
                            "message": "This exact textbook PDF has already been ingested.",
                            "existing_version_id": active_version.id,
                            "existing_title": active_version.title,
                            "ingestion_status": active_version.ingestion_status,
                        },
                    )
                elif active_version.ingestion_status == "FAILED":
                    # Clean up old failed record to allow fresh retry
                    logger.info(f"Removing previous failed ingestion record for checksum {checksum_sha256}")
                    await session.delete(active_version)
                    await session.commit()

            # 3. Disk-based PDF Validation
            page_count = validate_staged_pdf(staging_path)

            # 4. Bootstrap Curriculum Authority
            curriculum = await bootstrap_default_curriculum(session)

            # 5. Safe PDF Storage Promotion (Reusing stored bytes if a deleted version exists)
            del_stmt = (
                select(SubjectVersion)
                .where(
                    SubjectVersion.checksum_sha256 == checksum_sha256,
                    SubjectVersion.is_deleted == True,
                )
                .order_by(SubjectVersion.created_at.desc())
                .limit(1)
            )
            del_res = await session.execute(del_stmt)
            deleted_version = del_res.scalar_one_or_none()

            final_pdf_filename = f"{version_id}.pdf"
            final_pdf_path = settings.storage_pdfs_dir / final_pdf_filename

            if (
                deleted_version
                and deleted_version.stored_pdf_path
                and (settings.STORAGE_ROOT / deleted_version.stored_pdf_path).exists()
            ):
                shutil.copyfile(str(settings.STORAGE_ROOT / deleted_version.stored_pdf_path), str(final_pdf_path))
                if staging_path and staging_path.exists():
                    staging_path.unlink()
                staging_path = None
                logger.info(f"Reused stored PDF asset from deleted version '{deleted_version.id}' for new version '{version_id}'.")
            else:
                shutil.move(str(staging_path), str(final_pdf_path))
                staging_path = None  # moved successfully

            # 6. Create Initial SubjectVersion with status = 'PROCESSING'
            subject_version = SubjectVersion(
                id=version_id,
                curriculum_id=curriculum.id,
                grade_id=grade_id,
                subject_id=subject_id,
                title=Path(file.filename or "Textbook").stem.replace("_", " ").title(),
                source_filename=file.filename or "unknown.pdf",
                stored_pdf_path=f"pdfs/{final_pdf_filename}",
                file_size_bytes=file_size_bytes,
                checksum_sha256=checksum_sha256,
                page_count=page_count,
                ingestion_status="PROCESSING",
                ocr_pages_count=0,
                is_deleted=False,
                curriculum_quality_status="UNASSESSED",
                metadata_status="USER_CONFIRMED" if subject_id else "UNASSESSED",
                curriculum_parser_version=settings.CURRICULUM_PARSER_VERSION,
                metadata_resolver_version=settings.METADATA_RESOLVER_VERSION,
            )
            session.add(subject_version)
            await session.commit()
            logger.info(f"Created SubjectVersion {version_id} with status PROCESSING.")

        except IntegrityError as ie:
            await session.rollback()
            if staging_path and staging_path.exists():
                staging_path.unlink()
            err_str = str(ie).lower()
            if "uq_active_textbook_checksum" in err_str or "checksum_sha256" in err_str:
                logger.warning(f"Active checksum duplicate collision for {checksum_sha256}: {ie}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "DUPLICATE_PDF",
                        "message": "This exact textbook PDF has already been ingested.",
                    },
                )
            logger.error(f"Unexpected database integrity error during ingestion initialization: {ie}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error_code": "INGESTION_INIT_FAILED",
                    "message": "Ingestion could not be completed. Please try again or check the server logs.",
                },
            )
        except HTTPException:
            await session.rollback()
            if staging_path and staging_path.exists():
                staging_path.unlink()
            raise
        except Exception as exc:
            await session.rollback()
            if staging_path and staging_path.exists():
                staging_path.unlink()
            logger.error(f"Initialization stage failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error_code": "INGESTION_INIT_FAILED",
                    "message": "Ingestion could not be completed. Please try again or check the server logs.",
                },
            )

        # 7. Processing & Parsing Execution
        try:
            doc = pymupdf.open(str(final_pdf_path))

            # A. Metadata Detection
            detected_meta = DynamicMetadataDetector.detect_metadata(
                doc=doc,
                filename=file.filename or "",
            )

            # B. Resolve Grade: Explicit grade_id is strictly authoritative
            final_grade_id: Optional[int] = grade_id
            grade_name: Optional[str] = None

            if final_grade_id:
                g_stmt = select(Grade).where(Grade.id == final_grade_id)
                g_res = await session.execute(g_stmt)
                g_obj = g_res.scalar_one_or_none()
                if g_obj:
                    grade_name = g_obj.name
            elif detected_meta.grade_code:
                # Optional fallback if no explicit grade provided
                grade_stmt = select(Grade).where(
                    Grade.curriculum_id == curriculum.id,
                    Grade.code == detected_meta.grade_code,
                )
                grade_res = await session.execute(grade_stmt)
                grade = grade_res.scalar_one_or_none()
                if not grade:
                    grade = Grade(
                        curriculum_id=curriculum.id,
                        code=detected_meta.grade_code,
                        name=detected_meta.grade_name or detected_meta.grade_code.title(),
                        level_number=detected_meta.grade_level,
                        is_active=True,
                    )
                    session.add(grade)
                    await session.flush()
                final_grade_id = grade.id
                grade_name = grade.name

            # C. Resolve Subject: Explicit subject_id is strictly authoritative, fallback to detected
            final_subject_id: Optional[int] = subject_id
            metadata_status: str = "USER_CONFIRMED" if final_subject_id is not None else "UNASSESSED"

            if final_subject_id is None and detected_meta.subject_code:
                subj_stmt = select(Subject).where(
                    Subject.curriculum_id == curriculum.id,
                    Subject.code == detected_meta.subject_code,
                )
                subj_res = await session.execute(subj_stmt)
                subject = subj_res.scalar_one_or_none()
                if not subject:
                    subject = Subject(
                        curriculum_id=curriculum.id,
                        code=detected_meta.subject_code,
                        name=detected_meta.subject_name or detected_meta.subject_code.title(),
                        domain=detected_meta.domain,
                    )
                    session.add(subject)
                    await session.flush()
                final_subject_id = subject.id
                metadata_status = "VALID"
            elif final_subject_id is None:
                metadata_status = "NEEDS_REVIEW"

            # D. Page-by-Page Extraction with Quality Check & Thread-Isolated WinOCR Fallback
            ocr_provider = WinOCRProvider(language="en-US")
            extractor = PageExtractor(ocr_provider=ocr_provider)

            page_results: list[PageExtractionResult] = []
            ocr_pages_count = 0

            for p_idx in range(doc.page_count):
                page_res = await extractor.extract_page(doc, p_idx)
                if page_res.ocr_used:
                    ocr_pages_count += 1
                page_results.append(page_res)

            doc.close()

            # E. Dynamic Structure Parsing (Units, Lessons, ActivityNodes)
            parsed_structure = DynamicStructureParser.parse_document(
                page_results=page_results,
                domain=detected_meta.domain,
            )

            # 8. Atomic Hierarchy Persistence
            total_activity_nodes = 0
            total_lessons = 0

            for parsed_unit in parsed_structure.units:
                unit_orm = Unit(
                    subject_version_id=version_id,
                    ordinal=parsed_unit.ordinal,
                    detected_number=parsed_unit.detected_number,
                    label_type=parsed_unit.label_type,
                    title=parsed_unit.title,
                    start_page=parsed_unit.start_page,
                    end_page=parsed_unit.end_page,
                )
                session.add(unit_orm)
                await session.flush()  # obtain unit_orm.id

                # Direct nodes on Unit
                for node in parsed_unit.direct_nodes:
                    node_orm = ActivityNode(
                        subject_version_id=version_id,
                        unit_id=unit_orm.id,
                        lesson_id=None,
                        ordinal=node.ordinal,
                        node_type=node.node_type,
                        title=node.title,
                        content_text=node.content_text,
                        structured_payload=node.structured_payload,
                        page_number=node.page_number,
                        bounding_box=node.bounding_box,
                        content_hash=node.content_hash,
                        parser_metadata=node.parser_metadata,
                    )
                    session.add(node_orm)
                    total_activity_nodes += 1

                # Lessons on Unit
                for parsed_lesson in parsed_unit.lessons:
                    lesson_orm = Lesson(
                        unit_id=unit_orm.id,
                        ordinal=parsed_lesson.ordinal,
                        detected_number=parsed_lesson.detected_number,
                        title=parsed_lesson.title,
                        start_page=parsed_lesson.start_page,
                        end_page=parsed_lesson.end_page,
                    )
                    session.add(lesson_orm)
                    await session.flush()  # obtain lesson_orm.id
                    total_lessons += 1

                    for l_node in parsed_lesson.nodes:
                        l_node_orm = ActivityNode(
                            subject_version_id=version_id,
                            unit_id=unit_orm.id,
                            lesson_id=lesson_orm.id,
                            ordinal=l_node.ordinal,
                            node_type=l_node.node_type,
                            title=l_node.title,
                            content_text=l_node.content_text,
                            structured_payload=l_node.structured_payload,
                            page_number=l_node.page_number,
                            bounding_box=l_node.bounding_box,
                            content_hash=l_node.content_hash,
                            parser_metadata=l_node.parser_metadata,
                        )
                        session.add(l_node_orm)
                        total_activity_nodes += 1

            # Determine final status
            final_status = "PARTIAL" if parsed_structure.warnings else "COMPLETED"

            # Combine diagnostics
            meta_dict = detected_meta.diagnostic_signals or {}
            meta_dict["unresolved_front_matter_pages"] = parsed_structure.unresolved_front_matter_pages

            # Update SubjectVersion
            subject_version.grade_id = final_grade_id
            subject_version.subject_id = final_subject_id
            subject_version.title = detected_meta.title
            subject_version.edition_year = detected_meta.edition_year
            subject_version.edition_label = detected_meta.edition_label
            subject_version.publication_year = detected_meta.publication_year
            subject_version.version_label = detected_meta.version_label
            subject_version.ingestion_status = final_status
            subject_version.ocr_pages_count = ocr_pages_count
            subject_version.curriculum_quality_status = "BUILDING"
            subject_version.metadata_status = metadata_status
            subject_version.curriculum_parser_version = settings.CURRICULUM_PARSER_VERSION
            subject_version.metadata_resolver_version = settings.METADATA_RESOLVER_VERSION
            subject_version.detected_metadata = meta_dict
            subject_version.warnings = parsed_structure.warnings

            await session.commit()

            # Non-destructively generate generic CurriculumNodes & run quality gate
            try:
                from app.services.pdf.curriculum_migration import migrate_subject_version_to_generic_curriculum
                from app.services.pdf.curriculum_quality import CurriculumQualityGate
                await migrate_subject_version_to_generic_curriculum(session, version_id)

                nodes_stmt = select(CurriculumNode).where(CurriculumNode.subject_version_id == version_id)
                nodes_res = await session.execute(nodes_stmt)
                gen_nodes = nodes_res.scalars().all()

                quality_res = CurriculumQualityGate.evaluate_tree(gen_nodes, page_count)
                subject_version.curriculum_quality_status = "VALID" if quality_res.is_valid else "NEEDS_REFRESH"
                await session.commit()
            except Exception as e:
                logger.warning(f"Could not generate or evaluate generic curriculum nodes for {version_id}: {e}")
                subject_version.curriculum_quality_status = "NEEDS_REFRESH"
                await session.commit()

            # Re-fetch version with relations to compute readiness
            from sqlalchemy.orm import selectinload
            from app.services.assessment.readiness import AssessmentReadinessService
            fresh_stmt = select(SubjectVersion).where(SubjectVersion.id == version_id).options(
                selectinload(SubjectVersion.subject),
                selectinload(SubjectVersion.grade),
            )
            fresh_res = await session.execute(fresh_stmt)
            fresh_ver = fresh_res.scalar_one_or_none() or subject_version
            readiness = AssessmentReadinessService.evaluate(fresh_ver)

            logger.info(
                f"Ingestion completed for {version_id}: status={final_status}, "
                f"units={len(parsed_structure.units)}, lessons={total_lessons}, nodes={total_activity_nodes}"
            )

            return IngestionResponse(
                version_id=version_id,
                title=detected_meta.title,
                grade_id=final_grade_id,
                grade_name=grade_name,
                subject_id=final_subject_id,
                detected_grade=detected_meta.grade_name,
                detected_subject=detected_meta.subject_name,
                detected_domain=detected_meta.domain,
                edition_label=detected_meta.edition_label,
                publication_year=detected_meta.publication_year,
                curriculum_quality_status=subject_version.curriculum_quality_status,
                metadata_status=subject_version.metadata_status,
                assessment_ready=readiness.is_ready,
                assessment_readiness_reasons=readiness.reasons,
                page_count=page_count,
                unit_count=len(parsed_structure.units),
                lesson_count=total_lessons,
                activity_node_count=total_activity_nodes,
                ocr_pages_count=ocr_pages_count,
                ingestion_status=final_status,
                warnings=parsed_structure.warnings,
            )

        except Exception as exc:
            logger.error(f"Fatal parsing error during ingestion of {version_id}: {exc}", exc_info=True)
            await session.rollback()

            # Record failure in a separate small transaction
            try:
                fail_stmt = select(SubjectVersion).where(SubjectVersion.id == version_id)
                fail_res = await session.execute(fail_stmt)
                failed_ver = fail_res.scalar_one_or_none()
                if failed_ver:
                    failed_ver.ingestion_status = "FAILED"
                    failed_ver.error_message = str(exc)
                    await session.commit()
            except Exception as inner_exc:
                logger.error(f"Could not record FAILED status for {version_id}: {inner_exc}")

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error_code": "INGESTION_PROCESSING_FAILED",
                    "message": "PDF parsing and extraction failed. Please verify the document or check the server logs.",
                },
            )
