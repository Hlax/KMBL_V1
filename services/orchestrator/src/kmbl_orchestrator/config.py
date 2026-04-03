"""Settings loader — mirrors root .env.example."""

from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import AliasChoices, Field, model_validator
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
    # Mark graph_run rows still "running" longer than this as failed (GET + reconciler). 0 disables.
    orchestrator_running_stale_after_seconds: int = 3600
    # POST /orchestrator/runs/start: max wall time for synchronous persist (thread + graph_run rows).
    # 0 disables (wait indefinitely). Local dev default avoids hanging forever on stuck Supabase I/O.
    orchestrator_run_start_sync_timeout_sec: float = 120.0
    # If true: background work runs only one planner role + persist (no generator/evaluator/staging).
    orchestrator_smoke_planner_only: bool = False
    # When false: POST /orchestrator/invoke-role returns 404 (production uses LangGraph only).
    orchestrator_allow_dev_role_invoke: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KMBL_ORCHESTRATOR_ALLOW_DEV_ROLE_INVOKE",
            "orchestrator_allow_dev_role_invoke",
        ),
    )
    # LOCAL DEV ONLY — when true: empty identity profile silently substitutes DEFAULT_FALLBACK_PROFILE.
    # Default is true for local dev convenience. MUST be false in production / CI to prevent
    # silent identity substitution masquerading as real identity-driven generation.
    # Set KMBL_IDENTITY_ALLOW_FALLBACK_PROFILE=false to enforce real identity data.
    identity_allow_fallback_profile: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "KMBL_IDENTITY_ALLOW_FALLBACK_PROFILE",
            "identity_allow_fallback_profile",
        ),
    )
    # autonomous loop / identity_fetch: fail when seed.confidence is below this (0–1). 0 = disabled.
    identity_minimum_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "KMBL_IDENTITY_MINIMUM_CONFIDENCE",
            "identity_minimum_confidence",
        ),
    )
    # After this many consecutive graph tick failures, autonomous loop status becomes failed.
    autonomous_loop_max_consecutive_failures: int = Field(
        default=5,
        ge=1,
        le=100,
        validation_alias=AliasChoices(
            "KMBL_AUTONOMOUS_LOOP_MAX_CONSECUTIVE_FAILURES",
            "autonomous_loop_max_consecutive_failures",
        ),
    )
    # LangGraph generator↔evaluator loop: default max iterations (exploratory runs; Anthropic-style harness).
    graph_max_iterations_default: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias=AliasChoices(
            "KMBL_GRAPH_MAX_ITERATIONS_DEFAULT",
            "graph_max_iterations_default",
        ),
    )
    # When true, decision "iterate" may route to planner (new build_spec) instead of generator-only.
    graph_replan_on_iterate_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "KMBL_GRAPH_REPLAN_ON_ITERATE_ENABLED",
            "graph_replan_on_iterate_enabled",
        ),
    )
    # Refine + stagnation: replan when working-staging stagnation_count >= this (0 = stagnation-only replan off).
    graph_replan_stagnation_threshold: int = Field(
        default=0,
        ge=0,
        le=100,
        validation_alias=AliasChoices(
            "KMBL_GRAPH_REPLAN_STAGNATION_THRESHOLD",
            "graph_replan_stagnation_threshold",
        ),
    )
    # Cross-run memory: minimum structured-identity confidence to persist identity_derived rows.
    memory_identity_derive_min_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "KMBL_MEMORY_IDENTITY_DERIVE_MIN_CONFIDENCE",
            "memory_identity_derive_min_confidence",
        ),
    )
    # Nudge experience_mode from taste when identity confidence is below this (bias, not override).
    memory_bias_max_identity_confidence: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "KMBL_MEMORY_BIAS_MAX_IDENTITY_CONFIDENCE",
            "memory_bias_max_identity_confidence",
        ),
    )
    # Minimum effective taste strength (after freshness) to apply experience_mode bias.
    memory_bias_min_taste_strength: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "KMBL_MEMORY_BIAS_MIN_TASTE_STRENGTH",
            "memory_bias_min_taste_strength",
        ),
    )
    # Read-time: scale strength when memory is older than this many days (linear fade to ~0.5 at 2x).
    memory_freshness_half_life_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias=AliasChoices(
            "KMBL_MEMORY_FRESHNESS_HALF_LIFE_DAYS",
            "memory_freshness_half_life_days",
        ),
    )
    # Soft cap on distinct memory keys per identity (merge low-value keys when exceeded).
    memory_max_keys_per_identity: int = Field(
        default=48,
        ge=8,
        le=500,
        validation_alias=AliasChoices(
            "KMBL_MEMORY_MAX_KEYS_PER_IDENTITY",
            "memory_max_keys_per_identity",
        ),
    )
    # Absolute URLs in kmbl_session_staging (optional). E.g. http://127.0.0.1:8010 for local agents fetching previews.
    orchestrator_public_base_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "KMBL_ORCHESTRATOR_PUBLIC_BASE_URL",
            "orchestrator_public_base_url",
        ),
    )

    kiloclaw_base_url: str = "https://kiloclaw.example.invalid"
    # KiloClaw gateway OpenAI-compatible chat: POST {base}{path} (default /v1/chat/completions).
    kiloclaw_invoke_path: str = "/v1/chat/completions"
    # OpenAI ``user`` field (gateway session routing). HTTP client appends ``:{thread_id}``
    # from the role payload when present; bare ``kmbl-orchestrator`` alone can trigger
    # gateway 500 on some OpenClaw builds.
    kiloclaw_chat_completions_user: str = "kmbl-orchestrator"
    # auto | stub | http | openclaw_cli — auto: use http when KILOCLAW_API_KEY set, else stub.
    kiloclaw_transport: str = "auto"
    kiloclaw_api_key: str = ""
    # OpenClaw CLI (when kiloclaw_transport=openclaw_cli): executable on PATH, e.g. openclaw
    kiloclaw_openclaw_executable: str = "openclaw"
    kiloclaw_openclaw_timeout_sec: int = 300
    # Must match OpenClaw agents.list ids (see root .env.example — kmbl-planner, not "planner").
    kiloclaw_planner_config_key: str = "kmbl-planner"
    kiloclaw_generator_config_key: str = "kmbl-generator"
    kiloclaw_evaluator_config_key: str = "kmbl-evaluator"
    # OpenClaw agent id for generator when KMBL routes explicit image-generation work (required for image intent).
    # Default kmbl-image-gen; set empty only if image routes must be disabled (will fail closed when intent matches).
    kiloclaw_generator_openai_image_config_key: str = Field(
        default="kmbl-image-gen",
        validation_alias=AliasChoices(
            "KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY",
            "kiloclaw_generator_openai_image_config_key",
        ),
    )
    # Rolling-hour estimated token budget for OpenAI-image generator routing (KMBL-side accounting).
    kmb_openai_image_hourly_token_cap: int = Field(
        default=1_500_000,
        validation_alias=AliasChoices(
            "KMB_OPENAI_IMAGE_HOURLY_TOKEN_CAP", "kmb_openai_image_hourly_token_cap"
        ),
    )
    kmb_openai_image_route_estimated_tokens_per_invocation: int = Field(
        default=12_000,
        validation_alias=AliasChoices(
            "KMB_OPENAI_IMAGE_ROUTE_ESTIMATED_TOKENS_PER_INVOCATION",
            "kmb_openai_image_route_estimated_tokens_per_invocation",
        ),
    )
    # httpx client for KILOCLAW_TRANSPORT=http (chat completions POST).
    kiloclaw_http_connect_timeout_sec: float = 30.0
    kiloclaw_http_read_timeout_sec: float = 300.0
    # OpenAI-style chat completion cap (sent as ``max_tokens``). Planner JSON can be large;
    # omit or lower if your gateway rejects high values.
    kiloclaw_chat_max_tokens_planner: int | None = Field(
        default=8192,
        validation_alias=AliasChoices(
            "KILOCLAW_CHAT_MAX_TOKENS_PLANNER",
            "kiloclaw_chat_max_tokens_planner",
        ),
    )

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = ""

    # When set, mutating HTTP methods require X-API-Key or Authorization: Bearer <same>.
    # Empty (default): no auth (local dev). See docs/16_DEPLOYMENT_ARCHITECTURE.md.
    orchestrator_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ORCHESTRATOR_API_KEY",
            "orchestrator_api_key",
        ),
    )
    # fastapi_background: POST /runs/start enqueues BackgroundTasks (process-local).
    # external_worker: reserved; future queue consumer — see docs/18_DURABLE_GRAPH_RUNS.md.
    orchestrator_graph_run_dispatch: str = Field(
        default="fastapi_background",
        validation_alias=AliasChoices(
            "ORCHESTRATOR_GRAPH_RUN_DISPATCH",
            "orchestrator_graph_run_dispatch",
        ),
    )

    # Image generation via habitat assembly (uses KiloClaw kmbl-image-gen agent).
    # Set to False in tests/CI to skip image generation and use placeholder mode.
    habitat_image_generation_enabled: bool = Field(
        default=True,
        description="Enable image generation during habitat assembly (uses KiloClaw kmbl-image-gen).",
        validation_alias=AliasChoices(
            "HABITAT_IMAGE_GENERATION_ENABLED", "habitat_image_generation_enabled"
        ),
    )
    # When to persist an immutable staging_snapshot row on stage transitions.
    # on_nomination (default): intentional review rows when evaluator nominates — live surface is working_staging.
    # always: every stage (legacy / dense review). never: live only until materialize or policy change.
    staging_snapshot_policy: Literal["always", "on_nomination", "never"] = Field(
        default="on_nomination",
        validation_alias=AliasChoices(
            "KMBL_STAGING_SNAPSHOT_POLICY",
            "staging_snapshot_policy",
        ),
    )
    # deployment: development | test | production — production defaults stub transport off unless overridden
    kmbl_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("KMBL_ENV", "kmbl_env"),
    )
    # None at load: default from kmbl_env (stub allowed except production). Set explicitly to override.
    allow_stub_transport: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("ALLOW_STUB_TRANSPORT", "allow_stub_transport"),
    )

    @model_validator(mode="after")
    def _default_allow_stub_from_env(self) -> "Settings":
        if self.allow_stub_transport is None:
            object.__setattr__(self, "allow_stub_transport", self.kmbl_env != "production")
        return self

    def effective_allow_stub_transport(self) -> bool:
        """Whether stub KiloClaw transport is permitted (handles model_construct without validator)."""
        if self.allow_stub_transport is None:
            return self.kmbl_env != "production"
        return bool(self.allow_stub_transport)

    def effective_kiloclaw_transport(self) -> str:
        """Resolved transport name, or ``invalid`` if configuration fails validation."""
        from kmbl_orchestrator.providers.kiloclaw_protocol import (
            KiloclawTransportConfigError,
            compute_kiloclaw_resolution,
        )

        try:
            return compute_kiloclaw_resolution(self).resolved
        except KiloclawTransportConfigError:
            return "invalid"


@lru_cache
def get_settings() -> Settings:
    """
    Cached for the process lifetime. After changing ``.env`` / environment variables,
    **restart the uvicorn process** so settings reload (``/health`` otherwise reflects stale config).
    """
    return Settings()
