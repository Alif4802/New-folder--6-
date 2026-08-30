import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nctb.reconstruction.config")


@dataclass
class LayoutThresholds:
    paragraph_alignment_tolerance_pt: float = 12.0
    max_line_gap_ratio: float = 1.45
    heading_level_1_min_ratio: float = 1.40
    heading_level_2_min_ratio: float = 1.20
    heading_level_3_min_ratio: float = 1.08
    superscript_max_font_size_ratio: float = 0.88
    superscript_min_baseline_offset_ratio: float = 0.18
    subscript_min_baseline_offset_ratio: float = 0.15
    horizontal_char_gap_tolerance_pt: float = 3.0
    table_min_rows: int = 3
    table_min_cols: int = 2
    table_column_alignment_tolerance_pt: float = 8.0
    header_zone_ratio: float = 0.08
    footer_zone_ratio: float = 0.08
    header_footer_min_page_occurrences: int = 2
    header_footer_sample_pages_max: int = 12


@dataclass
class SemanticMarkers:
    example_starters: List[str] = field(default_factory=lambda: ["Example", "Worked Example", "Problem"])
    solution_starters: List[str] = field(default_factory=lambda: ["Solution", "Answer", "Explanation", "Proof"])
    activity_starters: List[str] = field(default_factory=lambda: ["Activity", "Work in pairs", "Look at the picture", "Pair work"])
    exercise_starters: List[str] = field(default_factory=lambda: ["Exercise", "Exercises", "Practice", "Questions and Exercises"])
    definition_starters: List[str] = field(default_factory=lambda: ["Definition", "Theorem", "Rule", "Law", "Formula"])
    note_starters: List[str] = field(default_factory=lambda: ["Note", "N.B.", "Observe", "Remember", "Important"])


@dataclass
class ReconstructionRules:
    layout: LayoutThresholds = field(default_factory=LayoutThresholds)
    markers: SemanticMarkers = field(default_factory=SemanticMarkers)

    @classmethod
    def load_from_file(cls, config_path: Optional[Path] = None) -> "ReconstructionRules":
        if config_path is None:
            # Default to backend/config/reconstruction_rules.json
            config_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "reconstruction_rules.json"

        if not config_path.is_file():
            logger.warning(f"Reconstruction rules config not found at {config_path}. Using built-in defaults.")
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("Reconstruction config root must be a JSON object.")

            layout_data = data.get("layout_thresholds", {})
            markers_data = data.get("semantic_markers", {})

            layout = LayoutThresholds(
                paragraph_alignment_tolerance_pt=float(layout_data.get("paragraph_alignment_tolerance_pt", 12.0)),
                max_line_gap_ratio=float(layout_data.get("max_line_gap_ratio", 1.45)),
                heading_level_1_min_ratio=float(layout_data.get("heading_level_1_min_ratio", 1.40)),
                heading_level_2_min_ratio=float(layout_data.get("heading_level_2_min_ratio", 1.20)),
                heading_level_3_min_ratio=float(layout_data.get("heading_level_3_min_ratio", 1.08)),
                superscript_max_font_size_ratio=float(layout_data.get("superscript_max_font_size_ratio", 0.88)),
                superscript_min_baseline_offset_ratio=float(layout_data.get("superscript_min_baseline_offset_ratio", 0.18)),
                subscript_min_baseline_offset_ratio=float(layout_data.get("subscript_min_baseline_offset_ratio", 0.15)),
                horizontal_char_gap_tolerance_pt=float(layout_data.get("horizontal_char_gap_tolerance_pt", 3.0)),
                table_min_rows=int(layout_data.get("table_min_rows", 3)),
                table_min_cols=int(layout_data.get("table_min_cols", 2)),
                table_column_alignment_tolerance_pt=float(layout_data.get("table_column_alignment_tolerance_pt", 8.0)),
                header_zone_ratio=float(layout_data.get("header_zone_ratio", 0.08)),
                footer_zone_ratio=float(layout_data.get("footer_zone_ratio", 0.08)),
                header_footer_min_page_occurrences=int(layout_data.get("header_footer_min_page_occurrences", 2)),
                header_footer_sample_pages_max=int(layout_data.get("header_footer_sample_pages_max", 12)),
            )

            markers = SemanticMarkers(
                example_starters=list(markers_data.get("example_starters", ["Example", "Worked Example", "Problem"])),
                solution_starters=list(markers_data.get("solution_starters", ["Solution", "Answer", "Explanation", "Proof"])),
                activity_starters=list(markers_data.get("activity_starters", ["Activity", "Work in pairs", "Look at the picture"])),
                exercise_starters=list(markers_data.get("exercise_starters", ["Exercise", "Exercises", "Practice", "Questions and Exercises"])),
                definition_starters=list(markers_data.get("definition_starters", ["Definition", "Theorem", "Rule", "Law", "Formula"])),
                note_starters=list(markers_data.get("note_starters", ["Note", "N.B.", "Observe", "Remember", "Important"])),
            )

            return cls(layout=layout, markers=markers)
        except Exception as exc:
            logger.error(f"Failed to load reconstruction rules config from {config_path}: {exc}")
            raise ValueError(f"Malformed reconstruction config: {exc}") from exc


_global_reconstruction_rules: Optional[ReconstructionRules] = None


def get_reconstruction_rules() -> ReconstructionRules:
    global _global_reconstruction_rules
    if _global_reconstruction_rules is None:
        _global_reconstruction_rules = ReconstructionRules.load_from_file()
    return _global_reconstruction_rules
