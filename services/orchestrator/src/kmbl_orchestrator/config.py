"""Settings loader — mirrors root .env.example."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

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
    # Smoke / local OpenClaw: omit evaluator preview_url so agents are nudged toward payload-only review
    # (no live page URL for Playwright-style tooling). Does not change LangGraph structure.
    orchestrator_smoke_contract_evaluator: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KMBL_SMOKE_CONTRACT_EVALUATOR",
            "orchestrator_smoke_contract_evaluator",
        ),
    )
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
    # Absolute root for on-disk generator workspaces (local builds). Empty = default under
    # %LOCALAPPDATA%/KMBL/generator_workspaces (Windows) or temp dir/kmb_generator_workspaces.
    kmbl_generator_workspace_root: str = Field(
        default="",
        validation_alias=AliasChoices(
            "KMBL_GENERATOR_WORKSPACE_ROOT",
            "kmbl_generator_workspace_root",
        ),
    )
    # Hard cap for total bytes read during workspace_manifest_v1 ingest (defense in depth).
    kmbl_workspace_ingest_max_bytes_total: int = Field(
        default=2_000_000,
        ge=64_000,
        le=50_000_000,
        validation_alias=AliasChoices(
            "KMBL_WORKSPACE_INGEST_MAX_BYTES_TOTAL",
            "kmbl_workspace_ingest_max_bytes_total",
        ),
    )
    # Static frontend vertical: require workspace_manifest_v1 + sandbox_ref + successful disk ingest
    # (no silent inline-HTML fallback). Default off for legacy runs.
    kmbl_manifest_first_static_vertical: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KMBL_MANIFEST_FIRST_STATIC_VERTICAL",
            "kmbl_manifest_first_static_vertical",
        ),
    )
    # Optional: prune old per-run dirs under kmbl_generator_workspace_root (disabled by default).
    kmbl_generator_workspace_retention_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KMBL_GENERATOR_WORKSPACE_RETENTION_ENABLED",
            "kmbl_generator_workspace_retention_enabled",
        ),
    )
    # Only delete workspace dirs older than this many days (mtime). Ignored when retention disabled.
    kmbl_generator_workspace_retention_min_age_days: float = Field(
        default=14.0,
        ge=0.5,
        le=3650.0,
        validation_alias=AliasChoices(
            "KMBL_GENERATOR_WORKSPACE_RETENTION_MIN_AGE_DAYS",
            "kmbl_generator_workspace_retention_min_age_days",
        ),
    )
    # When true, POST /orchestrator/maintenance/prune-generator-workspaces is allowed (still needs API key if set).
    kmbl_maintenance_prune_http_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KMBL_MAINTENANCE_PRUNE_HTTP_ENABLED",
            "kmbl_maintenance_prune_http_enabled",
        ),
    )

    # Local OpenClaw gateway (OpenAI-compatible). KILOCLAW_* env names remain accepted aliases.
    openclaw_base_url: str = Field(
        default="http://127.0.0.1:18789",
        validation_alias=AliasChoices("OPENCLAW_BASE_URL", "KILOCLAW_BASE_URL"),
    )
    openclaw_invoke_path: str = Field(
        default="/v1/chat/completions",
        validation_alias=AliasChoices("OPENCLAW_INVOKE_PATH", "KILOCLAW_INVOKE_PATH"),
    )
    # OpenAI ``user`` field (gateway session routing). HTTP client appends ``:{thread_id}``.
    openclaw_chat_completions_user: str = Field(
        default="kmbl-orchestrator",
        validation_alias=AliasChoices(
            "OPENCLAW_CHAT_COMPLETIONS_USER",
            "KILOCLAW_CHAT_COMPLETIONS_USER",
        ),
    )
    # auto | stub | http | openclaw_cli
    openclaw_transport: str = Field(
        default="auto",
        validation_alias=AliasChoices("OPENCLAW_TRANSPORT", "KILOCLAW_TRANSPORT"),
    )
    openclaw_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENCLAW_API_KEY", "KILOCLAW_API_KEY"),
    )
    openclaw_openclaw_executable: str = Field(
        default="openclaw",
        validation_alias=AliasChoices(
            "OPENCLAW_OPENCLAW_EXECUTABLE",
            "KILOCLAW_OPENCLAW_EXECUTABLE",
        ),
    )
    openclaw_openclaw_timeout_sec: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "OPENCLAW_OPENCLAW_TIMEOUT_SEC",
            "KILOCLAW_OPENCLAW_TIMEOUT_SEC",
        ),
    )
    openclaw_planner_config_key: str = Field(
        default="kmbl-planner",
        validation_alias=AliasChoices(
            "OPENCLAW_PLANNER_CONFIG_KEY",
            "KILOCLAW_PLANNER_CONFIG_KEY",
        ),
    )
    openclaw_generator_config_key: str = Field(
        default="kmbl-generator",
        validation_alias=AliasChoices(
            "OPENCLAW_GENERATOR_CONFIG_KEY",
            "KILOCLAW_GENERATOR_CONFIG_KEY",
        ),
    )
    openclaw_evaluator_config_key: str = Field(
        default="kmbl-evaluator",
        validation_alias=AliasChoices(
            "OPENCLAW_EVALUATOR_CONFIG_KEY",
            "KILOCLAW_EVALUATOR_CONFIG_KEY",
        ),
    )
    openclaw_generator_openai_image_config_key: str = Field(
        default="kmbl-image-gen",
        validation_alias=AliasChoices(
            "OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY",
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
    openclaw_http_connect_timeout_sec: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "OPENCLAW_HTTP_CONNECT_TIMEOUT_SEC",
            "KILOCLAW_HTTP_CONNECT_TIMEOUT_SEC",
        ),
    )
    openclaw_http_read_timeout_sec: float = Field(
        default=300.0,
        validation_alias=AliasChoices(
            "OPENCLAW_HTTP_READ_TIMEOUT_SEC",
            "KILOCLAW_HTTP_READ_TIMEOUT_SEC",
        ),
    )
    openclaw_chat_max_tokens_planner: int | None = Field(
        default=8192,
        validation_alias=AliasChoices(
            "OPENCLAW_CHAT_MAX_TOKENS_PLANNER",
            "KILOCLAW_CHAT_MAX_TOKENS_PLANNER",
            "kiloclaw_chat_max_tokens_planner",
        ),
    )
    openclaw_chat_max_tokens_generator: int | None = Field(
        default=8192,
        validation_alias=AliasChoices(
            "OPENCLAW_CHAT_MAX_TOKENS_GENERATOR",
            "KILOCLAW_CHAT_MAX_TOKENS_GENERATOR",
            "kiloclaw_chat_max_tokens_generator",
        ),
    )
    openclaw_chat_max_tokens_evaluator: int | None = Field(
        default=8192,
        validation_alias=AliasChoices(
            "OPENCLAW_CHAT_MAX_TOKENS_EVALUATOR",
            "KILOCLAW_CHAT_MAX_TOKENS_EVALUATOR",
            "kiloclaw_chat_max_tokens_evaluator",
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

    # Image generation via habitat assembly (uses OpenClaw kmbl-image-gen agent).
    # Set to False in tests/CI to skip image generation and use placeholder mode.
    habitat_image_generation_enabled: bool = Field(
        default=True,
        description="Enable image generation during habitat assembly (uses OpenClaw kmbl-image-gen).",
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

    # Local Playwright wrapper (``tools/playwright_wrapper``) — HTTP base URL, e.g. http://127.0.0.1:3847
    kmbl_playwright_wrapper_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "KMBL_PLAYWRIGHT_WRAPPER_URL",
            "kmbl_playwright_wrapper_url",
        ),
    )
    kmbl_playwright_max_pages_per_loop: int = Field(
        default=3,
        ge=0,
        le=20,
        validation_alias=AliasChoices(
            "KMBL_PLAYWRIGHT_MAX_PAGES_PER_LOOP",
            "kmbl_playwright_max_pages_per_loop",
        ),
    )
    kmbl_playwright_inspiration_domains: str = Field(
        default=(
            "www.awwwards.com,www.siteinspire.com,dribbble.com,"
            "threejs.org,github.com"
        ),
        validation_alias=AliasChoices(
            "KMBL_PLAYWRIGHT_INSPIRATION_DOMAINS",
            "kmbl_playwright_inspiration_domains",
        ),
    )
    kmbl_playwright_http_timeout_sec: float = Field(
        default=45.0,
        ge=5.0,
        le=300.0,
        validation_alias=AliasChoices(
            "KMBL_PLAYWRIGHT_HTTP_TIMEOUT_SEC",
            "kmbl_playwright_http_timeout_sec",
        ),
    )
    # 0 = never prune operational page_visit_log rows from Supabase (orchestrator-side cleanup).
    kmbl_page_visit_log_retention_days: int = Field(
        default=0,
        ge=0,
        le=3650,
        validation_alias=AliasChoices(
            "KMBL_PAGE_VISIT_LOG_RETENTION_DAYS",
            "kmbl_page_visit_log_retention_days",
        ),
    )
    kmbl_crawl_min_strong_internal_pages: int = Field(
        default=2,
        ge=1,
        le=20,
        validation_alias=AliasChoices(
            "KMBL_CRAWL_MIN_STRONG_INTERNAL_PAGES",
            "kmbl_crawl_min_strong_internal_pages",
        ),
    )
    kmbl_site_memory_stale_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias=AliasChoices(
            "KMBL_SITE_MEMORY_STALE_DAYS",
            "kmbl_site_memory_stale_days",
        ),
    )

    @model_validator(mode="after")
    def _default_allow_stub_from_env(self) -> "Settings":
        if self.allow_stub_transport is None:
            object.__setattr__(self, "allow_stub_transport", self.kmbl_env != "production")
        return self

    @model_validator(mode="after")
    def _validate_supabase_url_shape(self) -> "Settings":
        """Catch obvious misconfiguration before PostgREST returns HTML/Cloudflare pages."""
        url = (self.supabase_url or "").strip()
        key = (self.supabase_service_role_key or "").strip()
        if key and not url:
            raise ValueError(
                "SUPABASE_SERVICE_ROLE_KEY is set but SUPABASE_URL is empty — "
                "set the project API URL (https://<ref>.supabase.co) or remove the key for in-memory mode."
            )
        if not url:
            return self
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(
                f"SUPABASE_URL must use https or http, got scheme={parsed.scheme!r}"
            )
        if not parsed.netloc:
            raise ValueError("SUPABASE_URL is missing a host — check for typos or paste errors.")
        host_l = parsed.netloc.lower()
        if parsed.scheme == "http" and "127.0.0.1" not in host_l and "localhost" not in host_l:
            raise ValueError(
                "SUPABASE_URL may only use http:// for localhost development; use https:// for hosted Supabase."
            )
        if "app.supabase.com" in host_l or "/project/" in url:
            raise ValueError(
                "SUPABASE_URL must be the project's REST API base (e.g. https://<ref>.supabase.co), "
                "not the Supabase dashboard or a /project/… URL."
            )
        return self

    def effective_allow_stub_transport(self) -> bool:
        """Whether stub role-gateway transport is permitted (handles model_construct without validator)."""
        if self.allow_stub_transport is None:
            return self.kmbl_env != "production"
        return bool(self.allow_stub_transport)

    def effective_openclaw_transport(self) -> str:
        """Resolved transport name, or ``invalid`` if configuration fails validation."""
        from kmbl_orchestrator.providers.kiloclaw_protocol import (
            KiloclawTransportConfigError,
            compute_openclaw_resolution,
        )

        try:
            return compute_openclaw_resolution(self).resolved
        except KiloclawTransportConfigError:
            return "invalid"

    def effective_kiloclaw_transport(self) -> str:
        """Deprecated alias for :meth:`effective_openclaw_transport`."""
        return self.effective_openclaw_transport()


@lru_cache
def get_settings() -> Settings:
    """
    Cached for the process lifetime. After changing ``.env`` / environment variables,
    **restart the uvicorn process** so settings reload (``/health`` otherwise reflects stale config).
    """
    return Settings()
