"""Grafo seguro Triador → Revisor → políticas → destino simulado."""

import asyncio
import json
import sys
from typing import Any
from collections.abc import Awaitable, Callable

import structlog
from langgraph.graph import END, START, StateGraph

from triagem_n1_agentes.estado_grafo import EstadoTriagem
from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.logs import configurar_logs
from triagem_n1_agentes.modelo_langchain import criar_modelo_langchain
from triagem_n1_agentes.modelos import DecisaoTriagem, RevisaoTriagem
from triagem_n1_agentes.nos_grafo import (
    ModeloEstruturado,
    RegistradorConversa,
    aguardar_humano,
    aplicar_politicas,
    criar_no_revisor,
    criar_no_triador,
    decidir_destino,
    executar_simulado,
    registrar_rejeicao,
)

logger = structlog.get_logger(__name__)


def criar_grafo(
    triador: ModeloEstruturado | None = None,
    revisor: ModeloEstruturado | None = None,
    executor: Callable[[EstadoTriagem], Awaitable[dict[str, Any]]] | None = None,
    registrar_conversa: RegistradorConversa | None = None,
):
    """Compila o grafo; modelos falsos podem ser injetados nos testes."""
    if triador is None or revisor is None:
        modelo = criar_modelo_langchain()
        triador = triador or modelo.with_structured_output(
            DecisaoTriagem,
            method="json_mode",
        )
        revisor = revisor or modelo.with_structured_output(
            RevisaoTriagem,
            method="json_mode",
        )

    construtor = StateGraph(EstadoTriagem)
    construtor.add_node(
        "triador", criar_no_triador(triador, registrar_conversa)
    )
    construtor.add_node(
        "revisor", criar_no_revisor(revisor, registrar_conversa)
    )
    construtor.add_node("politicas", aplicar_politicas)
    construtor.add_node("humano", aguardar_humano)
    async def executar_com_log(estado: EstadoTriagem) -> dict[str, Any]:
        evento_id = str(estado["evento"].get("id", "desconhecido"))
        logger.info("agent_call_started", agent="executor", event_id=evento_id)
        try:
            resultado = await (executor or executar_simulado)(estado)
        except Exception as erro:
            logger.error(
                "agent_call_failed",
                agent="executor",
                event_id=evento_id,
                error_type=type(erro).__name__,
            )
            raise
        logger.info(
            "agent_call_completed",
            agent="executor",
            event_id=evento_id,
            status=resultado.get("resultado_execucao", {}).get("status"),
        )
        return resultado

    construtor.add_node("executor", executar_com_log)
    construtor.add_node("rejeitado", registrar_rejeicao)

    construtor.add_edge(START, "triador")
    construtor.add_edge("triador", "revisor")
    construtor.add_edge("revisor", "politicas")
    construtor.add_conditional_edges(
        "politicas",
        decidir_destino,
        {
            "humano": "humano",
            "executor": "executor",
            "rejeitado": "rejeitado",
        },
    )
    construtor.add_edge("humano", END)
    construtor.add_edge("executor", END)
    construtor.add_edge("rejeitado", END)
    return construtor.compile()


def _estado_demonstracao() -> EstadoTriagem:
    return {
        "evento": {
            "id": "LANGGRAPH-DEMO-001",
            "de": "marina.alves@t4h.exemplo",
            "assunto": "Dúvida sobre VPN",
            "corpo": "Como conecto o notebook novo à VPN de casa?",
        },
        "contexto": {
            "faq": [
                {
                    "id": "FAQ-01",
                    "pergunta": "Como me conecto à VPN?",
                    "resposta": (
                        "Instale o cliente pela Central de Software e entre com "
                        "seu usuário e senha da rede."
                    ),
                }
            ],
            "catalogo": [],
            "chamados": [],
            "incidentes": [],
        },
    }


async def demonstrar() -> dict[str, Any]:
    return await criar_grafo().ainvoke(_estado_demonstracao())


def main() -> int:
    """Demonstra o grafo com executor simulado e sem consumir o MCP."""
    configurar_logs(obter_configuracao().nivel_log)
    try:
        resultado = asyncio.run(demonstrar())
    except Exception as erro:
        print(f"Falha na demonstração LangGraph: {erro}", file=sys.stderr)
        return 1

    resumo = {
        "decisao": resultado["decisao"].model_dump(mode="json"),
        "revisao": resultado["revisao"].model_dump(mode="json"),
        "exige_humano": resultado["exige_humano"],
        "resultado_execucao": resultado["resultado_execucao"],
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

