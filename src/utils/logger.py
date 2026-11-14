"""
Configuração de logging da aplicação
"""

import logging
import logging.handlers
from pathlib import Path
from src.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configura o logging da aplicação"""
    
    # Criar diretório de logs se não existir
    log_dir = Path(settings.log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configurar nível de log
    log_level = getattr(logging, settings.log_level.upper())
    
    # Formato de log
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format)
    
    # Handler para arquivo
    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_file,
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    
    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    
    # Configurar logger raiz
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Reduzir verbosidade de bibliotecas externas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.INFO)
