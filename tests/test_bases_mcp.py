"""Testes para a consulta tipada das bases MCP."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.types import TextContent

from triagem_n1_agentes import bases_mcp
from triagem_n1_agentes.modelos import RespostaBases


def test_listar_bases_chama_ferramenta_converte_e_fecha_sessao(monkeypatch) -> None:
    chamadas = []
    dados = {
        "status": "ok",
        "bases": [
            {
                "base": "chamados",
                "descricao": "Chamados abertos.",
                "total": 10,
                "chave": "id",
                "campos": ["id", "tipo", "status"],
                "pode_registrar": True,
                "pode_atualizar": ["status"],
            }
        ],
        "agora": "agora",
    }

    class SessaoFalsa:
        async def __aenter__(self):
            chamadas.append("sessao_aberta")
            return self

        async def __aexit__(self, *_):
            chamadas.append("sessao_fechada")

        async def initialize(self):
            chamadas.append("inicializada")

        async def call_tool(self, nome, argumentos):
            chamadas.append((nome, argumentos))
            return SimpleNamespace(
                isError=False,
                structuredContent=None,
                content=[TextContent(type="text", text=json.dumps(dados))],
            )

    @asynccontextmanager
    async def transporte_falso(url):
        chamadas.append(("transporte_aberto", url))
        try:
            yield object(), object(), lambda: None
        finally:
            chamadas.append("transporte_fechado")

    monkeypatch.setattr(bases_mcp, "streamable_http_client", transporte_falso)
    monkeypatch.setattr(bases_mcp, "ClientSession", lambda *_: SessaoFalsa())

    resposta = asyncio.run(
        bases_mcp.listar_bases_disponiveis("http://localhost:8765/mcp")
    )

    assert isinstance(resposta, RespostaBases)
    assert resposta.bases[0].nome == "chamados"
    assert resposta.bases[0].chave == "id"
    assert resposta.bases[0].campos == ["id", "tipo", "status"]
    assert resposta.bases[0].pode_registrar is True
    assert resposta.bases[0].pode_atualizar == ["status"]
    assert chamadas == [
        ("transporte_aberto", "http://localhost:8765/mcp"),
        "sessao_aberta",
        "inicializada",
        (
            "listar_bases",
            {
                "agente": "orquestrador",
                "motivo": "Descobrir as bases e regras disponíveis no início da execução",
            },
        ),
        "sessao_fechada",
        "transporte_fechado",
    ]


def test_listar_bases_extrai_mensagem_de_erro_mcp(monkeypatch) -> None:
    class SessaoFalsa:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def initialize(self):
            return None

        async def call_tool(self, *_):
            return SimpleNamespace(
                isError=True,
                structuredContent=None,
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "status": "erro",
                                "mensagem": "O servidor demorou para responder.",
                            }
                        ),
                    )
                ],
            )

    @asynccontextmanager
    async def transporte_falso(_url):
        yield object(), object(), lambda: None

    monkeypatch.setattr(bases_mcp, "streamable_http_client", transporte_falso)
    monkeypatch.setattr(bases_mcp, "ClientSession", lambda *_: SessaoFalsa())

    with pytest.raises(
        bases_mcp.ErroRespostaBases,
        match="O servidor demorou para responder.",
    ):
        asyncio.run(bases_mcp.listar_bases_disponiveis("http://localhost:8765/mcp"))


def test_exibir_bases_mostra_dados_e_operacoes(capsys) -> None:
    resposta = RespostaBases.model_validate(
        {
            "status": "ok",
            "bases": [
                {
                    "base": "eventos",
                    "descricao": "Eventos recebidos.",
                    "total": 0,
                    "chave": "id",
                    "campos": ["id", "status"],
                    "pode_registrar": False,
                    "pode_atualizar": ["status"],
                }
            ],
        }
    )

    bases_mcp.exibir_bases(resposta)

    saida = capsys.readouterr().out
    assert "Base: eventos" in saida
    assert "Chave: id" in saida
    assert "Campos: id, status" in saida
    assert "Registrar: não" in saida
    assert "Atualizar: status" in saida
