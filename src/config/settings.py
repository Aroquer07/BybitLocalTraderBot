"""Secrets e conexão — carregados do .env (requer restart para alterar)."""

from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Credenciais e endpoints — regras operacionais ficam em data/settings.json."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram (Telethon + Bot API) ---
    telegram_api_id: int = Field(..., description="API ID do Telegram")
    telegram_api_hash: SecretStr = Field(..., description="API Hash do Telegram")
    telegram_session_name: str = Field(default="bybit_bot_session")
    telegram_channel_id: int = Field(..., description="Canal/grupo para escuta de sinais")
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description="Token do bot de notificações (BotFather)",
    )
    telegram_notify_chat_id: int | None = Field(
        default=None,
        description="Chat ID para notificações (@userinfobot)",
    )

    # --- Bybit (CCXT V5) ---
    bybit_mode: Literal["testnet", "demo", "live"] = Field(default="testnet")
    bybit_testnet: bool | None = Field(default=None, description="[legado]")
    bybit_demo: bool | None = Field(default=None, description="[legado]")
    bybit_testnet_api_key: SecretStr | None = None
    bybit_testnet_api_secret: SecretStr | None = None
    bybit_demo_api_key: SecretStr | None = None
    bybit_demo_api_secret: SecretStr | None = None
    bybit_api_key: SecretStr | None = None
    bybit_api_secret: SecretStr | None = None
    bybit_market_type: Literal["linear_swap"] = Field(default="linear_swap")

    # --- Ollama (LLM local) ---
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.2")
    ollama_timeout_seconds: float = Field(default=120.0, ge=10.0)
    ollama_keep_alive: str = Field(default="24h")

    # --- Runtime config (hot-reload) ---
    settings_path: str = Field(
        default="data/settings.json",
        description="Arquivo JSON com regras operacionais (hot-reload)",
    )

    @field_validator("telegram_notify_chat_id", mode="before")
    @classmethod
    def parse_optional_chat_id(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @model_validator(mode="before")
    @classmethod
    def resolve_bybit_mode_from_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("bybit_mode") or data.get("BYBIT_MODE"):
            return data
        demo = data.get("bybit_demo", data.get("BYBIT_DEMO"))
        testnet = data.get("bybit_testnet", data.get("BYBIT_TESTNET"))
        if demo is not None and str(demo).lower() in ("1", "true", "yes"):
            data["bybit_mode"] = "demo"
        elif testnet is not None and str(testnet).lower() in ("0", "false", "no"):
            data["bybit_mode"] = "live"
        elif testnet is not None and str(testnet).lower() in ("1", "true", "yes"):
            data["bybit_mode"] = "testnet"
        return data

    @staticmethod
    def _resolve_secret(primary: SecretStr | None, fallback: SecretStr | None) -> SecretStr | None:
        for candidate in (primary, fallback):
            if candidate is not None and candidate.get_secret_value().strip():
                return candidate
        return None

    def _credentials_for_mode(self) -> tuple[SecretStr | None, SecretStr | None]:
        if self.bybit_mode == "testnet":
            return (
                self._resolve_secret(self.bybit_testnet_api_key, self.bybit_api_key),
                self._resolve_secret(self.bybit_testnet_api_secret, self.bybit_api_secret),
            )
        if self.bybit_mode == "demo":
            return (
                self._resolve_secret(self.bybit_demo_api_key, self.bybit_api_key),
                self._resolve_secret(self.bybit_demo_api_secret, self.bybit_api_secret),
            )
        return self.bybit_api_key, self.bybit_api_secret

    @property
    def active_bybit_api_key(self) -> SecretStr:
        resolved, _ = self._credentials_for_mode()
        if resolved is None:
            raise ValueError(
                f"Credenciais Bybit ({self.bybit_mode}) não configuradas: API key ausente"
            )
        return resolved

    @property
    def active_bybit_api_secret(self) -> SecretStr:
        _, resolved = self._credentials_for_mode()
        if resolved is None:
            raise ValueError(
                f"Credenciais Bybit ({self.bybit_mode}) não configuradas: API secret ausente"
            )
        return resolved

    @model_validator(mode="after")
    def validate_bybit_credentials(self) -> Self:
        self.active_bybit_api_key
        self.active_bybit_api_secret
        return self


@lru_cache
def get_settings() -> Settings:
    """Singleton das configurações de conexão (.env)."""
    return Settings()
