"""Testes de validação do modelo de decisão de triagem."""

import pytest
from pydantic import ValidationError

from triagem_n1_agentes.modelos import (
    AcaoProposta,
    CategoriaTriagem,
    Criticidade,
    DecisaoTriagem,
    NivelRiscoSeguranca,
)


@pytest.fixture
def dados_decisao() -> dict:
    return {
        "evento": {"id": "evt-123", "assunto": "Acesso ao sistema"},
        "categoria": "solicitacao",
        "tipo_catalogo": "Acesso a sistema",
        "criticidade": "P2",
        "faq_utilizada": "faq-7",
        "campos_encontrados": ["sistema"],
        "campos_ausentes": ["justificativa"],
        "possivel_duplicidade": False,
        "risco_seguranca": "baixo",
        "dado_sensivel_presente": False,
        "necessita_aprovacao": True,
        "acao_proposta": "abrir_chamado",
        "justificativa": "O pedido corresponde a um tipo disponível no catálogo.",
        "confianca": 0.85,
    }


def test_decisao_triagem_valida_e_converte_enums(dados_decisao: dict) -> None:
    decisao = DecisaoTriagem.model_validate(dados_decisao)

    assert decisao.evento["id"] == "evt-123"
    assert decisao.categoria is CategoriaTriagem.SOLICITACAO
    assert decisao.criticidade is Criticidade.P2
    assert decisao.risco_seguranca is NivelRiscoSeguranca.BAIXO
    assert decisao.acao_proposta is AcaoProposta.ABRIR_CHAMADO
    assert decisao.campos_ausentes == ["justificativa"]


@pytest.mark.parametrize("criticidade", ["P0", "P1", "P2", "P3", "P4"])
def test_decisao_aceita_todos_os_niveis_de_criticidade(
    dados_decisao: dict,
    criticidade: str,
) -> None:
    dados_decisao["criticidade"] = criticidade

    assert DecisaoTriagem.model_validate(dados_decisao).criticidade.value == criticidade


@pytest.mark.parametrize("confianca", [0, 0.5, 1])
def test_decisao_aceita_limites_de_confianca(
    dados_decisao: dict,
    confianca: float,
) -> None:
    dados_decisao["confianca"] = confianca

    assert DecisaoTriagem.model_validate(dados_decisao).confianca == confianca


@pytest.mark.parametrize("confianca", [-0.01, 1.01])
def test_decisao_rejeita_confianca_fora_do_intervalo(
    dados_decisao: dict,
    confianca: float,
) -> None:
    dados_decisao["confianca"] = confianca

    with pytest.raises(ValidationError):
        DecisaoTriagem.model_validate(dados_decisao)


def test_decisao_rejeita_criticidade_invalida(dados_decisao: dict) -> None:
    dados_decisao["criticidade"] = "P5"

    with pytest.raises(ValidationError):
        DecisaoTriagem.model_validate(dados_decisao)
