"""Configuração de logs estruturados em JSON."""

import logging

import structlog


def configurar_logs(nivel: str = "INFO") -> None:
    """Configura logs estruturados para saída padrão."""
    logging.basicConfig(
        level=nivel.upper(),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

