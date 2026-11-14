"""Configuração do projeto por variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracao(BaseSettings):
    """Configurações tipadas carregadas do ambiente ou de um arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRIAGEM_",
        extra="ignore",
    )

    mcp_url: HttpUrl = Field(default="http://localhost:8765/mcp")
    legado_url: HttpUrl = Field(default="http://localhost:8765/legado")
    legado_origens_permitidas: str = Field(default="http://localhost:8765")
    banco_caminho: Path = Field(default=Path("data/triagem.db"))
    legado_perfil: Path = Field(default=Path("data/legado-browser"))
    legado_capturas: Path = Field(default=Path("data/legado-capturas"))
    nivel_log: str = Field(default="INFO")
    aprovador: str | None = Field(default=None)
    legado_modelo: str | None = Field(default=None)
    legado_headless: bool = Field(default=True)
    ai_api_key: SecretStr | None = Field(default=None, validation_alias="AI_API_KEY")
    ai_base_url: HttpUrl | None = Field(default=None, validation_alias="AI_BASE_URL")
    ai_model: str | None = Field(default=None, validation_alias="AI_MODEL")

    @field_validator("aprovador")
    @classmethod
    def validar_aprovador(cls, valor: str | None) -> str | None:
        """Aceita apenas o endereço interno usado para aprovações."""
        if valor is None or not valor.strip():
            return None
        endereco = valor.strip()
        if not endereco.lower().endswith("@t4h.exemplo"):
            raise ValueError("TRIAGEM_APROVADOR deve usar o domínio @t4h.exemplo.")
        return endereco


@lru_cache
def obter_configuracao() -> Configuracao:
    """Retorna a configuração carregada uma única vez por processo."""
    return Configuracao()

