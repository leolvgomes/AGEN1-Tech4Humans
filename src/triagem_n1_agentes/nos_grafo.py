"""Nós inteligentes e determinísticos do fluxo LangGraph."""

import json
from typing import Any, Protocol

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from triagem_n1_agentes.estado_grafo import EstadoTriagem
from triagem_n1_agentes.modelos import (
    AcaoProposta,
    Criticidade,
    DecisaoTriagem,
    NivelRiscoSeguranca,
    RevisaoTriagem,
)
from triagem_n1_agentes.prompts import carregar_prompt

logger = structlog.get_logger(__name__)


class ModeloEstruturado(Protocol):
    async def ainvoke(self, entrada: Any) -> Any: ...


class RegistradorConversa(Protocol):
    async def __call__(
        self, *, agente: str, de: str, para: str, mensagem: str
    ) -> None: ...


def criar_no_triador(
    modelo: ModeloEstruturado,
    registrar_conversa: RegistradorConversa | None = None,
):
    async def executar_triador(estado: EstadoTriagem) -> dict[str, Any]:
        evento = estado["evento"]
        evento_id = str(evento.get("id", "desconhecido"))
        entrada = json.dumps(
            {
                "evento": evento,
                "contexto_autorizado": estado["contexto"],
            },
            ensure_ascii=False,
            default=str,
        )
        logger.info("agent_call_started", agent="triador", event_id=evento_id)
        try:
            decisao: DecisaoTriagem = await modelo.ainvoke(
                [
                    SystemMessage(content=carregar_prompt("TRIADOR")),
                    HumanMessage(
                        content=(
                            "Analise usando somente o contexto autorizado e devolva "
                            "exclusivamente um objeto JSON.\n\n" + entrada
                        )
                    ),
                ]
            )
            # O modelo nunca pode substituir o evento de origem.
            decisao = decisao.model_copy(update={"evento": evento})
        except Exception as erro:
            logger.error(
                "agent_call_failed",
                agent="triador",
                event_id=evento_id,
                error_type=type(erro).__name__,
            )
            raise
        logger.info(
            "agent_call_completed",
            agent="triador",
            event_id=evento_id,
            categoria=decisao.categoria.value,
            criticidade=decisao.criticidade.value,
            acao_proposta=decisao.acao_proposta.value,
        )
        if registrar_conversa is not None:
            await registrar_conversa(
                agente="triador",
                de="triador",
                para="revisor",
                mensagem=(
                    f"Evento {evento.get('id')}: proposta de ação "
                    f"{decisao.acao_proposta}, criticidade "
                    f"{decisao.criticidade}. Motivo: {decisao.justificativa}"
                ),
            )
        return {"decisao": decisao}

    return executar_triador


def criar_no_revisor(
    modelo: ModeloEstruturado,
    registrar_conversa: RegistradorConversa | None = None,
):
    async def executar_revisor(estado: EstadoTriagem) -> dict[str, Any]:
        evento_id = str(estado["evento"].get("id", "desconhecido"))
        entrada = json.dumps(
            {
                "evento": estado["evento"],
                "contexto_autorizado": estado["contexto"],
                "decisao_do_triador": estado["decisao"].model_dump(mode="json"),
            },
            ensure_ascii=False,
            default=str,
        )
        logger.info("agent_call_started", agent="revisor", event_id=evento_id)
        try:
            revisao: RevisaoTriagem = await modelo.ainvoke(
                [
                    SystemMessage(content=carregar_prompt("REVISOR")),
                    HumanMessage(
                        content=(
                            "Revise usando somente os dados fornecidos e devolva "
                            "exclusivamente um objeto JSON.\n\n" + entrada
                        )
                    ),
                ]
            )
            # O evento de origem também prevalece na revisão.
            revisao = revisao.model_copy(update={"evento_id": evento_id})
        except Exception as erro:
            logger.error(
                "agent_call_failed",
                agent="revisor",
                event_id=evento_id,
                error_type=type(erro).__name__,
            )
            raise
        logger.info(
            "agent_call_completed",
            agent="revisor",
            event_id=evento_id,
            aprovado=revisao.aprovado,
            exige_humano=revisao.exige_humano,
            criticidade=revisao.criticidade_confirmada.value,
        )
        if registrar_conversa is not None:
            await registrar_conversa(
                agente="revisor",
                de="revisor",
                para="orquestrador",
                mensagem=(
                    f"Evento {revisao.evento_id}: "
                    f"{'aprovado' if revisao.aprovado else 'rejeitado'}; "
                    f"exige humano={revisao.exige_humano}; "
                    f"criticidade confirmada={revisao.criticidade_confirmada}. "
                    f"Motivo: {revisao.justificativa}"
                ),
            )
        return {"revisao": revisao}

    return executar_revisor


async def aplicar_politicas(estado: EstadoTriagem) -> dict[str, Any]:
    """Barreira determinística posterior às decisões da IA."""
    decisao = estado["decisao"]
    revisao = estado["revisao"]
    exige_humano = revisao.exige_humano

    if decisao.dado_sensivel_presente:
        exige_humano = True
    if decisao.risco_seguranca in {
        NivelRiscoSeguranca.ALTO,
        NivelRiscoSeguranca.CRITICO,
    }:
        exige_humano = True
    if decisao.criticidade in {Criticidade.P0, Criticidade.P1}:
        exige_humano = True
    if decisao.necessita_aprovacao:
        exige_humano = True
    if decisao.acao_proposta is AcaoProposta.REGISTRAR_FERIAS_LEGADO:
        exige_humano = True

    return {"exige_humano": exige_humano}


def decidir_destino(estado: EstadoTriagem) -> str:
    if estado["exige_humano"]:
        return "humano"
    if not estado["revisao"].aprovado:
        return "rejeitado"
    return "executor"


async def aguardar_humano(_estado: EstadoTriagem) -> dict[str, Any]:
    return {"resultado_execucao": {"status": "AGUARDANDO_HUMANO"}}


async def executar_simulado(_estado: EstadoTriagem) -> dict[str, Any]:
    return {
        "resultado_execucao": {
            "status": "EXECUCAO_SIMULADA",
            "aviso": "Nenhuma ferramenta MCP foi chamada.",
        }
    }


async def registrar_rejeicao(estado: EstadoTriagem) -> dict[str, Any]:
    return {
        "resultado_execucao": {
            "status": "REJEITADO",
            "problemas": estado["revisao"].problemas,
        }
    }

