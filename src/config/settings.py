"""
Configurações da aplicação
"""

from pydantic_settings import BaseSettings
from typing import Optional
import logging


class Settings(BaseSettings):
    """Configurações da aplicação"""

    # LLM Configuration
    openai_api_key: str
    openai_model: str = "gpt-4-turbo"

    # MCP Server Configuration
    mcp_server_url: str = "http://localhost:8000"
    mcp_server_timeout: int = 30

    # Email Configuration
    email_fetch_interval: int = 300  # seconds
    email_batch_size: int = 10

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/app.log"

    # Database
    database_url: Optional[str] = "sqlite:///data/triagem.db"

    # Agent Configuration
    agent_temperature: float = 0.3
    agent_max_tokens: int = 2000

    # Security
    enable_security_checks: bool = True
    enable_pii_detection: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False


def get_settings() -> Settings:
    """Retorna as configurações da aplicação"""
    return Settings()


def setup_logging(settings: Settings) -> None:
    """Configura o logging da aplicação"""
    log_level = getattr(logging, settings.log_level.upper())
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(settings.log_file),
            logging.StreamHandler()
        ]
    )
