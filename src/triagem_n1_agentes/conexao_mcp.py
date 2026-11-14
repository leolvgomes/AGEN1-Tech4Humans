"""Comando para verificar a conexão e listar ferramentas do servidor MCP."""

import asyncio
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPError, streamable_http_client
from mcp.shared.exceptions import McpError

from triagem_n1_agentes.configuracao import obter_configuracao


async def listar_ferramentas(url: str) -> list[str]:
    """Conecta via Streamable HTTP e retorna os nomes das ferramentas disponíveis."""
    async with streamable_http_client(url) as (fluxo_leitura, fluxo_escrita, _):
        async with ClientSession(fluxo_leitura, fluxo_escrita) as sessao:
            await sessao.initialize()
            nomes = []
            cursor = None
            while True:
                resultado = await sessao.list_tools(cursor=cursor)
                nomes.extend(ferramenta.name for ferramenta in resultado.tools)
                cursor = resultado.nextCursor
                if cursor is None:
                    return nomes


def main() -> int:
    """Executa o teste de conexão e apresenta o resultado no terminal."""
    url = str(obter_configuracao().mcp_url)

    try:
        nomes = asyncio.run(listar_ferramentas(url))
    except (httpx.HTTPError, StreamableHTTPError, McpError) as erro:
        print(
            f"Não foi possível conectar ou consultar as ferramentas do servidor MCP "
            f"em {url}: {erro}\n"
            "Verifique se o servidor está em execução e se o endereço está correto.",
            file=sys.stderr,
        )
        return 1

    print(f"Ferramentas disponíveis em {url}:")
    if nomes:
        for nome in nomes:
            print(f"- {nome}")
    else:
        print("Nenhuma ferramenta disponível.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
