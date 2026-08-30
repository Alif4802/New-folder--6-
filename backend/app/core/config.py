from pathlib import Path
from typing import Any, List, Optional, Union
import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root (one level above backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storage"
DEFAULT_DB_FILE = DEFAULT_DATA_DIR / "nctb_intelligence.db"
DEFAULT_SUBJECT_PROFILES_FILE = PROJECT_ROOT / "backend" / "config" / "subject_profiles.json"
DEFAULT_MCQ_CONFIG_FILE = PROJECT_ROOT / "backend" / "config" / "mcq_generation.json"
DEFAULT_PROMPTS_DIR = PROJECT_ROOT / "backend" / "app" / "prompts"


def _format_sqlite_url(db_path: Path) -> str:
    """Format a Path into a valid SQLite aiosqlite connection string with forward slashes."""
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


class Settings(BaseSettings):
    """Centralized application settings. Loaded from environment variables / .env file."""

    APP_NAME: str = "NCTB Intelligence Demo"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Default to project-controlled data/ directory, resolved predictably regardless of CWD
    DATABASE_URL: str = _format_sqlite_url(DEFAULT_DB_FILE)

    # Allowed CORS origins - accepts JSON list format or comma-separated list
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Local file storage root - configurable override, defaults to project root / storage
    STORAGE_ROOT: Path = DEFAULT_STORAGE_ROOT

    # Subject profiles configuration path
    SUBJECT_PROFILES_PATH: Path = DEFAULT_SUBJECT_PROFILES_FILE

    # MCQ assessment generation configuration path
    MCQ_CONFIG_PATH: Path = DEFAULT_MCQ_CONFIG_FILE

    # Prompts directory path
    PROMPTS_DIR: Path = DEFAULT_PROMPTS_DIR

    # Upload configuration
    MAX_UPLOAD_SIZE_MB: int = 100

    # Assessment profiles configuration path
    ASSESSMENT_PROFILES_PATH: Path = PROJECT_ROOT / "backend" / "config" / "assessment_profiles.json"

    # Default Curriculum Bootstrap Configuration
    DEFAULT_CURRICULUM_CODE: str = "NCTB"
    DEFAULT_CURRICULUM_NAME: str = "National Curriculum and Textbook Board, Bangladesh"
    DEFAULT_CURRICULUM_COUNTRY: str = "Bangladesh"
    DEFAULT_CURRICULUM_AUTHORITY: str = "Ministry of Education"

    # LLM Configuration (Backend only - never expose to frontend)
    LLM_PROVIDER: str = "groq"  # "groq", "gemini", "mock", "router"
    LLM_PRIMARY_PROVIDER: str = "groq"
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_API_KEY: Optional[str] = None
    LLM_MODEL: str = "openai/gpt-oss-120b"
    LLM_API_KEY: Optional[str] = None

    # Fallback Provider Configuration (OpenRouter)
    LLM_FALLBACK_PROVIDER: str = "openrouter"
    OPENROUTER_MODEL: str = "openai/gpt-oss-120b"
    OPENROUTER_API_KEY: Optional[str] = None

    # Failover & Timeout Configuration
    LLM_MAX_AUTO_RETRY_WAIT_SECONDS: float = 8.0
    LLM_PROVIDER_ATTEMPT_TIMEOUT_SECONDS: float = 30.0
    LLM_TOTAL_GENERATION_TIMEOUT_SECONDS: float = 120.0
    LLM_CIRCUIT_RECOVERY_SAFETY_SECONDS: float = 15.0

    # Assessment Generation Oversampling & Batching
    MCQ_CANDIDATE_OVERSAMPLE_RATIO: float = 1.25
    MCQ_CANDIDATE_OVERSAMPLE_MIN: int = 1

    LLM_REASONING_EFFORT: Optional[str] = "medium"
    LLM_THINKING_LEVEL: str = "medium"  # "low", "medium", "high", "off" (for Gemini)
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: float = 60.0

    # LLM Token & Rate Budget Configuration (Backend only)
    LLM_TPM_LIMIT: int = 8000
    LLM_REQUEST_TOKEN_TARGET: int = 2800
    LLM_VERIFY_REQUEST_TOKEN_TARGET: int = 4000
    LLM_OUTPUT_TOKEN_RESERVE: int = 1500
    LLM_RATE_LIMIT_SAFETY_RATIO: float = 0.85

    # Assessment Generation Limits & Operational Runaway Safety Limits
    MCQ_MAX_TOTAL_QUESTIONS: Optional[int] = None
    MCQ_MAX_GENERATION_ROUNDS: int = 6
    MCQ_MAX_PROVIDER_CALLS_PER_JOB: int = 12

    # Derived Structure and Metadata Parser Versions & Limits
    METADATA_FRONT_MATTER_MAX_PAGES: int = 8
    CURRICULUM_PARSER_VERSION: str = "v2.0"
    METADATA_RESOLVER_VERSION: str = "v2.0"

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_trimmed = v.strip()
            if not v_trimmed:
                return []
            if v_trimmed.startswith("[") and v_trimmed.endswith("]"):
                try:
                    parsed = json.loads(v_trimmed)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in v_trimmed.split(",") if origin.strip()]
        elif isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @field_validator("STORAGE_ROOT", mode="before")
    @classmethod
    def resolve_storage_root(cls, v: Any) -> Path:
        if isinstance(v, (str, Path)):
            p = Path(v)
            if not p.is_absolute():
                return (PROJECT_ROOT / p).resolve()
            return p.resolve()
        return DEFAULT_STORAGE_ROOT.resolve()

    @field_validator("SUBJECT_PROFILES_PATH", mode="before")
    @classmethod
    def resolve_subject_profiles_path(cls, v: Any) -> Path:
        if isinstance(v, (str, Path)):
            p = Path(v)
            if not p.is_absolute():
                return (PROJECT_ROOT / p).resolve()
            return p.resolve()
        return DEFAULT_SUBJECT_PROFILES_FILE.resolve()

    @field_validator("MCQ_CONFIG_PATH", mode="before")
    @classmethod
    def resolve_mcq_config_path(cls, v: Any) -> Path:
        if isinstance(v, (str, Path)):
            p = Path(v)
            if not p.is_absolute():
                return (PROJECT_ROOT / p).resolve()
            return p.resolve()
        return DEFAULT_MCQ_CONFIG_FILE.resolve()

    @field_validator("PROMPTS_DIR", mode="before")
    @classmethod
    def resolve_prompts_dir(cls, v: Any) -> Path:
        if isinstance(v, (str, Path)):
            p = Path(v)
            if not p.is_absolute():
                return (PROJECT_ROOT / p).resolve()
            return p.resolve()
        return DEFAULT_PROMPTS_DIR.resolve()

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def resolve_database_url(cls, v: Any) -> str:
        if isinstance(v, str) and v.strip():
            url_str = v.strip()
            # If relative sqlite path provided (e.g. sqlite+aiosqlite:///./data/foo.db)
            if url_str.startswith("sqlite+aiosqlite:///./") or url_str.startswith("sqlite+aiosqlite://../"):
                rel_path = url_str.split("sqlite+aiosqlite:///", 1)[1]
                abs_path = (PROJECT_ROOT / rel_path).resolve()
                return _format_sqlite_url(abs_path)
            return url_str
        return _format_sqlite_url(DEFAULT_DB_FILE)

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def storage_pdfs_dir(self) -> Path:
        return self.STORAGE_ROOT / "pdfs"

    @property
    def storage_images_dir(self) -> Path:
        return self.STORAGE_ROOT / "images"

    @property
    def storage_staging_dir(self) -> Path:
        return self.STORAGE_ROOT / "staging"

    @property
    def data_dir(self) -> Path:
        return DEFAULT_DATA_DIR


settings = Settings()

