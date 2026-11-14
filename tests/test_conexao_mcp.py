"""Testes do comando de conexão MCP sem depender de um servidor em execução."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx

from triagem_n1_agentes import conexao_mcp


def test_listar_ferramentas_abre_e_fecha_sessao(monkeypatch) -> None:
    chamadas = []

    class SessaoFalsa:
        async def __aenter__(self):
            chamadas.append("sessao_aberta")
            return self

        async def __aexit__(self, *_):
            chamadas.append("sessao_fechada")

        async def initialize(self):
            chamadas.append("inicializada")

        async def list_tools(self, cursor=None):
            chamadas.append(("ferramentas_listadas", cursor))
            if cursor is None:
                return SimpleNamespace(
                    tools=[SimpleNamespace(name="consultar_status")],
                    nextCursor="pagina-2",
                )
            return SimpleNamespace(
                tools=[SimpleNamespace(name="buscar_solicitacoes")],
                nextCursor=None,
            )

    @asynccontextmanager
    async def transporte_falso(url):
        chamadas.append(("transporte_aberto", url))
        try:
            yield object(), object(), lambda: None
        finally:
            chamadas.append("transporte_fechado")

    monkeypatch.setattr(conexao_mcp, "streamable_http_client", transporte_falso)
    monkeypatch.setattr(conexao_mcp, "ClientSession", lambda *_: SessaoFalsa())

    nomes = asyncio.run(conexao_mcp.listar_ferramentas("http://localhost:8765/mcp"))

    assert nomes == ["consultar_status", "buscar_solicitacoes"]
    assert chamadas == [
        ("transporte_aberto", "http://localhost:8765/mcp"),
        "sessao_aberta",
        "inicializada",
        ("ferramentas_listadas", None),
        ("ferramentas_listadas", "pagina-2"),
        "sessao_fechada",
        "transporte_fechado",
    ]


def test_main_exibe_erro_quando_servidor_nao_responde(monkeypatch, capsys) -> None:
    class ConfiguracaoFalsa:
        mcp_url = "http://localhost:8765/mcp"

    async def falhar_conexao(_url):
        raise httpx.ConnectError("conexão recusada")

    monkeypatch.setattr(conexao_mcp, "obter_configuracao", lambda: ConfiguracaoFalsa())
    monkeypatch.setattr(conexao_mcp, "listar_ferramentas", falhar_conexao)

    codigo_saida = conexao_mcp.main()
    erro = capsys.readouterr().err

    assert codigo_saida == 1
    assert "Não foi possível conectar" in erro
    assert "http://localhost:8765/mcp" in erro
    assert "Verifique se o servidor está em execução" in erro
