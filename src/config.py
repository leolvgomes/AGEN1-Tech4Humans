"""Configuração lida de variáveis de ambiente (e do arquivo .env, que fica fora do Git)."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def carregar_env(arquivo: pathlib.Path = RAIZ / ".env") -> None:
    """Lê um .env simples (CHAVE=valor). Variáveis já definidas no ambiente têm prioridade."""
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def _env(nome: str, padrao: str = "") -> str:
    return os.environ.get(nome, "").strip() or padrao


def _num(nome: str, padrao: float) -> float:
    try:
        return float(_env(nome, str(padrao)))
    except ValueError:
        return padrao


def _bool(nome: str, padrao: bool = False) -> bool:
    v = _env(nome, "1" if padrao else "0").lower()
    return v in ("1", "true", "sim", "yes", "on")


@dataclass
class Config:
    # IA (qualquer API compatível com a da OpenAI: OpenAI, gateway do evento, OpenRouter, Gemini, Ollama...)
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_model_revisor: str = ""
    llm_temperatura: float = 0.1
    llm_timeout_s: float = 60
    llm_max_concorrencia: int = 4
    llm_max_por_minuto: int = 120
    llm_json_mode: bool = True

    # Servidor MCP
    mcp_url: str = "http://localhost:8765/mcp"
    mcp_timeout_s: float = 20
    legado_url: str = "http://localhost:8765/legado"

    # Time
    max_casos_paralelos: int = 4
    espera_evento_s: int = 10
    lembrete_aprovacao_s: float = 90
    max_pedidos_info: int = 2
    operador_modo: str = "playwright"  # playwright | http
    operador_headless: bool = True

    # Canal humano
    canal_humano_host: str = "127.0.0.1"
    canal_humano_port: int = 8080

    # Persistência
    dados_dir: pathlib.Path = field(default_factory=lambda: RAIZ / "dados")
    logs_dir: pathlib.Path = field(default_factory=lambda: RAIZ / "logs")

    @property
    def servidor_url(self) -> str:
        """Endereço base do servidor (sem /mcp), usado pelo formulário interno de chamados."""
        url = self.mcp_url.rstrip("/")
        return url[: -len("/mcp")] if url.endswith("/mcp") else url

    @classmethod
    def carregar(cls) -> "Config":
        carregar_env()
        modelo = _env("LLM_MODEL")
        return cls(
            llm_api_key=_env("LLM_API_KEY"),
            llm_model=modelo,
            llm_base_url=_env("LLM_BASE_URL"),
            llm_model_revisor=_env("LLM_MODEL_REVISOR", modelo),
            llm_temperatura=_num("LLM_TEMPERATURA", 0.1),
            llm_timeout_s=_num("LLM_TIMEOUT_S", 60),
            llm_max_concorrencia=int(_num("LLM_MAX_CONCORRENCIA", 4)),
            llm_max_por_minuto=int(_num("LLM_MAX_POR_MINUTO", 120)),
            llm_json_mode=_bool("LLM_JSON_MODE", True),
            mcp_url=_env("MCP_URL", "http://localhost:8765/mcp"),
            mcp_timeout_s=max(15.0, _num("MCP_TIMEOUT_S", 20)),
            legado_url=_env("LEGADO_URL", "http://localhost:8765/legado").rstrip("/"),
            max_casos_paralelos=int(_num("MAX_CASOS_PARALELOS", 4)),
            espera_evento_s=int(min(30, _num("ESPERA_EVENTO_S", 10))),
            lembrete_aprovacao_s=_num("LEMBRETE_APROVACAO_S", 90),
            max_pedidos_info=int(_num("MAX_PEDIDOS_INFO", 2)),
            operador_modo=_env("OPERADOR_MODO", "playwright").lower(),
            operador_headless=_bool("OPERADOR_HEADLESS", True),
            canal_humano_host=_env("CANAL_HUMANO_HOST", "127.0.0.1"),
            canal_humano_port=int(_num("CANAL_HUMANO_PORT", 8080)),
            dados_dir=pathlib.Path(_env("DADOS_DIR", str(RAIZ / "dados"))),
            logs_dir=pathlib.Path(_env("LOGS_DIR", str(RAIZ / "logs"))),
        )

    def problemas_llm(self) -> list[str]:
        faltam = []
        if not self.llm_api_key:
            faltam.append("LLM_API_KEY")
        if not self.llm_model:
            faltam.append("LLM_MODEL")
        return faltam
