"""Executor restrito: recebe somente decisão validada pelo Revisor."""

from typing import Any

from triagem_n1_agentes.cliente_mcp import ClienteMCP
from triagem_n1_agentes.modelos import (
    AcaoProposta,
    Criticidade,
    DecisaoTriagem,
    NivelRiscoSeguranca,
    RevisaoTriagem,
)


class ErroExecucaoSegura(Exception):
    """A ação não tem dados suficientes ou excede a política permitida."""


async def executar_aprovado(
    cliente: ClienteMCP,
    evento: dict[str, Any],
    contexto: dict[str, Any],
    decisao: DecisaoTriagem,
    revisao: RevisaoTriagem,
    aprovacao_humana: dict[str, Any] | None = None,
) -> dict[str, Any]:
    humano_aprovou = bool(
        aprovacao_humana
        and aprovacao_humana.get("aprovado") is True
        and aprovacao_humana.get("evento_id") == str(evento.get("id", ""))
        and aprovacao_humana.get("decidido_por")
        and aprovacao_humana.get("motivo")
    )
    exige_humano = (
        revisao.exige_humano
        or decisao.dado_sensivel_presente
        or decisao.risco_seguranca
        in {NivelRiscoSeguranca.ALTO, NivelRiscoSeguranca.CRITICO}
        or decisao.criticidade in {Criticidade.P0, Criticidade.P1}
        or decisao.necessita_aprovacao
    )
    if not revisao.aprovado or (exige_humano and not humano_aprovou):
        raise ErroExecucaoSegura(
            "Falta aprovação do Revisor ou a intervenção humana exigida."
        )
    evento_id = str(evento["id"])
    motivo = f"Executar ação aprovada pelo Revisor para {evento_id}"
    acao = revisao.acao_confirmada

    if acao is AcaoProposta.RESPONDER_FAQ:
        faq = next(
            (item for item in contexto.get("faq", [])
             if item.get("id") == decisao.faq_utilizada),
            None,
        )
        if not faq or not faq.get("resposta"):
            raise ErroExecucaoSegura("A FAQ aprovada não foi encontrada no contexto.")
        retorno = await cliente.responder_evento(
            evento_id=evento_id,
            mensagem=str(faq["resposta"]),
            agente="executor",
            motivo=motivo,
        )
        return {"status": "CONCLUIDO", "acao": acao, "retorno": retorno}

    if acao is AcaoProposta.SOLICITAR_INFORMACOES:
        faltantes = decisao.campos_ausentes
        if not faltantes:
            raise ErroExecucaoSegura("Não há campos ausentes a solicitar.")
        nomes = ", ".join(faltantes)
        retorno = await cliente.responder_evento(
            evento_id=evento_id,
            mensagem=f"Para encaminhar seu pedido, informe por favor: {nomes}.",
            agente="executor",
            motivo=motivo,
            aguardar_resposta=True,
        )
        return {"status": "CONCLUIDO", "acao": acao, "retorno": retorno}

    if acao in {AcaoProposta.ABRIR_CHAMADO, AcaoProposta.ENCAMINHAR_APROVACAO}:
        if not decisao.tipo_catalogo:
            raise ErroExecucaoSegura("A decisão não selecionou um tipo do catálogo.")
        tipo = next(
            (item for item in contexto.get("catalogo", [])
             if item.get("tipo") == decisao.tipo_catalogo),
            None,
        )
        if not tipo:
            raise ErroExecucaoSegura("O tipo aprovado não existe no catálogo.")
        campos = decisao.campos_extraidos
        obrigatorios = tipo.get("campos_obrigatorios", [])
        ausentes = [campo for campo in obrigatorios if not campos.get(campo)]
        if ausentes:
            raise ErroExecucaoSegura(
                "Campos obrigatórios ausentes: " + ", ".join(ausentes)
            )
        dados = {
            "tipo": decisao.tipo_catalogo,
            "time": tipo.get("time"),
            "solicitante": evento.get("de"),
            "resumo": str(evento.get("assunto", ""))[:300],
            "campos": campos,
            "status": (
                "aguardando aprovação"
                if acao is AcaoProposta.ENCAMINHAR_APROVACAO
                else "aberto"
            ),
            "aprovador": tipo.get("aprovacao"),
        }
        retorno = await cliente.registrar(
            base="chamados", dados=dados, evento_id=evento_id,
            agente="executor", motivo=motivo,
        )
        return {"status": "CONCLUIDO", "acao": acao, "retorno": retorno}

    if acao is AcaoProposta.ESCALAR_INCIDENTE:
        if decisao.criticidade not in {"P0", "P1", "P2"}:
            raise ErroExecucaoSegura("Incidente exige criticidade P0, P1 ou P2.")
        produto = decisao.campos_extraidos.get("produto")
        resumo = decisao.campos_extraidos.get("resumo") or evento.get("assunto")
        if not resumo:
            raise ErroExecucaoSegura("Incidente exige um resumo.")
        retorno = await cliente.registrar(
            base="incidentes",
            dados={
                "criticidade": decisao.criticidade,
                "produto": produto,
                "resumo": str(resumo),
                "status": "aberto",
            },
            evento_id=evento_id,
            agente="executor",
            motivo=motivo,
        )
        return {"status": "CONCLUIDO", "acao": acao, "retorno": retorno}

    if acao is AcaoProposta.NAO_AGIR:
        return {"status": "CONCLUIDO", "acao": acao, "retorno": "Nenhuma alteração necessária."}

    raise ErroExecucaoSegura(f"Ação ainda não implementada: {acao}")

