"""Descoberta das bases disponíveis no servidor MCP."""

import asyncio
import json
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPError, streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import TextContent
from pydantic import ValidationError

from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.modelos import RespostaBases


class ErroRespostaBases(Exception):
    """Indica erro ou resposta inválida da ferramenta listar_bases."""


async def listar_bases_disponiveis(url: str | None = None) -> RespostaBases:
    """Consulta listar_bases como orquestrador e valida a resposta com Pydantic."""
    endereco = url or str(obter_configuracao().mcp_url)

    async with streamable_http_client(endereco) as (fluxo_leitura, fluxo_escrita, _):
        async with ClientSession(fluxo_leitura, fluxo_escrita) as sessao:
            await sessao.initialize()
            resultado = await sessao.call_tool(
                "listar_bases",
                {
                    "agente": "orquestrador",
                    "motivo": "Descobrir as bases e regras disponíveis no início da execução",
                },
            )

    if resultado.isError:
        detalhes = "\n".join(
            item.text for item in resultado.content if isinstance(item, TextContent)
        )
        try:
            conteudo_erro = json.loads(detalhes)
        except json.JSONDecodeError:
            conteudo_erro = None
        if isinstance(conteudo_erro, dict):
            detalhes = conteudo_erro.get("mensagem", detalhes)
        raise ErroRespostaBases(
            detalhes or "O servidor MCP retornou um erro sem detalhes."
        )

    dados = resultado.structuredContent
    if dados is None:
        textos = [
            item.text for item in resultado.content if isinstance(item, TextContent)
        ]
        if not textos:
            raise ErroRespostaBases(
                "A ferramenta listar_bases não retornou conteúdo JSON."
            )
        try:
            dados = json.loads(textos[0])
        except json.JSONDecodeError as erro:
            raise ErroRespostaBases(
                "A ferramenta listar_bases retornou um JSON inválido."
            ) from erro

    try:
        return RespostaBases.model_validate(dados)
    except ValidationError as erro:
        raise ErroRespostaBases(
            f"A resposta de listar_bases não corresponde ao formato esperado: {erro}"
        ) from erro


def exibir_bases(resposta: RespostaBases) -> None:
    """Imprime nome, chave, campos e permissões de cada base."""
    for base in resposta.bases:
        print(f"Base: {base.nome}")
        print(f"Chave: {base.chave}")
        print(f"Campos: {', '.join(base.campos)}")
        print("Operações permitidas:")
        print(f"  Registrar: {'sim' if base.pode_registrar else 'não'}")
        campos_atualizaveis = ", ".join(base.pode_atualizar) or "nenhum"
        print(f"  Atualizar: {campos_atualizaveis}")
        print()


def main() -> int:
    """Consulta e exibe as bases; não processa eventos."""
    try:
        resposta = asyncio.run(listar_bases_disponiveis())
    except (
        httpx.HTTPError,
        StreamableHTTPError,
        McpError,
        ErroRespostaBases,
    ) as erro:
        print(f"Falha ao listar as bases do servidor MCP: {erro}", file=sys.stderr)
        return 1

    exibir_bases(resposta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
