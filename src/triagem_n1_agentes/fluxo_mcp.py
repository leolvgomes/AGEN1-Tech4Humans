"""Executa um evento MCP e encaminha aprovações humanas para uma fila local."""

import asyncio
import json
import sys
from typing import Any

import structlog

from triagem_n1_agentes.cliente_mcp import (
    ClienteMCP,
    ErroMCP,
    buscar_contexto_evento,
)
from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.grafo_langchain import criar_grafo
from triagem_n1_agentes.executor_mcp import executar_aprovado
from triagem_n1_agentes.aprovacoes_humanas import FilaAprovacaoHumana
from triagem_n1_agentes.logs import configurar_logs
from triagem_n1_agentes.modelos import AcaoProposta

logger = structlog.get_logger(__name__)


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

        evento_id = str(evento["id"])
        fila_aprovacoes = FilaAprovacaoHumana(config.banco_caminho)
        tarefa_existente = fila_aprovacoes.obter(evento_id)
        if tarefa_existente is not None:
            return {
                "status": f"APROVACAO_{tarefa_existente.status}",
                "evento_id": evento_id,
                "mensagem": "Evento já registrado na fila de aprovação humana.",
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
        notificacao = "nao_aplicavel"
        if resultado["resultado_execucao"]["status"] == "AGUARDANDO_HUMANO":
            fila_aprovacoes.registrar_pendente(
                evento_id,
                {
                    "evento": evento,
                    "decisao": decisao.model_dump(mode="json"),
                    "revisao": revisao.model_dump(mode="json"),
                },
            )
            mensagem = (
                f"Aprovação necessária para o evento {evento_id}.\n"
                f"Criticidade: {decisao.criticidade.value}\n"
                f"Ação proposta: {revisao.acao_confirmada or decisao.acao_proposta}.\n"
                "Consulte o evento original no sistema de atendimento antes de decidir."
            )
            if revisao.acao_confirmada is AcaoProposta.REGISTRAR_FERIAS_LEGADO:
                mensagem += (
                    "\nDados da solicitação: "
                    f"colaborador={decisao.campos_extraidos.get('colaborador')}; "
                    f"início={decisao.campos_extraidos.get('data_inicio')}; "
                    f"fim={decisao.campos_extraidos.get('data_fim')}."
                )
            try:
                await cliente.registrar_conversa(
                    agente="orquestrador",
                    de="revisor",
                    para="humano",
                    mensagem=mensagem,
                )
            except Exception as erro:
                # A fila local já está persistida; falha de auditoria não a remove.
                logger.warning(
                    "human_escalation_conversation_log_failed",
                    event_id=evento_id,
                    error_type=type(erro).__name__,
                )
            if config.aprovador:
                try:
                    await cliente.enviar_mensagem(
                        para=config.aprovador,
                        assunto=f"Aprovação de triagem: {evento_id}",
                        mensagem=(
                            mensagem
                            + "\n\nExemplo de aprovação: "
                            ".venv/bin/python -m "
                            "triagem_n1_agentes.aprovacoes_humanas decidir "
                            "--evento-id "
                            f"{evento_id} --decisao aprovar "
                            "--aprovador SEU_NOME --motivo 'sua justificativa'."
                            " Para negar, use --decisao rejeitar."
                        ),
                        evento_id=evento_id,
                        agente="orquestrador",
                        motivo="Solicitar aprovação humana de evento escalado",
                    )
                    notificacao = "enviada"
                except Exception as erro:
                    # A tarefa local permanece pendente para não perder o evento.
                    notificacao = f"falhou:{type(erro).__name__}"
            else:
                notificacao = "pendente_sem_destinatario"
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
            "notificacao_humana": notificacao,
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

