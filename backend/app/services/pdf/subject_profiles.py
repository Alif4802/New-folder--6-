import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ValidationError
import re

from app.core.config import settings

logger = logging.getLogger("nctb.subject_profiles")


class SubjectDetectionProfile(BaseModel):
    """
    Typed, validated Subject Detection Profile.
    All profile definitions are loaded strictly from data/configuration files (e.g. subject_profiles.json).
    """
    code: str = Field(..., description="Unique subject identifier code, e.g. 'english-for-today'")
    name: str = Field(..., description="Canonical subject display name, e.g. 'English for Today'")
    domain: str = Field(default="GENERAL", description="Curriculum domain: LANGUAGE | STEM | GENERAL")
    aliases: List[str] = Field(default_factory=list, description="Common variations and aliases of the subject name")
    title_patterns: List[str] = Field(default_factory=list, description="Title/cover page matching regex/keywords")
    keywords: List[str] = Field(default_factory=list, description="Content keywords for domain scoring")
    negative_keywords: List[str] = Field(default_factory=list, description="Keywords that disqualify this profile")


def load_profiles_from_json_data(data: Union[List[Dict[str, Any]], Dict[str, Any]]) -> List[SubjectDetectionProfile]:
    """
    Validate and parse a list of raw profile dictionaries into SubjectDetectionProfile objects.
    Raises ValueError with actionable details if schema is malformed.
    """
    if isinstance(data, dict):
        raw_list = data.get("profiles", [])
    elif isinstance(data, list):
        raw_list = data
    else:
        raise ValueError(f"Invalid profile configuration structure: expected list or dict, got {type(data).__name__}")

    if not raw_list:
        raise ValueError("Subject profile configuration contains no profiles.")

    profiles: List[SubjectDetectionProfile] = []
    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"Profile at index {idx} is not a valid JSON object.")
        try:
            profile = SubjectDetectionProfile(**item)
            profiles.append(profile)
        except ValidationError as e:
            raise ValueError(f"Invalid subject profile at index {idx} ({item.get('code', 'unknown')}): {e}") from e

    return profiles


def load_profiles_from_file(file_path: Union[str, Path]) -> List[SubjectDetectionProfile]:
    """
    Load, parse, and validate subject profiles from a JSON configuration file.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Subject profile configuration file not found at: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in subject profile configuration at {path}: {e}") from e

    return load_profiles_from_json_data(data)


class SubjectProfileRegistry:
    """
    Config-driven registry for extensible subject detection.
    Zero textbook-specific profile data is hardcoded in this class.
    """

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self._profiles: List[SubjectDetectionProfile] = []
        self._config_path: Optional[Path] = Path(config_path).resolve() if config_path else None
        self.reload()

    def reload(self) -> None:
        """Reload profiles from the configured JSON file path."""
        target_path = self._config_path or settings.SUBJECT_PROFILES_PATH
        try:
            self._profiles = load_profiles_from_file(target_path)
            logger.info("Loaded %d subject profiles from %s", len(self._profiles), target_path)
        except Exception as e:
            logger.warning("Could not load subject profiles from %s: %s", target_path, e)
            self._profiles = []

    def set_profiles(self, profiles: List[SubjectDetectionProfile]) -> None:
        """Explicitly set loaded profiles (useful for isolated tests)."""
        self._profiles = list(profiles)

    def register_profile(self, profile: SubjectDetectionProfile) -> None:
        """Register an additional subject profile dynamically."""
        # Replace if code already exists
        self._profiles = [p for p in self._profiles if p.code != profile.code]
        self._profiles.append(profile)

    def list_profiles(self) -> List[SubjectDetectionProfile]:
        """Return a copy of all registered profiles."""
        return list(self._profiles)

    def find_best_match(
        self,
        sample_text: str,
        filename: str = "",
    ) -> Optional[SubjectDetectionProfile]:
        """
        Evaluate sample text (early pages) and filename against all registered profiles.
        Returns the highest-scoring profile or None if confidence threshold is not met.
        """
        norm_filename = re.sub(r"[_\-]+", " ", Path(filename).stem) if filename else ""
        combined = f"{norm_filename} {filename} {sample_text}".lower()
        best_profile: Optional[SubjectDetectionProfile] = None
        best_score = 0

        for profile in self._profiles:
            # Check negative keywords first
            if any(neg.lower() in combined for neg in profile.negative_keywords):
                continue

            score = 0

            # 1. Direct title patterns have the highest weight
            patterns_to_check = profile.title_patterns + profile.aliases + [profile.name]
            for pat in patterns_to_check:
                regex = r"\b" + re.escape(pat.lower()) + r"\b"
                if re.search(regex, combined):
                    score += 50

            # 2. Content keyword matching
            for kw in profile.keywords:
                regex = r"\b" + re.escape(kw.lower()) + r"\b"
                matches = len(re.findall(regex, combined))
                score += matches * 5

            if score > best_score and score >= 30:
                best_score = score
                best_profile = profile

        return best_profile


# Global default registry instance
subject_registry = SubjectProfileRegistry()
