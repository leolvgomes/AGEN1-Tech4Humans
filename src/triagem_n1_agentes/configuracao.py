"""Configuração do projeto por variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracao(BaseSettings):
    """Configurações tipadas carregadas do ambiente ou de um arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRIAGEM_",
        extra="ignore",
    )

    mcp_url: HttpUrl = Field(default="http://localhost:8765/mcp")
    banco_caminho: Path = Field(default=Path("data/triagem.db"))
    nivel_log: str = Field(default="INFO")
    ai_api_key: SecretStr | None = Field(default=None, validation_alias="AI_API_KEY")
    ai_base_url: HttpUrl | None = Field(default=None, validation_alias="AI_BASE_URL")
    ai_model: str | None = Field(default=None, validation_alias="AI_MODEL")


@lru_cache
def obter_configuracao() -> Configuracao:
    """Retorna a configuração carregada uma única vez por processo."""
    return Configuracao()

