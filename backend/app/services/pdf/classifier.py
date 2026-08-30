import hashlib
import re
from typing import Any, Dict, Optional, Tuple


def normalize_content_text(text: str) -> str:
    """Clean whitespace and normalize encoding for consistent hashing."""
    return re.sub(r"\s+", " ", text).strip()


def compute_content_hash(text: str) -> str:
    """Generate deterministic SHA-256 hash for activity node content."""
    normalized = normalize_content_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ActivityNodeClassifier:
    """
    Classifies textbook content blocks into domain-specific ActivityNode types
    without hardcoded page or unit mappings.
    """

    @classmethod
    def classify_language_block(cls, text: str) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """
        Classify content for LANGUAGE domain (English for Today / Grammar).
        Returns (node_type, title, structured_payload).
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        first_line = lines[0] if lines else ""

        # 1. Dialogue: check for speaker patterns (e.g. "Ruma: Hello", "Teacher: Good morning")
        speaker_lines = [l for l in lines if re.match(r"^[A-Z][a-zA-Z\s]{1,20}\s*:\s+", l)]
        if len(speaker_lines) >= 2 or (len(speaker_lines) >= 1 and len(lines) <= 4):
            speakers = []
            dialogue_turns = []
            for l in lines:
                m = re.match(r"^([A-Z][a-zA-Z\s]{1,20})\s*:\s*(.*)$", l)
                if m:
                    spk = m.group(1).strip()
                    spch = m.group(2).strip()
                    if spk not in speakers:
                        speakers.append(spk)
                    dialogue_turns.append({"speaker": spk, "utterance": spch})
                else:
                    dialogue_turns.append({"speaker": "narrator", "utterance": l})

            return (
                "dialogue",
                "Dialogue",
                {"speakers": speakers, "turns": dialogue_turns},
            )

        # 2. Vocabulary / Glossary: word-definition pairs
        vocab_matches = re.findall(r"^([A-Za-z\s]+)\s*[-–—:]\s*(.+)$", text, re.MULTILINE)
        if len(vocab_matches) >= 2 or re.search(r"(?i)\b(?:vocabulary|key\s+words|glossary)\b", first_line):
            terms = [{"term": m[0].strip(), "meaning": m[1].strip()} for m in vocab_matches]
            return "vocabulary", "Vocabulary", {"terms": terms} if terms else None

        # 3. Grammar Rule
        if re.search(r"(?i)^(?:Grammar|Rule\s*\d*|Structure|Note|Remember)\s*[:.\-—]?", first_line):
            return "grammar_rule", first_line[:60], None

        # 4. Exercise / Questions / Activities
        if re.search(
            r"(?i)\b(?:exercise|questions?|activity|fill\s+in\s+the\s+blanks?|choose\s+the\s+best\s+answer|match\s+the\s+column|answer\s+the\s+following)\b",
            first_line,
        ) or re.search(r"^[0-9]+[.)]\s+", first_line) or re.search(r"^[a-d][.)]\s+", first_line):
            return "exercise", "Exercise", None

        # 5. Instructions / Directives
        if re.search(
            r"(?i)^(?:Look\s+at\s+the|Work\s+in\s+pairs|Discuss\s+in|Read\s+and\s+say|Listen\s+and|Now\s+read)\b",
            first_line,
        ) and len(lines) <= 3:
            return "instruction", "Instruction", None

        # 6. Writing Task / Composition
        if re.search(r"(?i)\b(?:write\s+a\s+paragraph|write\s+a\s+letter|composition|dialogue\s+writing)\b", first_line):
            return "writing_task", "Writing Task", None

        # 7. Reading Passage: continuous multi-sentence narrative
        if len(lines) >= 3 or re.search(r"(?i)\b(?:read\s+the\s+(?:following\s+)?passage|read\s+the\s+text|story)\b", first_line):
            title = first_line[:60] if len(first_line) <= 60 else "Reading Passage"
            return "reading_passage", title, None

        return "generic_text", None, None

    @classmethod
    def classify_stem_block(cls, text: str) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """
        Classify content for STEM / Mathematics domain.
        Returns (node_type, title, structured_payload).
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        first_line = lines[0] if lines else ""

        # 1. Definition
        if re.search(r"(?i)^(?:Definition|Def\.)\s*[:.\-—]?", first_line) or re.search(
            r"(?i)\bis\s+defined\s+as\b", first_line
        ):
            return "definition", "Definition", None

        # 2. Theorem / Proposition / Lemma
        if re.search(r"(?i)^(?:Theorem|Proposition|Corollary|Lemma|Formula)\s*[\d.]*\s*[:.\-—]?", first_line):
            return "theorem", first_line[:60], None

        # 3. Proof
        if re.search(r"(?i)^(?:Proof|Demonstration)\s*[:.\-—]?", first_line):
            return "proof", "Proof", None

        # 4. Worked Example / Solution
        if re.search(r"(?i)^(?:Example|Problem|Worked\s+Example)\s*[\d.]*\s*[:.\-—]?", first_line) or re.search(
            r"(?i)^Solution\s*[:.\-—]?", first_line
        ):
            return "worked_example", first_line[:60], None

        # 5. Mathematics Exercise / Practice Problems
        if re.search(
            r"(?i)\b(?:exercise|practice\s+problems?|questions?|evaluate|solve\s+the\s+following|simplify|find\s+the\s+value)\b",
            first_line,
        ) or re.search(r"^[0-9]+[.)]\s+", first_line):
            return "exercise", "Exercise", None

        # 6. Mathematical Explanation (contains equation symbols, variables, steps)
        if any(sym in text for sym in ["=", "+", "-", "×", "÷", "√", "∈", "⊂", "∑", "∫", "<", ">", "≤", "≥"]):
            return "mathematical_explanation", None, None

        return "generic_text", None, None

    @classmethod
    def classify_block(
        cls,
        text: str,
        domain: str = "GENERAL",
    ) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """
        Main classifier entry point routing to domain-specific archetypes.
        """
        clean_text = text.strip()
        if not clean_text:
            return "generic_text", None, None

        if domain == "LANGUAGE":
            return cls.classify_language_block(clean_text)
        elif domain == "STEM":
            return cls.classify_stem_block(clean_text)
        else:
            # Try Language rules, then STEM rules
            lang_type, lang_title, lang_payload = cls.classify_language_block(clean_text)
            if lang_type != "generic_text":
                return lang_type, lang_title, lang_payload
            return cls.classify_stem_block(clean_text)
