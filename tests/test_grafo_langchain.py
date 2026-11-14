import asyncio

from structlog.testing import capture_logs

from triagem_n1_agentes.grafo_langchain import criar_grafo
from triagem_n1_agentes.modelos import (
    AcaoProposta,
    CategoriaTriagem,
    Criticidade,
    DecisaoTriagem,
    NivelRiscoSeguranca,
    RevisaoTriagem,
)


class ModeloFalso:
    def __init__(self, resposta):
        self.resposta = resposta

    async def ainvoke(self, _entrada):
        return self.resposta


def decisao_vpn(**alteracoes):
    dados = {
        "evento": {"id": "tentativa-de-substituicao"},
        "categoria": CategoriaTriagem.DUVIDA,
        "tipo_catalogo": None,
        "criticidade": Criticidade.P4,
        "faq_utilizada": "FAQ-01",
        "campos_encontrados": [],
        "campos_ausentes": [],
        "possivel_duplicidade": False,
        "risco_seguranca": NivelRiscoSeguranca.NENHUM,
        "dado_sensivel_presente": False,
        "necessita_aprovacao": False,
        "acao_proposta": AcaoProposta.RESPONDER_FAQ,
        "justificativa": "Coberto pela FAQ-01.",
        "confianca": 0.99,
    }
    dados.update(alteracoes)
    return DecisaoTriagem(**dados)


def revisao_aprovada():
    return RevisaoTriagem(
        evento_id="id-inventado-pelo-modelo",
        aprovado=True,
        exige_humano=False,
        problemas=[],
        criticidade_confirmada=Criticidade.P4,
        acao_confirmada=AcaoProposta.RESPONDER_FAQ,
        justificativa="Resposta integralmente fundamentada.",
        confianca=0.99,
    )


def estado_inicial():
    return {
        "evento": {
            "id": "TESTE-001",
            "de": "pessoa@t4h.exemplo",
            "assunto": "VPN",
            "corpo": "Como acesso?",
        },
        "contexto": {"faq": [{"id": "FAQ-01"}]},
    }


def test_grafo_aprovado_chega_ao_executor_simulado():
    grafo = criar_grafo(
        ModeloFalso(decisao_vpn()),
        ModeloFalso(revisao_aprovada()),
    )

    with capture_logs() as logs:
        resultado = asyncio.run(grafo.ainvoke(estado_inicial()))

    assert resultado["decisao"].evento["id"] == "TESTE-001"
    assert resultado["revisao"].evento_id == "TESTE-001"
    assert resultado["resultado_execucao"]["status"] == "EXECUCAO_SIMULADA"
    chamadas = [
        log["agent"]
        for log in logs
        if log["event"] == "agent_call_started"
    ]
    assert chamadas == ["triador", "revisor", "executor"]


def test_politica_envia_dado_sensivel_para_humano():
    grafo = criar_grafo(
        ModeloFalso(decisao_vpn(dado_sensivel_presente=True)),
        ModeloFalso(revisao_aprovada()),
    )

    resultado = asyncio.run(grafo.ainvoke(estado_inicial()))

    assert resultado["exige_humano"] is True
    assert resultado["resultado_execucao"]["status"] == "AGUARDANDO_HUMANO"

