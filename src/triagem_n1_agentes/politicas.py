"""Políticas determinísticas de criticidade e segurança para triagem."""

from triagem_n1_agentes.modelos import (
    AcaoPermitida,
    Criticidade,
    EntradaPoliticaTriagem,
    ImpactoOperacional,
    NivelRiscoSeguranca,
    ResultadoPoliticaTriagem,
)


_CRITICIDADE_POR_IMPACTO = {
    ImpactoOperacional.PRODUTO_FORA_DO_AR_PARA_TODOS: Criticidade.P0,
    ImpactoOperacional.FUNCAO_IMPORTANTE_INDISPONIVEL_PARA_MUITOS: Criticidade.P1,
    ImpactoOperacional.MODERADO: Criticidade.P2,
    ImpactoOperacional.LIMITADO: Criticidade.P3,
    ImpactoOperacional.MINIMO: Criticidade.P4,
}


def avaliar_politicas(
    entrada: EntradaPoliticaTriagem,
) -> ResultadoPoliticaTriagem:
    """Determina criticidade, incidente e escalação sem executar ações."""
    criticidade = _CRITICIDADE_POR_IMPACTO[entrada.impacto]
    exige_incidente = criticidade in {
        Criticidade.P0,
        Criticidade.P1,
        Criticidade.P2,
    }
    escalacao_imediata = criticidade in {Criticidade.P0, Criticidade.P1}
    escalacao_humana = (
        escalacao_imediata
        or entrada.risco_seguranca is not NivelRiscoSeguranca.NENHUM
        or entrada.dado_pessoal_sensivel_presente
    )

    if exige_incidente:
        acoes_permitidas = [AcaoPermitida.ABRIR_INCIDENTE]
    else:
        acoes_permitidas = [
            AcaoPermitida.ABRIR_CHAMADO,
            AcaoPermitida.RESPONDER,
        ]

    return ResultadoPoliticaTriagem(
        criticidade=criticidade,
        exige_incidente=exige_incidente,
        escalacao_humana=escalacao_humana,
        escalacao_imediata=escalacao_imediata,
        acoes_permitidas=acoes_permitidas,
    )
