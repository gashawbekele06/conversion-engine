"""Runtime configuration for the Conversion Engine.

Environment variables are the single source of truth. Defaults are
safe (everything routes to the staff sink; nothing hits a real prospect).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
TRACES_DIR = REPO_ROOT / "eval" / "traces"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # ---- KILL SWITCH ----
    # Default: unset. When unset, ALL outbound is routed to the staff sink.
    # Flip only after program-staff review. See Data-Handling Policy rule 4.
    tenacious_live: bool = field(default_factory=lambda: _env_bool("TENACIOUS_LIVE", False))

    # ---- Channel credentials (mocked by default) ----
    resend_api_key: str = field(default_factory=lambda: os.getenv("RESEND_API_KEY", ""))
    mailersend_api_key: str = field(default_factory=lambda: os.getenv("MAILERSEND_API_KEY", ""))
    at_api_key: str = field(default_factory=lambda: os.getenv("AT_API_KEY", ""))
    at_username: str = field(default_factory=lambda: os.getenv("AT_USERNAME", "sandbox"))
    hubspot_token: str = field(default_factory=lambda: os.getenv("HUBSPOT_TOKEN", ""))
    calcom_api_key: str = field(default_factory=lambda: os.getenv("CALCOM_API_KEY", ""))
    calcom_event_type_id: str = field(default_factory=lambda: os.getenv("CALCOM_EVENT_TYPE_ID", ""))
    langfuse_public_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY", ""))
    langfuse_secret_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY", ""))
    langfuse_host: str = field(default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))

    # ---- LLM (OpenRouter / Claude / OpenAI) ----
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    
    llm_tier: str = field(default_factory=lambda: os.getenv("LLM_TIER", "dev"))  # dev | eval
    llm_model_dev: str = field(default_factory=lambda: os.getenv("LLM_MODEL_DEV", "qwen/qwen3-next-80b-a3b"))
    llm_model_eval: str = field(default_factory=lambda: os.getenv("LLM_MODEL_EVAL", "claude-sonnet-4-6"))

    # ---- Staff sink ----
    staff_sink_email: str = field(default_factory=lambda: os.getenv("STAFF_SINK_EMAIL", "challenge-sink@tenacious.internal"))
    staff_sink_sms: str = field(default_factory=lambda: os.getenv("STAFF_SINK_SMS", "+10000000000"))

    # ---- Paths ----
    seed_dir: Path = field(default=SEED_DIR)
    traces_dir: Path = field(default=TRACES_DIR)

    @property
    def llm_model(self) -> str:
        return self.llm_model_eval if self.llm_tier == "eval" else self.llm_model_dev


def load_config() -> Config:
    return Config()
