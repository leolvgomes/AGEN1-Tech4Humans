"""Testes unitários das políticas determinísticas de triagem."""

import pytest

from triagem_n1_agentes.modelos import (
    AcaoPermitida,
    Criticidade,
    EntradaPoliticaTriagem,
    ImpactoOperacional,
    NivelRiscoSeguranca,
)
from triagem_n1_agentes.politicas import avaliar_politicas


def test_urgencia_no_assunto_nao_define_criticidade() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="URGENTÍSSIMO - mouse parou",
        impacto=ImpactoOperacional.MINIMO,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is Criticidade.P4
    assert resultado.exige_incidente is False
    assert resultado.escalacao_imediata is False


def test_produto_fora_do_ar_para_todos_e_p0_com_escalacao_imediata() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="Indisponibilidade",
        impacto=ImpactoOperacional.PRODUTO_FORA_DO_AR_PARA_TODOS,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is Criticidade.P0
    assert resultado.exige_incidente is True
    assert resultado.escalacao_humana is True
    assert resultado.escalacao_imediata is True
    assert resultado.acoes_permitidas == [AcaoPermitida.ABRIR_INCIDENTE]


def test_funcao_importante_indisponivel_para_muitos_e_p1() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="Função indisponível",
        impacto=ImpactoOperacional.FUNCAO_IMPORTANTE_INDISPONIVEL_PARA_MUITOS,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is Criticidade.P1
    assert resultado.exige_incidente is True
    assert resultado.escalacao_humana is True
    assert resultado.escalacao_imediata is True


def test_dado_pessoal_sensivel_exige_escalacao_humana() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="Atestado com diagnóstico e CPF",
        impacto=ImpactoOperacional.LIMITADO,
        dado_pessoal_sensivel_presente=True,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is Criticidade.P3
    assert resultado.escalacao_humana is True
    assert resultado.escalacao_imediata is False


def test_risco_de_seguranca_exige_escalacao_humana() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="Possível incidente de segurança",
        impacto=ImpactoOperacional.LIMITADO,
        risco_seguranca=NivelRiscoSeguranca.BAIXO,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.escalacao_humana is True


def test_p2_exige_incidente() -> None:
    entrada = EntradaPoliticaTriagem(
        assunto="Impacto moderado",
        impacto=ImpactoOperacional.MODERADO,
    )

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is Criticidade.P2
    assert resultado.exige_incidente is True
    assert resultado.acoes_permitidas == [AcaoPermitida.ABRIR_INCIDENTE]


@pytest.mark.parametrize(
    ("impacto", "criticidade"),
    [
        (ImpactoOperacional.LIMITADO, Criticidade.P3),
        (ImpactoOperacional.MINIMO, Criticidade.P4),
    ],
)
def test_p3_e_p4_podem_virar_chamado_ou_resposta(
    impacto: ImpactoOperacional,
    criticidade: Criticidade,
) -> None:
    entrada = EntradaPoliticaTriagem(assunto="Solicitação", impacto=impacto)

    resultado = avaliar_politicas(entrada)

    assert resultado.criticidade is criticidade
    assert resultado.exige_incidente is False
    assert resultado.acoes_permitidas == [
        AcaoPermitida.ABRIR_CHAMADO,
        AcaoPermitida.RESPONDER,
    ]
