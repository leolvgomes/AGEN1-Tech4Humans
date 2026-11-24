"""Configuração do modelo LangChain compatível com o gateway da T4H."""

from langchain_openai import ChatOpenAI

from triagem_n1_agentes.cliente_ia import normalizar_base_url
from triagem_n1_agentes.configuracao import Configuracao, obter_configuracao


def criar_modelo_langchain(
    configuracao: Configuracao | None = None,
) -> ChatOpenAI:
    """Cria o chat model sem expor a credencial nos logs."""
    config = configuracao or obter_configuracao()
    if config.ai_api_key is None:
        raise ValueError("AI_API_KEY não configurada.")
    if config.ai_base_url is None:
        raise ValueError("AI_BASE_URL não configurada.")
    if not config.ai_model:
        raise ValueError("AI_MODEL não configurado.")

    return ChatOpenAI(
        model=config.ai_model,
        api_key=config.ai_api_key.get_secret_value(),
        base_url=normalizar_base_url(str(config.ai_base_url)),
        temperature=0,
        timeout=30,
        max_retries=1,
    )

