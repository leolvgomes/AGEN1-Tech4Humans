"""Executa um evento real no LangGraph sem habilitar escrita operacional."""

import asyncio
import json
import sys
from typing import Any

from triagem_n1_agentes.cliente_mcp import (
    ClienteMCP,
    ErroMCP,
    buscar_contexto_evento,
)
from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.grafo_langchain import criar_grafo
from triagem_n1_agentes.executor_mcp import executar_aprovado
from triagem_n1_agentes.logs import configurar_logs


async def processar_um_evento() -> dict[str, Any]:
    config = obter_configuracao()
    async with ClienteMCP(str(config.mcp_url)) as cliente:
        caixa = await cliente.proximo_evento()
        evento = caixa.get("evento")
        if evento is None:
            return {
                "status": "SEM_EVENTO",
                "encerrado": bool(caixa.get("encerrado")),
                "mensagem": caixa.get("mensagem"),
            }

        contexto = await buscar_contexto_evento(cliente, evento)
        async def executar(estado: dict[str, Any]) -> dict[str, Any]:
            retorno = await executar_aprovado(
                cliente,
                estado["evento"],
                estado["contexto"],
                estado["decisao"],
                estado["revisao"],
            )
            return {"resultado_execucao": retorno}

        async def registrar_conversa(
            *, agente: str, de: str, para: str, mensagem: str
        ) -> None:
            await cliente.registrar_conversa(
                agente=agente, de=de, para=para, mensagem=mensagem
            )

        resultado = await criar_grafo(
            executor=executar,
            registrar_conversa=registrar_conversa,
        ).ainvoke(
            {"evento": evento, "contexto": contexto}
        )

        decisao = resultado["decisao"]
        revisao = resultado["revisao"]
        if resultado["resultado_execucao"]["status"] == "AGUARDANDO_HUMANO":
            await cliente.registrar_conversa(
                agente="orquestrador",
                de="revisor",
                para="humano",
                mensagem=(
                    f"Evento {evento['id']} requer revisão humana: "
                    f"{revisao.justificativa}"
                ),
            )
        if resultado["resultado_execucao"]["status"] == "EXECUCAO_SIMULADA":
            await cliente.registrar_conversa(
                agente="executor",
                de="revisor",
                para="executor",
                mensagem=(
                    f"evento={evento['id']}; ação aprovada recebida; "
                    "execução MCP mantida desabilitada nesta etapa"
                ),
            )

        return {
            "status": resultado["resultado_execucao"]["status"],
            "evento_id": evento["id"],
            "decisao": decisao.model_dump(mode="json"),
            "revisao": revisao.model_dump(mode="json"),
            "destino": resultado["resultado_execucao"],
        }


def main() -> int:
    configurar_logs(obter_configuracao().nivel_log)
    try:
        resultado = asyncio.run(processar_um_evento())
    except (ErroMCP, ValueError) as erro:
        print(f"Falha no fluxo MCP: {erro}", file=sys.stderr)
        return 1
    except Exception as erro:
        print(f"Falha inesperada no fluxo MCP: {erro}", file=sys.stderr)
        return 1

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

