import asyncio
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr

from triagem_n1_agentes.cliente_ia import (
    normalizar_base_url,
    testar_conexao as executar_teste_conexao,
)
from triagem_n1_agentes.configuracao import Configuracao


def test_conexao_ia_aceita_resposta_controlada(monkeypatch):
    configuracao = Configuracao(
        AI_API_KEY=SecretStr("chave-de-teste"),
        AI_BASE_URL="https://gateway.exemplo/v1",
        AI_MODEL="modelo-teste",
        _env_file=None,
    )
    resposta = MagicMock()
    resposta.choices = [MagicMock(message=MagicMock(content="CONEXAO_OK"))]
    cliente = MagicMock()
    cliente.chat.completions.create = AsyncMock(return_value=resposta)
    cliente.close = AsyncMock()

    monkeypatch.setattr(
        "triagem_n1_agentes.cliente_ia.criar_cliente",
        lambda _configuracao: cliente,
    )

    assert asyncio.run(executar_teste_conexao(configuracao)) is True
    cliente.close.assert_awaited_once()


def test_normaliza_endpoint_completo_de_chat():
    assert normalizar_base_url(
        "https://gateway.exemplo/v1/chat/completions"
    ) == "https://gateway.exemplo/v1"

