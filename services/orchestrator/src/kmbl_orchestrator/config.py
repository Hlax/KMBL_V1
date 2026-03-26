"""Settings loader — mirrors root .env.example."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve env files from repo layout so imports work no matter the process cwd.
# services/orchestrator/src/kmbl_orchestrator/config.py -> parents[2] = orchestrator dir, [4] = repo root.
_ORCH_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ENV_FILES = (
    _REPO_ROOT / ".env",
    _REPO_ROOT / ".env.local",
    _ORCH_DIR / ".env",
    _ORCH_DIR / ".env.local",
)


class Settings(BaseSettings):
    """Orchestrator configuration. TODO: validate against deployment secrets policy."""

    model_config = SettingsConfigDict(
        # Later files override earlier for the same variable. Missing files are skipped.
        env_file=tuple(str(p) for p in _ENV_FILES),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    orchestrator_host: str = "0.0.0.0"
    orchestrator_port: int = 8000
    # Set false on Windows if --reload causes file-watcher issues (e.g. OneDrive paths).
    orchestrator_reload: bool = True

    kiloclaw_base_url: str = "https://kiloclaw.example.invalid"
    kiloclaw_api_key: str = ""
    kiloclaw_planner_config_key: str = "planner"
    kiloclaw_generator_config_key: str = "generator"
    kiloclaw_evaluator_config_key: str = "evaluator"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
