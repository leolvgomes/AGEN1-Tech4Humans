"""Testes da máquina de estados persistente do orquestrador."""

import asyncio

import pytest

from triagem_n1_agentes.modelos import EstadoOrquestracao
from triagem_n1_agentes.orquestrador import (
    EventoJaExecutado,
    FalhaRecuperavel,
    Orquestrador,
    TransicaoInvalida,
)


def preparar_evento_aprovado(orquestrador: Orquestrador, evento_id: str) -> None:
    orquestrador.registrar_evento(evento_id)
    orquestrador.transicionar(evento_id, EstadoOrquestracao.EM_ANALISE)
    orquestrador.transicionar(evento_id, EstadoOrquestracao.APROVADO)


def test_persiste_estado_e_historico_entre_instancias(tmp_path) -> None:
    caminho = tmp_path / "triagem.db"
    primeiro = Orquestrador(caminho)

    assert primeiro.registrar_evento("evento-1") is True
    assert primeiro.registrar_evento("evento-1") is False
    primeiro.transicionar("evento-1", EstadoOrquestracao.EM_ANALISE)

    segundo = Orquestrador(caminho)

    assert segundo.obter_estado("evento-1") is EstadoOrquestracao.EM_ANALISE
    historico = segundo.obter_historico("evento-1")
    assert [item.estado_novo for item in historico] == [
        EstadoOrquestracao.RECEBIDO,
        EstadoOrquestracao.EM_ANALISE,
    ]
    assert historico[0].estado_anterior is None


def test_transicao_invalida_nao_altera_estado_ou_historico(tmp_path) -> None:
    orquestrador = Orquestrador(tmp_path / "triagem.db")
    orquestrador.registrar_evento("evento-1")

    with pytest.raises(TransicaoInvalida):
        orquestrador.transicionar("evento-1", EstadoOrquestracao.APROVADO)

    assert orquestrador.obter_estado("evento-1") is EstadoOrquestracao.RECEBIDO
    assert len(orquestrador.obter_historico("evento-1")) == 1


def test_evento_so_e_executado_uma_vez(tmp_path) -> None:
    caminho = tmp_path / "triagem.db"
    orquestrador = Orquestrador(caminho)
    preparar_evento_aprovado(orquestrador, "evento-1")
    chamadas = []

    async def acao() -> str:
        chamadas.append("executada")
        return "ok"

    assert asyncio.run(orquestrador.executar_uma_vez("evento-1", acao)) == "ok"
    assert orquestrador.obter_estado("evento-1") is EstadoOrquestracao.CONCLUIDO

    orquestrador_reiniciado = Orquestrador(caminho)
    with pytest.raises(EventoJaExecutado):
        asyncio.run(orquestrador_reiniciado.executar_uma_vez("evento-1", acao))

    assert chamadas == ["executada"]
    assert orquestrador_reiniciado.obter_estado("evento-1") is (
        EstadoOrquestracao.CONCLUIDO
    )


def test_lote_continua_apos_falha_recuperavel(tmp_path) -> None:
    orquestrador = Orquestrador(tmp_path / "triagem.db")
    preparar_evento_aprovado(orquestrador, "evento-com-falha")
    preparar_evento_aprovado(orquestrador, "evento-seguinte")
    chamadas = []

    async def falhar_recuperavelmente() -> None:
        chamadas.append("falhou")
        raise FalhaRecuperavel("Serviço temporariamente indisponível.")

    async def concluir() -> None:
        chamadas.append("concluiu")

    resultados = asyncio.run(
        orquestrador.executar_lote(
            [
                ("evento-com-falha", falhar_recuperavelmente),
                ("evento-seguinte", concluir),
            ]
        )
    )

    assert chamadas == ["falhou", "concluiu"]
    assert [resultado.estado for resultado in resultados] == [
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.CONCLUIDO,
    ]
    assert resultados[0].erro == "Serviço temporariamente indisponível."
    assert orquestrador.obter_estado("evento-com-falha") is (
        EstadoOrquestracao.ERRO_RECUPERAVEL
    )
    assert orquestrador.obter_estado("evento-seguinte") is (
        EstadoOrquestracao.CONCLUIDO
    )


def test_falha_recuperavel_pode_reiniciar_analise_se_nao_houve_execucao(
    tmp_path,
) -> None:
    orquestrador = Orquestrador(tmp_path / "triagem.db")
    orquestrador.registrar_evento("evento-1")
    orquestrador.transicionar(
        "evento-1",
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        "Falha antes da execução.",
    )

    orquestrador.transicionar("evento-1", EstadoOrquestracao.EM_ANALISE)

    assert orquestrador.obter_estado("evento-1") is EstadoOrquestracao.EM_ANALISE


def test_falha_apos_reivindicar_execucao_nao_permite_repeticao(tmp_path) -> None:
    orquestrador = Orquestrador(tmp_path / "triagem.db")
    preparar_evento_aprovado(orquestrador, "evento-1")

    async def falhar() -> None:
        raise FalhaRecuperavel("Resultado externo incerto.")

    with pytest.raises(FalhaRecuperavel):
        asyncio.run(orquestrador.executar_uma_vez("evento-1", falhar))

    assert orquestrador.obter_estado("evento-1") is (
        EstadoOrquestracao.ERRO_RECUPERAVEL
    )

    with pytest.raises(EventoJaExecutado):
        asyncio.run(orquestrador.executar_uma_vez("evento-1", falhar))


def test_falha_nao_recuperavel_persiste_erro_final(tmp_path) -> None:
    orquestrador = Orquestrador(tmp_path / "triagem.db")
    preparar_evento_aprovado(orquestrador, "evento-1")

    async def falhar() -> None:
        raise ValueError("Falha inesperada.")

    with pytest.raises(ValueError, match="Falha inesperada"):
        asyncio.run(orquestrador.executar_uma_vez("evento-1", falhar))

    assert orquestrador.obter_estado("evento-1") is EstadoOrquestracao.ERRO_FINAL
    assert orquestrador.obter_historico("evento-1")[-1].detalhe == (
        "Falha inesperada."
    )
