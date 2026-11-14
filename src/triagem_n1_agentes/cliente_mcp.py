"""Cliente MCP centralizado, com identidade explícita em toda chamada."""

import json
from contextlib import AsyncExitStack
from typing import Any

import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

logger = structlog.get_logger(__name__)


class ErroMCP(Exception):
    """Erro de transporte, ferramenta ou resposta inválida do mundo."""


class ClienteMCP:
    def __init__(self, url: str) -> None:
        self.url = url
        self._stack: AsyncExitStack | None = None
        self._sessao: ClientSession | None = None

    async def __aenter__(self) -> "ClienteMCP":
        self._stack = AsyncExitStack()
        leitura, escrita, _ = await self._stack.enter_async_context(
            streamable_http_client(self.url)
        )
        self._sessao = await self._stack.enter_async_context(
            ClientSession(leitura, escrita)
        )
        await self._sessao.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def _chamar(
        self,
        ferramenta: str,
        argumentos: dict[str, Any],
    ) -> dict[str, Any]:
        if self._sessao is None:
            raise ErroMCP("Cliente MCP não conectado.")
        log_contexto = {
            "tool": ferramenta,
            "agent": argumentos.get("agente", "desconhecido"),
            "event_id": argumentos.get("evento_id"),
        }
        logger.info("mcp_tool_call_started", **log_contexto)
        try:
            resultado = await self._sessao.call_tool(ferramenta, argumentos)
        except Exception as erro:
            logger.error(
                "mcp_tool_call_failed",
                **log_contexto,
                error_type=type(erro).__name__,
            )
            raise
        if resultado.isError:
            detalhes = "\n".join(
                item.text
                for item in resultado.content
                if isinstance(item, TextContent)
            )
            logger.error("mcp_tool_call_failed", **log_contexto)
            raise ErroMCP(detalhes or f"Falha em {ferramenta}.")

        dados = resultado.structuredContent
        if dados is not None:
            logger.info("mcp_tool_call_completed", **log_contexto)
            return dados
        textos = [
            item.text for item in resultado.content if isinstance(item, TextContent)
        ]
        if not textos:
            logger.error("mcp_tool_call_failed", **log_contexto)
            raise ErroMCP(f"{ferramenta} não retornou JSON.")
        try:
            dados = json.loads(textos[0])
        except json.JSONDecodeError as erro:
            logger.error("mcp_tool_call_failed", **log_contexto)
            raise ErroMCP(f"{ferramenta} retornou JSON inválido.") from erro
        logger.info("mcp_tool_call_completed", **log_contexto)
        return dados

    async def proximo_evento(self) -> dict[str, Any]:
        return await self._chamar(
            "proximo_evento",
            {
                "agente": "orquestrador",
                "motivo": "Buscar um evento para o fluxo LangGraph",
                "esperar_segundos": 10,
            },
        )

    async def consultar(
        self,
        base: str,
        *,
        agente: str,
        motivo: str,
        filtro: dict[str, Any] | None = None,
        busca: str | None = None,
        limite: int = 100,
    ) -> list[dict[str, Any]]:
        argumentos: dict[str, Any] = {
            "agente": agente,
            "motivo": motivo,
            "base": base,
            "limite": limite,
            "offset": 0,
        }
        if filtro:
            argumentos["filtro"] = filtro
        if busca:
            argumentos["busca"] = busca
        dados = await self._chamar("consultar", argumentos)
        return list(dados.get("registros", []))

    async def registrar_conversa(
        self,
        *,
        agente: str,
        de: str,
        para: str,
        mensagem: str,
    ) -> None:
        await self._chamar(
            "registrar_conversa",
            {
                "agente": agente,
                "motivo": "Registrar colaboração entre agentes",
                "de": de,
                "para": para,
                "mensagem": mensagem,
            },
        )

    async def responder_evento(
        self, *, evento_id: str, mensagem: str, agente: str, motivo: str,
        aguardar_resposta: bool = False,
    ) -> dict[str, Any]:
        return await self._chamar("responder_evento", {
            "evento_id": evento_id, "mensagem": mensagem,
            "agente": agente, "motivo": motivo,
            "aguardar_resposta": aguardar_resposta,
        })

    async def registrar(
        self, *, base: str, dados: dict[str, Any], evento_id: str,
        agente: str, motivo: str,
    ) -> dict[str, Any]:
        return await self._chamar("registrar", {
            "base": base, "dados": dados, "evento_id": evento_id,
            "agente": agente, "motivo": motivo,
        })

    async def atualizar(
        self, *, base: str, identificador: str, dados: dict[str, Any],
        evento_id: str, agente: str, motivo: str,
    ) -> dict[str, Any]:
        return await self._chamar("atualizar", {
            "base": base, "id": identificador, "dados": dados,
            "evento_id": evento_id, "agente": agente, "motivo": motivo,
        })

    async def enviar_mensagem(
        self, *, para: str, assunto: str, mensagem: str, evento_id: str,
        agente: str, motivo: str,
    ) -> dict[str, Any]:
        return await self._chamar("enviar_mensagem", {
            "para": para, "assunto": assunto, "mensagem": mensagem,
            "evento_id": evento_id, "agente": agente, "motivo": motivo,
        })


async def buscar_contexto_evento(
    cliente: ClienteMCP,
    evento: dict[str, Any],
) -> dict[str, Any]:
    """Busca contexto autorizado; nenhuma chamada altera bases."""
    evento_id = str(evento.get("id", "desconhecido"))
    solicitante = str(evento.get("de", ""))
    motivo = f"Reunir contexto autorizado para o evento {evento_id}"

    faq = await cliente.consultar("faq", agente="triador", motivo=motivo)
    catalogo = await cliente.consultar(
        "catalogo", agente="triador", motivo=motivo
    )
    times = await cliente.consultar("times", agente="triador", motivo=motivo)
    chamados = await cliente.consultar(
        "chamados",
        agente="triador",
        motivo=motivo,
        filtro={"solicitante": solicitante} if solicitante else None,
    )
    incidentes = await cliente.consultar(
        "incidentes", agente="triador", motivo=motivo
    )
    return {
        "faq": faq,
        "catalogo": catalogo,
        "times": times,
        "chamados": chamados,
        "incidentes": incidentes,
    }

