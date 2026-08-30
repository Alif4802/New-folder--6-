import difflib
import hashlib
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.assessment import (
    MCQAnswerKeyItemResponse,
    MCQOptionResponse,
    MCQQuestionResponse,
)
from app.schemas.llm_mcq import LLMMCGCandidateResponse, LLMMCGItem

logger = logging.getLogger("nctb.services.assessment.validator")


@dataclass
class RejectionAccounting:
    """
    Tracks granular rejection reasons across deterministic validation and LLM verification.
    Guarantees the invariant:
    CANDIDATES_RETURNED == FINAL_ACCEPTED + TOTAL_REJECTED + SURPLUS_NOT_NEEDED
    """
    candidates_returned: int = 0
    schema_rejected: int = 0
    invalid_option_count: int = 0
    duplicate_option_rejected: int = 0
    invalid_correct_option_id: int = 0
    invalid_source_chunk_rejected: int = 0
    exact_question_duplicate_rejected: int = 0
    near_duplicate_rejected: int = 0
    deterministic_math_rejected: int = 0
    llm_verification_rejected: int = 0
    other_rejected: int = 0
    surplus_not_needed: int = 0
    final_accepted: int = 0

    @property
    def total_rejected(self) -> int:
        return (
            self.schema_rejected
            + self.invalid_option_count
            + self.duplicate_option_rejected
            + self.invalid_correct_option_id
            + self.invalid_source_chunk_rejected
            + self.exact_question_duplicate_rejected
            + self.near_duplicate_rejected
            + self.deterministic_math_rejected
            + self.llm_verification_rejected
            + self.other_rejected
        )

    def check_invariant(self, context_str: str = "Batch") -> bool:
        """
        Assertable accounting check verifying that all returned candidates are accounted for.
        """
        accounted = self.final_accepted + self.total_rejected + self.surplus_not_needed
        if self.candidates_returned != accounted:
            logger.error(
                f"[{context_str} Accounting Invariant Violation] "
                f"CANDIDATES_RETURNED ({self.candidates_returned}) != "
                f"FINAL_ACCEPTED ({self.final_accepted}) + "
                f"TOTAL_REJECTED ({self.total_rejected}) + "
                f"SURPLUS_NOT_NEEDED ({self.surplus_not_needed}) [Sum={accounted}]"
            )
            return False
        return True

    def merge(self, other: "RejectionAccounting"):
        self.candidates_returned += other.candidates_returned
        self.schema_rejected += other.schema_rejected
        self.invalid_option_count += other.invalid_option_count
        self.duplicate_option_rejected += other.duplicate_option_rejected
        self.invalid_correct_option_id += other.invalid_correct_option_id
        self.invalid_source_chunk_rejected += other.invalid_source_chunk_rejected
        self.exact_question_duplicate_rejected += other.exact_question_duplicate_rejected
        self.near_duplicate_rejected += other.near_duplicate_rejected
        self.deterministic_math_rejected += other.deterministic_math_rejected
        self.llm_verification_rejected += other.llm_verification_rejected
        self.other_rejected += other.other_rejected
        self.surplus_not_needed += other.surplus_not_needed
        self.final_accepted += other.final_accepted

    def log_summary(self, logger_instance: logging.Logger, context_str: str = "Batch"):
        invariant_status = "PASS" if self.check_invariant(context_str) else "FAIL"
        logger_instance.info(
            f"[{context_str} Rejection Accounting | INVARIANT={invariant_status}] "
            f"CANDIDATES_RETURNED={self.candidates_returned}, "
            f"SCHEMA_REJECTED={self.schema_rejected}, "
            f"INVALID_OPTION_COUNT={self.invalid_option_count}, "
            f"DUPLICATE_OPTION_REJECTED={self.duplicate_option_rejected}, "
            f"INVALID_CORRECT_OPTION_ID={self.invalid_correct_option_id}, "
            f"INVALID_SOURCE_CHUNK_REJECTED={self.invalid_source_chunk_rejected}, "
            f"EXACT_QUESTION_DUPLICATE_REJECTED={self.exact_question_duplicate_rejected}, "
            f"NEAR_DUPLICATE_REJECTED={self.near_duplicate_rejected}, "
            f"DETERMINISTIC_MATH_REJECTED={self.deterministic_math_rejected}, "
            f"LLM_VERIFICATION_REJECTED={self.llm_verification_rejected}, "
            f"OTHER_REJECTED={self.other_rejected}, "
            f"SURPLUS_NOT_NEEDED={self.surplus_not_needed}, "
            f"TOTAL_REJECTED={self.total_rejected}, "
            f"FINAL_ACCEPTED={self.final_accepted}"
        )


class ValidationIssue:
    def __init__(self, question_id: str, message: str, category: str = "other"):
        self.question_id = question_id
        self.message = message
        self.category = category

    def __repr__(self) -> str:
        return f"[{self.question_id}|{self.category}] {self.message}"


class MCQValidator:
    """
    Validates structural integrity, distinct options, source chunk citations,
    stem completeness, within-set duplicate and near-duplicate prevention,
    and assigns sequential A/B/C/D labels preserving the exact LLM-returned ordering.
    """

    @classmethod
    def normalize_stem(cls, stem: str) -> str:
        """Lowercases, strips punctuation, and collapses whitespace for comparison."""
        cleaned = re.sub(r"[^\w\s\$\\]", " ", stem.lower())
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def is_near_duplicate(cls, stem1: str, stem2: str, threshold: float = 0.82) -> bool:
        """
        Determines whether two question stems are duplicates or near-duplicates
        using SequenceMatcher ratio and Jaccard token overlap on content words.
        Differentiates mathematical problems with distinct operands or operators.
        """
        s1_clean = re.sub(r"[^\w\s\$\\]", " ", stem1.lower()).strip()
        s2_clean = re.sub(r"[^\w\s\$\\]", " ", stem2.lower()).strip()
        s1_norm = re.sub(r"\s+", " ", s1_clean)
        s2_norm = re.sub(r"\s+", " ", s2_clean)

        if s1_norm == s2_norm:
            return True

        # Extract numeric operands
        nums1 = re.findall(r"\d+", s1_norm)
        nums2 = re.findall(r"\d+", s2_norm)

        # If both questions have numbers and they differ (e.g. square of 4 vs square of 5), they are distinct math problems!
        if nums1 and nums2 and nums1 != nums2:
            return False

        # Token-based Jaccard similarity without generic stopwords
        stopwords = {
            "what", "is", "the", "of", "a", "an", "in", "to", "which",
            "following", "if", "its", "then", "find", "calculate", "how",
            "many", "does", "by", "for", "from", "with", "according"
        }
        words1 = set(w for w in s1_norm.split() if w not in stopwords and len(w) > 1)
        words2 = set(w for w in s2_norm.split() if w not in stopwords and len(w) > 1)

        if words1 and words2:
            jaccard = len(words1 & words2) / len(words1 | words2)
            if jaccard >= threshold:
                return True

        # SequenceMatcher ratio for questions
        seq_ratio = difflib.SequenceMatcher(None, s1_norm, s2_norm).ratio()
        if seq_ratio >= 0.88:
            return True

        return False

    @classmethod
    def is_stem_complete(cls, stem: str) -> bool:
        """
        Ensures the stem is a complete, self-contained question and NOT
        just an isolated equation like '5^2 = 25' or 'x = 4'.
        """
        s = stem.strip()
        if len(s) < 8:
            return False

        # If the stem is purely an equation without any alphabetic prose
        letters = re.findall(r"[a-zA-Z]", s)
        if len(letters) < 4:
            return False

        return True

    @classmethod
    def validate_single_item(
        cls,
        q: LLMMCGItem,
        valid_chunk_ids: Set[str],
        existing_stems: List[str],
        near_duplicate_threshold: float = 0.82,
    ) -> List[ValidationIssue]:
        """Validates a single candidate MCQ item against quality and duplication rules."""
        issues: List[ValidationIssue] = []
        qid = q.question_id or "q_item"

        # 1. Stem validation & completeness
        stem = (q.stem or "").strip()
        if not stem:
            issues.append(ValidationIssue(qid, "Question stem is empty.", category="schema_rejected"))
            return issues

        if not cls.is_stem_complete(stem):
            issues.append(ValidationIssue(qid, f"Question stem is incomplete: '{stem}'.", category="other_rejected"))

        # 2. Duplicate checks
        for existing in existing_stems:
            if cls.normalize_stem(stem) == cls.normalize_stem(existing):
                issues.append(ValidationIssue(qid, f"Exact duplicate stem found: '{existing[:50]}...'", category="exact_question_duplicate_rejected"))
                break
            elif cls.is_near_duplicate(stem, existing, near_duplicate_threshold):
                issues.append(ValidationIssue(qid, f"Near-duplicate of existing question: '{existing[:50]}...'", category="near_duplicate_rejected"))
                break

        # 3. Options validation (exactly 4)
        if not q.options or len(q.options) != 4:
            issues.append(ValidationIssue(qid, f"Question must have exactly 4 options (found {len(q.options) if q.options else 0}).", category="invalid_option_count"))
            return issues

        # 4. Unique Option IDs
        opt_ids = [opt.id for opt in q.options if opt.id]
        if len(opt_ids) != 4 or len(set(opt_ids)) != 4:
            issues.append(ValidationIssue(qid, f"Options must have 4 unique IDs (found {opt_ids}).", category="duplicate_option_rejected"))

        # 5. Distinct normalized option content
        opt_texts = [re.sub(r"\s+", " ", (opt.text or "").lower().strip()) for opt in q.options]
        if any(not t for t in opt_texts):
            issues.append(ValidationIssue(qid, "One or more options have empty text.", category="other_rejected"))
        if len(set(opt_texts)) != 4:
            issues.append(ValidationIssue(qid, f"Option values must be distinct. Found duplicate texts in {opt_texts}.", category="duplicate_option_rejected"))

        # 6. Correct Option ID validation
        if not q.correct_option_id or q.correct_option_id not in opt_ids:
            issues.append(ValidationIssue(qid, f"Declared correct_option_id '{q.correct_option_id}' does not match any option ID in {opt_ids}.", category="invalid_correct_option_id"))

        # 7. Explanation presence
        if not (q.explanation or "").strip():
            issues.append(ValidationIssue(qid, "Explanation is missing or empty.", category="other_rejected"))

        # 8. Source chunk grounding validation
        if not q.source_chunk_ids:
            issues.append(ValidationIssue(qid, "source_chunk_ids is empty. Every question must cite at least one source chunk.", category="invalid_source_chunk_rejected"))
        else:
            invalid_cids = [cid for cid in q.source_chunk_ids if cid not in valid_chunk_ids]
            if invalid_cids:
                issues.append(ValidationIssue(qid, f"Invalid source_chunk_ids cited: {invalid_cids}. Must be in {list(valid_chunk_ids)}.", category="invalid_source_chunk_rejected"))

        # 9. Deterministic math check
        cls._deterministic_math_check(q, issues)

        return issues

    @classmethod
    def _deterministic_math_check(cls, q: LLMMCGItem, issues: List[ValidationIssue]):
        """Lightweight sanity check for simple arithmetic expressions where safe."""
        stem = q.stem
        # Check for simple square questions e.g. "square of 5"
        sq_match = re.search(r"square\s+of\s+(\d+)", stem, re.IGNORECASE)
        if sq_match:
            base_num = int(sq_match.group(1))
            expected = str(base_num * base_num)
            correct_opt = next((o for o in q.options if o.id == q.correct_option_id), None)
            if correct_opt and correct_opt.text.strip().isdigit():
                if correct_opt.text.strip() != expected:
                    issues.append(ValidationIssue(
                        q.question_id,
                        f"Deterministic check failed: square of {base_num} is {expected}, but declared answer is {correct_opt.text}.",
                        category="deterministic_math_rejected",
                    ))

        # Check for square root questions e.g. "square root of 16"
        sqrt_match = re.search(r"square\s+root\s+of\s+(\d+)", stem, re.IGNORECASE)
        if sqrt_match:
            base_num = int(sqrt_match.group(1))
            import math
            sqrt_val = math.isqrt(base_num)
            if sqrt_val * sqrt_val == base_num:
                expected = str(sqrt_val)
                correct_opt = next((o for o in q.options if o.id == q.correct_option_id), None)
                if correct_opt and correct_opt.text.strip().isdigit():
                    if correct_opt.text.strip() != expected:
                        issues.append(ValidationIssue(
                            q.question_id,
                            f"Deterministic check failed: square root of {base_num} is {expected}, but declared answer is {correct_opt.text}.",
                            category="deterministic_math_rejected",
                        ))

    @classmethod
    def assign_labels_and_build_answer_key_for_items(
        cls,
        items: List[LLMMCGItem],
    ) -> Tuple[List[MCQQuestionResponse], List[MCQAnswerKeyItemResponse]]:
        """
        Preserves EXACT LLM-returned question order and option order.
        Assigns sequential labels 'A', 'B', 'C', 'D' to options 0..3.
        Builds matching Answer Key.
        """
        display_labels = ["A", "B", "C", "D"]
        questions_out: List[MCQQuestionResponse] = []
        answer_key_out: List[MCQAnswerKeyItemResponse] = []

        for q_idx, q in enumerate(items):
            q_num = q_idx + 1
            options_out: List[MCQOptionResponse] = []
            correct_letter = "A"
            correct_text = ""
            correct_latex = None

            for opt_idx, opt in enumerate(q.options[:4]):
                label = display_labels[opt_idx]
                options_out.append(
                    MCQOptionResponse(
                        id=opt.id,
                        label=label,
                        text=opt.text.strip(),
                        latex=opt.latex,
                    )
                )
                if opt.id == q.correct_option_id:
                    correct_letter = label
                    correct_text = opt.text.strip()
                    correct_latex = opt.latex

            questions_out.append(
                MCQQuestionResponse(
                    id=q.question_id,
                    question_number=q_num,
                    question_text=q.stem.strip(),
                    question_latex=q.stem_latex,
                    options=options_out,
                    correct_option_id=q.correct_option_id,
                    explanation=q.explanation.strip(),
                )
            )

            answer_key_out.append(
                MCQAnswerKeyItemResponse(
                    question_number=q_num,
                    question_id=q.question_id,
                    correct_letter=correct_letter,
                    correct_text=correct_text,
                    correct_latex=correct_latex,
                    explanation=q.explanation.strip(),
                )
            )

        return questions_out, answer_key_out

    @classmethod
    def randomize_paper(
        cls,
        questions: List[MCQQuestionResponse],
        answer_key: List[MCQAnswerKeyItemResponse],
    ) -> Tuple[List[MCQQuestionResponse], List[MCQAnswerKeyItemResponse]]:
        """
        Instant, ZERO-LLM randomization of an existing assessment paper:
        1. Shuffles question order.
        2. Shuffles options inside every question independently.
        3. Recalculates display labels (A, B, C, D) and remaps Answer Key letters.
        4. Preserves explanations and underlying correct options.
        """
        if not questions:
            return [], []

        # Create copy of questions
        shuffled_questions = list(questions)
        random.shuffle(shuffled_questions)

        display_labels = ["A", "B", "C", "D"]
        new_questions: List[MCQQuestionResponse] = []
        new_answer_key: List[MCQAnswerKeyItemResponse] = []

        for q_idx, q in enumerate(shuffled_questions):
            q_num = q_idx + 1

            # Match original correct answer text or option ID
            orig_ak = next((ak for ak in answer_key if ak.question_number == q.question_number or ak.question_id == q.id), None)
            target_correct_text = orig_ak.correct_text if orig_ak else ""
            target_correct_id = q.correct_option_id

            # Shuffle options
            shuffled_options = list(q.options)
            random.shuffle(shuffled_options)

            new_options: List[MCQOptionResponse] = []
            new_correct_letter = "A"
            new_correct_text = ""
            new_correct_latex = None

            for opt_idx, opt in enumerate(shuffled_options[:4]):
                lbl = display_labels[opt_idx]
                new_options.append(
                    MCQOptionResponse(
                        id=opt.id,
                        label=lbl,
                        text=opt.text,
                        latex=opt.latex,
                    )
                )
                is_correct = False
                if target_correct_id and opt.id and opt.id == target_correct_id:
                    is_correct = True
                elif target_correct_text and opt.text.strip().lower() == target_correct_text.strip().lower():
                    is_correct = True

                if is_correct:
                    new_correct_letter = lbl
                    new_correct_text = opt.text
                    new_correct_latex = opt.latex

            new_questions.append(
                MCQQuestionResponse(
                    id=q.id,
                    question_number=q_num,
                    question_text=q.question_text,
                    question_latex=q.question_latex,
                    options=new_options,
                    correct_option_id=target_correct_id,
                    explanation=q.explanation,
                )
            )

            new_answer_key.append(
                MCQAnswerKeyItemResponse(
                    question_number=q_num,
                    question_id=q.id,
                    correct_letter=new_correct_letter,
                    correct_text=new_correct_text,
                    correct_latex=new_correct_latex,
                    explanation=q.explanation,
                )
            )

        return new_questions, new_answer_key
